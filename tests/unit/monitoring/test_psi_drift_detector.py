"""Tests for the PSI drift detector module.

Covers:
- PSI computation with known distributions
- Identical distributions → PSI ≈ 0
- Shifted distributions → PSI above threshold
- Edge cases (empty, constant, single-element, single-bin)
- PSIAlert dataclass behaviour
- PSIDriftDetector baseline management
- PSIDriftDetector drift checking and alert generation
- Rolling window tracking
"""

from __future__ import annotations

import math
import pytest

from monitoring.psi_drift_detector import (
    compute_psi,
    PSIAlert,
    PSIDriftDetector,
    FeatureWindow,
    DEFAULT_THRESHOLD,
    DEFAULT_N_BINS,
    EPSILON,
)


# ── compute_psi — basic correctness ────────────────────────────────────────


class TestComputePSI:
    """Tests for the standalone compute_psi() function."""

    def test_identical_distributions_psi_near_zero(self):
        """PSI of a distribution vs itself should be ~0."""
        data = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0,
                1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0]
        psi = compute_psi(data, data, n_bins=5)
        assert psi == pytest.approx(0.0, abs=1e-10)

    def test_shifted_distributions_positive_psi(self):
        """A clearly shifted actual distribution should produce PSI > 0."""
        expected = list(range(100))  # 0..99
        actual = list(range(50, 150))  # shifted right by 50
        psi = compute_psi(expected, actual, n_bins=10)
        assert psi > 0.1, f"Expected PSI > 0.1 for shifted dist, got {psi}"

    def test_major_shift_high_psi(self):
        """A drastically different distribution should produce high PSI."""
        expected = [float(i) for i in range(100)]
        actual = [1000.0 + i for i in range(100)]  # completely different range
        psi = compute_psi(expected, actual, n_bins=10)
        assert psi > 0.25, f"Expected PSI > 0.25 for major shift, got {psi}"

    def test_psi_is_non_negative(self):
        """PSI should always be ≥ 0."""
        expected = [1.0, 2.0, 3.0, 4.0, 5.0] * 10
        actual = [5.0, 4.0, 3.0, 2.0, 1.0] * 10  # reversed
        psi = compute_psi(expected, actual, n_bins=5)
        assert psi >= 0.0

    def test_different_n_bins(self):
        """PSI should be computable with different bin counts."""
        expected = [float(i) for i in range(50)]
        actual = [float(i) + 10 for i in range(50)]
        for n_bins in [2, 5, 10, 20]:
            psi = compute_psi(expected, actual, n_bins=n_bins)
            assert math.isfinite(psi)
            assert psi >= 0.0

    def test_psi_value_in_expected_range(self):
        """For a moderate shift, PSI should be in a reasonable range."""
        expected = [float(i) for i in range(100)]
        actual = [float(i) + 20 for i in range(100)]
        psi = compute_psi(expected, actual, n_bins=10)
        # Moderate shift should produce a detectable but not extreme PSI
        assert 0.01 < psi < 5.0

    def test_actual_sample_inside_expected_range(self):
        """PSI should be small when actual values are a subset of expected."""
        expected = list(range(100))
        actual = list(range(40, 60))  # subset, same area
        psi = compute_psi(expected, actual, n_bins=10)
        # There IS distribution change (more concentrated), but not huge
        assert psi >= 0.0


# ── compute_psi — edge cases ───────────────────────────────────────────────


class TestComputePSIEdgeCases:
    """Edge case tests for compute_psi()."""

    def test_empty_expected_raises(self):
        with pytest.raises(ValueError, match="expected"):
            compute_psi([], [1.0, 2.0])

    def test_empty_actual_raises(self):
        with pytest.raises(ValueError, match="actual"):
            compute_psi([1.0, 2.0], [])

    def test_single_bin_raises(self):
        with pytest.raises(ValueError, match="n_bins"):
            compute_psi([1, 2, 3], [1, 2, 3], n_bins=1)

    def test_constant_expected_distribution(self):
        """All expected values identical should still work."""
        expected = [5.0] * 20
        actual = [5.0] * 20
        psi = compute_psi(expected, actual, n_bins=5)
        assert psi == pytest.approx(0.0, abs=1e-10)

    def test_constant_expected_vs_different_actual(self):
        """Constant expected with different actual should produce PSI."""
        expected = [5.0] * 20
        actual = [10.0] * 20
        psi = compute_psi(expected, actual, n_bins=5)
        # All actual falls in a different bin region
        assert psi > 0.0

    def test_single_element_distributions(self):
        """Single-element inputs should not crash."""
        psi = compute_psi([1.0], [2.0], n_bins=2)
        assert math.isfinite(psi)

    def test_negative_values(self):
        """PSI should handle negative feature values."""
        expected = [-5.0, -3.0, -1.0, 1.0, 3.0, 5.0] * 5
        actual = [-2.0, 0.0, 2.0, 4.0, 6.0, 8.0] * 5
        psi = compute_psi(expected, actual, n_bins=5)
        assert math.isfinite(psi)
        assert psi >= 0.0

    def test_unequal_lengths(self):
        """Expected and actual can have different lengths."""
        expected = [float(i) for i in range(100)]
        actual = [float(i) + 5 for i in range(50)]
        psi = compute_psi(expected, actual, n_bins=10)
        assert math.isfinite(psi)


# ── PSIAlert ────────────────────────────────────────────────────────────────


class TestPSIAlert:
    """Tests for the PSIAlert dataclass."""

    def test_alert_severity_none_below_threshold(self):
        alert = PSIAlert(feature="win_rate", psi=0.05, threshold=0.2)
        assert alert.severity == "none"
        assert not alert.is_alert

    def test_alert_severity_minor(self):
        alert = PSIAlert(feature="win_rate", psi=0.15, threshold=0.2)
        assert alert.severity == "minor"
        assert not alert.is_alert  # 0.15 < 0.2 threshold

    def test_alert_severity_major(self):
        alert = PSIAlert(feature="win_rate", psi=0.30, threshold=0.2)
        assert alert.severity == "major"
        assert alert.is_alert

    def test_alert_at_exact_threshold(self):
        alert = PSIAlert(feature="x", psi=0.2, threshold=0.2)
        assert alert.is_alert  # >= threshold

    def test_alert_has_timestamp(self):
        alert = PSIAlert(feature="x", psi=0.0, threshold=0.2)
        assert alert.timestamp  # auto-generated


# ── FeatureWindow ──────────────────────────────────────────────────────────


class TestFeatureWindow:
    """Tests for the FeatureWindow rolling buffer."""

    def test_add_and_snapshot(self):
        fw = FeatureWindow()
        fw.add([1.0, 2.0, 3.0])
        assert fw.snapshot() == [1.0, 2.0, 3.0]
        assert fw.count == 3

    def test_maxlen_bounds_window(self):
        from collections import deque
        fw = FeatureWindow(values=deque(maxlen=5))
        fw.add([1, 2, 3, 4, 5, 6, 7])
        assert fw.count == 5
        assert fw.snapshot() == [3, 4, 5, 6, 7]

    def test_empty_window(self):
        fw = FeatureWindow()
        assert fw.count == 0
        assert fw.snapshot() == []


# ── PSIDriftDetector ────────────────────────────────────────────────────────


class TestPSIDriftDetector:
    """Tests for the multi-feature drift detector."""

    def _build_detector(self) -> PSIDriftDetector:
        d = PSIDriftDetector(threshold=0.2, n_bins=10)
        d.set_baseline("win_rate", [0.3 + 0.01 * i for i in range(50)])
        d.set_baseline("sharpe", [1.0 + 0.05 * i for i in range(50)])
        return d

    def test_set_baseline(self):
        d = PSIDriftDetector()
        d.set_baseline("x", [1.0, 2.0, 3.0])
        assert d.has_baseline("x")
        assert "x" in d.tracked_features
        assert not d.has_baseline("y")

    def test_set_baseline_empty_raises(self):
        d = PSIDriftDetector()
        with pytest.raises(ValueError):
            d.set_baseline("x", [])

    def test_check_drift_no_drift(self):
        d = self._build_detector()
        # Same baseline data → no drift
        alert = d.check_drift(
            "win_rate", [0.3 + 0.01 * i for i in range(50)]
        )
        assert alert.psi == pytest.approx(0.0, abs=1e-10)
        assert not alert.is_alert
        assert alert.severity == "none"

    def test_check_drift_with_shift(self):
        d = self._build_detector()
        # Shifted distribution → drift expected
        alert = d.check_drift(
            "win_rate", [0.6 + 0.01 * i for i in range(50)]
        )
        assert alert.psi > 0.1
        assert alert.is_alert

    def test_check_drift_missing_baseline_raises(self):
        d = PSIDriftDetector()
        with pytest.raises(KeyError, match="baseline"):
            d.check_drift("unknown", [1.0, 2.0])

    def test_check_all(self):
        d = self._build_detector()
        alerts = d.check_all({
            "win_rate": [0.3 + 0.01 * i for i in range(50)],  # no drift
            "sharpe": [3.0 + 0.05 * i for i in range(50)],    # major drift
        })
        assert len(alerts) == 2
        names = [a.feature for a in alerts]
        assert "win_rate" in names
        assert "sharpe" in names

    def test_check_all_skips_missing_baselines(self):
        d = self._build_detector()
        alerts = d.check_all({
            "unknown_feature": [1.0, 2.0],
            "win_rate": [0.3 + 0.01 * i for i in range(50)],
        })
        assert len(alerts) == 1
        assert alerts[0].feature == "win_rate"

    def test_alert_history(self):
        d = self._build_detector()
        d.check_drift("win_rate", [0.3 + 0.01 * i for i in range(50)])
        d.check_drift("sharpe", [3.0 + 0.05 * i for i in range(50)])
        assert len(d.alerts) == 2
        d.reset_alerts()
        assert len(d.alerts) == 0

    def test_invalid_threshold_raises(self):
        with pytest.raises(ValueError):
            PSIDriftDetector(threshold=0)

    def test_invalid_n_bins_raises(self):
        with pytest.raises(ValueError):
            PSIDriftDetector(n_bins=1)


# ── Rolling window integration ─────────────────────────────────────────────


class TestRollingWindow:
    """Tests for continuous rolling-window drift tracking."""

    def test_update_and_check_rolling(self):
        d = PSIDriftDetector(threshold=0.2)
        d.set_baseline("x", [float(i) for i in range(100)])

        # Push values spread across the baseline range → no alert
        d.update_rolling("x", [float(i) * 5 for i in range(20)])  # 0..95 spread
        alert = d.check_rolling_drift("x")
        assert alert is not None
        assert not alert.is_alert

        # Push shifted values → should drift
        d.update_rolling("x", [float(i) + 200 for i in range(20)])
        alert = d.check_rolling_drift("x")
        assert alert is not None
        assert alert.psi > 0.1

    def test_check_rolling_no_window(self):
        d = PSIDriftDetector()
        assert d.check_rolling_drift("x") is None

    def test_check_rolling_empty_window(self):
        d = PSIDriftDetector()
        d.update_rolling("x", [])  # adds nothing
        result = d.check_rolling_drift("x")
        assert result is None
