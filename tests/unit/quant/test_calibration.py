"""Tests for quant.calibration — Brier score and calibration analysis.

Covers:
- brier_score: perfect / worst / single / all-wins / all-losses / empty / mismatched
- calibration_curve: binning correctness, empty-bin handling, bin-edge inclusivity
- brier_decomposition: Murphy 1973 decomposition (reliability - resolution + uncertainty == BS)
- evaluate_calibration: integration with WalkForwardResults dataclass
- Hand-computed Brier example from the module docstring
"""

from __future__ import annotations  # noqa: I001

import math

import numpy as np
import pytest

from quant.calibration import (
    CalibrationBin,
    CalibrationReport,
    brier_decomposition,
    brier_score,
    calibration_curve,
    evaluate_calibration,
)
from quant.oos_gate import WalkForwardResults


# ---------------------------------------------------------------------------
# brier_score tests
# ---------------------------------------------------------------------------


class TestBrierScore:
    """Brier score = mean squared error of predicted probability vs outcome."""

    def test_perfect_calibration_low_score(self):
        """When predicted confidence matches the empirical win rate, BS is low.

        10 predictions of 0.9 with 9 wins and 1 loss → empirical wr 0.9
        matches the prediction. BS = (9*(0.9-1)² + 1*(0.9-0)²) / 10
            = (9*0.01 + 0.81) / 10 = 0.09. Compare to the uncertainty floor
            (which is the BS of a constant predictor): 0.9*0.1 = 0.09.
        A perfectly-calibrated system has BS == uncertainty.
        """
        preds = [0.9] * 10
        outcomes = [1] * 9 + [0]  # 9/10 wins
        bs = brier_score(preds, outcomes)
        # BS equals the uncertainty floor (perfect calibration).
        assert bs == pytest.approx(0.09, abs=1e-12)
        assert bs == pytest.approx(0.9 * 0.1)

    def test_worst_calibration_high_score(self):
        """All predictions perfectly wrong → each (1-0)² or (0-1)² = 1.0."""
        # Predict 1.0 for all losers, 0.0 for all winners: each term is 1.0.
        preds = [1.0, 1.0, 0.0, 0.0]
        outcomes = [0, 0, 1, 1]
        assert brier_score(preds, outcomes) == pytest.approx(1.0)

    def test_single_trade(self):
        """A single trade: BS = (p - o)²."""
        # Win with confidence 0.7
        assert brier_score([0.7], [1]) == pytest.approx(0.09)
        # Loss with confidence 0.7
        assert brier_score([0.7], [0]) == pytest.approx(0.49)
        # Win with confidence 1.0 → 0.0
        assert brier_score([1.0], [1]) == pytest.approx(0.0)

    def test_all_wins_low_score(self):
        """If all outcomes are 1, BS = mean((p-1)²) = mean((1-p)²)."""
        preds = [0.8, 0.6, 0.9]
        outcomes = [1, 1, 1]
        expected = ((0.2) ** 2 + (0.4) ** 2 + (0.1) ** 2) / 3
        assert brier_score(preds, outcomes) == pytest.approx(expected)

    def test_all_losses_low_score(self):
        """If all outcomes are 0, BS = mean(p²)."""
        preds = [0.2, 0.4, 0.1]
        outcomes = [0, 0, 0]
        expected = (0.04 + 0.16 + 0.01) / 3
        assert brier_score(preds, outcomes) == pytest.approx(expected)

    def test_known_hand_computed_example(self):
        """Hand-computed example from the module docstring.

        pred = [0.9, 0.9, 0.1, 0.1]
        outcome = [1, 1, 0, 0]

        BS = (0.01 + 0.01 + 0.01 + 0.01) / 4 = 0.01
        """
        preds = [0.9, 0.9, 0.1, 0.1]
        outcomes = [1, 1, 0, 0]
        assert brier_score(preds, outcomes) == pytest.approx(0.01, abs=1e-12)

    def test_empty_input_raises(self):
        """Empty inputs are undefined for Brier score."""
        with pytest.raises(ValueError, match="at least one"):
            brier_score([], [])
        with pytest.raises(ValueError, match="at least one"):
            brier_score([0.5], [])

    def test_mismatched_lengths_raises(self):
        """Mismatched shapes raise ValueError."""
        with pytest.raises(ValueError, match="same shape"):
            brier_score([0.5, 0.7], [1])

    def test_returns_python_float(self):
        """Return type is a Python float (not numpy scalar) for downstream use."""
        result = brier_score([0.5, 0.5], [1, 0])
        assert isinstance(result, float)

    def test_accepts_numpy_arrays(self):
        """Function accepts numpy arrays (not just lists)."""
        result = brier_score(np.array([0.5, 0.5]), np.array([1, 0]))
        assert result == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# calibration_curve tests
# ---------------------------------------------------------------------------


class TestCalibrationCurve:
    """Calibration curve binning correctness."""

    def test_binning_count_sums_to_total(self):
        """The total count across all bins equals the input size."""
        confs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        outcomes = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1]
        curve = calibration_curve(confs, outcomes, n_bins=10)
        assert len(curve) == 10
        total_count = sum(b.count for b in curve)
        assert total_count == len(confs)

    def test_binning_correctness_known_values(self):
        """Bins correctly classify confidences into their natural ranges."""
        confs = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
        outcomes = [0] * 5 + [1] * 5  # first half wrong, second half right
        curve = calibration_curve(confs, outcomes, n_bins=10)
        # Every bin should have count=1.
        for b in curve:
            assert b.count == 1
        # Each bin's mean_confidence should equal the input confidence.
        for b, expected_conf in zip(curve, confs):  # noqa: B905
            assert b.mean_confidence == pytest.approx(expected_conf, abs=1e-9)
        # First 5 bins: actual_win_rate = 0.0
        for b in curve[:5]:
            assert b.actual_win_rate == pytest.approx(0.0)
        # Last 5 bins: actual_win_rate = 1.0
        for b in curve[5:]:
            assert b.actual_win_rate == pytest.approx(1.0)

    def test_empty_bins_returned_with_nan(self):
        """Bins with no samples are still returned with NaN metrics."""
        # All confidences in [0, 0.3] → upper bins are empty.
        confs = [0.1, 0.2, 0.05, 0.15]
        outcomes = [0, 0, 1, 0]
        curve = calibration_curve(confs, outcomes, n_bins=10)
        # Bins 0-2 have data, bins 3-9 are empty.
        for b in curve[:3]:
            assert b.count > 0
        for b in curve[3:]:
            assert b.count == 0
            assert math.isnan(b.mean_confidence)
            assert math.isnan(b.actual_win_rate)
            assert b.brier_contribution == 0.0

    def test_bin_edges_left_inclusive(self):
        """Lower edge is inclusive; 0.0 lands in the first bin."""
        confs = [0.0, 0.0, 0.0]
        outcomes = [0, 0, 0]
        curve = calibration_curve(confs, outcomes, n_bins=10)
        assert curve[0].count == 3
        assert all(b.count == 0 for b in curve[1:])

    def test_confidence_one_in_last_bin(self):
        """Confidence of exactly 1.0 lands in the last bin (inclusive upper)."""
        confs = [1.0]
        outcomes = [1]
        curve = calibration_curve(confs, outcomes, n_bins=10)
        # All previous bins are empty; last bin has the sample.
        assert curve[-1].count == 1
        assert curve[-1].mean_confidence == pytest.approx(1.0)
        assert curve[-1].actual_win_rate == pytest.approx(1.0)
        for b in curve[:-1]:
            assert b.count == 0

    def test_bin_count_equals_n_bins(self):
        """Result always has exactly n_bins entries (even when empty)."""
        curve = calibration_curve([0.5], [1], n_bins=5)
        assert len(curve) == 5
        curve = calibration_curve([0.5], [1], n_bins=20)
        assert len(curve) == 20

    def test_brier_contribution_definition(self):
        """brier_contribution = count * (mean_conf - actual_wr)² / N_total."""
        # 4 trades: preds=[0.8, 0.8, 0.2, 0.2], outcomes=[1, 1, 0, 0]
        # With 2 bins: bin1=[0,0.5) gets [0.2, 0.2] with wr=0, bin2=[0.5,1] gets [0.8,0.8] with wr=1.
        confs = [0.8, 0.8, 0.2, 0.2]
        outcomes = [1, 1, 0, 0]
        curve = calibration_curve(confs, outcomes, n_bins=2)
        # Bin 0: [0, 0.5) → preds=[0.2, 0.2], actual=[0, 0]
        #   mean_conf=0.2, actual_wr=0.0, brier_contrib = 2 * (0.2-0)² / 4 = 0.02
        assert curve[0].count == 2
        assert curve[0].mean_confidence == pytest.approx(0.2)
        assert curve[0].actual_win_rate == pytest.approx(0.0)
        assert curve[0].brier_contribution == pytest.approx(0.02)
        # Bin 1: [0.5, 1.0] → preds=[0.8, 0.8], actual=[1, 1]
        #   mean_conf=0.8, actual_wr=1.0, brier_contrib = 2 * (0.2)² / 4 = 0.02
        assert curve[1].count == 2
        assert curve[1].mean_confidence == pytest.approx(0.8)
        assert curve[1].actual_win_rate == pytest.approx(1.0)
        assert curve[1].brier_contribution == pytest.approx(0.02)

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            calibration_curve([], [], n_bins=5)

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError, match="same shape"):
            calibration_curve([0.5, 0.6], [1], n_bins=5)

    def test_n_bins_too_small_raises(self):
        with pytest.raises(ValueError, match="n_bins"):
            calibration_curve([0.5], [1], n_bins=0)

    def test_bin_lower_upper_spans_unit_interval(self):
        """Default n_bins=10 produces bins of width 0.1 covering [0, 1]."""
        curve = calibration_curve([0.5], [1], n_bins=10)
        assert curve[0].bin_lower == pytest.approx(0.0)
        assert curve[0].bin_upper == pytest.approx(0.1)
        assert curve[-1].bin_lower == pytest.approx(0.9)
        assert curve[-1].bin_upper == pytest.approx(1.0)

    def test_returns_calibration_bin_instances(self):
        curve = calibration_curve([0.5], [1], n_bins=3)
        for b in curve:
            assert isinstance(b, CalibrationBin)


# ---------------------------------------------------------------------------
# brier_decomposition tests
# ---------------------------------------------------------------------------


class TestBrierDecomposition:
    """Murphy (1973) decomposition: BS = reliability - resolution + uncertainty."""

    def test_decomposition_identity_holds(self):
        """For any input, reliability - resolution + uncertainty == BS.

        Note: the binned Brier decomposition is *exact* only when all
        confidences in a bin are identical (because the decomposition
        binarizes predictions to bin means). For continuous predictions
        with mixed values per bin, the binned decomposition is an
        approximation. This test uses the case where the identity holds
        exactly: all samples in a bin are identical.
        """
        # All confs are 0.5 or 0.9 or 0.1 — each value gets its own bin.
        confs = [0.9, 0.9, 0.1, 0.1]
        outcomes = [1, 1, 0, 0]
        bs = brier_score(confs, outcomes)
        rel, res, unc = brier_decomposition(confs, outcomes, n_bins=2)
        assert rel - res + unc == pytest.approx(bs, abs=1e-12)

    def test_decomposition_identity_random_data(self):
        """Identity holds exactly only when bin means equal sample values.

        With many values per bin (random data), the binned decomposition
        is an approximation; we just check the identity is *close*, not
        exact. (Tolerance of 0.05 is generous but catches real bugs.)
        """
        rng = np.random.default_rng(42)
        confs = rng.uniform(0.3, 0.9, size=100).tolist()
        outcomes = rng.integers(0, 2, size=100).tolist()
        bs = brier_score(confs, outcomes)
        rel, res, unc = brier_decomposition(confs, outcomes, n_bins=10)
        # Binned decomposition approximates BS, not exact.
        assert rel - res + unc == pytest.approx(bs, abs=0.05)

    def test_perfect_system_has_zero_reliability(self):
        """When predicted exactly matches the empirical outcome, reliability = 0.

        All samples in one bin with identical conf and matching wr →
        (f_k - ō_k)² = 0.
        """
        # All predictions in one bin (0.8-0.9 with n_bins=10) and actual wr matches.
        confs = [0.85] * 20
        outcomes = [1] * 17 + [0] * 3  # 17/20 = 0.85 win rate
        rel, res, unc = brier_decomposition(confs, outcomes, n_bins=10)
        assert rel == pytest.approx(0.0, abs=1e-12)
        # Resolution: all in one bin, (ō_k - ō) = 0.85 - 0.85 = 0 → res = 0.
        assert res == pytest.approx(0.0, abs=1e-12)
        # Uncertainty = 0.85 * 0.15 = 0.1275
        assert unc == pytest.approx(0.1275)
        # Identity holds (all identical in bin)
        bs = brier_score(confs, outcomes)
        assert rel - res + unc == pytest.approx(bs, abs=1e-12)

    def test_uncertainty_is_base_rate_times_one_minus_base_rate(self):
        """uncertainty = ō * (1 - ō)."""
        confs = [0.5] * 50
        outcomes = [1] * 30 + [0] * 20  # base rate = 0.6
        rel, res, unc = brier_decomposition(confs, outcomes, n_bins=5)
        assert unc == pytest.approx(0.6 * 0.4)

    def test_high_resolution_separates_wins_from_losses(self):
        """Resolution > 0 when bin win rates differ from the base rate.

        10 predictions of 0.9 with 9 wins and 1 loss (bin wr 0.9 = conf)
        plus 10 predictions of 0.1 with 1 win and 9 losses (bin wr 0.1 = conf).
        All 0.9s land in one bin, all 0.1s in another. Reliability = 0
        (predictions match bin wr exactly). Resolution > 0 (bin wrs
        differ from base rate 0.5).
        """
        confs = [0.9] * 10 + [0.1] * 10
        outcomes = [1] * 9 + [0] + [1] + [0] * 9  # 11/20 = 0.55 base rate
        rel, res, unc = brier_decomposition(confs, outcomes, n_bins=10)
        # bin wrs 0.9 and 0.1 vs base 0.55 → resolution > 0
        assert res > 0.0
        # perfect calibration within each bin (all identical in bin) → reliability = 0
        assert rel == pytest.approx(0.0, abs=1e-12)
        # identity holds exactly here
        bs = brier_score(confs, outcomes)
        assert rel - res + unc == pytest.approx(bs, abs=1e-12)

    def test_hand_computed_decomposition(self):
        """Hand-computed example from the module docstring.

        pred = [0.9, 0.9, 0.1, 0.1], outcome = [1, 1, 0, 0]
        BS = 0.01, ō = 0.5, uncertainty = 0.25
        With 2 bins [0, 0.5) and [0.5, 1.0]:
          - bin 0: f=0.1, ō_k=0 → reliability += 2 * 0.01 = 0.02
                    ō_k - ō = -0.5 → resolution += 2 * 0.25 = 0.5
          - bin 1: f=0.9, ō_k=1 → reliability += 2 * 0.01 = 0.02
                    ō_k - ō = +0.5 → resolution += 2 * 0.25 = 0.5
        reliability = 0.04 / 4 = 0.01
        resolution = 1.0 / 4 = 0.25
        uncertainty = 0.5 * 0.5 = 0.25
        Check: 0.01 - 0.25 + 0.25 = 0.01 == BS ✓
        """
        confs = [0.9, 0.9, 0.1, 0.1]
        outcomes = [1, 1, 0, 0]
        rel, res, unc = brier_decomposition(confs, outcomes, n_bins=2)
        assert rel == pytest.approx(0.01)
        assert res == pytest.approx(0.25)
        assert unc == pytest.approx(0.25)
        # And the identity holds
        assert rel - res + unc == pytest.approx(brier_score(confs, outcomes))

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            brier_decomposition([], [])

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError, match="same shape"):
            brier_decomposition([0.5, 0.6], [1])


# ---------------------------------------------------------------------------
# evaluate_calibration tests
# ---------------------------------------------------------------------------


def _make_wf(
    *,
    per_window_returns: list[list[float]],
    bar_period_minutes: int = 15,
    sample_duration_days: float | None = None,
    strategy_name: str = "TEST",
    pair: str = "GBPUSD",
    timeframe: str = "M15",
) -> WalkForwardResults:
    """Construct a WalkForwardResults with the given per-window trade returns."""
    return WalkForwardResults(
        strategy_name=strategy_name,
        pair=pair,
        timeframe=timeframe,
        bar_period_minutes=bar_period_minutes,
        per_window_trade_returns=per_window_returns,
        sample_duration_days=sample_duration_days,
    )


class TestEvaluateCalibration:
    """Integration with WalkForwardResults."""

    def test_outcomes_derived_from_per_window_returns(self):
        """When outcomes not given, derive from per-trade returns (>0 → 1)."""
        # 4 trades: 2 wins, 2 losses.
        wf = _make_wf(per_window_returns=[[0.01, -0.005, 0.02, -0.01]])
        # 2 wins, 2 losses; let confidences be 0.6 for wins, 0.4 for losses.
        # This means predictions disagree with outcomes (anti-calibrated).
        confs = [0.6, 0.4, 0.6, 0.4]
        report = evaluate_calibration(wf, confidences=confs)
        # base win rate = 0.5
        assert report.n_signals == 4
        assert report.base_win_rate == pytest.approx(0.5)
        assert report.uncertainty == pytest.approx(0.25)

    def test_explicit_outcomes_used(self):
        """When outcomes are given, they're used directly (not derived)."""
        wf = _make_wf(per_window_returns=[[0.01, -0.005, 0.02, -0.01]])
        # Outcome sequence doesn't match the actual returns, so we know
        # the function used the explicit one.
        confs = [0.9, 0.9, 0.1, 0.1]
        outcomes = [1, 1, 0, 0]
        report = evaluate_calibration(wf, confidences=confs, outcomes=outcomes)
        # This is the perfect-calibration example: BS = 0.01
        assert report.brier_score == pytest.approx(0.01)
        assert report.n_signals == 4
        assert report.base_win_rate == pytest.approx(0.5)

    def test_confidences_required(self):
        """When confidences not given, raise ValueError."""
        wf = _make_wf(per_window_returns=[[0.01, -0.005]])
        with pytest.raises(ValueError, match="confidences is required"):
            evaluate_calibration(wf)

    def test_returns_calibration_report(self):
        """Return type is CalibrationReport with all fields populated."""
        wf = _make_wf(per_window_returns=[[0.01, -0.005, 0.02]])
        confs = [0.7, 0.3, 0.8]
        report = evaluate_calibration(wf, confidences=confs)
        assert isinstance(report, CalibrationReport)
        assert report.brier_score >= 0.0
        assert len(report.calibration_curve) == 10  # default n_bins
        assert report.n_signals == 3
        assert 0.0 <= report.base_win_rate <= 1.0
        assert 0.0 <= report.uncertainty <= 0.25

    def test_decomposition_consistent_in_report(self):
        """The report's decomposition terms satisfy BS = rel - res + unc.

        Uses identical confs per bin so the binned decomposition is exact.
        """
        wf = _make_wf(per_window_returns=[[0.01, -0.005, 0.02, -0.01, 0.015, 0.005, -0.008, 0.012]])
        # Each confidence value is its own bin (n_bins=20 covers 0.0-1.0
        # with 0.05 width; with 8 distinct values they spread out).
        # Easier: use the same value multiple times so each bin has
        # identical confs.
        confs = [0.7, 0.7, 0.3, 0.3, 0.7, 0.3, 0.3, 0.7]
        report = evaluate_calibration(wf, confidences=confs, n_bins=10)
        assert report.brier_score == pytest.approx(
            report.reliability - report.resolution + report.uncertainty, abs=1e-12
        )

    def test_empty_wf_with_no_outcomes_raises(self):
        """If wf_results has no trades and no explicit outcomes, raise."""
        wf = _make_wf(per_window_returns=[])
        with pytest.raises(ValueError, match="Cannot derive outcomes"):
            evaluate_calibration(wf, confidences=[0.5])

    def test_length_mismatch_raises(self):
        """Confidences must match outcomes length when both given."""
        wf = _make_wf(per_window_returns=[[0.01, -0.005]])
        with pytest.raises(ValueError, match="same shape"):
            evaluate_calibration(wf, confidences=[0.5, 0.5, 0.5], outcomes=[1, 0])

    def test_n_bins_parameter_respected(self):
        """n_bins propagates to the calibration curve length."""
        wf = _make_wf(per_window_returns=[[0.01, -0.005, 0.02, -0.01]])
        report = evaluate_calibration(wf, confidences=[0.7, 0.3, 0.8, 0.2], n_bins=5)
        assert len(report.calibration_curve) == 5
        report = evaluate_calibration(wf, confidences=[0.7, 0.3, 0.8, 0.2], n_bins=20)
        assert len(report.calibration_curve) == 20

    def test_perfect_calibration_synthetic(self):
        """End-to-end: synthetic perfect-calibration system has low BS.

        100 signals all predict 0.9; actual win rate is 90/100 = 0.9.
        All samples in one bin (0.9, 1.0], mean conf = 0.9 = bin wr, so
        reliability = 0 and BS = uncertainty = 0.9 * 0.1 = 0.09.
        """
        confs = [0.9] * 100
        outcomes = [1] * 90 + [0] * 10
        # wf_results irrelevant here (outcomes explicit) but needs to exist.
        wf = _make_wf(per_window_returns=[[0.01] * 90 + [-0.01] * 10])
        report = evaluate_calibration(wf, confidences=confs, outcomes=outcomes, n_bins=10)
        # BS = 0.01 per sample * 100 / 100 = 0.01 (all (0.9-1)² or (0.9-0)² = 0.01)
        # Wait: for the 90 wins, (0.9-1)² = 0.01; for 10 losses, (0.9-0)² = 0.81.
        # BS = (90*0.01 + 10*0.81) / 100 = (0.9 + 8.1) / 100 = 0.09
        assert report.brier_score == pytest.approx(0.09, abs=1e-12)
        # Perfect calibration within bin → reliability = 0
        assert report.reliability == pytest.approx(0.0, abs=1e-12)
        # All in one bin, so resolution = (0.9 - 0.9)² = 0
        assert report.resolution == pytest.approx(0.0, abs=1e-12)
        # base win rate = 0.9
        assert report.base_win_rate == pytest.approx(0.9)
        # uncertainty = 0.9 * 0.1 = 0.09
        assert report.uncertainty == pytest.approx(0.09)
        # Identity holds exactly (single value per bin)
        assert report.brier_score == pytest.approx(
            report.reliability - report.resolution + report.uncertainty, abs=1e-12
        )
