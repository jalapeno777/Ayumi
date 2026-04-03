import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from ml.data_source import ForexDBDataSource
from ml.features import build_feature_matrix, load_csv


def _create_test_db(db_path: str, symbol: str = "EURUSD", timeframe: str = "H1",
                    n: int = 100, seed: int = 42):
    """Create a minimal forex.db with candle data for testing."""
    np.random.seed(seed)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
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
    base_ts = 1704067200
    price = 1.1000
    rows = []
    for i in range(n):
        price += np.random.normal(0, 0.0005)
        ts = base_ts + i * 3600
        rows.append((
            symbol, timeframe, ts,
            round(price - 0.0001, 5),
            round(price + np.random.uniform(0.0001, 0.0003), 5),
            round(price - np.random.uniform(0.0001, 0.0003), 5),
            round(price, 5),
            int(np.random.randint(100, 10000)),
        ))
    conn.executemany(
        "INSERT INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db_path


class TestForexDBDataSource:

    def test_load_candles_returns_correct_columns(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_test_db(db_path)
            ds = ForexDBDataSource(db_path)
            df = ds.load_candles("EURUSD", "H1")
            assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
            assert len(df) == 100
        finally:
            os.unlink(db_path)

    def test_load_candles_sorted_by_timestamp(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_test_db(db_path)
            ds = ForexDBDataSource(db_path)
            df = ds.load_candles("EURUSD", "H1")
            dates = df["date"].tolist()
            assert dates == sorted(dates)
        finally:
            os.unlink(db_path)

    def test_load_candles_date_is_datetime(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_test_db(db_path)
            ds = ForexDBDataSource(db_path)
            df = ds.load_candles("EURUSD", "H1")
            assert pd.api.types.is_datetime64_any_dtype(df["date"])
            assert df["date"].iloc[0].year == 2024
        finally:
            os.unlink(db_path)

    def test_load_candles_empty_for_unknown_symbol(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_test_db(db_path)
            ds = ForexDBDataSource(db_path)
            df = ds.load_candles("NZDJPY", "H1")
            assert len(df) == 0
        finally:
            os.unlink(db_path)

    def test_load_candles_empty_for_unknown_timeframe(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_test_db(db_path)
            ds = ForexDBDataSource(db_path)
            df = ds.load_candles("EURUSD", "M5")
            assert len(df) == 0
        finally:
            os.unlink(db_path)

    def test_list_symbols(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_test_db(db_path, symbol="GBPUSD")
            ds = ForexDBDataSource(db_path)
            symbols = ds.list_symbols()
            assert symbols == ["GBPUSD"]
        finally:
            os.unlink(db_path)

    def test_list_timeframes(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_test_db(db_path, timeframe="H4")
            ds = ForexDBDataSource(db_path)
            tfs = ds.list_timeframes("EURUSD")
            assert tfs == ["H4"]
        finally:
            os.unlink(db_path)

    def test_file_not_found_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = os.path.join(tmpdir, "nonexistent.db")
            try:
                ForexDBDataSource(bad_path)
                assert False, "Expected FileNotFoundError"
            except FileNotFoundError:
                pass

    def test_env_var_db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_test_db(db_path)
            old = os.environ.get("FOREX_DB_PATH")
            os.environ["FOREX_DB_PATH"] = db_path
            try:
                ds = ForexDBDataSource()
                assert ds.db_path == Path(db_path)
                df = ds.load_candles("EURUSD", "H1")
                assert len(df) == 100
            finally:
                if old is not None:
                    os.environ["FOREX_DB_PATH"] = old
                else:
                    os.environ.pop("FOREX_DB_PATH", None)
        finally:
            os.unlink(db_path)


class TestDBDataSourcePipelineCompatibility:

    def test_build_feature_matrix_with_db_data(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_test_db(db_path, n=300)
            ds = ForexDBDataSource(db_path)
            df = ds.load_candles("EURUSD", "H1")
            features = build_feature_matrix(df)
            assert len(features) == 300
            assert "rsi" in features.columns
            assert "atr_14" in features.columns
            assert "bb_pct_b" in features.columns
            assert "killzone_london" in features.columns
        finally:
            os.unlink(db_path)

    def test_db_and_csv_produce_same_feature_columns(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_test_db(db_path, n=300)
            ds = ForexDBDataSource(db_path)
            db_df = ds.load_candles("EURUSD", "H1")

            csv_path = os.path.join(os.path.dirname(__file__), "..", "data",
                                    "forex", "historical", "EURUSD_H1.csv")
            if not os.path.exists(csv_path):
                return

            csv_df = load_csv(csv_path)

            db_features = build_feature_matrix(db_df)
            csv_features = build_feature_matrix(csv_df)

            db_cols = set(db_features.columns)
            csv_cols = set(csv_features.columns)
            assert db_cols == csv_cols, f"Column mismatch: DB has {db_cols - csv_cols}, CSV has {csv_cols - db_cols}"
        finally:
            os.unlink(db_path)
