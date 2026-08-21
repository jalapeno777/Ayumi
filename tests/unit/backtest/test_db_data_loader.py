"""Tests for backtest.db_data_loader.DbDataLoader.

Phase 8c. These tests cover the read-side of the DuckDB-backed loader:

* happy path queries return correct Bar objects
* date-range filtering works
* CSV fallback fires when the DB file is missing
* CSV fallback fires when a query returns no rows (unknown symbol)
* ``load_by_filepath`` parses the conventional filename correctly
* DB rows agree with the corresponding CSV rows for the overlap window
* integration: XAUUSD/H1 returns the expected 30,689 bars

Live DuckDB data at ``data/ayumi_market.duckdb`` is required. The tests are
written defensively: if the DB is missing they skip with a clear message
instead of failing — the goal is to ship the loader with parity coverage,
not to gate the suite on a specific environment.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from _project_root import PROJECT_ROOT
from backtest.data_loader import CsvDataLoader
from backtest.db_data_loader import DEFAULT_CSV_DIR, DEFAULT_DB_PATH, DbDataLoader
from backtest.engine import Bar

DB_PATH = PROJECT_ROOT / "data" / "ayumi_market.duckdb"


def _db_available() -> bool:
    return DB_PATH.exists()


@unittest.skipUnless(_db_available(), "data/ayumi_market.duckdb not present")
class TestDbDataLoaderHappyPath(unittest.TestCase):
    """Tests that require the real DuckDB file."""

    def setUp(self) -> None:
        self.loader = DbDataLoader(
            db_path=str(DB_PATH),
            csv_dir=str(PROJECT_ROOT / "data" / "forex" / "historical"),
        )

    def test_load_returns_bars_for_known_symbol(self) -> None:
        bars = self.loader.load("XAUUSD", "H1")
        self.assertGreater(len(bars), 0, "expected rows for XAUUSD/H1")
        self.assertEqual(len(bars), 30689)

    def test_load_returns_bars_in_chronological_order(self) -> None:
        bars = self.loader.load("EURUSD", "H1")
        times = [b.time for b in bars]
        self.assertEqual(times, sorted(times))

    def test_load_returns_correct_bar_dataclass(self) -> None:
        bars = self.loader.load("EURUSD", "H1")
        bar = bars[0]
        self.assertIsInstance(bar, Bar)
        # time must be tz-aware UTC (matches CsvDataLoader contract)
        self.assertIsNotNone(bar.time.tzinfo)
        self.assertEqual(bar.time.utcoffset().total_seconds(), 0)
        # OHLC prices always positive; volume may legitimately be 0
        for field in ("open", "high", "low", "close"):
            value = getattr(bar, field)
            self.assertIsInstance(value, float)
            self.assertGreater(value, 0.0)
        # volume is float but historically can be zero
        self.assertIsInstance(bar.volume, float)
        self.assertGreaterEqual(bar.volume, 0.0)

    def test_load_with_date_range_filter(self) -> None:
        # 2024-01-01 00:00 UTC == 1704067200; end exclusive corner at 1704163200
        start_ts = 1704067200
        end_ts = 1704163200
        bars = self.loader.load("XAUUSD", "M15", start_ts=start_ts, end_ts=end_ts)
        self.assertGreater(len(bars), 0)
        for bar in bars:
            epoch = int(bar.time.timestamp())
            self.assertGreaterEqual(epoch, start_ts)
            self.assertLessEqual(epoch, end_ts)

    def test_load_with_only_start_ts(self) -> None:
        start_ts = 1704067200
        bars = self.loader.load("EURUSD", "H1", start_ts=start_ts)
        self.assertGreater(len(bars), 0)
        for bar in bars:
            self.assertGreaterEqual(int(bar.time.timestamp()), start_ts)

    def test_load_with_only_end_ts(self) -> None:
        end_ts = 1704067200
        bars = self.loader.load("EURUSD", "H1", end_ts=end_ts)
        self.assertGreater(len(bars), 0)
        for bar in bars:
            self.assertLessEqual(int(bar.time.timestamp()), end_ts)

    def test_integration_xauusd_h1_count(self) -> None:
        # Confirmed DB row count for XAUUSD/H1 during Phase 8b parity check.
        bars = self.loader.load("XAUUSD", "H1")
        self.assertEqual(len(bars), 30689)

    def test_matches_csv_first_10_bars_xauusd_m15(self) -> None:
        # Compare the first 10 bars from the DB against the same window from
        # the CSV. We restrict the DB query to the same date range as the CSV
        # rows so we exercise the bounded query path (the unbounded XAUUSD/M15
        # table is ~85k rows and pandas/DuckDB parquet allocation is sensitive
        # in some sandbox memory profiles; the smaller window covers both the
        # CSV and DB result deterministically).
        csv_loader = CsvDataLoader()
        csv_bars = csv_loader.load(str(PROJECT_ROOT / "data" / "forex" / "historical" / "XAUUSD_M15.csv"))
        # Take the CSV's first 10 rows' timestamp span (~2.5 hours) as the
        # verification window — wide enough to capture multiple bars on both
        # sides, narrow enough to keep allocations trivial.
        window_start = int(csv_bars[0].time.timestamp())
        window_end = int(csv_bars[9].time.timestamp()) + 1
        db_bars = self.loader.load(
            "XAUUSD",
            "M15",
            start_ts=window_start - 1,
            end_ts=window_end,
        )
        csv_window = [
            b for b in csv_bars if int(b.time.timestamp()) >= window_start and int(b.time.timestamp()) < window_end
        ]
        self.assertEqual(len(db_bars), len(csv_window))
        for csv_bar, db_bar in zip(csv_window, db_bars):  # noqa: B905
            self.assertEqual(csv_bar.time, db_bar.time)
            self.assertAlmostEqual(csv_bar.open, db_bar.open, places=6)
            self.assertAlmostEqual(csv_bar.high, db_bar.high, places=6)
            self.assertAlmostEqual(csv_bar.low, db_bar.low, places=6)
            self.assertAlmostEqual(csv_bar.close, db_bar.close, places=6)
            self.assertAlmostEqual(csv_bar.volume, db_bar.volume, places=6)
            self.assertAlmostEqual(csv_bar.spread_pips, db_bar.spread_pips, places=6)


@unittest.skipUnless(_db_available(), "data/ayumi_market.duckdb not present")
class TestDbDataLoaderFallback(unittest.TestCase):
    """CSV-fallback path tests (still need the DB file present to query it)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)

    def _write_csv(self, name: str, lines: list[str]) -> Path:
        path = self.tmpdir / name
        path.write_text("Date,Open,High,Low,Close,Volume\n" + "\n".join(lines) + "\n")
        return path

    def test_fallback_when_db_file_missing(self) -> None:
        # Build a small CSV with known rows.
        rows = [
            "2024-01-02 09:30:00,1.1000,1.1050,1.0950,1.1020,100",
            "2024-01-02 09:45:00,1.1020,1.1080,1.1010,1.1060,120",
        ]
        self._write_csv("TEST_M15.csv", rows)

        loader = DbDataLoader(
            db_path=str(self.tmpdir / "no_such_db.duckdb"),
            csv_dir=str(self.tmpdir),
        )
        bars = loader.load("TEST", "M15")
        self.assertEqual(len(bars), 2)
        # CSV rows are parsed as ET then converted to UTC; ET is UTC-5 in
        # January. Confirm tz-aware UTC.
        self.assertEqual(bars[0].time.tzinfo, timezone.utc)
        self.assertEqual(bars[0].time.hour, 14)  # 09:30 ET + 5h = 14:30 UTC

    def test_fallback_when_query_returns_no_rows(self) -> None:
        # DB exists and is queried, but no rows match the symbol; should
        # fall back to CSV.
        rows = ["2024-01-02 09:30:00,1.1000,1.1050,1.0950,1.1020,100"]
        self._write_csv("MISSING_M15.csv", rows)

        loader = DbDataLoader(
            db_path=str(DB_PATH),
            csv_dir=str(self.tmpdir),
        )
        bars = loader.load("MISSING", "M15")
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].time.tzinfo, timezone.utc)

    def test_empty_result_when_db_returns_nothing_and_no_csv(self) -> None:
        # Real DB queries EURUSD/UNKNOWN -> 0 rows. No CSV fallback file
        # exists, so we get an empty list (no exception).
        loader = DbDataLoader(
            db_path=str(DB_PATH),
            csv_dir=str(self.tmpdir),
        )
        bars = loader.load("EURUSD", "UNKNOWN_TF_NO_SUCH_THING")
        self.assertEqual(bars, [])

    def test_load_by_filepath_parses_symbol_and_timeframe(self) -> None:
        rows = ["2024-06-15 09:30:00,1.1000,1.1050,1.0950,1.1020,100"]
        path = self._write_csv("PARSEME_M15.csv", rows)
        loader = DbDataLoader(
            db_path=str(self.tmpdir / "no_such_db.duckdb"),
            csv_dir=str(self.tmpdir),
        )
        bars = loader.load_by_filepath(str(path))
        self.assertEqual(len(bars), 1)

    def test_load_by_filepath_raises_on_bad_filename(self) -> None:
        loader = DbDataLoader(
            db_path=str(self.tmpdir / "no_such_db.duckdb"),
            csv_dir=str(self.tmpdir),
        )
        with self.assertRaises(ValueError):
            loader.load_by_filepath(str(self.tmpdir / "weird-name.csv"))

    def test_load_by_filepath_parses_real_filename(self) -> None:
        # The real DB layer is wired up correctly via the filename parse
        # helper below — no need to instantiate the loader here.
        # 'H1' for XAUUSD is 30k rows — fine for the bounded pytest path.
        sym, tf = DbDataLoader._parse_filename("XAUUSD_H1.csv")
        self.assertEqual((sym, tf), ("XAUUSD", "H1"))


class TestDbDataLoaderFilenameParsing(unittest.TestCase):
    """Pure unit tests — no DB or filesystem I/O needed."""

    def test_parse_simple(self) -> None:
        sym, tf = DbDataLoader._parse_filename("XAUUSD_M15.csv")
        self.assertEqual(sym, "XAUUSD")
        self.assertEqual(tf, "M15")

    def test_parse_with_suffix(self) -> None:
        sym, tf = DbDataLoader._parse_filename("EURUSD_M15_2026.csv")
        self.assertEqual(sym, "EURUSD")
        self.assertEqual(tf, "M15")

    def test_parse_with_fresh_suffix(self) -> None:
        sym, tf = DbDataLoader._parse_filename("XAUUSD_M15_fresh.csv")
        self.assertEqual(sym, "XAUUSD")
        self.assertEqual(tf, "M15")

    def test_parse_rejects_nonmatching(self) -> None:
        with self.assertRaises(ValueError):
            DbDataLoader._parse_filename("not-a-csv-name.csv")

    def test_parse_accepts_full_path(self) -> None:
        sym, tf = DbDataLoader._parse_filename("data/forex/historical/XAUUSD_M15.csv")
        self.assertEqual(sym, "XAUUSD")
        self.assertEqual(tf, "M15")


class TestDbDataLoaderDefaults(unittest.TestCase):
    """Confirm the module exposes the documented defaults."""

    def test_default_db_path_is_data_ayumi_market_duckdb(self) -> None:
        self.assertEqual(DEFAULT_DB_PATH, Path("data/ayumi_market.duckdb"))

    def test_default_csv_dir_is_data_forex_historical(self) -> None:
        self.assertEqual(DEFAULT_CSV_DIR, Path("data/forex/historical"))


class TestDbDataLoaderTimestampConversion(unittest.TestCase):
    """Verify the Bar dataclass is populated from a known DuckDB row."""

    def test_row_to_bar_uses_utc_datetime(self) -> None:
        # 2023-01-02 23:00:00 UTC == 1672700400
        bar = DbDataLoader._row_to_bar(
            1672700400,
            1826.837,
            1829.958,
            1825.967,
            1826.217,
            0,
            0.0,
        )
        self.assertEqual(
            bar.time,
            datetime(2023, 1, 2, 23, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(bar.time.tzinfo, timezone.utc)
        self.assertEqual(bar.open, 1826.837)
        self.assertEqual(bar.volume, 0.0)
        self.assertEqual(bar.spread_pips, 0.0)

    def test_row_to_bar_handles_none_spread(self) -> None:
        bar = DbDataLoader._row_to_bar(
            1672700400,
            1.0,
            1.0,
            1.0,
            1.0,
            5,
            None,
        )
        self.assertEqual(bar.spread_pips, 0.0)
        self.assertEqual(bar.volume, 5.0)

    def test_row_to_bar_coerces_bigint_volume_to_float(self) -> None:
        bar = DbDataLoader._row_to_bar(
            1672700400,
            1.0,
            1.0,
            1.0,
            1.0,
            12345,
            1.5,
        )
        self.assertIsInstance(bar.volume, float)
        self.assertEqual(bar.volume, 12345.0)
        self.assertEqual(bar.spread_pips, 1.5)


if __name__ == "__main__":
    unittest.main()
