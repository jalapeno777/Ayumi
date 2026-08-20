#!/usr/bin/env python3
"""Export M15 bars from DuckDB to CSV format matching XAUUSD_M15.csv layout.

Used after tick aggregation to produce the replacement M15 CSV.

Usage:
    python3 tools/dukascopy-harvester/export_m15_bars.py --symbol XAUUSD
    python3 tools/dukascopy-harvester/export_m15_bars.py --symbol XAUUSD --output /custom/path.csv
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "ayumi_market.duckdb"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "forex" / "historical"


def export_m15(symbol: str, output_path: Path) -> dict:
    """Export M15 bars for a symbol to CSV.

    Returns metadata dict with count, date range, and md5 hash.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        # Check data exists
        count = con.execute(
            "SELECT count(*) FROM bars WHERE symbol = ? AND timeframe = 'M15'",
            [symbol],
        ).fetchone()[0]

        if count == 0:
            logger.error("No M15 bars for %s in %s", symbol, DB_PATH)
            return {}

        # Get date range
        minmax = con.execute(
            "SELECT min(timestamp_utc), max(timestamp_utc) FROM bars WHERE symbol = ? AND timeframe = 'M15'",
            [symbol],
        ).fetchone()

        earliest = datetime.datetime.fromtimestamp(minmax[0], tz=datetime.timezone.utc)
        latest = datetime.datetime.fromtimestamp(minmax[1], tz=datetime.timezone.utc)

        logger.info("Exporting %d M15 bars for %s (%s → %s)", count, symbol, earliest.date(), latest.date())

        # Export to CSV using DuckDB's COPY
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write header + data
        con.execute(f"""
            COPY (
                SELECT
                    strftime(to_timestamp(timestamp_utc), '%Y-%m-%d %H:%M:%S') AS Date,
                    open AS Open,
                    high AS High,
                    low AS Low,
                    close AS Close,
                    volume AS Volume
                FROM bars
                WHERE symbol = '{symbol}' AND timeframe = 'M15'
                ORDER BY timestamp_utc
            ) TO '{output_path}' (HEADER, DELIMITER ',');
        """)  # noqa: S608

        # Compute MD5
        md5 = hashlib.md5(output_path.read_bytes()).hexdigest()  # noqa: S324

        logger.info("Wrote %d rows to %s", count, output_path)
        logger.info("MD5: %s", md5)

        return {
            "symbol": symbol,
            "timeframe": "M15",
            "row_count": count,
            "earliest": earliest.isoformat(),
            "latest": latest.isoformat(),
            "output_path": str(output_path),
            "md5": md5,
        }

    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description="Export M15 bars from DuckDB to CSV")
    parser.add_argument("--symbol", default="XAUUSD", help="Symbol to export")
    parser.add_argument("--output", help="Output path (default: data/forex/historical/<SYMBOL>_M15_tick_agg.csv)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    symbol = args.symbol.upper()
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = DEFAULT_OUTPUT / f"{symbol}_M15_tick_agg.csv"

    result = export_m15(symbol, output_path)
    if result:
        print(f"\nExport complete:")  # noqa: F541
        for k, v in result.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
