"""Tests for ProgressiveSLMixin and CombinedSignalMixin.

Rewritten for post-refactor API (card 99a4d28d).
- EngineCore requires BacktestConfig
- Position → SimulatedTrade
- SignalCombineMethod → CombineMethod
- ProgressiveSLConfig removed — mixin takes BacktestConfig
- CombinedSignalMixin._combine_signals uses StrategySignal objects
"""

from __future__ import annotations  # noqa: I001

from datetime import datetime, timezone

import pytest

from core.config import BacktestConfig
from core.types import Bar, StrategySignal, TradeDirection
from engine.base import EngineCore
from engine.mixins import CombineMethod, CombinedSignalMixin, ProgressiveSLMixin


def _make_bar(close=1.1000, high=None, low=None, opn=None) -> Bar:
    return Bar(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        open=opn if opn is not None else close - 0.0001,
        high=high if high is not None else close + 0.0002,
        low=low if low is not None else close - 0.0002,
        close=close,
        volume=100_000,
    )


def _make_trade(
    direction=TradeDirection.LONG,
    entry_price=1.1000,
    stop_loss=1.0950,
    tp1=1.1050,
    tp2=1.1080,
    tp3=1.1100,
) -> object:
    """Build a SimulatedTrade-like object for testing."""
    from core.types import SimulatedTrade

    return SimulatedTrade(
        entry_bar_index=0,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
    )


class _SLHost(EngineCore, ProgressiveSLMixin):
    def __init__(self):
        config = BacktestConfig()
        EngineCore.__init__(self, config)
        ProgressiveSLMixin.__init__(self, config)


class TestProgressiveSLMixin:
    def test_progressive_sl_init(self):
        host = _SLHost()
        assert hasattr(host, "config")

    def test_progressive_sl_moves_after_tp1(self):
        host = _SLHost()
        trade = _make_trade(
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            tp1=1.1030,
            tp2=1.1060,
        )
        bar = _make_bar(high=1.1040)  # Above TP1
        host._progressive_sl_update(trade, bar)
        assert trade._sl_moved_to_be is True

    def test_progressive_sl_moves_to_tp1_after_tp2(self):
        host = _SLHost()
        trade = _make_trade(
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            tp1=1.1030,
            tp2=1.1060,
        )
        bar = _make_bar(high=1.1070)  # Above TP2
        host._progressive_sl_update(trade, bar)
        assert trade._sl_moved_to_tp1 is True
        assert trade.stop_loss == pytest.approx(1.1030)

    def test_short_progressive_sl(self):
        host = _SLHost()
        trade = _make_trade(
            direction=TradeDirection.SHORT,
            entry_price=1.1000,
            stop_loss=1.1050,
            tp1=1.0970,
            tp2=1.0940,
        )
        bar = _make_bar(low=1.0960)  # Below TP1 for short
        host._progressive_sl_update(trade, bar)
        assert trade._sl_moved_to_be is True

    def test_check_trade_exit_stop_loss_long(self):
        host = _SLHost()
        trade = _make_trade(
            direction=TradeDirection.LONG,
            stop_loss=1.0950,
        )
        bar = _make_bar(low=1.0940)
        hit, price, reason = host._check_trade_exit(trade, bar)
        assert hit is True
        assert price == pytest.approx(1.0950)

    def test_check_trade_exit_tp_long(self):
        host = _SLHost()
        trade = _make_trade(
            direction=TradeDirection.LONG,
            tp1=1.1050,
            tp2=1.1080,
            tp3=1.1100,
        )
        bar = _make_bar(high=1.1110)
        hit, price, reason = host._check_trade_exit(trade, bar)
        assert hit is True
        assert price == pytest.approx(1.1100)

    def test_check_trade_exit_no_hit(self):
        host = _SLHost()
        trade = _make_trade(
            direction=TradeDirection.LONG,
            stop_loss=1.0950,
            tp1=1.1050,
            tp2=1.1080,
            tp3=1.1100,
        )
        bar = _make_bar(close=1.1000, high=1.1001, low=1.0999)
        hit, price, reason = host._check_trade_exit(trade, bar)
        assert hit is False


class TestCombinedSignalMixin:
    def _make_signal(self, direction=TradeDirection.LONG, confidence=0.8, **kw):
        defaults = dict(
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1050,
            take_profit_2=1.1080,
            take_profit_3=1.1100,
            rationale="test",
        )
        defaults.update(kw)
        return StrategySignal(direction=direction, confidence=confidence, **defaults)

    def test_empty_signals_returns_none(self):
        combo = CombinedSignalMixin()
        result = combo._combine_signals([])
        assert result is None

    def test_weighted_combine_long(self):
        combo = CombinedSignalMixin()
        signals = [
            self._make_signal(TradeDirection.LONG, 0.9),
            self._make_signal(TradeDirection.LONG, 0.7),
        ]
        result = combo._combine_signals(signals, method=CombineMethod.WEIGHTED)
        assert result is not None
        assert result.direction == TradeDirection.LONG
        assert result.confidence == pytest.approx(0.8)

    def test_voted_combine(self):
        combo = CombinedSignalMixin()
        signals = [
            self._make_signal(TradeDirection.LONG, 0.9),
            self._make_signal(TradeDirection.LONG, 0.7),
            self._make_signal(TradeDirection.SHORT, 0.8),
        ]
        result = combo._combine_signals(signals, method=CombineMethod.VOTED)
        assert result is not None
        assert result.direction == TradeDirection.LONG

    def test_best_combine(self):
        combo = CombinedSignalMixin()
        signals = [
            self._make_signal(TradeDirection.LONG, 0.5),
            self._make_signal(TradeDirection.SHORT, 0.9),
        ]
        result = combo._combine_signals(signals, method=CombineMethod.BEST)
        assert result is not None
        assert result.direction == TradeDirection.SHORT
        assert result.confidence == pytest.approx(0.9)

    def test_weighted_below_threshold_returns_none(self):
        combo = CombinedSignalMixin()
        signals = [self._make_signal(TradeDirection.LONG, 0.3)]
        result = combo._combine_signals(signals, method=CombineMethod.WEIGHTED, min_confidence=0.5)
        assert result is None
