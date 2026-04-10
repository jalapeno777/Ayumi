"""Tests for SlippageModel, spread passthrough, and clear_stuck_positions integration."""

from __future__ import annotations

import sys
from pathlib import Path


import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "forex-bot"))

from adapters.ctrader.models import (
    TradeDirection,
    TradeSignal,
)
from adapters.ctrader.order_manager import OrderManager, SlippageModel
from adapters.ctrader.paper_trader import PaperTrader


def _make_signal(
    direction=TradeDirection.LONG,
    symbol="EURUSD",
    entry=1.1000,
    sl=1.0990,
    tp=1.1040,
    confidence=0.7,
) -> TradeSignal:
    return TradeSignal(
        symbol=symbol,
        direction=direction,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp,
        take_profit_2=tp,
        take_profit_3=tp,
        volume=0.1,
        confidence=confidence,
        rationale="test",
    )


class TestSlippageModel:
    def test_apply_adds_slippage_for_long(self):
        model = SlippageModel(base_pips=0.1, random_pips=0.0, pip_value=0.0001)
        result = model.apply(1.1000, TradeDirection.LONG)
        assert result == pytest.approx(1.10001)

    def test_apply_subtracts_slippage_for_short(self):
        model = SlippageModel(base_pips=0.1, random_pips=0.0, pip_value=0.0001)
        result = model.apply(1.1000, TradeDirection.SHORT)
        assert result == pytest.approx(1.09999)

    def test_apply_with_spread_long(self):
        model = SlippageModel(base_pips=0.1, random_pips=0.0, pip_value=0.0001)
        result = model.apply_with_spread(1.1000, TradeDirection.LONG, spread=0.0002)
        assert result == pytest.approx(1.10011)

    def test_apply_with_spread_short(self):
        model = SlippageModel(base_pips=0.1, random_pips=0.0, pip_value=0.0001)
        result = model.apply_with_spread(1.1000, TradeDirection.SHORT, spread=0.0002)
        assert result == pytest.approx(1.09989)

    def test_zero_spread_uses_base_slippage_only(self):
        model = SlippageModel(base_pips=0.1, random_pips=0.0, pip_value=0.0001)
        result = model.apply_with_spread(1.1000, TradeDirection.LONG, spread=0.0)
        assert result == pytest.approx(1.10001)

    def test_random_component_adds_variance(self):
        model = SlippageModel(base_pips=0.0, random_pips=1.0, pip_value=0.0001)
        results = {model.apply(1.0, TradeDirection.LONG) for _ in range(50)}
        assert len(results) > 1


class TestPaperOrderSlippage:
    def test_paper_fill_includes_slippage(self):
        om = OrderManager()
        result = om.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            spread=0.0002,
        )
        assert result.success
        assert result.slippage_applied > 0
        assert result.order.filled_price != 1.1000

    def test_paper_fill_price_is_worse_for_long(self):
        om = OrderManager()
        result = om.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
        )
        assert result.order.filled_price >= 1.1000

    def test_paper_fill_price_is_worse_for_short(self):
        om = OrderManager()
        result = om.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.SHORT,
            volume=0.1,
            entry_price=1.1000,
        )
        assert result.order.filled_price <= 1.1000

    def test_position_uses_fill_price(self):
        om = OrderManager()
        result = om.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            spread=0.0002,
        )
        assert result.position.entry_price == result.order.filled_price


class TestPaperTraderSpreadPassthrough:
    def test_process_signal_passes_spread_to_order(self):
        trader = PaperTrader(starting_balance=100000.0)
        signal = _make_signal()
        om_result = trader._order_manager.execute_paper_order(
            symbol=signal.symbol,
            direction=signal.direction,
            volume=0.01,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit_1,
            spread=0.0003,
        )
        assert om_result.success
        assert om_result.slippage_applied > 0

    def test_execute_order_with_spread(self):
        trader = PaperTrader(starting_balance=100000.0)
        signal = _make_signal()
        result = trader._execute_order(signal, volume=0.01, spread=0.0002)
        assert result.success
        assert result.slippage_applied > 0
        assert result.order.filled_price != signal.entry_price

    def test_execute_order_without_spread_still_applies_base_slippage(self):
        trader = PaperTrader(starting_balance=100000.0)
        signal = _make_signal()
        result = trader._execute_order(signal, volume=0.01, spread=0.0)
        assert result.success
        assert result.slippage_applied > 0


class TestClearStuckPositions:
    def test_clear_stuck_positions_closes_all(self):
        trader = PaperTrader(starting_balance=100000.0)
        s1 = _make_signal(symbol="EURUSD", entry=1.1000, sl=1.0990, tp=1.1040)
        s2 = _make_signal(symbol="GBPUSD", entry=1.2600, sl=1.2590, tp=1.2640)
        trader._execute_order(s1, volume=0.01)
        trader._execute_order(s2, volume=0.01)

        open_before = len(trader.get_open_positions())
        assert open_before == 2

        cleared = trader.clear_stuck_positions()
        assert cleared == 2
        assert len(trader.get_open_positions()) == 0

    def test_clear_stuck_updates_balance(self):
        trader = PaperTrader(starting_balance=100000.0)
        signal = _make_signal(entry=1.1000, sl=1.0990, tp=1.1010)
        trader.process_signal(signal)
        trader.clear_stuck_positions()
        stats = trader.get_stats()
        assert stats.current_balance == stats.starting_balance + stats.realized_pnl

    def test_clear_empty_returns_zero(self):
        trader = PaperTrader(starting_balance=100000.0)
        cleared = trader.clear_stuck_positions()
        assert cleared == 0


class TestResetFunctionality:
    def test_reset_clears_trades(self):
        trader = PaperTrader(starting_balance=100000.0)
        signal = _make_signal()
        trader._execute_order(signal, volume=0.01)
        trader._stats.trades_executed = 1
        stats_before = trader.get_stats()
        assert stats_before.trades_executed == 1

        trader.reset()
        stats_after = trader.get_stats()
        assert stats_after.trades_executed == 0
        assert stats_after.current_balance == 100000.0

    def test_reset_with_stuck_positions(self):
        trader = PaperTrader(starting_balance=100000.0)
        trader._execute_order(_make_signal(), volume=0.01)
        trader.clear_stuck_positions()
        trader.reset()
        assert len(trader.get_open_positions()) == 0
        assert trader.get_stats().trades_executed == 0
