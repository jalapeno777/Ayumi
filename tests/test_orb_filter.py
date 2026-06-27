"""Tests for ORB Filter Prioritization (BQ-1042).

Covers:
    - Opening range calculation (normal, edge cases)
    - Signal scoring (aligned, counter-trend, inside range)
    - Session window selection and active-session detection
    - Batch prioritization ordering
    - Volume confirmation behaviour
"""

from __future__ import annotations

from datetime import datetime, time, timezone

import pytest

from signal_engine.orb_filter import (
    BREAKOUT_MIN_FRACTION,
    DEFAULT_ORB_WINDOW_MINUTES,
    ORBFilter,
    ORBScore,
    OpeningRange,
)
from signal_engine.data_types import Signal


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def orbf():
    return ORBFilter()


@pytest.fixture
def london_bars():
    """60 one-minute bars forming a London opening range.

    Range: low=1.0850, high=1.0870 (width = 20 pips).
    Volume averages 1000, last bar has volume 1800 (1.8× average).
    """
    bars = []
    for i in range(60):
        bars.append({
            "open": 1.0855,
            "high": 1.0862,   # below the OR high of 1.0870
            "low": 1.0852,    # above the OR low of 1.0850
            "close": 1.0858,
            "volume": 900 + (i * 5) % 300,   # 900–1195 range
            "timestamp": datetime(2026, 1, 5, 7, i, tzinfo=timezone.utc),
        })
    # Force the extreme high and low for predictable calculations
    bars[10]["high"] = 1.0870
    bars[20]["low"] = 1.0850
    bars[-1]["volume"] = 1800  # strong breakout-adjacent volume
    return bars


@pytest.fixture
def london_range(orbf, london_bars):
    return orbf.calculate_opening_range("LONDON", london_bars)


def _make_signal(direction="long", entry=1.0, **kw) -> Signal:
    """Quick signal factory."""
    defaults = dict(
        symbol="EURUSD",
        direction=direction,
        entry_price=entry,
        stop_loss=entry - 0.005 if direction == "long" else entry + 0.005,
        take_profit=entry + 0.010 if direction == "long" else entry - 0.010,
        confidence=0.7,
    )
    defaults.update(kw)
    return Signal(**defaults)


# ── Opening Range Calculation ───────────────────────────────────────────────

class TestOpeningRangeCalculation:
    def test_valid_range(self, orbf, london_bars):
        rng = orbf.calculate_opening_range("LONDON", london_bars)
        assert rng is not None
        assert rng.is_valid
        assert rng.session == "LONDON"
        assert rng.high == pytest.approx(1.0870)
        assert rng.low == pytest.approx(1.0850)
        assert rng.width == pytest.approx(0.0020)
        assert rng.mid == pytest.approx(1.0860)

    def test_avg_volume(self, orbf, london_bars):
        rng = orbf.calculate_opening_range("LONDON", london_bars)
        assert rng.avg_volume > 0
        # Should be around 1000-ish
        assert 800 < rng.avg_volume < 1300

    def test_too_few_bars(self, orbf):
        assert orbf.calculate_opening_range("LONDON", []) is None
        assert orbf.calculate_opening_range("LONDON", [{"high": 1.0, "low": 0.9}]) is None

    def test_unknown_session_uses_default_window(self, orbf, london_bars):
        """Unknown session should not crash — falls back to 60-bar window."""
        rng = orbf.calculate_opening_range("CUSTOM", london_bars)
        assert rng is not None
        assert rng.is_valid

    def test_respects_window_limit(self, orbf):
        """If orb_windows says 30, only first 30 bars should be used."""
        orbf_custom = ORBFilter(orb_windows={"LONDON": 30})
        bars = []
        for i in range(60):
            bars.append({
                "open": 1.0, "high": 1.001 * (1 + i * 0.0001),
                "low": 0.999, "close": 1.0, "volume": 100,
                "timestamp": datetime(2026, 1, 5, 7, i, tzinfo=timezone.utc),
            })
        rng = orbf_custom.calculate_opening_range("LONDON", bars)
        # Only first 30 bars — high should be from bar 29
        assert rng is not None
        assert rng.high <= 1.001 * (1 + 29 * 0.0001) + 1e-9


# ── Signal Scoring ──────────────────────────────────────────────────────────

class TestSignalScoring:
    def test_aligned_breakout_long(self, orbf, london_range):
        """Long signal clearly above range high → strong score."""
        sig = _make_signal("long", entry=1.0880)  # 10 pips above high
        result = orbf.score_signal(sig, london_range, current_volume=1800)
        assert result.direction_aligned is True
        assert result.breakout_type == "breakout"
        assert result.score > 0.6
        assert result.volume_score == 1.0  # 1800/avg > 1.5

    def test_aligned_breakout_short(self, orbf, london_range):
        """Short signal clearly below range low → strong score."""
        sig = _make_signal("short", entry=1.0830)  # 20 pips below low
        result = orbf.score_signal(sig, london_range, current_volume=1800)
        assert result.direction_aligned is True
        assert result.breakout_type == "breakout"
        assert result.score > 0.6

    def test_counter_trend_signal(self, orbf, london_range):
        """Short signal when price is above range high → not aligned."""
        sig = _make_signal("short", entry=1.0880)
        result = orbf.score_signal(sig, london_range)
        assert result.direction_aligned is False
        assert result.breakout_type == "failure"
        assert result.score < 0.5  # direction tanks the composite

    def test_inside_range_signal(self, orbf, london_range):
        """Signal entry inside the opening range → 'inside', no direction alignment."""
        sig = _make_signal("long", entry=1.0860)  # right at mid
        result = orbf.score_signal(sig, london_range)
        assert result.direction_aligned is False
        assert result.breakout_type == "inside"
        assert result.distance_score == 0.0
        assert result.score < 0.35

    def test_pseudo_breakout(self, orbf, london_range):
        """Entry barely beyond the range edge but below min fraction → 'pseudo'."""
        # Range width = 0.0020, min fraction = 0.10 → need 0.0002 beyond
        sig = _make_signal("long", entry=1.0871)  # 1 pip above high
        result = orbf.score_signal(sig, london_range)
        assert result.direction_aligned is True
        assert result.breakout_type == "pseudo"
        assert 0.0 < result.distance_score < 0.5

    def test_invalid_range(self, orbf):
        """Zero-width range → all scores are zero."""
        bad_range = OpeningRange(
            session="LONDON",
            high=1.0860,
            low=1.0860,
            open_time=datetime(2026, 1, 5, 7, 0, tzinfo=timezone.utc),
            close_time=datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc),
        )
        sig = _make_signal("long", entry=1.0880)
        result = orbf.score_signal(sig, bad_range)
        assert result.score == 0.0
        assert result.breakout_type == "invalid_range"

    def test_no_volume_data(self, orbf, london_range):
        """When current_volume=0, volume_score should be neutral (0.5)."""
        sig = _make_signal("long", entry=1.0880)
        result = orbf.score_signal(sig, london_range, current_volume=0)
        assert result.volume_score == 0.5


# ── Volume Confirmation ─────────────────────────────────────────────────────

class TestVolumeConfirmation:
    def test_strong_volume_boosts(self, orbf, london_range):
        sig = _make_signal("long", entry=1.0880)
        strong = orbf.score_signal(sig, london_range, current_volume=99999)
        weak = orbf.score_signal(sig, london_range, current_volume=100)
        assert strong.volume_score == 1.0
        assert weak.volume_score == 0.0
        assert strong.score > weak.score

    def test_threshold_boundaries(self, orbf, london_range):
        """Volume at exactly 1.5× avg → score 1.0; at exactly 1.0× → 0.6."""
        avg = london_range.avg_volume
        sig = _make_signal("long", entry=1.0880)

        strong = orbf.score_signal(sig, london_range, current_volume=avg * 1.5)
        assert strong.volume_score == 1.0

        normal = orbf.score_signal(sig, london_range, current_volume=avg * 1.0)
        assert normal.volume_score == 0.6


# ── Session Windows ─────────────────────────────────────────────────────────

class TestSessionWindows:
    def test_get_session_window_known(self, orbf):
        start, end = orbf.get_session_window("LONDON")
        assert start == time(7, 0)
        assert end == time(16, 0)

    def test_get_session_window_unknown(self, orbf):
        with pytest.raises(ValueError, match="Unknown session"):
            orbf.get_session_window("MARS")

    def test_active_sessions_london_open(self, orbf):
        """14:00 UTC → London + NY both active."""
        dt = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)
        active = orbf.get_active_sessions(dt)
        assert "LONDON" in active
        assert "NY" in active

    def test_active_sessions_asia_only(self, orbf):
        """03:00 UTC → only Asia."""
        dt = datetime(2026, 1, 5, 3, 0, tzinfo=timezone.utc)
        active = orbf.get_active_sessions(dt)
        assert active == ["ASIA"]

    def test_active_sessions_outside(self, orbf):
        """22:00 UTC → no sessions."""
        dt = datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc)
        active = orbf.get_active_sessions(dt)
        assert active == []


# ── Batch Prioritization ────────────────────────────────────────────────────

class TestPrioritization:
    def test_sorted_descending(self, orbf, london_range):
        signals = [
            _make_signal("short", entry=1.0830),   # strong short breakout
            _make_signal("long", entry=1.0860),     # inside range
            _make_signal("long", entry=1.0880),     # strong long breakout
            _make_signal("short", entry=1.0855),    # inside range (short)
        ]
        scored = orbf.prioritize(signals, london_range, current_volume=1800)
        assert len(scored) == 4
        # Descending order
        for i in range(len(scored) - 1):
            assert scored[i].score >= scored[i + 1].score

    def test_min_score_filter(self, orbf, london_range):
        signals = [
            _make_signal("long", entry=1.0860),     # inside — low score
            _make_signal("long", entry=1.0880),     # breakout — high score
        ]
        scored = orbf.prioritize(signals, london_range, min_score=0.5)
        assert len(scored) == 1
        assert scored[0].breakout_type == "breakout"

    def test_empty_signal_list(self, orbf, london_range):
        scored = orbf.prioritize([], london_range)
        assert scored == []

    def test_returns_orbscore_objects(self, orbf, london_range):
        signals = [_make_signal("long", entry=1.0880)]
        scored = orbf.prioritize(signals, london_range)
        assert len(scored) == 1
        assert isinstance(scored[0], ORBScore)


# ── Edge Cases ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_overlapping_sessions(self, orbf):
        """12:00 UTC → London/NY overlap — both should be active."""
        dt = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
        active = orbf.get_active_sessions(dt)
        assert "LONDON" in active
        assert "NY" in active

    def test_no_range_established(self, orbf):
        """When no opening range is available, score_signal gets an invalid range."""
        rng = OpeningRange(
            session="ASIA",
            high=0,
            low=0,
            open_time=datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc),
            close_time=datetime(2026, 1, 5, 1, 0, tzinfo=timezone.utc),
        )
        sig = _make_signal("long", entry=1.0850)
        result = orbf.score_signal(sig, rng)
        assert result.score == 0.0

    def test_custom_breakout_fraction(self, london_bars):
        """A higher breakout_min_fraction makes it harder to get 'breakout'."""
        orbf_strict = ORBFilter(breakout_min_fraction=0.5)
        rng = orbf_strict.calculate_opening_range("LONDON", london_bars)
        # Width = 0.0020, 50% fraction = need 0.0010 beyond
        sig = _make_signal("long", entry=1.0875)  # 5 pips above high
        result = orbf_strict.score_signal(sig, rng, current_volume=1800)
        assert result.breakout_type == "pseudo"  # 5 pips < 10 pips required

    def test_custom_orb_windows(self, london_bars):
        orbf_short = ORBFilter(orb_windows={"LONDON": 5})
        rng = orbf_short.calculate_opening_range("LONDON", london_bars)
        # Only first 5 bars — should still produce a valid range
        assert rng is not None
        assert rng.is_valid
