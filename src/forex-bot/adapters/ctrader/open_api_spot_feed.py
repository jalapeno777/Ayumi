"""cTrader Open API Spot Feed — live price streaming via protobuf subscriptions.

Uses ``ctrader_open_api`` to subscribe to spot events (ProtoOASubscribeSpotsReq)
and emit ``Tick`` objects compatible with ``ForwardTestEngine``.

Symbol name normalization (canonical format):
    - Strip '/' and '_' characters, uppercase the result.
    - Example: "EUR/USD" → "EURUSD", "GBP_USD" → "GBPUSD"
    - Broker symbol names are normalized the same way for matching.

Threading model:
    - Twisted reactor managed by ReactorManager singleton (process-lifetime).
    - Never stopped — daemon thread dies with process.
"""

import logging
import random
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Optional

from twisted.internet import reactor
from ctrader_open_api import Client, TcpProtocol
from ctrader_open_api.protobuf import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAAccountAuthReq,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOASymbolsListReq,
    ProtoOASubscribeSpotsReq,
    ProtoOAUnsubscribeSpotsReq,
    ProtoOASymbolByIdReq,
)
from .market_data_feed import Tick, SymbolInfo, DEFAULT_SYMBOLS
from .reactor_manager import ReactorManager

logger = logging.getLogger("ayumi.openapi_spot_feed")

# Spread sanity threshold: 100 pips for forex majors (0.0100 for 5-digit pairs)
_MAX_SPREAD_PIPS = 100
_PIP_SIZE_5DIGIT = 0.0001
_MAX_RECONNECT_ATTEMPTS = 20
_INITIAL_RECONNECT_DELAY = 5.0
_MAX_RECONNECT_DELAY = 120.0
_STABLE_CONNECTION_SECONDS = 30  # connection must stay up this long before backoff resets


def _normalize_symbol_name(name: str) -> str:
    """Normalize symbol name: strip '/' and '_', uppercase.

    Canonical format: no separators, all uppercase.
    Example: "EUR/USD" → "EURUSD", "GBP_USD" → "GBPUSD".
    """
    return name.replace("/", "").replace("_", "").upper()


class OpenApiSpotFeed:
    """Live spot price feed via cTrader Open API protobuf subscriptions.

    Produces ``Tick`` objects compatible with ``ForwardTestEngine``.
    """

    def __init__(
        self,
        ctid_account_id: int,
        client_id: str,
        client_secret: str,
        access_token: str,
        host: str = "live.ctraderapi.com",
        port: int = 5035,
    ):
        self._ctid_account_id = ctid_account_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = access_token
        self._host = host
        self._port = port

        # Reactor lifecycle
        self._reactor_manager = ReactorManager()

        # Client instance
        self._client: Optional[Client] = None

        # State
        self._running: bool = False
        self._connected: threading.Event = threading.Event()
        self._authed: threading.Event = threading.Event()
        self._app_authed: threading.Event = threading.Event()
        self._symbols_loaded: threading.Event = threading.Event()
        self._lock = threading.Lock()

        # Symbol metadata
        self._symbols: dict[int, SymbolInfo] = {}
        self._name_to_id: dict[str, int] = {}  # normalized name → id
        self._id_to_name: dict[int, str] = {}  # id → original broker name
        self._symbol_digits: dict[int, int] = {}  # symbol_id → digits

        # Subscriptions
        self._subscribed_symbol_ids: set[int] = set()
        self._subscription_events: dict[int, threading.Event] = {}

        # Tick data
        self._ticks: dict[str, Tick] = {}  # symbol_name (normalized) → latest Tick
        self._ticks_by_id: dict[int, Tick] = {}  # symbol_id → latest Tick
        self._tick_callbacks: list[Callable[[Tick], None]] = []

        # Tick count tracking (Liora condition 4)
        self._tick_counts: dict[str, int] = {}  # normalized name → count

        # Reconnection state
        self._reconnect_attempts: int = 0
        self._reconnect_delay: float = _INITIAL_RECONNECT_DELAY
        self._connected_at: float | None = None  # timestamp of last successful connect
        self._stop_event: threading.Event = threading.Event()

    # --- Properties ---

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def symbols(self) -> dict[int, SymbolInfo]:
        return dict(self._symbols)

    @property
    def name_to_id(self) -> dict[str, int]:
        return dict(self._name_to_id)

    @property
    def ticks(self) -> dict[str, Tick]:
        with self._lock:
            return dict(self._ticks)

    @property
    def tick_counts(self) -> dict[str, int]:
        """Tick counts per normalized symbol name for validation (Liora #4)."""
        with self._lock:
            return dict(self._tick_counts)

    # --- Lifecycle ---

    def start(self, auto_subscribe: list[str] | None = None) -> bool:
        """Connect, authenticate, fetch symbol list, optionally subscribe."""
        if self._running:
            logger.warning("OpenApiSpotFeed already running")
            return True

        self._stop_event.clear()

        # Ensure shared reactor is running
        self._reactor_manager.ensure_running()

        # Create client and connect
        if not self._connect():
            return False

        if not self._auth():
            return False

        # Fetch symbol list via API, fall back to static mapping
        if not self._fetch_symbol_list():
            logger.warning("Symbol list API failed, using static fallback")
            self._populate_static_symbols()

        self._running = True

        if auto_subscribe:
            for symbol_name in auto_subscribe:
                if not self.subscribe(symbol_name):
                    logger.warning("Failed to auto-subscribe to %s", symbol_name)

        logger.info(
            "OpenApiSpotFeed started: account=%d symbols_loaded=%d",
            self._ctid_account_id,
            len(self._symbols),
        )
        return True

    def stop(self):
        """Unsubscribe all, disconnect client. Does NOT stop the reactor."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        # Unsubscribe all
        for symbol_id in list(self._subscribed_symbol_ids):
            self._unsubscribe_by_id(symbol_id)

        # Disconnect client
        if self._client:
            try:
                self._client.stopService()
            except Exception:
                pass
            self._client = None

        logger.info("OpenApiSpotFeed stopped")



    # --- Subscription ---

    def subscribe(self, symbol_name: str) -> bool:
        """Subscribe to spot events for a symbol. Resolves name→ID internally."""
        symbol_id = self._resolve_name_to_id(symbol_name)
        if symbol_id is None:
            logger.error("Cannot resolve symbol '%s' to ID", symbol_name)
            return False
        return self._subscribe_by_id(symbol_id)

    def unsubscribe(self, symbol_name: str) -> bool:
        """Unsubscribe from spot events."""
        symbol_id = self._resolve_name_to_id(symbol_name)
        if symbol_id is None:
            logger.error("Cannot resolve symbol '%s' to ID", symbol_name)
            return False
        return self._unsubscribe_by_id(symbol_id)

    def on_tick(self, callback: Callable[[Tick], None]):
        """Register a callback to be invoked on every new tick."""
        self._tick_callbacks.append(callback)

    def get_tick(self, symbol_name: str) -> Optional[Tick]:
        """Get the latest tick for a symbol (by name)."""
        normalized = _normalize_symbol_name(symbol_name)
        with self._lock:
            return self._ticks.get(normalized)

    def get_tick_by_id(self, symbol_id: int) -> Optional[Tick]:
        """Get the latest tick for a symbol (by ID)."""
        with self._lock:
            return self._ticks_by_id.get(symbol_id)

    def get_all_ticks(self) -> dict[str, Tick]:
        """Get all latest ticks."""
        with self._lock:
            return dict(self._ticks)

    def get_spread(self, symbol_name: str) -> Optional[float]:
        """Get the current spread for a symbol."""
        tick = self.get_tick(symbol_name)
        return tick.spread if tick else None

    # --- Internal: Connection & Auth ---

    def _connect(self) -> bool:
        """Create the Client and establish TCP connection."""
        self._connected.clear()
        self._client = Client(self._host, self._port, TcpProtocol)

        self._client.setConnectedCallback(self._on_connected)
        self._client.setDisconnectedCallback(self._on_disconnected)
        # Message callback set after auth in _auth()

        self._reactor_manager.ensure_running()
        reactor.callFromThread(self._client.startService)

        if not self._connected.wait(timeout=15):
            logger.error("Connection timeout")
            return False
        return True

    def _on_connected(self, client):
        """Callback: TCP connection established."""
        logger.info("Connected to %s:%d", self._host, self._port)
        self._connected_at = time.monotonic()
        self._connected.set()

    def _on_disconnected(self, client, reason):
        """Callback: TCP connection lost."""
        logger.warning("Disconnected: %s", reason)
        self._connected.clear()
        self._authed.clear()
        self._app_authed.clear()

        if self._running and not self._stop_event.is_set():
            self._schedule_reconnect()

    def _send_and_wait(self, message, timeout: float = 10):
        """Send a protobuf message and wait for response via Deferred (library pattern)."""
        event = threading.Event()
        result = [None]

        client_msg_id = f"{id(message)}_{time.monotonic()}"

        def on_success(proto_res):
            result[0] = proto_res
            event.set()

        def on_error(failure):
            logger.error("Send-and-wait failed: %s", failure)
            event.set()

        def do_send():
            d = self._client.send(message, clientMsgId=client_msg_id, responseTimeoutInSeconds=timeout)
            d.addCallbacks(on_success, on_error)

        reactor.callFromThread(do_send)

        if not event.wait(timeout=timeout + 5):
            logger.error("Send-and-wait timeout")
            return None
        return result[0]

    def _auth(self) -> bool:
        """Two-step authentication using the library's Deferred pattern."""
        # Step 1: Application auth
        app_res = self._send_and_wait(
            ProtoOAApplicationAuthReq(
                clientId=self._client_id,
                clientSecret=self._client_secret,
            ),
            timeout=10,
        )
        if app_res is None:
            logger.error("Application auth failed")
            return False
        logger.info("Application authenticated")

        # Step 2: Account auth
        acct_res = self._send_and_wait(
            ProtoOAAccountAuthReq(
                ctidTraderAccountId=self._ctid_account_id,
                accessToken=self._access_token,
            ),
            timeout=10,
        )
        if acct_res is None:
            logger.error("Account auth failed")
            return False
        logger.info("Account authenticated")

        # Now set persistent message callback for streaming events
        self._client.setMessageReceivedCallback(self._on_message)
        return True

    def _populate_static_symbols(self):
        """Fallback: populate symbol caches from known static mapping."""
        static = {
            1: ("EURUSD", 5),
            2: ("GBPUSD", 5),
            4: ("USDJPY", 3),
        }
        for symbol_id, (name, digits) in static.items():
            pip_size = 10 ** (-digits)
            info = SymbolInfo(
                symbol_id=symbol_id,
                name=name,
                pip_size=pip_size,
                digits=digits,
            )
            self._symbols[symbol_id] = info
            self._symbol_digits[symbol_id] = digits
            self._id_to_name[symbol_id] = name
            normalized = _normalize_symbol_name(name)
            self._name_to_id[normalized] = symbol_id
        logger.info("Loaded %d symbols from static fallback", len(self._symbols))
        self._symbols_loaded.set()

    def _fetch_symbol_list(self) -> bool:
        """Fetch all symbols via API using _send_and_wait, populate caches."""
        logger.info("Requesting symbol list for account %d", self._ctid_account_id)

        req = ProtoOASymbolsListReq()
        req.ctidTraderAccountId = self._ctid_account_id

        response = self._send_and_wait(req, timeout=15)
        if response is None:
            logger.error("Symbol list API returned no response")
            return False

        payload = Protobuf.extract(response)
        if payload is None:
            logger.error("Failed to extract symbol list payload")
            return False

        self._handle_symbol_list(payload)
        return len(self._name_to_id) > 0

    # --- Internal: Message Handling ---

    def _on_message(self, client, message):
        """Route incoming protobuf messages."""
        msg_type = message.payloadType
        logger.debug("Received message type=%d", msg_type)

        # Account auth response
        if msg_type == 2101:  # ProtoOAAccountAuthRes
            self._authed.set()
            logger.info("Account authenticated")

        # Symbol list response — handled by _send_and_wait, ignore here

        # Spot event
        elif msg_type == 2131:  # ProtoOASpotEvent
            payload = Protobuf.extract(message)
            self._handle_spot_event(payload)

        # Subscribe spots response
        elif msg_type == 2128:  # ProtoOASubscribeSpotsRes
            pass  # Subscription confirmed

        # Unsubscribe spots response
        elif msg_type == 2130:  # ProtoOAUnsubscribeSpotsRes
            pass

        # Error response
        elif msg_type == 2142:  # ProtoOAErrorRes
            payload = Protobuf.extract(message)
            self._handle_error(payload)

        # Application auth response
        elif msg_type == 2103:  # ProtoOAApplicationAuthRes
            self._app_authed.set()
            logger.info("Application authenticated")

        else:
            logger.debug("Unhandled message type: %d", msg_type)

    def _handle_symbol_list(self, message):
        """Process light symbol list response, populate name↔ID caches.

        ProtoOASymbolsListRes returns ProtoOALightSymbol entries which lack
        'digits'. We store name→ID mappings here and fetch full details
        (including digits) via ProtoOASymbolByIdReq when subscribing.
        """
        for sym in message.symbol:
            symbol_id = sym.symbolId
            name = sym.symbolName  # broker's name, e.g. "EUR/USD"

            self._id_to_name[symbol_id] = name

            # Normalized name mapping
            normalized = _normalize_symbol_name(name)
            self._name_to_id[normalized] = symbol_id

        logger.info(
            "Loaded %d symbol name mappings from API",
            len(self._name_to_id),
        )
        self._symbols_loaded.set()

    def _handle_spot_event(self, message):
        """Process a spot event into a Tick."""
        symbol_id = message.symbolId
        raw_bid = message.bid
        raw_ask = message.ask

        # Skip completely empty ticks (market closed)
        if raw_bid == 0 and raw_ask == 0:
            return

        # cTrader spot event prices use a FIXED 10^5 encoding regardless
        # of the symbol's 'digits' field. digits is for display only.
        divisor = 100_000
        bid = raw_bid / divisor
        ask = raw_ask / divisor

        logger.debug(
            "SpotEvent: symbol_id=%d raw_bid=%d raw_ask=%d divisor=100000 bid=%.5f ask=%.5f",
            symbol_id, raw_bid, raw_ask, bid, ask,
        )

        # Partial updates: bid=0 or ask=0 means only one side changed.
        # Use the last known price for the missing side.
        if raw_bid == 0 or raw_ask == 0:
            last_tick = self._ticks_by_id.get(symbol_id)
            if last_tick:
                if raw_bid == 0:
                    bid = last_tick.bid
                    logger.debug(
                        "Partial tick: using last bid=%.5f for symbol_id=%d",
                        bid, symbol_id,
                    )
                if raw_ask == 0:
                    ask = last_tick.ask
                    logger.debug(
                        "Partial tick: using last ask=%.5f for symbol_id=%d",
                        ask, symbol_id,
                    )
            else:
                # No prior tick for this symbol — skip partial update
                logger.debug(
                    "Skipping partial tick: no prior data for symbol_id=%d",
                    symbol_id,
                )
                return

        # Spread sanity check
        if bid >= ask:
            logger.debug(
                "Rejecting tick: bid >= ask (symbol_id=%d bid=%.5f ask=%.5f)",
                symbol_id, bid, ask,
            )
            return

        spread = ask - bid
        mid = (bid + ask) / 2
        max_spread = mid * 0.01
        if spread > max_spread:
            logger.debug(
                "Rejecting tick: spread too wide (symbol_id=%d spread=%.5f max=%.5f)",
                symbol_id, spread, max_spread,
            )
            return

        # Build Tick
        timestamp = datetime.fromtimestamp(message.timestamp / 1000, tz=timezone.utc)
        tick = Tick(symbol_id=symbol_id, bid=bid, ask=ask, timestamp=timestamp)

        # Resolve symbol name
        broker_name = self._id_to_name.get(symbol_id, str(symbol_id))
        normalized = _normalize_symbol_name(broker_name)

        with self._lock:
            self._ticks[normalized] = tick
            self._ticks_by_id[symbol_id] = tick
            self._tick_counts[normalized] = self._tick_counts.get(normalized, 0) + 1

        # Fire callbacks
        for callback in self._tick_callbacks:
            try:
                callback(tick)
            except Exception as exc:
                logger.error("Tick callback error: %s", exc, exc_info=True)

    def _handle_error(self, message):
        """Handle error responses, detect auth failures for token refresh."""
        error_code = getattr(message, "errorCode", "UNKNOWN")
        description = getattr(message, "description", "")
        logger.error("API error: %s — %s", error_code, description)

        # Detect auth failure — trigger token refresh (Kaito condition 2)
        auth_errors = {"CH_OAUTH_TOKEN_EXPIRED", "CH_INVALID_TOKEN"}
        if error_code in auth_errors:
            logger.info("Auth failure detected, attempting token refresh")
            self._refresh_token_and_reauth()

    def _refresh_token_and_reauth(self):
        """Refresh OAuth token and re-authenticate (Kaito condition 2).

        Pattern from ctrader_client.py._refresh_oauth_token().
        """
        try:
            import requests

            resp = requests.post(
                "https://openapi.ctrader.com/apps/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("errorCode"):
                logger.error("Token refresh failed: %s", data.get("description", ""))
                return

            self._access_token = data.get("accessToken") or data.get("access_token")
            # Note: refresh_token may also rotate
            new_refresh = data.get("refreshToken") or data.get("refresh_token")
            if new_refresh:
                self._refresh_token = new_refresh

            logger.info("OAuth token refreshed, re-authenticating")

            # Re-auth
            acct_auth_req = ProtoOAAccountAuthReq()
            acct_auth_req.ctidTraderAccountId = self._ctid_account_id
            acct_auth_req.accessToken = self._access_token
            reactor.callFromThread(self._safe_send, acct_auth_req)

        except Exception as exc:
            logger.error("Token refresh error: %s", exc, exc_info=True)

    # --- Internal: Subscription helpers ---

    def _safe_send(self, req):
        """Send a request, suppressing unhandled Deferred errors from library timeout."""
        try:
            d = self._client.send(req)
            d.addErrback(lambda f: logger.debug("Send response timeout (expected): %s", f))
        except Exception as exc:
            logger.debug("Send failed: %s", exc)

    def _subscribe_by_id(self, symbol_id: int) -> bool:
        """Send ProtoOASubscribeSpotsReq for a symbol."""
        # Fetch full symbol details (digits) if not already known
        if symbol_id not in self._symbol_digits:
            if not self._fetch_symbol_details(symbol_id):
                logger.warning(
                    "No digits for symbol_id=%d, will use default 5",
                    symbol_id,
                )

        req = ProtoOASubscribeSpotsReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.symbolId.append(symbol_id)

        reactor.callFromThread(self._safe_send, req)
        self._subscribed_symbol_ids.add(symbol_id)
        logger.info("Subscribed to spot events for symbol_id=%d", symbol_id)
        return True

    def _fetch_symbol_details(self, symbol_id: int) -> bool:
        """Fetch full symbol details via ProtoOASymbolByIdReq to get digits."""
        req = ProtoOASymbolByIdReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.symbolId.append(symbol_id)

        response = self._send_and_wait(req, timeout=10)
        if response is None:
            logger.error("Symbol details request failed for symbol_id=%d", symbol_id)
            return False

        payload = Protobuf.extract(response)
        if payload is None or not payload.symbol:
            logger.error("No symbol details in response for symbol_id=%d", symbol_id)
            return False

        sym = payload.symbol[0]
        digits = sym.digits
        name = self._id_to_name.get(symbol_id, str(symbol_id))
        pip_size = 10 ** (-digits)

        info = SymbolInfo(
            symbol_id=symbol_id,
            name=name,
            pip_size=pip_size,
            digits=digits,
        )
        self._symbols[symbol_id] = info
        self._symbol_digits[symbol_id] = digits

        logger.info(
            "Fetched symbol details: id=%d digits=%d",
            symbol_id, digits,
        )
        return True

    def _unsubscribe_by_id(self, symbol_id: int) -> bool:
        """Send ProtoOAUnsubscribeSpotsReq for a symbol."""
        if symbol_id not in self._subscribed_symbol_ids:
            return True

        req = ProtoOAUnsubscribeSpotsReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.symbolId.append(symbol_id)

        try:
            reactor.callFromThread(self._safe_send, req)
        except Exception:
            pass

        self._subscribed_symbol_ids.discard(symbol_id)
        logger.info("Unsubscribed from spot events for symbol_id=%d", symbol_id)
        return True

    def _resolve_name_to_id(self, symbol_name: str) -> Optional[int]:
        """Resolve a symbol name to its numeric ID using normalized lookup."""
        normalized = _normalize_symbol_name(symbol_name)
        return self._name_to_id.get(normalized)

    # --- Internal: Reconnection ---

    def _schedule_reconnect(self):
        """Schedule a reconnection attempt with exponential backoff + jitter."""
        if self._stop_event.is_set():
            return

        self._reconnect_attempts += 1

        if self._reconnect_attempts > _MAX_RECONNECT_ATTEMPTS:
            logger.critical(
                "Reconnect circuit-breaker tripped: %d attempts (max=%d)",
                self._reconnect_attempts,
                _MAX_RECONNECT_ATTEMPTS,
            )
            self._running = False
            return

        jitter = random.uniform(0, self._reconnect_delay * 0.3)
        delay = self._reconnect_delay + jitter
        self._reconnect_delay = min(self._reconnect_delay * 2, _MAX_RECONNECT_DELAY)

        logger.info(
            "Reconnect scheduled in %.1fs (attempt %d)",
            delay,
            self._reconnect_attempts,
        )

        timer = threading.Timer(delay, self._do_reconnect)
        timer.daemon = True
        timer.start()

    def _do_reconnect(self):
        """Execute a reconnection attempt."""
        if self._stop_event.is_set() or not self._running:
            return

        logger.info("Attempting reconnection...")

        # Disconnect old client
        if self._client:
            try:
                reactor.callFromThread(self._client.stopService)
            except Exception:
                pass

        if not self._connect():
            self._schedule_reconnect()
            return

        if not self._auth():
            self._schedule_reconnect()
            return

        # Re-subscribe to all previously subscribed symbols
        for symbol_id in list(self._subscribed_symbol_ids):
            self._subscribe_by_id(symbol_id)

        # Reset backoff only if connection was stable long enough
        if self._connected_at and (time.monotonic() - self._connected_at >= _STABLE_CONNECTION_SECONDS):
            self._reconnect_attempts = 0
            self._reconnect_delay = _INITIAL_RECONNECT_DELAY
            logger.info("Reconnection successful (stable)")
        else:
            logger.info("Reconnection successful (not yet stable — keeping backoff at %.1fs, attempt %d)",
                        self._reconnect_delay, self._reconnect_attempts)


