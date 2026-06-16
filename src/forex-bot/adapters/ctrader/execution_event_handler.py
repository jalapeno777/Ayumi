"""Execution event handler — routes cTrader protobuf messages to handlers.

Replaces the _on_message() switch in open_api_spot_feed.py.
Routes by payload type. Maintains pending-order correlation map.

Payload type → handler mapping:
    2126, 2151  →  on_execution_event   (order filled / cancelled / rejected)
    2132        →  on_order_error        (order error event)
    2142        →  on_general_error      (general error response)

Reference: BQ-1043 Phase 3a, §4.6 of the infra rebuild spec.
Amendment A5: SignalStatsRecorder wiring for outcome tracking.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from .protocols import OrderResult, OrderStatus

logger = logging.getLogger("ayumi.execution")

# ── Payload type constants (mirror open_api_spot_feed.py) ────────────────────

_EXECUTION_EVENT_PAYLOAD_TYPES = {2126, 2151}
_ORDER_ERROR_PAYLOAD_TYPE = 2132
_GENERAL_ERROR_PAYLOAD_TYPE = 2142

# ── ProtoOAExecutionType enum values (from OpenApiModelMessages_pb2) ─────────
# We use integers directly to avoid importing the protobuf module (which
# requires the SDK at runtime and complicates unit tests).  The values are
# stable as they are wire-format enums defined by cTrader.
_EXEC_TYPE_FILLED = 3       # ORDER_FILLED
_EXEC_TYPE_PARTIAL_FILL = 11  # ORDER_PARTIAL_FILL
_EXEC_TYPE_CANCELLED = 5    # ORDER_CANCELLED
_EXEC_TYPE_REJECTED = 7     # ORDER_REJECTED
_EXEC_TYPE_EXPIRED = 6      # ORDER_EXPIRED


class ExecutionEventHandler:
    """Routes execution events and correlates order responses.

    Maintains a pending-orders map keyed by ``client_msg_id``.  Each entry
    has a ``threading.Event`` + ``OrderResult`` holder.  When a response
    arrives (success OR error), the event fires and the holder is populated.

    This is the ONLY module that touches the pending-orders correlation map.
    ``OrderGateway`` registers entries; ``ExecutionEventHandler`` resolves
    them.

    A secondary map (``_client_order_ids``) correlates the SDK-generated
    ``clientOrderId`` back to the ``clientMsgId`` so that execution events
    (which carry ``clientOrderId``) can resolve entries registered under
    ``clientMsgId``.
    """

    def __init__(
        self,
        stats_recorder: Any = None,
        on_filled: Callable[[OrderResult], None] | None = None,
        on_rejected: Callable[[OrderResult], None] | None = None,
    ):
        """Initialise the handler.

        Args:
            stats_recorder: Optional ``SignalStatsRecorder`` for outcome
                tracking (Amendment A5).  When provided, ``record_outcome``
                is called on fills.
            on_filled: Optional callback invoked after a successful fill.
            on_rejected: Optional callback invoked after a rejection.
        """
        self._pending: dict[str, threading.Event] = {}
        self._results: dict[str, OrderResult | None] = {}
        self._client_order_ids: dict[str, str] = {}  # clientOrderId → client_msg_id
        self._lock = threading.Lock()
        self._stats = stats_recorder
        self._on_filled = on_filled
        self._on_rejected = on_rejected

    # ── Registration / lookup API (called by OrderGateway) ───────────────

    def register_pending(
        self,
        client_msg_id: str,
        client_order_id: str | None = None,
    ) -> threading.Event:
        """Register a pending order before sending.

        Args:
            client_msg_id: The ``clientMsgId`` used when sending the order.
            client_order_id: Optional ``clientOrderId`` if known upfront.

        Returns:
            ``threading.Event`` that will be set when the response arrives.
        """
        event = threading.Event()
        with self._lock:
            self._pending[client_msg_id] = event
            self._results[client_msg_id] = None
            if client_order_id:
                self._client_order_ids[client_order_id] = client_msg_id
        return event

    def get_result(self, client_msg_id: str) -> OrderResult | None:
        """Return the resolved result for ``client_msg_id``, or ``None``."""
        with self._lock:
            return self._results.get(client_msg_id)

    def cleanup_pending(self, client_msg_id: str) -> None:
        """Remove all trace of a pending entry after the caller is done."""
        with self._lock:
            self._pending.pop(client_msg_id, None)
            self._results.pop(client_msg_id, None)
            # Clean reverse map entries pointing to this client_msg_id
            for co_id, cm_id in list(self._client_order_ids.items()):
                if cm_id == client_msg_id:
                    self._client_order_ids.pop(co_id, None)

    # ── Routing ──────────────────────────────────────────────────────────

    def route(self, message: Any, envelope: Any | None = None) -> None:
        """Route an incoming message by payload type.

        Args:
            message: The extracted protobuf payload (from ``Protobuf.extract``).
            envelope: The raw SDK message envelope (has ``clientMsgId``).
                       May be ``None`` when no envelope context is available.
        """
        payload_type = getattr(message, "payloadType", None)

        if payload_type in _EXECUTION_EVENT_PAYLOAD_TYPES:
            self.on_execution_event(message)
        elif payload_type == _ORDER_ERROR_PAYLOAD_TYPE:
            self.on_order_error(message, envelope)
        elif payload_type == _GENERAL_ERROR_PAYLOAD_TYPE:
            self.on_general_error(message, envelope)
        else:
            logger.debug("[ROUTE] Unhandled payload type: %s", payload_type)

    # ── Handlers ─────────────────────────────────────────────────────────

    def on_execution_event(self, message: Any) -> None:
        """Handle order filled / cancelled / rejected (payload 2126, 2151).

        Extracts ``clientOrderId`` from the order payload, matches it to a
        pending entry, builds an :class:`OrderResult`, and fires the event.
        """
        order_payload = getattr(message, "order", None)
        client_order_id = (
            getattr(order_payload, "clientOrderId", "") if order_payload else ""
        )
        etype = getattr(message, "executionType", None)

        with self._lock:
            matched_id = self._match_by_client_order_id(client_order_id)
            if not matched_id:
                logger.warning(
                    "[EXEC] No match for clientOrderId=%r etype=%r",
                    client_order_id,
                    etype,
                )
                return

            result = self._build_result_from_execution(message, order_payload, etype)
            self._results[matched_id] = result
            self._pending[matched_id].set()

        logger.info(
            "[EXEC] clientOrderId=%r → %s", client_order_id, result.status.value
        )

        # Stats recording (Amendment A5)
        if self._stats is not None and result.status == OrderStatus.FILLED:
            try:
                self._stats.record_outcome(
                    signal_id=matched_id,
                    outcome="tp_hit",
                    pips=0.0,
                    time_to_close=0,
                )
            except Exception:
                logger.debug("[EXEC] Stats recording failed (non-fatal)")

        # Callbacks
        if result.status == OrderStatus.FILLED and self._on_filled:
            try:
                self._on_filled(result)
            except Exception:
                logger.debug("[EXEC] on_filled callback error (non-fatal)")

        if result.status == OrderStatus.REJECTED and self._on_rejected:
            try:
                self._on_rejected(result)
            except Exception:
                logger.debug("[EXEC] on_rejected callback error (non-fatal)")

    def on_order_error(self, message: Any, envelope: Any | None) -> None:
        """Handle order error event (payload 2132).

        Extracts ``errorCode`` + ``description``, matches by
        ``clientOrderId`` (from the payload) or ``clientMsgId`` (from the
        envelope), populates a REJECTED :class:`OrderResult`, fires event.
        """
        client_order_id = getattr(message, "clientOrderId", "")
        client_msg_id = ""
        if envelope is not None:
            client_msg_id = getattr(envelope, "clientMsgId", "")

        error_code = getattr(message, "errorCode", "UNKNOWN")
        description = getattr(message, "description", "")

        with self._lock:
            matched_id = self._match_by_client_order_id(client_order_id)
            if not matched_id and client_msg_id:
                matched_id = (
                    client_msg_id if client_msg_id in self._pending else None
                )
            if not matched_id:
                logger.warning(
                    "[ORDER_ERROR] No match clientOrderId=%r clientMsgId=%r "
                    "errorCode=%r desc=%r",
                    client_order_id,
                    client_msg_id,
                    error_code,
                    description,
                )
                return

            result = OrderResult(
                status=OrderStatus.REJECTED,
                error_code=error_code,
                error_message=description,
            )
            self._results[matched_id] = result
            self._pending[matched_id].set()

        logger.warning(
            "[ORDER_ERROR] → REJECTED errorCode=%r desc=%r",
            error_code,
            description,
        )

        if self._on_rejected:
            try:
                self._on_rejected(result)
            except Exception:
                logger.debug("[ORDER_ERROR] on_rejected callback error (non-fatal)")

    def on_general_error(self, message: Any, envelope: Any | None = None) -> None:
        """Handle general error response (payload 2142).

        Tries to resolve any pending order that might be waiting on this
        error response (matching by ``clientMsgId`` from the envelope).
        If no pending order matches, simply logs the error.
        """
        error_code = getattr(message, "errorCode", "UNKNOWN")
        description = getattr(message, "description", "")

        client_msg_id = ""
        if envelope is not None:
            client_msg_id = getattr(envelope, "clientMsgId", "")

        resolved = False
        if client_msg_id:
            with self._lock:
                if client_msg_id in self._pending:
                    result = OrderResult(
                        status=OrderStatus.REJECTED,
                        error_code=error_code,
                        error_message=description,
                    )
                    self._results[client_msg_id] = result
                    self._pending[client_msg_id].set()
                    resolved = True

        if resolved:
            logger.warning(
                "[ERROR] → REJECTED clientMsgId=%r errorCode=%r desc=%r",
                client_msg_id,
                error_code,
                description,
            )
        else:
            logger.error(
                "[ERROR] General error: code=%r desc=%r", error_code, description
            )

    # ── Internal helpers ─────────────────────────────────────────────────

    def _match_by_client_order_id(self, client_order_id: str) -> str | None:
        """Match a ``clientOrderId`` to a pending entry's ``client_msg_id``.

        Checks the explicit ``_client_order_ids`` reverse map first, then
        falls back to a direct key match (for cases where the
        ``clientOrderId`` *is* the ``clientMsgId``).
        """
        if not client_order_id:
            return None

        # Explicit reverse map
        if client_order_id in self._client_order_ids:
            return self._client_order_ids[client_order_id]

        # Direct match (clientOrderId used as clientMsgId)
        if client_order_id in self._pending:
            return client_order_id

        return None

    @staticmethod
    def _build_result_from_execution(
        message: Any,
        order_payload: Any,
        etype: Any,
    ) -> OrderResult:
        """Construct an :class:`OrderResult` from an execution event.

        Maps the ``ProtoOAExecutionType`` to the appropriate
        :class:`OrderStatus` and extracts fill details.
        """
        if etype in (_EXEC_TYPE_FILLED, _EXEC_TYPE_PARTIAL_FILL):
            filled_price = (
                getattr(order_payload, "executionPrice", None)
                if order_payload
                else None
            )
            filled_volume = (
                getattr(order_payload, "executedVolume", None)
                if order_payload
                else None
            )
            return OrderResult(
                status=OrderStatus.FILLED,
                order_id=str(getattr(order_payload, "orderId", "") or ""),
                filled_price=filled_price,
                filled_volume=filled_volume,
            )

        if etype == _EXEC_TYPE_CANCELLED:
            return OrderResult(
                status=OrderStatus.CANCELLED,
                order_id=str(getattr(order_payload, "orderId", "") or "")
                if order_payload
                else None,
            )

        if etype in (_EXEC_TYPE_REJECTED, _EXEC_TYPE_EXPIRED):
            error_code = getattr(message, "errorCode", None) or "REJECTED"
            return OrderResult(
                status=OrderStatus.REJECTED,
                order_id=str(getattr(order_payload, "orderId", "") or "")
                if order_payload
                else None,
                error_code=error_code,
            )

        # Default: treat as filled (ORDER_ACCEPTED, ORDER_REPLACED, etc.)
        logger.debug("[EXEC] Unhandled executionType=%r, defaulting to FILLED", etype)
        return OrderResult(status=OrderStatus.FILLED)


__all__ = ["ExecutionEventHandler"]
