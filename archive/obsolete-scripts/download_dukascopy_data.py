#!/usr/bin/env python3
"""
Download historical data from Dukascopy Bank.

Usage:
    python scripts/download_dukascopy_data.py                        # All pairs, all timeframes (bid+ask)
    python scripts/download_dukascopy_data.py --pairs EURUSD GBPUSD  # Specific pairs
    python scripts/download_dukascopy_data.py --timeframes M1 H1     # Specific timeframes
    python scripts/download_dukascopy_data.py --start 2021-01-01     # Custom start date
    python scripts/download_dukascopy_data.py --bid-only              # Bid data only (legacy mode)

Output:
    data/forex/{pair}_{timeframe}.parquet
    Columns: timestamp, Open, High, Low, Close, Volume, ask_open, ask_high, ask_low, ask_close
    e.g., data/forex/EURUSD_M1.parquet, data/forex/EURUSD_H1.parquet
"""

import argparse  # noqa: I001
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

import dukascopy_python  # noqa: F401
from dukascopy_python.instruments import (
    INSTRUMENT_FX_MAJORS_AUD_USD,
    INSTRUMENT_FX_MAJORS_EUR_USD,
    INSTRUMENT_FX_MAJORS_GBP_USD,
    INSTRUMENT_FX_MAJORS_NZD_USD,
    INSTRUMENT_FX_MAJORS_USD_CAD,
    INSTRUMENT_FX_MAJORS_USD_CHF,
    INSTRUMENT_FX_MAJORS_USD_JPY,
)
from dukascopy_python import (
    INTERVAL_DAY_1,
    INTERVAL_HOUR_1,
    INTERVAL_HOUR_4,
    INTERVAL_MIN_1,
    INTERVAL_MIN_15,
    INTERVAL_MIN_30,
    INTERVAL_MIN_5,
    OFFER_SIDE_ASK,
    OFFER_SIDE_BID,
    fetch,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PAIRS = {
    "AUDUSD": INSTRUMENT_FX_MAJORS_AUD_USD,
    "EURUSD": INSTRUMENT_FX_MAJORS_EUR_USD,
    "GBPUSD": INSTRUMENT_FX_MAJORS_GBP_USD,
    "NZDUSD": INSTRUMENT_FX_MAJORS_NZD_USD,
    "USDCAD": INSTRUMENT_FX_MAJORS_USD_CAD,
    "USDCHF": INSTRUMENT_FX_MAJORS_USD_CHF,
    "USDJPY": INSTRUMENT_FX_MAJORS_USD_JPY,
}

TIMEFRAMES = {
    "M1": (INTERVAL_MIN_1, 1),
    "M5": (INTERVAL_MIN_5, 5),
    "M15": (INTERVAL_MIN_15, 15),
    "M30": (INTERVAL_MIN_30, 30),
    "H1": (INTERVAL_HOUR_1, 60),
    "H4": (INTERVAL_HOUR_4, 240),
    "D1": (INTERVAL_DAY_1, 1440),
}

DEFAULT_START = datetime(2021, 1, 1)
DEFAULT_END = datetime.now()


def _normalize_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index("timestamp")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df = df.reset_index()
    df = df.rename(columns={"timestamp": "timestamp"})
    df["timestamp"] = df["timestamp"].dt.tz_convert(None).dt.tz_localize("Europe/London")
    return df


def download_pair(
    pair: str,
    instrument,
    timeframe: str,
    interval,
    start: datetime,
    end: datetime,
    output_dir: Path,
    bid_only: bool = False,
) -> Path | None:
    pair_file = output_dir / f"{pair}_{timeframe}.parquet"
    if pair_file.exists():
        logger.info("  %s %s: already exists, skipping", pair, timeframe)
        return pair_file

    logger.info("  %s %s: downloading bid %s to %s", pair, timeframe, start.date(), end.date())
    try:
        bid_df = fetch(instrument, interval, OFFER_SIDE_BID, start, end)
    except Exception as e:
        logger.error("  %s %s: bid download failed - %s", pair, timeframe, e)
        return None

    if bid_df.empty:
        logger.warning("  %s %s: no data returned", pair, timeframe)
        return None

    bid_df = _normalize_timestamps(bid_df)

    if not bid_only:
        logger.info(
            "  %s %s: downloading ask %s to %s",
            pair,
            timeframe,
            start.date(),
            end.date(),
        )
        try:
            ask_df = fetch(instrument, interval, OFFER_SIDE_ASK, start, end)
        except Exception as e:
            logger.error("  %s %s: ask download failed - %s", pair, timeframe, e)
            return None

        if not ask_df.empty:
            ask_df = _normalize_timestamps(ask_df)
            merged = bid_df.merge(
                ask_df,
                on="timestamp",
                how="inner",
                suffixes=("", "_ask"),
            )
            merged = merged.rename(
                columns={
                    "Open_ask": "ask_open",
                    "High_ask": "ask_high",
                    "Low_ask": "ask_low",
                    "Close_ask": "ask_close",
                    "Volume_ask": "ask_volume",
                }
            )
            bid_df = merged

    bid_df.to_parquet(pair_file, index=False)
    logger.info("  %s %s: saved %d bars to %s", pair, timeframe, len(bid_df), pair_file.name)
    return pair_file


def main():
    parser = argparse.ArgumentParser(description="Download Dukascopy historical data")
    parser.add_argument(
        "--pairs",
        nargs="+",
        choices=list(PAIRS.keys()),
        default=list(PAIRS.keys()),
        help="Pairs to download (default: all)",
    )
    parser.add_argument(
        "--timeframes",
        nargs="+",
        choices=list(TIMEFRAMES.keys()),
        default=["M1", "H1", "H4", "D1"],
        help="Timeframes to download (default: M1 H1 H4 D1)",
    )
    parser.add_argument(
        "--start",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d"),
        default=DEFAULT_START,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d"),
        default=DEFAULT_END,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/forex"),
        help="Output directory",
    )
    parser.add_argument(
        "--bid-only",
        action="store_true",
        help="Download bid data only (no ask/spread columns)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    total_pairs = len(args.pairs) * len(args.timeframes)
    logger.info(
        "Downloading %d pairs x %d timeframes = %d files from %s to %s",
        len(args.pairs),
        len(args.timeframes),
        total_pairs,
        args.start.date(),
        args.end.date(),
    )

    results = []
    for pair in sorted(args.pairs):
        instrument = PAIRS[pair]
        for tf in args.timeframes:
            interval, _ = TIMEFRAMES[tf]
            path = download_pair(
                pair,
                instrument,
                tf,
                interval,
                args.start,
                args.end,
                output_dir,
                bid_only=args.bid_only,
            )
            if path:
                results.append(path)

    logger.info("Done. %d/%d files saved.", len(results), total_pairs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
