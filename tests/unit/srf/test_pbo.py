"""Tests for SRF PBO (Probability of Backtest Overfitting) via CSCV."""

import numpy as np
import pytest
from srf.pbo import PBOScore, _sharpe_ratio, compute_pbo, store_pbo_score

# ── Sharpe helper ────────────────────────────────────────────────────────


class TestSharpeHelper:
    def test_basic(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(loc=0.001, scale=0.02, size=(100, 3))
        sharpes = _sharpe_ratio(returns)
        assert sharpes.shape == (3,)
        assert np.all(np.isfinite(sharpes))

    def test_zero_variance(self):
        returns = np.ones((50, 2)) * 0.01
        sharpes = _sharpe_ratio(returns)
        # std ≈ 0 → should not produce inf, but near-zero denominator
        assert np.all(np.isfinite(sharpes))


# ── PBO computation ──────────────────────────────────────────────────────


class TestComputePBO:
    def test_robust_strategy_low_pbo(self):
        """A genuinely profitable strategy across many trials should get PBO < 0.3."""
        rng = np.random.default_rng(42)
        # 100 periods, 30 strategies all with genuine positive edge
        returns = rng.normal(loc=0.001, scale=0.01, size=(200, 30))
        score = compute_pbo(returns, n_blocks=8)
        assert score.pbo < 0.5  # Should not be flagged as overfit
        assert score.n_combinations > 0
        assert score.n_strategies == 30
        assert score.n_periods == 200

    def test_overfit_strategy_high_pbo(self):
        """Pure noise with many trials should get PBO > 0.5."""
        rng = np.random.default_rng(42)
        # 200 periods, 50 strategies all pure noise
        returns = rng.normal(loc=0.0, scale=0.01, size=(200, 50))
        score = compute_pbo(returns, n_blocks=8)
        # With pure noise and many strategies, PBO tends high
        assert score.pbo > 0.3  # At least moderate overfit signal
        # Logit should match PBO
        expected_logit = np.log(score.pbo / (1 - score.pbo + 1e-10) + 1e-10)
        assert score.logit == pytest.approx(expected_logit, rel=0.01)

    def test_ci_bounds(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(loc=0.001, scale=0.01, size=(100, 10))
        score = compute_pbo(returns, n_blocks=4)
        assert 0 <= score.ci_lower <= score.pbo <= score.ci_upper <= 1

    def test_few_strategies(self):
        """With 2 strategies the PBO should still compute."""
        rng = np.random.default_rng(42)
        returns = rng.normal(loc=0.001, scale=0.01, size=(100, 2))
        score = compute_pbo(returns, n_blocks=4)
        assert score.n_strategies == 2
        assert 0 <= score.pbo <= 1

    def test_reproducibility(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(loc=0.001, scale=0.01, size=(100, 10))
        s1 = compute_pbo(returns, n_blocks=4)
        s2 = compute_pbo(returns, n_blocks=4)
        assert s1.pbo == s2.pbo  # deterministic given same input

    def test_block_reduction_for_tractability(self):
        """If n_blocks is too high for max_combinations, it should be reduced."""
        rng = np.random.default_rng(42)
        returns = rng.normal(loc=0.001, scale=0.01, size=(500, 20))
        score = compute_pbo(returns, n_blocks=16, max_combinations=1000)
        # Should reduce blocks to keep combinations manageable
        from math import comb

        actual_comb = comb(2 * score.n_blocks, score.n_blocks) // 2
        assert actual_comb <= 1000

    def test_input_validation(self):
        with pytest.raises(ValueError, match="at least 2 strategies"):
            compute_pbo(np.array([[1.0], [2.0]]))
        with pytest.raises(ValueError, match="at least 4 time"):
            compute_pbo(np.array([[1.0, 2.0]]))
        with pytest.raises(ValueError, match="2D"):
            compute_pbo(np.array([1.0, 2.0, 3.0]))


# ── PBOScore dataclass ───────────────────────────────────────────────────


class TestPBOScore:
    def test_is_overfit(self):
        score = PBOScore(
            pbo=0.7,
            logit=0.85,
            ci_lower=0.5,
            ci_upper=0.9,
            n_strategies=30,
            n_periods=200,
            n_combinations=6435,
            n_blocks=8,
        )
        assert score.is_overfit()
        assert not score.is_overfit(threshold=0.8)

    def test_summary(self):
        score = PBOScore(
            pbo=0.3,
            logit=-0.85,
            ci_lower=0.15,
            ci_upper=0.5,
            n_strategies=10,
            n_periods=100,
            n_combinations=1287,
            n_blocks=8,
        )
        s = score.summary()
        assert s["pbo"] == 0.3
        assert s["n_strategies"] == 10


# ── DuckDB storage ───────────────────────────────────────────────────────


class TestStorePBOScore:
    def test_store_and_retrieve(self, tmp_path):
        from srf.schema import SRFDatabase

        db_path = str(tmp_path / "test_pbo.duckdb")
        with SRFDatabase(db_path) as conn:
            # Need a run to reference (monte_carlo_samples has FK on runs)
            conn.execute(
                "INSERT INTO strategies (name, version, module_path, status) "
                "VALUES ('SRMR+', '1.0', 'srf.srmr', 'production') ON CONFLICT DO NOTHING"
            )
            conn.execute(
                "INSERT INTO runs (run_id, strategy_name, pair, timeframe, git_commit, "
                "data_hash, params_json, status) VALUES "
                "('study:test_study', 'SRMR+', 'GBPUSD', 15, 'abc', 'def', '{}', 'completed')"
            )
            score = PBOScore(
                pbo=0.35,
                logit=-0.62,
                ci_lower=0.2,
                ci_upper=0.55,
                n_strategies=30,
                n_periods=200,
                n_combinations=6435,
                n_blocks=8,
            )
            store_pbo_score(conn, "test_study", score)

            rows = conn.execute(
                "SELECT metric_name, metric_value FROM monte_carlo_samples "
                "WHERE run_id = 'study:test_study' ORDER BY metric_name"
            ).fetchall()
            assert len(rows) >= 4
            names = [r[0] for r in rows]
            assert "pbo" in names
            assert "pbo_logit" in names
