from __future__ import annotations

from datetime import datetime

from backtest.engine import Bar, SessionType, TradeDirection
from backtest.ict_smc.confluence_engine import (
    MULTI_SESSION_BONUS,
    SINGLE_SESSION_PENALTY,
    SignalConfluenceEngine,
    compute_session_span,
)
from backtest.ict_smc.models import ConfluenceSignal, SignalStrength
from backtest.pattern_detector import MWPattern


def _make_bar(
    hour: int,
    day: int = 1,
    month: int = 1,
    year: int = 2023,
    open_p: float = 1.0,
    high: float = 1.001,
    low: float = 0.999,
    close: float = 1.0005,
    volume: float = 100.0,
) -> Bar:
    return Bar(
        time=datetime(year, month, day, hour, 0),
        open=open_p,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _make_mw_pattern(
    sessions: list[SessionType],
    pattern_type: str = "W",
) -> MWPattern:
    return MWPattern(
        pattern_type=pattern_type,
        left_shoulder_idx=0,
        left_shoulder_price=1.0,
        neckline_start_idx=0,
        neckline_start_price=1.0,
        valley_peak_idx=5,
        valley_peak_price=1.005,
        neckline_end_idx=10,
        neckline_end_price=1.0,
        right_shoulder_idx=10,
        right_shoulder_price=1.0,
        neckline_level=1.0,
        depth_pips=50.0,
        formation_start_time=datetime(2023, 1, 1),
        formation_end_time=datetime(2023, 1, 2),
        sessions=sessions,
        bar_count=11,
    )


class TestMWPatternIsMultiSession:
    def test_single_session_london_is_not_multi(self):
        p = _make_mw_pattern([SessionType.LONDON] * 20)
        assert p.is_multi_session is False

    def test_two_sessions_is_multi(self):
        p = _make_mw_pattern([SessionType.LONDON] * 10 + [SessionType.NY_AM] * 10)
        assert p.is_multi_session is True

    def test_three_sessions_is_multi(self):
        p = _make_mw_pattern([SessionType.LONDON] * 5 + [SessionType.NY_AM] * 5 + [SessionType.NY_PM] * 5)
        assert p.is_multi_session is True

    def test_outside_only_is_not_multi(self):
        p = _make_mw_pattern([SessionType.OUTSIDE] * 20)
        assert p.is_multi_session is False

    def test_outside_plus_one_session_is_not_multi(self):
        p = _make_mw_pattern([SessionType.OUTSIDE] * 10 + [SessionType.LONDON] * 10)
        assert p.is_multi_session is False

    def test_outside_plus_two_sessions_is_multi(self):
        p = _make_mw_pattern([SessionType.OUTSIDE] * 5 + [SessionType.LONDON] * 5 + [SessionType.NY_AM] * 5)
        assert p.is_multi_session is True

    def test_empty_sessions_is_not_multi(self):
        p = _make_mw_pattern([])
        assert p.is_multi_session is False


class TestMWPatternSessionSpanQualityScore:
    def test_single_session_has_lowest_score(self):
        p = _make_mw_pattern([SessionType.LONDON] * 20)
        assert p.session_span_quality_score == 0.55

    def test_two_sessions_has_medium_score(self):
        p = _make_mw_pattern([SessionType.LONDON] * 10 + [SessionType.NY_AM] * 10)
        assert p.session_span_quality_score == 0.85

    def test_three_sessions_has_highest_score(self):
        p = _make_mw_pattern([SessionType.LONDON] * 5 + [SessionType.NY_AM] * 5 + [SessionType.NY_PM] * 5)
        assert p.session_span_quality_score == 1.0

    def test_four_or_more_sessions_has_highest_score(self):
        p = _make_mw_pattern(
            [SessionType.LONDON] * 5 + [SessionType.NY_AM] * 5 + [SessionType.NY_PM] * 5 + [SessionType.LONDON] * 5
        )
        assert p.session_span_quality_score == 1.0

    def test_empty_sessions_has_lowest_score(self):
        p = _make_mw_pattern([])
        assert p.session_span_quality_score == 0.55

    def test_multi_session_score_higher_than_single(self):
        single = _make_mw_pattern([SessionType.LONDON] * 20)
        multi = _make_mw_pattern([SessionType.LONDON] * 10 + [SessionType.NY_AM] * 10)
        assert multi.session_span_quality_score > single.session_span_quality_score


class TestComputeSessionSpan:
    def test_empty_bars(self):
        count, is_multi = compute_session_span([])
        assert count == 0
        assert is_multi is False

    def test_single_session_bars(self):
        bars = [_make_bar(hour=9) for _ in range(10)]
        count, is_multi = compute_session_span(bars)
        assert count == 1
        assert is_multi is False

    def test_multi_session_bars_london_ny(self):
        bars = [_make_bar(hour=9) for _ in range(5)] + [_make_bar(hour=13) for _ in range(5)]
        count, is_multi = compute_session_span(bars)
        assert count == 2
        assert is_multi is True

    def test_multi_session_bars_three_sessions(self):
        bars = (
            [_make_bar(hour=9) for _ in range(3)]
            + [_make_bar(hour=13) for _ in range(3)]
            + [_make_bar(hour=17) for _ in range(3)]
        )
        count, is_multi = compute_session_span(bars)
        assert count == 3
        assert is_multi is True

    def test_outside_hours_excluded(self):
        bars = [_make_bar(hour=21) for _ in range(5)] + [_make_bar(hour=22) for _ in range(5)]
        count, is_multi = compute_session_span(bars)
        assert count == 0
        assert is_multi is False

    def test_mixed_with_outside(self):
        bars = (
            [_make_bar(hour=21) for _ in range(3)]
            + [_make_bar(hour=9) for _ in range(3)]
            + [_make_bar(hour=13) for _ in range(3)]
        )
        count, is_multi = compute_session_span(bars)
        assert count == 2
        assert is_multi is True


class TestConfluenceSignalSessionSpanFields:
    def test_default_values(self):
        signal = ConfluenceSignal(
            direction=TradeDirection.LONG,
            strength=SignalStrength.MODERATE,
            confidence_score=0.6,
            entry_price=1.1,
            stop_loss=1.09,
            take_profit_1=1.11,
            take_profit_2=1.12,
            take_profit_3=1.13,
            signal_time=datetime(2023, 1, 1),
            rationale="test",
        )
        assert signal.session_span_count == 0
        assert signal.is_multi_session is False

    def test_multi_session_values(self):
        signal = ConfluenceSignal(
            direction=TradeDirection.LONG,
            strength=SignalStrength.MODERATE,
            confidence_score=0.6,
            entry_price=1.1,
            stop_loss=1.09,
            take_profit_1=1.11,
            take_profit_2=1.12,
            take_profit_3=1.13,
            signal_time=datetime(2023, 1, 1),
            rationale="test",
            session_span_count=3,
            is_multi_session=True,
        )
        assert signal.session_span_count == 3
        assert signal.is_multi_session is True


class TestSignalConfluenceEngineMultiSession:
    def test_multi_session_bonus_increases_confidence(self):
        engine = SignalConfluenceEngine(
            min_confidence=0.3,
            multi_session_weight_bonus=MULTI_SESSION_BONUS,
            single_session_penalty=SINGLE_SESSION_PENALTY,
        )
        assert engine._multi_session_bonus == MULTI_SESSION_BONUS
        assert engine._single_session_penalty == SINGLE_SESSION_PENALTY

    def test_custom_bonus_and_penalty(self):
        engine = SignalConfluenceEngine(
            multi_session_weight_bonus=0.15,
            single_session_penalty=0.05,
        )
        assert engine._multi_session_bonus == 0.15
        assert engine._single_session_penalty == 0.05

    def test_bonus_defaults_are_positive(self):
        assert MULTI_SESSION_BONUS > 0
        assert SINGLE_SESSION_PENALTY > 0
        assert MULTI_SESSION_BONUS > SINGLE_SESSION_PENALTY
