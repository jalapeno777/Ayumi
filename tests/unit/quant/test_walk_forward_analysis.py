"""Tests for walk_forward_analysis.py — proxy haircut-ratio analysis.

Covers:
1. Haircut computation (positive/negative/zero sharpe, various decay)
2. Kill/marginal/healthy thresholds
3. Missing data handling (NULL metrics)
4. Strategy name normalization (underscore vs non-underscore variants)
5. Aggregation across naming variants
6. Edge cases (empty runs, all-None data, denominator zero)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure script is importable
SCRIPT_DIR = Path(__file__).resolve().parents[3] / "scripts" / "quant"
sys.path.insert(0, str(SCRIPT_DIR))

from walk_forward_analysis import (  # noqa: E402, I001
    FTMO_CANDIDATES,
    KILL_THRESHOLD,
    CandidateResult,
    StrategyRun,
    _normalize_name,
    aggregate_candidate,
    generate_report,
)

# ---------------------------------------------------------------------------
# 1. Haircut computation tests
# ---------------------------------------------------------------------------


class TestHaircutComputation:
    """Test the haircut ratio formula and verdict assignment."""

    def test_positive_sharpe_zero_decay_healthy(self):
        """Strategy with strong positive Sharpe and zero decay → healthy."""
        c = CandidateResult(name="test", avg_mean_sharpe=2.0, avg_oos_decay=0.0)
        c.compute_haircut()
        # haircut = 2.0 / max(2.0, 0+1) = 2.0 / 2.0 = 1.0
        assert c.haircut_ratio == pytest.approx(1.0)
        assert c.verdict == "healthy"

    def test_positive_sharpe_high_decay_marginal(self):
        """Strategy with decent Sharpe but significant decay → marginal."""
        c = CandidateResult(name="test", avg_mean_sharpe=1.5, avg_oos_decay=0.8)
        c.compute_haircut()
        # haircut = 1.5 / max(1.5, 0.8+1) = 1.5 / 1.8 ≈ 0.833
        assert c.haircut_ratio == pytest.approx(0.833, abs=0.01)
        assert c.verdict == "healthy"

    def test_positive_sharpe_very_high_decay_kill(self):
        """Strategy with positive Sharpe but extreme decay → kill."""
        c = CandidateResult(name="test", avg_mean_sharpe=0.5, avg_oos_decay=2.0)
        c.compute_haircut()
        # haircut = 0.5 / max(0.5, 2+1) = 0.5 / 3.0 ≈ 0.167
        assert c.haircut_ratio == pytest.approx(0.167, abs=0.01)
        assert c.verdict == "kill"

    def test_negative_sharpe_kill(self):
        """Strategy with negative Sharpe → always kill regardless of decay."""
        c = CandidateResult(name="test", avg_mean_sharpe=-5.0, avg_oos_decay=0.0)
        c.compute_haircut()
        # denominator = max(-5.0, 0+1) = 1.0, haircut = -5.0/1.0 = -5.0
        assert c.haircut_ratio == pytest.approx(-5.0)
        assert c.verdict == "kill"

    def test_zero_sharpe_zero_decay(self):
        """Strategy with exactly 0 Sharpe and 0 decay → kill (sharpe <= 0)."""
        c = CandidateResult(name="test", avg_mean_sharpe=0.0, avg_oos_decay=0.0)
        c.compute_haircut()
        # denominator = max(0, 1) = 1, haircut = 0/1 = 0.0
        assert c.haircut_ratio == pytest.approx(0.0)
        assert c.verdict == "kill"  # sharpe <= 0 → kill

    def test_small_positive_sharpe_low_decay(self):
        """Strategy with small positive Sharpe → marginal or kill."""
        c = CandidateResult(name="test", avg_mean_sharpe=0.6, avg_oos_decay=0.1)
        c.compute_haircut()
        # haircut = 0.6 / max(0.6, 0.1+1) = 0.6 / 1.1 ≈ 0.545
        assert c.haircut_ratio == pytest.approx(0.545, abs=0.01)
        assert c.verdict == "marginal"  # between 0.5 and 0.7


# ---------------------------------------------------------------------------
# 2. Threshold boundary tests
# ---------------------------------------------------------------------------


class TestThresholds:
    """Test that kill/marginal/healthy thresholds are correctly applied."""

    def test_exact_kill_threshold(self):
        """Haircut exactly at KILL_THRESHOLD (0.5) → marginal (not kill)."""
        # Need haircut = 0.5: avg_sharpe / max(avg_sharpe, decay+1) = 0.5
        # If sharpe=1, decay=1: 1/max(1,2) = 0.5
        c = CandidateResult(name="test", avg_mean_sharpe=1.0, avg_oos_decay=1.0)
        c.compute_haircut()
        assert c.haircut_ratio == pytest.approx(0.5)
        assert c.verdict == "marginal"  # >= 0.5 → marginal

    def test_just_below_kill_threshold(self):
        """Haircut just below KILL_THRESHOLD → kill."""
        # sharpe=0.9, decay=1: 0.9/max(0.9,2) = 0.9/2 = 0.45
        c = CandidateResult(name="test", avg_mean_sharpe=0.9, avg_oos_decay=1.0)
        c.compute_haircut()
        assert c.haircut_ratio < KILL_THRESHOLD
        assert c.verdict == "kill"

    def test_exact_marginal_threshold(self):
        """Haircut at MARGINAL_THRESHOLD (0.7) → healthy."""
        # Need ratio = 0.7: sharpe / max(sharpe, decay+1) = 0.7
        # sharpe=2.333, decay=1: 2.333/max(2.333,2) = 2.333/2.333 = 1.0 — not right
        # sharpe=0.7, decay=0: 0.7/max(0.7,1) = 0.7/1 = 0.7
        c = CandidateResult(name="test", avg_mean_sharpe=0.7, avg_oos_decay=0.0)
        c.compute_haircut()
        assert c.haircut_ratio == pytest.approx(0.7)
        assert c.verdict == "healthy"  # >= 0.7 → healthy

    def test_just_below_marginal_threshold(self):
        """Haircut just below MARGINAL_THRESHOLD → marginal."""
        # sharpe=0.65, decay=0: 0.65/max(0.65,1) = 0.65/1 = 0.65
        c = CandidateResult(name="test", avg_mean_sharpe=0.65, avg_oos_decay=0.0)
        c.compute_haircut()
        assert c.haircut_ratio == pytest.approx(0.65)
        assert c.verdict == "marginal"


# ---------------------------------------------------------------------------
# 3. Missing data handling tests
# ---------------------------------------------------------------------------


class TestMissingData:
    """Test handling of NULL/missing metrics."""

    def test_none_sharpe_no_data(self):
        """Strategy with no sharpe data → no_data verdict."""
        c = CandidateResult(name="test", avg_mean_sharpe=None)
        c.compute_haircut()
        assert c.haircut_ratio is None
        assert c.verdict == "no_data"

    def test_none_decay_treated_as_zero(self):
        """Strategy with Sharpe but NULL decay → decay treated as 0."""
        c = CandidateResult(name="test", avg_mean_sharpe=2.0, avg_oos_decay=None)
        c.compute_haircut()
        # decay=None → abs(0.0) = 0, denominator = max(2.0, 1.0) = 2.0
        assert c.haircut_ratio == pytest.approx(1.0)
        assert c.verdict == "healthy"

    def test_empty_candidate_result(self):
        """Fresh CandidateResult with defaults → no_data."""
        c = CandidateResult(name="test")
        c.compute_haircut()
        assert c.haircut_ratio is None
        assert c.verdict == "no_data"


# ---------------------------------------------------------------------------
# 4. Strategy name normalization tests
# ---------------------------------------------------------------------------


class TestNameNormalization:
    """Test the _normalize_name function for deduplication."""

    def test_underscore_to_stripped(self):
        assert _normalize_name("killzone_momentum") == "killzonemomentum"

    def test_already_stripped(self):
        assert _normalize_name("killzonemomentum") == "killzonemomentum"

    def test_case_insensitive(self):
        assert _normalize_name("Killzone_Momentum") == "killzonemomentum"

    def test_mixed_underscore_and_case(self):
        assert _normalize_name("SRMR_Plus") == "srmrplus"
        assert _normalize_name("srmr_plus") == "srmrplus"

    def test_all_8_candidates_normalize(self):
        """Verify all 8 FTMO candidates normalize correctly."""
        for name in FTMO_CANDIDATES:
            normalized = _normalize_name(name)
            assert "_" not in normalized
            assert normalized == normalized.lower()


# ---------------------------------------------------------------------------
# 5. Aggregation tests
# ---------------------------------------------------------------------------


class TestAggregation:
    """Test aggregation of runs into candidate results."""

    def test_merge_naming_variants(self):
        """Runs with underscore and non-underscore names should merge."""
        runs = [
            StrategyRun(
                "killzone_momentum",
                "EURUSD",
                5,
                "r1",
                -1.0,
                None,
                0,
                5,
                "no-go",
                None,
                None,
                None,
            ),
            StrategyRun(
                "killzonemomentum",
                "EURUSD",
                5,
                "r2",
                2.0,
                0.1,
                1,
                5,
                "no-go",
                0.5,
                0.8,
                1.2,
            ),
        ]
        result = aggregate_candidate("killzone_momentum", runs)
        assert result.total_runs == 2
        # Should prefer runs with decay (r2)
        assert result.runs_with_metrics == 1
        assert result.avg_mean_sharpe == 2.0
        assert result.avg_oos_decay == 0.1

    def test_no_matching_runs(self):
        """Strategy with no runs → no_data."""
        result = aggregate_candidate("nonexistent_strategy", [])
        assert result.total_runs == 0
        assert result.verdict == "no_data"

    def test_all_none_metrics(self):
        """Runs with all-None metrics → no_data after aggregation."""
        runs = [
            StrategyRun("test", "EURUSD", 5, "r1", None, None, 0, 5, "no-go", None, None, None),
            StrategyRun("test", "EURUSD", 15, "r2", None, None, 0, 5, "no-go", None, None, None),
        ]
        result = aggregate_candidate("test", runs)
        assert result.avg_mean_sharpe is None
        assert result.verdict == "no_data"

    def test_best_run_tracking(self):
        """Best/worst Sharpe and pair/TF are tracked correctly."""
        runs = [
            StrategyRun("test", "EURUSD", 5, "r1", -2.0, 0.0, 0, 5, "no-go", None, None, None),
            StrategyRun("test", "XAUUSD", 60, "r2", 3.5, 0.1, 2, 5, "no-go", 0.3, 0.6, 0.4),
            StrategyRun("test", "GBPUSD", 15, "r3", -5.0, 0.0, 0, 5, "no-go", None, None, None),
        ]
        result = aggregate_candidate("test", runs)
        assert result.best_sharpe == 3.5
        assert result.worst_sharpe == -5.0
        assert result.best_pair == "XAUUSD"
        assert result.best_timeframe == 60

    def test_notes_for_no_go(self):
        """All no-go runs should add a note."""
        runs = [
            StrategyRun("test", "EURUSD", 5, "r1", -1.0, 0.0, 0, 5, "no-go", None, None, None),
        ]
        result = aggregate_candidate("test", runs)
        assert any("no-go" in note for note in result.notes)


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    def test_single_positive_run(self):
        """Single run with strong positive Sharpe."""
        runs = [
            StrategyRun("test", "XAUUSD", 60, "r1", 3.3, 0.114, 2, 5, "no-go", 0.26, 0.61, 0.37),
        ]
        result = aggregate_candidate("test", runs)
        assert result.avg_mean_sharpe == pytest.approx(3.3)
        assert result.avg_oos_decay == pytest.approx(0.114)
        result.compute_haircut()
        # haircut = 3.3 / max(3.3, 0.114+1) = 3.3 / 3.3 = 1.0
        assert result.haircut_ratio == pytest.approx(1.0, abs=0.01)
        assert result.verdict == "healthy"

    def test_extreme_negative_sharpe(self):
        """Deeply negative Sharpe (as seen in real data, e.g. -2812)."""
        c = CandidateResult(name="test", avg_mean_sharpe=-2812.0, avg_oos_decay=0.0)
        c.compute_haircut()
        assert c.verdict == "kill"
        assert c.haircut_ratio < 0

    def test_ftmo_candidates_count(self):
        """Verify we have exactly 8 FTMO candidates."""
        assert len(FTMO_CANDIDATES) == 8

    def test_report_generation(self):
        """Report generation produces valid markdown."""
        results = [
            CandidateResult(
                name="test_strategy",
                total_runs=3,
                runs_with_metrics=3,
                avg_mean_sharpe=-5.0,
                avg_oos_decay=0.0,
                best_sharpe=-1.0,
                worst_sharpe=-10.0,
                best_pair="EURUSD",
                best_timeframe=15,
            ),
        ]
        results[0].compute_haircut()
        report = generate_report(results, {"test_strategy": []}, "test.duckdb")
        assert "# Walk-Forward Haircut-Ratio Analysis (Proxy)" in report
        assert "test_strategy" in report
        assert "kill" in report.lower()

    def test_report_with_no_data_candidate(self):
        """Report handles candidates with no data gracefully."""
        results = [CandidateResult(name="empty_strategy")]
        results[0].compute_haircut()
        report = generate_report(results, {"empty_strategy": []}, "test.duckdb")
        assert "empty_strategy" in report
        assert "no_data" in report or "No Data" in report
