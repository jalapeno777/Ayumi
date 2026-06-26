"""Tests for trading strategies."""
import pytest
import pandas as pd
import numpy as np
from src.forex_trading.strategies.momentum import MomentumCrossoverStrategy
from src.forex_trading.strategies.mean_reversion import MeanReversionStrategy
from src.forex_trading.strategies.breakout import BreakoutStrategy
from src.forex_trading.strategies.regime_aware import RegimeAwareStrategy, RegimeClassifier
from src.forex_trading.strategies.carry import CarryTradeStrategy


def generate_test_data(n_days: int = 100) -> pd.DataFrame:
    dates = pd.date_range(start='2024-01-01', periods=n_days, freq='D')
    np.random.seed(42)

    close = 1.1000 + np.cumsum(np.random.randn(n_days) * 0.002)
    high = close + np.abs(np.random.randn(n_days) * 0.001)
    low = close - np.abs(np.random.randn(n_days) * 0.001)
    open_price = low + np.random.rand(n_days) * (high - low)
    volume = np.random.randint(100000, 500000, n_days)

    df = pd.DataFrame({
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    }, index=dates)

    return df


def test_momentum_strategy_parameters():
    strat = MomentumCrossoverStrategy(fast_period=10, slow_period=30, adx_period=14, adx_threshold=20.0)
    params = strat.get_parameters()

    assert params['fast_period'] == 10
    assert params['slow_period'] == 30
    assert params['adx_threshold'] == 20.0


def test_momentum_strategy_generates_signals():
    data = generate_test_data(150)
    strat = MomentumCrossoverStrategy(fast_period=10, slow_period=30)
    signals = strat.generate_signals(data)

    assert len(signals) == len(data)
    assert signals.dtype == np.int64
    assert set(signals.unique()).issubset({-1, 0, 1})


def test_mean_reversion_parameters():
    strat = MeanReversionStrategy(rsi_period=7, rsi_oversold=20, rsi_overbought=80)
    params = strat.get_parameters()

    assert params['rsi_period'] == 7
    assert params['rsi_oversold'] == 20
    assert params['rsi_overbought'] == 80


def test_mean_reversion_generates_signals():
    data = generate_test_data(150)
    strat = MeanReversionStrategy()
    signals = strat.generate_signals(data)

    assert len(signals) == len(data)


def test_breakout_parameters():
    strat = BreakoutStrategy(channel_period=20, volume_threshold=1.2)
    params = strat.get_parameters()

    assert params['channel_period'] == 20
    assert params['volume_threshold'] == 1.2


def test_breakout_generates_signals():
    data = generate_test_data(100)
    strat = BreakoutStrategy()
    signals = strat.generate_signals(data)

    assert len(signals) == len(data)


def test_regime_aware_strategy():
    data = generate_test_data(100)
    strat = RegimeAwareStrategy()

    regime = RegimeClassifier.classify_regime(data)
    strat.set_regime(regime)

    signals = strat.generate_signals(data)
    assert len(signals) == len(data)


def test_carry_trade_parameters():
    strat = CarryTradeStrategy(rate_diff_threshold=2.0, momentum_period=30)
    params = strat.get_parameters()

    assert params['rate_diff_threshold'] == 2.0
    assert params['momentum_period'] == 30


def test_carry_trade_generates_signals():
    data = generate_test_data(100)
    strat = CarryTradeStrategy()
    signals = strat.generate_signals(data, pair='EURUSD')

    assert len(signals) == len(data)


def test_carry_trade_annualized():
    strat = CarryTradeStrategy()
    carry = strat.get_annualized_carry('EURUSD', lot_size=0.1)

    assert isinstance(carry, float)
