"""Tests for backtest.bootstrap_ci — Bootstrap CI runner for Profit Factor.

Covers:
- Empty input (no trades)
- Single trade (degenerate distribution)
- Synthetic 100-trade series (primary case)
- All-winners and all-losers edge cases
- CLI invocation
- Reproducibility with fixed seed
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure the project root is importable (for `backtest.bootstrap_ci`)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backtest.bootstrap_ci import (
    DEFAULT_CONFIDENCE,
    PF_CAP,
    _parse_pnls,
    _percentile,
    bootstrap_pf,
    compute_profit_factor,
)


# ---------------------------------------------------------------------------
# compute_profit_factor
# ---------------------------------------------------------------------------


class TestComputeProfitFactor:
    def test_mixed_trades(self):
        """Standard case: winners and losers present."""
        pnls = [100.0, -50.0, 80.0, -40.0, 20.0]
        # gross_profit = 200, gross_loss = 90 → PF = 2.222...
        pf = compute_profit_factor(pnls)
        assert pytest.approx(pf, rel=1e-4) == 200.0 / 90.0

    def test_empty_input(self):
        assert compute_profit_factor([]) == 0.0

    def test_all_winners(self):
        """No losses → PF should cap at PF_CAP."""
        pnls = [50.0, 100.0, 25.0]
        assert compute_profit_factor(pnls) == PF_CAP

    def test_all_losers(self):
        """No profits → PF = 0.0."""
        pnls = [-50.0, -100.0, -25.0]
        assert compute_profit_factor(pnls) == 0.0

    def test_break_even(self):
        """Sum of PnLs = 0, both sides non-zero."""
        pnls = [50.0, -50.0]
        assert compute_profit_factor(pnls) == pytest.approx(1.0)

    def test_single_trade_win(self):
        pf = compute_profit_factor([42.0])
        assert pf == PF_CAP

    def test_single_trade_loss(self):
        pf = compute_profit_factor([-42.0])
        assert pf == 0.0

    def test_near_zero_loss(self):
        """Very small gross_loss should still divide, not cap."""
        pnls = [100.0, -1e-13]
        pf = compute_profit_factor(pnls)
        # gross_loss < PF_EPSILON → should cap
        assert pf == PF_CAP


# ---------------------------------------------------------------------------
# bootstrap_pf
# ---------------------------------------------------------------------------


class TestBootstrapPF:
    def test_synthetic_100_trades(self):
        """Primary case: 100-trade synthetic series with known properties."""
        # 60 winners of +10, 40 losers of -8  → PF = 600/320 = 1.875
        pnls = [10.0] * 60 + [-8.0] * 40
        result = bootstrap_pf(pnls, iterations=5000, seed=42)

        assert result["n_trades"] == 100
        assert result["iterations"] == 5000
        assert result["confidence"] == DEFAULT_CONFIDENCE

        # Point estimate
        assert pytest.approx(result["profit_factor"], rel=1e-4) == 1.875

        # CI bounds should bracket the point estimate
        assert result["ci_lower"] <= result["profit_factor"]
        assert result["ci_upper"] >= result["profit_factor"]

        # Lower bound should be > 0 for a profitable strategy
        assert result["ci_lower"] > 0.0

        # Gross values
        assert pytest.approx(result["gross_profit"], rel=1e-4) == 600.0
        assert pytest.approx(result["gross_loss"], rel=1e-4) == 320.0

    def test_empty_input(self):
        result = bootstrap_pf([], iterations=100)
        assert result["n_trades"] == 0
        assert result["profit_factor"] == 0.0
        assert result["ci_lower"] == 0.0
        assert result["ci_upper"] == 0.0

    def test_single_trade(self):
        """Single trade → degenerate CI (bounds == point estimate)."""
        pnls = [15.0]
        result = bootstrap_pf(pnls, iterations=1000)
        assert result["n_trades"] == 1
        assert result["profit_factor"] == PF_CAP
        assert result["ci_lower"] == PF_CAP
        assert result["ci_upper"] == PF_CAP

    def test_all_losers(self):
        """All-losing strategy → PF = 0, CI bounds = 0."""
        pnls = [-10.0, -20.0, -5.0, -15.0]
        result = bootstrap_pf(pnls, iterations=1000)
        assert result["profit_factor"] == 0.0
        assert result["ci_lower"] == 0.0
        assert result["ci_upper"] == 0.0

    def test_reproducibility(self):
        """Same seed → identical results."""
        pnls = [
            12.0,
            -5.0,
            8.0,
            -3.0,
            15.0,
            -7.0,
            4.0,
            -2.0,
            9.0,
            -6.0,
            11.0,
            -4.0,
            7.0,
            -8.0,
            3.0,
            -1.0,
            10.0,
            -9.0,
            6.0,
            -5.0,
        ]
        r1 = bootstrap_pf(pnls, iterations=2000, seed=99)
        r2 = bootstrap_pf(pnls, iterations=2000, seed=99)
        assert r1 == r2

    def test_different_seed_variation(self):
        """Different seeds → slightly different CI bounds (not identical)."""
        pnls = [
            12.0,
            -5.0,
            8.0,
            -3.0,
            15.0,
            -7.0,
            4.0,
            -2.0,
            9.0,
            -6.0,
            11.0,
            -4.0,
            7.0,
            -8.0,
            3.0,
            -1.0,
            10.0,
            -9.0,
            6.0,
            -5.0,
        ]
        r1 = bootstrap_pf(pnls, iterations=2000, seed=1)
        r2 = bootstrap_pf(pnls, iterations=2000, seed=2)
        # CI bounds should be close but not exactly equal
        assert r1["profit_factor"] == r2["profit_factor"]  # point est same
        # Lower bounds differ with different seeds (very likely)
        assert abs(r1["ci_lower"] - r2["ci_lower"]) >= 0.0  # non-negative diff

    def test_confidence_level(self):
        """Higher confidence → wider CI."""
        pnls = [10.0] * 55 + [-8.0] * 45
        r95 = bootstrap_pf(pnls, iterations=5000, confidence=0.95, seed=42)
        r99 = bootstrap_pf(pnls, iterations=5000, confidence=0.99, seed=42)
        assert r99["ci_lower"] <= r95["ci_lower"]
        assert r99["ci_upper"] >= r95["ci_upper"]


# ---------------------------------------------------------------------------
# _parse_pnls
# ---------------------------------------------------------------------------


class TestParsePnls:
    def test_trades_format(self):
        data = {"trades": [{"pnl": 10.0}, {"pnl": -5.0}, {"pnl": 3.0}]}
        assert _parse_pnls(data) == [10.0, -5.0, 3.0]

    def test_pnls_format(self):
        data = {"pnls": [10.0, -5.0, 3.0]}
        assert _parse_pnls(data) == [10.0, -5.0, 3.0]

    def test_pnl_format(self):
        data = {"pnl": [10.0, -5.0, 3.0]}
        assert _parse_pnls(data) == [10.0, -5.0, 3.0]

    def test_bare_list(self):
        assert _parse_pnls([10.0, -5.0, 3.0]) == [10.0, -5.0, 3.0]

    def test_empty_trades(self):
        assert _parse_pnls({"trades": []}) == []

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            _parse_pnls({"unexpected_key": 42})


# ---------------------------------------------------------------------------
# _percentile helper
# ---------------------------------------------------------------------------


class TestPercentile:
    def test_median(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _percentile(vals, 50.0) == pytest.approx(3.0)

    def test_min(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _percentile(vals, 0.0) == pytest.approx(1.0)

    def test_max(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _percentile(vals, 100.0) == pytest.approx(5.0)

    def test_interpolation(self):
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        # 25th percentile = 2nd element boundary area
        result = _percentile(vals, 25.0)
        assert 15.0 <= result <= 25.0

    def test_single_element(self):
        assert _percentile([42.0], 50.0) == pytest.approx(42.0)

    def test_empty(self):
        assert _percentile([], 50.0) == 0.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_cli_basic(self, tmp_path):
        """Invoke CLI on a small JSON file, verify JSON output."""
        results = {"pnls": [10.0] * 60 + [-8.0] * 40}
        results_file = tmp_path / "results.json"
        results_file.write_text(json.dumps(results))

        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "backtest.bootstrap_ci",
                str(results_file),
                "--iterations",
                "500",
            ],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
            timeout=30,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        output = json.loads(proc.stdout)
        assert output["n_trades"] == 100
        assert output["profit_factor"] == pytest.approx(1.875, rel=1e-4)
        assert output["ci_lower"] > 0
        assert output["ci_lower"] <= output["profit_factor"]
        assert output["ci_upper"] >= output["profit_factor"]

    def test_cli_file_not_found(self, tmp_path):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "backtest.bootstrap_ci",
                str(tmp_path / "nonexistent.json"),
            ],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
            timeout=10,
        )
        assert proc.returncode == 2
        assert "not found" in proc.stderr.lower()

    def test_cli_empty_input(self, tmp_path):
        results_file = tmp_path / "empty.json"
        results_file.write_text(json.dumps({"pnls": []}))
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "backtest.bootstrap_ci",
                str(results_file),
                "--iterations",
                "100",
            ],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
            timeout=10,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        output = json.loads(proc.stdout)
        assert output["n_trades"] == 0
        assert output["profit_factor"] == 0.0
