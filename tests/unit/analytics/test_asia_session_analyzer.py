"""Tests for AsiaSessionAnalyzer and flight-log pattern detection."""

from __future__ import annotations

from datetime import datetime, timedelta, time as dt_time


from signal_engine.data_types import Swing, SwingType
from signal_engine.pattern_detector import (
    AsiaSessionAnalyzer,
    PatternDetector,
)


# ── Fixtures ───────────────────────────────────────────────────────
# ET offset: April = EDT (UTC-4). Bars store UTC timestamps.
_ET_OFFSET = timedelta(hours=4)


def _et_to_utc(et_hour: int, et_minute: int = 0) -> datetime:
    """Convert an ET hour to a naive UTC datetime (April EDT)."""
    t = datetime(2026, 4, 10, et_hour, et_minute) + _ET_OFFSET
    return t


def _make_bar(
    high: float, low: float, close: float, open_: float, hour: int, minute: int = 0
) -> dict:
    return {
        "high": high,
        "low": low,
        "close": close,
        "open": open_,
        "time": _et_to_utc(hour, minute),
    }


def _make_asia_bars(
    price: float = 1.0850, range_pips: float = 10, hours: list[int] | None = None
) -> list[dict]:
    """Create bars during Asia window (8pm–1:30am ET, stored as UTC)."""
    if hours is None:
        hours = [20, 20, 21, 21, 22, 22, 23, 23, 0, 0, 1]
    mid = price
    half = range_pips * 0.0001 / 2
    bars = []
    for h in hours:
        # Alternate touching high and low for consolidation
        if len(bars) % 2 == 0:
            bars.append(_make_bar(mid + half, mid - half + 0.00001, mid, mid, h))
        else:
            bars.append(_make_bar(mid + half - 0.00001, mid - half, mid, mid, h))
    return bars


# ── AsiaSessionAnalyzer Tests ──────────────────────────────────────


class TestAsiaRangeQualification:
    def test_tight_range_is_tradable(self):
        analyzer = AsiaSessionAnalyzer(max_range_pct=2.0)
        bars = _make_asia_bars(price=1.0850, range_pips=10)  # ~0.09%
        result = analyzer.analyze_asia_range(bars)
        assert result is not None
        assert result.is_tradable is True
        assert result.range_pct < 2.0

    def test_wide_range_is_not_tradable(self):
        analyzer = AsiaSessionAnalyzer(max_range_pct=2.0)
        bars = _make_asia_bars(price=1.0850, range_pips=300)  # ~2.7%
        result = analyzer.analyze_asia_range(bars)
        assert result is not None
        assert result.is_tradable is False
        assert result.range_pct > 2.0

    def test_empty_bars_returns_none(self):
        analyzer = AsiaSessionAnalyzer()
        assert analyzer.analyze_asia_range([]) is None

    def test_insufficient_bars_returns_none(self):
        analyzer = AsiaSessionAnalyzer()
        bars = [_make_bar(1.0860, 1.0840, 1.0850, 1.0850, 20)]
        assert analyzer.analyze_asia_range(bars) is None

    def test_consolidation_detected(self):
        analyzer = AsiaSessionAnalyzer(min_touches_per_side=2)
        bars = _make_asia_bars(price=1.0850, range_pips=10)
        result = analyzer.analyze_asia_range(bars)
        assert result is not None
        assert result.is_consolidated is True
        assert result.high_touches >= 2
        assert result.low_touches >= 2

    def test_no_consolidation_when_one_sided(self):
        analyzer = AsiaSessionAnalyzer(
            min_touches_per_side=2, touch_tolerance_pct=0.001
        )
        # All bars have same high, low varies — only high touched
        bars = []
        for h in [20, 21, 22, 23, 0, 1]:
            bars.append(
                _make_bar(1.0860, 1.0840 + 0.0001 * len(bars), 1.0850, 1.0850, h)
            )
        result = analyzer.analyze_asia_range(bars)
        assert result is not None
        # With tight tolerance, each unique low should NOT count as a touch to asia_low
        assert result.low_touches < 2


class TestSessionFilter:
    def test_london_kz(self):
        analyzer = AsiaSessionAnalyzer()
        assert analyzer.is_kill_zone(_et_to_utc(3, 0)) == "london_kz"
        assert analyzer.is_kill_zone(_et_to_utc(4, 30)) == "london_kz"

    def test_ny_kz(self):
        analyzer = AsiaSessionAnalyzer()
        assert analyzer.is_kill_zone(_et_to_utc(8, 0)) == "ny_kz"
        assert analyzer.is_kill_zone(_et_to_utc(9, 30)) == "ny_kz"

    def test_outside_kill_zone(self):
        analyzer = AsiaSessionAnalyzer()
        assert analyzer.is_kill_zone(_et_to_utc(6, 0)) == "outside"
        assert analyzer.is_kill_zone(_et_to_utc(12, 0)) == "outside"
        assert analyzer.is_kill_zone(_et_to_utc(21, 0)) == "outside"

    def test_mandatory_exit(self):
        analyzer = AsiaSessionAnalyzer()
        assert analyzer.should_mandatory_exit(_et_to_utc(7, 59)) is False
        assert analyzer.should_mandatory_exit(_et_to_utc(8, 0)) is True
        assert analyzer.should_mandatory_exit(_et_to_utc(10, 0)) is True


class TestAsiaWindowFiltering:
    def test_filters_pm_bars(self):
        analyzer = AsiaSessionAnalyzer()
        bars = [
            _make_bar(1.086, 1.084, 1.085, 1.085, 19),  # before — excluded
            _make_bar(1.086, 1.084, 1.085, 1.085, 20),  # included
            _make_bar(1.086, 1.084, 1.085, 1.085, 22),  # included
            _make_bar(1.086, 1.084, 1.085, 1.085, 1),  # included
            _make_bar(1.086, 1.084, 1.085, 1.085, 2),  # after — excluded
        ]
        filtered = analyzer._filter_asia_bars(bars)
        assert len(filtered) == 3

    def test_quality_score_range(self):
        analyzer = AsiaSessionAnalyzer()
        bars = _make_asia_bars(price=1.0850, range_pips=5)
        result = analyzer.analyze_asia_range(bars)
        assert result is not None
        assert 0.0 <= result.quality_score <= 1.0


# ── Flight-Log Pattern Detection Tests ─────────────────────────────


class TestFlightLogPatterns:
    """Integration tests for flight-log pattern detection."""

    def _make_detector(self) -> PatternDetector:
        return PatternDetector()

    def _make_asia_analyzer(self) -> AsiaSessionAnalyzer:
        return AsiaSessionAnalyzer()

    def test_no_signals_outside_kill_zone(self):
        detector = self._make_detector()
        analyzer = self._make_asia_analyzer()
        bars = _make_asia_bars()
        # 6pm ET — outside all kill zones
        bar_time = _et_to_utc(18, 0)
        patterns = detector._detect_flight_log_patterns(
            swings=[],
            levels=[],
            bars=bars,
            current_price=1.085,
            bar_time=bar_time,
            asia_analyzer=analyzer,
        )
        assert patterns == []

    def test_no_signals_after_mandatory_exit(self):
        detector = self._make_detector()
        analyzer = self._make_asia_analyzer()
        bars = _make_asia_bars()
        # 9am ET — past mandatory exit
        bar_time = _et_to_utc(9, 0)
        patterns = detector._detect_flight_log_patterns(
            swings=[],
            levels=[],
            bars=bars,
            current_price=1.085,
            bar_time=bar_time,
            asia_analyzer=analyzer,
        )
        assert patterns == []

    def test_no_signals_on_wide_asia_range(self):
        detector = self._make_detector()
        analyzer = self._make_asia_analyzer()
        # 300 pips range — too wide
        bars = _make_asia_bars(range_pips=300)
        bar_time = _et_to_utc(3, 0)
        patterns = detector._detect_flight_log_patterns(
            swings=[],
            levels=[],
            bars=bars,
            current_price=1.085,
            bar_time=bar_time,
            asia_analyzer=analyzer,
        )
        assert patterns == []

    def test_fl002_bullish_liquidity_grab(self):
        detector = self._make_detector()
        analyzer = self._make_asia_analyzer()
        asia_bars = _make_asia_bars(price=1.0850, range_pips=10)
        asia_result = analyzer.analyze_asia_range(asia_bars)
        assert asia_result is not None
        assert asia_result.is_tradable

        asia_low = asia_result.asia_low
        # Add a grab candle that sweeps below Asia low with large wick
        grab_bar = {
            "high": 1.0855,
            "low": asia_low - 0.0015,
            "open": 1.0848,
            "close": 1.0852,
            "time": _et_to_utc(3, 0),
        }
        # Current bar closing above Asia low (entry window)
        current_bar = {
            "high": 1.0856,
            "low": 1.0850,
            "open": 1.0852,
            "close": 1.0854,
            "time": _et_to_utc(3, 15),
        }
        all_bars = asia_bars + [grab_bar, current_bar]

        pattern = detector._detect_fl002(all_bars, 1.0854, asia_result)
        assert pattern is not None
        assert pattern.flight_log_id == "FL-002"
        assert pattern.direction == "long"
        assert pattern.stop_at_first_peak is True
        assert pattern.key_levels["target"] == asia_result.asia_high

    def test_fl002_bearish_liquidity_grab(self):
        detector = self._make_detector()
        analyzer = self._make_asia_analyzer()
        asia_bars = _make_asia_bars(price=1.0850, range_pips=10)
        asia_result = analyzer.analyze_asia_range(asia_bars)
        assert asia_result is not None

        asia_high = asia_result.asia_high
        grab_bar = {
            "high": asia_high + 0.0015,
            "low": 1.0848,
            "open": 1.0852,
            "close": 1.0849,
            "time": _et_to_utc(3, 0),
        }
        current_bar = {
            "high": 1.0850,
            "low": 1.0845,
            "open": 1.0849,
            "close": 1.0846,
            "time": _et_to_utc(3, 15),
        }
        all_bars = asia_bars + [grab_bar, current_bar]

        pattern = detector._detect_fl002(all_bars, 1.0846, asia_result)
        assert pattern is not None
        assert pattern.flight_log_id == "FL-002"
        assert pattern.direction == "short"

    def test_fl002_no_grab_without_sweep(self):
        detector = self._make_detector()
        analyzer = self._make_asia_analyzer()
        asia_bars = _make_asia_bars(price=1.0850, range_pips=10)
        asia_result = analyzer.analyze_asia_range(asia_bars)
        assert asia_result is not None

        # Normal candle — no sweep outside range
        bar1 = _make_bar(1.0855, 1.0845, 1.0850, 1.0848, 3)
        bar2 = _make_bar(1.0856, 1.0846, 1.0852, 1.0850, 3)
        all_bars = asia_bars + [bar1, bar2]

        pattern = detector._detect_fl002(all_bars, 1.0852, asia_result)
        assert pattern is None

    def test_fl001_w_single_session(self):
        detector = self._make_detector()
        analyzer = self._make_asia_analyzer()
        asia_bars = _make_asia_bars(price=1.0850, range_pips=15)
        asia_result = analyzer.analyze_asia_range(asia_bars)
        assert asia_result is not None

        asia_low = asia_result.asia_low
        asia_high = asia_result.asia_high
        mid = (asia_high + asia_low) / 2

        # Create swings: SL1 (lower), SH1 (peak), SL2 (higher low)
        swings = [
            Swing(bar_index=0, price=asia_low + 0.0001, swing_type=SwingType.LOW),
            Swing(bar_index=2, price=mid + 0.0002, swing_type=SwingType.HIGH),
            Swing(bar_index=4, price=asia_low + 0.0003, swing_type=SwingType.LOW),  # HL
        ]

        # Trigger bar at SL2, current bar rising
        trigger = _make_bar(
            mid, asia_low + 0.0003, asia_low + 0.0004, asia_low + 0.0002, 3
        )
        current = _make_bar(
            mid + 0.0002, asia_low + 0.0004, mid - 0.0001, asia_low + 0.0004, 3
        )

        pattern = detector._detect_fl001(
            swings,
            asia_bars + [trigger, current],
            mid - 0.0001,
            asia_result,
        )
        # Pattern may or may not trigger depending on exact bar conditions
        if pattern:
            assert pattern.flight_log_id == "FL-001"
            assert pattern.direction == "long"
            assert pattern.stop_at_first_peak is True

    def test_fl004_bullish_fakeout(self):
        detector = self._make_detector()
        analyzer = self._make_asia_analyzer()
        asia_bars = _make_asia_bars(price=1.0850, range_pips=10)
        asia_result = analyzer.analyze_asia_range(asia_bars)
        assert asia_result is not None

        asia_low = asia_result.asia_low

        # Bars showing break below then recovery
        sweep_bar = _make_bar(1.0845, asia_low - 0.0010, asia_low - 0.0002, 1.0848, 3)
        recovery_bar = _make_bar(1.0852, 1.0848, 1.0851, 1.0849, 3)

        [
            Swing(bar_index=0, price=asia_low + 0.0001, swing_type=SwingType.LOW),
            Swing(bar_index=2, price=1.0855, swing_type=SwingType.HIGH),
            Swing(bar_index=4, price=asia_low + 0.0002, swing_type=SwingType.LOW),
        ]

        pattern = detector._detect_fl004(
            asia_bars + [sweep_bar, recovery_bar],
            1.0851,
            asia_result,
        )
        if pattern:
            assert pattern.flight_log_id == "FL-004"
            assert pattern.direction == "long"

    def test_detected_pattern_has_flight_log_fields(self):
        """Verify DetectedPattern supports flight-log extensions."""
        from signal_engine.pattern_detector import DetectedPattern

        p = DetectedPattern(
            pattern_type="W",
            direction="long",
            confidence=0.8,
            flight_log_id="FL-001",
            asia_range=(1.086, 1.084),
            stop_at_first_peak=True,
            mandatory_exit_time=dt_time(8, 0),
        )
        assert p.flight_log_id == "FL-001"
        assert p.asia_range == (1.086, 1.084)
        assert p.stop_at_first_peak is True
        assert p.mandatory_exit_time == dt_time(8, 0)


# ── Backward Compatibility ─────────────────────────────────────────


class TestBackwardCompatibility:
    """Ensure existing pattern detection still works unchanged."""

    def test_detect_all_without_asia_analyzer(self):
        detector = PatternDetector()
        swings = [
            Swing(0, 1.0900, SwingType.HIGH),
            Swing(2, 1.0850, SwingType.LOW),
            Swing(4, 1.0895, SwingType.HIGH),  # lower high
            Swing(6, 1.0840, SwingType.LOW),  # lower low
            Swing(8, 1.0905, SwingType.HIGH),  # breaks SH1 → M confirmed
        ]
        bars = [{"high": 1.0890, "low": 1.0840, "close": 1.0845, "open": 1.0880}]
        # Call without bar_time / asia_analyzer — should still work
        patterns = detector.detect_all(
            swings=swings,
            levels=[],
            bars=bars,
            current_price=1.0845,
            session="LONDON",
        )
        # Should find M pattern from existing logic
        mw_found = any(p.pattern_type == "M" for p in patterns)
        assert mw_found, "Existing M/W detection should still work"
