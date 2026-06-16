"""Tests for OrderGateway — cTrader order sending and correlation.

Tests mock the session and event_handler. No real protobuf compilation
or SDK network calls are required.

Reference: BQ-1043 Phase 3b.
BQ-1042 fix: timeout returns TIMEOUT, never PENDING.
"""

from __future__ import annotations

import logging
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from adapters.ctrader.order_gateway import OrderGateway
from adapters.ctrader.protocols import OrderResult, OrderStatus, TradeSide


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_session():
    """A mock session with a no-op ``send()``."""
    session = MagicMock()
    session.send.return_value = None  # default: response received OK
    return session


@pytest.fixture
def mock_event_handler():
    """A mock ExecutionEventHandler with real Event objects.

    Individual tests configure the event to fire immediately or not at all.
    """
    eh = MagicMock()
    # By default, create a real Event that tests can control
    eh.register_pending.return_value = threading.Event()
    eh.get_result.return_value = None
    eh.cleanup_pending.return_value = None
    return eh


@pytest.fixture
def gateway(mock_session, mock_event_handler):
    return OrderGateway(
        session=mock_session,
        event_handler=mock_event_handler,
        account_id=5795523,
    )


# ── Test: successful market order fill ──────────────────────────────────────


def test_send_market_order_returns_filled(gateway, mock_session, mock_event_handler):
    """A fill event produces OrderResult with status=FILLED."""
    event = threading.Event()
    event.set()  # immediately fired
    mock_event_handler.register_pending.return_value = event
    mock_event_handler.get_result.return_value = OrderResult(
        status=OrderStatus.FILLED,
        order_id="12345",
        filled_price=1.08500,
        filled_volume=100000,
    )

    result = gateway.send_market_order(
        symbol_id=1,
        side=TradeSide.BUY,
        volume=100000,
    )

    assert result.status == OrderStatus.FILLED
    assert result.order_id == "12345"
    assert result.filled_price == 1.08500
    assert result.filled_volume == 100000
    assert result.execution_time_ms is not None

    # Verify session.send was called
    mock_session.send.assert_called_once()
    # Verify cleanup happened
    mock_event_handler.cleanup_pending.assert_called_once()


# ── Test: order rejected ────────────────────────────────────────────────────


def test_send_market_order_returns_rejected(gateway, mock_session, mock_event_handler):
    """A rejection event produces OrderResult with status=REJECTED."""
    event = threading.Event()
    event.set()
    mock_event_handler.register_pending.return_value = event
    mock_event_handler.get_result.return_value = OrderResult(
        status=OrderStatus.REJECTED,
        error_code="TRADE_DISABLED",
        error_message="Trading is disabled for this account",
    )

    result = gateway.send_market_order(
        symbol_id=2,
        side=TradeSide.SELL,
        volume=50000,
    )

    assert result.status == OrderStatus.REJECTED
    assert result.error_code == "TRADE_DISABLED"
    assert "disabled" in result.error_message.lower()

    mock_event_handler.cleanup_pending.assert_called_once()


# ── Test: order timeout — THE BQ-1042 FIX ───────────────────────────────────


def test_send_market_order_returns_timeout(gateway, mock_session, mock_event_handler):
    """When the event never fires, the result is TIMEOUT, not PENDING."""
    event = threading.Event()
    # Do NOT set the event — simulate timeout
    mock_event_handler.register_pending.return_value = event

    with patch("adapters.ctrader.order_gateway._ORDER_TIMEOUT", 0.05):
        result = gateway.send_market_order(
            symbol_id=1,
            side=TradeSide.BUY,
            volume=100000,
        )

    assert result.status == OrderStatus.TIMEOUT
    assert result.error_message is not None
    assert "timed out" in result.error_message.lower()
    assert result.execution_time_ms is not None

    mock_event_handler.cleanup_pending.assert_called_once()


# ── Test: cleanup is always called ──────────────────────────────────────────


def test_send_market_order_cleans_up_pending_on_fill(
    gateway, mock_session, mock_event_handler
):
    """Cleanup is called after a successful fill."""
    event = threading.Event()
    event.set()
    mock_event_handler.register_pending.return_value = event
    mock_event_handler.get_result.return_value = OrderResult(
        status=OrderStatus.FILLED,
    )

    gateway.send_market_order(symbol_id=1, side=TradeSide.BUY, volume=100000)

    mock_event_handler.cleanup_pending.assert_called_once()


def test_send_market_order_cleans_up_pending_on_timeout(
    gateway, mock_session, mock_event_handler
):
    """Cleanup is called even after a timeout."""
    event = threading.Event()
    mock_event_handler.register_pending.return_value = event

    with patch("adapters.ctrader.order_gateway._ORDER_TIMEOUT", 0.05):
        gateway.send_market_order(symbol_id=1, side=TradeSide.BUY, volume=100000)

    mock_event_handler.cleanup_pending.assert_called_once()


def test_send_market_order_cleans_up_pending_on_send_error(
    gateway, mock_session, mock_event_handler
):
    """Cleanup is called when session.send raises."""
    mock_session.send.side_effect = RuntimeError("not connected")

    result = gateway.send_market_order(
        symbol_id=1, side=TradeSide.BUY, volume=100000
    )

    assert result.status == OrderStatus.REJECTED
    assert result.error_code == "SEND_ERROR"
    mock_event_handler.cleanup_pending.assert_called_once()


# ── Test: cancel order ──────────────────────────────────────────────────────


def test_cancel_order_returns_true_on_success(gateway, mock_session):
    """Cancel returns True when session.send returns a response."""
    mock_session.send.return_value = MagicMock()  # non-None response

    result = gateway.cancel_order(order_id=42)

    assert result is True
    mock_session.send.assert_called_once()
    # Verify the correct protobuf was built
    args, kwargs = mock_session.send.call_args
    req = args[0]
    assert req.orderId == 42
    assert req.ctidTraderAccountId == 5795523


def test_cancel_order_returns_false_on_failure(gateway, mock_session):
    """Cancel returns False when session.send returns None (timeout)."""
    mock_session.send.return_value = None

    result = gateway.cancel_order(order_id=42)

    assert result is False


def test_cancel_order_returns_false_on_exception(gateway, mock_session):
    """Cancel returns False when session.send raises."""
    mock_session.send.side_effect = RuntimeError("send failed")

    result = gateway.cancel_order(order_id=42)

    assert result is False


# ── Test: amend position ────────────────────────────────────────────────────


def test_amend_position(gateway, mock_session):
    """Amend builds correct protobuf and returns True on success."""
    mock_session.send.return_value = MagicMock()

    result = gateway.amend_position(position_id=99, sl=1.08000, tp=1.09000)

    assert result is True
    args, kwargs = mock_session.send.call_args
    req = args[0]
    assert req.positionId == 99
    assert req.stopLoss == 1.08000
    assert req.takeProfit == 1.09000
    assert req.ctidTraderAccountId == 5795523


def test_amend_position_returns_false_on_failure(gateway, mock_session):
    """Amend returns False on timeout."""
    mock_session.send.return_value = None

    result = gateway.amend_position(position_id=99, sl=1.08)
    assert result is False


# ── Test: close position ────────────────────────────────────────────────────


def test_close_position(gateway, mock_session):
    """Close builds correct protobuf and returns True on success."""
    mock_session.send.return_value = MagicMock()

    result = gateway.close_position(position_id=77, volume=50000)

    assert result is True
    args, kwargs = mock_session.send.call_args
    req = args[0]
    assert req.positionId == 77
    assert req.volume == 50000
    assert req.ctidTraderAccountId == 5795523


def test_close_position_returns_false_on_failure(gateway, mock_session):
    """Close returns False on timeout."""
    mock_session.send.return_value = None

    result = gateway.close_position(position_id=77, volume=50000)
    assert result is False


# ── Test: BQ-1042 explicit guarantee — no PENDING status ────────────────────


def test_order_result_never_returns_pending(gateway, mock_session, mock_event_handler):
    """Explicitly test that timeout returns TIMEOUT, not PENDING.

    This is the core regression test for BQ-1042:
    'order_manager returns success=True for timed-out orders'.

    The old code returned OrderStatus.PENDING on timeout, which callers
    treated as success. The new OrderGateway must return TIMEOUT.
    """
    event = threading.Event()
    mock_event_handler.register_pending.return_value = event

    with patch("adapters.ctrader.order_gateway._ORDER_TIMEOUT", 0.05):
        result = gateway.send_market_order(
            symbol_id=1,
            side=TradeSide.BUY,
            volume=100000,
        )

    # The status MUST be TIMEOUT, NOT PENDING
    assert result.status == OrderStatus.TIMEOUT
    assert result.status != OrderStatus.PENDING
    assert result.status != OrderStatus.FILLED

    # The caller checks `result.status == OrderStatus.FILLED` for success.
    # A timed-out order will NOT be counted as a fill.
    assert result.status == OrderStatus.FILLED or result.status != OrderStatus.FILLED  # sanity
    is_success = (result.status == OrderStatus.FILLED)
    assert is_success is False  # timed-out order is NOT a success


# ── Test: SL/TP passed through to protobuf ──────────────────────────────────


def test_send_market_order_with_sl_tp(gateway, mock_session, mock_event_handler):
    """Verify SL and TP are set on the protobuf request."""
    event = threading.Event()
    event.set()
    mock_event_handler.register_pending.return_value = event
    mock_event_handler.get_result.return_value = OrderResult(
        status=OrderStatus.FILLED,
    )

    gateway.send_market_order(
        symbol_id=1,
        side=TradeSide.BUY,
        volume=100000,
        sl=1.08000,
        tp=1.09000,
        comment="test-order",
    )

    args, kwargs = mock_session.send.call_args
    req = args[0]
    assert req.stopLoss == 1.08000
    assert req.takeProfit == 1.09000
    assert req.comment == "test-order"
    # client_msg_id prefix
    msg_id = args[1] if len(args) > 1 else kwargs.get("client_msg_id", "")
    assert msg_id.startswith("order_")
