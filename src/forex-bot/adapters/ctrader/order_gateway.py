"""Order gateway — sends orders to cTrader and correlates responses.

Uses ExecutionEventHandler for pending-order correlation.
OrderResult.status is explicitly FILLED | REJECTED | TIMEOUT — no more
PENDING masquerading as success.

Reactor bridge: dispatches via session.send(), which uses
reactor.callFromThread + threading.Event. Both callback and errback
fire event.set() (Amendment A1).

Reference: BQ-1043 Phase 3b, §4.5 of the infra rebuild spec.
Fix for BQ-1042: timed-out orders return TIMEOUT, not PENDING.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAmendPositionSLTPReq,
    ProtoOACancelOrderReq,
    ProtoOAClosePositionReq,
    ProtoOANewOrderReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATimeInForce,
    ProtoOATradeSide,
)

from .execution_event_handler import ExecutionEventHandler
from .protocols import OrderResult, OrderStatus, TradeSide

logger = logging.getLogger("ayumi.order_gateway")

# ── Order timeout in seconds ────────────────────────────────────────────────
_ORDER_TIMEOUT = 30.0


class OrderGateway:
    """Sends, cancels, and amends orders via the cTrader session.

    Implements :class:`OrderGatewayProtocol`. Uses
    :class:`ExecutionEventHandler` for response correlation — the
    gateway never touches the pending-order map directly.

    The BQ-1042 fix: ``send_market_order`` returns ``OrderResult`` with
    an explicit status — ``FILLED``, ``REJECTED``, or ``TIMEOUT``.
    PENDING is never returned. Callers must check
    ``result.status == OrderStatus.FILLED`` before counting success.
    """

    def __init__(
        self,
        session: Any,
        event_handler: ExecutionEventHandler,
        account_id: int,
    ) -> None:
        """Initialise the gateway.

        Args:
            session: A :class:`cTraderSession` (or any object with a
                compatible ``send()`` method).
            event_handler: The shared :class:`ExecutionEventHandler`
                used for request/response correlation.
            account_id: The cTrader trader account ID.
        """
        self._session = session
        self._event_handler = event_handler
        self._account_id = account_id

    # ── Market order ───────────────────────────────────────────────────────

    def send_market_order(
        self,
        symbol_id: int,
        side: TradeSide,
        volume: float,
        sl: float | None = None,
        tp: float | None = None,
        comment: str = "",
    ) -> OrderResult:
        """Send a market order and wait for fill / rejection / timeout.

        Returns:
            ``OrderResult`` with status ``FILLED``, ``REJECTED``, or
            ``TIMEOUT`` — never ``PENDING``.
        """
        client_msg_id = f"order_{uuid.uuid4().hex}"
        client_order_id = client_msg_id  # same ID for both correlation paths

        # Build protobuf request
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self._account_id
        req.symbolId = symbol_id
        req.orderType = ProtoOAOrderType.MARKET
        req.tradeSide = (
            ProtoOATradeSide.BUY if side == TradeSide.BUY else ProtoOATradeSide.SELL
        )
        req.volume = int(volume)
        req.timeInForce = ProtoOATimeInForce.GOOD_TILL_CANCEL
        req.clientOrderId = client_order_id
        if sl is not None:
            req.stopLoss = sl
        if tp is not None:
            req.takeProfit = tp
        if comment:
            req.comment = comment

        # Register with event handler BEFORE sending
        event = self._event_handler.register_pending(
            client_msg_id,
            client_order_id=client_order_id,
        )

        start_ts = time.monotonic()

        try:
            # Send via reactor bridge
            self._session.send(req, client_msg_id, timeout=_ORDER_TIMEOUT)
        except Exception as exc:
            logger.error(
                "Order send failed (msg_id=%s): %s", client_msg_id, exc
            )
            self._event_handler.cleanup_pending(client_msg_id)
            return OrderResult(
                status=OrderStatus.REJECTED,
                error_code="SEND_ERROR",
                error_message=str(exc),
            )

        # Wait for the event handler to fire the event
        fired = event.wait(timeout=_ORDER_TIMEOUT)
        elapsed_ms = int((time.monotonic() - start_ts) * 1000)

        if not fired:
            # BQ-1042 FIX: return TIMEOUT, NOT PENDING
            logger.warning(
                "Order timed out (msg_id=%s, symbol_id=%d, %.1fs)",
                client_msg_id,
                symbol_id,
                _ORDER_TIMEOUT,
            )
            self._event_handler.cleanup_pending(client_msg_id)
            return OrderResult(
                status=OrderStatus.TIMEOUT,
                error_message=f"Order timed out after {_ORDER_TIMEOUT:.0f}s",
                execution_time_ms=elapsed_ms,
            )

        # Event fired — retrieve the result
        result = self._event_handler.get_result(client_msg_id)
        self._event_handler.cleanup_pending(client_msg_id)

        if result is None:
            # Event fired but no result — treat as rejection
            logger.error(
                "Event fired but no result (msg_id=%s)", client_msg_id
            )
            return OrderResult(
                status=OrderStatus.REJECTED,
                error_code="NO_RESULT",
                error_message="Event fired but no result was set",
                execution_time_ms=elapsed_ms,
            )

        # Attach execution time
        if result.execution_time_ms is None:
            result = OrderResult(
                status=result.status,
                order_id=result.order_id,
                filled_price=result.filled_price,
                filled_volume=result.filled_volume,
                error_code=result.error_code,
                error_message=result.error_message,
                execution_time_ms=elapsed_ms,
            )

        logger.info(
            "Order completed (msg_id=%s, status=%s, %dms)",
            client_msg_id,
            result.status.value,
            elapsed_ms,
        )
        return result

    # ── Cancel order ───────────────────────────────────────────────────────

    def cancel_order(self, order_id: int) -> bool:
        """Cancel a pending order.

        Returns:
            ``True`` on success, ``False`` on failure or timeout.
        """
        client_msg_id = f"cancel_{uuid.uuid4().hex}"

        req = ProtoOACancelOrderReq()
        req.ctidTraderAccountId = self._account_id
        req.orderId = order_id

        try:
            response = self._session.send(req, client_msg_id, timeout=_ORDER_TIMEOUT)
        except Exception as exc:
            logger.error("Cancel order failed (order_id=%d): %s", order_id, exc)
            return False

        if response is None:
            logger.warning("Cancel order timed out (order_id=%d)", order_id)
            return False

        logger.info("Order cancelled (order_id=%d)", order_id)
        return True

    # ── Amend position SL/TP ───────────────────────────────────────────────

    def amend_position(
        self,
        position_id: int,
        sl: float | None = None,
        tp: float | None = None,
    ) -> bool:
        """Amend stop-loss and/or take-profit on an open position.

        Returns:
            ``True`` on success, ``False`` on failure or timeout.
        """
        client_msg_id = f"amend_{uuid.uuid4().hex}"

        req = ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId = self._account_id
        req.positionId = position_id
        if sl is not None:
            req.stopLoss = sl
        if tp is not None:
            req.takeProfit = tp

        try:
            response = self._session.send(req, client_msg_id, timeout=_ORDER_TIMEOUT)
        except Exception as exc:
            logger.error("Amend position failed (position_id=%d): %s", position_id, exc)
            return False

        if response is None:
            logger.warning("Amend position timed out (position_id=%d)", position_id)
            return False

        logger.info("Position amended (position_id=%d, sl=%s, tp=%s)", position_id, sl, tp)
        return True

    # ── Close position ─────────────────────────────────────────────────────

    def close_position(self, position_id: int, volume: float) -> bool:
        """Partially or fully close an open position.

        Returns:
            ``True`` on success, ``False`` on failure or timeout.
        """
        client_msg_id = f"close_{uuid.uuid4().hex}"

        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = self._account_id
        req.positionId = position_id
        req.volume = int(volume)

        try:
            response = self._session.send(req, client_msg_id, timeout=_ORDER_TIMEOUT)
        except Exception as exc:
            logger.error("Close position failed (position_id=%d): %s", position_id, exc)
            return False

        if response is None:
            logger.warning("Close position timed out (position_id=%d)", position_id)
            return False

        logger.info("Position closed (position_id=%d, volume=%d)", position_id, volume)
        return True


__all__ = ["OrderGateway"]
