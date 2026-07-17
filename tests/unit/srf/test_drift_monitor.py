"""Tests for srf.drift_monitor — PSI/KS distribution drift detection.

Covers:
- PSI computation correctness (known distributions, edge cases)
- KS test wrapper
- DriftMonitor class lifecycle
- DriftReport aggregation
- Edge cases: empty data, NaN handling, constant features, single bin
- Realistic signal_engine-like feature scenarios
"""

import math
import numpy as np
import pandas as pd
import pytest

from srf.drift_monitor import (
    DriftMonitor,
    DriftReport,
    DriftResult,
    compute_psi,
    compute_ks_test,
    DEFAULT_PSI_THRESHOLD,
    DEFAULT_KS_ALPHA,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RNG = np.random.default_rng(seed=42)


@pytest.fixture
def stable_reference() -> pd.DataFrame:
    """Baseline features drawn from standard normal."""
    return pd.DataFrame(
        {
            "feature_a": RNG.normal(0, 1, 1000),
            "feature_b": RNG.normal(5, 2, 1000),
            "feature_c": RNG.uniform(0, 10, 1000),
        }
    )


@pytest.fixture
def stable_current(stable_reference) -> pd.DataFrame:
    """Current data drawn from the same distributions (no drift)."""
    return pd.DataFrame(
        {
            "feature_a": RNG.normal(0, 1, 500),
            "feature_b": RNG.normal(5, 2, 500),
            "feature_c": RNG.uniform(0, 10, 500),
        }
    )


@pytest.fixture
def drifted_current() -> pd.DataFrame:
    """Current data with clear distribution shift."""
    return pd.DataFrame(
        {
            "feature_a": RNG.normal(2, 1.5, 500),   # mean + variance shift
            "feature_b": RNG.normal(8, 3, 500),      # mean + variance shift
            "feature_c": RNG.uniform(5, 15, 500),    # range shift
        }
    )


# ---------------------------------------------------------------------------
# compute_psi tests
# ---------------------------------------------------------------------------


class TestComputePSI:
    def test_identical_distributions_psi_near_zero(self):
        """PSI of identical distributions should be ≈ 0."""
        data = RNG.normal(0, 1, 2000)
        psi = compute_psi(data, data)
        assert psi < 0.01, f"PSI for identical dist should be ~0, got {psi}"

    def test_similar_distributions_low_psi(self):
        """PSI between two samples from the same distribution should be low."""
        ref = RNG.normal(0, 1, 5000)
        cur = RNG.normal(0, 1, 5000)
        psi = compute_psi(ref, cur)
        assert psi < 0.1, f"PSI for same dist samples should be <0.1, got {psi}"

    def test_shifted_mean_moderate_psi(self):
        """Moderate mean shift should produce detectable PSI."""
        ref = RNG.normal(0, 1, 5000)
        cur = RNG.normal(1, 1, 5000)
        psi = compute_psi(ref, cur)
        assert psi > 0.1, f"PSI for mean-shifted dist should be >0.1, got {psi}"

    def test_large_shift_high_psi(self):
        """Large distribution shift should produce high PSI."""
        ref = RNG.normal(0, 1, 5000)
        cur = RNG.normal(5, 2, 5000)
        psi = compute_psi(ref, cur)
        assert psi > 0.25, f"PSI for large shift should be >0.25, got {psi}"

    def test_psi_non_negative(self):
        """PSI is always non-negative."""
        ref = RNG.normal(0, 1, 500)
        cur = RNG.normal(3, 0.5, 500)
        psi = compute_psi(ref, cur)
        assert psi >= 0

    def test_empty_reference_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            compute_psi([], [1, 2, 3])

    def test_empty_current_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            compute_psi([1, 2, 3], [])

    def test_custom_n_bins(self):
        """PSI should work with different bin counts."""
        ref = RNG.normal(0, 1, 1000)
        cur = RNG.normal(1, 1, 1000)
        psi_5 = compute_psi(ref, cur, n_bins=5)
        psi_20 = compute_psi(ref, cur, n_bins=20)
        # Both should detect drift
        assert psi_5 > 0.05
        assert psi_20 > 0.05

    def test_constant_feature(self):
        """Constant feature (all same value) should not crash."""
        ref = np.full(100, 5.0)
        cur = np.full(100, 5.0)
        psi = compute_psi(ref, cur)
        # With constant values, all go into one bin — PSI should be ~0
        assert psi < 0.01

    def test_nan_values_handled(self):
        """NaN values in input should be dropped, not crash."""
        ref = np.array([1, 2, np.nan, 3, 4, np.nan, 5, 6, 7, 8])
        cur = np.array([1, 2, 3, 4, np.nan, 5, 6, 7, 8, 9])
        psi = compute_psi(ref, cur)
        assert isinstance(psi, float)
        assert psi >= 0

    def test_pandas_series_input(self):
        """Function should accept pandas Series."""
        ref = pd.Series(RNG.normal(0, 1, 500))
        cur = pd.Series(RNG.normal(0, 1, 500))
        psi = compute_psi(ref, cur)
        assert 0 <= psi < 0.1


# ---------------------------------------------------------------------------
# compute_ks_test tests
# ---------------------------------------------------------------------------


class TestComputeKSTest:
    def test_identical_distributions_high_pvalue(self):
        """KS test on identical data should give high p-value."""
        data = RNG.normal(0, 1, 1000)
        stat, pval = compute_ks_test(data, data)
        assert pval > 0.5, f"p-value for identical data should be high, got {pval}"

    def test_different_distributions_low_pvalue(self):
        """KS test should reject H0 for clearly different distributions."""
        ref = RNG.normal(0, 1, 2000)
        cur = RNG.normal(3, 1, 2000)
        stat, pval = compute_ks_test(ref, cur)
        assert pval < 0.001, f"p-value for different dists should be tiny, got {pval}"
        assert stat > 0.3

    def test_returns_floats(self):
        ref = RNG.normal(0, 1, 100)
        cur = RNG.normal(0, 1, 100)
        stat, pval = compute_ks_test(ref, cur)
        assert isinstance(stat, float)
        assert isinstance(pval, float)

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            compute_ks_test([], [1, 2, 3])


# ---------------------------------------------------------------------------
# DriftResult tests
# ---------------------------------------------------------------------------


class TestDriftResult:
    def _make(self, psi=0.05, ks_p=0.5, psi_thr=0.2, ks_alpha=0.05):
        return DriftResult(
            feature="test_feature",
            psi=psi,
            ks_statistic=0.1,
            ks_pvalue=ks_p,
            psi_threshold=psi_thr,
            ks_alpha=ks_alpha,
        )

    def test_no_drift(self):
        r = self._make(psi=0.05, ks_p=0.5)
        assert not r.psi_drift
        assert not r.ks_drift
        assert not r.is_drifted

    def test_psi_drift_only(self):
        r = self._make(psi=0.3, ks_p=0.5)
        assert r.psi_drift
        assert not r.ks_drift
        assert r.is_drifted

    def test_ks_drift_only(self):
        r = self._make(psi=0.05, ks_p=0.01)
        assert not r.psi_drift
        assert r.ks_drift
        assert r.is_drifted

    def test_severity_none(self):
        r = self._make(psi=0.05)
        assert r.severity() == "none"

    def test_severity_moderate(self):
        r = self._make(psi=0.15)
        assert r.severity() == "moderate"

    def test_severity_high(self):
        r = self._make(psi=0.3)
        assert r.severity() == "high"

    def test_str_contains_feature_name(self):
        r = self._make(psi=0.3)
        assert "test_feature" in str(r)
        assert "DRIFT" in str(r)


# ---------------------------------------------------------------------------
# DriftReport tests
# ---------------------------------------------------------------------------


class TestDriftReport:
    def test_empty_report(self):
        report = DriftReport()
        assert not report.has_drift
        assert report.alerts() == []
        assert len(list(report)) == 0

    def test_all_stable(self):
        results = [
            DriftResult("a", 0.01, 0.05, 0.8, 0.2, 0.05),
            DriftResult("b", 0.03, 0.02, 0.6, 0.2, 0.05),
        ]
        report = DriftReport(results=results)
        assert not report.has_drift
        assert report.alerts() == []
        assert "stable" in report.summary().lower()

    def test_mixed(self):
        results = [
            DriftResult("stable_feat", 0.01, 0.05, 0.8, 0.2, 0.05),
            DriftResult("drifted_feat", 0.35, 0.4, 0.001, 0.2, 0.05),
        ]
        report = DriftReport(results=results)
        assert report.has_drift
        assert len(report.alerts()) == 1
        assert report.alerts()[0].feature == "drifted_feat"
        assert "1/2" in report.summary()


# ---------------------------------------------------------------------------
# DriftMonitor tests
# ---------------------------------------------------------------------------


class TestDriftMonitor:
    def test_init_with_valid_reference(self, stable_reference):
        mon = DriftMonitor(stable_reference)
        assert set(mon.features) == {"feature_a", "feature_b", "feature_c"}
        assert mon.psi_threshold == DEFAULT_PSI_THRESHOLD
        assert mon.ks_alpha == DEFAULT_KS_ALPHA

    def test_init_with_explicit_features(self, stable_reference):
        mon = DriftMonitor(stable_reference, features=["feature_a"])
        assert mon.features == ["feature_a"]

    def test_init_custom_thresholds(self, stable_reference):
        mon = DriftMonitor(
            stable_reference,
            psi_threshold=0.15,
            ks_alpha=0.01,
            n_bins=5,
        )
        assert mon.psi_threshold == 0.15
        assert mon.ks_alpha == 0.01
        assert mon.n_bins == 5

    def test_init_empty_reference_raises(self):
        with pytest.raises(ValueError, match="empty"):
            DriftMonitor(pd.DataFrame())

    def test_init_missing_feature_raises(self, stable_reference):
        with pytest.raises(KeyError, match="not in reference"):
            DriftMonitor(stable_reference, features=["nonexistent"])

    def test_init_all_nan_column_raises(self):
        df = pd.DataFrame({"good": [1, 2, 3], "bad": [np.nan, np.nan, np.nan]})
        with pytest.raises(ValueError, match="no non-NaN"):
            DriftMonitor(df, features=["good", "bad"])

    def test_check_drift_stable(self, stable_reference, stable_current):
        mon = DriftMonitor(stable_reference)
        report = mon.check_drift(stable_current)
        assert isinstance(report, DriftReport)
        assert len(report.results) == 3
        # Same distributions — should not flag drift
        assert not report.has_drift, (
            f"Expected no drift for stable data, but got alerts: {report.alerts()}"
        )

    def test_check_drift_shifted(self, stable_reference, drifted_current):
        mon = DriftMonitor(stable_reference)
        report = mon.check_drift(drifted_current)
        assert report.has_drift
        assert len(report.alerts()) == 3
        for alert in report.alerts():
            assert alert.psi > 0.1 or alert.ks_pvalue < 0.05

    def test_check_drift_subset_features(self, stable_reference, stable_current):
        mon = DriftMonitor(stable_reference, features=["feature_a", "feature_b"])
        report = mon.check_drift(stable_current, features=["feature_a"])
        assert len(report.results) == 1
        assert report.results[0].feature == "feature_a"

    def test_check_drift_missing_feature_in_current(self, stable_reference):
        mon = DriftMonitor(stable_reference)
        current = pd.DataFrame({"feature_a": [1, 2, 3]})
        with pytest.raises(KeyError, match="not in current"):
            mon.check_drift(current)

    def test_check_drift_empty_current_column(self, stable_reference):
        """If current column is all NaN, result should have NaN metrics."""
        mon = DriftMonitor(stable_reference, features=["feature_a"])
        current = pd.DataFrame({"feature_a": [np.nan, np.nan, np.nan]})
        report = mon.check_drift(current)
        assert len(report.results) == 1
        r = report.results[0]
        assert math.isnan(r.psi)
        assert math.isnan(r.ks_pvalue)

    def test_reference_sizes(self, stable_reference):
        mon = DriftMonitor(stable_reference)
        sizes = mon.reference_sizes
        assert all(s == 1000 for s in sizes.values())

    def test_add_reference_samples(self, stable_reference):
        mon = DriftMonitor(stable_reference, features=["feature_a"])
        original_size = mon.reference_sizes["feature_a"]
        mon.add_reference_samples("feature_a", np.array([1.0, 2.0, 3.0]))
        assert mon.reference_sizes["feature_a"] == original_size + 3

    def test_add_reference_samples_unknown_feature(self, stable_reference):
        mon = DriftMonitor(stable_reference)
        with pytest.raises(KeyError, match="unknown feature"):
            mon.add_reference_samples("nonexistent", np.array([1.0]))

    def test_auto_detect_numeric_columns(self):
        """If features=None, only numeric columns should be selected."""
        df = pd.DataFrame(
            {
                "num1": [1.0, 2.0, 3.0, 4.0, 5.0],
                "num2": [6.0, 7.0, 8.0, 9.0, 10.0],
                "cat": ["a", "b", "c", "d", "e"],
            }
        )
        mon = DriftMonitor(df)
        assert "num1" in mon.features
        assert "num2" in mon.features
        assert "cat" not in mon.features

    def test_only_numeric_when_explicit_non_numeric_given(self):
        df = pd.DataFrame({"num": [1, 2, 3], "text": ["a", "b", "c"]})
        with pytest.raises((KeyError, ValueError, TypeError)):
            DriftMonitor(df, features=["text"])


# ---------------------------------------------------------------------------
# Realistic signal_engine-like feature scenarios
# ---------------------------------------------------------------------------


class TestSignalEngineScenarios:
    """Simulate drift scenarios on ICT/signal_engine-like feature distributions."""

    def _make_ict_features(self, n: int, mu: float = 0, sigma: float = 1) -> pd.DataFrame:
        """Generate synthetic ICT-feature-like data."""
        return pd.DataFrame(
            {
                "ict_confluence_score": np.clip(RNG.normal(mu + 0.5, sigma * 0.3, n), 0, 1),
                "ict_structure_score": np.clip(RNG.normal(mu + 0.4, sigma * 0.25, n), 0, 1),
                "ict_ob_score": np.clip(RNG.normal(mu + 0.3, sigma * 0.2, n), 0, 1),
                "ict_fvg_score": np.clip(RNG.normal(mu + 0.2, sigma * 0.2, n), 0, 1),
                "ict_bias_encoded": RNG.choice([-1, 0, 1], size=n),
            }
        )

    def test_baseline_to_production_no_drift(self):
        ref = self._make_ict_features(2000)
        cur = self._make_ict_features(1000)
        mon = DriftMonitor(ref)
        report = mon.check_drift(cur)
        # ICT features from same distribution — most should be stable
        n_drifted = len(report.alerts())
        assert n_drifted <= 1, (
            f"Expected ≤1 drifted feature for stable data, got {n_drifted}: "
            f"{[a.feature for a in report.alerts()]}"
        )

    def test_regime_change_detected(self):
        """Simulate market regime change — scores shift upward."""
        ref = self._make_ict_features(2000, mu=0)
        cur = self._make_ict_features(1000, mu=0.5, sigma=1.5)
        mon = DriftMonitor(ref)
        report = mon.check_drift(cur)
        assert report.has_drift
        drifted_features = {a.feature for a in report.alerts()}
        # At least the continuous-score features should drift
        assert "ict_confluence_score" in drifted_features or "ict_structure_score" in drifted_features

    def test_report_summary_contains_counts(self):
        ref = self._make_ict_features(500)
        cur = self._make_ict_features(200, mu=0.5)
        mon = DriftMonitor(ref)
        report = mon.check_drift(cur)
        summary = report.summary()
        assert "/" in summary  # "N/M features drifted"
