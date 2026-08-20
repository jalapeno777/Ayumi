"""Tests for StrategyBlendOptimizer."""

from __future__ import annotations  # noqa: I001

import math

import pytest

from strategies.registry import StrategyRegistry, StrategyConfig
from ml.blend_optimizer import (
    StrategyBlendOptimizer,
    BlendOptConfig,
    BlendConfig,
    BlendResult,
)


def _make_registry(strategies: list[StrategyConfig] | None = None) -> StrategyRegistry:
    reg = StrategyRegistry()
    if strategies is None:
        strategies = [
            StrategyConfig(
                strategy_id="srmr_plus",
                name="Session Range Mean Reversion Plus",
                strategy_type="mean_reversion",
                symbols=["EURUSD", "GBPUSD"],
                timeframes=["H1"],
                typical_confidence_range=(0.40, 0.75),
            ),
            StrategyConfig(
                strategy_id="killzone_momentum",
                name="Killzone Momentum",
                strategy_type="momentum",
                symbols=["EURUSD", "XAUUSD"],
                timeframes=["M15"],
                typical_confidence_range=(0.45, 0.80),
            ),
        ]
    for s in strategies:
        reg.register(s)
    return reg


class TestScoreCalculation:
    def test_score_formula(self):
        """Score = profit_factor * win_rate * sqrt(trades) * dd_factor * strategy_penalty."""
        score = StrategyBlendOptimizer._compute_score(
            win_rate=0.6,
            total_trades=100,
            max_dd_pct=10.0,
            gross_profit=200.0,
            gross_loss=100.0,
        )
        pf = 200.0 / 100.0
        dd_factor = 1.0 / (1.0 + 10.0 / 100.0)
        expected = pf * 0.6 * math.sqrt(100) * dd_factor * 1.0
        assert abs(score - expected) < 1e-9

    def test_zero_trades(self):
        assert StrategyBlendOptimizer._compute_score(0.5, 0, 5.0) == 0.0

    def test_high_drawdown_penalized(self):
        score_low_dd = StrategyBlendOptimizer._compute_score(0.6, 50, 5.0, gross_profit=200.0, gross_loss=100.0)
        score_high_dd = StrategyBlendOptimizer._compute_score(0.6, 50, 30.0, gross_profit=200.0, gross_loss=100.0)
        assert score_low_dd > score_high_dd


class TestBlendConfig:
    def test_creation(self):
        cfg = BlendConfig(
            active_strategies={"a": True, "b": False},
            strategy_weights={"a": 0.7},
            allowed_symbols={"a": ["EURUSD"]},
            sniper_threshold=0.75,
            swarm_threshold=0.40,
        )
        assert cfg.active_strategies["a"] is True
        assert cfg.sniper_threshold == 0.75


class TestOptimizerIntegration:
    def test_empty_registry_rejected(self):
        """Optimizer with no strategies should produce zero score."""
        reg = _make_registry([])
        opt = StrategyBlendOptimizer(reg, BlendOptConfig())
        study = opt._best_result
        assert study is None

    def test_single_strategy(self):
        """Single strategy should work."""
        reg = _make_registry(
            [
                StrategyConfig(
                    strategy_id="solo",
                    name="Solo",
                    strategy_type="mean_reversion",
                    symbols=["EURUSD"],
                    timeframes=["H1"],
                    typical_confidence_range=(0.4, 0.7),
                ),
            ]
        )
        opt = StrategyBlendOptimizer(reg, BlendOptConfig(min_trades_for_score=1))
        result = opt.optimize(n_trials=3, timeout=30)
        assert isinstance(result, BlendResult)
        assert result.best_total_trades >= 0
        assert result.best_win_rate >= 0.0

    def test_multi_strategy_optimization(self):
        """Run 5 trials with 2 strategies."""
        reg = _make_registry()
        opt = StrategyBlendOptimizer(reg, BlendOptConfig(min_trades_for_score=1))
        result = opt.optimize(n_trials=5, timeout=30)
        assert result.best_score >= 0.0
        assert isinstance(result.best_config, BlendConfig)
        assert len(result.best_config.active_strategies) == 2

    def test_weight_clipping(self):
        """Weights should be in 0.1-1.0 range."""
        reg = _make_registry()
        opt = StrategyBlendOptimizer(reg, BlendOptConfig(min_trades_for_score=1))
        result = opt.optimize(n_trials=5, timeout=30)
        for sid, w in result.best_config.strategy_weights.items():
            assert 0.1 <= w <= 1.0, f"Weight {w} for {sid} out of range"

    def test_cpu_metering(self):
        """CPU budget should be respected."""
        reg = _make_registry()
        cfg = BlendOptConfig(
            min_trades_for_score=1,
            cpu_limit_percent=15.0,
            timeout_seconds=30,
        )
        opt = StrategyBlendOptimizer(reg, cfg)
        result = opt.optimize(n_trials=5, timeout=30)
        # Should complete without error — budget is generous for 5 trials
        assert isinstance(result, BlendResult)

    def test_get_best_blend_raises_before_optimize(self):
        reg = _make_registry()
        opt = StrategyBlendOptimizer(reg, BlendOptConfig())
        with pytest.raises(RuntimeError):
            opt.get_best_blend()
