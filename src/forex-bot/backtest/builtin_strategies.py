from __future__ import annotations


from backtest.walk_forward_runner import register_strategy
from backtest.strategies import (
    MACrossStrategy,
    BBStrategy,
    RSIStrategy,
    SRBreakoutStrategy,
    ROCMStrategy,
    MomentumBreakoutStrategy,
    ISignalStrategy,
)
from strategies.grid import GridConfig, GridStrategyAdapter
from backtest.stat_arb import StatArbStrategy


def _make_ma_crossover() -> ISignalStrategy:
    return MACrossStrategy(fast_period=5, slow_period=13, atr_multiplier=2.0)


def _make_bollinger() -> ISignalStrategy:
    return BBStrategy(period=20, std_dev=2.0)


def _make_rsi() -> ISignalStrategy:
    return RSIStrategy(period=14, oversold=35, overbought=65)


def _make_sr_breakout() -> ISignalStrategy:
    return SRBreakoutStrategy(
        lookback=50, confirmation_bars=1, breakout_threshold=0.0001
    )


def _make_roc() -> ISignalStrategy:
    return ROCMStrategy(period=12, roc_threshold=0.3)


def _make_momentum() -> ISignalStrategy:
    return MomentumBreakoutStrategy(
        fast_period=9, slow_period=21, adx_threshold=25.0
    )


def _make_grid(pair: str = "EURUSD") -> ISignalStrategy:
    return GridStrategyAdapter(GridConfig.ftmo(pair))


def _make_stat_arb() -> ISignalStrategy:
    return StatArbStrategy()


def register_builtin_strategies(pair: str = "EURUSD") -> None:
    register_strategy("ma_crossover", _make_ma_crossover)
    register_strategy("bollinger", _make_bollinger)
    register_strategy("rsi", _make_rsi)
    register_strategy("sr_breakout", _make_sr_breakout)
    register_strategy("roc", _make_roc)
    register_strategy("momentum", _make_momentum)
    register_strategy("grid", lambda: _make_grid(pair))
    register_strategy("stat_arb", _make_stat_arb)
