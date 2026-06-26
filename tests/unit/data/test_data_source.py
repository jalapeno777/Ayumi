import os
import sqlite3
import tempfile
import unittest
from datetime import timezone
from pathlib import Path

import pandas as pd
from ml.data_source import (
    CANDLE_COLUMNS,
    SQLiteCandleLoader,
    _resolve_db_path,
)


def _seed_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS candles (
            symbol     TEXT NOT NULL,
            timeframe  TEXT NOT NULL,
            timestamp  INTEGER NOT NULL,
            open       REAL,
            high       REAL,
            low        REAL,
            close      REAL,
            volume     REAL DEFAULT 0,
            PRIMARY KEY (symbol, timeframe, timestamp)
        );
    """)
    rows = [
        ("EURUSD", "M15", 1704067200, 1.1000, 1.1010, 1.0990, 1.1005, 100),
        ("EURUSD", "M15", 1704068100, 1.1005, 1.1015, 1.1000, 1.1010, 150),
        ("EURUSD", "M15", 1704069000, 1.1010, 1.1020, 1.1005, 1.1015, 120),
        ("GBPUSD", "H1", 1704067200, 1.2600, 1.2610, 1.2590, 1.2605, 200),
        ("GBPUSD", "H1", 1704070800, 1.2605, 1.2620, 1.2600, 1.2615, 180),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


class TestResolveDbPath(unittest.TestCase):
    def test_explicit_path_takes_priority(self):
        result = _resolve_db_path("/tmp/custom.db")
        self.assertEqual(result, Path("/tmp/custom.db"))

    def test_env_var_fallback(self):
        os.environ["FOREX_DB_PATH"] = "/tmp/from_env.db"
        try:
            result = _resolve_db_path()
            self.assertEqual(result, Path("/tmp/from_env.db"))
        finally:
            del os.environ["FOREX_DB_PATH"]

    def test_default_when_no_override(self):
        env_key = "FOREX_DB_PATH"
        saved = os.environ.pop(env_key, None)
        try:
            result = _resolve_db_path()
            self.assertEqual(result, Path("data/forex/forex.db"))
        finally:
            if saved is not None:
                os.environ[env_key] = saved


class TestSQLiteCandleLoaderLoadCandles(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.tmp_dir) / "test.db"
        _seed_db(self.db_path)
        self.loader = SQLiteCandleLoader(db_path=self.db_path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_load_returns_expected_columns(self):
        df = self.loader.load_candles("EURUSD", "M15")
        for col in CANDLE_COLUMNS:
            self.assertIn(col, df.columns)

    def test_load_returns_correct_row_count(self):
        df = self.loader.load_candles("EURUSD", "M15")
        self.assertEqual(len(df), 3)

    def test_load_sorted_by_timestamp(self):
        df = self.loader.load_candles("EURUSD", "M15")
        ts = df["timestamp"].tolist()
        self.assertEqual(ts, sorted(ts))

    def test_load_with_start_ts_filter(self):
        df = self.loader.load_candles("EURUSD", "M15", start_ts=1704068100)
        self.assertEqual(len(df), 2)
        self.assertTrue((df["timestamp"] >= 1704068100).all())

    def test_load_with_end_ts_filter(self):
        df = self.loader.load_candles("EURUSD", "M15", end_ts=1704068100)
        self.assertEqual(len(df), 2)
        self.assertTrue((df["timestamp"] <= 1704068100).all())

    def test_load_with_both_ts_filters(self):
        df = self.loader.load_candles(
            "EURUSD", "M15", start_ts=1704068100, end_ts=1704068100
        )
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["timestamp"], 1704068100)

    def test_load_empty_result_returns_correct_columns(self):
        df = self.loader.load_candles("JPYUSD", "D1")
        self.assertEqual(len(df), 0)
        for col in CANDLE_COLUMNS:
            self.assertIn(col, df.columns)

    def test_timestamp_column_is_int64(self):
        df = self.loader.load_candles("EURUSD", "M15")
        self.assertTrue(pd.api.types.is_integer_dtype(df["timestamp"]))

    def test_ohlcv_values_are_numeric(self):
        df = self.loader.load_candles("EURUSD", "M15")
        for col in ["open", "high", "low", "close", "volume"]:
            self.assertTrue(pd.api.types.is_numeric_dtype(df[col]))


class TestSQLiteCandleLoaderListSymbols(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.tmp_dir) / "test.db"
        _seed_db(self.db_path)
        self.loader = SQLiteCandleLoader(db_path=self.db_path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_returns_sorted_unique_symbols(self):
        symbols = self.loader.list_symbols()
        self.assertEqual(symbols, ["EURUSD", "GBPUSD"])


class TestSQLiteCandleLoaderListTimeframes(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.tmp_dir) / "test.db"
        _seed_db(self.db_path)
        self.loader = SQLiteCandleLoader(db_path=self.db_path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_all_timeframes_without_symbol_filter(self):
        tfs = self.loader.list_timeframes()
        self.assertIn("M15", tfs)
        self.assertIn("H1", tfs)

    def test_filtered_by_symbol(self):
        tfs = self.loader.list_timeframes(symbol="EURUSD")
        self.assertEqual(tfs, ["M15"])


class TestToOhlcv(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.tmp_dir) / "test.db"
        _seed_db(self.db_path)
        self.loader = SQLiteCandleLoader(db_path=self.db_path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_output_has_ohlcv_columns(self):
        candles = self.loader.load_candles("EURUSD", "M15")
        ohlcv = self.loader.to_ohlcv(candles)
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            self.assertIn(col, ohlcv.columns)

    def test_index_is_datetime_utc(self):
        candles = self.loader.load_candles("EURUSD", "M15")
        ohlcv = self.loader.to_ohlcv(candles)
        self.assertEqual(ohlcv.index.name, "timestamp")
        self.assertIsInstance(ohlcv.index, pd.DatetimeIndex)
        self.assertEqual(ohlcv.index.tz, timezone.utc)

    def test_index_sorted_ascending(self):
        candles = self.loader.load_candles("EURUSD", "M15")
        ohlcv = self.loader.to_ohlcv(candles)
        self.assertTrue(ohlcv.index.is_monotonic_increasing)

    def test_values_preserved(self):
        candles = self.loader.load_candles("EURUSD", "M15")
        ohlcv = self.loader.to_ohlcv(candles)
        self.assertAlmostEqual(ohlcv.iloc[0]["Open"], 1.1000)
        self.assertAlmostEqual(ohlcv.iloc[0]["Close"], 1.1005)

    def test_row_count_matches_input(self):
        candles = self.loader.load_candles("EURUSD", "M15")
        ohlcv = self.loader.to_ohlcv(candles)
        self.assertEqual(len(ohlcv), len(candles))


if __name__ == "__main__":
    unittest.main()
