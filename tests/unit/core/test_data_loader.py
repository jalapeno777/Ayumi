import os
import tempfile
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backtest.data_loader import CsvDataLoader, _parse_csv_timestamp
from backtest.engine import SessionType, determine_session


class TestParseCsvTimestamp(unittest.TestCase):
    def test_winter_est_converts_to_utc(self):
        dt = _parse_csv_timestamp("2024-01-01 17:00")
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 22)
        self.assertEqual(dt.day, 1)

    def test_summer_edt_converts_to_utc(self):
        dt = _parse_csv_timestamp("2024-07-01 09:00")
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 13)

    def test_midnight_est(self):
        dt = _parse_csv_timestamp("2024-01-01 00:00")
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 5)

    def test_dst_boundary_spring_forward(self):
        dt_before = _parse_csv_timestamp("2024-03-10 01:59")
        dt_after = _parse_csv_timestamp("2024-03-10 03:00")
        self.assertGreater(dt_after, dt_before)


class TestCsvDataLoader(unittest.TestCase):
    def setUp(self):
        self.loader = CsvDataLoader()

    def test_load_from_string_produces_utc_bars(self):
        csv = "Date,Open,High,Low,Close,Volume\n2024-01-01 17:00,1.0697,1.07066,1.06788,1.06929,100\n"
        bars = self.loader.load_from_string(csv)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].time.tzinfo, timezone.utc)

    def test_load_from_file_produces_utc_bars(self):
        csv = "Date,Open,High,Low,Close,Volume\n2024-01-01 17:00,1.0697,1.07066,1.06788,1.06929,100\n2024-01-01 18:00,1.06896,1.07047,1.06829,1.07005,200\n"  # noqa: E501
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            bars = self.loader.load(f.name)
            os.unlink(f.name)

        self.assertEqual(len(bars), 2)
        for bar in bars:
            self.assertEqual(bar.time.tzinfo, timezone.utc)

    def test_infer_timeframe_with_utc_bars(self):
        csv = "Date,Open,High,Low,Close,Volume\n"
        csv += "2024-01-01 17:00,1.0,1.01,0.99,1.005,100\n"
        csv += "2024-01-01 18:00,1.0,1.01,0.99,1.005,100\n"
        bars = self.loader.load_from_string(csv)
        tf = self.loader.infer_timeframe(bars)
        self.assertEqual(tf.minutes, 60)

    def test_est_bar_correct_session(self):
        csv = "Date,Open,High,Low,Close,Volume\n2024-01-01 03:00,1.0,1.01,0.99,1.005,100\n"
        bars = self.loader.load_from_string(csv)
        session = determine_session(bars[0].time)
        self.assertEqual(session, SessionType.LONDON)

    def test_est_ny_am_bar_correct_session(self):
        csv = "Date,Open,High,Low,Close,Volume\n2024-01-01 07:00,1.0,1.01,0.99,1.005,100\n"
        bars = self.loader.load_from_string(csv)
        session = determine_session(bars[0].time)
        self.assertEqual(session, SessionType.NY_AM)


class TestDetermineSession(unittest.TestCase):
    def test_asian_session(self):
        dt = datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(determine_session(dt), SessionType.ASIAN)

    def test_london_session(self):
        dt = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(determine_session(dt), SessionType.LONDON)

    def test_ny_am_session(self):
        dt = datetime(2024, 1, 1, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(determine_session(dt), SessionType.NY_AM)

    def test_ny_pm_session(self):
        dt = datetime(2024, 1, 1, 17, 0, tzinfo=timezone.utc)
        self.assertEqual(determine_session(dt), SessionType.NY_PM)

    def test_outside_session(self):
        dt = datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc)
        self.assertEqual(determine_session(dt), SessionType.OUTSIDE)

    def test_naive_datetime_still_works(self):
        dt = datetime(2024, 1, 1, 9, 0)
        self.assertEqual(determine_session(dt), SessionType.LONDON)

    def test_non_utc_tz_converts(self):
        est = datetime(2024, 1, 1, 4, 0, tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(determine_session(est), SessionType.LONDON)

    def test_asian_boundary_start(self):
        dt = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(determine_session(dt), SessionType.ASIAN)

    def test_asian_boundary_end(self):
        dt = datetime(2024, 1, 1, 5, 59, tzinfo=timezone.utc)
        self.assertEqual(determine_session(dt), SessionType.ASIAN)


if __name__ == "__main__":
    unittest.main()
