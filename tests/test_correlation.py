"""Tests for backtest.correlation — Cross-strategy correlation matrix.

Covers:
- Empty input (no strategies)
- Single strategy (trivial 1×1 matrix)
- Two strategies with perfect positive/negative/zero correlation
- Three strategies with known correlation structure
- Constant returns (zero variance edge case)
- Single-element returns (insufficient overlap)
- CLI invocation
- High correlation detection
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backtest.correlation import (  # noqa: I001
    compute_correlation_matrix,
    pearson_correlation,
)


# ---------------------------------------------------------------------------
# pearson_correlation
# ---------------------------------------------------------------------------


class TestPearsonCorrelation:
    def test_perfect_positive(self):
        """Identical series → correlation = 1.0."""
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert pearson_correlation(x, x) == pytest.approx(1.0, abs=1e-6)

    def test_perfect_negative(self):
        """Mirror series → correlation = -1.0."""
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [-1.0, -2.0, -3.0, -4.0, -5.0]
        assert pearson_correlation(x, y) == pytest.approx(-1.0, abs=1e-6)

    def test_zero_correlation(self):
        """Orthogonal-ish series → near-zero correlation."""
        x = [1.0, -1.0, 1.0, -1.0, 1.0]
        y = [1.0, 1.0, -1.0, -1.0, 1.0]
        corr = pearson_correlation(x, y)
        assert abs(corr) < 0.5  # not perfectly orthogonal but low

    def test_constant_returns(self):
        """Zero variance → correlation = 0.0 (guard against division by zero)."""
        x = [0.5, 0.5, 0.5, 0.5]
        y = [1.0, 2.0, 3.0, 4.0]
        assert pearson_correlation(x, y) == 0.0

    def test_both_constant(self):
        """Both series constant → 0.0."""
        x = [1.0, 1.0, 1.0]
        y = [2.0, 2.0, 2.0]
        assert pearson_correlation(x, y) == 0.0

    def test_different_lengths(self):
        """Uses min length overlap."""
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        y = [2.0, 4.0, 6.0, 8.0]  # perfectly correlated with first 4 of x
        corr = pearson_correlation(x, y)
        assert corr == pytest.approx(1.0, abs=1e-6)

    def test_single_element(self):
        """Single element → can't compute correlation."""
        assert pearson_correlation([1.0], [2.0]) == 0.0

    def test_empty(self):
        """Empty input → 0.0."""
        assert pearson_correlation([], []) == 0.0

    def test_known_moderate_correlation(self):
        """Hand-checked moderate correlation."""
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 1.0, 4.0, 3.0, 5.0]
        corr = pearson_correlation(x, y)
        # Not perfect, should be positive moderate-to-high
        assert 0.0 < corr < 1.0
        assert corr == pytest.approx(0.7, abs=0.15)  # approximately 0.7


# ---------------------------------------------------------------------------
# compute_correlation_matrix
# ---------------------------------------------------------------------------


class TestCorrelationMatrix:
    def test_empty_input(self):
        result = compute_correlation_matrix({})
        assert result["n_strategies"] == 0
        assert result["matrix"] == []
        assert result["strategies"] == []

    def test_single_strategy(self):
        """Single strategy → 1×1 matrix with 1.0 on diagonal."""
        result = compute_correlation_matrix({"a": [1.0, 2.0, 3.0]})
        assert result["n_strategies"] == 1
        assert result["matrix"] == [[1.0]]
        assert result["strategies"] == ["a"]
        assert result["high_correlations"] == []

    def test_two_identical_strategies(self):
        """Two identical strategies → correlation 1.0, should be flagged."""
        result = compute_correlation_matrix(
            {
                "a": [0.01, 0.02, -0.01, 0.03, 0.02],
                "b": [0.01, 0.02, -0.01, 0.03, 0.02],
            }
        )
        assert result["n_strategies"] == 2
        assert result["matrix"][0][1] == pytest.approx(1.0, abs=1e-6)
        assert result["matrix"][1][0] == pytest.approx(1.0, abs=1e-6)
        assert result["matrix"][0][0] == 1.0
        assert result["matrix"][1][1] == 1.0
        assert len(result["high_correlations"]) == 1
        assert result["high_correlations"][0]["pair"] == ["a", "b"]

    def test_three_strategies_symmetric(self):
        """Matrix should be symmetric."""
        import random

        rng = random.Random(42)  # noqa: S311
        returns = {
            "s1": [rng.gauss(0, 0.01) for _ in range(50)],
            "s2": [rng.gauss(0, 0.01) for _ in range(50)],
            "s3": [rng.gauss(0, 0.01) for _ in range(50)],
        }
        result = compute_correlation_matrix(returns)
        assert result["n_strategies"] == 3
        m = result["matrix"]
        for i in range(3):
            for j in range(3):
                assert m[i][j] == pytest.approx(m[j][i], abs=1e-5)
        assert m[0][0] == 1.0
        assert m[1][1] == 1.0
        assert m[2][2] == 1.0

    def test_alignment_info(self):
        """Alignment dict should contain overlap counts."""
        result = compute_correlation_matrix(
            {
                "a": [1.0, 2.0, 3.0],
                "b": [1.0, 2.0],
            }
        )
        key = "a__b"
        assert key in result["alignment"]
        assert result["alignment"][key]["overlap"] == 2

    def test_insufficient_overlap(self):
        """Single-element strategy should note insufficient overlap."""
        result = compute_correlation_matrix(
            {
                "a": [1.0, 2.0, 3.0],
                "b": [1.0],
            }
        )
        key = "a__b"
        assert result["alignment"][key]["overlap"] == 1
        assert result["alignment"][key].get("note") == "insufficient_overlap"
        assert result["matrix"][0][1] == 0.0

    def test_strategies_sorted(self):
        """Strategy names should be sorted in the output."""
        result = compute_correlation_matrix(
            {
                "zebra": [1.0, 2.0],
                "alpha": [1.0, 2.0],
                "middle": [1.0, 2.0],
            }
        )
        assert result["strategies"] == ["alpha", "middle", "zebra"]

    def test_constant_strategy_pair(self):
        """One constant strategy → 0.0 correlation, no crash."""
        result = compute_correlation_matrix(
            {
                "const": [0.5, 0.5, 0.5, 0.5],
                "varied": [0.1, 0.3, -0.2, 0.05],
            }
        )
        assert result["matrix"][0][1] == 0.0
        # Should not be in high correlations
        assert len(result["high_correlations"]) == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCorrelationCLI:
    def test_cli_basic(self, tmp_path):
        """CLI should produce valid JSON output."""
        data = {
            "a": [0.01, 0.02, -0.01, 0.03, 0.02, -0.005],
            "b": [0.02, 0.01, 0.03, -0.01, 0.015, 0.025],
        }
        infile = tmp_path / "returns.json"
        infile.write_text(json.dumps(data))

        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "backtest.correlation", "--input", str(infile)],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["n_strategies"] == 2
        assert len(output["matrix"]) == 2
        assert len(output["matrix"][0]) == 2

    def test_cli_output_file(self, tmp_path):
        """--output flag should write to file."""
        data = {"x": [1.0, 2.0, 3.0], "y": [3.0, 2.0, 1.0]}
        infile = tmp_path / "in.json"
        outfile = tmp_path / "out.json"
        infile.write_text(json.dumps(data))

        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "backtest.correlation",
                "--input",
                str(infile),
                "--output",
                str(outfile),
            ],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        assert result.returncode == 0
        assert outfile.exists()
        output = json.loads(outfile.read_text())
        assert output["n_strategies"] == 2

    def test_cli_missing_file(self):
        """Missing file should exit with code 2."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "backtest.correlation",
                "--input",
                "/nonexistent/path.json",
            ],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        assert result.returncode == 2
