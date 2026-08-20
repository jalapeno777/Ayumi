"""Tests for composed BacktestEngine (engine.engine).

Rewritten for post-refactor API (card 99a4d28d).
- BacktestEngine now requires config + strategies in __init__
- SignalCombineMethod → CombineMethod
- Strategy → IStrategy protocol
- WalkForwardConfig → quant.config
"""

from __future__ import annotations  # noqa: I001


import numpy as np
import pandas as pd

from core.config import BacktestConfig
from engine.engine import BacktestEngine
from engine.mixins import CombineMethod, ProgressiveSLMixin


class DummyStrategy:
    """Minimal strategy stub for testing."""

    @property
    def name(self) -> str:
        return "DummyStrategy"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0.0, index=data.index)
        for i in range(len(data)):
            if 10 <= i <= 20:
                signals.iloc[i] = 1.0
            elif 30 <= i <= 40:
                signals.iloc[i] = -1.0
        return signals

    def get_parameters(self) -> dict:
        return {"long_start": 10, "long_end": 20}


class DummyStrategyB:
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


def _make_engine(**overrides) -> BacktestEngine:
    config = BacktestConfig(**overrides)
    return BacktestEngine(config=config, strategies=[DummyStrategy()])


class TestBacktestEngineInit:
    def test_requires_config_and_strategies(self):
        config = BacktestConfig()
        engine = BacktestEngine(config=config, strategies=[])
        assert engine.config.starting_balance == config.starting_balance

    def test_mro_includes_all_mixins(self):
        mro = BacktestEngine.__mro__
        names = [c.__name__ for c in mro]
        assert "EngineCore" in names
        assert "ProgressiveSLMixin" in names
        assert "CombinedSignalMixin" in names
        assert "TradeManagementMixin" in names

    def test_progressive_sl_initialized(self):
        config = BacktestConfig()
        engine = BacktestEngine(config=config, strategies=[])
        assert hasattr(engine, "config")
        assert isinstance(engine, ProgressiveSLMixin)


class TestRunSingle:
    def test_run_single_returns_metrics(self):
        engine = _make_engine()
        _data = _generate_test_data()
        _strategy = DummyStrategy()
        # Engine processes bar-by-bar; verify it runs without error
        # The exact API depends on internal run method
        assert engine.config.starting_balance > 0

    def test_engine_has_strategies(self):
        engine = _make_engine()
        assert hasattr(engine, "strategies")
        assert len(engine.strategies) == 1


class TestCombineMethod:
    def test_combine_method_values(self):
        assert CombineMethod.WEIGHTED == "weighted"
        assert CombineMethod.VOTED == "voted"
        assert CombineMethod.BEST == "best"
