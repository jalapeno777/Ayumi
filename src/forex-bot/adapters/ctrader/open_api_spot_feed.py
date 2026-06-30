"""cTrader Open API Spot Feed — orchestrator composing extracted modules.

Slim orchestrator that composes:
- ``CTraderConnection`` — TCP connect/disconnect, reconnection, health monitoring
- ``CTraderAuth`` — authentication (app + account level) [archived; re-exported via credential_store/token_lifecycle]
- ``BarBuilder`` — tick → OHLCV aggregation (used by ForwardTestEngine)

This module handles:
- Subscription management (symbol resolution, spot subscriptions)
- Tick routing (spot events → Tick objects → callbacks)
- Order execution (new, amend, cancel, close, reconcile)
- Token refresh lifecycle (proactive + reactive)
- Kill switch integration

Symbol name normalization (canonical format):
    Strip '/' and '_' characters, uppercase. Example: "EUR/USD" → "EURUSD".

Historical context (preserved for grep-ability and design intent):

BQ-1327 — dual-token-manager race condition fix. The orchestrator coordinates
a single ``TokenManager`` instance (see ``self._token_mgr``) and serializes
all token refreshes through ``self._refresh_lock``. Before this fix, the
auth shim and the spot feed each ran their own token refresh loop, racing on
the same refresh token and clobbering ``.env``. The fix consolidates refresh
into this orchestrator and exposes ``_handle_auth_failure`` /
``_check_circuit_breaker`` for the single-state auth-error escalation path.

BQ-1329 — concurrent-session conflict (second-app strategy). cTrader enforces
a single-session rule (one live TCP session per OpenAPI app). To run both
the live spot feed (``OpenApiSpotFeed``) and historical bar requests
(``CTraderOpenApiClient``) without one evicting the other, they authenticate
with separate OpenAPI apps: the spot feed uses ``CTRADER_OPENAPI_CLIENT_ID``
/ ``CTRADER_OPENAPI_CLIENT_SECRET`` (primary), while the historical client
uses ``CTRADER_TRADE_APP_ID`` / ``CTRADER_TRADE_SECRET`` (secondary). A fully
shared TCP socket was deferred because it requires invasive changes to the
archived feed implementation; the second-app approach is the Phase-5
pragmatic fallback.
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
from ctrader_open_api.protobuf import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASymbolsListReq,
    ProtoOASubscribeSpotsReq,
    ProtoOAUnsubscribeSpotsReq,
    ProtoOASymbolByIdReq,
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
from .market_data_feed import Tick, SymbolInfo
from .volume_calculator import VolumeCalculator
from .connection import CTraderConnection
from .auth_error_types import get_policy, AuthFaultType
from .connection_state import ConnectionState, ConnectionStateManager
from .token_manager import TokenManager, TokenStatus
from .token_lifecycle import TokenLifecycle
from .credential_store import CredentialStore
from .execution_permission import ExecutionPermissionPolicy
from .environment import (
    Environment,
    DEMO_HOSTS,
    LIVE_HOSTS,
    _infer_environment,
    validate_endpoint_environment,
    log_startup_environment,
)
from .models import (
    Order,
    OrderStatus,
    OrderType,
    Position,
    PositionStatus,
    TradeDirection,
)

logger = logging.getLogger("ayumi.openapi_spot_feed")

# Payload type constants
_APP_AUTH_RES_PAYLOAD_TYPE = 2101
_ACCT_AUTH_RES_PAYLOAD_TYPE = 2103
_ERROR_RES_PAYLOAD_TYPE = 2142
_EXECUTION_EVENT_PAYLOAD_TYPES = {2126, 2151}
_ORDER_ERROR_EVENT_PAYLOAD_TYPE = 2132
_ORDER_TIMEOUT_SEC = 10.0
_AMEND_TIMEOUT_SEC = 30.0  # SL/TP amends are not time-critical — use a longer timeout
_RECONCILE_TIMEOUT_SEC = 10.0

# Re-exported from connection.py for backward compatibility
from .connection import (
    _HEARTBEAT_DEGRADED_SEC,
    _HEARTBEAT_RECONNECT_SEC,
)
from .market_hours import is_forex_market_closed

# Stale tick thresholds (seconds during market hours)
_STALE_TICK_WARN_SEC = 60.0
_STALE_TICK_FREEZE_SEC = 120.0

# Error tier classification per BQ-1382 §6
_ERROR_TIERS = {
    # Tier 1: Transient — auto-reconnect
    "CH_OAUTH_TOKEN_EXPIRED": "transient",
    "CH_INVALID_TOKEN": "transient",
    "ALREADY_LOGGED_IN": "transient",
    "SESSION_EXPIRED": "transient",

    # Tier 2: Rate/Resource — back off
    "SERVER_BUSY": "rate_resource",
    "RATE_LIMIT_REACHED": "rate_resource",
    "CH_ACCOUNT_NOT_LOGGED_IN": "transient",

    # Tier 3: Critical — alert and halt
    "CH_PERMISSION_DENIED": "critical",
    "CH_SERVER_SECURITY_NOT_PASSED": "critical",
}


def _normalize_symbol_name(name: str) -> str:
    return name.replace("/", "").replace("_", "").upper()


def _lots_to_units(lots: float) -> int:
    """Deprecated — use VolumeCalculator.lots_to_volume() instead.

    Kept as a backward-compat alias for any external callers that haven't
    migrated yet. All internal call sites now go through VolumeCalculator.
    """
    return int(round(lots * 100_000))


class OpenApiSpotFeed:
    """Live spot price feed via cTrader Open API.

    Composes CTraderConnection (TCP), routes ticks to callbacks,
    and manages order execution.
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
        token_lifecycle: Optional["TokenLifecycle"] = None,
    ):
        self._ctid_account_id = ctid_account_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = access_token
        self._refresh_token = refresh_token or ""
        self._host = host
        self._port = port

        # TokenManager — DEPRECATED for OAuth operations.
        # OAuth refresh is owned by TokenLifecycle (self._token_lifecycle).
        # Do not add new OAuth calls here.
        self._token_mgr = TokenManager(
            token_path=Path(__file__).resolve().parents[3] / "data" / "token_state.json",
            env_path=Path(__file__).resolve().parents[3] / ".env",
        )

        # TokenLifecycle — the ONLY OAuth refresh owner.
        # If not passed by caller, lazily construct from .env.
        self._token_lifecycle: Optional[TokenLifecycle] = token_lifecycle

        # Connection (extracted module)
        self._state_mgr = ConnectionStateManager(name="spot_feed")
        self._conn = CTraderConnection(
            host, port, state_manager=self._state_mgr,
        )
        self._conn.on_connected(self._on_conn_connected)
        self._conn.on_disconnected(self._on_conn_disconnected)
        self._conn.on_feed_dead(self._on_conn_feed_dead)

        # State
        self._running: bool = False
        self._authed: threading.Event = threading.Event()
        self._app_authed: threading.Event = threading.Event()
        self._reauth_in_progress = threading.Event()
        self._lock = threading.Lock()

        # Symbol metadata
        self._symbols: dict[int, SymbolInfo] = {}
        self._name_to_id: dict[str, int] = {}
        self._id_to_name: dict[int, str] = {}
        self._symbol_digits: dict[int, int] = {}

        # Subscriptions
        self._subscribed_symbol_ids: set[int] = set()

        # Tick data
        self._ticks: dict[str, Tick] = {}
        self._ticks_by_id: dict[int, Tick] = {}
        self._tick_callbacks: list[Callable[[Tick], None]] = []
        self._tick_counts: dict[str, int] = {}
        self._last_tick_recv_monotonic: float = time.monotonic()

        # Token refresh state
        self._token_expires_at: float | None = None
        self._refresh_timer: threading.Timer | None = None
        self._refresh_in_progress = False
        self._refresh_lock = threading.Lock()
        self._auth_error_count: int = 0
        self._auth_circuit_open: bool = False
        self._last_reactive_refresh_time: float = 0.0
        self._last_successful_auth_time: float = 0.0

        # Reconnection state
        self._connected_at: float | None = None
        self._disconnect_at: float | None = None
        self._on_reconnected_callbacks: list[Callable[[float], None]] = []

        # Kill switch
        self._kill_switch: Optional[object] = None
        self._permission_policy: Optional[ExecutionPermissionPolicy] = None

        # Order execution
        self._pending_orders: dict[str, tuple[threading.Event, Order]] = {}
        self._pending_client_msg_ids: dict[str, str] = {}
        self._disconnected_pending_orders: list[Order] = []
        self._callbacks: dict[str, list[Callable]] = {
            "on_order_filled": [],
            "on_order_rejected": [],
            "on_order_cancelled": [],
        }
        self._callback_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="openapi-spot-callback",
        )

        # Volume conversion (per-symbol, replaces hardcoded 100_000)
        self._volume_calc = VolumeCalculator(self._symbols)

    # ── Properties ─────────────────────────────────────────────────────────

    def set_kill_switch(self, kill_switch) -> None:
        self._kill_switch = kill_switch

    def set_permission_policy(self, policy: ExecutionPermissionPolicy) -> None:
        self._permission_policy = policy

    def validate_wiring(self) -> None:
        """Validate that required production dependencies are wired.

        Called by ForwardTestEngine after construction, NOT in __init__.
        This allows tests to construct OpenApiSpotFeed without a full
        TokenLifecycle while ensuring production paths can't forget it.
        """
        if self._token_lifecycle is None:
            raise RuntimeError(
                "OpenApiSpotFeed.validate_wiring(): token_lifecycle is None. "
                "Production runtime requires a TokenLifecycle instance for OAuth refresh delegation. "
                "Pass token_lifecycle=<TokenLifecycle> when constructing for live/demo use."
            )
        logger.info(
            "[Startup] refresh_owner=TokenLifecycle wired=%s",
            self._token_lifecycle is not None,
        )

    def on_reconnected(self, callback: Callable[[float], None]) -> None:
        self._on_reconnected_callbacks.append(callback)

    @property
    def state_manager(self) -> ConnectionStateManager:
        return self._state_mgr

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
    def connection(self):
        """Expose the underlying CTraderConnection for account queries (balance, positions)."""
        return self._conn

    @property
    def ctid_account_id(self) -> int:
        """Expose the cTrader account ID for account-state queries."""
        return self._ctid_account_id

    @property
    def ticks(self) -> dict[str, Tick]:
        with self._lock:
            return dict(self._ticks)

    @property
    def tick_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._tick_counts)

    def lots_to_volume(self, symbol_id: int, lots: float) -> int:
        """Public accessor for VolumeCalculator — used by Task 4 consumers."""
        return self._volume_calc.lots_to_volume(symbol_id, lots)

    def get_health(self) -> dict:
        now = time.monotonic()
        heartbeat_age = now - self._conn._last_heartbeat_recv if self._conn._last_heartbeat_recv else None
        return {
            "auth_circuit_open": self._auth_circuit_open,
            "auth_error_count": self._auth_error_count,
            "refresh_in_progress": self._refresh_in_progress,
            "connected": self._conn.is_connected,
            "authed": self._authed.is_set(),
            "state": self._state_mgr.state.value,
            "is_operational": self._state_mgr.is_operational,
            "last_tick_age": now - self._last_tick_recv_monotonic,
            "last_heartbeat_age": heartbeat_age if heartbeat_age is not None else 999,
        }

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self, auto_subscribe: list[str] | None = None) -> bool:
        if self._running:
            return True

        # Environment validation — cross-check endpoint vs configured environment.
        _env = _infer_environment(self._host)
        try:
            validate_endpoint_environment(self._host, _env)
        except ValueError as e:
            logger.critical("%s", e)
            raise  # Fail closed — do not connect

        log_startup_environment(
            env=_env,
            host=self._host,
            account_id=str(self._ctid_account_id),
            kill_switch_active=True,  # kill switch is always "active" conceptually
            kill_switch_mode="freeze",
        )

        logger.info(
            "[Startup Diagnostics] environment=%s endpoint=%s account=%s "
            "refresh_owner=%s execution_mode=%s kill_switch=%s",
            _env.value,
            self._host,
            self._ctid_account_id,
            "TokenLifecycle" if self._token_lifecycle is not None else "NONE",
            "live" if getattr(self, '_is_live', False) else "demo",
            "preserved",  # don't read kill switch state here — just note it's checked
        )

        # Token validation — placeholder check only.
        # TokenLifecycle.ensure_valid() (called by ForwardTestEngine) handles
        # OAuth refresh. We keep a lightweight placeholder guard here.
        _PLACEHOLDER_VALUES = {"***", "new-access", "new-refresh", "", "none", "null", "todo", "changeme"}
        if self._access_token.lower() in _PLACEHOLDER_VALUES:
            logger.critical("STARTUP ABORTED: Access token is a placeholder")
            return False
        if self._refresh_token.lower() in _PLACEHOLDER_VALUES:
            logger.critical("STARTUP ABORTED: Refresh token is a placeholder")
            return False

        if getattr(self._callback_executor, "_shutdown", False):
            self._callback_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="openapi-spot-callback",
            )

        # Connect via CTraderConnection
        if not self._conn.connect():
            return False

        # Authenticate
        if not self._auth():
            return False

        # Fetch symbols
        if not self._fetch_symbol_list():
            logger.warning("Symbol list API failed, using static fallback")
            self._populate_static_symbols()

        self._running = True
        self._conn.start_health_monitor()

        if auto_subscribe:
            for symbol_name in auto_subscribe:
                symbol_id = self._resolve_name_to_id(symbol_name)
                if symbol_id is None:
                    logger.warning("Cannot resolve '%s' — skipping", symbol_name)
                    continue
                if symbol_id not in self._symbol_digits:
                    self._fetch_symbol_details(symbol_id)
            for symbol_name in auto_subscribe:
                if not self.subscribe(symbol_name):
                    logger.warning("Failed to auto-subscribe to %s", symbol_name)

        logger.info("OpenApiSpotFeed started: account=%d symbols=%d", self._ctid_account_id, len(self._symbols))
        return True

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._conn.stop_health_monitor()
        self._conn.disconnect()

        for symbol_id in list(self._subscribed_symbol_ids):
            self._unsubscribe_by_id(symbol_id)

        for _, (event, order) in list(self._pending_orders.items()):
            order.status = OrderStatus.PENDING
            order.comment = order.comment or "connection_lost_during_order"
            setattr(order, "reason", "connection_lost_during_order")
            event.set()
        self._pending_orders.clear()
        self._pending_client_msg_ids.clear()
        self._callback_executor.shutdown(wait=False, cancel_futures=True)

        if self._refresh_timer is not None:
            self._refresh_timer.cancel()
            self._refresh_timer = None

        logger.info("OpenApiSpotFeed stopped")

    # ── Connection callbacks (from CTraderConnection) ──────────────────────

    def _on_conn_connected(self, conn: CTraderConnection) -> None:
        self._connected_at = time.monotonic()
        # On reconnect (not initial), spawn re-auth thread
        if self._running and not self._reauth_in_progress.is_set():
            self._reauth_in_progress.set()
            t = threading.Thread(target=self._reconnect_restore, daemon=True)
            t.start()

    def _on_conn_disconnected(self, conn: CTraderConnection, reason) -> None:
        self._authed.clear()
        self._app_authed.clear()
        self._reauth_in_progress.clear()
        self._disconnect_at = time.monotonic()

        for _, (event, order) in list(self._pending_orders.items()):
            order.status = OrderStatus.PENDING
            order.comment = order.comment or "connection_lost_during_order"
            setattr(order, "reason", "connection_lost_during_order")
            event.set()
            self._disconnected_pending_orders.append(order)
        self._pending_orders.clear()
        self._pending_client_msg_ids.clear()

    def _on_conn_feed_dead(self, conn: CTraderConnection) -> None:
        """CTraderConnection exhausted reconnect attempts — escalate."""
        if is_forex_market_closed():
            logger.debug("Feed dead during market close — not activating kill switch")
            return
        logger.critical("Feed declared dead by CTraderConnection — activating kill switch")
        self._activate_kill_switch_freeze("feed_dead:reconnect_exhausted")

    # ── Authentication ─────────────────────────────────────────────────────

    def _auth(self) -> bool:
        if self._reauth_in_progress.is_set():
            if self._authed.wait(timeout=20):
                return True
            if self._app_authed.wait(timeout=15):
                pass  # fall through to account auth
            else:
                return False

        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq,
        )

        # App auth
        self._state_mgr.transition_to(ConnectionState.APP_AUTHENTICATING, reason="app_auth_sending")
        app_res = self._conn.send_and_wait(
            ProtoOAApplicationAuthReq(clientId=self._client_id, clientSecret=self._client_secret),
            timeout=10,
        )
        if app_res is None or not self._is_expected_auth_response(app_res, _APP_AUTH_RES_PAYLOAD_TYPE, "app"):
            self._handle_auth_failure("initial_app_auth")
            return False

        # Account auth
        self._state_mgr.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="acct_auth_sending")
        acct_res = self._conn.send_and_wait(
            ProtoOAAccountAuthReq(ctidTraderAccountId=self._ctid_account_id, accessToken=self._access_token),
            timeout=10,
        )
        if acct_res is None or not self._is_expected_auth_response(acct_res, _ACCT_AUTH_RES_PAYLOAD_TYPE, "account"):
            self._handle_auth_failure("initial_acct_auth")
            return False

        # Track token expiry
        payload = Protobuf.extract(acct_res)
        expires_in = getattr(payload, 'expiresIn', None) or 86400
        if expires_in and expires_in > 0:
            self._token_expires_at = time.monotonic() + expires_in
            self._schedule_proactive_refresh(expires_in)
        # Token tracking is handled by TokenLifecycle/CredentialStore.
        # The old self._token_mgr.track_token() call is removed (BQ-1327 no-op).

        self._state_mgr.transition_to(ConnectionState.AUTHENTICATED, reason="initial_auth_complete")
        self._set_message_callback()
        self._auto_clear_kill_switch()
        return True

    def _is_expected_auth_response(self, response, expected_payload_type: int, stage: str) -> bool:
        payload_type = getattr(response, "payloadType", None)
        if payload_type == expected_payload_type:
            return True
        if payload_type == _ERROR_RES_PAYLOAD_TYPE:
            payload = Protobuf.extract(response)
            error_code = getattr(payload, "errorCode", "UNKNOWN")
            if error_code == "ALREADY_LOGGED_IN" and self._app_authed.is_set():
                return True
            logger.error("%s auth rejected: %s", stage, error_code)
            return False
        return False

    def _set_message_callback(self) -> None:
        client = self._conn.client
        if client:
            client.setMessageReceivedCallback(self._on_message)

    def _auto_clear_kill_switch(self) -> None:
        if self._kill_switch is not None:
            try:
                if self._kill_switch.is_active:
                    self._kill_switch.deactivate(reason="auto_cleared_on_successful_auth")
            except Exception:
                pass

    # ── Message routing ────────────────────────────────────────────────────

    def _on_message(self, client, message):
        msg_type = message.payloadType
        self._conn.notify_heartbeat()

        # Diagnostic: log all non-heartbeat message types
        if msg_type not in (2131,):
            logger.debug("[MSG] payloadType=%s pending_orders=%d", msg_type, len(self._pending_orders))

        if msg_type == 2101:
            self._authed.set()
            self._auth_error_count = 0
            self._auth_circuit_open = False
            self._last_successful_auth_time = time.monotonic()
        elif msg_type == 2131:
            self._handle_spot_event(Protobuf.extract(message))
        elif msg_type in _EXECUTION_EVENT_PAYLOAD_TYPES:
            self._handle_execution_event(Protobuf.extract(message), message)
        elif msg_type == _ORDER_ERROR_EVENT_PAYLOAD_TYPE:
            self._handle_order_error_event(Protobuf.extract(message), message)
        elif msg_type == 2142:
            payload = Protobuf.extract(message)
            if not self._handle_pending_order_error(payload, message):
                self._handle_error(payload)
        elif msg_type == 2103:
            self._app_authed.set()
        elif msg_type in (2128, 2130):
            pass

    def _handle_spot_event(self, message) -> None:
        if message is None:
            return
        symbol_id = message.symbolId
        raw_bid, raw_ask = message.bid, message.ask
        if raw_bid == 0 and raw_ask == 0:
            return

        digits = self._symbol_digits.get(symbol_id, 5)
        if symbol_id not in self._symbol_digits:
            logger.warning("Tick decode: no digits for symbol_id=%s, using default 5", symbol_id)
        divisor = 10 ** digits
        bid, ask = raw_bid / divisor, raw_ask / divisor

        if raw_bid == 0 or raw_ask == 0:
            last = self._ticks_by_id.get(symbol_id)
            if last:
                bid = last.bid if raw_bid == 0 else bid
                ask = last.ask if raw_ask == 0 else ask
            else:
                return

        if bid >= ask or (ask - bid) > ((bid + ask) / 2) * 0.01:
            return

        ts_raw = message.timestamp / 1000
        timestamp = datetime.fromtimestamp(ts_raw if ts_raw > 0 else datetime.now(timezone.utc).timestamp(), tz=timezone.utc)
        tick = Tick(symbol_id=symbol_id, bid=bid, ask=ask, timestamp=timestamp)

        self._last_tick_recv_monotonic = time.monotonic()
        broker_name = self._id_to_name.get(symbol_id, str(symbol_id))
        normalized = _normalize_symbol_name(broker_name)

        with self._lock:
            self._ticks[normalized] = tick
            self._ticks_by_id[symbol_id] = tick
            self._tick_counts[normalized] = self._tick_counts.get(normalized, 0) + 1

        for cb in self._tick_callbacks:
            try:
                cb(tick)
            except Exception as exc:
                logger.error("Tick callback error: %s", exc)

    # ── Subscription ───────────────────────────────────────────────────────

    def subscribe(self, symbol_name: str) -> bool:
        symbol_id = self._resolve_name_to_id(symbol_name)
        return self._subscribe_by_id(symbol_id) if symbol_id else False

    def unsubscribe(self, symbol_name: str) -> bool:
        symbol_id = self._resolve_name_to_id(symbol_name)
        return self._unsubscribe_by_id(symbol_id) if symbol_id else False

    def on_tick(self, callback: Callable[[Tick], None]):
        self._tick_callbacks.append(callback)

    def register_callback(self, event_name: str, fn: Callable) -> None:
        # Dedupe: if the same function is already registered for this event,
        # don't append a second copy. Without this, multiple orders sharing
        # the same callback function cause the callback to fire repeatedly
        # for each subsequent registration.
        existing = self._callbacks.setdefault(event_name, [])
        if fn not in existing:
            existing.append(fn)

    def _trigger_callback(self, event_name: str, *args) -> None:
        for cb in list(self._callbacks.get(event_name, [])):
            try:
                self._callback_executor.submit(cb, *args)
            except RuntimeError:
                pass

    def get_tick(self, symbol_name: str) -> Optional[Tick]:
        with self._lock:
            return self._ticks.get(_normalize_symbol_name(symbol_name))

    def get_tick_by_id(self, symbol_id: int) -> Optional[Tick]:
        with self._lock:
            return self._ticks_by_id.get(symbol_id)

    def get_all_ticks(self) -> dict[str, Tick]:
        with self._lock:
            return dict(self._ticks)

    def get_spread(self, symbol_name: str) -> Optional[float]:
        tick = self.get_tick(symbol_name)
        return tick.spread if tick else None

    def _subscribe_by_id(self, symbol_id: int) -> bool:
        if symbol_id not in self._symbol_digits:
            self._fetch_symbol_details(symbol_id)
        req = ProtoOASubscribeSpotsReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.symbolId.append(symbol_id)
        req.subscribeToSpotTimestamp = True
        reactor.callFromThread(self._conn.send, req)
        self._subscribed_symbol_ids.add(symbol_id)
        return True

    def _unsubscribe_by_id(self, symbol_id: int) -> bool:
        if symbol_id not in self._subscribed_symbol_ids:
            return True
        req = ProtoOAUnsubscribeSpotsReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.symbolId.append(symbol_id)
        try:
            reactor.callFromThread(self._conn.send, req)
        except Exception:
            pass
        self._subscribed_symbol_ids.discard(symbol_id)
        return True

    # ── Symbol management ──────────────────────────────────────────────────

    def _resolve_name_to_id(self, name: str) -> Optional[int]:
        return self._name_to_id.get(_normalize_symbol_name(name))

    def resolve_symbol_id(self, name: str) -> int:
        sid = self._resolve_name_to_id(name)
        if sid is None:
            raise ValueError(f"Symbol '{name}' not found. Known: {sorted(self._name_to_id.keys())}")
        return sid

    def _fetch_symbol_list(self) -> bool:
        req = ProtoOASymbolsListReq()
        req.ctidTraderAccountId = self._ctid_account_id
        response = self._conn.send_and_wait(req, timeout=15)
        if response is None:
            return False
        payload = Protobuf.extract(response)
        if payload is None or not hasattr(payload, 'symbol'):
            return False
        for sym in payload.symbol:
            self._id_to_name[sym.symbolId] = sym.symbolName
            self._name_to_id[_normalize_symbol_name(sym.symbolName)] = sym.symbolId
        return len(self._name_to_id) > 0

    def _fetch_symbol_details(self, symbol_id: int) -> bool:
        req = ProtoOASymbolByIdReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.symbolId.append(symbol_id)
        response = self._conn.send_and_wait(req, timeout=10)
        if response is None:
            return False
        payload = Protobuf.extract(response)
        if payload is None or not payload.symbol:
            return False
        sym = payload.symbol[0]
        self._symbols[symbol_id] = SymbolInfo(
            symbol_id=symbol_id,
            name=self._id_to_name.get(symbol_id, str(symbol_id)),
            pip_size=10 ** (-sym.digits),
            digits=sym.digits,
            lot_size=sym.lotSize if sym.lotSize else 100_000,
            min_volume=sym.minVolume if sym.minVolume else 0,
            max_volume=sym.maxVolume if sym.maxVolume else 0,
            step_volume=sym.stepVolume if sym.stepVolume else 1,
        )
        self._symbol_digits[symbol_id] = sym.digits
        return True

    def _populate_static_symbols(self):
        for sid, (name, digits) in {1: ("EURUSD", 5), 2: ("GBPUSD", 5), 4: ("USDJPY", 3)}.items():
            self._symbols[sid] = SymbolInfo(sid, name, 10 ** (-digits), digits, lot_size=100_000)
            self._symbol_digits[sid] = digits
            self._id_to_name[sid] = name
            self._name_to_id[_normalize_symbol_name(name)] = sid

    # ── Trendbars / Historical Bars ────────────────────────────────────────

    def fetch_historical_bars(self, symbol: str, timeframe: str, count: int) -> list:
        """Fetch historical bars through the existing authenticated connection.

        Single-connection replacement for CTraderOpenApiClient.get_trendbars().
        Uses the same TCP session that powers spot ticks and order execution.

        Args:
            symbol: Normalized symbol name, e.g. "GBPUSD"
            timeframe: "M15", "H1", etc. (same codes as CTraderOpenApiClient)
            count: Number of bars to fetch

        Returns list of Bar objects.
        """
        _TF_MAP = {"M1": 1, "M5": 5, "M15": 15, "M30": 30,
                   "H1": 60, "H4": 240, "D1": 1440}
        period_minutes = _TF_MAP.get(timeframe.upper())
        if period_minutes is None:
            raise ValueError(f"Unknown timeframe '{timeframe}'. Valid: {list(_TF_MAP.keys())}")
        return self.fetch_trendbars(symbol, period_minutes, count)

    def fetch_trendbars(self, symbol: str, period_minutes: int, count: int) -> list:
        from backtest.engine import Bar
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq

        if not self._conn.is_connected:
            return []
        symbol_id = self._resolve_name_to_id(symbol)
        if symbol_id is None:
            return []

        PERIOD_MAP = {1:1, 2:2, 3:3, 4:4, 5:5, 10:6, 15:7, 30:8, 60:9, 240:10, 720:11, 1440:12, 10080:13}
        period_enum = PERIOD_MAP.get(period_minutes)
        if period_enum is None:
            return []

        req = ProtoOAGetTrendbarsReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.symbolId = symbol_id
        req.period = period_enum
        req.count = count
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        req.toTimestamp = now_ms
        req.fromTimestamp = now_ms - (count * period_minutes * 60 * 1000)

        response = self._conn.send_and_wait(req, timeout=15)
        if response is None:
            return []
        payload = Protobuf.extract(response)
        if payload is None:
            return []

        bars = []
        for tb in getattr(payload, 'trendbar', []):
            bar_time = datetime.fromtimestamp(getattr(tb, 'utcTimestampInMinutes', 0) * 60, tz=timezone.utc)
            low_raw = getattr(tb, 'low', 0)
            d = float(10 ** self._symbol_digits.get(symbol_id, 5))
            bars.append(Bar(
                time=bar_time,
                open=round((low_raw + getattr(tb, 'deltaOpen', 0)) / d, 5),
                high=round((low_raw + getattr(tb, 'deltaHigh', 0)) / d, 5),
                low=round(low_raw / d, 5),
                close=round((low_raw + getattr(tb, 'deltaClose', 0)) / d, 5),
                volume=getattr(tb, 'volume', 0),
            ))
        return bars

    # ── Order execution ────────────────────────────────────────────────────

    def _symbol_name_for_id(self, symbol_id: int) -> str:
        return _normalize_symbol_name(self._id_to_name.get(symbol_id, str(symbol_id)))

    def _round_price(self, symbol_id, value):
        """Round a price value to the symbol's allowed decimal places.

        cTrader rejects orders whose SL/TP/limit/stop prices exceed the
        symbol's digit precision (e.g. 5 digits for EURUSD, 3 for USDJPY).
        This prevents INVALID_REQUEST rejections from floating-point noise.
        """
        if value is None:
            return None
        digits = self._symbol_digits.get(symbol_id, 5)
        return round(float(value), digits)

    def new_order(self, symbol_id, side, volume, *, order_type=ProtoOAOrderType.MARKET,
                  price=None, sl=None, tp=None,
                  time_in_force=ProtoOATimeInForce.GOOD_TILL_CANCEL,
                  comment="", timeout=_ORDER_TIMEOUT_SEC) -> Order:
        # P5A: defense-in-depth permission check. Must block before any broker
        # mutation or reactor dispatch.
        if self._permission_policy is not None:
            allowed, reason = self._permission_policy.can_send_order()
            if not allowed:
                logger.warning("Order blocked by permission policy: %s", reason)
                request_id = uuid.uuid4().hex
                order = Order(
                    order_id=request_id,
                    symbol=self._symbol_name_for_id(symbol_id),
                    direction=TradeDirection.LONG if side == ProtoOATradeSide.BUY else TradeDirection.SHORT,
                    order_type={ProtoOAOrderType.LIMIT: OrderType.LIMIT, ProtoOAOrderType.STOP: OrderType.STOP}.get(order_type, OrderType.MARKET),
                    volume=self._volume_calc.volume_to_lots(symbol_id, volume), price=price, stop_loss=sl, take_profit=tp,
                    status=OrderStatus.REJECTED, comment=comment,
                )
                setattr(order, "reason", reason)
                return order

        request_id = uuid.uuid4().hex
        order = Order(
            order_id=request_id,
            symbol=self._symbol_name_for_id(symbol_id),
            direction=TradeDirection.LONG if side == ProtoOATradeSide.BUY else TradeDirection.SHORT,
            order_type={ProtoOAOrderType.LIMIT: OrderType.LIMIT, ProtoOAOrderType.STOP: OrderType.STOP}.get(order_type, OrderType.MARKET),
            volume=self._volume_calc.volume_to_lots(symbol_id, volume), price=price, stop_loss=sl, take_profit=tp,
            status=OrderStatus.PENDING, comment=comment,
        )
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
        price = self._round_price(symbol_id, price)
        sl = self._round_price(symbol_id, sl)
        tp = self._round_price(symbol_id, tp)
        if order_type == ProtoOAOrderType.LIMIT and price is not None:
            req.limitPrice = price
        elif order_type == ProtoOAOrderType.STOP and price is not None:
            req.stopPrice = price
        if sl is not None: req.stopLoss = sl
        if tp is not None: req.takeProfit = tp
        if comment: req.comment = comment

        event = threading.Event()
        client_msg_id = f"order_{uuid.uuid4().hex}"
        self._pending_orders[request_id] = (event, order)
        self._pending_client_msg_ids[client_msg_id] = request_id

        client = self._conn.client
        if client is None:
            order.status = OrderStatus.REJECTED
            order.comment = "not_connected"
            return order

        def do_send():
            d = client.send(req, clientMsgId=client_msg_id, responseTimeoutInSeconds=timeout)

            def on_error(failure):
                logger.warning("Order send deferred error: %s", failure)
                # The error event handler (_handle_pending_order_error) will
                # set order status. But set the event so the calling thread
                # doesn't block until timeout.
                event.set()

            d.addCallbacks(lambda _: None, on_error)
        reactor.callFromThread(do_send)

        if not event.wait(timeout=timeout):
            # Don't immediately purge — keep entries for 60s grace period
            # so late error events can still be matched/logged
            def _delayed_cleanup():
                self._pending_orders.pop(request_id, None)
                self._pending_client_msg_ids.pop(client_msg_id, None)
            reactor.callFromThread(lambda: reactor.callLater(60.0, _delayed_cleanup))
            order.status = OrderStatus.PENDING
            order.comment = "timeout_awaiting_event"
            setattr(order, "reason", "timeout_awaiting_event")
        return order

    def send_order(self, symbol, direction, order_type, volume, price=None,
                   stop_loss=None, take_profit=None, comment="") -> Order:
        symbol_id = self.resolve_symbol_id(symbol)
        side = ProtoOATradeSide.BUY if direction == TradeDirection.LONG else ProtoOATradeSide.SELL
        proto_type = {OrderType.MARKET: ProtoOAOrderType.MARKET, OrderType.LIMIT: ProtoOAOrderType.LIMIT,
                      OrderType.STOP: ProtoOAOrderType.STOP}.get(order_type, ProtoOAOrderType.MARKET)
        return self.new_order(symbol_id, side, self._volume_calc.lots_to_volume(symbol_id, volume), order_type=proto_type,
                             price=price, sl=stop_loss, tp=take_profit, comment=comment)

    def cancel_order(self, order_id, *, timeout=_ORDER_TIMEOUT_SEC) -> bool:
        req = ProtoOACancelOrderReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.orderId = order_id
        return self._conn.send_and_wait(req, timeout=timeout, prefix="order") is not None

    def amend_order(self, order_id, *, price=None, sl=None, tp=None, symbol_id=None, timeout=_ORDER_TIMEOUT_SEC) -> bool:
        req = ProtoOAAmendOrderReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.orderId = order_id
        if symbol_id:
            price = self._round_price(symbol_id, price)
            sl = self._round_price(symbol_id, sl)
            tp = self._round_price(symbol_id, tp)
        if price is not None: req.limitPrice = price
        if sl is not None: req.stopLoss = sl
        if tp is not None: req.takeProfit = tp
        return self._conn.send_and_wait(req, timeout=timeout, prefix="order") is not None

    def amend_sl_tp(self, position_id, sl, tp, *, symbol_id=None, timeout=_AMEND_TIMEOUT_SEC) -> bool:
        req = ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.positionId = position_id
        if symbol_id:
            sl = self._round_price(symbol_id, sl)
            tp = self._round_price(symbol_id, tp)
        req.stopLoss = sl
        req.takeProfit = tp
        return self._conn.send_and_wait(req, timeout=timeout, prefix="order") is not None

    def close_position(self, position_id, volume, *, timeout=_ORDER_TIMEOUT_SEC) -> bool:
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.positionId = position_id
        req.volume = volume
        return self._conn.send_and_wait(req, timeout=timeout, prefix="order") is not None

    def reconcile(self, timeout=_RECONCILE_TIMEOUT_SEC) -> list[Position]:
        if not self._state_mgr.is_operational:
            return []
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self._ctid_account_id
        res = self._conn.send_and_wait(req, timeout=timeout, prefix="qry")
        if res is None:
            return []
        payload = Protobuf.extract(res) if hasattr(res, "payloadType") else res
        positions = []
        for raw in getattr(payload, "position", []):
            try:
                td = getattr(raw, "tradeData", None)
                positions.append(Position(
                    position_id=str(getattr(raw, "positionId", "")),
                    symbol=self._symbol_name_for_id(getattr(td, "symbolId", 0)),
                    direction=TradeDirection.LONG if getattr(td, "tradeSide", 0) == ProtoOATradeSide.BUY else TradeDirection.SHORT,
                    volume=self._volume_calc.volume_to_lots(getattr(td, "symbolId", 0), int(getattr(td, "volume", 0))),
                    entry_price=getattr(raw, "price", 0.0),
                    current_price=getattr(raw, "price", 0.0),
                    stop_loss=getattr(raw, "stopLoss", None) or None,
                    take_profit=getattr(raw, "takeProfit", None) or None,
                    status=PositionStatus.OPEN,
                ))
            except Exception as exc:
                logger.warning("Reconcile parse error: %s", exc)
        return positions

    # ── Execution event handlers ───────────────────────────────────────────

    def _handle_execution_event(self, message, envelope=None) -> None:
        order_payload = getattr(message, "order", None)
        client_order_id = getattr(order_payload, "clientOrderId", "") if order_payload else ""
        etype = getattr(message, "executionType", None)
        logger.info("[EXEC_EVENT] clientOrderId=%r execType=%s has_order=%s pending_keys=%s",
                     client_order_id, etype, order_payload is not None,
                     list(self._pending_orders.keys()) if self._pending_orders else "[]")
        if not client_order_id or client_order_id not in self._pending_orders:
            # Fallback: try matching by envelope clientMsgId (same pattern as
            # _handle_pending_order_error). When cTrader acks with empty
            # clientOrderId, the clientMsgId from the envelope is the only
            # way to correlate the fill back to the pending order.
            client_msg_id = getattr(envelope, "clientMsgId", "") if envelope else ""
            if client_msg_id:
                client_order_id = self._pending_client_msg_ids.get(client_msg_id, "")
            if not client_order_id or client_order_id not in self._pending_orders:
                error_code = getattr(message, "errorCode", "UNKNOWN")
                description = getattr(message, "description", "")
                logger.warning(
                    "[EXEC_EVENT] DROP — clientOrderId=%r not in pending_orders (keys=%s) "
                    "errorCode=%r description=%r",
                    client_order_id,
                    list(self._pending_orders.keys()) if self._pending_orders else "[]",
                    error_code, description,
                )
                return
        event, order = self._pending_orders.pop(client_order_id)
        self._pending_client_msg_ids.pop(client_order_id, None)

        etype = getattr(message, "executionType", None)
        if etype == ProtoOAExecutionType.ORDER_CANCELLED:
            order.status = OrderStatus.CANCELLED
            setattr(order, "reason", "order_cancelled")
            event.set()
            self._trigger_callback("on_order_cancelled", order, message)
            return
        if etype == ProtoOAExecutionType.ORDER_REJECTED:
            reason = getattr(message, "errorCode", "") or "order_rejected"
            order.status = OrderStatus.REJECTED
            order.comment = reason
            setattr(order, "reason", reason)
            event.set()
            self._trigger_callback("on_order_rejected", order, message, reason)
            return

        order.status = OrderStatus.FILLED
        order.filled_at = datetime.utcnow()
        order.filled_price = (
            getattr(order_payload, "executionPrice", None)
            or getattr(getattr(message, "deal", None), "executionPrice", None)
            or getattr(getattr(message, "position", None), "price", None)
            or order.price
        )
        ev = getattr(order_payload, "executedVolume", 0)
        if ev:
            ev_symbol_id = getattr(order_payload, "symbolId", None)
            if ev_symbol_id is None:
                ev_symbol_id = self._resolve_name_to_id(order.symbol) or 0
            order.volume = self._volume_calc.volume_to_lots(ev_symbol_id, ev)
        setattr(order, "reason", "order_filled")
        event.set()
        self._trigger_callback("on_order_filled", order, message)

    def _handle_order_error_event(self, message, envelope) -> None:
        self._handle_pending_order_error(message, envelope)

    def _handle_pending_order_error(self, message, envelope) -> bool:
        client_order_id = getattr(message, "clientOrderId", "")
        client_msg_id = getattr(envelope, "clientMsgId", "")
        logger.info("[ORDER_ERROR] clientOrderId=%r clientMsgId=%r pending_keys=%s",
                     client_order_id, client_msg_id,
                     list(self._pending_orders.keys()) if self._pending_orders else "[]")
        if not client_order_id and client_msg_id:
            client_order_id = self._pending_client_msg_ids.get(client_msg_id, "")
        if not client_order_id or client_order_id not in self._pending_orders:
            error_code = getattr(message, "errorCode", "UNKNOWN")
            description = getattr(message, "description", "")
            logger.warning(
                "[ORDER_ERROR] DROP — no match for clientOrderId=%r clientMsgId=%r "
                "errorCode=%r description=%r",
                client_order_id, client_msg_id, error_code, description,
            )
            return False
        event, order = self._pending_orders.pop(client_order_id)
        self._pending_client_msg_ids.pop(client_order_id, None)
        error_code = getattr(message, 'errorCode', 'UNKNOWN')
        description = getattr(message, 'description', '')
        reason = f"{error_code}: {description}".strip(": ")
        order.status = OrderStatus.REJECTED
        order.comment = reason
        setattr(order, "reason", reason)
        logger.warning(
            "[ORDER_ERROR] MATCHED clientOrderId=%r errorCode=%r description=%r reason=%s",
            client_order_id, error_code, description, reason,
        )
        event.set()
        self._trigger_callback("on_order_rejected", order, message, reason)
        return True

    # ── Error handling & token refresh ─────────────────────────────────────

    def _handle_error(self, message) -> None:
        error_code = getattr(message, "errorCode", "UNKNOWN")
        if error_code == "ALREADY_LOGGED_IN":
            self._authed.set()
            return
        if self._auth_circuit_open or self._refresh_in_progress:
            return
        # Centralized auth error classification
        description = getattr(message, "description", "")

        # Tier classification (BQ-1382 §6)
        tier = _ERROR_TIERS.get(error_code, "unknown")
        logger.warning(
            "cTrader error [%s] tier=%s: %s",
            error_code, tier, description,
        )

        # Tier 3: Critical — halt auto-reconnect for permission/security errors
        if tier == "critical":
            logger.critical(
                "Critical cTrader error [%s] — halting auto-reconnect: %s",
                error_code, description,
            )
            return  # Don't attempt reconnect for permission/security errors

        # Tier 2: Rate/Resource — extended backoff before reconnect
        if tier == "rate_resource":
            logger.warning(
                "Rate/resource error [%s] — applying 10s extended backoff",
                error_code,
            )
            time.sleep(10)

        fault_type, policy = get_policy(error_code, description)
        logger.warning(
            "Auth error classified: code=%s fault_type=%s tier=%s can_refresh=%s escalate=%s",
            error_code, fault_type.value, tier, policy.can_refresh, policy.requires_escalation,
        )
        if policy.activate_kill_switch:
            logger.error(
                "Kill switch recommended due to %s fault (code=%s)",
                fault_type.value, error_code,
            )
        if policy.can_refresh:
            now = time.monotonic()
            if now - self._last_reactive_refresh_time < 60.0:
                return
            self._last_reactive_refresh_time = now
            self._refresh_token_and_reauth()
        elif policy.requires_escalation:
            logger.error(
                "Auth fault requires escalation: %s (%s) — failing closed",
                fault_type.value, error_code,
            )

    def _refresh_token_and_reauth(self, proactive: bool = False) -> None:
        """Delegate OAuth refresh to TokenLifecycle and re-auth on success.

        Runs the refresh in a background thread to avoid blocking the Twisted
        reactor. The re-auth send is dispatched back to the reactor thread
        via reactor.callFromThread().

        If no TokenLifecycle is wired or refresh is disabled, falls back to
        no-op (migration safety).
        """
        if self._token_lifecycle is None:
            logger.warning("_refresh_token_and_reauth: no TokenLifecycle wired — skipping")
            return

        if getattr(self._token_lifecycle, '_refresh_disabled', False):
            logger.info(
                "_refresh_token_and_reauth: token refresh DISABLED — skipping "
                "(manual rotation required). proactive=%s", proactive
            )
            return

        if not proactive and self._auth_circuit_open:
            return

        def _do_refresh_offthread():
            try:
                new_token = self._token_lifecycle.force_refresh()
                self._access_token = new_token
                # Refresh the refresh token too
                creds = self._token_lifecycle._store.get()
                self._refresh_token = creds.refresh_token
                # Update local expiry tracking
                exp = self._token_lifecycle.expires_at
                if exp is not None:
                    self._token_expires_at = time.monotonic() + max(
                        (exp - datetime.now(timezone.utc)).total_seconds(), 60.0
                    )
                else:
                    self._token_expires_at = time.monotonic() + 86400
                # Re-auth via reactor
                from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAccountAuthReq
                req = ProtoOAAccountAuthReq()
                req.ctidTraderAccountId = self._ctid_account_id
                req.accessToken = new_token
                reactor.callFromThread(self._conn.send, req)
                self._auth_error_count = 0
                logger.info("Token refreshed via TokenLifecycle delegation")
            except Exception as exc:
                self._auth_error_count += 1
                self._check_circuit_breaker()
                logger.error("Token refresh delegation failed: %s", exc)

        threading.Thread(target=_do_refresh_offthread, daemon=True).start()

    def _handle_auth_failure(self, context: str) -> None:
        self._auth_error_count += 1
        self._check_circuit_breaker()

    def _check_circuit_breaker(self) -> None:
        if self._auth_error_count >= 5:
            self._auth_circuit_open = True
            self._state_mgr.transition_to(ConnectionState.FAILED, reason=f"auth_errors:{self._auth_error_count}")
            self._activate_kill_switch_freeze(f"auth_failure:{self._auth_error_count}")
        elif self._auth_error_count >= 3:
            self._state_mgr.transition_to(ConnectionState.DEGRADED, reason=f"auth_degraded:{self._auth_error_count}")

    def _schedule_proactive_refresh(self, expires_in: int) -> None:
        if self._auth_circuit_open:
            return
        if getattr(self._token_lifecycle, '_refresh_disabled', False):
            logger.info("_schedule_proactive_refresh: skipped — token refresh DISABLED")
            return
        if self._refresh_timer is not None:
            self._refresh_timer.cancel()
        refresh_in = max(expires_in * 0.8, 60.0)
        self._refresh_timer = threading.Timer(refresh_in, self._proactive_refresh_task)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _proactive_refresh_task(self) -> None:
        if self._running:
            self._refresh_token_and_reauth(proactive=True)

    # ── Health-check compatibility wrappers ─────────────────────────────
    # These delegate to the data now owned by CTraderConnection so that
    # legacy tests and monitoring scripts keep working after the archived
    # refactor moved heartbeat/stale-tick state into CTraderConnection.

    def _check_heartbeat_health(self) -> None:
        """Compatibility wrapper — checks heartbeat health and transitions state.

        Heartbeat data lives in CTraderConnection._last_heartbeat_recv.
        This wrapper replicates the old health-check logic so tests and
        monitoring code that call it keep working.
        """
        if not self._state_mgr.is_operational:
            return  # Skip when DISCONNECTED/CONNECTING/RECONNECTING/FAILED

        now = time.monotonic()
        last_hb = self._conn._last_heartbeat_recv
        if last_hb is None:
            return
        age = now - last_hb

        if age >= _HEARTBEAT_RECONNECT_SEC:
            logger.warning("Heartbeat stale (%.1fs) → RECONNECTING", age)
            self._state_mgr.transition_to(
                ConnectionState.RECONNECTING, reason="heartbeat_reconnect",
            )
        elif age >= _HEARTBEAT_DEGRADED_SEC:
            logger.warning("Heartbeat degraded (%.1fs) → DEGRADED", age)
            self._state_mgr.transition_to(
                ConnectionState.DEGRADED, reason="heartbeat_degraded",
            )

    def _check_stale_ticks(self) -> None:
        """Compatibility wrapper — checks for stale ticks during market hours.

        Stale-tick detection was moved out of the feed during the archived
        refactor. This wrapper restores the check so tests and monitoring
        code keep working. Weekend and non-authenticated states are skipped.
        """
        if not self._state_mgr.is_authenticated and self._state_mgr.state != ConnectionState.DEGRADED:
            return  # Only check when AUTHENTICATED or DEGRADED

        now_dt = datetime.now(timezone.utc)
        if now_dt.weekday() >= 5:
            return  # Weekend — skip

        age = time.monotonic() - self._last_tick_recv_monotonic
        if age >= _STALE_TICK_FREEZE_SEC:
            logger.warning("Stale ticks (%.1fs) → activating kill switch freeze", age)
            self._activate_kill_switch_freeze(f"stale_ticks:{age:.0f}s")
        elif age >= _STALE_TICK_WARN_SEC:
            logger.warning("Stale ticks detected (%.1fs) — warning only", age)

    def _activate_kill_switch_freeze(self, reason: str) -> None:
        # Market-hours gating is handled by callers (e.g. _on_conn_feed_dead)
        # that check is_forex_market_closed() before invoking this method.
        # Auth-failure and other hard-error callers should fire unconditionally.
        if self._kill_switch is not None:
            try:
                self._kill_switch.activate_global_freeze(reason=reason, triggered_by="spot_feed")
            except Exception as exc:
                logger.error("Kill switch activation failed: %s", exc)

    # ── Reconnection ───────────────────────────────────────────────────────

    def _reconnect_restore(self) -> None:
        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import (
                ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq,
            )
            if not self._conn.is_connected:
                return

            self._state_mgr.transition_to(
                ConnectionState.APP_AUTHENTICATING, reason="reconnect_app_auth_sending",
            )
            app_res = self._conn.send_and_wait(
                ProtoOAApplicationAuthReq(clientId=self._client_id, clientSecret=self._client_secret),
                timeout=10,
            )
            if app_res is None or not self._is_expected_auth_response(app_res, _APP_AUTH_RES_PAYLOAD_TYPE, "reconnect_app"):
                self._handle_auth_failure("reconnect_app")
                return
            self._app_authed.set()

            self._state_mgr.transition_to(
                ConnectionState.ACCT_AUTHENTICATING, reason="reconnect_acct_auth_sending",
            )
            if not self._conn.is_connected:
                return

            acct_res = self._conn.send_and_wait(
                ProtoOAAccountAuthReq(ctidTraderAccountId=self._ctid_account_id, accessToken=self._access_token),
                timeout=10,
            )
            if acct_res is None or not self._is_expected_auth_response(acct_res, _ACCT_AUTH_RES_PAYLOAD_TYPE, "reconnect_acct"):
                self._handle_auth_failure("reconnect_acct")
                return
            self._authed.set()
            self._set_message_callback()

            logger.info(
                "Re-subscribing to %d symbols after reconnect: %s",
                len(self._subscribed_symbol_ids),
                list(self._subscribed_symbol_ids),
            )
            for sid in list(self._subscribed_symbol_ids):
                self._subscribe_by_id(sid)

            self._state_mgr.transition_to(ConnectionState.AUTHENTICATED, reason="reconnect_complete")
            positions = self.reconcile()
            self._resolve_disconnected_orders(positions)
            self._fire_reconnect_callbacks()
        except Exception as exc:
            logger.error("Reconnect restore failed: %s", exc, exc_info=True)
        finally:
            self._reauth_in_progress.clear()

    def _resolve_disconnected_orders(self, positions: list[Position]) -> None:
        if not self._disconnected_pending_orders:
            return
        available = list(positions)
        unresolved = []
        for order in self._disconnected_pending_orders:
            match = next((p for p in available if p.symbol == order.symbol and p.direction == order.direction and abs(p.volume - order.volume) < 0.000001), None)
            if match is None:
                unresolved.append(order)
                continue
            available.remove(match)
            order.status = OrderStatus.FILLED
            order.filled_at = datetime.utcnow()
            order.filled_price = match.entry_price
            setattr(order, "reason", "resolved_by_reconcile")
            self._trigger_callback("on_order_filled", order, match)
        self._disconnected_pending_orders = unresolved

    def _fire_reconnect_callbacks(self) -> None:
        if self._disconnect_at is None:
            return
        outage = time.monotonic() - self._disconnect_at
        for cb in self._on_reconnected_callbacks:
            try:
                cb(outage)
            except Exception as exc:
                logger.error("Reconnect callback error: %s", exc)
        self._disconnect_at = None
