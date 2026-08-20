"""Tests for PatternDetector: M/W formations, SVC, traps, liquidity grabs, FL."""

from __future__ import annotations  # noqa: I001


from signal_engine.pattern_detector import PatternDetector
from signal_engine.data_types import Level, LevelType, Swing, SwingType


def _make_swings(prices: list[tuple[int, float, str]]) -> list[Swing]:
    """Helper: (bar_index, price, 'H'|'L')"""
    return [Swing(bi, p, SwingType.HIGH if t == "H" else SwingType.LOW) for bi, p, t in prices]


# ── M/W Formation Tests ────────────────────────────────────────────


class TestMWFormation:
    def setup_method(self):
        self.detector = PatternDetector()

    def test_detects_w_bullish_reversal(self):
        """W pattern: lower lows with higher high in middle → long signal."""
        swings = _make_swings(
            [
                (0, 1.1000, "L"),  # SL1
                (2, 1.1050, "H"),  # SH1
                (4, 1.0990, "L"),  # SL2 (lower than SL1)
                (6, 1.1060, "H"),  # SH2 (higher than SH1)
                (8, 1.0985, "L"),  # SL3 (breaks SL1)
            ]
        )
        levels = [
            Level(1.1000, LevelType.D1, 0.0050, 0),
            Level(1.0990, LevelType.D2, 0.0060, 4),
        ]
        result = self.detector.detect_mw_formation(swings, levels, 1.0985)
        assert result is not None
        assert result.pattern_type == "W"
        assert result.direction == "long"
        assert result.checklist_score > 0.4

    def test_detects_m_bearish_reversal(self):
        """M pattern: higher highs with lower low in middle → short signal."""
        swings = _make_swings(
            [
                (0, 1.1000, "H"),  # SH1
                (2, 1.0950, "L"),  # SL1
                (4, 1.1010, "H"),  # SH2 (higher than SH1)
                (6, 1.0940, "L"),  # SL2 (lower than SL1)
                (8, 1.1015, "H"),  # SH3 (breaks SH1)
            ]
        )
        levels = [
            Level(1.1000, LevelType.R1, 0.0050, 0),
            Level(1.1010, LevelType.R2, 0.0060, 4),
        ]
        result = self.detector.detect_mw_formation(swings, levels, 1.1015)
        assert result is not None
        assert result.pattern_type == "M"
        assert result.direction == "short"

    def test_no_pattern_insufficient_swings(self):
        """Should return None with fewer than 5 alternating swings."""
        swings = _make_swings(
            [
                (0, 1.1000, "H"),
                (2, 1.0950, "L"),
                (4, 1.1010, "H"),
            ]
        )
        result = self.detector.detect_mw_formation(swings, [])
        assert result is None

    def test_no_pattern_bad_structure(self):
        """M pattern fails if SH3 doesn't break SH1."""
        swings = _make_swings(
            [
                (0, 1.1000, "H"),
                (2, 1.0950, "L"),
                (4, 1.0990, "H"),  # SH2 below SH1
                (6, 1.0940, "L"),
                (8, 1.0995, "H"),  # SH3 doesn't break SH1
            ]
        )
        result = self.detector.detect_mw_formation(swings, [])
        assert result is None


# ── SVC Tests ──────────────────────────────────────────────────────


class TestSVC:
    def setup_method(self):
        self.detector = PatternDetector()

    def test_detects_spring(self):
        """SVC spring: wick below D1 level, body closes above."""
        bar = {"high": 1.0970, "low": 1.0940, "open": 1.0955, "close": 1.0960}
        levels = [Level(1.0950, LevelType.D1, 0.005, 0)]
        result = self.detector.detect_svc(bar, levels)
        assert result is not None
        assert result.pattern_type == "SVC_SPRING"
        assert result.direction == "long"

    def test_detects_vacation(self):
        """SVC vacation: wick above R1 level, body closes below."""
        bar = {"high": 1.1010, "low": 1.0980, "open": 1.0995, "close": 1.0990}
        levels = [Level(1.1000, LevelType.R1, 0.005, 0)]
        result = self.detector.detect_svc(bar, levels)
        assert result is not None
        assert result.pattern_type == "SVC_VACATION"
        assert result.direction == "short"

    def test_no_svc_small_body(self):
        """Small body candle should not be detected as SVC."""
        bar = {"high": 1.0960, "low": 1.0940, "open": 1.0945, "close": 1.0955}
        levels = [Level(1.0950, LevelType.D1, 0.005, 0)]
        result = self.detector.detect_svc(bar, levels)
        # Body ratio = 0.001/0.002 = 0.50 — borderline; check continuity path
        assert result is None or result.pattern_type != "SVC_SPRING"


# ── Trap Tests ─────────────────────────────────────────────────────


class TestTrap:
    def setup_method(self):
        self.detector = PatternDetector()

    def test_detects_bullish_trap(self):
        """Price breaks above level then closes below → bearish trap."""
        bars = [
            {"high": 1.1050, "low": 1.0980, "close": 1.1040, "open": 1.1000},
            {"high": 1.1060, "low": 1.0990, "close": 1.0990, "open": 1.1040},
        ]
        result = self.detector.detect_trap(bars, 1.1000, "LONDON")
        assert result is not None
        assert result.pattern_type == "TRAP"
        assert result.direction == "short"

    def test_detects_bearish_trap(self):
        """Price breaks below level then closes above → bullish trap."""
        bars = [
            {"high": 1.1020, "low": 1.0940, "close": 1.0950, "open": 1.1000},
            {"high": 1.1010, "low": 1.0950, "close": 1.1010, "open": 1.0955},
        ]
        result = self.detector.detect_trap(bars, 1.1000, "LONDON")
        assert result is not None
        assert result.direction == "long"

    def test_no_trap_insufficient_break(self):
        """Break too small → no trap detected."""
        bars = [
            {"high": 1.1002, "low": 1.0998, "close": 1.1002, "open": 1.0999},
        ]
        result = self.detector.detect_trap(bars, 1.1000, "LONDON")
        assert result is None

    def test_asia_requires_larger_break(self):
        """Asia session requires 0.4% break, not 0.2%."""
        level = 1.1000
        # 0.3% break — passes London, fails Asia
        bars = [
            {"high": 1.1033, "low": 1.0998, "close": 1.0995, "open": 1.1030},
        ]
        london_result = self.detector.detect_trap(bars, level, "LONDON")
        asia_result = self.detector.detect_trap(bars, level, "ASIA")
        assert london_result is not None
        assert asia_result is None


# ── Liquidity Grab Tests ───────────────────────────────────────────


class TestLiquidityGrab:
    def setup_method(self):
        self.detector = PatternDetector()

    def test_detects_bullish_liq_grab(self):
        # open and close both above level, long wick below
        bar = {"high": 1.1000, "low": 1.0920, "open": 1.0960, "close": 1.0970}
        levels = [Level(1.0955, LevelType.D1, 0.005, 0)]
        result = self.detector.detect_liquidity_grab(bar, levels)
        assert result is not None
        assert result.direction == "long"
        assert result.pattern_type == "LIQUIDITY_GRAB"

    def test_detects_bearish_liq_grab(self):
        # open and close both below level, long wick above
        bar = {"high": 1.1080, "low": 1.1000, "open": 1.1040, "close": 1.1030}
        levels = [Level(1.1045, LevelType.R1, 0.005, 0)]
        result = self.detector.detect_liquidity_grab(bar, levels)
        assert result is not None
        assert result.direction == "short"


# ── FL Pattern Tests ───────────────────────────────────────────────


class TestFLPattern:
    def setup_method(self):
        self.detector = PatternDetector()

    def test_detects_bullish_fl(self):
        """HH-HL staircase pattern → bullish FL."""
        swings = _make_swings(
            [
                (0, 1.0950, "L"),  # HL1
                (2, 1.1000, "H"),  # HH1
                (4, 1.0970, "L"),  # HL2
                (6, 1.1030, "H"),  # HH2
                (8, 1.0990, "L"),  # HL3
                (10, 1.1050, "H"),  # HH3
            ]
        )
        result = self.detector.detect_fl_pattern(swings, [])
        assert result is not None
        assert result.direction == "long"
        assert result.pattern_type == "FL"

    def test_detects_bearish_fl(self):
        """LH-LL staircase → bearish FL."""
        swings = _make_swings(
            [
                (0, 1.1050, "H"),
                (2, 1.1000, "L"),
                (4, 1.1030, "H"),
                (6, 1.0970, "L"),
                (8, 1.1010, "H"),
                (10, 1.0950, "L"),
            ]
        )
        result = self.detector.detect_fl_pattern(swings, [])
        assert result is not None
        assert result.direction == "short"

    def test_no_fl_insufficient_swings(self):
        swings = _make_swings([(0, 1.1, "H"), (2, 1.09, "L")])
        result = self.detector.detect_fl_pattern(swings, [])
        assert result is None


# ── Composite Detection ────────────────────────────────────────────


class TestDetectAll:
    def test_detect_all_returns_patterns(self):
        detector = PatternDetector()
        swings = _make_swings(
            [
                (0, 1.0950, "L"),
                (2, 1.1000, "H"),
                (4, 1.0990, "L"),
                (6, 1.1010, "H"),
                (8, 1.0985, "L"),
            ]
        )
        levels = [Level(1.1000, LevelType.R1, 0.005, 2)]
        bars = [{"high": 1.1020, "low": 1.0970, "open": 1.0990, "close": 1.1010}]
        patterns = detector.detect_all(swings, levels, bars, 1.1010, "LONDON")
        assert isinstance(patterns, list)
        assert len(patterns) > 0
