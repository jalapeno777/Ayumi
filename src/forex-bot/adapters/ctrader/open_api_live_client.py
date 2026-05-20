"""cTrader Open API live trading client.

Sends real orders to cTrader via the Open API (protobuf over TCP).
Used by ``OrderManager.execute_live_order()`` when a real cTrader account
is connected.

ProtoOANewOrderReq fields used:
    - ctidTraderAccountId (required)
    - symbolId (required)
    - orderType (required)
    - tradeSide (required)
    - volume (required)
    - stopLoss (optional, server-side SL)
    - takeProfit (optional, server-side TP)

ProtoOAClosePositionReq fields used:
    - ctidTraderAccountId (required)
    - positionId (required)
    - volume (required)
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from ctrader_open_api.client import Client
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOANewOrderReq,
    ProtoOAClosePositionReq,
    ProtoOAAmendPositionSLTPReq,
    ProtoOACancelOrderReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATradeSide,
    ProtoOATimeInForce,
)
from ctrader_open_api.protobuf import Protobuf
from ctrader_open_api.tcpProtocol import TcpProtocol
from twisted.internet import reactor

from .reactor_manager import ReactorManager
from .models import TradeDirection, OrderType

logger = logging.getLogger("ayumi.openapi_live_client")

_MAX_RECONNECT_ATTEMPTS = 20
_INITIAL_RECONNECT_DELAY = 5.0
_MAX_RECONNECT_DELAY = 120.0


def _lots_to_units(lots: float) -> int:
    """Convert lots to units for cTrader (1 standard lot = 100,000 units)."""
    return int(round(lots * 100_000))


def _normalize_symbol_name(name: str) -> str:
    """Normalize symbol name: strip '/' and '_', uppercase."""
    return name.replace("/", "").replace("_", "").upper()


class OpenApiLiveClient:
    """Live trading client using cTrader Open API (protobuf over TCP).

    Manages its own TCP connection (separate from OpenApiSpotFeed's read-only feed).
    Sends ProtoOANewOrderReq with SL/TP on every order.
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
        spot_feed: "OpenApiSpotFeed | None" = None,
    ):
        self._ctid_account_id = ctid_account_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._host = host
        self._port = port

        self._client: Client | None = None
        self._spot_feed = spot_feed  # Use spot feed's authenticated client for sending
        self._connected = threading.Event()
        self._running = False
        self._lock = threading.Lock()

        # Callbacks
        self._callbacks: dict[str, list[Callable]] = {
            "on_connected": [],
            "on_disconnected": [],
            "on_order_filled": [],
            "on_order_rejected": [],
            "on_position_opened": [],
            "on_position_closed": [],
        }

        # Pending orders (maps client-order-id → order dict)
        self._pending_orders: dict[str, dict] = {}

        # Reconnect state
        self._reconnect_attempts = 0
        self._reconnect_delay = _INITIAL_RECONNECT_DELAY

        # Symbol name → ID mapping (populated by set_symbol_map)
        self._symbol_map: dict[str, int] = {}

    # ─── Properties ────────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    @property
    def is_live_mode(self) -> bool:
        return True  # This is ALWAYS live mode — paper mode uses OrderManager.execute_paper_order

    @property
    def is_paper_mode(self) -> bool:
        """Always False — this is the live trading client, not paper."""
        return False

    # ─── Symbol Mapping ────────────────────────────────────────────────────────

    def set_symbol_map(self, symbol_map: dict[str, int]):
        """Store a mapping from normalized symbol name → cTrader numeric symbol ID.

        Allows ``send_order`` to accept symbol names (e.g. "EURUSD")
        instead of requiring numeric IDs.
        """
        self._symbol_map: dict[str, int] = {
            _normalize_symbol_name(k): v for k, v in symbol_map.items()
        }
        logger.info(
            "[OpenApiLiveClient] Symbol map set: %d entries",
            len(self._symbol_map),
        )

    def resolve_symbol_id(self, name: str) -> int:
        """Resolve a symbol name to its numeric cTrader symbol ID.

        Raises ``ValueError`` if the symbol is not in the map — fail-fast
        to prevent sending orders with unknown symbols.
        """
        normalized = _normalize_symbol_name(name)
        symbol_id = self._symbol_map.get(normalized)
        if symbol_id is None:
            raise ValueError(
                f"Symbol '{name}' (normalized: '{normalized}') not found in symbol map. "
                f"Known symbols: {sorted(self._symbol_map.keys())}"
            )
        return symbol_id

    # ─── Lifecycle ──────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Connect to cTrader Open API and authenticate.

        When a ``spot_feed`` is provided, rides on its already-authenticated
        TCP connection — no separate auth needed.  This avoids cTrader's
        rejection of simultaneous sessions with the same app credentials.
        """
        if self._running and self._connected.is_set():
            return True

        # ── Spot-feed path: use the already-authenticated connection ──
        if self._spot_feed is not None and self._spot_feed._client is not None and self._spot_feed._client.isConnected:
            self._client = self._spot_feed._client
            # Chain our message handler with the spot feed's existing handler
            # to avoid overwriting it (which would kill tick processing)
            existing_handler = self._spot_feed._on_message
            live_handler = self._on_message
            def _chained_handler(client, message):
                try:
                    existing_handler(client, message)
                except Exception:
                    pass
                try:
                    live_handler(client, message)
                except Exception:
                    pass
            self._client.setMessageReceivedCallback(_chained_handler)
            self._running = True
            self._connected.set()
            logger.info("[OpenApiLiveClient] Riding on spot feed's authenticated connection")
            self._trigger_callback("on_connected")
            return True

        # ── Own-connection path (fallback) ──
        ReactorManager().ensure_running()

        self._client = Client(self._host, self._port, TcpProtocol)

        connected_event = threading.Event()

        def on_connected(_):
            logger.info("[OpenApiLiveClient] TCP connected to %s:%d", self._host, self._port)
            connected_event.set()
            self._connected.set()

        def on_disconnected(_, reason):
            logger.warning("[OpenApiLiveClient] TCP disconnected: %s", reason)
            self._connected.clear()
            self._trigger_callback("on_disconnected")

        self._client.setConnectedCallback(on_connected)
        self._client.setDisconnectedCallback(on_disconnected)
        self._client.setMessageReceivedCallback(self._on_message)

        reactor.callFromThread(self._client.startService)

        if not connected_event.wait(timeout=15):
            logger.error("[OpenApiLiveClient] Connection timeout")
            return False

        self._running = True

        # Authenticate
        if not self._auth():
            return False

        logger.info("[OpenApiLiveClient] Connected and authenticated")
        self._trigger_callback("on_connected")
        return True

    def disconnect(self):
        """Disconnect the client.

        If riding on the spot feed's connection, just detach without stopping
        the shared TCP client.
        """
        self._running = False
        if self._spot_feed is not None and self._client is self._spot_feed._client:
            # Don't kill the spot feed's connection
            logger.info("[OpenApiLiveClient] Detached from spot feed connection")
            self._client = None
        elif self._client:
            try:
                reactor.callFromThread(self._client.stopService)
            except Exception:
                pass
            self._client = None
        self._connected.clear()
        logger.info("[OpenApiLiveClient] Disconnected")

    # ─── Internal: Auth ──────────────────────────────────────────────────────────

    def _send_and_wait(self, message, timeout: float = 10):
        """Send a protobuf message and wait for response synchronously."""
        if not self._client or not self._client.isConnected:
            return None

        event = threading.Event()
        result = [None]
        client_msg_id = f"{id(message)}_{time.monotonic()}"

        def on_success(proto_res):
            result[0] = proto_res
            event.set()

        def on_error(failure):
            logger.error("[OpenApiLiveClient] send-and-wait error: %s", failure)
            event.set()

        def do_send():
            d = self._client.send(message, clientMsgId=client_msg_id, responseTimeoutInSeconds=timeout)
            d.addCallbacks(on_success, on_error)

        reactor.callFromThread(do_send)

        if not event.wait(timeout=timeout + 5):
            logger.error("[OpenApiLiveClient] send-and-wait timeout")
            return None
        return result[0]

    def _auth(self) -> bool:
        """Two-step auth: application + account."""
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAApplicationAuthReq,
            ProtoOAAccountAuthReq,
        )

        app_res = self._send_and_wait(
            ProtoOAApplicationAuthReq(
                clientId=self._client_id,
                clientSecret=self._client_secret,
            ),
            timeout=10,
        )
        if app_res is None:
            logger.error("[OpenApiLiveClient] Application auth failed")
            return False

        acct_res = self._send_and_wait(
            ProtoOAAccountAuthReq(
                ctidTraderAccountId=self._ctid_account_id,
                accessToken=self._access_token,
            ),
            timeout=10,
        )
        if acct_res is None:
            logger.error("[OpenApiLiveClient] Account auth failed")
            return False

        logger.info("[OpenApiLiveClient] Authenticated")
        return True

    # ─── Internal: Message Handling ───────────────────────────────────────────────

    def _on_message(self, client, message):
        """Route incoming execution / error events."""
        msg_type = message.payloadType
        logger.debug("[OpenApiLiveClient] Message type=%d", msg_type)

        # Execution event (position opened/closed, order filled/rejected)
        if msg_type == 2151:  # ProtoOAExecutionEvent
            payload = Protobuf.extract(message)
            self._handle_execution_event(payload)

        # Error response
        elif msg_type == 2142:  # ProtoOAErrorRes
            payload = Protobuf.extract(message)
            self._handle_error(payload)

    def _handle_execution_event(self, payload):
        """Handle ProtoOAExecutionEvent — order fills, closes, rejections."""
        execution_type = getattr(payload, 'executionType', None)
        position = getattr(payload, 'position', None)
        order = getattr(payload, 'order', None)

        # Map execution type enum to friendly name
        # ProtoOAExecutionType: MARKET_OPEN=1, MARKET_CLOSE=2, STOP_LOSS=3,
        # TAKE_PROFIT=4, TRAILING_STOP=5, etc.
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
            "[OpenApiLiveClient] Execution event: type=%s symbol=%s",
            exec_name,
            position.symbolId if position else "?",
        )

        if order and hasattr(order, 'orderId'):
            order_id_str = str(getattr(order, 'orderId', ''))
            if order_id_str in self._pending_orders:
                pending = self._pending_orders.pop(order_id_str)
                pending["order_id"] = order_id_str
                pending["symbol"] = _normalize_symbol_name(
                    str(getattr(position, 'symbolId', '') if position else pending.get("symbol", ""))
                )
                pending["volume"] = getattr(order, 'filledVolume', pending.get("volume", 0))
                pending["filled_price"] = getattr(order, 'filledPrice', pending.get("entry_price", 0))

                if exec_name == "MARKET_OPEN":
                    self._trigger_callback("on_order_filled", pending)
                elif exec_name in ("STOP_LOSS", "TAKE_PROFIT", "MARKET_CLOSE"):
                    self._trigger_callback("on_position_closed", pending)
                else:
                    self._trigger_callback("on_order_filled", pending)

    def _handle_error(self, payload):
        """Handle error responses — log and propagate."""
        error_code = getattr(payload, "errorCode", "UNKNOWN")
        description = getattr(payload, "description", "")
        order_id = getattr(payload, "orderId", None)
        position_id = getattr(payload, "positionId", None)

        logger.warning(
            "[OpenApiLiveClient] API error: code=%s desc=%s order_id=%s position_id=%s",
            error_code,
            description,
            order_id,
            position_id,
        )

        # If this was a pending order, move it to rejected
        if order_id and order_id in self._pending_orders:
            pending = self._pending_orders.pop(order_id)
            pending["rejection_reason"] = f"{error_code}: {description}"
            self._trigger_callback("on_order_rejected", pending)

    # ─── Order Sending ──────────────────────────────────────────────────────────

    # ─── Order Sending ──────────────────────────────────────────────────────────

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
    ):
        """Send an order to cTrader (called by ``OrderManager.execute_live_order``).

        ``order_type`` is ``OrderType.MARKET`` or ``OrderType.LIMIT``.
        SL/TP are sent in the ``ProtoOANewOrderReq`` so cTrader manages them
        server-side — they execute even if this script crashes.
        """
        direction_str = "long" if direction == TradeDirection.LONG else "short"
        return self.send_market_order(
            symbol=symbol,
            direction=direction_str,
            volume=volume,
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment=comment,
        )

    def send_market_order(
        self,
        symbol: str,
        direction: str,  # "long" or "short"
        volume: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str = "",
    ) -> str | None:
        """Send a market order with SL and TP.

        Returns client_order_id on success, None on failure.
        SL/TP are sent in the ProtoOANewOrderReq itself — cTrader manages
        them server-side even if the script crashes.
        """
        # Resolve symbol name to ID
        try:
            symbol_id = int(symbol)
        except (ValueError, TypeError):
            # symbol is a name like "EURUSD" — look up via symbol_map
            try:
                symbol_id = self.resolve_symbol_id(symbol)
            except ValueError:
                logger.error(
                    "[OpenApiLiveClient] Cannot resolve symbol '%s' — not in symbol map",
                    symbol,
                )
                return None

        # Map direction string to ProtoOATradeSide
        LONG_SIDE = 1  # ProtoOATradeSide.BUY
        SHORT_SIDE = 2  # ProtoOATradeSide.SELL
        trade_side = LONG_SIDE if direction.lower() == "long" else SHORT_SIDE

        order_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"

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

        req.label.append(order_id)

        with self._lock:
            self._pending_orders[order_id] = {
                "symbol": symbol,
                "direction": direction,
                "volume": volume,
                "entry_price": 0,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "order_id": order_id,
            }

        try:
            reactor.callFromThread(self._safe_send, req)
            logger.info(
                "[OpenApiLiveClient] Order sent: %s %s %.2f lots symbol_id=%d SL=%s TP=%s",
                order_id,
                direction,
                volume,
                symbol_id,
                stop_loss,
                take_profit,
            )
            return order_id
        except Exception as exc:
            logger.error("[OpenApiLiveClient] Failed to send order: %s", exc)
            with self._lock:
                self._pending_orders.pop(order_id, None)
            return None

    def close_position_by_id(
        self,
        position_id: int,
        volume: float,
    ) -> bool:
        """Close a position by its cTrader position ID."""
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.positionId.append(position_id)
        req.volume.append(_lots_to_units(volume))

        try:
            reactor.callFromThread(self._safe_send, req)
            logger.info(
                "[OpenApiLiveClient] Close position sent: position_id=%d volume=%.2f",
                position_id,
                volume,
            )
            return True
        except Exception as exc:
            logger.error("[OpenApiLiveClient] Failed to send close position: %s", exc)
            return False

    def amend_slTp(
        self,
        position_id: int,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> bool:
        """Amend SL/TP on an existing position."""
        req = ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId = self._ctid_account_id
        req.positionId.append(position_id)

        if stop_loss is not None:
            req.stopLoss.append(stop_loss)
        if take_profit is not None:
            req.takeProfit.append(take_profit)

        try:
            reactor.callFromThread(self._safe_send, req)
            logger.info(
                "[OpenApiLiveClient] SLTP amended: position_id=%d SL=%s TP=%s",
                position_id,
                stop_loss,
                take_profit,
            )
            return True
        except Exception as exc:
            logger.error("[OpenApiLiveClient] Failed to amend SLTP: %s", exc)
            return False

    # ─── Helpers ────────────────────────────────────────────────────────────────

    def _safe_send(self, req):
        """Send a request, suppressing timeout errors from library."""
        try:
            d = self._client.send(req)
            d.addErrback(lambda f: logger.debug("Send response timeout (expected): %s", f))
        except Exception as exc:
            logger.debug("Send failed: %s", exc)

    def register_callback(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callback(self, event: str, *args, **kwargs):
        if event in self._callbacks:
            for callback in self._callbacks[event]:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    logger.error("[OpenApiLiveClient] Callback error for %s: %s", event, e)
