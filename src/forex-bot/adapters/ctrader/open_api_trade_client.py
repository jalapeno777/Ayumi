"""cTrader Open API trade execution client with independent TCP connection.

This REPLACES the broken ``open_api_live_client.py`` approach where order
execution rode the spot feed's TCP connection, breaking the ctrader_open_api
library's internal ``send().addCallbacks()`` response routing.

Key design decisions:
    - **Own TCP connection** to cTrader Open API (port 5035 SSL)
    - Does NOT receive a spot_feed reference — creates its own ``Client``
    - Independent heartbeat loop (every 10 seconds)
    - Full authentication sequence: app auth → account auth
    - Thread-safe send with response matching via ``clientMsgId``
    - Reconnection with full-jitter exponential backoff
    - Reports to ``ConnectionStateManager`` on every state change
    - On FAILED state: activates kill switch FREEZE via ``KillSwitchManager``
"""

import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from twisted.internet import reactor

from ctrader_open_api import Client, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAAccountAuthReq,
    ProtoOANewOrderReq,
    ProtoOAClosePositionReq,
    ProtoOAAmendOrderReq,
    ProtoOACancelOrderReq,
    ProtoOAReconcileReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATradeSide,
    ProtoOATimeInForce,
)
from ctrader_open_api.protobuf import Protobuf

from .connection_state import ConnectionState, ConnectionStateManager
from .kill_switch import KillSwitchManager
from .reactor_manager import ReactorManager
from .models import Order, Position, TradeDirection, OrderType, OrderStatus, PositionStatus

logger = logging.getLogger("ayumi.trade_client")


# ── Constants ─────────────────────────────────────────────────────────────────

_HEARTBEAT_INTERVAL_SEC = 10.0
_HEARTBEAT_DEGRADED_SEC = 15.0   # no heartbeat response within 15s → DEGRADED
_HEARTBEAT_RECONNECT_SEC = 30.0  # no heartbeat response within 30s → RECONNECTING

_BACKOFF_BASE_SEC = 1.0
_BACKOFF_CAP_SEC = 60.0
_BACKOFF_MAX_ATTEMPTS = 10

_AUTH_TIMEOUT_SEC = 10.0
_ORDER_TIMEOUT_SEC = 15.0
_RECONCILE_TIMEOUT_SEC = 30.0
_TCP_CONNECT_TIMEOUT_SEC = 15.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lots_to_units(lots: float) -> int:
    """Convert lots to units for cTrader (1 standard lot = 100,000 units)."""
    return int(round(lots * 100_000))


def _normalize_symbol_name(name: str) -> str:
    """Normalize symbol name: strip '/' and '_', uppercase."""
    return name.replace("/", "").replace("_", "").upper()


def calculate_full_jitter_backoff(
    attempt: int,
    base: float = _BACKOFF_BASE_SEC,
    cap: float = _BACKOFF_CAP_SEC,
) -> float:
    """Full-jitter exponential backoff (AWS recommended).

    delay = random_between(0, min(cap, base * 2^attempt))

    See: https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/
    """
    upper = min(cap, base * (2 ** attempt))
    return random.uniform(0, upper)


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class OrderResult:
    """Result of an order operation."""
    success: bool
    order_id: Optional[str] = None
    position_id: Optional[str] = None
    filled_price: Optional[float] = None
    volume: Optional[float] = None
    error: Optional[str] = None
    client_msg_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Trade Client ──────────────────────────────────────────────────────────────

class OpenApiTradeClient:
    """Trade execution client with its own dedicated TCP connection.

    This client maintains an independent connection to cTrader Open API,
    separate from the spot feed. This eliminates the response routing
    conflicts that occur when two clients share a single TCP connection.

    Usage::

        client = OpenApiTradeClient(
            ctid_account_id=12345,
            client_id="...",
            client_secret="...",
            access_token="...",
            host="demo.ctraderapi.com",
            port=5035,
        )
        client.connect()
        result = client.send_market_order("EURUSD", "long", 0.1, sl=1.0800, tp=1.0900)
        client.disconnect()
    """

    def __init__(
        self,
        ctid_account_id: int,
        client_id: str,
        client_secret: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        host: str = "demo.ctraderapi.com",
        port: int = 5035,
        kill_switch: Optional[KillSwitchManager] = None,
    ):
        self._ctid_account_id = ctid_account_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._host = host
        self._port = port

        # Kill switch for FREEZE on connection failure
        self._kill_switch = kill_switch  # May be None — caller can set later

        # Connection state manager
        self._state_mgr = ConnectionStateManager(name="trade_client")

        # Twisted client
        self._client: Optional[Client] = None

        # Thread-safe primitives
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._running = False
        self._connected_event = threading.Event()

        # Pending requests: clientMsgId → (Event, result_holder)
        self._pending: dict[str, tuple[threading.Event, list]] = {}

        # Heartbeat
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_heartbeat = threading.Event()
        self._last_heartbeat_recv: float = 0.0  # monotonic

        # Reconnection
        self._reconnect_thread: Optional[threading.Thread] = None
        self._reconnect_attempts = 0

        # Symbol name → ID mapping
        self._symbol_map: dict[str, int] = {}

        # Callbacks
        self._callbacks: dict[str, list[Callable]] = {
            "on_connected": [],
            "on_disconnected": [],
            "on_order_filled": [],
            "on_order_rejected": [],
            "on_position_opened": [],
            "on_position_closed": [],
            "on_state_change": [],
        }

        # Track if we've already fired kill switch (avoid duplicates)
        self._kill_switch_fired = False

    # ─── Properties ────────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._state_mgr.is_operational

    @property
    def is_live_mode(self) -> bool:
        return True

    @property
    def is_paper_mode(self) -> bool:
        return False

    @property
    def state(self) -> ConnectionState:
        return self._state_mgr.state

    @property
    def state_manager(self) -> ConnectionStateManager:
        return self._state_mgr

    # ─── Symbol Mapping ────────────────────────────────────────────────────────

    def set_symbol_map(self, symbol_map: dict[str, int]) -> None:
        """Store symbol name → cTrader numeric ID mapping."""
        self._symbol_map = {
            _normalize_symbol_name(k): v for k, v in symbol_map.items()
        }
        logger.info("[TradeClient] Symbol map set: %d entries", len(self._symbol_map))

    def resolve_symbol_id(self, name: str) -> int:
        """Resolve symbol name to cTrader numeric ID. Raises ValueError if unknown."""
        normalized = _normalize_symbol_name(name)
        symbol_id = self._symbol_map.get(normalized)
        if symbol_id is None:
            raise ValueError(
                f"Symbol '{name}' (normalized: '{normalized}') not in symbol map. "
                f"Known: {sorted(self._symbol_map.keys())}"
            )
        return symbol_id

    # ─── Kill Switch ───────────────────────────────────────────────────────────

    def set_kill_switch(self, kill_switch: KillSwitchManager) -> None:
        """Set the kill switch manager (can be set after construction)."""
        self._kill_switch = kill_switch

    def _fire_kill_switch(self, reason: str) -> None:
        """Activate kill switch FREEZE on critical failures."""
        if self._kill_switch_fired:
            return
        self._kill_switch_fired = True
        if self._kill_switch is not None:
            logger.critical(
                "[TradeClient] Activating kill switch FREEZE: %s", reason,
            )
            self._kill_switch.activate_global_freeze(
                reason=reason,
                triggered_by="trade_client",
            )
        else:
            logger.critical(
                "[TradeClient] Kill switch not set — cannot activate FREEZE: %s",
                reason,
            )

    # ─── Lifecycle ──────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Establish independent TCP connection and authenticate.

        Returns True on success, False on failure.
        """
        if self._running and self._state_mgr.is_authenticated:
            return True

        self._kill_switch_fired = False
        ReactorManager().ensure_running()

        self._state_mgr.transition_to(
            ConnectionState.CONNECTING, reason="connect() called",
        )

        if not self._tcp_connect():
            self._state_mgr.transition_to(
                ConnectionState.FAILED, reason="tcp_connect_failed",
            )
            return False

        self._state_mgr.transition_to(
            ConnectionState.CONNECTED, reason="tcp_established",
        )

        # Authentication
        self._state_mgr.transition_to(
            ConnectionState.APP_AUTHENTICATING, reason="sending_app_auth",
        )
        if not self._app_authenticate():
            self._state_mgr.transition_to(
                ConnectionState.FAILED, reason="app_auth_failed",
            )
            self._fire_kill_switch("Application authentication failed")
            return False

        self._state_mgr.transition_to(
            ConnectionState.ACCT_AUTHENTICATING, reason="sending_account_auth",
        )
        if not self._account_authenticate():
            self._state_mgr.transition_to(
                ConnectionState.FAILED, reason="account_auth_failed",
            )
            self._fire_kill_switch("Account authentication failed")
            return False

        self._state_mgr.transition_to(
            ConnectionState.AUTHENTICATED, reason="fully_authenticated",
        )

        self._running = True
        self._connected_event.set()
        self._reconnect_attempts = 0
        self._last_heartbeat_recv = time.monotonic()

        # Start heartbeat
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="trade-client-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

        # Register for state change callbacks → propagate to our listeners
        self._state_mgr.on_state_change(self._on_state_change_internal)

        logger.info("[TradeClient] Connected and authenticated on independent connection")
        self._trigger_callback("on_connected")
        return True

    def disconnect(self) -> None:
        """Clean shutdown of the trade client."""
        self._running = False
        self._connected_event.clear()
        self._stop_heartbeat.set()

        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5.0)
            self._heartbeat_thread = None

        if self._client is not None:
            try:
                reactor.callFromThread(self._client.stopService)
            except Exception:
                pass
            self._client = None

        # Fail any pending requests
        with self._lock:
            for cmid, (event, holder) in self._pending.items():
                holder[0] = None
                holder[1] = "disconnected"
                event.set()
            self._pending.clear()

        self._state_mgr.transition_to(
            ConnectionState.DISCONNECTED, reason="disconnect() called",
        )
        logger.info("[TradeClient] Disconnected")
        self._trigger_callback("on_disconnected")

    # ─── Internal: TCP Connect ─────────────────────────────────────────────────

    def _tcp_connect(self) -> bool:
        """Establish TCP + SSL connection to cTrader Open API."""
        self._client = Client(self._host, self._port, TcpProtocol)

        connected_event = threading.Event()
        error_holder: list[str] = [""]

        def on_connected(_):
            logger.info(
                "[TradeClient] TCP connected to %s:%d", self._host, self._port,
            )
            connected_event.set()

        def on_disconnected(_, reason):
            logger.warning("[TradeClient] TCP disconnected: %s", reason)
            self._connected_event.clear()
            if self._running:
                self._handle_connection_loss(reason)

        self._client.setConnectCallback(on_connected)
        self._client.setDisconnectCallback(on_disconnected)
        self._client.setMessageReceivedCallback(self._on_message)

        reactor.callFromThread(self._client.startService)

        if not connected_event.wait(timeout=_TCP_CONNECT_TIMEOUT_SEC):
            logger.error("[TradeClient] TCP connect timeout (%.0fs)", _TCP_CONNECT_TIMEOUT_SEC)
            return False

        return True

    # ─── Internal: Authentication ──────────────────────────────────────────────

    def _app_authenticate(self) -> bool:
        """Send ProtoOAApplicationAuthReq and wait for response."""
        req = ProtoOAApplicationAuthReq(
            clientId=self._client_id,
            clientSecret=self._client_secret,
        )
        res = self._send_and_wait(req, timeout=_AUTH_TIMEOUT_SEC)
        if res is None:
            logger.error("[TradeClient] App auth failed — no response")
            return False
        return True

    def _account_authenticate(self) -> bool:
        """Send ProtoOAAccountAuthReq and wait for response."""
        req = ProtoOAAccountAuthReq(
            ctidTraderAccountId=self._ctid_account_id,
            accessToken=self._access_token,
        )
        res = self._send_and_wait(req, timeout=_AUTH_TIMEOUT_SEC)
        if res is None:
            logger.error("[TradeClient] Account auth failed — no response")
            return False
        return True

    # ─── Internal: Send and Wait ───────────────────────────────────────────────

    def _send_and_wait(
        self,
        message,
        timeout: float = _ORDER_TIMEOUT_SEC,
    ) -> Optional[object]:
        """Send a protobuf message and synchronously wait for the response.

        Uses the client's own connection — the ``Deferred`` returned by
        ``client.send()`` fires when the response with matching ``clientMsgId``
        arrives on THIS connection. This is the core fix: no callback override.
        """
        if self._client is None or not self._client.isConnected:
            return None

        event = threading.Event()
        result: list = [None, None]  # [response, error]
        client_msg_id = f"tc_{id(message)}_{time.monotonic()}"

        def on_success(proto_res):
            result[0] = proto_res
            event.set()

        def on_error(failure):
            result[1] = str(failure)
            logger.error("[TradeClient] send_and_wait error: %s", failure)
            event.set()

        def do_send():
            try:
                d = self._client.send(
                    message,
                    clientMsgId=client_msg_id,
                    responseTimeoutInSeconds=timeout,
                )
                d.addCallbacks(on_success, on_error)
            except Exception as exc:
                logger.error("[TradeClient] send failed: %s", exc)
                result[1] = str(exc)
                event.set()

        with self._send_lock:
            reactor.callFromThread(do_send)

        if not event.wait(timeout=timeout + 5):
            logger.error("[TradeClient] send_and_wait timeout (%.0fs)", timeout)
            return None

        if result[1] is not None:
            return None
        return result[0]

    # ─── Internal: Message Handling ────────────────────────────────────────────

    def _on_message(self, client, message) -> None:
        """Route incoming messages from the trade client's own connection."""
        msg_type = message.payloadType
        logger.debug("[TradeClient] Message received: payloadType=%d", msg_type)

        # Update heartbeat timestamp on any message
        self._last_heartbeat_recv = time.monotonic()

        # Execution event
        if msg_type == 2151:  # ProtoOAExecutionEvent
            payload = Protobuf.extract(message)
            self._handle_execution_event(payload)

        # Error response
        elif msg_type == 2142:  # ProtoOAErrorRes
            payload = Protobuf.extract(message)
            self._handle_error_response(payload)

        # Heartbeat response (any payload from server counts as heartbeat)
        elif msg_type == 2:  # ProtoHeartbeatEvent
            logger.debug("[TradeClient] Heartbeat received")

    def _handle_execution_event(self, payload) -> None:
        """Handle ProtoOAExecutionEvent — order fills, closes, rejections."""
        execution_type = getattr(payload, "executionType", None)
        position = getattr(payload, "position", None)
        order = getattr(payload, "order", None)

        EXEC_TYPE_MAP = {
            1: "MARKET_OPEN",
            2: "MARKET_CLOSE",
            3: "STOP_LOSS",
            4: "TAKE_PROFIT",
            5: "TRAILING_STOP",
            6: "ORDER_CANCELLED",
        }
        exec_name = EXEC_TYPE_MAP.get(execution_type, str(execution_type))

        logger.info(
            "[TradeClient] Execution event: type=%s",
            exec_name,
        )

        if exec_name in ("MARKET_OPEN",):
            self._trigger_callback("on_order_filled", payload)
            self._trigger_callback("on_position_opened", payload)
        elif exec_name in ("MARKET_CLOSE", "STOP_LOSS", "TAKE_PROFIT"):
            self._trigger_callback("on_position_closed", payload)
        elif exec_name == "ORDER_CANCELLED":
            self._trigger_callback("on_order_rejected", payload)

    def _handle_error_response(self, payload) -> None:
        """Handle ProtoOAErrorRes."""
        error_code = getattr(payload, "errorCode", "UNKNOWN")
        description = getattr(payload, "description", "")
        logger.warning(
            "[TradeClient] API error: code=%s desc=%s",
            error_code, description,
        )

    # ─── Internal: Heartbeat ──────────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        """Independent heartbeat loop — sends ProtoHeartbeatEvent every 10s."""
        while not self._stop_heartbeat.wait(_HEARTBEAT_INTERVAL_SEC):
            if not self._running:
                break
            try:
                self._send_heartbeat()
                self._check_heartbeat_health()
            except Exception as exc:
                logger.error("[TradeClient] Heartbeat loop error: %s", exc)

    def _send_heartbeat(self) -> None:
        """Send a heartbeat message to keep the connection alive."""
        if self._client is None or not self._client.isConnected:
            return
        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoHeartbeatEvent

            def do_send():
                try:
                    d = self._client.send(ProtoHeartbeatEvent())
                    d.addErrback(
                        lambda f: logger.debug("[TradeClient] Heartbeat send errback: %s", f)
                    )
                except Exception:
                    pass

            reactor.callFromThread(do_send)
        except Exception as exc:
            logger.debug("[TradeClient] Heartbeat send error: %s", exc)

    def _check_heartbeat_health(self) -> None:
        """Check heartbeat receive health and trigger state transitions."""
        now = time.monotonic()
        elapsed = now - self._last_heartbeat_recv

        if elapsed > _HEARTBEAT_RECONNECT_SEC:
            logger.warning(
                "[TradeClient] Heartbeat timeout %.1fs > %.1fs → RECONNECTING",
                elapsed, _HEARTBEAT_RECONNECT_SEC,
            )
            self._handle_connection_loss("heartbeat_timeout")
        elif elapsed > _HEARTBEAT_DEGRADED_SEC:
            if self._state_mgr.state == ConnectionState.AUTHENTICATED:
                self._state_mgr.transition_to(
                    ConnectionState.DEGRADED,
                    reason=f"heartbeat_delayed_{elapsed:.1f}s",
                )
        else:
            # Heartbeat is healthy
            if self._state_mgr.state == ConnectionState.DEGRADED:
                self._state_mgr.transition_to(
                    ConnectionState.AUTHENTICATED,
                    reason="heartbeat_recovered",
                )

    # ─── Internal: Reconnection ────────────────────────────────────────────────

    def _handle_connection_loss(self, reason: str) -> None:
        """Handle unexpected connection loss — trigger reconnection."""
        if not self._running:
            return

        was_failed = self._state_mgr.state == ConnectionState.FAILED
        self._state_mgr.transition_to(
            ConnectionState.RECONNECTING, reason=reason,
        )

        # Start reconnection in a separate thread to avoid blocking heartbeat
        if self._reconnect_thread is not None and self._reconnect_thread.is_alive():
            return  # Already reconnecting

        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop,
            name="trade-client-reconnect",
            daemon=True,
        )
        self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        """Reconnection loop with full-jitter exponential backoff."""
        while self._running and self._reconnect_attempts < _BACKOFF_MAX_ATTEMPTS:
            self._reconnect_attempts += 1
            attempt = self._reconnect_attempts

            delay = calculate_full_jitter_backoff(attempt - 1)
            logger.info(
                "[TradeClient] Reconnect attempt %d/%d in %.1fs",
                attempt, _BACKOFF_MAX_ATTEMPTS, delay,
            )

            # Wait for backoff
            if self._stop_heartbeat.wait(timeout=delay):
                return  # stopped

            if not self._running:
                return

            # Attempt reconnection
            self._state_mgr.transition_to(
                ConnectionState.CONNECTING,
                reason=f"reconnect_attempt_{attempt}",
            )

            # Stop old client
            if self._client is not None:
                try:
                    reactor.callFromThread(self._client.stopService)
                except Exception:
                    pass
                self._client = None

            # TCP connect
            if not self._tcp_connect():
                logger.warning(
                    "[TradeClient] Reconnect attempt %d: TCP connect failed", attempt,
                )
                continue

            self._state_mgr.transition_to(
                ConnectionState.CONNECTED,
                reason=f"reconnect_tcp_up_{attempt}",
            )

            # Re-authenticate
            self._state_mgr.transition_to(
                ConnectionState.APP_AUTHENTICATING,
                reason=f"reconnect_app_auth_{attempt}",
            )
            if not self._app_authenticate():
                logger.warning(
                    "[TradeClient] Reconnect attempt %d: app auth failed", attempt,
                )
                continue

            self._state_mgr.transition_to(
                ConnectionState.ACCT_AUTHENTICATING,
                reason=f"reconnect_acct_auth_{attempt}",
            )
            if not self._account_authenticate():
                logger.warning(
                    "[TradeClient] Reconnect attempt %d: account auth failed", attempt,
                )
                continue

            # Success!
            self._reconnect_attempts = 0
            self._last_heartbeat_recv = time.monotonic()
            self._state_mgr.transition_to(
                ConnectionState.AUTHENTICATED,
                reason="reconnect_success",
            )
            logger.info("[TradeClient] Reconnected successfully")

            # Reconcile positions/orders with broker
            try:
                self.reconcile()
            except Exception as exc:
                logger.warning("[TradeClient] Post-reconnect reconcile error: %s", exc)

            return

        # Exhausted all retries
        logger.critical(
            "[TradeClient] Reconnection FAILED after %d attempts",
            _BACKOFF_MAX_ATTEMPTS,
        )
        self._state_mgr.transition_to(
            ConnectionState.FAILED, reason="max_reconnect_attempts_exhausted",
        )
        self._fire_kill_switch(
            f"Trade client connection failed after {_BACKOFF_MAX_ATTEMPTS} attempts",
        )
        self._running = False

    # ─── Internal: State Change ────────────────────────────────────────────────

    def _on_state_change_internal(
        self,
        old: ConnectionState,
        new: ConnectionState,
        reason: str,
        metadata: dict,
    ) -> None:
        """Internal callback from ConnectionStateManager — propagate to listeners."""
        self._trigger_callback("on_state_change", old, new, reason, metadata)

    # ─── Order Operations ──────────────────────────────────────────────────────

    def send_market_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "",
    ) -> OrderResult:
        """Send a market order. Returns OrderResult."""
        if not self._state_mgr.is_operational:
            return OrderResult(success=False, error="not_connected")

        try:
            symbol_id = self._resolve_symbol(symbol)
        except ValueError as exc:
            return OrderResult(success=False, error=str(exc))

        trade_side = ProtoOATradeSide.BUY if side.lower() == "long" else ProtoOATradeSide.SELL

        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.symbolId.append(symbol_id)
        req.orderType = ProtoOAOrderType.MARKET
        req.tradeSide = trade_side
        req.volume.append(_lots_to_units(volume))
        req.timeInForce = ProtoOATimeInForce.GOOD_TILL_CANCEL

        if stop_loss is not None:
            req.stopLoss.append(stop_loss)
        if take_profit is not None:
            req.takeProfit.append(take_profit)
        if comment:
            req.comment.append(comment)

        label = f"tc_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        req.label.append(label)

        res = self._send_and_wait(req, timeout=_ORDER_TIMEOUT_SEC)
        if res is None:
            return OrderResult(
                success=False, error="order_timeout",
                client_msg_id=label,
            )

        # Parse response — ProtoOANewOrderRes or error
        payload = Protobuf.extract(res) if hasattr(res, "payloadType") else res
        order_id = getattr(payload, "orderId", None)
        if order_id:
            order_id = str(order_id)

        return OrderResult(
            success=True,
            order_id=order_id,
            client_msg_id=label,
            volume=volume,
        )

    def send_limit_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "",
    ) -> OrderResult:
        """Send a limit order. Returns OrderResult."""
        if not self._state_mgr.is_operational:
            return OrderResult(success=False, error="not_connected")

        try:
            symbol_id = self._resolve_symbol(symbol)
        except ValueError as exc:
            return OrderResult(success=False, error=str(exc))

        trade_side = ProtoOATradeSide.BUY if side.lower() == "long" else ProtoOATradeSide.SELL

        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.symbolId.append(symbol_id)
        req.orderType = ProtoOAOrderType.LIMIT
        req.tradeSide = trade_side
        req.volume.append(_lots_to_units(volume))
        req.timeInForce = ProtoOATimeInForce.GOOD_TILL_CANCEL

        # Limit price
        req.requestedPrice.append(price)

        if stop_loss is not None:
            req.stopLoss.append(stop_loss)
        if take_profit is not None:
            req.takeProfit.append(take_profit)
        if comment:
            req.comment.append(comment)

        label = f"tc_lim_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        req.label.append(label)

        res = self._send_and_wait(req, timeout=_ORDER_TIMEOUT_SEC)
        if res is None:
            return OrderResult(success=False, error="limit_order_timeout")

        payload = Protobuf.extract(res) if hasattr(res, "payloadType") else res
        order_id = getattr(payload, "orderId", None)
        if order_id:
            order_id = str(order_id)

        return OrderResult(
            success=True,
            order_id=order_id,
            client_msg_id=label,
            volume=volume,
        )

    def amend_order(
        self,
        order_id: int,
        new_price: Optional[float] = None,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
    ) -> OrderResult:
        """Amend an existing pending order."""
        if not self._state_mgr.is_operational:
            return OrderResult(success=False, error="not_connected")

        req = ProtoOAAmendOrderReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.orderId.append(order_id)

        if new_price is not None:
            req.requestedPrice.append(new_price)
        if new_sl is not None:
            req.stopLoss.append(new_sl)
        if new_tp is not None:
            req.takeProfit.append(new_tp)

        res = self._send_and_wait(req, timeout=_ORDER_TIMEOUT_SEC)
        if res is None:
            return OrderResult(success=False, error="amend_timeout")

        return OrderResult(success=True, order_id=str(order_id))

    def cancel_order(self, order_id: int) -> OrderResult:
        """Cancel a pending order."""
        if not self._state_mgr.is_operational:
            return OrderResult(success=False, error="not_connected")

        req = ProtoOACancelOrderReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.orderId.append(order_id)

        res = self._send_and_wait(req, timeout=_ORDER_TIMEOUT_SEC)
        if res is None:
            return OrderResult(success=False, error="cancel_timeout")

        return OrderResult(success=True, order_id=str(order_id))

    def close_position(
        self,
        position_id: int,
        volume: Optional[float] = None,
    ) -> OrderResult:
        """Close a position (fully or partially)."""
        if not self._state_mgr.is_operational:
            return OrderResult(success=False, error="not_connected")

        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.positionId.append(position_id)

        if volume is not None:
            req.volume.append(_lots_to_units(volume))

        res = self._send_and_wait(req, timeout=_ORDER_TIMEOUT_SEC)
        if res is None:
            return OrderResult(success=False, error="close_timeout")

        return OrderResult(success=True, position_id=str(position_id))

    def get_positions(self) -> list[Position]:
        """Get all open positions via reconciliation."""
        result = self.reconcile()
        return result if result else []

    def get_orders(self) -> list:
        """Get all pending orders via reconciliation."""
        if not self._state_mgr.is_operational:
            return []

        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self._ctid_account_id

        res = self._send_and_wait(req, timeout=_RECONCILE_TIMEOUT_SEC)
        if res is None:
            return []

        payload = Protobuf.extract(res) if hasattr(res, "payloadType") else res
        orders = getattr(payload, "order", [])
        return list(orders) if orders else []

    def reconcile(self) -> list[Position]:
        """Query actual positions/orders from broker after reconnect or on demand.

        Returns a list of Position objects representing broker-side state.
        """
        if not self._state_mgr.is_operational:
            return []

        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self._ctid_account_id

        res = self._send_and_wait(req, timeout=_RECONCILE_TIMEOUT_SEC)
        if res is None:
            logger.warning("[TradeClient] Reconcile: no response")
            return []

        payload = Protobuf.extract(res) if hasattr(res, "payloadType") else res
        raw_positions = getattr(payload, "position", [])

        positions: list[Position] = []
        for rp in raw_positions:
            try:
                pos = Position(
                    position_id=str(getattr(rp, "positionId", "")),
                    symbol=str(getattr(rp, "symbolId", "")),
                    direction=(
                        TradeDirection.LONG
                        if getattr(rp, "tradeSide", 0) == 1
                        else TradeDirection.SHORT
                    ),
                    volume=getattr(rp, "volume", 0) / 100_000.0,
                    entry_price=getattr(rp, "price", 0.0),
                    current_price=getattr(rp, "price", 0.0),
                    stop_loss=getattr(rp, "stopLoss", None) or None,
                    take_profit=getattr(rp, "takeProfit", None) or None,
                    status=PositionStatus.OPEN,
                )
                positions.append(pos)
            except Exception as exc:
                logger.warning("[TradeClient] Reconcile parse error: %s", exc)

        logger.info("[TradeClient] Reconciled %d positions", len(positions))
        return positions

    # ─── Legacy API compatibility ──────────────────────────────────────────────

    def send_order(
        self,
        symbol: str,
        direction: TradeDirection,
        order_type: OrderType,
        volume: float,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "",
    ):
        """Legacy-compatible send_order API.

        Returns client_order_id on success, None on failure (matching
        the old OpenApiLiveClient.send_order return type).
        """
        side = "long" if direction == TradeDirection.LONG else "short"

        if order_type == OrderType.MARKET:
            result = self.send_market_order(
                symbol=symbol, side=side, volume=volume,
                stop_loss=stop_loss, take_profit=take_profit, comment=comment,
            )
        elif order_type == OrderType.LIMIT:
            if price is None:
                return None
            result = self.send_limit_order(
                symbol=symbol, side=side, volume=volume, price=price,
                stop_loss=stop_loss, take_profit=take_profit, comment=comment,
            )
        else:
            return None

        return result.order_id if result.success else None

    def close_position_by_id(self, position_id: int, volume: float) -> bool:
        """Legacy-compatible close_position_by_id."""
        result = self.close_position(position_id, volume)
        return result.success

    def amend_slTp(
        self,
        position_id: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> bool:
        """Legacy-compatible amend_slTp (amends position SL/TP)."""
        if not self._state_mgr.is_operational:
            return False

        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAAmendPositionSLTPReq,
        )

        req = ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.positionId.append(position_id)

        if stop_loss is not None:
            req.stopLoss.append(stop_loss)
        if take_profit is not None:
            req.takeProfit.append(take_profit)

        res = self._send_and_wait(req, timeout=_ORDER_TIMEOUT_SEC)
        return res is not None

    # ─── Helpers ────────────────────────────────────────────────────────────────

    def _resolve_symbol(self, symbol: str) -> int:
        """Resolve symbol name to ID — accepts int or name string."""
        try:
            return int(symbol)
        except (ValueError, TypeError):
            return self.resolve_symbol_id(symbol)

    # ─── Callbacks ──────────────────────────────────────────────────────────────

    def register_callback(self, event: str, callback: Callable) -> None:
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callback(self, event: str, *args, **kwargs) -> None:
        if event in self._callbacks:
            for callback in self._callbacks[event]:
                try:
                    callback(*args, **kwargs)
                except Exception as exc:
                    logger.error(
                        "[TradeClient] Callback error for %s: %s", event, exc,
                    )
