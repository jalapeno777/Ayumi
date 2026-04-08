from __future__ import annotations

import json
from datetime import datetime

import pytest

from backtest.engine import Bar, SessionType
from backtest.statistical_study import (
    CriterionResult,
    GoNoGoCriteria,
    StatisticalStudy,
    StatisticalStudyResult,
)
from backtest.pattern_detector import MWPattern, MWPatternDetector


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


def _make_rising_bars(n: int, base_price: float = 1.0, step: float = 0.0001) -> list[Bar]:
    bars = []
    for i in range(n):
        h = (i // 24) % 24
        d = (i // 24) + 1
        price = base_price + i * step
        bars.append(
            Bar(
                time=datetime(2023, 1, d, h, 0),
                open=price,
                high=price + 0.0002,
                low=price - 0.0002,
                close=price + step * 0.5,
                volume=100.0,
            )
        )
    return bars


class _DummyStudy(StatisticalStudy):
    def analyze(self, bars: list[Bar]) -> dict:
        return {"hit_rate": 0.65, "sample_size": 100}


class TestGoNoGoCriteria:
    def test_greater_equal_pass(self):
        c = GoNoGoCriteria(metric="hit_rate", threshold=0.6, operator=">=")
        assert c.evaluate(0.65) is True

    def test_greater_equal_fail(self):
        c = GoNoGoCriteria(metric="hit_rate", threshold=0.6, operator=">=")
        assert c.evaluate(0.55) is False

    def test_less_equal_pass(self):
        c = GoNoGoCriteria(metric="max_dd", threshold=5.0, operator="<=")
        assert c.evaluate(3.0) is True

    def test_less_equal_fail(self):
        c = GoNoGoCriteria(metric="max_dd", threshold=5.0, operator="<=")
        assert c.evaluate(6.0) is False

    def test_greater_than_pass(self):
        c = GoNoGoCriteria(metric="pf", threshold=1.5, operator=">")
        assert c.evaluate(1.6) is True

    def test_greater_than_fail_on_equal(self):
        c = GoNoGoCriteria(metric="pf", threshold=1.5, operator=">")
        assert c.evaluate(1.5) is False

    def test_less_than(self):
        c = GoNoGoCriteria(metric="drawdown", threshold=10.0, operator="<")
        assert c.evaluate(5.0) is True
        assert c.evaluate(10.0) is False

    def test_equals(self):
        c = GoNoGoCriteria(metric="value", threshold=1.0, operator="==")
        assert c.evaluate(1.0) is True
        assert c.evaluate(1.0 + 1e-10) is True
        assert c.evaluate(1.001) is False

    def test_unknown_operator_raises(self):
        c = GoNoGoCriteria(metric="x", threshold=0.0, operator="!=")
        with pytest.raises(ValueError, match="Unknown operator"):
            c.evaluate(0.0)


class TestStatisticalStudyResult:
    def test_to_dict_structure(self):
        result = StatisticalStudyResult(
            question="Q1",
            test_period_start="2023-01-01",
            test_period_end="2024-01-01",
            instrument="EURUSD",
            timeframe="H1",
            sample_size=100,
            results={"hit_rate": 0.65},
            go_nogo=True,
            notes="test",
        )
        d = result.to_dict()
        assert d["question"] == "Q1"
        assert d["pass"] is True
        assert d["instrument"] == "EURUSD"
        assert d["timeframe"] == "H1"
        assert d["sample_size"] == 100
        assert d["test_period"] == "2023-01-01 to 2024-01-01"

    def test_to_json_valid(self):
        result = StatisticalStudyResult(
            question="Q1",
            test_period_start="2023-01-01",
            test_period_end="2024-01-01",
            instrument="EURUSD",
            timeframe="H1",
            sample_size=50,
            go_nogo=False,
        )
        j = result.to_json()
        parsed = json.loads(j)
        assert parsed["question"] == "Q1"
        assert parsed["pass"] is False

    def test_to_json_with_criteria(self):
        cr = CriterionResult(
            metric="hit_rate", value=0.7, threshold=0.6,
            operator=">=", passed=True, weight=1.0,
        )
        result = StatisticalStudyResult(
            question="Q2",
            test_period_start="2023-01-01",
            test_period_end="2024-01-01",
            instrument="EURUSD",
            timeframe="H1",
            sample_size=10,
            pass_fail=[cr],
            go_nogo=True,
        )
        j = result.to_json()
        parsed = json.loads(j)
        assert len(parsed["criteria"]) == 1
        assert parsed["criteria"][0]["metric"] == "hit_rate"
        assert parsed["criteria"][0]["passed"] is True

    def test_save_creates_file(self, tmp_path):
        result = StatisticalStudyResult(
            question="Q1",
            test_period_start="2023-01-01",
            test_period_end="2024-01-01",
            instrument="EURUSD",
            timeframe="H1",
            sample_size=10,
        )
        path = tmp_path / "subdir" / "result.json"
        result.save(str(path))
        assert path.exists()
        parsed = json.loads(path.read_text())
        assert parsed["question"] == "Q1"


class TestStatisticalStudy:
    def test_run_returns_result(self):
        study = _DummyStudy(
            question_id="Q1",
            go_nogo_criteria=[
                GoNoGoCriteria(metric="hit_rate", threshold=0.6, operator=">="),
            ],
        )
        bars = _make_rising_bars(100)
        result = study.run(bars)
        assert isinstance(result, StatisticalStudyResult)
        assert result.question == "Q1"
        assert result.sample_size == 100
        assert result.go_nogo is True

    def test_run_empty_bars(self):
        study = _DummyStudy(question_id="Q1")
        result = study.run([])
        assert result.sample_size == 0
        assert result.go_nogo is False

    def test_run_go_nogo_weighted(self):
        study = _DummyStudy(
            question_id="Q1",
            go_nogo_criteria=[
                GoNoGoCriteria(metric="hit_rate", threshold=0.6, operator=">=", weight=2.0),
                GoNoGoCriteria(metric="hit_rate", threshold=0.9, operator=">=", weight=1.0),
            ],
        )
        bars = _make_rising_bars(100)
        result = study.run(bars)
        assert result.go_nogo is True
        assert len(result.pass_fail) == 2

    def test_run_go_nogo_all_fail(self):
        study = _DummyStudy(
            question_id="Q1",
            go_nogo_criteria=[
                GoNoGoCriteria(metric="hit_rate", threshold=0.9, operator=">="),
                GoNoGoCriteria(metric="hit_rate", threshold=0.8, operator=">="),
            ],
        )
        bars = _make_rising_bars(100)
        result = study.run(bars)
        assert result.go_nogo is False

    def test_filter_by_session(self):
        bars = [
            _make_bar(9),
            _make_bar(10),
            _make_bar(13),
            _make_bar(22),
        ]
        study = _DummyStudy(question_id="Q1")
        london = study.filter_by_session(bars, SessionType.LONDON)
        assert len(london) == 2

    def test_filter_by_day_of_week(self):
        bars = [
            _make_bar(10, day=2),
            _make_bar(10, day=3),
            _make_bar(10, day=4),
        ]
        study = _DummyStudy(question_id="Q1")
        wed = study.filter_by_day_of_week(bars, 2)
        assert len(wed) == 1

    def test_filter_by_date_range(self):
        bars = [
            _make_bar(10, day=1),
            _make_bar(10, day=5),
            _make_bar(10, day=10),
        ]
        study = _DummyStudy(question_id="Q1")
        filtered = study.filter_by_date_range(
            bars,
            datetime(2023, 1, 3),
            datetime(2023, 1, 7),
        )
        assert len(filtered) == 1

    def test_group_by_session(self):
        bars = [
            _make_bar(9),
            _make_bar(14),
            _make_bar(18),
            _make_bar(3),
        ]
        study = _DummyStudy(question_id="Q1")
        groups = study.group_by_session(bars)
        assert len(groups[SessionType.LONDON]) == 1
        assert len(groups[SessionType.NY_AM]) == 1
        assert len(groups[SessionType.NY_PM]) == 1
        assert len(groups[SessionType.OUTSIDE]) == 1

    def test_group_by_day(self):
        bars = [
            _make_bar(10, day=1),
            _make_bar(11, day=1),
            _make_bar(10, day=2),
        ]
        study = _DummyStudy(question_id="Q1")
        groups = study.group_by_day(bars)
        assert len(groups) == 2
        assert len(groups["2023-01-01"]) == 2
        assert len(groups["2023-01-02"]) == 1

    def test_compute_atr(self):
        bars = _make_rising_bars(30)
        atr = StatisticalStudy.compute_atr(bars, 14)
        assert len(atr) == 30
        assert atr[0] == 0.0001
        assert all(a > 0 for a in atr)

    def test_pip_value(self):
        assert StatisticalStudy.pip_value(1.1000) == 0.0001
        assert StatisticalStudy.pip_value(145.0) == 0.01
        assert StatisticalStudy.pip_value(0.85) == 0.00000001

    def test_price_to_pips(self):
        pips = StatisticalStudy.price_to_pips(0.0050, 1.1000)
        assert abs(pips - 50.0) < 0.01

    def test_sample_size_from_analyze(self):
        class CustomStudy(StatisticalStudy):
            def analyze(self, bars):
                return {"count": 42, "sample_size": 42}

        study = CustomStudy(question_id="Q1")
        result = study.run(_make_rising_bars(100))
        assert result.sample_size == 42

    def test_notes_contain_criteria(self):
        study = _DummyStudy(
            question_id="Q1",
            go_nogo_criteria=[
                GoNoGoCriteria(metric="hit_rate", threshold=0.6, operator=">="),
            ],
        )
        result = study.run(_make_rising_bars(100))
        assert "hit_rate" in result.notes
        assert "PASS" in result.notes


class TestMWPatternDetector:
    def _make_w_pattern_bars(self) -> list[Bar]:
        bars = []
        pattern = [
            (1.1000, 1.1010, 1.0990, 1.0995),
            (1.0995, 1.1005, 1.0985, 1.0990),
            (1.0990, 1.1000, 1.0980, 1.0985),
            (1.0985, 1.1005, 1.0980, 1.1000),
            (1.1000, 1.1020, 1.0995, 1.1015),
            (1.1015, 1.1030, 1.1010, 1.1025),
            (1.1025, 1.1040, 1.1020, 1.1035),
            (1.1035, 1.1050, 1.1030, 1.1045),
            (1.1045, 1.1060, 1.1040, 1.1055),
            (1.1055, 1.1070, 1.1050, 1.1065),
            (1.1065, 1.1075, 1.1050, 1.1060),
            (1.1060, 1.1070, 1.1040, 1.1050),
            (1.1050, 1.1060, 1.1030, 1.1040),
            (1.1040, 1.1050, 1.1020, 1.1030),
            (1.1030, 1.1040, 1.1010, 1.1020),
            (1.1020, 1.1030, 1.1000, 1.1010),
            (1.1010, 1.1030, 1.1000, 1.1020),
            (1.1020, 1.1040, 1.1010, 1.1030),
            (1.1030, 1.1050, 1.1020, 1.1040),
            (1.1040, 1.1060, 1.1030, 1.1050),
        ]
        for i, (opn, hi, lo, cls) in enumerate(pattern):
            bars.append(
                Bar(
                    time=datetime(2023, 1, 1 + i // 24, i % 24, 0),
                    open=opn, high=hi, low=lo, close=cls, volume=100.0,
                )
            )
        return bars

    def test_detect_empty_bars(self):
        detector = MWPatternDetector()
        patterns = detector.detect([])
        assert patterns == []

    def test_detect_insufficient_bars(self):
        bars = [_make_bar(h) for h in range(5)]
        detector = MWPatternDetector()
        patterns = detector.detect(bars)
        assert patterns == []

    def test_detect_with_w_like_shape(self):
        bars = self._make_w_pattern_bars()
        detector = MWPatternDetector(swing_lookback=2, min_bar_span=5)
        patterns = detector.detect(bars)
        assert isinstance(patterns, list)

    def test_pattern_has_required_fields(self):
        bars = self._make_w_pattern_bars()
        detector = MWPatternDetector(swing_lookback=2, min_bar_span=5)
        patterns = detector.detect(bars)
        for p in patterns:
            assert p.pattern_type in ("M", "W")
            assert p.neckline_level > 0
            assert p.depth_pips >= 0
            assert p.bar_count > 0
            assert len(p.sessions) > 0
            assert p.formation_start_time <= p.formation_end_time

    def test_is_bullish_bearish(self):
        w = MWPattern(
            pattern_type="W",
            left_shoulder_idx=0, left_shoulder_price=1.0,
            neckline_start_idx=0, neckline_start_price=1.0,
            valley_peak_idx=5, valley_peak_price=1.005,
            neckline_end_idx=10, neckline_end_price=1.0,
            right_shoulder_idx=10, right_shoulder_price=1.0,
            neckline_level=1.0, depth_pips=50.0,
            formation_start_time=datetime(2023, 1, 1),
            formation_end_time=datetime(2023, 1, 2),
            sessions=[], bar_count=11,
        )
        assert w.is_bullish is True
        assert w.is_bearish is False

    def test_sessions_spanned_excludes_outside(self):
        p = MWPattern(
            pattern_type="W",
            left_shoulder_idx=0, left_shoulder_price=1.0,
            neckline_start_idx=0, neckline_start_price=1.0,
            valley_peak_idx=5, valley_peak_price=1.005,
            neckline_end_idx=10, neckline_end_price=1.0,
            right_shoulder_idx=10, right_shoulder_price=1.0,
            neckline_level=1.0, depth_pips=50.0,
            formation_start_time=datetime(2023, 1, 1),
            formation_end_time=datetime(2023, 1, 2),
            sessions=[SessionType.LONDON, SessionType.OUTSIDE, SessionType.NY_AM],
            bar_count=11,
        )
        assert p.sessions_spanned_count() == 2

    def test_neckline_break_distance_bullish(self):
        w = MWPattern(
            pattern_type="W",
            left_shoulder_idx=0, left_shoulder_price=1.1,
            neckline_start_idx=0, neckline_start_price=1.1,
            valley_peak_idx=5, valley_peak_price=1.09,
            neckline_end_idx=10, neckline_end_price=1.1,
            right_shoulder_idx=10, right_shoulder_price=1.1,
            neckline_level=1.1, depth_pips=100.0,
            formation_start_time=datetime(2023, 1, 1),
            formation_end_time=datetime(2023, 1, 2),
            sessions=[], bar_count=11,
        )
        assert w.neckline_break_distance == 0.0

    def test_neckline_break_distance_bearish(self):
        m = MWPattern(
            pattern_type="M",
            left_shoulder_idx=0, left_shoulder_price=1.1,
            neckline_start_idx=0, neckline_start_price=1.1,
            valley_peak_idx=5, valley_peak_price=1.12,
            neckline_end_idx=10, neckline_end_price=1.1,
            right_shoulder_idx=10, right_shoulder_price=1.1,
            neckline_level=1.1, depth_pips=200.0,
            formation_start_time=datetime(2023, 1, 1),
            formation_end_time=datetime(2023, 1, 2),
            sessions=[], bar_count=11,
        )
        assert m.neckline_break_distance == 0.0

    def test_remove_overlapping(self):
        p1 = MWPattern(
            pattern_type="W",
            left_shoulder_idx=0, left_shoulder_price=1.0,
            neckline_start_idx=0, neckline_start_price=1.0,
            valley_peak_idx=5, valley_peak_price=1.005,
            neckline_end_idx=10, neckline_end_price=1.0,
            right_shoulder_idx=10, right_shoulder_price=1.0,
            neckline_level=1.0, depth_pips=50.0,
            formation_start_time=datetime(2023, 1, 1),
            formation_end_time=datetime(2023, 1, 5),
            sessions=[], bar_count=11,
        )
        p2 = MWPattern(
            pattern_type="W",
            left_shoulder_idx=0, left_shoulder_price=1.0,
            neckline_start_idx=0, neckline_start_price=1.0,
            valley_peak_idx=5, valley_peak_price=1.005,
            neckline_end_idx=10, neckline_end_price=1.0,
            right_shoulder_idx=10, right_shoulder_price=1.0,
            neckline_level=1.0, depth_pips=50.0,
            formation_start_time=datetime(2023, 1, 3),
            formation_end_time=datetime(2023, 1, 8),
            sessions=[], bar_count=11,
        )
        p3 = MWPattern(
            pattern_type="W",
            left_shoulder_idx=0, left_shoulder_price=1.0,
            neckline_start_idx=0, neckline_start_price=1.0,
            valley_peak_idx=5, valley_peak_price=1.005,
            neckline_end_idx=10, neckline_end_price=1.0,
            right_shoulder_idx=10, right_shoulder_price=1.0,
            neckline_level=1.0, depth_pips=50.0,
            formation_start_time=datetime(2023, 1, 10),
            formation_end_time=datetime(2023, 1, 15),
            sessions=[], bar_count=11,
        )
        detector = MWPatternDetector()
        result = detector._remove_overlapping([p1, p2, p3])
        assert len(result) == 2
        assert result[0] is p1
        assert result[1] is p3
