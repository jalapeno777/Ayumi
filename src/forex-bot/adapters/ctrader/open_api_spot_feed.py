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
import os
import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from twisted.internet import reactor
from twisted.application.internet import backoffPolicy
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
    ProtoOAAccountAuthRes,
    ProtoOANewOrderReq,
    ProtoOAClosePositionReq,
    ProtoOAAmendOrderReq,
    ProtoOACancelOrderReq,
    ProtoOAReconcileReq,
    ProtoOAAmendPositionSLTPReq,
    ProtoOAExecutionEvent,
    ProtoOAOrderErrorEvent,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATradeSide,
    ProtoOATimeInForce,
    ProtoOAExecutionType,
)
from .market_data_feed import Tick, SymbolInfo, DEFAULT_SYMBOLS
from .reactor_manager import ReactorManager
from .connection_state import ConnectionState, ConnectionStateManager
from .token_manager import TokenManager, TokenStatus
from .auth import CTraderAuth
from .models import (
    Order,
    OrderStatus,
    OrderType,
    Position,
    PositionStatus,
    TradeDirection,
)

logger = logging.getLogger("ayumi.openapi_spot_feed")

# Spread sanity threshold: 100 pips for forex majors (0.0100 for 5-digit pairs)
_MAX_SPREAD_PIPS = 100
_PIP_SIZE_5DIGIT = 0.0001

# Heartbeat monitoring thresholds (seconds)
_HEARTBEAT_DEGRADED_SEC = 35.0   # No heartbeat → DEGRADED
_HEARTBEAT_RECONNECT_SEC = 60.0  # No heartbeat → force reconnect

# Stale tick thresholds (seconds during market hours)
_STALE_TICK_WARN_SEC = 60.0      # No tick → log warning
_STALE_TICK_FREEZE_SEC = 120.0   # No tick → kill switch FREEZE
_APP_AUTH_RES_PAYLOAD_TYPE = 2101
_ACCT_AUTH_RES_PAYLOAD_TYPE = 2103
_ERROR_RES_PAYLOAD_TYPE = 2142
_EXECUTION_EVENT_PAYLOAD_TYPES = {2126, 2151}
_ORDER_ERROR_EVENT_PAYLOAD_TYPE = 2132
_ORDER_TIMEOUT_SEC = 10.0
_RECONCILE_TIMEOUT_SEC = 10.0


def _lots_to_units(lots: float) -> int:
    """Convert lots to cTrader units (1 standard lot = 100,000 units)."""
    return int(round(lots * 100_000))


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
        refresh_token: str | None = None,
        host: str = "live.ctraderapi.com",
        port: int = 5035,
    ):
        self._ctid_account_id = ctid_account_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = access_token
        self._refresh_token = refresh_token if refresh_token is not None else ""  # B2: callers should pass via CTraderAuth; no more .env reads here
        self._host = host
        self._port = port

        # TokenManager (BQ-681): lightweight wrapper for token lifecycle
        self._token_mgr = TokenManager(
            token_path=Path(__file__).resolve().parents[4] / "data" / "token_state.json",
            env_path=Path(__file__).resolve().parents[4] / ".env",
        )

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

        # Proactive token refresh (Kaito #2)
        # Store token expiry so we can proactively refresh before it expires.
        # _token_expires_at: Unix timestamp; refreshed at ~80% of token lifetime.
        self._token_expires_at: float | None = None
        self._refresh_timer: threading.Timer | None = None
        self._refresh_in_progress = False  # guard against concurrent refresh attempts
        self._refresh_lock = threading.Lock()

        # Auth error backoff & circuit breaker (B3)
        self._auth_error_count: int = 0
        self._auth_circuit_open: bool = False
        self._last_reactive_refresh_time: float = 0.0  # B2: cooldown between reactive refreshes
        self._last_successful_auth_time: float = 0.0   # B3: reset backoff after stable auth

        # ALREADY_LOGGED_IN rate counter (Amendment 1)
        self._already_logged_in_times: list[float] = []
        self._ALREADY_LOGGED_IN_WINDOW = 60.0  # seconds
        self._ALREADY_LOGGED_IN_THRESHOLD = 3

        # Reconnection state
        self._connected_at: float | None = None  # timestamp of last successful connect
        self._stop_event: threading.Event = threading.Event()
        self._reauth_in_progress: threading.Event = threading.Event()  # guard for reconnect_restore

        # ── Phase 1B: Connection Self-Healing ────────────────────────────────

        # Formal state machine (additive — informal flags kept as fallback)
        self._state_mgr = ConnectionStateManager(name="spot_feed")

        # Heartbeat monitoring
        self._last_heartbeat_recv: float = time.monotonic()  # last server heartbeat
        self._health_check_interval: float = 10.0  # how often to run health checks
        self._health_timer: threading.Timer | None = None

        # Stale tick detection
        self._last_tick_recv_monotonic: float = time.monotonic()

        # Reconnection tracking
        self._disconnect_at: float | None = None  # monotonic timestamp of disconnect
        self._on_reconnected_callbacks: list[Callable[[float], None]] = []

        # Kill switch reference (optional — set externally)
        self._kill_switch: Optional[object] = None

        # Order execution state
        self._pending_orders: dict[str, tuple[threading.Event, Order]] = {}
        self._pending_client_msg_ids: dict[str, str] = {}
        self._disconnected_pending_orders: list[Order] = []
        self._callbacks: dict[str, list[Callable]] = {
            "on_order_filled": [],
            "on_order_rejected": [],
            "on_order_cancelled": [],
        }
        self._callback_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="openapi-spot-callback",
        )

        # Market hours check: skip stale detection on weekends
        # Forex market opens ~Sunday 17:00 ET → Friday 17:00 ET

    def set_kill_switch(self, kill_switch) -> None:
        """Set the kill switch manager for FREEZE on FAILED state."""
        self._kill_switch = kill_switch

    def on_reconnected(self, callback: Callable[[float], None]) -> None:
        """Register a callback fired after successful reconnect.

        Callback signature: ``callback(outage_duration_sec: float)``
        """
        self._on_reconnected_callbacks.append(callback)

    @property
    def state_manager(self) -> ConnectionStateManager:
        """Expose the state manager for external health queries."""
        return self._state_mgr

    # --- Properties ---

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_connected(self) -> bool:
        return self._state_mgr.is_authenticated

    @property
    def is_paper_mode(self) -> bool:
        return False

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

    def get_health(self) -> dict:
        """B3: Health endpoint reflecting circuit breaker and state machine state."""
        return {
            "auth_circuit_open": self._auth_circuit_open,
            "auth_error_count": self._auth_error_count,
            "refresh_in_progress": self._refresh_in_progress,
            "connected": self._connected.is_set(),
            "authed": self._authed.is_set(),
            # Phase 1B: State machine status
            "state": self._state_mgr.state.value,
            "is_operational": self._state_mgr.is_operational,
            "last_heartbeat_age": time.monotonic() - self._last_heartbeat_recv,
            "last_tick_age": time.monotonic() - self._last_tick_recv_monotonic,
        }

    # --- Lifecycle ---

    def start(self, auto_subscribe: list[str] | None = None) -> bool:
        """Connect, authenticate, fetch symbol list, optionally subscribe."""
        if self._running:
            logger.warning("OpenApiSpotFeed already running")
            return True

        # Pre-flight: validate tokens are not placeholders or empty
        _PLACEHOLDER_VALUES = {"***", "new-access", "new-refresh", "", "none", "null", "todo", "changeme"}

        # BQ-681: TokenManager startup validation BEFORE preloader client creation (K-3)
        startup_status = self._token_mgr.validate_on_startup(self._access_token)
        if startup_status["status"] in (TokenStatus.PLACEHOLDER, TokenStatus.MISSING):
            logger.warning(
                "Token validation: %s — will attempt refresh on connect. %s",
                startup_status["status"], startup_status["message"],
            )
        elif startup_status["status"] == TokenStatus.EXPIRED:
            logger.critical(
                "STARTUP ABORTED: Token expired: %s",
                startup_status["message"],
            )
            return False
        if startup_status["status"] == TokenStatus.CRITICAL:
            logger.warning(
                "Token critical: %s — attempting proactive refresh before startup",
                startup_status["message"],
            )
            new_token = self._token_mgr.refresh_if_needed(
                self._client_id, self._client_secret, self._refresh_token, warning_days=0,
            )
            if new_token:
                self._access_token = new_token
                logger.info("Startup token refreshed successfully")
            else:
                logger.critical("Startup token refresh failed — aborting")
                return False
        elif startup_status["status"] == TokenStatus.WARNING:
            logger.warning("Token warning: %s", startup_status["message"])

        if not self._access_token or self._access_token.lower() in _PLACEHOLDER_VALUES:
            logger.warning(
                "CTRADER_OPENAPI_ACCESS_TOKEN is missing or placeholder — will attempt refresh on connect",
            )
        if not self._refresh_token or self._refresh_token.lower() in _PLACEHOLDER_VALUES:
            logger.warning(
                "CTRADER_OPENAPI_REFRESH_TOKEN is missing or placeholder — will attempt refresh on connect",
            )

        if getattr(self._callback_executor, "_shutdown", False):
            self._callback_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="openapi-spot-callback",
            )

        self._stop_event.clear()

        # Start the health check loop
        self._start_health_check()

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
            # Pre-fetch details for ALL symbols before subscribing any.
            # _subscribe_by_id() tries to fetch details lazily, but if that fails
            # the symbol is still subscribed without digits — causing USDJPY to
            # never enter the working symbol map. By fetching all first we avoid
            # racing between subscription and detail resolution.
            for symbol_name in auto_subscribe:
                symbol_id = self._resolve_name_to_id(symbol_name)
                if symbol_id is None:
                    logger.warning("Cannot resolve '%s' to a symbol ID — skipping", symbol_name)
                    continue
                if symbol_id not in self._symbol_digits:
                    logger.info("Pre-fetching details for %s (id=%d)", symbol_name, symbol_id)
                    self._fetch_symbol_details(symbol_id)

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

        # Cancel health check timer
        if self._health_timer is not None:
            self._health_timer.cancel()
            self._health_timer = None

        # Cancel any pending proactive refresh timer
        if self._refresh_timer is not None:
            self._refresh_timer.cancel()
            self._refresh_timer = None

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

        for _, (event, order) in list(self._pending_orders.items()):
            order.status = OrderStatus.PENDING
            order.comment = order.comment or "connection_lost_during_order"
            setattr(order, "reason", "connection_lost_during_order")
            event.set()
        self._pending_orders.clear()
        self._pending_client_msg_ids.clear()
        self._callback_executor.shutdown(wait=False, cancel_futures=True)

        logger.info("OpenApiSpotFeed stopped")



    # --- Subscription ---

    def subscribe(self, symbol_name: str) -> bool:
        """Subscribe to spot events for a symbol. Resolves name→ID internally."""
        symbol_id = self._resolve_name_to_id(symbol_name)
        if symbol_id is None:
            logger.error("Cannot resolve symbol '%s' to ID", symbol_name)
            return False
        return self._subscribe_by_id(symbol_id)

    def subscribe_spots(self, symbol_ids: list[int]) -> None:
        """Subscribe to spot events for already-resolved symbol IDs."""
        for symbol_id in symbol_ids:
            self._subscribe_by_id(symbol_id)

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

    def register_callback(self, event_name: str, fn: Callable) -> None:
        """Register an order-event callback."""
        callbacks = self._callbacks.setdefault(event_name, [])
        if fn not in callbacks:
            callbacks.append(fn)

    def _trigger_callback(self, event_name: str, *args) -> None:
        """Dispatch order callbacks off the reactor thread."""
        for callback in list(self._callbacks.get(event_name, [])):
            try:
                self._callback_executor.submit(callback, *args)
            except RuntimeError:
                logger.debug("Callback executor closed; dropping %s", event_name)
            except Exception as exc:
                logger.error("Callback dispatch error for %s: %s", event_name, exc)

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

    # ─── Trendbar (historical bars) ────────────────────────────────────────────

    def fetch_trendbars(
        self,
        symbol: str,
        period_minutes: int,
        count: int,
    ) -> list["Bar"]:
        """Fetch historical trendbars from cTrader and convert to Bar objects.

        Requires the feed to be connected and authenticated.

        Args:
            symbol: Symbol name (e.g. "EURUSD", "XAUUSD").
            period_minutes: Bar period in minutes. Must match cTrader periods:
                1, 2, 3, 4, 5, 6, 10, 15, 20, 30, 60, 120, 240, 360, 480, 720, 1440, 10080.
            count: Maximum number of bars to fetch.

        Returns:
            List of Bar objects (oldest first), or empty list on failure.
        """
        from backtest.engine import Bar
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq

        if not self._connected.is_set():
            logger.error("Cannot fetch trendbars: not connected")
            return []

        symbol_id = self._resolve_name_to_id(symbol)
        if symbol_id is None:
            logger.error("Cannot resolve symbol '%s' for trendbar fetch", symbol)
            return []

        # cTrader period enum mapping (minutes → ProtoOATrendbarPeriod enum index)
        PERIOD_MAP = {
            1: 1, 2: 2, 3: 3, 4: 4, 5: 5,  # M1–M5
            10: 6, 15: 7, 30: 8, 60: 9,  # M10, M15, M30, H1
            240: 10, 720: 11, 1440: 12, 10080: 13,  # H4, H12, D1, W1
        }
        period_enum = PERIOD_MAP.get(period_minutes)
        if period_enum is None:
            logger.error(
                "Unsupported trendbar period: %dm — supported: %s",
                period_minutes, sorted(PERIOD_MAP.keys()),
            )
            return []

        req = ProtoOAGetTrendbarsReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.symbolId = symbol_id
        req.period = period_enum
        req.count = count

        # Set time window (from now backwards)
        from datetime import datetime, timezone
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        req.toTimestamp = now_ms
        req.fromTimestamp = now_ms - (count * period_minutes * 60 * 1000)

        response = self._send_and_wait(req, timeout=15)
        if response is None:
            logger.error("Trendbar request failed for %s %dm", symbol, period_minutes)
            return []

        payload = Protobuf.extract(response)
        if payload is None:
            logger.error("Failed to extract trendbar payload")
            return []

        bars = []
        for tb in getattr(payload, 'trendbar', []):
            # ProtoOATrendbar uses delta encoding: low is base, others are deltas
            # timestamp is in unix minutes, not milliseconds
            utc_min = getattr(tb, 'utcTimestampInMinutes', 0)
            bar_time = datetime.fromtimestamp(utc_min * 60, tz=timezone.utc)
            vol = getattr(tb, 'volume', 0)
            digits = self._symbol_digits.get(symbol_id, 5)
            divisor = 10 ** digits

            low_raw = getattr(tb, 'low', 0)
            # OHLC encoded as low + delta, all divided by 100000 (fixed cTrader encoding)
            ctrader_divisor = 100000.0
            open_price = (low_raw + getattr(tb, 'deltaOpen', 0)) / ctrader_divisor
            high_price = (low_raw + getattr(tb, 'deltaHigh', 0)) / ctrader_divisor
            low_price = low_raw / ctrader_divisor
            close_price = (low_raw + getattr(tb, 'deltaClose', 0)) / ctrader_divisor

            bar = Bar(
                time=bar_time,
                open=round(open_price, digits),
                high=round(high_price, digits),
                low=round(low_price, digits),
                close=round(close_price, digits),
                volume=vol,
            )
            bars.append(bar)

        logger.info(
            "Fetched %d trendbars for %s %dm",
            len(bars), symbol, period_minutes,
        )
        return bars

    # --- Internal: Connection & Auth ---

    def _connect(self) -> bool:
        """Create the Client and establish TCP connection."""
        self._connected.clear()
        self._state_mgr.transition_to(
            ConnectionState.CONNECTING, reason="tcp_connect_initiated",
        )
        self._client = Client(
            self._host, self._port, TcpProtocol,
            # NOTE: No retryPolicy — we handle reconnection ourselves via
            # _on_disconnected -> state machine -> _reconnect_restore.
            # Using backoffPolicy creates a ClientService that conflicts
            # with other Client instances sharing the same Twisted reactor
            # (e.g., the pre-fetch bar client in launch_blend_forward_test.py).
        )

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
        self._last_heartbeat_recv = time.monotonic()
        self._state_mgr.transition_to(
            ConnectionState.CONNECTED, reason="tcp_connected",
        )

        # Spawn re-auth thread (handles RECONNECTS only).
        #
        # On the INITIAL connect, start() handles auth via _auth() in the
        # main thread. If we also spawned _reconnect_restore() here, both
        # paths would race on the same TCP connection — one would get
        # ALREADY_LOGGED_IN or time out. The previous "race patch" only
        # handled the narrow case where _reauth_in_progress happened to
        # still be set when _auth() ran, which is not the common case
        # (reconnect_restore typically completes in ~1s, well before
        # _auth() is invoked from the start() path).
        #
        # self._running is set to True by start() AFTER _auth() succeeds,
        # so it is False for the initial connect and True on every
        # reconnect. Use that as the gate.
        if not self._running:
            logger.debug("Initial connect — _auth() will handle auth, skipping reconnect_restore")
            return
        if not self._reauth_in_progress.is_set():
            self._reauth_in_progress.set()
            t = threading.Thread(target=self._reconnect_restore, daemon=True)
            t.start()

    def _on_disconnected(self, client, reason):
        """Callback: TCP connection lost."""
        logger.warning("Disconnected: %s", reason)
        self._connected.clear()
        self._authed.clear()
        self._app_authed.clear()
        self._reauth_in_progress.clear()  # allow next reconnect to attempt auth
        self._disconnect_at = time.monotonic()
        self._state_mgr.transition_to(
            ConnectionState.RECONNECTING,
            reason=f"disconnected: {reason}",
        )
        for _, (event, order) in list(self._pending_orders.items()):
            order.status = OrderStatus.PENDING
            order.comment = order.comment or "connection_lost_during_order"
            setattr(order, "reason", "connection_lost_during_order")
            event.set()
            self._disconnected_pending_orders.append(order)
        self._pending_orders.clear()
        self._pending_client_msg_ids.clear()

    def _send_and_wait(
        self,
        message,
        timeout: float = 10,
        *,
        prefix: str = "spot",
        clientMsgId: str | None = None,
    ):
        """Send a protobuf message and wait for response via Deferred (library pattern)."""
        event = threading.Event()
        result = [None]

        client_msg_id = clientMsgId or f"{prefix}_{uuid.uuid4().hex}"

        def on_success(proto_res):
            result[0] = proto_res
            event.set()

        def on_error(failure):
            logger.error("Send-and-wait failed: %s", failure)
            event.set()

        # Pass the raw protobuf message through. TcpProtocol.send() handles
        # wrapping in ProtoMessage. Pre-serialization was causing issues where
        # the wrapped message was subtly different from what cTrader expects.
        _pre_serialized = message

        def do_send():
            d = self._client.send(_pre_serialized, clientMsgId=client_msg_id, responseTimeoutInSeconds=timeout)
            d.addCallbacks(on_success, on_error)

        reactor.callFromThread(do_send)

        if not event.wait(timeout=timeout + 5):
            logger.error("Send-and-wait timeout")
            return None
        return result[0]

    def _auth(self) -> bool:
        """Two-step authentication using the library's Deferred pattern."""

        # If the reconnect_restore thread (triggered by _on_connected) is
        # already performing the initial auth, wait for it to finish instead
        # of racing a second auth request on the same connection.
        if self._reauth_in_progress.is_set():
            # Wait for the full auth (app + account) to complete via reconnect path.
            if self._authed.wait(timeout=20):
                logger.info("_auth: reconnect_restore already completed full auth")
                return True
            # App auth may have completed but account auth still pending.
            if self._app_authed.wait(timeout=15):
                logger.info("_auth: reconnect_restore completed app auth; doing account auth")
                # Fall through to do account auth only (below) — but we still
                # need to send a request, so let the normal path handle it.
            else:
                logger.error("_auth: timed out waiting for reconnect_restore app auth")
                return False

        # Step 1: Application auth
        self._state_mgr.transition_to(
            ConnectionState.APP_AUTHENTICATING, reason="app_auth_sending",
        )
        app_res = self._send_and_wait(
            ProtoOAApplicationAuthReq(
                clientId=self._client_id,
                clientSecret=self._client_secret,
            ),
            timeout=10,
        )
        if app_res is None or not self._is_expected_auth_response(
            app_res,
            expected_payload_type=_APP_AUTH_RES_PAYLOAD_TYPE,
            stage="app",
        ):
            logger.error("Application auth failed")
            self._handle_auth_failure("initial_app_auth")
            return False
        logger.info("Application authenticated")

        # Step 2: Account auth
        self._state_mgr.transition_to(
            ConnectionState.ACCT_AUTHENTICATING, reason="acct_auth_sending",
        )
        acct_res = self._send_and_wait(
            ProtoOAAccountAuthReq(
                ctidTraderAccountId=self._ctid_account_id,
                accessToken=self._access_token,
            ),
            timeout=10,
        )
        if acct_res is None or not self._is_expected_auth_response(
            acct_res,
            expected_payload_type=_ACCT_AUTH_RES_PAYLOAD_TYPE,
            stage="account",
        ):
            logger.error("Account auth failed")
            self._handle_auth_failure("initial_acct_auth")
            return False

        # Store token expiry from account auth response (ProtoOAAccountAuthRes)
        # so we can schedule a proactive refresh before the token expires.
        payload = Protobuf.extract(acct_res)
        expires_in = getattr(payload, 'expiresIn', None)
        if expires_in is not None and expires_in > 0:
            self._token_expires_at = time.monotonic() + expires_in
            logger.info("Token lifetime captured: %ds — scheduling proactive refresh at ~80%%", expires_in)
            self._schedule_proactive_refresh(expires_in)
        else:
            # Default to 24 hours if server didn't provide an expiry.
            # This is a safety net for demo/sandbox tokens where expiresIn may be absent.
            default_lifetime = 86400
            self._token_expires_at = time.monotonic() + default_lifetime
            logger.info("No token lifetime from server — defaulting to %ds", default_lifetime)
            self._schedule_proactive_refresh(default_lifetime)

        # BQ-681: Track token in TokenManager after successful auth
        self._token_mgr.track_token(self._access_token, expires_in or default_lifetime)

        logger.info("Account authenticated")

        self._state_mgr.transition_to(
            ConnectionState.AUTHENTICATED, reason="initial_auth_complete",
        )

        # Auto-clear stale kill switch on successful fresh auth.
        # If the kill switch was left in FREEZE from a previous crashed run,
        # and we just authenticated successfully, clear it — the freeze is stale.
        if self._kill_switch is not None:
            try:
                if self._kill_switch.is_active:
                    logger.info(
                        "Kill switch was active — clearing after successful auth (stale from previous run)",
                    )
                    self._kill_switch.deactivate(reason="auto_cleared_on_successful_auth")
            except Exception as exc:
                logger.warning("Failed to auto-clear kill switch: %s", exc)

        # Now set persistent message callback for streaming events
        self._client.setMessageReceivedCallback(self._on_message)
        return True

    def _is_expected_auth_response(
        self,
        response,
        expected_payload_type: int,
        stage: str,
    ) -> bool:
        """Validate that auth requests returned the expected success payload."""
        payload_type = getattr(response, "payloadType", None)
        if payload_type == expected_payload_type:
            return True
        if payload_type == _ERROR_RES_PAYLOAD_TYPE:
            try:
                payload = Protobuf.extract(response)
                error_code = getattr(payload, "errorCode", "UNKNOWN")
                description = getattr(payload, "description", "")
            except Exception as exc:
                error_code = "UNKNOWN"
                description = f"failed to parse error payload: {exc}"
            # ALREADY_LOGGED_IN means a concurrent reconnect_restore thread
            # already authenticated this client_id on this connection. The
            # auth is functionally complete — treat as success.
            if error_code == "ALREADY_LOGGED_IN" and self._app_authed.is_set():
                logger.info(
                    "%s auth: %s — concurrent auth already succeeded, accepting",
                    stage, error_code,
                )
                return True
            logger.error(
                "%s auth rejected: code=%s desc=%s",
                stage, error_code, description,
            )
            return False
        logger.error(
            "%s auth returned unexpected payloadType=%s",
            stage, payload_type,
        )
        return False

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

        # Update heartbeat timestamp on ANY incoming message (server is alive)
        self._last_heartbeat_recv = time.monotonic()

        # Account auth response
        if msg_type == 2101:  # ProtoOAAccountAuthRes
            self._authed.set()
            logger.info("Account authenticated")
            # B3: Reset auth error state on successful auth
            if self._auth_error_count > 0 or self._auth_circuit_open:
                logger.info(
                    "Auth recovered — resetting error_count (%d→0) and circuit_breaker (%s→False)",
                    self._auth_error_count, self._auth_circuit_open,
                )
            self._auth_error_count = 0
            self._auth_circuit_open = False
            self._last_successful_auth_time = time.monotonic()

        # Symbol list response — handled by _send_and_wait, ignore here

        # Spot event
        elif msg_type == 2131:  # ProtoOASpotEvent
            payload = Protobuf.extract(message)
            self._handle_spot_event(payload)

        # Execution event (payload type differs across cTrader docs/SDK builds)
        elif msg_type in _EXECUTION_EVENT_PAYLOAD_TYPES:
            payload = Protobuf.extract(message)
            self._handle_execution_event(payload)

        # Order-specific error event
        elif msg_type == _ORDER_ERROR_EVENT_PAYLOAD_TYPE:
            payload = Protobuf.extract(message)
            self._handle_order_error_event(payload, message)

        # Subscribe spots response
        elif msg_type == 2128:  # ProtoOASubscribeSpotsRes
            pass  # Subscription confirmed

        # Unsubscribe spots response
        elif msg_type == 2130:  # ProtoOAUnsubscribeSpotsRes
            pass

        # Error response
        elif msg_type == 2142:  # ProtoOAErrorRes
            payload = Protobuf.extract(message)
            if self._handle_pending_order_error(payload, message):
                return
            self._handle_error(payload)

        # Application auth response
        elif msg_type == 2103:  # ProtoOAApplicationAuthRes
            self._app_authed.set()
            logger.info("Application authenticated")

        else:
            logger.debug("Unhandled message type: %d", msg_type)

    def _handle_execution_event(self, message: ProtoOAExecutionEvent) -> None:
        order_payload = getattr(message, "order", None)
        client_order_id = getattr(order_payload, "clientOrderId", "") if order_payload else ""
        if not client_order_id or client_order_id not in self._pending_orders:
            return

        event, order = self._pending_orders.pop(client_order_id)
        self._drop_pending_client_msg_id(client_order_id)

        execution_type = getattr(message, "executionType", None)
        if execution_type == ProtoOAExecutionType.ORDER_CANCELLED:
            order.status = OrderStatus.CANCELLED
            setattr(order, "reason", "order_cancelled")
            event.set()
            self._trigger_callback("on_order_cancelled", order, message)
            return

        if execution_type == ProtoOAExecutionType.ORDER_REJECTED:
            reason = getattr(message, "errorCode", "") or "order_rejected"
            order.status = OrderStatus.REJECTED
            order.comment = reason
            setattr(order, "reason", reason)
            event.set()
            self._trigger_callback("on_order_rejected", order, message, reason)
            return

        order.status = OrderStatus.FILLED
        order.filled_at = datetime.utcnow()
        fill_price = (
            getattr(order_payload, "executionPrice", None)
            or getattr(getattr(message, "deal", None), "executionPrice", None)
            or getattr(getattr(message, "position", None), "price", None)
            or order.price
        )
        order.filled_price = fill_price
        executed_volume = getattr(order_payload, "executedVolume", 0)
        if executed_volume:
            order.volume = executed_volume / 100_000.0
        setattr(order, "reason", "order_filled")
        event.set()
        self._trigger_callback("on_order_filled", order, message)

    def _handle_order_error_event(
        self,
        message: ProtoOAOrderErrorEvent,
        envelope,
    ) -> None:
        self._handle_pending_order_error(message, envelope)

    def _handle_pending_order_error(self, message, envelope) -> bool:
        client_order_id = getattr(message, "clientOrderId", "")
        client_msg_id = getattr(envelope, "clientMsgId", "")
        if not client_order_id and client_msg_id:
            client_order_id = self._pending_client_msg_ids.get(client_msg_id, "")

        if not client_order_id or client_order_id not in self._pending_orders:
            return False

        event, order = self._pending_orders.pop(client_order_id)
        self._drop_pending_client_msg_id(client_order_id)
        error_code = getattr(message, "errorCode", "UNKNOWN")
        description = getattr(message, "description", "")
        reason = f"{error_code}: {description}".strip(": ")
        order.status = OrderStatus.REJECTED
        order.comment = reason
        setattr(order, "reason", reason)
        event.set()
        self._trigger_callback("on_order_rejected", order, message, reason)
        return True

    def _drop_pending_client_msg_id(self, request_id: str) -> None:
        for client_msg_id, pending_request_id in list(self._pending_client_msg_ids.items()):
            if pending_request_id == request_id:
                self._pending_client_msg_ids.pop(client_msg_id, None)

    def _handle_symbol_list(self, message):
        """Process light symbol list response, populate name↔ID caches.

        ProtoOASymbolsListRes returns ProtoOALightSymbol entries which lack
        'digits'. We store name→ID mappings here and fetch full details
        (including digits) via ProtoOASymbolByIdReq when subscribing.
        """
        # Guard: ProtoOAErrorRes (msg type 2142) has no 'symbol' attribute
        if not hasattr(message, 'symbol'):
            error_code = getattr(message, 'errorCode', 'UNKNOWN')
            description = getattr(message, 'description', '')
            logger.error(
                "Symbol list request failed with error: %s — %s",
                error_code,
                description,
            )
            return

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
        ts_raw = message.timestamp / 1000
        if ts_raw <= 0:
            ts_raw = datetime.now(timezone.utc).timestamp()
        timestamp = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
        tick = Tick(symbol_id=symbol_id, bid=bid, ask=ask, timestamp=timestamp)

        # Update stale tick tracker
        self._last_tick_recv_monotonic = time.monotonic()

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

        # B2: ALREADY_LOGGED_IN is NOT an auth error — session is still active.
        # Handle it explicitly: log, set authed event, and return without refresh.
        if error_code == "ALREADY_LOGGED_IN":
            logger.info("ALREADY_LOGGED_IN received — session is already active, no action needed")
            self._authed.set()

            # Amendment 1: rate counter for ALREADY_LOGGED_IN
            now = time.monotonic()
            self._already_logged_in_times = [
                t for t in self._already_logged_in_times
                if now - t < self._ALREADY_LOGGED_IN_WINDOW
            ]
            self._already_logged_in_times.append(now)
            if len(self._already_logged_in_times) > self._ALREADY_LOGGED_IN_THRESHOLD:
                logger.warning(
                    "ALREADY_LOGGED_IN fired %d times in %.0fs — possible duplicate instance. "
                    "Consider triggering reconnect.",
                    len(self._already_logged_in_times),
                    self._ALREADY_LOGGED_IN_WINDOW,
                )
            return

        # B3: Check circuit breaker before any reactive refresh
        if self._auth_circuit_open:
            logger.warning("Auth circuit breaker is OPEN — skipping reactive refresh")
            return

        # Amendment 3: Check _refresh_in_progress guard for reactive path too
        if self._refresh_in_progress:
            logger.debug("Refresh already in progress — skipping reactive refresh from error handler")
            return

        # Detect auth failure — trigger token refresh
        auth_errors = {
            "CH_OAUTH_TOKEN_EXPIRED",
            "CH_INVALID_TOKEN",
            "SESSION_EXPIRED",
        }
        if error_code in auth_errors:
            # B2: Cooldown — minimum 60s between reactive refresh attempts
            now = time.monotonic()
            since_last = now - self._last_reactive_refresh_time
            if since_last < 60.0:
                logger.info(
                    "Auth failure (error=%s) but reactive refresh cooldown active (%.1fs < 60s) — skipping",
                    error_code, since_last,
                )
                return

            logger.info("Auth failure detected (error=%s), attempting token refresh", error_code)
            self._last_reactive_refresh_time = now
            self._refresh_token_and_reauth()

    def _refresh_token_and_reauth(self, proactive: bool = False):
        """Refresh OAuth token and re-authenticate.

        Called in two scenarios:
        - Proactive: scheduled timer fires before token expiry (preferred path)
        - Reactive: error handler detects auth failure after the fact

        Args:
            proactive: True if this was a scheduled proactive refresh.
        """
        # B3: Check circuit breaker
        if not proactive and self._auth_circuit_open:
            logger.warning("Auth circuit breaker OPEN — refusing reactive refresh")
            return

        with self._refresh_lock:
            if self._refresh_in_progress:
                logger.debug("Refresh already in progress — skipping duplicate")
                return
            self._refresh_in_progress = True

        # B3: Exponential backoff for reactive refreshes
        if not proactive:
            backoff = min(10 * (2 ** self._auth_error_count), 300)
            logger.info(
                "Applying reactive refresh backoff: %.1fs (error_count=%d)",
                backoff, self._auth_error_count,
            )
            time.sleep(backoff)

        if not self._refresh_token:
            logger.error("Cannot refresh token: refresh_token is not set")
            self._refresh_in_progress = False
            self._auth_error_count += 1
            self._check_circuit_breaker()
            return

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
                self._auth_error_count += 1
                self._check_circuit_breaker()
                self._refresh_in_progress = False
                return

            new_access = data.get("accessToken") or data.get("access_token")
            new_refresh = data.get("refreshToken") or data.get("refresh_token")

            if not new_access:
                logger.error("Token refresh response missing accessToken")
                self._auth_error_count += 1
                self._check_circuit_breaker()
                self._refresh_in_progress = False
                return

            # Update tokens in memory
            self._access_token = new_access
            if new_refresh:
                self._refresh_token = new_refresh

            # Update expiry (ProtoOARefreshTokenRes includes expiresIn)
            expires_in = data.get("expiresIn") or data.get("expires_in")
            if expires_in is not None and expires_in > 0:
                self._token_expires_at = time.monotonic() + expires_in
                logger.info(
                    "Token refresh succeeded: new lifetime=%ds — rescheduling proactive refresh",
                    expires_in,
                )
                self._schedule_proactive_refresh(expires_in)
            else:
                # Preserve existing expiry / default if server didn't provide one
                default_lifetime = 86400
                if self._token_expires_at is None:
                    self._token_expires_at = time.monotonic() + default_lifetime
                logger.info("Token refresh succeeded — preserving expiry schedule")

            # Persist new tokens to .env so they survive restarts (Kaito #3)
            # BQ-681: Delegate to TokenManager for atomic .env writes + state tracking
            self._token_mgr.track_token(self._access_token, expires_in or default_lifetime)
            self._token_mgr._atomic_env_write(self._access_token, self._refresh_token)

            logger.info("OAuth token refreshed, re-authenticating")

            # Re-authenticate with new token
            acct_auth_req = ProtoOAAccountAuthReq()
            acct_auth_req.ctidTraderAccountId = self._ctid_account_id
            acct_auth_req.accessToken = self._access_token
            reactor.callFromThread(self._safe_send, acct_auth_req)

            # B3: Reset error count on successful token refresh (auth confirmation
            # happens asynchronously via _on_message → _authed.set())
            # We'll reset _auth_error_count when _authed fires (see _on_message).
            # For now, just clear the refresh_in_progress flag.

        except Exception as exc:
            logger.error("Token refresh error: %s", exc, exc_info=True)
            self._auth_error_count += 1
            self._check_circuit_breaker()
        finally:
            self._refresh_in_progress = False

    def _check_circuit_breaker(self):
        """B3: Check if auth error count exceeds threshold and escalate.

        Phase 1B: Now integrates with ConnectionStateManager:
        - Errors 3-4: transition to DEGRADED
        - Errors >=5: transition to FAILED, activate kill switch FREEZE
        """
        if self._auth_error_count >= 5:
            self._auth_circuit_open = True
            logger.critical(
                "Auth circuit breaker TRIPPED: %d consecutive failures — "
                "stopping all refresh attempts",
                self._auth_error_count,
            )
            # Phase 1B: Transition to FAILED and activate kill switch
            self._state_mgr.transition_to(
                ConnectionState.FAILED,
                reason=f"auth_errors_exceeded:{self._auth_error_count}",
            )
            self._activate_kill_switch_freeze(
                f"auth_failure:{self._auth_error_count}_errors",
            )
        elif self._auth_error_count >= 3:
            # Phase 1B: Transition to DEGRADED
            self._state_mgr.transition_to(
                ConnectionState.DEGRADED,
                reason=f"auth_errors_degraded:{self._auth_error_count}",
            )
            logger.warning(
                "Auth errors at %d — transitioning to DEGRADED",
                self._auth_error_count,
            )
        else:
            logger.warning(
                "Auth error count: %d/5 before circuit breaker",
                self._auth_error_count,
            )

    def _schedule_proactive_refresh(self, expires_in: int):
        """Schedule a proactive token refresh at ~80% of the token lifetime.

        Args:
            expires_in: Token lifetime in seconds (from expiresIn field).
        """
        # B3: Don't schedule if circuit breaker is open
        if self._auth_circuit_open:
            logger.warning("Circuit breaker is OPEN — not scheduling proactive refresh")
            return

        # Cancel any pending timer
        if self._refresh_timer is not None:
            self._refresh_timer.cancel()
            self._refresh_timer = None

        refresh_in = expires_in * 0.8  # refresh at 80% of lifetime
        # Minimum 60s to avoid scheduling a refresh in the past
        refresh_in = max(refresh_in, 60.0)

        logger.info(
            "Scheduling proactive token refresh in %.0fs (token lifetime=%ds)",
            refresh_in,
            expires_in,
        )
        self._refresh_timer = threading.Timer(refresh_in, self._proactive_refresh_task)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _proactive_refresh_task(self):
        """Timer callback: proactively refresh the OAuth token before it expires."""
        if not self._running:
            logger.debug("Proactive refresh skipped: feed not running")
            return
        logger.info("Proactive token refresh triggered — refreshing now")
        self._refresh_token_and_reauth(proactive=True)

    # BQ-681: _persist_tokens replaced by TokenManager._atomic_env_write()
    # The inline method is kept as a thin fallback for backward compatibility
    # if TokenManager is unavailable, but the feed now delegates to TokenManager.
    def _persist_tokens(self, access_token: str, refresh_token: str):
        """Write updated tokens to .env so they survive process restarts.

        DEPRECATED — use TokenManager._atomic_env_write() instead.
        Kept for backward compatibility.
        """
        if hasattr(self, "_token_mgr") and self._token_mgr is not None:
            self._token_mgr._atomic_env_write(access_token, refresh_token)
            return

        # Fallback inline implementation (non-atomic — should not be reached)
        env_path = Path(__file__).resolve().parents[4] / ".env"
        if not env_path.exists():
            logger.warning("Cannot persist tokens: .env not found at %s", env_path)
            return

        try:
            lines = env_path.read_text().splitlines()
            new_lines = []
            access_written = False
            refresh_written = False

            for line in lines:
                if line.startswith("CTRADER_OPENAPI_ACCESS_TOKEN="):
                    new_lines.append(f"CTRADER_OPENAPI_ACCESS_TOKEN={access_token}")
                    access_written = True
                elif line.startswith("CTRADER_OPENAPI_REFRESH_TOKEN="):
                    new_lines.append(f"CTRADER_OPENAPI_REFRESH_TOKEN={refresh_token}")
                    refresh_written = True
                else:
                    new_lines.append(line)

            if not access_written:
                new_lines.append(f"CTRADER_OPENAPI_ACCESS_TOKEN={access_token}")
            if not refresh_written:
                new_lines.append(f"CTRADER_OPENAPI_REFRESH_TOKEN={refresh_token}")

            env_path.write_text("\n".join(new_lines) + "\n")
            logger.info("Tokens persisted to %s", env_path)

        except Exception as exc:
            logger.error("Failed to persist tokens to .env: %s", exc, exc_info=True)

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
        req.subscribeToSpotTimestamp = True

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

    def resolve_symbol_id(self, name: str) -> int:
        """Resolve a symbol name to its numeric cTrader ID."""
        symbol_id = self._resolve_name_to_id(name)
        if symbol_id is None:
            raise ValueError(
                f"Symbol '{name}' not found in symbol map. "
                f"Known symbols: {sorted(self._name_to_id.keys())}"
            )
        return symbol_id

    # --- Order execution ---

    def _refresh_is_active(self) -> bool:
        if hasattr(self._refresh_in_progress, "is_set"):
            return self._refresh_in_progress.is_set()
        return bool(self._refresh_in_progress)

    def _symbol_name_for_id(self, symbol_id: int) -> str:
        return _normalize_symbol_name(self._id_to_name.get(symbol_id, str(symbol_id)))

    def _order_from_request(
        self,
        request_id: str,
        symbol_id: int,
        side: ProtoOATradeSide,
        volume: int,
        order_type: ProtoOAOrderType,
        price: float | None,
        sl: float | None,
        tp: float | None,
        comment: str,
    ) -> Order:
        return Order(
            order_id=request_id,
            symbol=self._symbol_name_for_id(symbol_id),
            direction=(
                TradeDirection.LONG
                if side == ProtoOATradeSide.BUY
                else TradeDirection.SHORT
            ),
            order_type=(
                OrderType.LIMIT
                if order_type == ProtoOAOrderType.LIMIT
                else OrderType.STOP
                if order_type == ProtoOAOrderType.STOP
                else OrderType.MARKET
            ),
            volume=volume / 100_000.0,
            price=price,
            stop_loss=sl,
            take_profit=tp,
            status=OrderStatus.PENDING,
            comment=comment,
        )

    def _send_order_message(self, message, client_msg_id: str, timeout: float) -> bool:
        if self._client is None:
            return False
        sent = threading.Event()
        ok = [False]

        def do_send():
            try:
                d = self._client.send(
                    message,
                    clientMsgId=client_msg_id,
                    responseTimeoutInSeconds=timeout,
                )
                d.addErrback(lambda failure: logger.debug("Order send errback: %s", failure))
                ok[0] = True
            except Exception as exc:
                logger.error("Order send failed: %s", exc)
            finally:
                sent.set()

        reactor.callFromThread(do_send)
        sent.wait(timeout=5)
        return ok[0]

    def new_order(
        self,
        symbol_id: int,
        side: ProtoOATradeSide,
        volume: int,
        *,
        order_type: ProtoOAOrderType = ProtoOAOrderType.MARKET,
        price: float | None = None,
        sl: float | None = None,
        tp: float | None = None,
        time_in_force: ProtoOATimeInForce = ProtoOATimeInForce.GOOD_TILL_CANCEL,
        comment: str = "",
        timeout: float = _ORDER_TIMEOUT_SEC,
    ) -> Order:
        request_id = uuid.uuid4().hex
        order = self._order_from_request(
            request_id, symbol_id, side, volume, order_type, price, sl, tp, comment,
        )

        if self._refresh_is_active():
            setattr(order, "reason", "refresh_in_progress")
            threading.Thread(target=self.reconcile, daemon=True).start()
            return order

        if not self._state_mgr.is_operational:
            setattr(order, "reason", "not_connected")
            return order

        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.symbolId = symbol_id
        req.orderType = order_type
        req.tradeSide = side
        req.volume = volume
        req.timeInForce = time_in_force
        req.clientOrderId = request_id
        if order_type == ProtoOAOrderType.LIMIT and price is not None:
            req.limitPrice = price
        elif order_type == ProtoOAOrderType.STOP and price is not None:
            req.stopPrice = price
        if sl is not None:
            req.stopLoss = sl
        if tp is not None:
            req.takeProfit = tp
        if comment:
            req.comment = comment

        event = threading.Event()
        client_msg_id = f"order_{uuid.uuid4().hex}"
        self._pending_orders[request_id] = (event, order)
        self._pending_client_msg_ids[client_msg_id] = request_id

        if not self._send_order_message(req, client_msg_id, timeout):
            self._pending_orders.pop(request_id, None)
            self._drop_pending_client_msg_id(request_id)
            order.status = OrderStatus.REJECTED
            order.comment = "send_failed"
            setattr(order, "reason", "send_failed")
            return order

        if not event.wait(timeout=timeout):
            if request_id in self._pending_orders:
                self._pending_orders.pop(request_id, None)
                self._drop_pending_client_msg_id(request_id)
                order.status = OrderStatus.PENDING
                order.comment = order.comment or "timeout_awaiting_event"
                setattr(order, "reason", "timeout_awaiting_event")
        return order

    def cancel_order(self, order_id: int, *, timeout: float = _ORDER_TIMEOUT_SEC) -> bool:
        req = ProtoOACancelOrderReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.orderId = order_id
        return self._send_and_wait(req, timeout=timeout, prefix="order") is not None

    def amend_order(
        self,
        order_id: int,
        *,
        price: float | None = None,
        sl: float | None = None,
        tp: float | None = None,
        timeout: float = _ORDER_TIMEOUT_SEC,
    ) -> bool:
        req = ProtoOAAmendOrderReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.orderId = order_id
        if price is not None:
            req.limitPrice = price
        if sl is not None:
            req.stopLoss = sl
        if tp is not None:
            req.takeProfit = tp
        return self._send_and_wait(req, timeout=timeout, prefix="order") is not None

    def amend_sl_tp(
        self,
        position_id: int,
        sl: float,
        tp: float,
        *,
        timeout: float = _ORDER_TIMEOUT_SEC,
    ) -> bool:
        req = ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.positionId = position_id
        req.stopLoss = sl
        req.takeProfit = tp
        return self._send_and_wait(req, timeout=timeout, prefix="order") is not None

    def close_position(
        self,
        position_id: int,
        volume: int,
        *,
        timeout: float = _ORDER_TIMEOUT_SEC,
    ) -> bool:
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.positionId = position_id
        req.volume = volume
        return self._send_and_wait(req, timeout=timeout, prefix="order") is not None

    def reconcile(self, timeout: float = _RECONCILE_TIMEOUT_SEC) -> list[Position]:
        if not self._state_mgr.is_operational:
            return []

        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self._ctid_account_id
        res = self._send_and_wait(req, timeout=timeout, prefix="qry")
        if res is None:
            return []

        payload = Protobuf.extract(res) if hasattr(res, "payloadType") else res
        positions: list[Position] = []
        for raw_position in getattr(payload, "position", []):
            try:
                trade_data = getattr(raw_position, "tradeData", None)
                symbol_id = getattr(trade_data, "symbolId", 0)
                trade_side = getattr(trade_data, "tradeSide", 0)
                volume = getattr(trade_data, "volume", 0) / 100_000.0
                price = getattr(raw_position, "price", 0.0)
                positions.append(
                    Position(
                        position_id=str(getattr(raw_position, "positionId", "")),
                        symbol=self._symbol_name_for_id(symbol_id),
                        direction=(
                            TradeDirection.LONG
                            if trade_side == ProtoOATradeSide.BUY
                            else TradeDirection.SHORT
                        ),
                        volume=volume,
                        entry_price=price,
                        current_price=price,
                        stop_loss=getattr(raw_position, "stopLoss", None) or None,
                        take_profit=getattr(raw_position, "takeProfit", None) or None,
                        status=PositionStatus.OPEN,
                    )
                )
            except Exception as exc:
                logger.warning("Reconcile parse error: %s", exc)
        return positions

    def send_order(
        self,
        symbol: str,
        direction: TradeDirection,
        order_type: OrderType,
        volume: float,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str = "",
    ) -> Order:
        symbol_id = self.resolve_symbol_id(symbol)
        trade_side = (
            ProtoOATradeSide.BUY
            if direction == TradeDirection.LONG
            else ProtoOATradeSide.SELL
        )
        proto_order_type = {
            OrderType.MARKET: ProtoOAOrderType.MARKET,
            OrderType.LIMIT: ProtoOAOrderType.LIMIT,
            OrderType.STOP: ProtoOAOrderType.STOP,
        }.get(order_type, ProtoOAOrderType.MARKET)
        return self.new_order(
            symbol_id=symbol_id,
            side=trade_side,
            volume=_lots_to_units(volume),
            order_type=proto_order_type,
            price=price,
            sl=stop_loss,
            tp=take_profit,
            comment=comment,
        )

    # --- Internal: Reconnection ---

    def _reconnect_restore(self):
        """Re-authenticate and re-subscribe after a TCP reconnect.

        Called in a daemon thread from _on_connected. Guarded by _reauth_in_progress
        to prevent concurrent re-auth attempts. On failure, Twisted's ClientService
        retryPolicy will handle TCP reconnection and _on_connected will fire again.
        """
        try:
            if not self._connected.is_set():
                logger.debug("_reconnect_restore: connection lost before auth started — aborting")
                return

            logger.info("Reconnect restore: starting re-authentication...")

            # Step 1: Application auth
            self._state_mgr.transition_to(
                ConnectionState.APP_AUTHENTICATING,
                reason="reconnect_app_auth",
            )
            app_res = self._send_and_wait(
                ProtoOAApplicationAuthReq(
                    clientId=self._client_id,
                    clientSecret=self._client_secret,
                ),
                timeout=10,
            )
            if app_res is None or not self._is_expected_auth_response(
                app_res,
                expected_payload_type=_APP_AUTH_RES_PAYLOAD_TYPE,
                stage="reconnect_app",
            ):
                logger.error("Reconnect restore: application auth failed")
                self._handle_auth_failure("reconnect_app_auth")
                return
            self._app_authed.set()
            logger.info("Reconnect restore: application authenticated")

            if not self._connected.is_set():
                logger.debug("_reconnect_restore: connection lost during app auth — aborting")
                return

            # Step 2: Account auth
            self._state_mgr.transition_to(
                ConnectionState.ACCT_AUTHENTICATING,
                reason="reconnect_acct_auth",
            )
            acct_res = self._send_and_wait(
                ProtoOAAccountAuthReq(
                    ctidTraderAccountId=self._ctid_account_id,
                    accessToken=self._access_token,
                ),
                timeout=10,
            )
            if acct_res is None or not self._is_expected_auth_response(
                acct_res,
                expected_payload_type=_ACCT_AUTH_RES_PAYLOAD_TYPE,
                stage="reconnect_account",
            ):
                logger.error("Reconnect restore: account auth failed")
                self._handle_auth_failure("reconnect_acct_auth")
                return
            self._authed.set()
            logger.info("Reconnect restore: account authenticated")

            # Persist message callback for streaming events
            self._client.setMessageReceivedCallback(self._on_message)

            if not self._connected.is_set():
                logger.debug("_reconnect_restore: connection lost during account auth — aborting")
                return

            # Step 3: Re-subscribe to all previously subscribed symbols
            symbol_ids = list(self._subscribed_symbol_ids)
            if symbol_ids:
                logger.info("Reconnect restore: re-subscribing to %d symbols", len(symbol_ids))
                for symbol_id in symbol_ids:
                    self._subscribe_by_id(symbol_id)

            # Schedule proactive token refresh if we know the expiry
            if self._token_expires_at is not None:
                remaining = self._token_expires_at - time.monotonic()
                if remaining > 60:
                    self._schedule_proactive_refresh(int(remaining))

            # Step 4: Transition to AUTHENTICATED and reconcile
            self._state_mgr.transition_to(
                ConnectionState.AUTHENTICATED,
                reason="reconnect_auth_complete",
            )

            positions = self.reconcile()
            self._resolve_disconnected_pending_orders(positions)

            # Fire reconciliation callbacks
            self._fire_reconnect_reconciliation()

            logger.info("Reconnect restore: completed successfully")

        except Exception as exc:
            logger.error("Reconnect restore failed: %s", exc, exc_info=True)
        finally:
            self._reauth_in_progress.clear()

    def _resolve_disconnected_pending_orders(self, positions: list[Position]) -> None:
        if not self._disconnected_pending_orders:
            return

        unresolved: list[Order] = []
        available_positions = list(positions)
        for order in self._disconnected_pending_orders:
            match = next(
                (
                    position
                    for position in available_positions
                    if position.symbol == order.symbol
                    and position.direction == order.direction
                    and abs(position.volume - order.volume) < 0.000001
                ),
                None,
            )
            if match is None:
                unresolved.append(order)
                continue
            available_positions.remove(match)
            order.status = OrderStatus.FILLED
            order.filled_at = datetime.utcnow()
            order.filled_price = match.entry_price
            setattr(order, "reason", "resolved_by_reconcile")
            self._trigger_callback("on_order_filled", order, match)

        self._disconnected_pending_orders = unresolved

    # ── Phase 1B: Health Monitoring & Self-Healing ────────────────────────────

    def _start_health_check(self) -> None:
        """Start the periodic health check timer."""
        if self._health_timer is not None:
            self._health_timer.cancel()
        self._health_timer = threading.Timer(
            self._health_check_interval, self._health_check_loop,
        )
        self._health_timer.daemon = True
        self._health_timer.start()

    def _health_check_loop(self) -> None:
        """Periodic health check: heartbeat, stale ticks, state transitions."""
        if not self._running:
            return

        try:
            self._check_heartbeat_health()
            self._check_stale_ticks()
        except Exception as exc:
            logger.error("Health check error: %s", exc, exc_info=True)

        # Schedule next check
        self._start_health_check()

    def _check_heartbeat_health(self) -> None:
        """Check if server heartbeats are arriving within thresholds.

        - No heartbeat for 35s → transition to DEGRADED, log warning
        - No heartbeat for 60s → transition to RECONNECTING, force disconnect + reconnect
        """
        # Only monitor when we expect to be connected
        current_state = self._state_mgr.state
        if current_state in (
            ConnectionState.DISCONNECTED,
            ConnectionState.CONNECTING,
            ConnectionState.RECONNECTING,
            ConnectionState.FAILED,
        ):
            return

        now = time.monotonic()
        elapsed = now - self._last_heartbeat_recv

        if elapsed >= _HEARTBEAT_RECONNECT_SEC:
            logger.warning(
                "No heartbeat for %.1fs (threshold: %.0fs) — forcing reconnect",
                elapsed, _HEARTBEAT_RECONNECT_SEC,
            )
            self._state_mgr.transition_to(
                ConnectionState.RECONNECTING,
                reason=f"heartbeat_timeout:{elapsed:.0f}s",
            )
            # Force disconnect to trigger Twisted's reconnect cycle
            if self._client:
                try:
                    reactor.callFromThread(self._client.stopService)
                except Exception:
                    pass

        elif elapsed >= _HEARTBEAT_DEGRADED_SEC:
            logger.warning(
                "No heartbeat for %.1fs (threshold: %.0fs) — transitioning to DEGRADED",
                elapsed, _HEARTBEAT_DEGRADED_SEC,
            )
            self._state_mgr.transition_to(
                ConnectionState.DEGRADED,
                reason=f"heartbeat_stale:{elapsed:.0f}s",
            )

    def _check_stale_ticks(self) -> None:
        """Detect stale ticks during market hours.

        - No tick for 60s during market hours → log warning
        - No tick for 120s during market hours → activate kill switch FREEZE
        - Skip on weekends (forex market closed)
        """
        # Only check when authenticated or degraded
        current_state = self._state_mgr.state
        if current_state not in (
            ConnectionState.AUTHENTICATED,
            ConnectionState.DEGRADED,
        ):
            return

        # Skip on weekends (Saturday=5, Sunday=6)
        now_dt = datetime.now(timezone.utc)
        if now_dt.weekday() >= 5:
            return

        now = time.monotonic()
        elapsed = now - self._last_tick_recv_monotonic

        if elapsed >= _STALE_TICK_FREEZE_SEC:
            logger.critical(
                "No ticks for %.1fs (threshold: %.0fs) — activating kill switch FREEZE",
                elapsed, _STALE_TICK_FREEZE_SEC,
            )
            self._activate_kill_switch_freeze(
                f"stale_ticks:{elapsed:.0f}s",
            )

        elif elapsed >= _STALE_TICK_WARN_SEC:
            logger.warning(
                "No ticks for %.1fs during market hours — data feed may be stale",
                elapsed,
            )

    def _is_market_hours(self) -> bool:
        """Check if forex market is likely open.

        Simple heuristic: not weekend (UTC). Real production would use
        session calendars, but this is sufficient for stale tick gating.
        """
        now_dt = datetime.now(timezone.utc)
        return now_dt.weekday() < 5  # Mon-Fri

    def _handle_auth_failure(self, context: str) -> None:
        """Handle an auth failure during initial or reconnect auth.

        Increments auth error count and triggers escalation via the
        circuit breaker.
        """
        self._auth_error_count += 1
        logger.error(
            "Auth failure in %s (error_count=%d)",
            context, self._auth_error_count,
        )
        self._check_circuit_breaker()

    def _activate_kill_switch_freeze(self, reason: str) -> None:
        """Activate kill switch FREEZE if a kill switch manager is registered."""
        if self._kill_switch is not None:
            try:
                self._kill_switch.activate_global_freeze(
                    reason=reason,
                    triggered_by="spot_feed_self_healing",
                )
                logger.critical("Kill switch FREEZE activated: %s", reason)
            except Exception as exc:
                logger.error(
                    "Failed to activate kill switch FREEZE: %s", exc,
                    exc_info=True,
                )
        else:
            logger.warning(
                "Kill switch FREEZE requested but no kill switch manager registered: %s",
                reason,
            )

    def _fire_reconnect_reconciliation(self) -> None:
        """Fire on_reconnected callbacks after a successful reconnect.

        Computes outage duration from _disconnect_at and notifies all
        registered callbacks. Does NOT replay missed signals.
        """
        if self._disconnect_at is None:
            logger.debug("Reconnect reconciliation: no disconnect_at recorded — skipping")
            return

        outage_duration = time.monotonic() - self._disconnect_at
        logger.warning(
            "Connection restored after %.1fs outage — firing reconciliation callbacks",
            outage_duration,
        )

        for callback in self._on_reconnected_callbacks:
            try:
                callback(outage_duration)
            except Exception as exc:
                logger.error(
                    "Reconciliation callback error: %s", exc, exc_info=True,
                )

        # Reset disconnect tracker
        self._disconnect_at = None
