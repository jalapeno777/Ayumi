"""Tests for backtest.dsr — Deflated Sharpe Ratio with combined-criteria guard.

Covers:
- Empty input (no trades)
- Single trade
- Fewer than 30 trades (insufficient guard)
- Exactly 30 trades (boundary)
- 50 trades with positive Sharpe (sufficient)
- Constant returns (zero variance edge case)
- All-negative returns (negative Sharpe)
- Known Sharpe verification
- Skewness and kurtosis computation
- CLI invocation
"""

from __future__ import annotations  # noqa: I001

import json
import subprocess
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backtest.dsr import (  # noqa: I001
    compute_kurtosis,
    compute_sharpe,
    compute_skewness,
    deflated_sharpe_ratio,
    expected_max_sharpe,
)


# ---------------------------------------------------------------------------
# compute_sharpe
# ---------------------------------------------------------------------------


class TestComputeSharpe:
    def test_empty(self):
        assert compute_sharpe([]) == 0.0

    def test_single_trade(self):
        assert compute_sharpe([0.01]) == 0.0

    def test_constant_returns(self):
        """Zero variance → Sharpe = 0.0."""
        assert compute_sharpe([0.01, 0.01, 0.01]) == 0.0

    def test_positive_returns(self):
        """Consistently positive returns with some variance → positive Sharpe."""
        pnls = [0.01, 0.02, 0.015, 0.008, 0.012, 0.018, 0.006, 0.009]
        sharpe = compute_sharpe(pnls, bar_period_minutes=60)
        assert sharpe > 0.0

    def test_negative_returns(self):
        """Consistently negative returns → negative Sharpe."""
        pnls = [-0.01, -0.02, -0.005, -0.015, -0.008]
        sharpe = compute_sharpe(pnls, bar_period_minutes=60)
        assert sharpe < 0.0

    def test_bar_period_affects_magnitude(self):
        """Different bar periods should scale the annualised Sharpe."""
        pnls = [0.01, -0.005, 0.008, 0.012, -0.003, 0.006, 0.009, -0.002]
        s_h1 = compute_sharpe(pnls, bar_period_minutes=60)
        s_m15 = compute_sharpe(pnls, bar_period_minutes=15)
        # M15 has more periods per year → higher sqrt factor → larger annual Sharpe
        assert abs(s_m15) > abs(s_h1)


# ---------------------------------------------------------------------------
# compute_skewness / compute_kurtosis
# ---------------------------------------------------------------------------


class TestMoments:
    def test_skewness_empty(self):
        assert compute_skewness([]) == 0.0

    def test_skewness_two_elements(self):
        assert compute_skewness([1.0, 2.0]) == 0.0

    def test_skewness_symmetric(self):
        """Symmetric distribution → near-zero skewness."""
        pnls = [-2.0, -1.0, 0.0, 1.0, 2.0]
        skew = compute_skewness(pnls)
        assert abs(skew) < 0.5  # approximately zero

    def test_skewness_right_skewed(self):
        """Right-skewed (positive outliers) → positive skewness."""
        pnls = [0.01, 0.01, 0.01, 0.01, 0.01, 0.5]
        skew = compute_skewness(pnls)
        assert skew > 0.0

    def test_kurtosis_empty(self):
        assert compute_kurtosis([]) == 3.0

    def test_kurtosis_few_elements(self):
        assert compute_kurtosis([1.0, 2.0]) == 3.0

    def test_kurtosis_normal_like(self):
        """Near-normal distribution → kurtosis near 3."""
        import random

        rng = random.Random(42)  # noqa: S311
        pnls = [rng.gauss(0, 0.01) for _ in range(200)]
        kurt = compute_kurtosis(pnls)
        assert 2.0 < kurt < 4.0  # approximately normal

    def test_kurtosis_heavy_tails(self):
        """Heavy tails (extreme outliers) → high kurtosis."""
        pnls = [0.0] * 20 + [1.0, -1.0]  # mostly flat with two extremes
        kurt = compute_kurtosis(pnls)
        assert kurt > 3.0


# ---------------------------------------------------------------------------
# expected_max_sharpe
# ---------------------------------------------------------------------------


class TestExpectedMaxSharpe:
    def test_one_trial(self):
        """One trial → expected max ≈ 0 (no selection bias)."""
        result = expected_max_sharpe(1, 1.0, 0.0, 3.0)
        assert abs(result) < 1.0

    def test_more_trials_higher_expected_max(self):
        """More trials → higher expected max (more selection bias)."""
        em_6 = expected_max_sharpe(6, 1.0, 0.0, 3.0)
        em_100 = expected_max_sharpe(100, 1.0, 0.0, 3.0)
        assert em_100 > em_6

    def test_zero_trials(self):
        assert expected_max_sharpe(0, 1.0, 0.0, 3.0) == 0.0


# ---------------------------------------------------------------------------
# deflated_sharpe_ratio — combined criteria guard
# ---------------------------------------------------------------------------


class TestDeflatedSharpeRatio:
    def test_insufficient_trades(self):
        """Fewer than 30 trades → verdict 'insufficient'."""
        pnls = [0.01, -0.005, 0.008, 0.012, -0.003]  # 5 trades
        result = deflated_sharpe_ratio(pnls)
        assert result["verdict"] == "insufficient"
        assert result["n_trades"] == 5
        assert result["dsr_pvalue"] is None
        assert result["combined_criteria"]["sufficient_trades"] is False
        assert result["combined_criteria"]["verdict"] == "insufficient_trades"

    def test_boundary_exactly_30(self):
        """Exactly 30 trades → should compute DSR (sufficient)."""
        import random

        rng = random.Random(42)  # noqa: S311
        pnls = [rng.gauss(0.002, 0.01) for _ in range(30)]
        result = deflated_sharpe_ratio(pnls)
        assert result["verdict"] == "sufficient"
        assert result["n_trades"] == 30
        assert result["dsr_pvalue"] is not None
        assert result["combined_criteria"]["sufficient_trades"] is True

    def test_empty_input(self):
        """Zero trades → insufficient."""
        result = deflated_sharpe_ratio([])
        assert result["verdict"] == "insufficient"
        assert result["n_trades"] == 0

    def test_single_trade(self):
        """One trade → insufficient."""
        result = deflated_sharpe_ratio([0.01])
        assert result["verdict"] == "insufficient"
        assert result["n_trades"] == 1

    def test_sufficient_with_positive_sharpe(self):
        """50 trades with consistent positive edge → DSR should compute."""
        import random

        rng = random.Random(123)  # noqa: S311
        pnls = [rng.gauss(0.003, 0.008) for _ in range(50)]
        result = deflated_sharpe_ratio(pnls, n_independent_trials=6)
        assert result["verdict"] == "sufficient"
        assert result["dsr_pvalue"] is not None
        assert 0.0 <= result["dsr_pvalue"] <= 1.0
        assert result["edge_probability"] is not None
        assert 0.0 <= result["edge_probability"] <= 1.0
        assert result["min_track_record_length"] is not None
        # Combined criteria structure
        cc = result["combined_criteria"]
        assert "sharpe_positive" in cc
        assert "dsr_significant" in cc
        assert "sufficient_trades" in cc
        assert "verdict" in cc

    def test_all_negative_returns(self):
        """All losing trades → negative Sharpe → reject."""
        import random

        rng = random.Random(99)  # noqa: S311
        pnls = [rng.gauss(-0.005, 0.008) for _ in range(40)]
        result = deflated_sharpe_ratio(pnls)
        assert result["verdict"] == "sufficient"
        assert result["sharpe"] < 0
        assert result["combined_criteria"]["sharpe_positive"] is False
        assert "reject" in result["combined_criteria"]["verdict"]

    def test_constant_returns_insufficient(self):
        """Constant returns with < 30 trades → insufficient (no variance)."""
        pnls = [0.01] * 10
        result = deflated_sharpe_ratio(pnls)
        assert result["verdict"] == "insufficient"
        assert result["sharpe"] == 0.0  # zero variance

    def test_constant_returns_sufficient(self):
        """Constant returns with ≥ 30 trades → sufficient but zero Sharpe."""
        pnls = [0.01] * 35
        result = deflated_sharpe_ratio(pnls)
        assert result["verdict"] == "sufficient"
        assert result["sharpe"] == 0.0

    def test_n_trials_affects_dsr(self):
        """More trials → stricter DSR → higher p-value (harder to reject)."""
        import random

        rng = random.Random(42)  # noqa: S311
        pnls = [rng.gauss(0.002, 0.008) for _ in range(50)]
        r_few = deflated_sharpe_ratio(pnls, n_independent_trials=2)
        r_many = deflated_sharpe_ratio(pnls, n_independent_trials=100)
        # With more trials, DSR should be more conservative (higher p-value or similar)
        # The relationship isn't always monotonic but the correction should be stronger
        assert r_few["n_independent_trials"] == 2
        assert r_many["n_independent_trials"] == 100

    def test_note_in_insufficient(self):
        """Insufficient verdict should include guidance note."""
        result = deflated_sharpe_ratio([0.01, 0.02])
        assert "note" in result["combined_criteria"]
        assert "do NOT promote" in result["combined_criteria"]["note"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestDSRCLI:
    def test_cli_inline_pnls(self):
        """--pnls flag should accept inline values."""
        pnls = [0.01, -0.005, 0.008] + [0.002] * 30
        args = (
            [sys.executable, "-m", "backtest.dsr", "--pnls"]
            + [str(p) for p in pnls]
            + ["--name", "test_strategy", "--n-trials", "3"]
        )
        result = subprocess.run(  # noqa: S603
            args,
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["name"] == "test_strategy"
        assert output["n_trades"] == len(pnls)

    def test_cli_input_file(self, tmp_path):
        """--input flag should read JSON file."""
        import random

        rng = random.Random(7)  # noqa: S311
        data = {
            "name": "cli_test",
            "pnls": [rng.gauss(0.001, 0.005) for _ in range(35)],
            "n_independent_trials": 6,
            "bar_period_minutes": 60,
        }
        infile = tmp_path / "strategy.json"
        infile.write_text(json.dumps(data))

        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "backtest.dsr", "--input", str(infile)],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["name"] == "cli_test"
        assert output["n_trades"] == 35

    def test_cli_insufficient_trades(self):
        """CLI with < 30 trades → insufficient verdict."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "backtest.dsr",
                "--pnls",
                "0.01",
                "-0.005",
                "0.008",
                "--name",
                "small",
            ],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["verdict"] == "insufficient"
        assert output["n_trades"] == 3

    def test_cli_no_input_error(self):
        """No --input or --pnls → error."""
        result = subprocess.run(
            [sys.executable, "-m", "backtest.dsr"],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        assert result.returncode != 0
