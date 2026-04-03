import os
import sqlite3
from pathlib import Path

import pandas as pd


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "forex" / "forex.db"


class ForexDBDataSource:
    """Loads candle data from the SQLite forex database.

    Returns DataFrames in the same format as ``features.load_csv`` so
    the rest of the ML pipeline (``build_feature_matrix``, etc.) works
    unchanged regardless of data origin.
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            env_path = os.environ.get("FOREX_DB_PATH")
            if env_path:
                db_path = Path(env_path)
            else:
                db_path = DEFAULT_DB_PATH

        self.db_path = Path(db_path)

        if not self.db_path.exists():
            raise FileNotFoundError(f"Forex DB not found at {self.db_path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def load_candles(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Load candles for *symbol* / *timeframe* and return a DataFrame
        compatible with ``features.load_csv`` output.

        Columns: ``date, open, high, low, close, volume`` — sorted by
        timestamp ascending.
        """
        conn = self._connect()
        try:
            query = """
                SELECT timestamp, open, high, low, close, volume
                FROM candles
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp ASC
            """
            rows = conn.execute(query, (symbol, timeframe)).fetchall()
        finally:
            conn.close()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame([dict(r) for r in rows])

        df["date"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.drop(columns=["timestamp"])
        df = df[["date", "open", "high", "low", "close", "volume"]]
        df = df.reset_index(drop=True)
        return df

    def list_symbols(self) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT symbol FROM candles ORDER BY symbol"
            ).fetchall()
        finally:
            conn.close()
        return [r["symbol"] for r in rows]

    def list_timeframes(self, symbol: str) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT timeframe FROM candles WHERE symbol = ? ORDER BY timeframe",
                (symbol,),
            ).fetchall()
        finally:
            conn.close()
        return [r["timeframe"] for r in rows]
