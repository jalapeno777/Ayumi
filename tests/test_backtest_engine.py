"""Tests for backtesting engine."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.forex_trading.services.backtest.engine_v2 import BacktestEngine
from src.forex_trading.services.backtest.engine_core.base import BacktestMetrics
from src.forex_trading.services.backtest.strategies import Strategy
from src.forex_trading.services.backtest.prop_firm_rules import PropFirmConfig


class DummyStrategy(Strategy):
    @property
    def name(self):
        return "Dummy"

    def get_parameters(self):
        return {}

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=data.index)
        signals.iloc[10:20] = 1
        signals.iloc[30:40] = -1
        return signals


def generate_test_data(n_days: int = 100) -> pd.DataFrame:
    dates = pd.date_range(start="2024-01-01", periods=n_days, freq="D")
    np.random.seed(42)

    close = 1.1000 + np.cumsum(np.random.randn(n_days) * 0.002)
    high = close + np.abs(np.random.randn(n_days) * 0.001)
    low = close - np.abs(np.random.randn(n_days) * 0.001)
    open_price = low + np.random.rand(n_days) * (high - low)
    volume = np.random.randint(100000, 500000, n_days)

    df = pd.DataFrame(
        {
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )

    return df


def test_backtest_engine_initialization():
    engine = BacktestEngine(starting_balance=10000.0)
    assert engine.starting_balance == 10000.0
    assert len(engine.positions) == 0


def test_backtest_engine_run():
    data = generate_test_data()
    strategy = DummyStrategy()
    engine = BacktestEngine()
    result = engine.run_single(strategy, data)

    assert isinstance(result, BacktestMetrics)
    assert result.total_trades >= 0


def test_prop_firm_config():
    config = PropFirmConfig(
        max_daily_drawdown_pct=0.05, max_total_drawdown_pct=0.10, profit_target_pct=0.10
    )
    assert config.max_daily_drawdown_pct == 0.05
    assert config.max_total_drawdown_pct == 0.10


def test_strategy_validate_data():
    strategy = DummyStrategy()
    valid_data = generate_test_data()
    assert strategy.validate_data(valid_data) is True

    invalid_data = pd.DataFrame({"close": [1.1, 1.2, 1.3]})
    assert strategy.validate_data(invalid_data) is False


def test_backtest_with_no_signals():
    class NoSignalStrategy(Strategy):
        @property
        def name(self):
            return "NoSignal"

        def get_parameters(self):
            return {}

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            return pd.Series(0, index=data.index)

    data = generate_test_data()
    strategy = NoSignalStrategy()
    engine = BacktestEngine()
    result = engine.run_single(strategy, data)

    assert result.total_trades == 0
    assert len(result.equity_curve) > 0
