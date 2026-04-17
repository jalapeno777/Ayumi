"""Historical forex data download using yfinance."""
import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf


PAIR_TICKER_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
}

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"


def download_forex_data(
    pair: str,
    interval: str = "1d",
    period: str = "2y",
    cache: bool = True,
) -> pd.DataFrame:
    ticker = PAIR_TICKER_MAP.get(pair)
    if not ticker:
        raise ValueError(f"Unknown pair: {pair}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / f"{pair}_{interval}.parquet"

    if cache and cache_path.exists():
        import pyarrow.parquet as pq
        from datetime import timezone as dt_tz
        table = pq.read_table(cache_path)
        cols = {}
        for name in table.column_names:
            if name == 'timestamp':
                ts_col = table.column(name)
                utc_times = []
                for i in range(len(ts_col)):
                    ts = ts_col[i].as_py()
                    if ts.tzinfo is not None:
                        ts = ts.astimezone(dt_tz.utc)
                    utc_times.append(ts.replace(tzinfo=None))
                cols[name] = utc_times
            else:
                cols[name] = table.column(name).to_pylist()
        df = pd.DataFrame(cols)
        df = df.set_index('timestamp')
        df.columns = [c.lower() for c in df.columns]
        return df

    t = yf.Ticker(ticker)
    raw = t.history(period=period, interval=interval)

    if raw.empty:
        raise ValueError(f"No data returned for {ticker} ({pair}) interval={interval}")

    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = [c.lower() for c in df.columns]
    df.index.name = "timestamp"

    if cache:
        df.to_parquet(cache_path)

    time.sleep(0.5)
    return df


def load_all_pairs(
    interval: str = "1d",
    period: str = "2y",
) -> dict[str, pd.DataFrame]:
    data = {}
    for pair in PAIR_TICKER_MAP:
        try:
            data[pair] = download_forex_data(pair, interval=interval, period=period)
        except Exception as e:
            print(f"  WARNING: Failed to load {pair}: {e}")
    return data
