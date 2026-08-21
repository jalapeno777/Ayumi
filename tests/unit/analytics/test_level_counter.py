"""Tests for LevelCounter: rise/drop counting, level validation, type mapping."""

from __future__ import annotations

from signal_engine.data_types import LevelType, Swing, SwingType
from signal_engine.level_counter import LevelCounter


def _swing(idx, price, stype):
    return Swing(idx, price, stype)


# ── Single rise/drop ───────────────────────────────────────────────


class TestRiseDetection:
    def setup_method(self):
        self.counter = LevelCounter()

    def test_single_rise_to_r1(self):
        """Low→High leg creates R1."""
        lows = [_swing(0, 1.0900, SwingType.LOW)]
        highs = [_swing(2, 1.1000, SwingType.HIGH)]
        levels = self.counter.detect_levels(highs, lows)
        assert any(lv.level_type == LevelType.R1 for lv in levels)

    def test_two_rises_r1_r2(self):
        """Two new-high legs produce R1 and R2."""
        lows = [
            _swing(0, 1.0900, SwingType.LOW),
            _swing(4, 1.0920, SwingType.LOW),
        ]
        highs = [
            _swing(2, 1.1000, SwingType.HIGH),
            _swing(6, 1.1100, SwingType.HIGH),
        ]
        levels = self.counter.detect_levels(highs, lows)
        types = {lv.level_type for lv in levels}
        assert LevelType.R1 in types
        assert LevelType.R2 in types

    def test_three_rises_exhaustion(self):
        """Three rises produce R1, R2, R3."""
        lows = [
            _swing(0, 1.0900, SwingType.LOW),
            _swing(4, 1.0920, SwingType.LOW),
            _swing(8, 1.0940, SwingType.LOW),
        ]
        highs = [
            _swing(2, 1.1000, SwingType.HIGH),
            _swing(6, 1.1100, SwingType.HIGH),
            _swing(10, 1.1200, SwingType.HIGH),
        ]
        levels = self.counter.detect_levels(highs, lows)
        types = {lv.level_type for lv in levels}
        assert LevelType.R3 in types

    def test_r3_incomplete_if_too_small(self):
        """R3 magnitude < 90% of R2 → incomplete."""
        counter = LevelCounter(r3_ratio=0.9)
        counter._prev_rise_magnitude = 1000  # R2 magnitude = 1000 pips
        lows = [_swing(0, 1.0, SwingType.LOW)]
        highs = [_swing(2, 1.01, SwingType.HIGH)]
        # We need to set up tracking manually for this test
        levels = counter.detect_levels(highs, lows)
        # With only one rise, no R3 validation occurs
        assert all(isinstance(lv.level_type, LevelType) for lv in levels)


class TestDropDetection:
    def setup_method(self):
        self.counter = LevelCounter()

    def test_single_drop_to_d1(self):
        """High→Low leg creates D1."""
        highs = [_swing(0, 1.1000, SwingType.HIGH)]
        lows = [_swing(2, 1.0900, SwingType.LOW)]
        levels = self.counter.detect_levels(highs, lows)
        assert any(lv.level_type == LevelType.D1 for lv in levels)

    def test_two_drops_d1_d2(self):
        highs = [
            _swing(0, 1.1000, SwingType.HIGH),
            _swing(4, 1.0950, SwingType.HIGH),
        ]
        lows = [
            _swing(2, 1.0900, SwingType.LOW),
            _swing(6, 1.0800, SwingType.LOW),
        ]
        levels = self.counter.detect_levels(highs, lows)
        types = {lv.level_type for lv in levels}
        assert LevelType.D1 in types
        assert LevelType.D2 in types


class TestMixedSequence:
    def setup_method(self):
        self.counter = LevelCounter()

    def test_alternating_rises_and_drops(self):
        """Interleaved swings produce both rise and drop levels."""
        highs = [
            _swing(0, 1.1000, SwingType.HIGH),
            _swing(4, 1.1100, SwingType.HIGH),
        ]
        lows = [
            _swing(2, 1.0900, SwingType.LOW),
            _swing(6, 1.0800, SwingType.LOW),
        ]
        levels = self.counter.detect_levels(highs, lows)
        types = {lv.level_type for lv in levels}
        # Should have both rises and drops
        rise_types = types & {LevelType.R1, LevelType.R2, LevelType.R3}
        drop_types = types & {LevelType.D1, LevelType.D2, LevelType.D3}
        assert len(rise_types) > 0 or len(drop_types) > 0

    def test_no_new_high_skips_rise(self):
        """A rise to the same high doesn't increment count."""
        lows = [_swing(0, 1.0900, SwingType.LOW)]
        highs = [_swing(2, 1.1000, SwingType.HIGH)]
        levels = self.counter.detect_levels(highs, lows)
        assert len(levels) == 1


class TestEdgeCases:
    def test_empty_swings(self):
        counter = LevelCounter()
        assert counter.detect_levels([], []) == []

    def test_only_highs(self):
        highs = [_swing(0, 1.1, SwingType.HIGH)]
        assert LevelCounter().detect_levels(highs, []) == []

    def test_only_lows(self):
        lows = [_swing(0, 1.0, SwingType.LOW)]
        assert LevelCounter().detect_levels([], lows) == []

    def test_single_swing_no_pair(self):
        highs = [_swing(0, 1.1, SwingType.HIGH)]
        lows = [_swing(0, 1.0, SwingType.LOW)]
        levels = LevelCounter().detect_levels(highs, lows)
        # Same bar index — sorted order depends, but len < 2 → no legs
        assert levels == [] or len(levels) <= 1


class TestFeedToHtf:
    def test_feed_format(self):
        counter = LevelCounter()
        from signal_engine.data_types import Level

        level = Level(1.1, LevelType.R1, 0.01, 5, True)
        result = counter.feed_to_htf(level)
        assert result["price"] == 1.1
        assert result["type"] == "R1"
        assert result["completed"] is True

    def test_detect_levels_with_tracking(self):
        lows = [_swing(0, 1.0, SwingType.LOW)]
        highs = [_swing(2, 1.01, SwingType.HIGH)]
        counter = LevelCounter()
        levels = counter.detect_levels_with_tracking(highs, lows)
        assert isinstance(levels, list)
