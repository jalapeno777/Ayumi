"""Tests for spread_classifier: regime classification, penalties, rolling window."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from signal_engine.spread_classifier import (
    SpreadRegime,
    SpreadRegimeClassifier,
    _DEFAULT_PENALTIES,
    TIMEFRAME_WINDOW,
    DEFAULT_WINDOW,
)


# ── SpreadRegime Enum ───────────────────────────────────────────────

class TestSpreadRegimeEnum:
    def test_all_regimes_exist(self):
        names = {r.name for r in SpreadRegime}
        assert names == {"TIGHT", "NORMAL", "WIDE", "EXTREME"}

    def test_regime_values(self):
        assert SpreadRegime.TIGHT.value == "tight"
        assert SpreadRegime.EXTREME.value == "extreme"


# ── Default Penalties ───────────────────────────────────────────────

class TestDefaultPenalties:
    def test_tight_no_penalty(self):
        assert _DEFAULT_PENALTIES[SpreadRegime.TIGHT] == 1.0

    def test_extreme_heaviest_penalty(self):
        assert _DEFAULT_PENALTIES[SpreadRegime.EXTREME] == 0.50

    def test_penalty_ordering(self):
        assert _DEFAULT_PENALTIES[SpreadRegime.TIGHT] >= _DEFAULT_PENALTIES[SpreadRegime.NORMAL]
        assert _DEFAULT_PENALTIES[SpreadRegime.NORMAL] >= _DEFAULT_PENALTIES[SpreadRegime.WIDE]
        assert _DEFAULT_PENALTIES[SpreadRegime.WIDE] >= _DEFAULT_PENALTIES[SpreadRegime.EXTREME]


# ── Classification ──────────────────────────────────────────────────

class TestClassification:
    def setup_method(self):
        self.clf = SpreadRegimeClassifier(window=20)
        # Seed with values 1..20 to create known distribution
        for v in range(1, 21):
            self.clf.update(float(v))

    def test_tight_regime(self):
        assert self.clf.classify(1.0) == SpreadRegime.TIGHT

    def test_normal_regime(self):
        assert self.clf.classify(8.0) == SpreadRegime.NORMAL

    def test_wide_regime(self):
        assert self.clf.classify(17.0) == SpreadRegime.WIDE

    def test_extreme_regime(self):
        assert self.clf.classify(20.0) == SpreadRegime.EXTREME

    def test_classify_and_penalize(self):
        regime, penalty = self.clf.classify_and_penalize(1.0)
        assert regime == SpreadRegime.TIGHT
        assert penalty == 1.0


# ── Rolling Window ──────────────────────────────────────────────────

class TestRollingWindow:
    def test_window_truncation(self):
        clf = SpreadRegimeClassifier(window=5)
        for v in range(1, 11):
            clf.update(float(v))
        assert clf.stats["count"] == 5

    def test_empty_window_stats(self):
        clf = SpreadRegimeClassifier(window=10)
        stats = clf.stats
        assert stats["count"] == 0

    def test_single_value(self):
        clf = SpreadRegimeClassifier(window=10)
        clf.update(5.0)
        assert clf.stats["count"] == 1

    def test_zero_spread_uses_fallback(self):
        clf = SpreadRegimeClassifier(window=10, fallback_spread=2.0)
        clf.update(0.0)
        assert clf._window[-1] == 2.0

    def test_all_same_values(self):
        clf = SpreadRegimeClassifier(window=10)
        for _ in range(10):
            clf.update(5.0)
        # All values are the same → any spread=5.0 should be TIGHT (<=p25)
        assert clf.classify(5.0) == SpreadRegime.TIGHT


# ── Timeframe Window Sizing ────────────────────────────────────────

class TestTimeframeWindow:
    def test_m15_window(self):
        assert TIMEFRAME_WINDOW[15] == 96

    def test_h1_window(self):
        assert TIMEFRAME_WINDOW[60] == 24

    def test_h4_window(self):
        assert TIMEFRAME_WINDOW[240] == 6

    def test_set_timeframe(self):
        clf = SpreadRegimeClassifier()
        clf.set_timeframe(15)
        assert clf._max_window == 96


# ── Reject Extreme ──────────────────────────────────────────────────

class TestRejectExtreme:
    def test_extreme_returns_zero(self):
        clf = SpreadRegimeClassifier(reject_extreme=True)
        assert clf.get_spread_penalty(SpreadRegime.EXTREME) == 0.0

    def test_non_extreme_unchanged(self):
        clf = SpreadRegimeClassifier(reject_extreme=True)
        assert clf.get_spread_penalty(SpreadRegime.TIGHT) == 1.0


# ── Update from Bars ────────────────────────────────────────────────

class TestUpdateFromBars:
    def test_update_from_bars(self):
        clf = SpreadRegimeClassifier(window=10)
        bars = [SimpleNamespace(spread_pips=float(i)) for i in range(1, 6)]
        clf.update_from_bars(bars)
        assert clf.stats["count"] == 5

    def test_update_from_bars_zero_spread(self):
        clf = SpreadRegimeClassifier(window=10, fallback_spread=3.0)
        bars = [SimpleNamespace(spread_pips=0.0)]
        clf.update_from_bars(bars)
        assert clf._window[-1] == 3.0
