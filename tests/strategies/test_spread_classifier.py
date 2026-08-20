"""Tests for spread_classifier: regime classification, penalties, rolling window.

NOTE (BQ-1037): The signal_engine.spread_classifier module does NOT exist
in the current codebase. This test was written against a planned feature
that was not implemented. Per the sprint plan, the test is preserved as
a skip so the import-error cascade is fixed, but the assertions are
guarded so they don't run. When the spread_classifier feature is built
(BQ-133: Spread Regime Classifier Feature), the test should be
re-enabled.

Related BQ: BQ-133 (Spread Regime Classifier Feature)
"""

from __future__ import annotations

import pytest

# TODO: spread_classifier not yet implemented — re-enable when BQ-133 ships
pytestmark = pytest.mark.skip(
    reason="signal_engine.spread_classifier module does not exist (BQ-133 not implemented yet)"
)


# Since the entire module is skipped, we guard the import with try/except.
# This avoids sys.modules pollution (BQ-1037 Phase 1b) while keeping
# collection clean. When BQ-133 ships, remove the skip and the try/except.

try:
    from signal_engine.spread_classifier import (  # noqa: E402, F401, I001
        SpreadRegime,
        SpreadRegimeClassifier,
        _DEFAULT_PENALTIES,
        TIMEFRAME_WINDOW,
        DEFAULT_WINDOW,
    )
except ImportError:
    SpreadRegime = None  # type: ignore[assignment]
    SpreadRegimeClassifier = None  # type: ignore[assignment]
    _DEFAULT_PENALTIES = {}  # type: ignore[assignment]
    TIMEFRAME_WINDOW = {}  # type: ignore[assignment]
    DEFAULT_WINDOW = 0  # type: ignore[assignment]


# Original test code preserved below, gated by the skip above.

from types import SimpleNamespace  # noqa: E402, I001


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
            self.clf.update(SimpleNamespace(spread=v * 0.0001))

    def test_classify_tight(self):
        regime = self.clf.classify(0.0001)
        assert regime == SpreadRegime.TIGHT

    def test_classify_wide(self):
        regime = self.clf.classify(0.0050)
        assert regime in (SpreadRegime.WIDE, SpreadRegime.EXTREME)

    def test_classify_within_distribution(self):
        regime = self.clf.classify(0.0010)
        assert regime in (
            SpreadRegime.TIGHT,
            SpreadRegime.NORMAL,
            SpreadRegime.WIDE,
            SpreadRegime.EXTREME,
        )


# ── Window Behavior ─────────────────────────────────────────────────


class TestWindowBehavior:
    def test_window_size(self):
        clf = SpreadRegimeClassifier(window=50)
        assert clf.window == 50

    def test_update_keeps_window_size(self):
        clf = SpreadRegimeClassifier(window=5)
        for v in range(1, 11):
            clf.update(SimpleNamespace(spread=v * 0.0001))
        # Should only keep last 5
        assert len(clf.spreads) == 5


# ── Timeframe Integration ───────────────────────────────────────────


class TestTimeframeIntegration:
    def test_default_window(self):
        assert DEFAULT_WINDOW > 0

    def test_timeframe_window_has_keys(self):
        # Should have entries for common timeframes
        assert isinstance(TIMEFRAME_WINDOW, dict)
        assert len(TIMEFRAME_WINDOW) > 0
