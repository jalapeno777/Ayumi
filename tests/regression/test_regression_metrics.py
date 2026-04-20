from __future__ import annotations

import math
import pickle
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from src.forex_trading.services.backtest.engine_v2 import (
    BacktestEngine,
    WalkForwardConfig,
)
from src.forex_trading.services.backtest.prop_firm_rules import PropFirmConfig
from src.forex_trading.strategies.momentum import MomentumCrossoverStrategy
from src.forex_trading.strategies.mean_reversion import MeanReversionStrategy
from src.forex_trading.strategies.breakout import BreakoutStrategy
from src.forex_trading.strategies.regime_aware import (
    RegimeAwareStrategy,
    RegimeClassifier,
)
from src.forex_trading.strategies.carry import CarryTradeStrategy
from src.forex_trading.strategies.regime_switching_momentum import (
    RegimeSwitchingMomentumStrategy,
)

STRATEGY_CLASSES = [
    MomentumCrossoverStrategy,
    MeanReversionStrategy,
    BreakoutStrategy,
    CarryTradeStrategy,
    RegimeSwitchingMomentumStrategy,
]

PAIRS = ["EURUSD", "GBPUSD"]

PROP_FIRM_CONFIG = PropFirmConfig(
    max_daily_drawdown_pct=0.05,
    max_total_drawdown_pct=0.10,
    profit_target_pct=0.10,
    max_concurrent_positions=2,
    max_daily_trades=10,
)

WF_CONFIG = WalkForwardConfig(train_bars=378, test_bars=756, step_bars=126)

GOLDEN_DIR = Path(__file__).resolve().parent


def _make_strategy(cls, data):
    if cls is RegimeAwareStrategy:
        regime = RegimeClassifier.classify_regime(data)
        return cls(regime=regime)
    return cls()


def _make_engine():
    return BacktestEngine(
        starting_balance=10_000.0,
        prop_firm_config=PROP_FIRM_CONFIG,
        sharpe_annualization_factor=252**0.5,
        use_progressive_sl=False,
    )


def _find_strategy_name(golden, cls):
    for name in golden:
        if name.startswith(cls.__name__.replace("Strategy", "")):
            return name
    return cls.__name__


@pytest.mark.parametrize("strategy_cls", STRATEGY_CLASSES)
@pytest.mark.parametrize("pair", PAIRS)
def test_v1_v2_directional_consistency(strategy_cls, pair, golden_data, h1_data):
    v1 = golden_data[pair]
    data = h1_data[pair]

    name = _find_strategy_name(v1, strategy_cls)
    if name not in v1:
        pytest.skip(f"{name} not in golden dataset")

    v1_single = v1[name]["single"]
    if "error" in v1_single:
        pytest.skip(f"Golden data has error")

    strategy = _make_strategy(strategy_cls, data)
    engine = _make_engine()
    v2_metrics = engine.run_single(strategy, data, pair)

    v1_return = v1_single["total_return"]
    v2_return = v2_metrics.total_return

    if abs(v1_return) < 0.01:
        pytest.skip(
            f"v1 return near zero ({v1_return:.4f}), direction check unreliable"
        )

    same_sign = (v1_return > 0) == (v2_return > 0)
    assert same_sign, (
        f"Direction mismatch: v1_return={v1_return:+.4f}, v2_return={v2_return:+.4f}"
    )


@pytest.mark.parametrize("strategy_cls", STRATEGY_CLASSES)
@pytest.mark.parametrize("pair", PAIRS)
def test_total_trades_within_tolerance(strategy_cls, pair, golden_data, h1_data):
    v1 = golden_data[pair]
    data = h1_data[pair]

    name = _find_strategy_name(v1, strategy_cls)
    if name not in v1:
        pytest.skip(f"{name} not in golden dataset")

    v1_single = v1[name]["single"]
    if "error" in v1_single:
        pytest.skip(f"Golden data has error")

    strategy = _make_strategy(strategy_cls, data)
    engine = _make_engine()
    v2_metrics = engine.run_single(strategy, data, pair)

    v1_trades = v1_single["total_trades"]
    v2_trades = v2_metrics.total_trades

    trade_diff = abs(v2_trades - v1_trades)
    assert trade_diff <= 1, (
        f"Trade count off by {trade_diff}: v1={v1_trades}, v2={v2_trades}"
    )


@pytest.mark.parametrize("strategy_cls", STRATEGY_CLASSES)
@pytest.mark.parametrize("pair", PAIRS)
def test_v2_engine_runs_without_error(strategy_cls, pair, h1_data):
    data = h1_data[pair]
    strategy = _make_strategy(strategy_cls, data)
    engine = _make_engine()

    metrics = engine.run_single(strategy, data, pair)

    assert metrics.total_trades >= 0
    assert metrics.total_return is not None
    assert metrics.win_rate >= 0.0
    assert metrics.win_rate <= 1.0


@pytest.mark.parametrize("strategy_cls", STRATEGY_CLASSES)
@pytest.mark.parametrize("pair", PAIRS)
def test_v2_walk_forward_runs_without_error(strategy_cls, pair, h1_data):
    data = h1_data[pair]
    strategy = _make_strategy(strategy_cls, data)
    engine = _make_engine()

    wf_results = engine.run_walk_forward(strategy, data, pair, WF_CONFIG)

    assert len(wf_results.windows) > 0
    assert wf_results.combined_oos_metrics is not None
    assert wf_results.combined_oos_metrics.total_trades >= 0


@pytest.mark.parametrize("strategy_cls", STRATEGY_CLASSES)
@pytest.mark.parametrize("pair", PAIRS)
def test_v2_walk_forward_pf_cap(strategy_cls, pair, h1_data):
    data = h1_data[pair]
    strategy = _make_strategy(strategy_cls, data)
    engine = _make_engine()

    wf_results = engine.run_walk_forward(strategy, data, pair, WF_CONFIG)

    if wf_results.combined_oos_metrics is None:
        pytest.skip("No combined OOS metrics")

    pf = wf_results.combined_oos_metrics.profit_factor
    assert pf <= 10.0, f"PF cap violated: {pf:.2f} > 10.0"


@pytest.mark.parametrize("strategy_cls", STRATEGY_CLASSES)
@pytest.mark.parametrize("pair", PAIRS)
def test_v2_deterministic_with_seed(strategy_cls, pair, h1_data):
    data = h1_data[pair]
    strategy = _make_strategy(strategy_cls, data)

    np.random.seed(42)
    engine1 = _make_engine()
    m1 = asdict(engine1.run_single(strategy, data, pair))

    np.random.seed(42)
    engine2 = _make_engine()
    m2 = asdict(engine2.run_single(strategy, data, pair))

    for field in METRIC_FIELDS:
        v1, v2 = m1[field], m2[field]
        if math.isnan(v1) and math.isnan(v2):
            continue
        assert v1 == v2, f"Non-deterministic with seed: {field} differs ({v1} vs {v2})"


METRIC_FIELDS = [
    "total_return",
    "sharpe_ratio",
    "max_drawdown",
    "max_drawdown_duration",
    "win_rate",
    "profit_factor",
    "total_trades",
    "avg_trade_duration",
]
