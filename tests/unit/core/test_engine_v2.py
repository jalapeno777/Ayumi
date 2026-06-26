"""Tests for composed BacktestEngine (engine_v2)."""

import math

import numpy as np
import pandas as pd
import pytest

from src.forex_trading.services.backtest.engine_v2 import (
    BacktestEngine,
    WalkForwardConfig,
    WalkForwardResults,
    WalkForwardWindow,
)
from src.forex_trading.services.backtest.mixins import SignalCombineMethod
from src.forex_trading.services.backtest.strategies import Strategy


class DummyStrategy(Strategy):
    """Simple strategy that generates long signals in bars 10-20 and short signals in bars 30-40."""

    def __init__(self, long_start=10, long_end=20, short_start=30, short_end=40):
        self._long_start = long_start
        self._long_end = long_end
        self._short_start = short_start
        self._short_end = short_end

    @property
    def name(self) -> str:
        return "DummyStrategy"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0.0, index=data.index)
        for i in range(len(data)):
            if self._long_start <= i <= self._long_end:
                signals.iloc[i] = 1.0
            elif self._short_start <= i <= self._short_end:
                signals.iloc[i] = -1.0
        return signals

    def get_parameters(self) -> dict:
        return {"long_start": self._long_start, "long_end": self._long_end}


class DummyStrategyB(Strategy):
    """Second strategy for combined signal tests."""

    @property
    def name(self) -> str:
        return "DummyStrategyB"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0.0, index=data.index)
        for i in range(len(data)):
            if 15 <= i <= 25:
                signals.iloc[i] = 1.0
            elif 35 <= i <= 45:
                signals.iloc[i] = -1.0
        return signals

    def get_parameters(self) -> dict:
        return {}


def _generate_test_data(n_bars: int = 100, seed: int = 42) -> pd.DataFrame:
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n_bars, freq="1h")
    base_price = 1.1000
    returns = np.random.normal(0, 0.0005, n_bars)
    prices = base_price * np.cumprod(1 + returns)
    noise = np.random.normal(0, 0.0001, n_bars)

    return pd.DataFrame(
        {
            "open": prices - noise,
            "high": prices + abs(noise) * 2,
            "low": prices - abs(noise) * 2,
            "close": prices,
            "volume": np.random.randint(10000, 100000, n_bars),
        },
        index=dates,
    )


class TestBacktestEngineInit:
    def test_defaults(self):
        engine = BacktestEngine()
        assert engine.starting_balance == 10_000.0
        assert engine._use_progressive_sl is False
        assert engine._combine_method == SignalCombineMethod.WEIGHTED

    def test_progressive_sl_enabled(self):
        engine = BacktestEngine(use_progressive_sl=True)
        assert engine._use_progressive_sl is True

    def test_custom_signal_method(self):
        engine = BacktestEngine(signal_method=SignalCombineMethod.BEST)
        assert engine._combine_method == SignalCombineMethod.BEST


class TestRunSingle:
    def test_run_single_returns_metrics(self):
        engine = BacktestEngine()
        data = _generate_test_data()
        strategy = DummyStrategy()
        result = engine.run_single(strategy, data)
        assert isinstance(result, type(engine._calculate_metrics([], [1.0])))
        assert result.total_trades >= 0

    def test_run_single_resets_state(self):
        engine = BacktestEngine()
        data = _generate_test_data()
        strategy = DummyStrategy()
        engine.run_single(strategy, data)
        first_trades = len(engine.trades)
        engine.run_single(strategy, data)
        assert len(engine.trades) == first_trades

    def test_run_single_invalid_data_raises(self):
        engine = BacktestEngine()
        bad_data = pd.DataFrame({"close": [1.0, 2.0]})
        strategy = DummyStrategy()
        with pytest.raises(ValueError, match="missing required columns"):
            engine.run_single(strategy, bad_data)

    def test_run_single_no_signals(self):
        engine = BacktestEngine()
        data = _generate_test_data()
        strategy = DummyStrategy(
            long_start=999, long_end=999, short_start=999, short_end=999
        )
        result = engine.run_single(strategy, data)
        assert result.total_trades == 0
        assert result.total_return == 0.0


class TestRunAll:
    def test_run_all_returns_dict(self):
        engine = BacktestEngine()
        data = _generate_test_data()
        strategies = [DummyStrategy(), DummyStrategyB()]
        results = engine.run_all(strategies, data)
        assert isinstance(results, dict)
        assert "DummyStrategy" in results
        assert "DummyStrategyB" in results


class TestRunCombined:
    def test_run_combined_weighted(self):
        engine = BacktestEngine()
        data = _generate_test_data()
        strategies = [DummyStrategy(), DummyStrategyB()]
        result = engine.run_combined(
            strategies, data, method=SignalCombineMethod.WEIGHTED
        )
        assert result.total_trades >= 0

    def test_run_combined_voted(self):
        engine = BacktestEngine()
        data = _generate_test_data()
        strategies = [DummyStrategy(), DummyStrategyB()]
        result = engine.run_combined(strategies, data, method=SignalCombineMethod.VOTED)
        assert result.total_trades >= 0

    def test_run_combined_best(self):
        engine = BacktestEngine()
        data = _generate_test_data()
        strategies = [DummyStrategy(), DummyStrategyB()]
        result = engine.run_combined(strategies, data, method=SignalCombineMethod.BEST)
        assert result.total_trades >= 0


class TestRunWalkForward:
    def test_walk_forward_returns_results(self):
        engine = BacktestEngine()
        data = _generate_test_data(300)
        strategy = DummyStrategy()
        wf_config = WalkForwardConfig(train_bars=63, test_bars=63, step_bars=21)
        result = engine.run_walk_forward(strategy, data, wf_config=wf_config)
        assert isinstance(result, WalkForwardResults)
        assert len(result.windows) > 0

    def test_walk_forward_has_oos_metrics(self):
        engine = BacktestEngine()
        data = _generate_test_data(300)
        strategy = DummyStrategy()
        wf_config = WalkForwardConfig(train_bars=63, test_bars=63, step_bars=21)
        result = engine.run_walk_forward(strategy, data, wf_config=wf_config)
        assert result.combined_oos_metrics is not None
        assert result.combined_oos_metrics.profit_factor <= 10.0

    def test_walk_forward_windows_have_both_is_and_oos(self):
        engine = BacktestEngine()
        data = _generate_test_data(300)
        strategy = DummyStrategy()
        wf_config = WalkForwardConfig(train_bars=63, test_bars=63, step_bars=21)
        result = engine.run_walk_forward(strategy, data, wf_config=wf_config)
        for w in result.windows:
            assert w.is_metrics is not None
            assert w.oos_metrics is not None
            assert w.train_end - w.train_start == wf_config.train_bars


class TestWalkForwardDataclasses:
    def test_walk_forward_config_defaults(self):
        cfg = WalkForwardConfig()
        assert cfg.train_bars == 63
        assert cfg.test_bars == 126
        assert cfg.step_bars == 21

    def test_walk_forward_window(self):
        w = WalkForwardWindow(
            window_index=0, train_start=0, train_end=63, test_start=63, test_end=189
        )
        assert w.window_index == 0
        assert w.is_metrics is None
        assert w.oos_metrics is None

    def test_walk_forward_results_oos_property(self):
        r = WalkForwardResults(
            windows=[
                WalkForwardWindow(
                    window_index=0,
                    train_start=0,
                    train_end=10,
                    test_start=10,
                    test_end=20,
                )
            ]
        )
        assert len(r.oos_results) == 1
        assert r.oos_results[0] is None


class TestMRO:
    def test_backtest_engine_mro(self):
        mro = BacktestEngine.__mro__
        names = [c.__name__ for c in mro]
        assert "EngineCore" in names
        assert "ProgressiveSLMixin" in names
        assert "CombinedSignalMixin" in names
        assert "TradeManagementMixin" in names
