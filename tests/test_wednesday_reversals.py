#!/usr/bin/env python3
"""Tests for Wednesday reversal analysis with corrected methodology."""

from datetime import datetime

from backtest.engine import Bar
from backtest.wednesday_reversal import DayReversalStats, WednesdayReversalStudy


def _bar(date: datetime, open: float, high: float, low: float, close: float) -> Bar:
    return Bar(time=date, open=open, high=high, low=low, close=close, volume=0)


def test_wednesday_reversal_study_creation():
    study = WednesdayReversalStudy(instrument="EURUSD")
    assert study.instrument == "EURUSD"
    assert study.min_reversal_pips == 50


def test_pip_value_eurusd():
    study = WednesdayReversalStudy(instrument="EURUSD")
    assert study._pip_value(1.1000) == 0.0001


def test_pip_value_usdjpy():
    study = WednesdayReversalStudy(instrument="USDJPY")
    assert study._pip_value(150.0) == 0.01


def test_to_pips_eurusd():
    study = WednesdayReversalStudy(instrument="EURUSD")
    assert study._to_pips(0.0050, 1.1000) == 50.0
    assert study._to_pips(-0.0050, 1.1000) == -50.0


def test_to_pips_usdjpy():
    study = WednesdayReversalStudy(instrument="USDJPY")
    assert study._to_pips(0.50, 150.0) == 50.0
    assert study._to_pips(-0.50, 150.0) == -50.0


def test_is_direction_reversal_tue_up_wed_down():
    study = WednesdayReversalStudy(instrument="EURUSD")
    prev_prev = _bar(datetime(2025, 9, 29), 1.0900, 1.0950, 1.0890, 1.0900)
    prev = _bar(datetime(2025, 9, 30), 1.0900, 1.0960, 1.0890, 1.0960)
    curr = _bar(datetime(2025, 10, 1), 1.0960, 1.1020, 1.0940, 1.0890)
    assert study._is_direction_reversal(prev_prev, prev, curr) is True


def test_is_direction_reversal_same_direction():
    study = WednesdayReversalStudy(instrument="EURUSD")
    prev_prev = _bar(datetime(2025, 9, 29), 1.0900, 1.0950, 1.0890, 1.0900)
    prev = _bar(datetime(2025, 9, 30), 1.0900, 1.0960, 1.0890, 1.0960)
    curr = _bar(datetime(2025, 10, 1), 1.0960, 1.1020, 1.0940, 1.1010)
    assert study._is_direction_reversal(prev_prev, prev, curr) is False


def test_is_direction_reversal_zero_prev():
    study = WednesdayReversalStudy(instrument="EURUSD")
    prev_prev = _bar(datetime(2025, 9, 29), 1.0900, 1.0950, 1.0890, 1.0900)
    prev = _bar(datetime(2025, 9, 30), 1.0900, 1.0960, 1.0890, 1.0900)
    curr = _bar(datetime(2025, 10, 1), 1.0900, 1.1020, 1.0890, 1.0830)
    assert study._is_direction_reversal(prev_prev, prev, curr) is False


def test_analyze_basic():
    study = WednesdayReversalStudy(instrument="EURUSD")
    bars = [
        _bar(datetime(2025, 9, 29), 1.0900, 1.0950, 1.0890, 1.0900),
        _bar(datetime(2025, 9, 30), 1.0900, 1.0960, 1.0890, 1.0950),
        _bar(datetime(2025, 10, 1), 1.0950, 1.1020, 1.0940, 1.1010),
        _bar(datetime(2025, 10, 2), 1.1010, 1.1020, 1.0990, 1.1000),
        _bar(datetime(2025, 10, 3), 1.1000, 1.1010, 1.0900, 1.0910),
        _bar(datetime(2025, 10, 6), 1.0910, 1.0960, 1.0900, 1.0950),
        _bar(datetime(2025, 10, 7), 1.0950, 1.1020, 1.0940, 1.1010),
        _bar(datetime(2025, 10, 8), 1.1010, 1.1020, 1.0950, 1.0960),
        _bar(datetime(2025, 10, 9), 1.0960, 1.0970, 1.0860, 1.0870),
        _bar(datetime(2025, 10, 10), 1.0870, 1.0920, 1.0860, 1.0910),
    ]
    result = study.analyze(bars)
    assert "wednesday" in result
    assert "tuesday" in result
    assert "thursday" in result


def test_analyze_reversal_detected():
    study = WednesdayReversalStudy(instrument="EURUSD")
    bars = [
        _bar(datetime(2025, 10, 6), 1.1000, 1.1050, 1.0990, 1.1000),
        _bar(datetime(2025, 10, 7), 1.1000, 1.1080, 1.0990, 1.1070),
        _bar(datetime(2025, 10, 8), 1.1070, 1.1080, 1.0990, 1.1000),
    ]
    result = study.analyze(bars)
    assert result["wednesday"]["total"] == 1
    assert result["wednesday"]["reversals"] == 1


def test_analyze_no_reversal_same_direction():
    study = WednesdayReversalStudy(instrument="EURUSD")
    bars = [
        _bar(datetime(2025, 10, 6), 1.1000, 1.1050, 1.0990, 1.1000),
        _bar(datetime(2025, 10, 7), 1.1000, 1.1080, 1.0990, 1.1070),
        _bar(datetime(2025, 10, 8), 1.1070, 1.1150, 1.1060, 1.1140),
    ]
    result = study.analyze(bars)
    assert result["wednesday"]["total"] == 1
    assert result["wednesday"]["reversals"] == 0


def test_weekend_gap_skipped():
    study = WednesdayReversalStudy(instrument="EURUSD")
    bars = [
        _bar(datetime(2025, 10, 3), 1.1000, 1.1100, 1.0900, 1.1070),
        _bar(datetime(2025, 10, 6), 1.1070, 1.1150, 1.1060, 1.0950),
        _bar(datetime(2025, 10, 7), 1.0950, 1.1000, 1.0900, 1.1000),
    ]
    result = study.analyze(bars)
    assert result["wednesday"]["total"] == 0


def test_wrong_adjacent_day_skipped():
    study = WednesdayReversalStudy(instrument="EURUSD")
    bars = [
        _bar(datetime(2025, 10, 6), 1.1000, 1.1100, 1.0900, 1.1000),
        _bar(datetime(2025, 10, 7), 1.1000, 1.1100, 1.0900, 1.1000),
        _bar(datetime(2025, 10, 8), 1.1000, 1.1150, 1.0950, 1.0950),
    ]
    result = study.analyze(bars)
    assert result["wednesday"]["total"] == 1
    assert result["wednesday"]["reversals"] == 0


def test_day_reversal_stats_to_dict():
    stats = DayReversalStats(total=10, reversals=5, rate=0.5, avg_pips=65.3)
    d = stats.to_dict()
    assert d == {"total": 10, "reversals": 5, "rate": 0.5, "avg_pips": 65.3}


def test_empty_bars():
    study = WednesdayReversalStudy(instrument="EURUSD")
    result = study.analyze([])
    assert result["wednesday"]["total"] == 0
    assert result["wednesday"]["reversals"] == 0


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
