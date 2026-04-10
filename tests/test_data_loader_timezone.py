import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from backtest.data_loader import (
    CsvDataLoader,
    _detect_est_timezone,
    _est_dst_end,
    _est_dst_start,
    _est_to_utc,
)


class TestEstToUtc(unittest.TestCase):
    def test_est_offset_winter(self):
        dt = datetime(2023, 1, 15, 12, 0)
        result = _est_to_utc(dt)
        self.assertEqual(result, datetime(2023, 1, 15, 17, 0))

    def test_edt_offset_summer(self):
        dt = datetime(2023, 7, 15, 12, 0)
        result = _est_to_utc(dt)
        self.assertEqual(result, datetime(2023, 7, 15, 16, 0))

    def test_dst_transition_start(self):
        dt = datetime(2023, 3, 12, 3, 0)
        result = _est_to_utc(dt)
        self.assertEqual(result, datetime(2023, 3, 12, 7, 0))

    def test_dst_transition_end_before_switch(self):
        dt = datetime(2023, 11, 5, 1, 0)
        result = _est_to_utc(dt)
        self.assertEqual(result, datetime(2023, 11, 5, 5, 0))

    def test_dst_transition_end_after_switch(self):
        dt = datetime(2023, 11, 5, 3, 0)
        result = _est_to_utc(dt)
        self.assertEqual(result, datetime(2023, 11, 5, 8, 0))

    def test_midnight_est(self):
        dt = datetime(2023, 2, 1, 0, 0)
        result = _est_to_utc(dt)
        self.assertEqual(result, datetime(2023, 2, 1, 5, 0))

    def test_forex_sunday_open_est(self):
        dt = datetime(2023, 1, 1, 17, 0)
        result = _est_to_utc(dt)
        self.assertEqual(result, datetime(2023, 1, 1, 22, 0))


class TestDetectEstTimezone(unittest.TestCase):
    def test_sunday_17pm_detected(self):
        self.assertTrue(_detect_est_timezone(datetime(2023, 1, 1, 17, 0)))

    def test_sunday_18pm_detected(self):
        self.assertTrue(_detect_est_timezone(datetime(2023, 1, 1, 18, 0)))

    def test_sunday_16pm_detected(self):
        self.assertTrue(_detect_est_timezone(datetime(2023, 1, 1, 16, 0)))

    def test_monday_17pm_detected(self):
        self.assertTrue(_detect_est_timezone(datetime(2023, 1, 2, 17, 0)))

    def test_midnight_not_detected(self):
        self.assertFalse(_detect_est_timezone(datetime(2023, 1, 1, 0, 0)))

    def test_utc_22_not_detected(self):
        self.assertFalse(_detect_est_timezone(datetime(2023, 1, 1, 22, 0)))


class TestDstBoundaries(unittest.TestCase):
    def test_dst_start_2023(self):
        start = _est_dst_start(2023)
        self.assertEqual(start, datetime(2023, 3, 12, 2, 0))

    def test_dst_end_2023(self):
        end = _est_dst_end(2023)
        self.assertEqual(end, datetime(2023, 11, 5, 2, 0))

    def test_dst_start_2024(self):
        start = _est_dst_start(2024)
        self.assertEqual(start, datetime(2024, 3, 10, 2, 0))

    def test_dst_end_2024(self):
        end = _est_dst_end(2024)
        self.assertEqual(end, datetime(2024, 11, 3, 2, 0))


class TestCsvDataLoaderTimezone(unittest.TestCase):
    def test_explicit_est_timezone(self):
        loader = CsvDataLoader(source_timezone="est")
        csv = "Date,Open,High,Low,Close,Volume\n2023-01-01 17:00,1.0697,1.07066,1.06788,1.06929,0\n"
        bars = loader.load_from_string(csv)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].time, datetime(2023, 1, 1, 22, 0))

    def test_auto_detect_est_from_sunday_17(self):
        loader = CsvDataLoader()
        csv = "Date,Open,High,Low,Close,Volume\n2023-01-01 17:00,1.0697,1.07066,1.06788,1.06929,0\n2023-01-01 18:00,1.06896,1.07047,1.06829,1.07005,0\n"
        bars = loader.load_from_string(csv)
        self.assertEqual(loader.source_timezone, "est")
        self.assertEqual(bars[0].time, datetime(2023, 1, 1, 22, 0))
        self.assertEqual(bars[1].time, datetime(2023, 1, 1, 23, 0))

    def test_no_timezone_when_utc_data(self):
        loader = CsvDataLoader()
        csv = "Date,Open,High,Low,Close,Volume\n2023-01-02 08:00,1.0697,1.07066,1.06788,1.06929,0\n"
        bars = loader.load_from_string(csv)
        self.assertIsNone(loader.source_timezone)
        self.assertEqual(bars[0].time, datetime(2023, 1, 2, 8, 0))

    def test_none_timezone_no_conversion(self):
        loader = CsvDataLoader(source_timezone=None)
        csv = "Date,Open,High,Low,Close,Volume\n2023-01-01 17:00,1.0697,1.07066,1.06788,1.06929,0\n"
        bars = loader.load_from_string(csv)
        self.assertEqual(bars[0].time, datetime(2023, 1, 1, 17, 0))

    def test_est_summer_time_conversion(self):
        loader = CsvDataLoader(source_timezone="est")
        csv = "Date,Open,High,Low,Close,Volume\n2023-07-10 08:00,1.1000,1.1005,1.0995,1.1002,0\n"
        bars = loader.load_from_string(csv)
        self.assertEqual(bars[0].time, datetime(2023, 7, 10, 12, 0))

    def test_load_file_auto_detects_est(self):
        loader = CsvDataLoader()
        csv_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "data",
            "forex",
            "historical",
            "EURUSD_H1.csv",
        )
        if not os.path.exists(csv_path):
            self.skipTest(f"EURUSD H1 data not found at {csv_path}")
        bars = loader.load(csv_path)
        self.assertGreater(len(bars), 100)
        self.assertEqual(loader.source_timezone, "est")
        first_bar = bars[0]
        self.assertEqual(first_bar.time, datetime(2023, 1, 1, 22, 0))

    def test_infer_timeframe_unchanged(self):
        loader = CsvDataLoader(source_timezone="est")
        csv = (
            "Date,Open,High,Low,Close,Volume\n"
            "2023-01-01 17:00,1.0697,1.07066,1.06788,1.06929,0\n"
            "2023-01-01 18:00,1.06896,1.07047,1.06829,1.07005,0\n"
            "2023-01-01 19:00,1.07007,1.07058,1.06912,1.0704,0\n"
        )
        bars = loader.load_from_string(csv)
        tf = loader.infer_timeframe(bars)
        self.assertEqual(tf.minutes, 60)


if __name__ == "__main__":
    unittest.main()
