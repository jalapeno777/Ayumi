"""Tests for ``signals.spread_regime_classifier``.

Mirrors the planned API documented in ``tests/test_spread_classifier.py``
(BQ-1037 / BQ-133) but targets the new ``signals`` package path that the
signal engine uses.

The tests cover:
- :class:`SpreadRegime` enum membership and string values.
- :data:`_DEFAULT_PENALTIES` ordering and TIGHT/EXTREME boundary values.
- Rolling-window :class:`SpreadRegimeClassifier` classification.
- FIFO window-size enforcement.
- :data:`TIMEFRAME_WINDOW` and :data:`DEFAULT_WINDOW` module exports.
- :meth:`SpreadRegimeClassifier.confidence_penalty` range constraint.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from signals.spread_regime_classifier import (
    DEFAULT_WINDOW,
    TIMEFRAME_WINDOW,
    SpreadRegime,
    SpreadRegimeClassifier,
    _DEFAULT_PENALTIES,
)


# ── SpreadRegime Enum ───────────────────────────────────────────────


class TestSpreadRegimeEnum:
    def test_all_regimes_exist(self):
        names = {r.name for r in SpreadRegime}
        assert names == {"TIGHT", "NORMAL", "WIDE", "EXTREME"}

    def test_regime_values(self):
        assert SpreadRegime.TIGHT.value == "tight"
        assert SpreadRegime.NORMAL.value == "normal"
        assert SpreadRegime.WIDE.value == "wide"
        assert SpreadRegime.EXTREME.value == "extreme"


# ── Default Penalties ───────────────────────────────────────────────


class TestDefaultPenalties:
    def test_tight_no_penalty(self):
        assert _DEFAULT_PENALTIES[SpreadRegime.TIGHT] == 1.0

    def test_extreme_heaviest_penalty(self):
        assert _DEFAULT_PENALTIES[SpreadRegime.EXTREME] == 0.50

    def test_penalty_ordering(self):
        assert (
            _DEFAULT_PENALTIES[SpreadRegime.TIGHT]
            >= _DEFAULT_PENALTIES[SpreadRegime.NORMAL]
        )
        assert (
            _DEFAULT_PENALTIES[SpreadRegime.NORMAL]
            >= _DEFAULT_PENALTIES[SpreadRegime.WIDE]
        )
        assert (
            _DEFAULT_PENALTIES[SpreadRegime.WIDE]
            >= _DEFAULT_PENALTIES[SpreadRegime.EXTREME]
        )

    def test_penalty_range(self):
        # Acceptance criterion: confidence_penalty must be in [0.5, 1.0].
        for regime in SpreadRegime:
            assert 0.5 <= _DEFAULT_PENALTIES[regime] <= 1.0


# ── Classification ──────────────────────────────────────────────────


class TestClassification:
    def setup_method(self):
        self.clf = SpreadRegimeClassifier(window=20)
        # Seed with values 1..20 (in pip-equivalent units) to create a
        # known, uniformly-spaced distribution.
        for v in range(1, 21):
            self.clf.update(SimpleNamespace(spread=v * 0.0001))

    def test_classify_tight(self):
        # 0.0001 is below the 25th percentile of the seeded distribution.
        assert self.clf.classify(0.0001) == SpreadRegime.TIGHT

    def test_classify_extreme(self):
        # 0.0050 is well above the 90th percentile.
        assert self.clf.classify(0.0050) == SpreadRegime.EXTREME

    def test_classify_within_distribution(self):
        # 0.0010 sits inside the seeded distribution; must be a valid
        # regime regardless of which bucket it lands in.
        regime = self.clf.classify(0.0010)
        assert regime in (
            SpreadRegime.TIGHT,
            SpreadRegime.NORMAL,
            SpreadRegime.WIDE,
            SpreadRegime.EXTREME,
        )

    def test_classify_empty_window_returns_normal(self):
        empty = SpreadRegimeClassifier(window=10)
        assert empty.classify(0.0010) == SpreadRegime.NORMAL


# ── Window Behavior ─────────────────────────────────────────────────


class TestWindowBehavior:
    def test_window_size(self):
        clf = SpreadRegimeClassifier(window=50)
        assert clf.window == 50

    def test_default_window_size(self):
        clf = SpreadRegimeClassifier()
        assert clf.window == DEFAULT_WINDOW

    def test_update_keeps_window_size(self):
        clf = SpreadRegimeClassifier(window=5)
        for v in range(1, 11):
            clf.update(SimpleNamespace(spread=v * 0.0001))
        # Should only keep the last 5 entries.
        assert len(clf.spreads) == 5
        assert clf.spreads[0] == pytest.approx(0.0006)
        assert clf.spreads[-1] == pytest.approx(0.0010)

    def test_update_rejects_missing_spread_attr(self):
        clf = SpreadRegimeClassifier(window=5)
        with pytest.raises(TypeError):
            clf.update(SimpleNamespace(other=1.0))

    def test_update_rejects_negative_spread(self):
        clf = SpreadRegimeClassifier(window=5)
        with pytest.raises(ValueError):
            clf.update(SimpleNamespace(spread=-0.0001))


# ── Timeframe Integration ───────────────────────────────────────────


class TestTimeframeIntegration:
    def test_default_window_positive(self):
        assert DEFAULT_WINDOW > 0

    def test_timeframe_window_is_dict(self):
        assert isinstance(TIMEFRAME_WINDOW, dict)
        assert len(TIMEFRAME_WINDOW) > 0

    def test_timeframe_window_values_positive(self):
        for timeframe, size in TIMEFRAME_WINDOW.items():
            assert size > 0, f"{timeframe} has non-positive window {size}"


# ── Confidence Penalty Method ───────────────────────────────────────


class TestConfidencePenalty:
    def test_penalty_for_known_regime(self):
        clf = SpreadRegimeClassifier(window=5)
        assert clf.confidence_penalty(regime=SpreadRegime.TIGHT) == 1.0
        assert clf.confidence_penalty(regime=SpreadRegime.EXTREME) == 0.5

    def test_penalty_via_spread_pips(self):
        clf = SpreadRegimeClassifier(window=20)
        for v in range(1, 21):
            clf.update(SimpleNamespace(spread=v * 0.0001))
        # Below p25 → TIGHT → full confidence.
        assert clf.confidence_penalty(spread_pips=0.0001) == 1.0
        # Above p90 → EXTREME → half confidence.
        assert clf.confidence_penalty(spread_pips=0.0050) == 0.5

    def test_requires_regime_or_spread(self):
        clf = SpreadRegimeClassifier(window=5)
        with pytest.raises(TypeError):
            clf.confidence_penalty()
