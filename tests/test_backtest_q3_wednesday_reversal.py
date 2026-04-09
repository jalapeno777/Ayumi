"""Tests for BACKTEST Q3 Wednesday Midweek Reversal Analysis"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.engine import Bar


def _dbar(date: datetime, open_p: float, close: float) -> Bar:
    return Bar(
        time=date,
        open=open_p,
        high=max(open_p, close) + 0.001,
        low=min(open_p, close) - 0.001,
        close=close,
    )


class TestComputeBarDirection:
    def test_up_bar(self):
        from scripts.backtest_q3_wednesday_reversal import compute_bar_direction

        bar = Bar(time=None, open=1.0, high=1.01, low=0.99, close=1.005)
        assert compute_bar_direction(bar) == 1

    def test_down_bar(self):
        from scripts.backtest_q3_wednesday_reversal import compute_bar_direction

        bar = Bar(time=None, open=1.005, high=1.01, low=0.99, close=1.0)
        assert compute_bar_direction(bar) == -1

    def test_flat_bar(self):
        from scripts.backtest_q3_wednesday_reversal import compute_bar_direction

        bar = Bar(time=None, open=1.0, high=1.001, low=0.999, close=1.0)
        assert compute_bar_direction(bar) == 0


class TestAdjacentWeekdays:
    def test_monday_after_friday(self):
        from scripts.backtest_q3_wednesday_reversal import _are_adjacent_weekdays

        assert _are_adjacent_weekdays(4, 0) is True

    def test_consecutive_weekdays(self):
        from scripts.backtest_q3_wednesday_reversal import _are_adjacent_weekdays

        assert _are_adjacent_weekdays(0, 1) is True
        assert _are_adjacent_weekdays(1, 2) is True
        assert _are_adjacent_weekdays(2, 3) is True
        assert _are_adjacent_weekdays(3, 4) is True

    def test_non_adjacent(self):
        from scripts.backtest_q3_wednesday_reversal import _are_adjacent_weekdays

        assert _are_adjacent_weekdays(0, 2) is False
        assert _are_adjacent_weekdays(4, 2) is False
        assert _are_adjacent_weekdays(1, 3) is False

    def test_same_day(self):
        from scripts.backtest_q3_wednesday_reversal import _are_adjacent_weekdays

        assert _are_adjacent_weekdays(2, 2) is False


class TestAnalyzeReversals:
    def test_perfect_alternation(self):
        from scripts.backtest_q3_wednesday_reversal import analyze_reversals

        base = datetime(2024, 1, 8)
        bars = []
        for i in range(10):
            dt = base + timedelta(days=i)
            close = 1.0 if i % 2 == 0 else 1.005
            open_p = 1.003 if i % 2 == 0 else 0.997
            bars.append(_dbar(dt, open_p, close))

        results = analyze_reversals(bars)
        assert results["question"] == "Q3"
        assert "by_day" in results
        for day_name, stats in results["by_day"].items():
            assert "reversal_rate" in stats
            assert "total_days" in stats

    def test_no_reversals(self):
        from scripts.backtest_q3_wednesday_reversal import analyze_reversals

        base = datetime(2024, 1, 8)
        bars = []
        for i in range(10):
            dt = base + timedelta(days=i)
            bars.append(_dbar(dt, 1.0, 1.005))

        results = analyze_reversals(bars)
        for day_name, stats in results["by_day"].items():
            if stats["total_days"] > 0:
                assert stats["reversal_rate"] == 0.0

    def test_holiday_gap_skipped(self):
        from scripts.backtest_q3_wednesday_reversal import analyze_reversals

        fri = datetime(2024, 1, 5)
        tue = datetime(2024, 1, 9)
        wed = datetime(2024, 1, 10)

        bars = [
            _dbar(fri, 1.0, 1.005),
            _dbar(tue, 1.005, 1.0),
            _dbar(wed, 1.0, 1.005),
        ]

        results = analyze_reversals(bars)
        tue_stats = results["by_day"]["Tuesday"]
        wed_stats = results["by_day"]["Wednesday"]
        assert tue_stats["total_days"] == 0
        assert wed_stats["total_days"] == 1

    def test_correct_tue_wed_pair(self):
        from scripts.backtest_q3_wednesday_reversal import analyze_reversals

        mon = datetime(2024, 1, 8)
        tue = datetime(2024, 1, 9)
        wed = datetime(2024, 1, 10)

        bars = [
            _dbar(mon, 1.0, 1.005),
            _dbar(tue, 1.005, 1.0),
            _dbar(wed, 1.0, 1.005),
        ]

        results = analyze_reversals(bars)
        tue_stats = results["by_day"]["Tuesday"]
        wed_stats = results["by_day"]["Wednesday"]
        assert tue_stats["total_days"] == 1
        assert wed_stats["total_days"] == 1
        assert wed_stats["reversals"] == 1

    def test_insufficient_data(self):
        from scripts.backtest_q3_wednesday_reversal import analyze_reversals

        result = analyze_reversals([])
        assert "error" in result

    def test_results_format(self):
        from scripts.backtest_q3_wednesday_reversal import analyze_reversals

        base = datetime(2024, 1, 8)
        bars = []
        for i in range(100):
            dt = base + timedelta(days=i)
            direction = 1 if i % 3 == 0 else -1
            close = 1.0 + direction * 0.001
            open_p = 1.0
            bars.append(_dbar(dt, open_p, close))

        results = analyze_reversals(bars)
        assert results["question"] == "Q3"
        assert "test_period" in results
        assert results["instrument"] == "EURUSD"
        assert results["timeframe"] == "D1"
        assert results["sample_size"] > 0
        assert "wednesday_reversal_rate" in results["results"]
        assert "avg_reversal_pips" in results["results"]
        assert "vs_tuesday_rate" in results["results"]
        assert "vs_thursday_rate" in results["results"]
        assert "pass" in results
        assert isinstance(results["pass"], bool)
        assert "notes" in results
        assert "by_day" in results
        assert "methodology" in results


class TestQ3Integration:
    def test_results_format_with_real_data(self):
        from backtest.data_loader import CsvDataLoader

        data_dir = project_root / "data" / "forex" / "historical"
        eurusd_file = data_dir / "EURUSD_D1.csv"

        if not eurusd_file.exists():
            pytest.skip("EURUSD D1 data not available")

        loader = CsvDataLoader()
        bars = loader.load(str(eurusd_file))

        if len(bars) < 30:
            pytest.skip("Insufficient data")

        from scripts.backtest_q3_wednesday_reversal import analyze_reversals

        results = analyze_reversals(bars)
        assert results["question"] == "Q3"
        assert results["sample_size"] > 10
        assert 0 <= results["results"]["wednesday_reversal_rate"] <= 1.0
        assert results["results"]["avg_reversal_pips"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
