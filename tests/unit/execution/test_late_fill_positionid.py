"""Tests for late-fill callback positionId validation (Phase 1B).

Verifies that:
- When positionId is a non-numeric string (UUID-like clientOrderId), amend_sl_tp is skipped
- A warning is logged about the missing cTrader positionId
- When positionId is a valid int, amend proceeds normally
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest


class TestLateFillPositionIdValidation:
    """Verify positionId type validation in late-fill callbacks."""

    @pytest.fixture
    def engine_mock(self):
        """Create a minimal ForwardTestEngine mock with _register_late_fill_callbacks accessible."""
        from adapters.ctrader.forward_test_engine import (
            ForwardTestConfig,
            ForwardTestEngine,
        )

        # Create a minimal mock engine — we only need the callback registration
        _config = ForwardTestConfig(
            symbol="GBPUSD",
            symbols=["GBPUSD"],
            starting_balance=10_000.0,
            min_confidence=0.50,
            live_mode=True,
            execution_mode="live",
        )

        # We'll mock the __init__ to avoid needing real connections
        with patch.object(ForwardTestEngine, "__init__", return_value=None):
            engine = ForwardTestEngine.__new__(ForwardTestEngine)
            engine._lock = MagicMock()
            engine._market_feed = MagicMock()
            engine._pending_outcome_keys = set()
            engine._live_fill_count = 0
            engine._health = MagicMock()
            engine._health.signals_traded = 0
            engine._health.signals_pending = 0
            engine._health.signals_failed_live = 0
            engine._correlation_gate = None
            engine._blend_runner = None

        return engine

    def _make_signal(self):
        """Create a CTraderTradeSignal for testing."""
        from adapters.ctrader.models import TradeDirection, CTraderTradeSignal

        return CTraderTradeSignal(
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            entry_price=1.25000,
            stop_loss=1.24500,
            take_profit_1=1.26000,
            take_profit_2=1.27000,
            take_profit_3=1.28000,
            volume=0.1,
            confidence=0.70,
            rationale="test_signal",
        )

    def test_string_position_id_skips_amend(self, engine_mock, caplog):
        """When positionId is a UUID-like string, amend_sl_tp must not be called."""

        # Build a mock order
        order = MagicMock()
        order.order_id = "test-order-001"

        signal = self._make_signal()

        # Register the callbacks
        feed = MagicMock()
        feed.register_callback = MagicMock()
        engine_mock._market_feed = feed

        # Capture the registered callback closures
        registered_callbacks = {}

        def capture_callback(event_name, func):
            registered_callbacks[event_name] = func

        feed.register_callback.side_effect = capture_callback

        engine_mock._register_late_fill_callbacks(order, signal, "test_strategy")

        assert "on_order_filled" in registered_callbacks

        # Build a synthetic execution event with only a string clientOrderId-like positionId
        cb_order = MagicMock()
        cb_order.order_id = "test-order-001"

        message = MagicMock()
        message.order = MagicMock()
        message.order.positionId = "abc-12345-def"  # UUID-like string, not a valid int
        message.position = MagicMock()
        message.position.positionId = None
        message.deal = MagicMock()
        message.deal.positionId = None

        with caplog.at_level(logging.WARNING, logger="ayumi.forward_test_engine"):
            registered_callbacks["on_order_filled"](cb_order, message)

        # Verify amend_sl_tp was NOT called
        engine_mock._market_feed.amend_sl_tp.assert_not_called()

        # Verify warning was logged about missing/invalid positionId
        assert any(
            "no cTrader positionId" in record.message
            or "positionId" in record.message.lower()
            for record in caplog.records
        ), (
            f"Expected warning about missing positionId, got: {[r.message for r in caplog.records]}"
        )

    def test_valid_int_position_id_proceeds_with_amend(self, engine_mock, caplog):
        """When positionId is a valid integer string, amend_sl_tp proceeds."""

        order = MagicMock()
        order.order_id = "test-order-002"

        signal = self._make_signal()

        feed = MagicMock()
        registered_callbacks = {}

        def capture_callback(event_name, func):
            registered_callbacks[event_name] = func

        feed.register_callback.side_effect = capture_callback
        feed.resolve_symbol_id.return_value = 2
        feed.amend_sl_tp.return_value = True
        engine_mock._market_feed = feed

        engine_mock._register_late_fill_callbacks(order, signal, "test_strategy")

        cb_order = MagicMock()
        cb_order.order_id = "test-order-002"

        message = MagicMock()
        message.order = MagicMock()
        message.order.positionId = "1234567"  # valid numeric string
        message.position = MagicMock()
        message.position.positionId = None
        message.deal = MagicMock()
        message.deal.positionId = None

        with caplog.at_level(logging.INFO, logger="ayumi.forward_test_engine"):
            registered_callbacks["on_order_filled"](cb_order, message)

        # Verify amend_sl_tp WAS called with the int positionId
        engine_mock._market_feed.amend_sl_tp.assert_called_once()
        call_args = engine_mock._market_feed.amend_sl_tp.call_args
        assert call_args[0][0] == 1234567  # first positional arg is positionId, as int

    def test_zero_position_id_skips_amend(self, engine_mock, caplog):
        """When positionId is 0, amend_sl_tp must not be called."""
        order = MagicMock()
        order.order_id = "test-order-003"

        signal = self._make_signal()

        feed = MagicMock()
        registered_callbacks = {}

        def capture_callback(event_name, func):
            registered_callbacks[event_name] = func

        feed.register_callback.side_effect = capture_callback
        engine_mock._market_feed = feed

        engine_mock._register_late_fill_callbacks(order, signal, "test_strategy")

        cb_order = MagicMock()
        cb_order.order_id = "test-order-003"

        message = MagicMock()
        message.order = MagicMock()
        message.order.positionId = 0  # zero positionId
        message.position = MagicMock()
        message.position.positionId = 0
        message.deal = MagicMock()
        message.deal.positionId = 0

        with caplog.at_level(logging.WARNING, logger="ayumi.forward_test_engine"):
            registered_callbacks["on_order_filled"](cb_order, message)

        engine_mock._market_feed.amend_sl_tp.assert_not_called()

    def test_missing_position_id_skips_amend(self, engine_mock, caplog):
        """When no positionId is available at all, amend is skipped with warning."""
        order = MagicMock()
        order.order_id = "test-order-004"

        signal = self._make_signal()

        feed = MagicMock()
        registered_callbacks = {}

        def capture_callback(event_name, func):
            registered_callbacks[event_name] = func

        feed.register_callback.side_effect = capture_callback
        engine_mock._market_feed = feed

        engine_mock._register_late_fill_callbacks(order, signal, "test_strategy")

        cb_order = MagicMock()
        cb_order.order_id = "test-order-004"

        message = MagicMock()
        message.order = MagicMock()
        message.order.positionId = None
        message.position = MagicMock()
        message.position.positionId = None
        message.deal = MagicMock()
        message.deal.positionId = None

        with caplog.at_level(logging.WARNING, logger="ayumi.forward_test_engine"):
            registered_callbacks["on_order_filled"](cb_order, message)

        engine_mock._market_feed.amend_sl_tp.assert_not_called()

        assert any(
            "no cTrader positionId" in record.message for record in caplog.records
        ), (
            f"Expected warning about missing positionId, got: {[r.message for r in caplog.records]}"
        )
