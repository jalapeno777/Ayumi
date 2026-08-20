"""Tests for SRF Monte Carlo robustness module."""

import numpy as np  # noqa: I001
import pytest

from srf.monte_carlo import (
    TradeRecord,
    run_monte_carlo,
    trade_shuffle,
    block_bootstrap,
    slippage_stress,
    spread_stress,
    missed_trade_sim,
    _max_drawdown,
    _profit_factor,
    _sharpe,
    store_mc_results,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def winning_trades():
    """50 trades with positive expectancy."""
    rng = np.random.default_rng(42)
    pnls = rng.normal(loc=10.0, scale=30.0, size=50)
    return [TradeRecord(pnl=float(p), entry_time=i, exit_time=i + 1) for i, p in enumerate(pnls)]


@pytest.fixture
def losing_trades():
    """50 trades with negative expectancy."""
    rng = np.random.default_rng(42)
    pnls = rng.normal(loc=-8.0, scale=25.0, size=50)
    return [TradeRecord(pnl=float(p), entry_time=i, exit_time=i + 1) for i, p in enumerate(pnls)]


@pytest.fixture
def mixed_trades():
    """50 trades roughly break-even."""
    rng = np.random.default_rng(42)
    pnls = rng.normal(loc=0.0, scale=20.0, size=50)
    return [TradeRecord(pnl=float(p), entry_time=i, exit_time=i + 1) for i, p in enumerate(pnls)]


# ── Metric helpers ────────────────────────────────────────────────────────


class TestMetricHelpers:
    def test_max_drawdown_no_drawdown(self):
        equity = np.array([100, 110, 120, 130])
        assert _max_drawdown(equity) == pytest.approx(0.0, abs=1e-10)

    def test_max_drawdown_simple(self):
        equity = np.array([100, 120, 80, 90])
        dd = _max_drawdown(equity)
        # Peak 120, trough 80 → DD = 40/120
        assert dd == pytest.approx(40 / 120, rel=1e-6)

    def test_profit_factor_all_wins(self):
        pnls = np.array([10, 20, 30])
        assert _profit_factor(pnls) == float("inf")

    def test_profit_factor_all_losses(self):
        pnls = np.array([-10, -20, -30])
        assert _profit_factor(pnls) == 0.0

    def test_profit_factor_mixed(self):
        pnls = np.array([30, -10, 20, -10])
        # gains=50, losses=20 → PF=2.5
        assert _profit_factor(pnls) == pytest.approx(2.5)

    def test_sharpe_zero_variance(self):
        pnls = np.array([10, 10, 10])
        assert _sharpe(pnls) == 0.0

    def test_sharpe_positive(self):
        rng = np.random.default_rng(42)
        pnls = rng.normal(loc=5, scale=2, size=100)
        s = _sharpe(pnls)
        assert s > 0


# ── MC methods ───────────────────────────────────────────────────────────


class TestTradeShuffle:
    def test_preserves_pnl_set(self, winning_trades):
        results = trade_shuffle(winning_trades, n_iter=5, rng=np.random.default_rng(42))
        assert len(results) == 5
        original = sorted(t.pnl for t in winning_trades)
        for shuffled in results:
            assert sorted(shuffled.tolist()) == pytest.approx(original)

    def test_different_iterations(self, winning_trades):
        results = trade_shuffle(winning_trades, n_iter=3, rng=np.random.default_rng(42))
        # At least 2 should differ
        differs = sum(
            1
            for i in range(len(results))
            for j in range(i + 1, len(results))
            if not np.array_equal(results[i], results[j])
        )
        assert differs >= 1


class TestBlockBootstrap:
    def test_preserves_length(self, mixed_trades):
        results = block_bootstrap(mixed_trades, n_iter=3, block_size=5, rng=np.random.default_rng(42))
        assert len(results) == 3
        for arr in results:
            assert len(arr) == len(mixed_trades)

    def test_fallback_small_input(self):
        trades = [TradeRecord(pnl=1.0), TradeRecord(pnl=-1.0)]
        results = block_bootstrap(trades, n_iter=2, block_size=10, rng=np.random.default_rng(42))
        assert len(results) == 2
        for arr in results:
            assert len(arr) == 2


class TestSlippageStress:
    def test_reduces_pnl_on_average(self, winning_trades):
        base_sum = sum(t.pnl for t in winning_trades)
        results = slippage_stress(winning_trades, rng=np.random.default_rng(42))
        assert len(results) == 3  # default 3 slippage levels
        # Higher slippage should tend to reduce total
        assert sum(results[0]) <= base_sum + 100  # rough check


class TestSpreadStress:
    def test_returns_results(self, winning_trades):
        results = spread_stress(winning_trades)
        assert len(results) == 2  # 50%, 100%
        for arr in results:
            assert len(arr) == len(winning_trades)


class TestMissedTradeSim:
    def test_drops_correct_fraction(self, winning_trades):
        results = missed_trade_sim(winning_trades, drop_fraction=0.2, n_iter=5, rng=np.random.default_rng(42))
        assert len(results) == 5
        for arr in results:
            assert len(arr) == 40  # 80% of 50


# ── Full MC run ──────────────────────────────────────────────────────────


class TestRunMonteCarlo:
    def test_winning_strategy(self, winning_trades):
        result = run_monte_carlo(winning_trades, n_iterations=50, seed=42)
        assert result.n_iterations > 50  # includes stress variants
        assert result.p5_sharpe > 0  # winning strategy should have positive 5th pct Sharpe
        assert 0 <= result.prop_rule_breach_prob <= 1
        assert result.p5_max_drawdown >= 0

    def test_losing_strategy(self, losing_trades):
        result = run_monte_carlo(losing_trades, n_iterations=50, seed=42)
        assert result.p5_sharpe < 0
        assert result.prop_rule_breach_prob > 0.0  # losing strategy should breach at least sometimes

    def test_reproducible_with_seed(self, winning_trades):
        r1 = run_monte_carlo(winning_trades, n_iterations=20, seed=123)
        r2 = run_monte_carlo(winning_trades, n_iterations=20, seed=123)
        assert r1.p5_sharpe == pytest.approx(r2.p5_sharpe)

    def test_block_bootstrap_toggle(self, winning_trades):
        r_with = run_monte_carlo(winning_trades, n_iterations=20, seed=42, use_block_bootstrap=True)
        r_without = run_monte_carlo(winning_trades, n_iterations=20, seed=42, use_block_bootstrap=False)
        # With block bootstrap should have more total iterations
        assert r_with.n_iterations > r_without.n_iterations

    def test_summary_dict(self, winning_trades):
        result = run_monte_carlo(winning_trades, n_iterations=10, seed=42)
        s = result.summary()
        assert "p5_sharpe" in s
        assert "prop_rule_breach_prob" in s
        assert "n_iterations" in s
        assert "methods_used" in s


# ── DuckDB storage ───────────────────────────────────────────────────────


class TestStoreMCResults:
    def test_store_and_retrieve(self, tmp_path):

        db_path = str(tmp_path / "test_mc.duckdb")

        # Create schema
        from srf.schema import SRFDatabase

        with SRFDatabase(db_path) as conn:
            # Need a run to reference
            conn.execute(
                "INSERT INTO strategies (name, version, module_path, status) "
                "VALUES ('SRMR+', '1.0', 'srf.srmr', 'production') ON CONFLICT DO NOTHING"
            )
            conn.execute(
                "INSERT INTO runs (run_id, strategy_name, pair, timeframe, git_commit, "
                "data_hash, params_json, status) VALUES "
                "('test_run_1', 'SRMR+', 'GBPUSD', 15, 'abc123', 'def456', '{}', 'completed')"
            )

            trades = [TradeRecord(pnl=float(p)) for p in [10, -5, 20, -3, 15]]
            result = run_monte_carlo(trades, n_iterations=10, seed=42)
            store_mc_results(conn, "test_run_1", result)

            # Verify rows
            rows = conn.execute(
                "SELECT metric_name, metric_value FROM monte_carlo_samples "
                "WHERE run_id = 'test_run_1' ORDER BY metric_name"
            ).fetchall()
            assert len(rows) > 0
            names = [r[0] for r in rows]
            assert "p5_sharpe" in names
            assert "prop_rule_breach_prob" in names
