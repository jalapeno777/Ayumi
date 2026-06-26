"""Tests for ProgressiveSLMixin and CombinedSignalMixin."""

import pandas as pd
import pytest

from src.forex_trading.services.backtest.engine_core.base import EngineCore, Position
from src.forex_trading.services.backtest.mixins import (
    CombinedSignalMixin,
    ProgressiveSLMixin,
    ProgressiveSLConfig,
    SignalCombineMethod,
)


class _SLHost(EngineCore, ProgressiveSLMixin):
    def __init__(self, sl_config=None):
        EngineCore.__init__(self)
        ProgressiveSLMixin.__init__(self, sl_config=sl_config)


def _make_bar(close=1.1000, high=None, low=None, timestamp=None):
    if timestamp is None:
        timestamp = pd.Timestamp("2024-01-01")
    return pd.Series(
        {
            "open": close - 0.0001,
            "high": high if high is not None else close + 0.0002,
            "low": low if low is not None else close - 0.0002,
            "close": close,
            "volume": 100000,
        },
        name=timestamp,
    )


class TestProgressiveSLMixin:
    def test_no_position_returns_none(self):
        host = _SLHost()
        bar = _make_bar()
        result = host._check_progressive_sl_tp(
            bar, pd.Timestamp("2024-01-01"), "EURUSD"
        )
        assert result is None

    def test_long_sl_hit(self):
        host = _SLHost()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="long",
            lots=0.1,
            pair="EURUSD",
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        host.positions.append(pos)
        bar = _make_bar(low=1.0940)
        result = host._check_progressive_sl_tp(
            bar, pd.Timestamp("2024-01-02"), "EURUSD"
        )
        assert result == pytest.approx(1.0950)

    def test_short_sl_hit(self):
        host = _SLHost()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="short",
            lots=0.1,
            pair="EURUSD",
            stop_loss=1.1050,
            take_profit=1.0900,
        )
        host.positions.append(pos)
        bar = _make_bar(high=1.1060)
        result = host._check_progressive_sl_tp(
            bar, pd.Timestamp("2024-01-02"), "EURUSD"
        )
        assert result == pytest.approx(1.1050)

    def test_long_tp3_hit(self):
        host = _SLHost(sl_config=ProgressiveSLConfig(tp3_ratio=1.0))
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="long",
            lots=0.1,
            pair="EURUSD",
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        host.positions.append(pos)
        host._tp_stage[id(pos)] = 2
        bar = _make_bar(high=1.1101)
        result = host._check_progressive_sl_tp(
            bar, pd.Timestamp("2024-01-02"), "EURUSD"
        )
        assert result == pytest.approx(1.1100)

    def test_clear_tp_stage(self):
        host = _SLHost()
        host._tp_stage[42] = 2
        host._clear_tp_stage(42)
        assert 42 not in host._tp_stage

    def test_progressive_sl_moves_after_tp1(self):
        host = _SLHost(sl_config=ProgressiveSLConfig(tp1_sl_move=0.5))
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="long",
            lots=0.1,
            pair="EURUSD",
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        host.positions.append(pos)
        risk = 1.1100 - 1.1000
        tp1 = 1.1000 + risk * 0.33
        bar = _make_bar(high=tp1 + 0.0001)
        host._check_progressive_sl_tp(bar, pd.Timestamp("2024-01-02"), "EURUSD")
        assert host._tp_stage[id(pos)] == 1
        expected_sl = 1.1000 + 0.5 * risk
        assert pos.stop_loss == pytest.approx(expected_sl)


class TestCombinedSignalMixin:
    def test_empty_signals_raises(self):
        combo = CombinedSignalMixin()
        with pytest.raises(ValueError):
            combo.combine_signals({})

    def test_weighted_combine(self):
        combo = CombinedSignalMixin(
            method=SignalCombineMethod.WEIGHTED,
            weights={"a": 0.6, "b": 0.4},
            min_threshold=0.0,
        )
        idx = pd.date_range("2024-01-01", periods=5)
        sig_a = pd.Series([1.0, -1.0, 0.0, 1.0, 1.0], index=idx)
        sig_b = pd.Series([1.0, 1.0, -1.0, -1.0, 0.0], index=idx)
        result = combo.combine_signals({"a": sig_a, "b": sig_b})
        assert result.iloc[0] == pytest.approx(1.0)
        assert result.iloc[1] == pytest.approx(-0.2)
        assert result.iloc[3] == pytest.approx(0.2)

    def test_voted_combine(self):
        combo = CombinedSignalMixin(method=SignalCombineMethod.VOTED)
        idx = pd.date_range("2024-01-01", periods=5)
        sig_a = pd.Series([1.0, -1.0, 1.0, 1.0, 0.0], index=idx)
        sig_b = pd.Series([1.0, -1.0, -1.0, 0.0, 0.0], index=idx)
        sig_c = pd.Series([1.0, 1.0, 1.0, 1.0, -1.0], index=idx)
        result = combo.combine_signals({"a": sig_a, "b": sig_b, "c": sig_c})
        assert result.iloc[0] == 1.0
        assert result.iloc[1] == -1.0
        assert result.iloc[2] == 1.0

    def test_best_combine(self):
        combo = CombinedSignalMixin(method=SignalCombineMethod.BEST)
        idx = pd.date_range("2024-01-01", periods=3)
        sig_a = pd.Series([0.5, -0.3, 0.0], index=idx)
        sig_b = pd.Series([0.8, -0.1, 0.0], index=idx)
        result = combo.combine_signals({"a": sig_a, "b": sig_b})
        assert result.iloc[0] == pytest.approx(0.8)
        assert result.iloc[1] == pytest.approx(-0.3)

    def test_normalize_weights(self):
        combo = CombinedSignalMixin(weights={"a": 1.15, "b": 0.85})
        w = combo._normalize_weights(["a", "b"])
        assert w["a"] + w["b"] == pytest.approx(1.0)

    def test_unequal_length_truncates(self):
        combo = CombinedSignalMixin(method=SignalCombineMethod.WEIGHTED)
        idx_long = pd.date_range("2024-01-01", periods=5)
        idx_short = pd.date_range("2024-01-01", periods=3)
        sig_a = pd.Series([1.0] * 5, index=idx_long)
        sig_b = pd.Series([1.0] * 3, index=idx_short)
        result = combo.combine_signals({"a": sig_a, "b": sig_b})
        assert len(result) == 3

    def test_min_threshold_filters(self):
        combo = CombinedSignalMixin(
            method=SignalCombineMethod.WEIGHTED,
            weights={"a": 0.5, "b": 0.5},
            min_threshold=0.5,
        )
        idx = pd.date_range("2024-01-01", periods=2)
        sig_a = pd.Series([0.3, 1.0], index=idx)
        sig_b = pd.Series([-0.1, -1.0], index=idx)
        result = combo.combine_signals({"a": sig_a, "b": sig_b})
        assert result.iloc[0] == 0.0
