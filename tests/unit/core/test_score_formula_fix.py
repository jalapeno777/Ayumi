"""Test that _compute_score uses non-circular gross_profit/gross_loss."""

import math

from ml.blend_optimizer import StrategyBlendOptimizer


class TestComputeScoreNonCircular:
    def test_score_uses_raw_gross_values(self):
        # With raw values: gp=200, gl=100 → pf=2.0
        score_raw = StrategyBlendOptimizer._compute_score(
            win_rate=0.6,
            total_trades=50,
            max_dd_pct=5.0,
            gross_profit=200.0,
            gross_loss=100.0,
        )

        # The old circular formula would have been:
        # gross_profit = profit_factor * max(total_pnl, 0) — which IS profit_factor
        # gross_loss = max(-total_pnl, 0) — which is just total_pnl if negative
        # This means profit_factor = gross_profit / gross_loss would always be ~1 or inf
        # With raw values, pf=2.0 which should be different from the circular derivation

        # Verify profit_factor is actually 2.0 (not circularly derived)
        expected_pf = 200.0 / 100.0  # 2.0
        dd_factor = 1.0 / (1.0 + 5.0 / 100.0)
        strategy_penalty = 1.0  # default num_active=1
        expected = expected_pf * 0.6 * math.sqrt(50) * dd_factor * strategy_penalty
        assert abs(score_raw - expected) < 0.001

    def test_zero_gross_loss(self):
        score = StrategyBlendOptimizer._compute_score(
            win_rate=0.8,
            total_trades=30,
            max_dd_pct=2.0,
            gross_profit=500.0,
            gross_loss=0.0,
        )
        # Should not crash — pf uses max(gross_loss, 1.0)
        assert score > 0

    def test_zero_trades(self):
        score = StrategyBlendOptimizer._compute_score(
            win_rate=0.5,
            total_trades=0,
            max_dd_pct=0.0,
        )
        assert score == 0.0
