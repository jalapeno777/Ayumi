from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar
from backtest.wednesday_reversal import (
    DayReversalStats,
    WednesdayReversalStudy,
)


def _bar(
    date: datetime,
    o: float = 1.0,
    h: float = 1.01,
    low: float = 0.99,
    c: float = 1.005,
    v: int = 1000,
) -> Bar:
    return Bar(time=date, open=o, high=h, low=low, close=c, volume=v)


def _eurusd_bar(date: datetime, close: float) -> Bar:
    return Bar(
        time=date,
        open=close - 0.0005,
        high=close + 0.001,
        low=close - 0.001,
        close=close,
        volume=1000,
    )


def _usdjpy_bar(date: datetime, close: float) -> Bar:
    return Bar(
        time=date,
        open=close - 0.05,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=1000,
    )


class TestDayReversalStats(unittest.TestCase):
    def test_to_dict(self):
        stats = DayReversalStats(total=10, reversals=5, rate=0.5, avg_pips=75.0)
        d = stats.to_dict()
        self.assertEqual(d["total"], 10)
        self.assertEqual(d["reversals"], 5)
        self.assertEqual(d["rate"], 0.5)
        self.assertEqual(d["avg_pips"], 75.0)

    def test_frozen(self):
        stats = DayReversalStats(total=1, reversals=0, rate=0.0, avg_pips=0.0)
        with self.assertRaises(AttributeError):
            stats.total = 5


class TestWednesdayReversalStudyInit(unittest.TestCase):
    def test_default_instrument(self):
        study = WednesdayReversalStudy()
        self.assertEqual(study.instrument, "EURUSD")
        self.assertEqual(study.timeframe, "D1")
        self.assertEqual(study.question_id, "Q3")

    def test_custom_instrument(self):
        study = WednesdayReversalStudy(instrument="GBPUSD")
        self.assertEqual(study.instrument, "GBPUSD")

    def test_custom_threshold(self):
        study = WednesdayReversalStudy(min_reversal_pips=30)
        self.assertEqual(study.min_reversal_pips, 30)

    def test_go_nogo_criteria(self):
        study = WednesdayReversalStudy()
        self.assertEqual(len(study.go_nogo_criteria), 1)
        self.assertEqual(study.go_nogo_criteria[0].metric, "wednesday_reversal_rate")
        self.assertEqual(study.go_nogo_criteria[0].threshold, 0.50)


class TestWednesdayReversalStudyAnalyze(unittest.TestCase):
    def test_empty_bars(self):
        study = WednesdayReversalStudy()
        result = study.run([])
        self.assertFalse(result.go_nogo)
        self.assertEqual(result.sample_size, 0)

    def test_single_bar(self):
        study = WednesdayReversalStudy()
        bar = _eurusd_bar(datetime(2025, 10, 1), 1.1000)
        result = study.run([bar])
        self.assertEqual(result.sample_size, 0)

    def test_all_wednesdays_reversal_passes(self):
        study = WednesdayReversalStudy()
        bars = []
        base = datetime(2025, 10, 6)
        for i in range(6):
            date = base + timedelta(days=i)
            close = 1.1000 + (i * 0.01)
            bars.append(_eurusd_bar(date, close))

        result = study.run(bars)
        self.assertTrue(result.go_nogo)
        self.assertGreater(result.results["wednesday_reversal_rate"], 0)

    def test_no_wednesdays_in_range(self):
        study = WednesdayReversalStudy()
        bars = [
            _eurusd_bar(datetime(2025, 10, 6), 1.1000),
            _eurusd_bar(datetime(2025, 10, 7), 1.1100),
        ]
        result = study.run(bars)
        self.assertEqual(result.sample_size, 0)

    def test_wednesday_small_move_below_threshold(self):
        study = WednesdayReversalStudy(min_reversal_pips=100)
        bars = [
            _eurusd_bar(datetime(2025, 10, 7), 1.1000),
            _eurusd_bar(datetime(2025, 10, 8), 1.1002),
        ]
        result = study.run(bars)
        self.assertEqual(result.results["wednesday"]["reversals"], 0)
        self.assertEqual(result.results["wednesday_reversal_rate"], 0.0)

    def test_wednesday_large_move_above_threshold(self):
        study = WednesdayReversalStudy(min_reversal_pips=50)
        bars = [
            _eurusd_bar(datetime(2025, 10, 7), 1.1000),
            _eurusd_bar(datetime(2025, 10, 8), 1.1100),
        ]
        result = study.run(bars)
        self.assertEqual(result.results["wednesday"]["reversals"], 1)
        self.assertGreater(result.results["wednesday_reversal_rate"], 0.5)

    def test_tuesday_and_thursday_computed(self):
        study = WednesdayReversalStudy()
        bars = [
            _eurusd_bar(datetime(2025, 10, 6), 1.1000),
            _eurusd_bar(datetime(2025, 10, 7), 1.1200),
            _eurusd_bar(datetime(2025, 10, 8), 1.1300),
            _eurusd_bar(datetime(2025, 10, 9), 1.1500),
        ]
        result = study.run(bars)
        self.assertIn("tuesday", result.results)
        self.assertIn("thursday", result.results)
        self.assertIn("vs_tuesday_rate", result.results)
        self.assertIn("vs_thursday_rate", result.results)

    def test_usdjpy_pip_calculation(self):
        study = WednesdayReversalStudy(instrument="USDJPY", min_reversal_pips=50)
        bars = [
            _usdjpy_bar(datetime(2025, 10, 7), 150.00),
            _usdjpy_bar(datetime(2025, 10, 8), 151.00),
        ]
        result = study.run(bars)
        move_pips = abs(151.00 - 150.00) / 0.01
        self.assertEqual(move_pips, 100)
        self.assertEqual(result.results["wednesday"]["reversals"], 1)

    def test_weekend_gap_skipped(self):
        study = WednesdayReversalStudy()
        bars = [
            _eurusd_bar(datetime(2025, 10, 3), 1.1000),
            _eurusd_bar(datetime(2025, 10, 8), 1.1200),
        ]
        result = study.run(bars)
        self.assertEqual(result.results["wednesday"]["reversals"], 0)
        self.assertEqual(result.results["wednesday"]["total"], 0)

    def test_multiple_weeks(self):
        study = WednesdayReversalStudy()
        bars = []
        week_start = datetime(2025, 10, 6)
        for week in range(4):
            base = week_start + timedelta(weeks=week)
            bars.append(_eurusd_bar(base, 1.1000 + week * 0.01))
            bars.append(_eurusd_bar(base + timedelta(days=1), 1.1000 + week * 0.01))
            bars.append(_eurusd_bar(base + timedelta(days=2), 1.1000 + week * 0.01))
            bars.append(_eurusd_bar(base + timedelta(days=3), 1.1000 + week * 0.01))
            bars.append(_eurusd_bar(base + timedelta(days=4), 1.1000 + week * 0.01))

        result = study.run(bars)
        self.assertEqual(result.results["wednesday"]["total"], 4)

    def test_date_range_filtering(self):
        study = WednesdayReversalStudy()
        bars = [
            _eurusd_bar(datetime(2025, 9, 1), 1.1000),
            _eurusd_bar(datetime(2025, 9, 2), 1.1000),
            _eurusd_bar(datetime(2025, 9, 3), 1.1200),
            _eurusd_bar(datetime(2025, 10, 7), 1.1000),
            _eurusd_bar(datetime(2025, 10, 8), 1.1300),
        ]
        filtered = study.filter_by_date_range(
            bars,
            datetime(2025, 10, 1),
            datetime(2025, 10, 31),
        )
        result = study.run(filtered)
        self.assertEqual(result.results["wednesday"]["total"], 1)

    def test_avg_reversal_pips(self):
        study = WednesdayReversalStudy(min_reversal_pips=50)
        bars = [
            _eurusd_bar(datetime(2025, 10, 7), 1.1000),
            _eurusd_bar(datetime(2025, 10, 8), 1.1100),
        ]
        result = study.run(bars)
        expected_pips = abs(1.1100 - 1.1000) / 0.0001
        self.assertAlmostEqual(result.results["avg_reversal_pips"], expected_pips, places=1)


class TestWednesdayReversalStudyMultiInstrument(unittest.TestCase):
    def test_multi_instrument(self):
        study = WednesdayReversalStudy()
        instruments = {
            "EURUSD": [
                _eurusd_bar(datetime(2025, 10, 7), 1.1000),
                _eurusd_bar(datetime(2025, 10, 8), 1.1200),
            ],
            "GBPUSD": [
                _bar(datetime(2025, 10, 7), c=1.3000, h=1.3050, low=1.2950),
                _bar(datetime(2025, 10, 8), c=1.3200, h=1.3250, low=1.3150),
            ],
        }
        results = study.run_multi_instrument(
            instruments,
            datetime(2025, 10, 1),
            datetime(2025, 10, 31),
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].instrument, "EURUSD")
        self.assertEqual(results[1].instrument, "GBPUSD")

    def test_empty_instrument(self):
        study = WednesdayReversalStudy()
        results = study.run_multi_instrument(
            {"EURUSD": []},
            datetime(2025, 10, 1),
            datetime(2025, 10, 31),
        )
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].go_nogo)


class TestWednesdayReversalStudyFormatSummary(unittest.TestCase):
    def test_format_summary(self):
        study = WednesdayReversalStudy()
        result = study.run([
            _eurusd_bar(datetime(2025, 10, 7), 1.1000),
            _eurusd_bar(datetime(2025, 10, 8), 1.1200),
        ])
        summary = study.format_summary([result])
        self.assertIn("EURUSD", summary)
        self.assertIn("Wednesday", summary)
        self.assertIn("PASS", summary)


class TestWednesdayReversalStudyToDict(unittest.TestCase):
    def test_result_to_dict_has_required_fields(self):
        study = WednesdayReversalStudy()
        bars = [
            _eurusd_bar(datetime(2025, 10, 7), 1.1000),
            _eurusd_bar(datetime(2025, 10, 8), 1.1200),
        ]
        result = study.run(bars)
        d = result.to_dict()
        self.assertEqual(d["question"], "Q3")
        self.assertEqual(d["timeframe"], "D1")
        self.assertIn("test_period", d)
        self.assertIn("results", d)
        self.assertIn("pass", d)
        self.assertIn("criteria", d)
        self.assertIn("notes", d)

    def test_result_to_json_valid(self):
        import json

        study = WednesdayReversalStudy()
        bars = [
            _eurusd_bar(datetime(2025, 10, 7), 1.1000),
            _eurusd_bar(datetime(2025, 10, 8), 1.1200),
        ]
        result = study.run(bars)
        json_str = result.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["question"], "Q3")
