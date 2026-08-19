"""Tests for ExecutionEventHandler — cTrader execution event routing.

Tests use MagicMock objects that mimic the protobuf message structure.
No real protobuf compilation or SDK import is required.

Reference: BQ-1043 Phase 3a.
"""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock


from adapters.ctrader.execution_event_handler import ExecutionEventHandler
from adapters.ctrader.protocols import OrderResult, OrderStatus


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_order_payload(
    client_order_id: str = "",
    execution_price: float | None = None,
    executed_volume: float | None = None,
    order_id: int = 0,
):
    """Mock the ``order`` sub-message of a ProtoOAExecutionEvent."""
    m = MagicMock()
    m.clientOrderId = client_order_id
    m.executionPrice = execution_price
    m.executedVolume = executed_volume
    m.orderId = order_id
    return m


def make_execution_event(
    execution_type: int,
    order=None,
    error_code: str = "",
    payload_type: int = 2126,
):
    """Mock a ProtoOAExecutionEvent payload."""
    m = MagicMock()
    m.payloadType = payload_type
    m.executionType = execution_type
    m.order = order
    m.errorCode = error_code
    return m


def make_order_error_event(
    client_order_id: str = "",
    error_code: str = "UNKNOWN",
    description: str = "",
):
    """Mock a ProtoOAOrderErrorEvent payload (payload type 2132)."""
    m = MagicMock()
    m.payloadType = 2132
    m.clientOrderId = client_order_id
    m.errorCode = error_code
    m.description = description
    return m


def make_general_error(
    error_code: str = "UNKNOWN",
    description: str = "",
    client_msg_id: str = "",
):
    """Mock a ProtoOAErrorRes payload (payload type 2142)."""
    payload = MagicMock()
    payload.payloadType = 2142
    payload.errorCode = error_code
    payload.description = description

    envelope = MagicMock()
    envelope.payloadType = 2142
    envelope.clientMsgId = client_msg_id
    return payload, envelope


def make_envelope(client_msg_id: str = ""):
    """Mock the SDK envelope message (has clientMsgId)."""
    m = MagicMock()
    m.clientMsgId = client_msg_id
    return m


# ── Enum values from ProtoOAExecutionType ────────────────────────────────────

ORDER_FILLED = 3
ORDER_PARTIAL_FILL = 11
ORDER_CANCELLED = 5
ORDER_REJECTED = 7
ORDER_EXPIRED = 6


# ── Tests ────────────────────────────────────────────────────────────────────


class TestRegisterAndGetResult:
    """1. register_pending → fire event manually → get_result."""

    def test_register_and_get_result(self):
        handler = ExecutionEventHandler()
        event = handler.register_pending("cmid-001")

        assert not event.is_set()
        assert handler.get_result("cmid-001") is None

        # Manually set the event and inject a result (simulates handler path)
        with handler._lock:
            handler._results["cmid-001"] = OrderResult(status=OrderStatus.FILLED)
            handler._pending["cmid-001"].set()

        assert event.is_set()
        result = handler.get_result("cmid-001")
        assert result is not None
        assert result.status == OrderStatus.FILLED


class TestExecutionEventFilled:
    """2. Execution event with ORDER_FILLED → result FILLED."""

    def test_execution_event_filled(self):
        handler = ExecutionEventHandler()
        handler.register_pending("cmid-100", client_order_id="co-100")

        order = make_order_payload(
            client_order_id="co-100",
            execution_price=1.08500,
            executed_volume=10000,
            order_id=42,
        )
        msg = make_execution_event(ORDER_FILLED, order=order)

        handler.on_execution_event(msg)

        result = handler.get_result("cmid-100")
        assert result is not None
        assert result.status == OrderStatus.FILLED
        assert result.filled_price == 1.08500
        assert result.filled_volume == 10000
        assert result.order_id == "42"

    def test_execution_event_partial_fill(self):
        """Partial fill should also result in FILLED status."""
        handler = ExecutionEventHandler()
        handler.register_pending("cmid-pf", client_order_id="co-pf")

        order = make_order_payload(
            client_order_id="co-pf",
            execution_price=1.1000,
            executed_volume=5000,
        )
        msg = make_execution_event(ORDER_PARTIAL_FILL, order=order)

        handler.on_execution_event(msg)

        result = handler.get_result("cmid-pf")
        assert result is not None
        assert result.status == OrderStatus.FILLED


class TestExecutionEventRejected:
    """3. Execution event with ORDER_REJECTED → result REJECTED."""

    def test_execution_event_rejected(self):
        handler = ExecutionEventHandler()
        handler.register_pending("cmid-200", client_order_id="co-200")

        order = make_order_payload(client_order_id="co-200", order_id=99)
        msg = make_execution_event(ORDER_REJECTED, order=order, error_code="BAD_VOLUME")

        handler.on_execution_event(msg)

        result = handler.get_result("cmid-200")
        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert result.error_code == "BAD_VOLUME"

    def test_execution_event_cancelled(self):
        """ORDER_CANCELLED should produce CANCELLED status."""
        handler = ExecutionEventHandler()
        handler.register_pending("cmid-cxl", client_order_id="co-cxl")

        order = make_order_payload(client_order_id="co-cxl", order_id=77)
        msg = make_execution_event(ORDER_CANCELLED, order=order)

        handler.on_execution_event(msg)

        result = handler.get_result("cmid-cxl")
        assert result is not None
        assert result.status == OrderStatus.CANCELLED

    def test_execution_event_expired(self):
        """ORDER_EXPIRED should produce REJECTED status."""
        handler = ExecutionEventHandler()
        handler.register_pending("cmid-exp", client_order_id="co-exp")

        order = make_order_payload(client_order_id="co-exp")
        msg = make_execution_event(ORDER_EXPIRED, order=order)

        handler.on_execution_event(msg)

        result = handler.get_result("cmid-exp")
        assert result is not None
        assert result.status == OrderStatus.REJECTED


class TestOrderErrorMatchesByMsgId:
    """4. Order error event matched by clientMsgId → REJECTED."""

    def test_order_error_matches_by_client_order_id(self):
        handler = ExecutionEventHandler()
        handler.register_pending("cmid-300", client_order_id="co-300")

        msg = make_order_error_event(
            client_order_id="co-300",
            error_code="INVALID_STOP_LOSS",
            description="Stop loss too close to market",
        )
        env = make_envelope(client_msg_id="some-msg-id")

        handler.on_order_error(msg, env)

        result = handler.get_result("cmid-300")
        assert result is not None
        assert result.status == OrderStatus.REJECTED

    def test_order_error_falls_back_to_envelope_client_msg_id(self):
        """When clientOrderId doesn't match, fall back to envelope clientMsgId."""
        handler = ExecutionEventHandler()
        # Register with client_msg_id only (no client_order_id)
        handler.register_pending("env-msg-001")

        msg = make_order_error_event(
            client_order_id="",  # empty — won't match
            error_code="RANGE_ERROR",
            description="Price out of range",
        )
        env = make_envelope(client_msg_id="env-msg-001")

        handler.on_order_error(msg, env)

        result = handler.get_result("env-msg-001")
        assert result is not None
        assert result.status == OrderStatus.REJECTED


class TestUnmatchedLogsWarning:
    """5. Event with unknown clientOrderId → warning logged, no crash."""

    def test_unmatched_execution_event_logs_warning(self, caplog):
        handler = ExecutionEventHandler()
        handler.register_pending("cmid-known", client_order_id="co-known")

        order = make_order_payload(client_order_id="co-UNKNOWN")
        msg = make_execution_event(ORDER_FILLED, order=order)

        with caplog.at_level(logging.WARNING, logger="ayumi.execution"):
            handler.on_execution_event(msg)

        assert any("No match" in rec.message for rec in caplog.records)
        # The known pending entry should still be unresolved
        result = handler.get_result("cmid-known")
        assert result is None

    def test_unmatched_order_error_logs_warning(self, caplog):
        handler = ExecutionEventHandler()

        msg = make_order_error_event(
            client_order_id="co-NOPE",
            error_code="WHATEVER",
            description="desc",
        )
        env = make_envelope(client_msg_id="nope")

        with caplog.at_level(logging.WARNING, logger="ayumi.execution"):
            handler.on_order_error(msg, env)

        assert any("No match" in rec.message for rec in caplog.records)


class TestOrderErrorIncludesCodeAndDescription:
    """6. Order error should capture both errorCode and description."""

    def test_order_error_includes_error_code_and_description(self):
        handler = ExecutionEventHandler()
        handler.register_pending("cmid-400", client_order_id="co-400")

        msg = make_order_error_event(
            client_order_id="co-400",
            error_code="INSUFFICIENT_FUNDS",
            description="Not enough margin for this order",
        )
        env = make_envelope(client_msg_id="msg-400")

        handler.on_order_error(msg, env)

        result = handler.get_result("cmid-400")
        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert result.error_code == "INSUFFICIENT_FUNDS"
        assert result.error_message == "Not enough margin for this order"


class TestGeneralError:
    """7. General error (2142) resolves pending entry by clientMsgId."""

    def test_general_error_resolves_pending(self):
        handler = ExecutionEventHandler()
        handler.register_pending("cmid-500")

        payload, envelope = make_general_error(
            error_code="PROTO_ERROR",
            description="Protocol error",
            client_msg_id="cmid-500",
        )

        handler.on_general_error(payload, envelope)

        result = handler.get_result("cmid-500")
        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert result.error_code == "PROTO_ERROR"
        assert result.error_message == "Protocol error"

    def test_general_error_no_pending_logs_error(self, caplog):
        handler = ExecutionEventHandler()

        payload, envelope = make_general_error(
            error_code="WEIRD",
            description="Something happened",
            client_msg_id="not-pending",
        )

        with caplog.at_level(logging.ERROR, logger="ayumi.execution"):
            handler.on_general_error(payload, envelope)

        assert any("General error" in rec.message for rec in caplog.records)


class TestRoute:
    """8. route() dispatches by payload type."""

    def test_route_execution_event(self):
        handler = ExecutionEventHandler()
        handler.register_pending("cmid-r1", client_order_id="co-r1")

        order = make_order_payload(client_order_id="co-r1", execution_price=1.0)
        msg = make_execution_event(ORDER_FILLED, order=order)

        handler.route(msg)
        result = handler.get_result("cmid-r1")
        assert result is not None
        assert result.status == OrderStatus.FILLED

    def test_route_unhandled_payload_type(self, caplog):
        handler = ExecutionEventHandler()

        msg = MagicMock()
        msg.payloadType = 9999

        with caplog.at_level(logging.DEBUG, logger="ayumi.execution"):
            handler.route(msg)

        assert any("Unhandled" in rec.message for rec in caplog.records)


class TestCleanup:
    """9. cleanup_pending removes all traces."""

    def test_cleanup_pending(self):
        handler = ExecutionEventHandler()
        handler.register_pending("cmid-cl", client_order_id="co-cl")

        handler.cleanup_pending("cmid-cl")

        assert handler.get_result("cmid-cl") is None
        assert "cmid-cl" not in handler._pending
        assert "co-cl" not in handler._client_order_ids


class TestStatsRecorder:
    """10. SignalStatsRecorder wiring (Amendment A5)."""

    def test_stats_recorder_called_on_fill(self):
        stats = MagicMock()
        handler = ExecutionEventHandler(stats_recorder=stats)
        handler.register_pending("cmid-st", client_order_id="co-st")

        order = make_order_payload(
            client_order_id="co-st", execution_price=1.0, executed_volume=100
        )
        msg = make_execution_event(ORDER_FILLED, order=order)

        handler.on_execution_event(msg)

        stats.record_outcome.assert_called_once()
        call_kwargs = stats.record_outcome.call_args
        assert call_kwargs.kwargs["signal_id"] == "cmid-st"

    def test_stats_recorder_not_called_on_reject(self):
        stats = MagicMock()
        handler = ExecutionEventHandler(stats_recorder=stats)
        handler.register_pending("cmid-st2", client_order_id="co-st2")

        order = make_order_payload(client_order_id="co-st2")
        msg = make_execution_event(ORDER_REJECTED, order=order)

        handler.on_execution_event(msg)

        stats.record_outcome.assert_not_called()


class TestCallbacks:
    """11. on_filled / on_rejected callbacks."""

    def test_on_filled_callback(self):
        filled_results = []
        handler = ExecutionEventHandler(on_filled=filled_results.append)
        handler.register_pending("cmid-cb1", client_order_id="co-cb1")

        order = make_order_payload(client_order_id="co-cb1", execution_price=1.0)
        msg = make_execution_event(ORDER_FILLED, order=order)

        handler.on_execution_event(msg)
        assert len(filled_results) == 1
        assert filled_results[0].status == OrderStatus.FILLED

    def test_on_rejected_callback(self):
        rejected_results = []
        handler = ExecutionEventHandler(on_rejected=rejected_results.append)
        handler.register_pending("cmid-cb2", client_order_id="co-cb2")

        order = make_order_payload(client_order_id="co-cb2")
        msg = make_execution_event(ORDER_REJECTED, order=order)

        handler.on_execution_event(msg)
        assert len(rejected_results) == 1
        assert rejected_results[0].status == OrderStatus.REJECTED


class TestThreadSafety:
    """12. 10 threads concurrently registering + resolving."""

    def test_thread_safety(self):
        handler = ExecutionEventHandler()
        errors: list[Exception] = []

        def worker(idx: int):
            try:
                cmid = f"cmid-{idx}"
                event = handler.register_pending(cmid, client_order_id=f"co-{idx}")

                order = make_order_payload(
                    client_order_id=f"co-{idx}",
                    execution_price=float(idx),
                    executed_volume=1000,
                )
                msg = make_execution_event(ORDER_FILLED, order=order)

                handler.on_execution_event(msg)

                assert event.wait(timeout=5.0), f"Timeout for {cmid}"
                result = handler.get_result(cmid)
                assert result is not None, f"Null result for {cmid}"
                assert result.status == OrderStatus.FILLED

                handler.cleanup_pending(cmid)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert not errors, f"Thread errors: {errors}"

        # After all threads, pending map should be empty
        assert len(handler._pending) == 0
        assert len(handler._results) == 0
