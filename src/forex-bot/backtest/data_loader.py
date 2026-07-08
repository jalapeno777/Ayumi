import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow.parquet as pq

from .engine import Bar, BarPeriod
from core.pip import PipCalculator

logger = logging.getLogger(__name__)

_EASTERN = ZoneInfo("America/New_York")
_UTC = timezone.utc

_ASK_OPEN = "ask_open"
_ASK_CLOSE = "ask_close"
_BID_OPEN = "Open"
_BID_CLOSE = "Close"

_OHLC_COL_MAP = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
}


def _find_column(df: pd.DataFrame, name: str) -> str:
    if name in df.columns:
        return name
    lower_map = {c.lower(): c for c in df.columns}
    if name.lower() in lower_map:
        return lower_map[name.lower()]
    return name


def _parse_csv_timestamp(ts_str: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(ts_str, fmt)
            dt = dt.replace(tzinfo=_EASTERN)
            return dt.astimezone(_UTC)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {ts_str}")


def _compute_spread_pips(bid_price: float, ask_price: float) -> float:
    spread_price = abs(ask_price - bid_price)
    return PipCalculator.price_to_pips(bid_price, spread_price)


def _detect_ask_columns(df: pd.DataFrame) -> bool:
    return _ASK_OPEN in df.columns and _ASK_CLOSE in df.columns


class CsvDataLoader:
    def load(self, filepath: str) -> list[Bar]:
        bars = []
        dropped = 0
        with open(filepath) as f:
            lines = f.readlines()

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue

            try:
                dt = _parse_csv_timestamp(parts[0])
                open_price = float(parts[1])
                high = float(parts[2])
                low = float(parts[3])
                close = float(parts[4])
                volume = float(parts[5]) if len(parts) > 5 else 0.0

                bar = Bar(
                    time=dt,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
                bars.append(bar)
            except (ValueError, IndexError):
                dropped += 1
                continue

        if dropped:
            logger.warning("Dropped %d malformed rows from %s", dropped, filepath)
        return bars

    def load_from_string(self, csv_content: str) -> list[Bar]:
        bars = []
        dropped = 0
        lines = csv_content.strip().split("\n")

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue

            try:
                dt = _parse_csv_timestamp(parts[0])
                open_price = float(parts[1])
                high = float(parts[2])
                low = float(parts[3])
                close = float(parts[4])
                volume = float(parts[5]) if len(parts) > 5 else 0.0

                bar = Bar(
                    time=dt,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
                bars.append(bar)
            except (ValueError, IndexError):
                dropped += 1
                continue

        if dropped:
            logger.warning("Dropped %d malformed rows from CSV string input", dropped)
        return bars

    @staticmethod
    def _parse_datetime(s: str) -> datetime:
        """Parse datetime with or without seconds."""
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        raise ValueError(f"Cannot parse datetime: {s}")

    def infer_timeframe(self, bars: list[Bar]) -> BarPeriod:
        if len(bars) < 2:
            return BarPeriod(60)

        time_diffs = []
        for i in range(1, min(len(bars), 10)):
            diff = (bars[i].time - bars[i - 1].time).total_seconds() / 60
            time_diffs.append(diff)

        avg_diff = sum(time_diffs) / len(time_diffs) if time_diffs else 60

        if avg_diff <= 20:
            return BarPeriod(15)
        elif avg_diff <= 60:
            return BarPeriod(60)
        elif avg_diff <= 300:
            return BarPeriod(240)
        else:
            return BarPeriod(1440)

    def load_parquet(self, filepath: str | Path) -> list[Bar]:
        """Load OHLC(V) bars from a parquet file.

        Supports two parquet formats:
          1. Bid-only: timestamp, Open, High, Low, Close, Volume
          2. Bid+Ask:  timestamp, Open, High, Low, Close, Volume,
                      ask_open, ask_high, ask_low, ask_close

        When ask columns are present, per-bar spread_pips is computed
        from (ask_open - bid_open) using PipCalculator.

        Column names are matched case-insensitively.
        """
        table = pq.read_table(str(filepath))
        df = table.to_pandas(timestamp_as_object=True)
        df = df.reset_index(drop=True)  # Phase 0: fix KeyError 'timestamp' when parquet index is unnamed
        ts_col = _find_column(df, "timestamp")
        timestamps = pd.to_datetime(df[ts_col], utc=True).dt.tz_convert(_UTC)
        has_ask = _detect_ask_columns(df)
        col_open = _find_column(df, "open")
        col_high = _find_column(df, "high")
        col_low = _find_column(df, "low")
        col_close = _find_column(df, "close")
        col_volume = _find_column(df, "volume")
        bars = []
        for i, row in df.iterrows():
            spread = 0.0
            if has_ask:
                bid_open = float(row[col_open])
                ask_open_val = float(row[_ASK_OPEN])
                spread = _compute_spread_pips(bid_open, ask_open_val)
            bar = Bar(
                time=timestamps.iloc[i].to_pydatetime(),
                open=float(row[col_open]),
                high=float(row[col_high]),
                low=float(row[col_low]),
                close=float(row[col_close]),
                volume=float(row.get(col_volume, 0.0)),
                spread_pips=spread,
            )
            bars.append(bar)
        return bars
