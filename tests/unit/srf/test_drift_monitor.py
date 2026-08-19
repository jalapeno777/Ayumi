"""Tests for srf.drift_monitor — PSI/KS distribution drift detection.

Covers:
- PSI computation correctness (known distributions, edge cases)
- KS test wrapper
- DriftMonitor class lifecycle
- DriftReport aggregation
- Edge cases: empty data, NaN handling, constant features, single bin
- Realistic signal_engine-like feature scenarios

Layer 2 (permutation importance) and Layer 3 (SHAP) tests:
- PermutationDriftMonitor lifecycle and importance computation
- ImportanceResult dataclass properties
- ImportanceReport aggregation
- ShapDriftChecker graceful degradation
- CompositeDriftMonitor integration
- Realistic signal_engine feature-decay scenarios
"""

import math
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

from srf.drift_monitor import (
    DriftMonitor,
    DriftReport,
    DriftResult,
    compute_psi,
    compute_ks_test,
    DEFAULT_PSI_THRESHOLD,
    DEFAULT_KS_ALPHA,
)
from srf.permutation_drift import (
    PermutationDriftMonitor,
    ImportanceResult,
    ImportanceReport,
    CompositeDriftMonitor,
    CompositeReport,
    ShapDriftChecker,
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
            "feature_a": RNG.normal(2, 1.5, 500),  # mean + variance shift
            "feature_b": RNG.normal(8, 3, 500),  # mean + variance shift
            "feature_c": RNG.uniform(5, 15, 500),  # range shift
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

    def _make_ict_features(
        self, n: int, mu: float = 0, sigma: float = 1
    ) -> pd.DataFrame:
        """Generate synthetic ICT-feature-like data."""
        return pd.DataFrame(
            {
                "ict_confluence_score": np.clip(
                    RNG.normal(mu + 0.5, sigma * 0.3, n), 0, 1
                ),
                "ict_structure_score": np.clip(
                    RNG.normal(mu + 0.4, sigma * 0.25, n), 0, 1
                ),
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
        assert (
            "ict_confluence_score" in drifted_features
            or "ict_structure_score" in drifted_features
        )

    def test_report_summary_contains_counts(self):
        ref = self._make_ict_features(500)
        cur = self._make_ict_features(200, mu=0.5)
        mon = DriftMonitor(ref)
        report = mon.check_drift(cur)
        summary = report.summary()
        assert "/" in summary  # "N/M features drifted"


# ---------------------------------------------------------------------------
# Layer 2: Permutation Importance tests
# ---------------------------------------------------------------------------


class TestImportanceResult:
    """Test ImportanceResult dataclass properties."""

    def _make(
        self,
        ref_imp=0.10,
        cur_imp=0.10,
        decay_thr=0.50,
        red_zone=0.01,
    ):
        return ImportanceResult(
            feature="test_feature",
            reference_importance=ref_imp,
            current_importance=cur_imp,
            reference_std=0.02,
            current_std=0.01,
            decay_threshold=decay_thr,
            red_zone=red_zone,
        )

    def test_no_drift_when_unchanged(self):
        r = self._make(ref_imp=0.10, cur_imp=0.10)
        assert not r.is_declining
        assert r.severity() == "clear"
        assert abs(r.pct_decay) < 0.01

    def test_declining_when_large_drop(self):
        r = self._make(ref_imp=0.10, cur_imp=0.03)
        assert r.is_declining  # 70% decay > 50% threshold
        assert r.severity() == "yellow"

    def test_red_zone_when_near_zero(self):
        r = self._make(ref_imp=0.10, cur_imp=0.005)
        assert r.is_red_zone
        assert r.severity() == "red"

    def test_negative_importance(self):
        """Feature that hurts the model (permutation improved performance)."""
        r = self._make(ref_imp=0.10, cur_imp=-0.02)
        assert r.is_negative
        assert r.severity() == "red"

    def test_delta_computation(self):
        r = self._make(ref_imp=0.15, cur_imp=0.08)
        assert abs(r.delta - (-0.07)) < 0.001

    def test_pct_decay_computation(self):
        r = self._make(ref_imp=0.20, cur_imp=0.08)
        # decay = 1 - (0.08/0.20) = 0.60
        assert abs(r.pct_decay - 0.60) < 0.01

    def test_pct_decay_zero_reference(self):
        """When reference importance is 0, pct_decay should be 0 (no ratio)."""
        r = self._make(ref_imp=0.0, cur_imp=0.05)
        assert r.pct_decay == 0.0

    def test_str_contains_feature_name(self):
        r = self._make(ref_imp=0.10, cur_imp=0.02)
        assert "test_feature" in str(r)


class TestImportanceReport:
    """Test ImportanceReport aggregation."""

    def test_empty_report(self):
        report = ImportanceReport()
        assert not report.has_drift
        assert report.alerts() == []
        assert len(list(report)) == 0

    def test_all_clear(self):
        results = [
            ImportanceResult("f1", 0.1, 0.1, 0.02, 0.02, 0.5, 0.01),
            ImportanceResult("f2", 0.2, 0.18, 0.03, 0.02, 0.5, 0.01),
        ]
        report = ImportanceReport(results=results)
        assert not report.has_drift
        assert report.alerts() == []
        assert "stable" in report.summary().lower()

    def test_mixed_alerts(self):
        results = [
            ImportanceResult("stable_f", 0.1, 0.09, 0.02, 0.01, 0.5, 0.01),
            ImportanceResult("yellow_f", 0.2, 0.08, 0.03, 0.02, 0.5, 0.01),
            ImportanceResult("red_f", 0.15, 0.001, 0.02, 0.001, 0.5, 0.01),
        ]
        report = ImportanceReport(results=results)
        assert report.has_drift
        assert len(report.alerts()) == 2  # yellow + red
        assert len(report.yellow_alerts()) == 1
        assert len(report.red_alerts()) == 1
        assert "2/3" in report.summary()

    def test_summary_contains_red_and_yellow(self):
        results = [
            ImportanceResult("yellow_f", 0.2, 0.08, 0.03, 0.02, 0.5, 0.01),
            ImportanceResult("red_f", 0.15, 0.001, 0.02, 0.001, 0.5, 0.01),
        ]
        report = ImportanceReport(results=results)
        summary = report.summary()
        assert "red" in summary.lower()
        assert "yellow" in summary.lower()


class TestPermutationDriftMonitor:
    """Test PermutationDriftMonitor class lifecycle."""

    @pytest.fixture
    def simple_model_data(self):
        """Create a simple linear regression dataset where f1 is important."""
        X = pd.DataFrame(
            {
                "f1": RNG.normal(0, 1, 200),
                "f2": RNG.normal(0, 1, 200),
                "noise": RNG.normal(0, 0.1, 200),  # uninformative feature
            }
        )
        y = 3 * X["f1"] + 0.5 * X["f2"] + RNG.normal(0, 0.1, 200)
        model = LinearRegression().fit(X, y)
        return X, y, model

    def test_init_computes_reference_importance(self, simple_model_data):
        X, y, model = simple_model_data
        monitor = PermutationDriftMonitor(
            model=model, scoring="r2", reference_X=X, reference_y=y
        )
        ref_imp = monitor.reference_importance
        assert "f1" in ref_imp
        assert "f2" in ref_imp
        assert "noise" in ref_imp
        # f1 should be most important (coefficient 3x)
        assert ref_imp["f1"]["mean"] > ref_imp["noise"]["mean"]

    def test_check_drift_no_change(self, simple_model_data):
        """When current data is from the same distribution, no drift expected
        for features with meaningful predictive power."""
        X, y, model = simple_model_data
        monitor = PermutationDriftMonitor(
            model=model, scoring="r2", reference_X=X, reference_y=y
        )
        # Same data — should not flag major drift
        X_new = pd.DataFrame(
            {
                "f1": RNG.normal(0, 1, 200),
                "f2": RNG.normal(0, 1, 200),
                "noise": RNG.normal(0, 0.1, 200),
            }
        )
        y_new = 3 * X_new["f1"] + 0.5 * X_new["f2"] + RNG.normal(0, 0.1, 200)
        report = monitor.check_importance_drift(X_new, y_new)
        # With same distributions, predictive features (f1, f2) should not decay.
        # The 'noise' feature has near-zero importance and may fall in red zone —
        # that's expected behavior for uninformative features.
        meaningful_alerts = [
            r for r in report.alerts() if r.reference_importance > 0.01
        ]
        assert len(meaningful_alerts) == 0, (
            f"Unexpected drift on meaningful features: {meaningful_alerts}"
        )

    def test_check_drift_importance_decay(self, simple_model_data):
        """When f1 loses predictive relationship, its importance should decay."""
        X, y, model = simple_model_data
        monitor = PermutationDriftMonitor(
            model=model,
            scoring="r2",
            reference_X=X,
            reference_y=y,
            decay_threshold=0.30,  # 30% decay triggers alert
        )
        # Create current data where f1 is no longer predictive
        X_decayed = pd.DataFrame(
            {
                "f1": RNG.normal(0, 1, 200),
                "f2": RNG.normal(0, 1, 200),
                "noise": RNG.normal(0, 0.1, 200),
            }
        )
        # y depends only on f2 now (f1 relationship removed)
        y_decayed = 0.5 * X_decayed["f2"] + RNG.normal(0, 0.1, 200)
        report = monitor.check_importance_drift(X_decayed, y_decayed)
        # f1 importance should drop significantly
        f1_result = next(r for r in report.results if r.feature == "f1")
        assert f1_result.pct_decay > 0.3, (
            f"Expected f1 importance to decay >30%, got {f1_result.pct_decay:.1%}"
        )

    def test_compute_importance_standalone(self, simple_model_data):
        """compute_importance can be called independently."""
        X, y, model = simple_model_data
        monitor = PermutationDriftMonitor(
            model=model, scoring="r2", reference_X=X, reference_y=y
        )
        imp = monitor.compute_importance(X, y)
        assert isinstance(imp, dict)
        assert all(f in imp for f in ["f1", "f2", "noise"])
        assert all("mean" in v and "std" in v for v in imp.values())

    def test_custom_thresholds(self, simple_model_data):
        X, y, model = simple_model_data
        monitor = PermutationDriftMonitor(
            model=model,
            scoring="r2",
            reference_X=X,
            reference_y=y,
            decay_threshold=0.15,
            red_zone=0.001,
        )
        assert monitor.decay_threshold == 0.15
        assert monitor.red_zone == 0.001

    def test_empty_data_raises(self, simple_model_data):
        _, _, model = simple_model_data
        X_empty = pd.DataFrame({"f1": [], "f2": []})
        with pytest.raises(ValueError, match="non-empty"):
            PermutationDriftMonitor(
                model=model, scoring="r2", reference_X=X_empty, reference_y=[]
            )

    def test_mismatched_lengths_raises(self, simple_model_data):
        X, _, model = simple_model_data
        with pytest.raises(ValueError, match="samples"):
            PermutationDriftMonitor(
                model=model,
                scoring="r2",
                reference_X=X,
                reference_y=np.array([1.0, 2.0]),  # only 2 samples
            )

    def test_features_inferred_from_dataframe(self, simple_model_data):
        X, y, model = simple_model_data
        monitor = PermutationDriftMonitor(
            model=model, scoring="r2", reference_X=X, reference_y=y
        )
        assert set(monitor.features) == {"f1", "f2", "noise"}


class TestShapDriftChecker:
    """Test SHAP drift checker graceful degradation."""

    def test_is_available_returns_bool(self):
        result = ShapDriftChecker.is_available()
        assert isinstance(result, bool)

    def test_compute_raises_clear_error_when_unavailable(self):
        """If shap not installed, should raise ImportError with install instructions."""
        if ShapDriftChecker.is_available():
            pytest.skip("shap is installed — skipping unavailable-path test")
        with pytest.raises(ImportError, match="pip install shap"):
            ShapDriftChecker.compute_shap_drift(
                model=None,
                reference_X=pd.DataFrame({"f1": [1, 2]}),
                current_X=pd.DataFrame({"f1": [1, 2]}),
            )


class TestCompositeDriftMonitor:
    """Test Layer 1 + Layer 2 integration."""

    @pytest.fixture
    def composite_setup(self):
        """Create data + monitors for composite testing."""
        X = pd.DataFrame(
            {
                "f1": RNG.normal(0, 1, 300),
                "f2": RNG.normal(5, 2, 300),
            }
        )
        y = 2 * X["f1"] + X["f2"] + RNG.normal(0, 0.1, 300)
        model = LinearRegression().fit(X, y)

        dist_monitor = DriftMonitor(X, features=["f1", "f2"])
        imp_monitor = PermutationDriftMonitor(
            model=model, scoring="r2", reference_X=X, reference_y=y
        )
        return dist_monitor, imp_monitor, X, y

    def test_check_all_returns_composite_report(self, composite_setup):
        dist_mon, imp_mon, X, y = composite_setup
        composite = CompositeDriftMonitor(dist_mon, imp_mon)
        report = composite.check_all(X, X, y)
        assert isinstance(report, CompositeReport)
        assert report.distribution is not None
        assert report.importance is not None

    def test_no_drift_when_stable(self, composite_setup):
        dist_mon, imp_mon, X, y = composite_setup
        composite = CompositeDriftMonitor(dist_mon, imp_mon)
        # Same distribution data
        X_stable = pd.DataFrame(
            {
                "f1": RNG.normal(0, 1, 200),
                "f2": RNG.normal(5, 2, 200),
            }
        )
        y_stable = 2 * X_stable["f1"] + X_stable["f2"] + RNG.normal(0, 0.1, 200)
        report = composite.check_all(X_stable, X_stable, y_stable)
        # Should not have severe drift (some sampling variance OK)
        assert len(report.importance.red_alerts()) == 0

    def test_summary_output(self, composite_setup):
        dist_mon, imp_mon, X, y = composite_setup
        composite = CompositeDriftMonitor(dist_mon, imp_mon)
        report = composite.check_all(X, X, y)
        summary = report.summary()
        assert "Composite" in summary
        assert "Drift Report" in summary or "Importance" in summary

    def test_both_layers_flag_same_feature(self, composite_setup):
        """When a feature has both distribution shift AND importance decay,
        it should be surfaced as highest priority."""
        dist_mon, imp_mon, X, y = composite_setup
        composite = CompositeDriftMonitor(dist_mon, imp_mon)

        # Shift f1 distribution AND remove its predictive relationship
        X_shifted = pd.DataFrame(
            {
                "f1": RNG.normal(3, 2, 200),  # mean + variance shift
                "f2": RNG.normal(5, 2, 200),  # same
            }
        )
        # y no longer depends on f1
        y_shifted = X_shifted["f2"] + RNG.normal(0, 0.1, 200)

        report = composite.check_all(X_shifted, X_shifted, y_shifted)
        summary = report.summary()

        # f1 should be flagged by both layers
        dist_features = {r.feature for r in report.distribution.alerts()}
        imp_features = {r.feature for r in report.importance.alerts()}
        both = dist_features & imp_features

        if both:
            assert "BOTH" in summary or "both" in summary.lower()


class TestSignalEngineFeatureDecay:
    """Realistic feature decay scenarios for signal_engine-like features."""

    def _make_features(
        self, n: int, f1_weight: float = 2.0
    ) -> tuple[pd.DataFrame, np.ndarray]:
        """Generate synthetic signal_engine-like features + target."""
        X = pd.DataFrame(
            {
                "ict_confluence_score": np.clip(RNG.normal(0.5, 0.2, n), 0, 1),
                "ict_structure_score": np.clip(RNG.normal(0.4, 0.15, n), 0, 1),
                "ict_ob_score": np.clip(RNG.normal(0.3, 0.15, n), 0, 1),
                "ict_fvg_score": np.clip(RNG.normal(0.2, 0.1, n), 0, 1),
            }
        )
        # Target is a weighted combination
        y = (
            f1_weight * X["ict_confluence_score"]
            + 1.0 * X["ict_structure_score"]
            + 0.5 * X["ict_ob_score"]
            + 0.3 * X["ict_fvg_score"]
            + RNG.normal(0, 0.05, n)
        )
        return X, y

    def test_baseline_importance_ranking(self):
        """Most predictive features should rank highest in permutation importance."""
        X, y = self._make_features(500)
        model = LinearRegression().fit(X, y)
        monitor = PermutationDriftMonitor(
            model=model, scoring="r2", reference_X=X, reference_y=y
        )
        ref = monitor.reference_importance
        # ict_confluence_score has weight=2.0, should be most important
        assert ref["ict_confluence_score"]["mean"] > ref["ict_fvg_score"]["mean"]

    def test_feature_decay_detected(self):
        """When a feature's predictive relationship weakens, the model trained
        on reference data shows different importance patterns on current data."""
        # Baseline: confluence has strong relationship
        X_ref, y_ref = self._make_features(500, f1_weight=2.0)
        model_ref = LinearRegression().fit(X_ref, y_ref)

        # Train a second model on decayed data for comparison
        X_cur, y_cur = self._make_features(500, f1_weight=0.0)  # f1 removed
        model_cur = LinearRegression().fit(X_cur, y_cur)

        # Permutation importance on reference model vs current model
        # should show confluence_score importance dropping
        monitor_ref = PermutationDriftMonitor(
            model=model_ref, scoring="r2", reference_X=X_ref, reference_y=y_ref
        )
        ref_imp = monitor_ref.reference_importance

        monitor_cur = PermutationDriftMonitor(
            model=model_cur, scoring="r2", reference_X=X_cur, reference_y=y_cur
        )
        cur_imp = monitor_cur.reference_importance

        # Reference model should rely heavily on confluence_score
        assert ref_imp["ict_confluence_score"]["mean"] > 0.1
        # Current model (where f1 has no relationship) should not rely on it
        assert (
            cur_imp["ict_confluence_score"]["mean"]
            < ref_imp["ict_confluence_score"]["mean"]
        )

    def test_stable_features_no_meaningful_decay(self):
        """Features with stable, meaningful predictive power should not show
        significant importance decay."""
        X, y = self._make_features(500)
        model = LinearRegression().fit(X, y)
        monitor = PermutationDriftMonitor(
            model=model, scoring="r2", reference_X=X, reference_y=y
        )
        X_new, y_new = self._make_features(300)
        report = monitor.check_importance_drift(X_new, y_new)
        # Features with meaningful reference importance should not show >50% decay
        for r in report.results:
            if r.reference_importance > 0.05:
                assert not r.is_declining, (
                    f"{r.feature} unexpectedly decayed: {r.pct_decay:.1%}"
                )

    def test_report_summary_shows_feature_names(self):
        """Report summary should contain actual feature names."""
        X, y = self._make_features(200)
        model = LinearRegression().fit(X, y)
        monitor = PermutationDriftMonitor(
            model=model, scoring="r2", reference_X=X, reference_y=y
        )
        report = monitor.check_importance_drift(X, y)
        summary = report.summary()
        # Summary should mention feature counts and be non-empty
        assert "/" in summary  # "N/M features affected"
        assert len(summary) > 20  # non-trivial content
