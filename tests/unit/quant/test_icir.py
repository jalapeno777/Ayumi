"""Tests for quant.icir and quant.icir_monitor — IC + ICIR computations.

Covers:

* ``information_coefficient`` — Spearman rank correlation between signal
  confidence and realized R-multiple, with edge cases (perfect, no
  correlation, anti-correlation, empty / constant / mismatched inputs).
* ``icir`` — mean/std ICIR time-series over evaluation periods, plus
  confidence tiers based on ``n_windows``.
* ``evaluate_icir`` — applied across WF windows with per-trade data, with
  aggregate-only data, and with empty input.
* ``IcirMonitor`` — live rolling 30/60/90-day ICIR with the
  ``decay_alert`` flag triggering on sub-threshold 30-day ICIR.
"""

from __future__ import annotations  # noqa: I001

import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from quant.icir import (
    CONF_HIGH_MIN_N,
    CONF_MEDIUM_MIN_N,
    DECAY_ALERT_THRESHOLD,
    evaluate_icir,
    icir,
    information_coefficient,
)
from quant.icir_monitor import IcirMonitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ic_perfect() -> tuple[list[float], list[float]]:
    """Confidence perfectly ranks with R-multiple (Spearman = 1.0)."""
    return [0.1, 0.3, 0.5, 0.7, 0.9], [-1.0, 0.0, 0.5, 1.0, 2.0]


def _ic_anti() -> tuple[list[float], list[float]]:
    """Confidence perfectly anti-ranks with R-multiple (Spearman = -1.0)."""
    return [0.9, 0.7, 0.5, 0.3, 0.1], [-1.0, 0.0, 0.5, 1.0, 2.0]


def _ic_random_seed(seed: int = 42) -> tuple[list[float], list[float]]:
    """Deterministic no-correlation pair for reproducibility."""
    rng = np.random.default_rng(seed)
    n = 50
    conf = rng.uniform(0.2, 0.9, n)
    r = rng.normal(0.0, 1.0, n)
    return conf.tolist(), r.tolist()


def _build_window_series(
    base_offset: int,
    *,
    n_windows: int,
    conf_strength: float = 1.0,
    r_noise: float = 0.5,
    seed: int = 0,
) -> list[float]:
    """Build a time-series of IC values with a known mean/std.

    Each point is a Spearman-ish synthetic value centered on ``base_offset``
    to give the series a positive or negative drift.
    """
    rng = np.random.default_rng(seed)
    raw = rng.normal(loc=base_offset, scale=r_noise, size=n_windows)
    # Symmetric / sign-preserving adjustment so direction matters.
    return (raw * conf_strength).tolist()


# ---------------------------------------------------------------------------
# information_coefficient
# ---------------------------------------------------------------------------


class TestInformationCoefficient:
    """Pure Spearman IC — covers perfect, anti, none, edge cases."""

    def test_perfect_positive_correlation(self):
        """Confidence ranks perfectly with R-multiple → IC = +1.0."""
        confs, rs = _ic_perfect()
        rho = information_coefficient(confs, rs)
        assert rho == pytest.approx(1.0, abs=1e-9)

    def test_perfect_anti_correlation(self):
        """Confidence perfectly anti-ranks with R-multiple → IC = -1.0."""
        confs, rs = _ic_anti()
        rho = information_coefficient(confs, rs)
        assert rho == pytest.approx(-1.0, abs=1e-9)

    def test_no_correlation_close_to_zero(self):
        """Random pairing of confidence and R → IC ≈ 0 (within 0.2)."""
        confs, rs = _ic_random_seed(seed=7)
        rho = information_coefficient(confs, rs)
        # Loose tolerance — Spearman on truly-independent samples over
        # n=50 should be near 0 ± 0.2. Tightening this risks flakiness.
        assert abs(rho) < 0.2

    def test_empty_inputs_return_nan(self):
        """Empty sequences → NaN, not an exception."""
        assert math.isnan(information_coefficient([], []))
        assert math.isnan(information_coefficient([0.5], []))
        assert math.isnan(information_coefficient([], [1.0]))

    def test_mismatched_lengths_return_nan(self):
        """Length mismatch → NaN (fail silently rather than crash)."""
        assert math.isnan(information_coefficient([0.1, 0.2], [0.5]))
        assert math.isnan(information_coefficient([0.1], [0.5, 0.6]))

    def test_too_few_observations_returns_nan(self):
        """Fewer than MIN_OBS_FOR_IC observations → NaN."""
        assert math.isnan(information_coefficient([0.5], [1.0]))
        confs2, rs2 = [0.5, 0.7], [0.0, 1.0]  # n=2, still under threshold
        assert math.isnan(information_coefficient(confs2, rs2))

    def test_constant_confidence_returns_nan(self):
        """Zero variance in confidence → Spearman undefined → NaN."""
        confs = [0.5] * 5
        rs = [-1.0, -0.5, 0.0, 0.5, 1.0]
        rho = information_coefficient(confs, rs)
        assert math.isnan(rho)

    def test_constant_r_multiple_returns_nan(self):
        """Zero variance in R-multiple → Spearman undefined → NaN."""
        confs = [0.1, 0.3, 0.5, 0.7, 0.9]
        rs = [0.0] * 5
        rho = information_coefficient(confs, rs)
        assert math.isnan(rho)


# ---------------------------------------------------------------------------
# icir (time-series)
# ---------------------------------------------------------------------------


class TestIcir:
    """``icir()`` — mean/std ICIR + confidence tier mapping."""

    def test_basic_icir_is_mean_over_std(self):
        """ICIR over a synthetic series matches mean/std by hand."""
        ic_values = [0.05, 0.07, 0.04, 0.06, 0.08]
        mean_ic = sum(ic_values) / len(ic_values)
        std_ic = float(np.std(ic_values, ddof=1))
        expected = mean_ic / std_ic

        result = icir(ic_values)
        assert result["icir"] == pytest.approx(expected, rel=1e-9)
        assert result["mean_ic"] == pytest.approx(mean_ic, rel=1e-9)
        assert result["std_ic"] == pytest.approx(std_ic, rel=1e-9)
        assert result["n_windows"] == len(ic_values)

    def test_constant_nonzero_ic_returns_inf_for_icir(self):
        """All-equal nonzero IC vector → mean != 0 → ICIR = +inf.

        Mathematically, mean/std at zero std is undefined; semantically
        this is "skill is consistent" which is the strongest-skill regime.
        We report +inf and let callers interpret (note in the result).
        """
        result = icir([0.05] * 6)
        # mean = 0.05 > 0 → +inf. JSON-serialised None (= infinity).
        assert result["icir"] is None
        assert result["mean_ic"] == pytest.approx(0.05, rel=1e-6, abs=1e-9)
        assert result["std_ic"] == pytest.approx(0.0)
        # Note explains the convention.
        assert "zero variance" in result["note"].lower()
        assert "consistent" in result["note"].lower()

    def test_constant_zero_ic_returns_nan(self):
        """All-zero IC vector → no signal at all → ICIR NaN."""
        result = icir([0.0] * 8)
        assert result["icir"] is None
        assert result["std_ic"] == pytest.approx(0.0)
        assert "no signal" in result["note"].lower()

    def test_empty_input_returns_low_tier_zero_n(self):
        """Empty input → confidence='low', n_windows=0, NaN ICIR."""
        result = icir([])
        assert result["confidence"] == "low"
        assert result["n_windows"] == 0
        assert result["icir"] is None  # JSON serialization of NaN → None

    def test_insufficient_periods_returns_none(self):
        """2 valid observations (< MIN_PERIODS_FOR_ICIR=3) → None."""
        result = icir([0.05, math.nan, 0.06])
        assert result["icir"] is None
        assert "only 2 valid" in result["note"].lower()
        # n_windows counts the valid observations, not the total.
        assert result["n_windows"] == 2
        assert result["confidence"] == "low"

    def test_confidence_tier_mapping(self):
        """n_windows → tier mapping follows CONF_*_MIN_N thresholds."""
        assert icir(_build_window_series(0.05, n_windows=5))["confidence"] == "low"
        assert icir(_build_window_series(0.05, n_windows=15))["confidence"] == "medium"
        assert icir(_build_window_series(0.05, n_windows=45))["confidence"] == "high"

    def test_confidence_threshold_boundary(self):
        """Boundaries: n=CONF_MEDIUM_MIN_N is medium; n=CONF_HIGH_MIN_N is high."""
        n_medium_min = CONF_MEDIUM_MIN_N
        n_high_min = CONF_HIGH_MIN_N
        assert icir(_build_window_series(0.05, n_windows=n_medium_min))["confidence"] == "medium"
        assert icir(_build_window_series(0.05, n_windows=n_high_min))["confidence"] == "high"

    def test_nan_entries_excluded_from_mean_std(self):
        """NaN entries in the input do not poison mean / std."""
        # First make a clean series, then inject NaN.
        clean = [0.04, 0.06, 0.05, 0.07, 0.05]
        clean_result = icir(clean)
        # Same series with NaN slots — should give the same numbers.
        nan_series = [0.04, math.nan, 0.06, 0.05, math.nan, 0.07, 0.05]
        nan_result = icir(nan_series)
        assert nan_result["mean_ic"] == pytest.approx(clean_result["mean_ic"], rel=1e-9)
        assert nan_result["std_ic"] == pytest.approx(clean_result["std_ic"], rel=1e-9)
        # n_windows counts valid only.
        assert nan_result["n_windows"] == 5


# ---------------------------------------------------------------------------
# evaluate_icir
# ---------------------------------------------------------------------------


class TestEvaluateIcir:
    """``evaluate_icir()`` — applied across WF results."""

    def test_per_trade_windows_yield_icir(self):
        """WF windows with per-trade confidences/Rs → real ICIR."""
        wf = []
        # Window 1: high correlation
        wf.append(
            {
                "window": 0,
                "confidences": [0.1, 0.3, 0.5, 0.7, 0.9],
                "r_multiples": [-0.8, -0.2, 0.3, 0.9, 1.7],
            }
        )
        # Window 2: high correlation (slightly different r)
        wf.append(
            {
                "window": 1,
                "confidences": [0.2, 0.4, 0.6, 0.8, 0.95],
                "r_multiples": [-0.5, 0.1, 0.4, 1.0, 1.5],
            }
        )
        # Window 3: high correlation
        wf.append(
            {
                "window": 2,
                "confidences": [0.15, 0.35, 0.55, 0.75, 0.9],
                "r_multiples": [-0.6, -0.1, 0.5, 0.8, 1.6],
            }
        )
        # Window 4: high correlation
        wf.append(
            {
                "window": 3,
                "confidences": [0.25, 0.45, 0.65, 0.85, 0.95],
                "r_multiples": [-0.7, 0.0, 0.3, 1.1, 1.4],
            }
        )

        result = evaluate_icir(wf)
        # We should get 4 high-IC observations.
        assert result["n_windows_with_ic"] == 4
        assert result["n_windows"] == 4
        assert all(math.isfinite(ic) and ic > 0.9 for ic in result["per_window_ic"])
        # Per-window ICs are highly consistent → std tiny → ICIR is
        # mathematically infinite (positive infinity in this case
        # because mean is positive). In JSON-serialised output this
        # becomes None — a sentinel meaning "infinite / consistent".
        # We verify consistency via mean_ic + std_ic instead of a numeric ICIR.
        assert result["mean_ic"] is not None
        assert result["mean_ic"] > 0.9
        assert result["confidence"] == "low"  # n=4 < CONF_MEDIUM_MIN_N
        # Recompute via ``icir()`` to see the underlying math state.
        underlying = icir(result["per_window_ic"])
        # std is exactly 0 → icir is +inf → JSON None + positive mean.
        assert underlying["std_ic"] == pytest.approx(0.0)
        assert underlying["mean_ic"] is not None
        assert underlying["mean_ic"] > 0.9

    def test_aggregate_only_data_returns_low_tier(self):
        """Aggregate-only WF data (current Ayumi report shape) → low tier."""
        wf = [
            {"window": 0, "mean_confidence": 0.5, "mean_r_multiple": 0.3},
            {"window": 1, "mean_confidence": 0.6, "mean_r_multiple": 0.7},
            {"window": 2, "mean_confidence": 0.4, "mean_r_multiple": -0.2},
            {"window": 3, "mean_confidence": 0.7, "mean_r_multiple": 1.0},
            {"window": 4, "mean_confidence": 0.5, "mean_r_multiple": 0.5},
        ]
        result = evaluate_icir(wf)
        assert result["n_windows_with_ic"] == 0
        assert result["icir"] is None
        assert result["confidence"] == "low"
        # Note explains the missing data + why ICIR is NaN.
        note = result["note"].lower()
        assert "no per-trade" in note or "per-trade" in note

    def test_empty_wf_results_returns_low_tier(self):
        """Empty input → low tier, NaN ICIR, helpful note."""
        result = evaluate_icir([])
        assert result["n_windows"] == 0
        assert result["n_windows_with_ic"] == 0
        assert result["icir"] is None
        assert result["confidence"] == "low"

    def test_mixed_per_trade_and_aggregate(self):
        """Some per-trade, some aggregate → per-trade windows contribute."""
        wf = [
            # Window 0: per-trade data (high IC)
            {
                "window": 0,
                "confidences": [0.2, 0.5, 0.8],
                "r_multiples": [-0.5, 0.0, 1.0],
            },
            # Window 1: aggregate-only → contributes nothing
            {"window": 1, "mean_confidence": 0.5, "mean_r_multiple": 0.2},
            # Window 2: per-trade, no correlation
            {
                "window": 2,
                "confidences": [0.1, 0.4, 0.7, 0.9],
                "r_multiples": [0.5, -0.5, 0.3, -0.3],
            },
            # Window 3: bad window with no usable data
            {"window": 3},
        ]
        result = evaluate_icir(wf)
        assert result["n_windows"] == 4
        assert result["n_windows_with_ic"] == 2
        # IC for window 0 is high, window 2 is low/negative.
        assert result["per_window_ic"][0] is not None
        assert result["per_window_ic"][0] > 0.8
        # Per-trade IC for window 2 — Spearman on this small set is
        # not extremely high (rank is not monotonic).
        ic2 = result["per_window_ic"][2]
        assert ic2 is not None
        # Window 1 (aggregate only) and window 3 (no data) → NaN → None
        # in the JSON-serialised dict form.
        assert result["per_window_ic"][1] is None
        assert result["per_window_ic"][3] is None


# ---------------------------------------------------------------------------
# IcirMonitor
# ---------------------------------------------------------------------------


class _FixedNow:
    """A `now_provider` that returns a fixed datetime (so tests are deterministic)."""

    def __init__(self, dt: datetime) -> None:
        self._dt = dt

    def __call__(self) -> datetime:
        return self._dt


class TestIcirMonitor:
    """Rolling ICIR monitor — 30/60/90-day windows + decay alert."""

    def test_empty_monitor_returns_none_for_icir(self):
        """No observations → all ICIR fields None, decay_alert=False."""
        monitor = IcirMonitor(now_provider=_FixedNow(datetime(2026, 7, 8, 12, 0)))
        status = monitor.get_status()
        assert status["icir_30d"] is None
        assert status["icir_60d"] is None
        assert status["icir_90d"] is None
        assert status["n_obs_total"] == 0
        assert status["decay_alert"] is False

    def test_skips_nan_or_infinite_observations(self):
        """NaN / infinite confidence or R-multiple are silently dropped."""
        monitor = IcirMonitor(now_provider=_FixedNow(datetime(2026, 7, 8, 12, 0)))
        monitor.update(0.5, 1.0, datetime(2026, 7, 7, 10, 0))  # valid
        monitor.update(float("nan"), 1.0, datetime(2026, 7, 7, 11, 0))  # NaN → skipped
        monitor.update(0.6, float("inf"), datetime(2026, 7, 7, 12, 0))  # inf → skipped
        monitor.update(0.7, 0.5, datetime(2026, 7, 7, 13, 0))  # valid
        # Only the two non-bad rows are stored.
        assert monitor.n_observations == 2

    def test_update_and_get_status_returns_shape(self):
        """Basic update flow returns the expected status shape."""
        monitor = IcirMonitor(now_provider=_FixedNow(datetime(2026, 7, 8, 12, 0)))
        # 5 trades, well-correlated: high confidence → high R, low conf → low R
        now = datetime(2026, 7, 8, 12, 0)
        for i, (c, r) in enumerate(
            [
                (0.30, -0.5),
                (0.45, -0.1),
                (0.55, 0.4),
                (0.70, 0.9),
                (0.85, 1.7),
            ]
        ):
            monitor.update(c, r, now - timedelta(days=i))

        status = monitor.get_status()
        assert status["n_obs_total"] == 5
        assert status["n_obs_30d"] == 5
        assert status["n_obs_60d"] == 5
        assert status["n_obs_90d"] == 5
        # n_obs only 5 < 90d window size — single bucket so ICIR undefined.
        assert status["icir_30d"] is None
        assert status["last_updated"] != ""

    def test_30_day_icir_with_dense_positive_correlation(self):
        """30 days of well-correlated daily trades → high positive 30-day ICIR.

        Per-day pattern uses confidence + R-multiple pairs whose rank
        ordering varies slightly day to day (rs are not monotonic across
        days in the same way), so the per-day ICs have nonzero std and
        the ICIR is a meaningful finite number rather than ``+inf``.
        """
        monitor = IcirMonitor(now_provider=_FixedNow(datetime(2026, 7, 8, 12, 0)))
        anchor = datetime(2026, 7, 8, 12, 0)
        # 30 days, 4 trades per day. Confidence values are deterministic
        # per trade (so trade ordering maps cleanly to day indexing) but
        # R-multiple values include a per-trade uniform jitter wide
        # enough to sometimes perturb ranks within a day. Net effect:
        # per-day ICs are mostly high (+0.7 to +1) but vary across days,
        # keeping std > 0 and ICIR finite.
        rng = np.random.default_rng(7)
        for day_offset in range(30):
            base = anchor - timedelta(days=day_offset)
            # Order confs ascending; jitter rs uniformly in [-0.4, 0.4]
            # so successive-rank changes occur ~25% of the time within a
            # day.
            confs = [0.30, 0.50, 0.70, 0.85]
            per_day_rs = [
                -0.5 + rng.uniform(-0.4, 0.4),
                0.2 + rng.uniform(-0.4, 0.4),
                0.9 + rng.uniform(-0.4, 0.4),
                1.6 + rng.uniform(-0.4, 0.4),
            ]
            for hour_offset, (c, r) in enumerate(zip(confs, per_day_rs)):  # noqa: B905
                ts = base.replace(hour=10 + hour_offset)
                monitor.update(c, r, ts)

        status = monitor.get_status()
        assert status["n_obs_30d"] == 30 * 4
        # Per-day ICs vary slightly → ICIR is a finite, large positive
        # number reflecting strong consistent skill.
        assert status["icir_30d"] is not None
        assert status["icir_30d"] > 1.0
        assert status["decay_alert"] is False

    def test_30_day_icir_with_no_correlation_does_not_alert(self):
        """30 days of uncorrelated trades + raised threshold → no alert.

        Uses ``decay_threshold=-1000`` so the alert can never fire
        regardless of the (random) ICIR value — this isolates the test
        to verifying the alert logic, not the IC distribution.

        Per-day ICs are ~0 ± noise; std of per-day ICs is positive;
        ICIR is a finite near-zero number.
        """
        monitor = IcirMonitor(
            decay_threshold=-1000.0,  # effectively disable the alert
            now_provider=_FixedNow(datetime(2026, 7, 8, 12, 0)),
        )
        rng = np.random.default_rng(11)
        anchor = datetime(2026, 7, 8, 12, 0)
        for day_offset in range(30):
            base = anchor - timedelta(days=day_offset)
            n_today = 5
            confs = rng.uniform(0.2, 0.9, n_today)
            rs = rng.normal(0.0, 1.0, n_today)
            for i, (c, r) in enumerate(zip(confs, rs)):  # noqa: B905
                monitor.update(float(c), float(r), base.replace(hour=10 + i))

        status = monitor.get_status()
        # Threshold is far below any realistic ICIR → no decay alert.
        assert status["decay_alert"] is False
        # ICIR is computed (random data is non-constant) and finite.
        assert status["icir_30d"] is not None
        assert math.isfinite(status["icir_30d"])

    def test_decay_alert_triggers_below_threshold(self):
        """decay_alert=True when icir_30d < DECAY_ALERT_THRESHOLD and sufficient data."""
        monitor = IcirMonitor(
            decay_threshold=0.5,  # custom threshold for predictability
            now_provider=_FixedNow(datetime(2026, 7, 8, 12, 0)),
        )
        anchor = datetime(2026, 7, 8, 12, 0)
        # Push 30 days of trades with a *negative* drift in confidence → R mapping.
        # Each day has only 3 trades (the MIN_OBS_FOR_IC boundary) with weak
        # positive correlation, so the daily IC vector will have high std →
        # ICIR will be < 0.5 once we have enough days.
        for day_offset in range(30):
            base = anchor - timedelta(days=day_offset)
            # Make half the days positively correlated, half anti-correlated.
            # Per-day ICs split equally → std is large → ICIR below threshold.
            if day_offset % 2 == 0:
                triples = [
                    (0.30, -0.5),
                    (0.55, 0.3),
                    (0.85, 1.5),
                ]
            else:
                triples = [
                    (0.30, 1.5),
                    (0.55, 0.3),
                    (0.85, -0.5),
                ]
            for hour_offset, (c, r) in enumerate(triples):
                ts = base.replace(hour=10 + hour_offset)
                monitor.update(c, r, ts)

        status = monitor.get_status()
        # We have 30 daily buckets, well above MIN_PERIODS_FOR_ICIR.
        assert status["icir_30d"] is not None
        # Per-day ICs are ~+1 / ~-1 alternating → std → ICIR ≈ 0.
        assert status["icir_30d"] < 0.5
        # decay_alert fires because ICIR < decay_threshold.
        assert status["decay_alert"] is True

    def test_decay_alert_does_not_fire_with_insufficient_data(self):
        """decay_alert stays False until 30d window has enough IC observations."""
        monitor = IcirMonitor(decay_threshold=0.5, now_provider=_FixedNow(datetime(2026, 7, 8, 12, 0)))
        anchor = datetime(2026, 7, 8, 12, 0)
        # Only 5 days of trades (not enough IC buckets for ICIR).
        for day_offset in range(5):
            base = anchor - timedelta(days=day_offset)
            for c, r in [(0.30, -0.5), (0.55, 0.3), (0.85, 1.5)]:
                monitor.update(c, r, base.replace(hour=10))

        status = monitor.get_status()
        # Insufficient data → ICIR is None; alert cannot fire.
        assert status["icir_30d"] is None
        assert status["decay_alert"] is False

    def test_decay_alert_threshold_constant_is_reasonable(self):
        """Smoke test on the module-level decay threshold constant."""
        # Just ensures future tweaks to the constant don't silently
        # push the threshold to a useless value.
        assert 0.0 < DECAY_ALERT_THRESHOLD < 2.0

    def test_60_and_90_day_windows(self):
        """Sanity: with 90+ days of data, all three windows compute."""
        monitor = IcirMonitor(now_provider=_FixedNow(datetime(2026, 7, 8, 12, 0)))
        anchor = datetime(2026, 7, 8, 12, 0)
        # 95 days of 5 trades/day with predictable positive correlation.
        # Confs spaced closely so per-trade R noise often flips a rank,
        # giving per-day ICs that vary across days.
        rng = np.random.default_rng(123)
        for day_offset in range(95):
            base = anchor - timedelta(days=day_offset)
            confs = [0.30, 0.42, 0.54, 0.66, 0.85]
            per_day_rs = [
                -0.30 + rng.normal(0, 0.15),
                -0.05 + rng.normal(0, 0.15),
                0.20 + rng.normal(0, 0.15),
                0.45 + rng.normal(0, 0.15),
                1.10 + rng.normal(0, 0.15),
            ]
            for hour_offset, (c, r) in enumerate(zip(confs, per_day_rs)):  # noqa: B905
                monitor.update(c, r, base.replace(hour=10 + hour_offset))

        status = monitor.get_status()
        assert status["icir_30d"] is not None
        assert status["icir_60d"] is not None
        assert status["icir_90d"] is not None
        # All windows are well above the decay threshold (loose bound).
        for v in (
            status["icir_30d"],
            status["icir_60d"],
            status["icir_90d"],
        ):
            assert v is not None
            assert v > 1.0

    def test_clear_resets_the_monitor(self):
        """clear() drops all observations."""
        monitor = IcirMonitor(now_provider=_FixedNow(datetime(2026, 7, 8, 12, 0)))
        monitor.update(0.5, 1.0, datetime(2026, 7, 7, 12, 0))
        monitor.update(0.6, 0.5, datetime(2026, 7, 6, 12, 0))
        assert monitor.n_observations == 2
        monitor.clear()
        assert monitor.n_observations == 0
        status = monitor.get_status()
        assert status["n_obs_total"] == 0
        assert status["icir_30d"] is None
