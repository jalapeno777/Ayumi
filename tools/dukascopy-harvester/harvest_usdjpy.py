#!/usr/bin/env python3
"""Harvest USDJPY tick data from Dukascopy .bi5 feed, populate DuckDB, generate bars.

This script replaces the tick-vault approach with direct HTTP downloads using
the existing bi5_gap_fill infrastructure. It:

1. Downloads missing USDJPY .bi5 files (2020-01-01 → present)
2. Imports all tick CSVs into a DuckDB database
3. Generates M5, M15, H1, H4, D1 bar tables from ticks
4. Runs integrity checks (gap detection, bar counts)

Usage:
    # Full harvest + DuckDB build
    python3 harvest_usdjpy.py

    # Download only (skip DuckDB build)
    python3 harvest_usdjpy.py --download-only

    # DuckDB build only (skip download, use existing CSVs)
    python3 harvest_usdjpy.py --build-only

    # Custom date range
    python3 harvest_usdjpy.py --start 2023-01-01 --end 2023-12-31
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import httpx

# Import the existing bi5 download infrastructure
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from bi5_gap_fill import (
    get_existing_dates,
    harvest_day,
)

logger = logging.getLogger(__name__)

# ─── Configuration ───────────────────────────────────────────────────────────

SYMBOL = "USDJPY"
START_DATE = "2020-01-01"
END_DATE = "2026-07-25"

OUTPUT_DIR = SCRIPT_DIR / "output"
DUCKDB_DIR = SCRIPT_DIR.parent.parent / "data" / "ayumi" / "duckdb"
DUCKDB_PATH = DUCKDB_DIR / "usdjpy_ticks.duckdb"

# Bar timeframes: (table_suffix, seconds)
TIMEFRAMES = [
    ("m5", 300),
    ("m15", 900),
    ("h1", 3600),
    ("h4", 14400),
    ("d1", 86400),
]


# ─── Phase 1: Download ───────────────────────────────────────────────────────


async def download_missing_days(start: datetime, end: datetime) -> dict:
    """Download all missing USDJPY .bi5 files in the date range."""
    existing = get_existing_dates(OUTPUT_DIR, SYMBOL)
    logger.info("Found %d existing %s CSV files", len(existing), SYMBOL)

    stats = {"downloaded": 0, "skipped": 0, "ticks": 0, "errors": 0}
    headers = {
        "User-Agent": "Mozilla/5.0 (Java Web Start/17.0)",
        "Connection": "close",
    }

    async with httpx.AsyncClient(http2=False, headers=headers) as client:
        current = start
        while current < end:
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            date_str = current.strftime("%Y%m%d")
            filename = f"{SYMBOL}_{date_str}.csv"
            output_path = OUTPUT_DIR / filename

            if date_str in existing and output_path.exists() and output_path.stat().st_size > 100:
                stats["skipped"] += 1
                current += timedelta(days=1)
                continue

            try:
                files, ticks = await harvest_day(client, SYMBOL, current, existing)
                if files > 0:
                    stats["downloaded"] += files
                    stats["ticks"] += ticks
                    if stats["downloaded"] % 50 == 0:
                        logger.info(
                            "  Progress: %d days downloaded, %d skipped, %d ticks",
                            stats["downloaded"],
                            stats["skipped"],
                            stats["ticks"],
                        )
            except Exception as e:
                logger.error("Error harvesting %s: %s", current.date(), e)
                stats["errors"] += 1

            current += timedelta(days=1)

    logger.info(
        "Download complete: %d downloaded, %d skipped, %d ticks, %d errors",
        stats["downloaded"],
        stats["skipped"],
        stats["ticks"],
        stats["errors"],
    )
    return stats


# ─── Phase 2: DuckDB Import ─────────────────────────────────────────────────


def import_ticks_to_duckdb(db_path: Path) -> int:
    """Import all USDJPY tick CSVs into DuckDB. Returns total tick count."""
    logger.info("Importing ticks into DuckDB at %s", db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(db_path))

    conn.execute("DROP TABLE IF EXISTS ticks")
    conn.execute("""
        CREATE TABLE ticks (
            timestamp_ms BIGINT,
            symbol VARCHAR,
            bid DOUBLE,
            ask DOUBLE,
            bid_vol DOUBLE,
            ask_vol DOUBLE
        )
    """)

    csv_files = sorted(glob.glob(str(OUTPUT_DIR / f"{SYMBOL}_2*.csv")))
    csv_files = [f for f in csv_files if "_M1" not in f]
    logger.info("Found %d CSV files to import", len(csv_files))

    for i, csv_file in enumerate(csv_files):
        fname = os.path.basename(csv_file)
        try:
            # CSV format: timestamp,instrument,bid,ask,bidVol,askVol
            conn.execute(
                "INSERT INTO ticks SELECT timestamp, instrument, bid, ask, bidVol, askVol FROM read_csv_auto(?, header=true)",  # noqa: E501
                [csv_file],
            )
        except Exception as e:
            logger.warning("Failed to import %s: %s, trying explicit schema", fname, e)
            try:
                conn.execute(
                    "INSERT INTO ticks SELECT CAST(timestamp AS BIGINT), instrument, CAST(bid AS DOUBLE), CAST(ask AS DOUBLE), CAST(bidVol AS DOUBLE), CAST(askVol AS DOUBLE) FROM read_csv(?, header=true, columns={'timestamp': 'VARCHAR', 'instrument': 'VARCHAR', 'bid': 'VARCHAR', 'ask': 'VARCHAR', 'bidVol': 'VARCHAR', 'askVol': 'VARCHAR'})",  # noqa: E501
                    [csv_file],
                )
            except Exception as e2:
                logger.error("Skipping %s: %s", fname, e2)

        if (i + 1) % 100 == 0:
            count = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
            logger.info("  Imported %d/%d files, %d ticks so far", i + 1, len(csv_files), count)

    total = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
    logger.info("Creating index on timestamp_ms...")
    conn.execute("CREATE INDEX idx_ticks_ts ON ticks(timestamp_ms)")
    logger.info("Import complete: %d total ticks", total)

    conn.close()
    return total


# ─── Phase 3: Bar Generation ────────────────────────────────────────────────


def generate_bars(db_path: Path) -> dict:
    """Generate M5, M15, H1, H4, D1 bar tables from ticks."""
    conn = duckdb.connect(str(db_path))
    results = {}

    for suffix, seconds in TIMEFRAMES:
        table_name = f"bars_{suffix}"
        logger.info("Generating %s bars...", table_name.upper())

        conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        conn.execute(f"""
            CREATE TABLE {table_name} AS
            SELECT
                time_bucket(INTERVAL '{seconds} SECOND', to_timestamp(timestamp_ms / 1000.0)) AS bar_start,
                MIN(timestamp_ms) AS first_tick_ms,
                MAX(timestamp_ms) AS last_tick_ms,
                COUNT(*) AS tick_count,
                AVG(bid) AS avg_bid,
                AVG(ask) AS avg_ask,
                MIN(bid) AS low_bid,
                MAX(bid) AS high_bid,
                MIN(ask) AS low_ask,
                MAX(ask) AS high_ask,
                FIRST(bid ORDER BY timestamp_ms) AS open_bid,
                LAST(bid ORDER BY timestamp_ms) AS close_bid,
                FIRST(ask ORDER BY timestamp_ms) AS open_ask,
                LAST(ask ORDER BY timestamp_ms) AS close_ask,
                SUM(bid_vol) AS total_bid_vol,
                SUM(ask_vol) AS total_ask_vol
            FROM ticks
            GROUP BY bar_start
            ORDER BY bar_start
        """)  # noqa: S608

        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]  # noqa: S608
        results[suffix] = count
        logger.info("  %s: %d bars", table_name.upper(), count)

    conn.close()
    return results


# ─── Phase 4: Integrity Check ───────────────────────────────────────────────


def run_integrity_check(db_path: Path, bar_counts: dict) -> dict:
    """Run integrity checks on the generated data."""
    conn = duckdb.connect(str(db_path))
    checks = {}

    # Check 1: Bar counts meet minimums
    min_expected = {"m5": 500_000, "m15": 170_000, "h1": 42_000, "h4": 10_500, "d1": 1_750}
    for tf, expected in min_expected.items():
        actual = bar_counts.get(tf, 0)
        checks[f"bar_count_{tf}"] = {
            "expected_min": expected,
            "actual": actual,
            "pass": actual >= expected,
        }

    # Check 2: Gap detection on M5 bars (no gaps > 5 trading days)
    gaps = conn.execute("""
        WITH m5_dates AS (
            SELECT DISTINCT CAST(bar_start AS DATE) AS d FROM bars_m5
        ),
        date_gaps AS (
            SELECT
                d,
                d - LAG(d) OVER (ORDER BY d) AS gap_days
            FROM m5_dates
        )
        SELECT MAX(gap_days) AS max_gap, COUNT(CASE WHEN gap_days > 7 THEN 1 END) AS big_gaps
        FROM date_gaps
        WHERE gap_days IS NOT NULL
    """).fetchone()

    max_gap = gaps[0] if gaps else 0
    big_gap_count = gaps[1] if gaps else 0
    checks["gap_check"] = {
        "max_gap_days": max_gap,
        "gaps_over_7_days": big_gap_count,
        "pass": big_gap_count == 0,
    }

    # Check 3: Date range coverage
    range_result = conn.execute("""
        SELECT CAST(MIN(bar_start) AS DATE), CAST(MAX(bar_start) AS DATE)
        FROM bars_m5
    """).fetchone()
    checks["date_range"] = {
        "start": str(range_result[0]) if range_result else None,
        "end": str(range_result[1]) if range_result else None,
        "pass": range_result[0] is not None,
    }

    # Check 4: Query latency test (< 100ms for single-day M5 query)
    start_time = time.time()
    conn.execute("""
        SELECT * FROM bars_m5
        WHERE bar_start >= '2022-01-03'::TIMESTAMP
          AND bar_start < '2022-01-04'::TIMESTAMP
    """).fetchall()
    latency_ms = (time.time() - start_time) * 1000
    checks["query_latency"] = {
        "ms": round(latency_ms, 1),
        "pass": latency_ms < 100,
    }

    # Check 5: No NULL prices
    null_count = conn.execute("SELECT COUNT(*) FROM ticks WHERE bid IS NULL OR ask IS NULL").fetchone()[0]
    checks["null_prices"] = {
        "count": null_count,
        "pass": null_count == 0,
    }

    conn.close()
    return checks


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Harvest USDJPY tick data and build DuckDB bars")
    parser.add_argument("--start", default=START_DATE, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=END_DATE, help="End date YYYY-MM-DD")
    parser.add_argument("--download-only", action="store_true", help="Skip DuckDB build")
    parser.add_argument("--build-only", action="store_true", help="Skip download, build DuckDB from existing CSVs")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    # Phase 1: Download
    if not args.build_only:
        logger.info("=" * 60)
        logger.info("PHASE 1: Download USDJPY .bi5 data (%s → %s)", start.date(), end.date())
        logger.info("=" * 60)
        asyncio.run(download_missing_days(start, end))

    if args.download_only:
        logger.info("Download-only mode, skipping DuckDB build")
        return

    # Phase 2: Import to DuckDB
    logger.info("=" * 60)
    logger.info("PHASE 2: Import ticks into DuckDB")
    logger.info("=" * 60)
    tick_count = import_ticks_to_duckdb(DUCKDB_PATH)
    logger.info("Total ticks imported: %d", tick_count)

    # Phase 3: Generate bars
    logger.info("=" * 60)
    logger.info("PHASE 3: Generate bar tables")
    logger.info("=" * 60)
    bar_counts = generate_bars(DUCKDB_PATH)

    # Phase 4: Integrity check
    logger.info("=" * 60)
    logger.info("PHASE 4: Integrity check")
    logger.info("=" * 60)
    checks = run_integrity_check(DUCKDB_PATH, bar_counts)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"DuckDB: {DUCKDB_PATH}")
    print(f"Total ticks: {tick_count:,}")
    print()
    print("Bar counts:")
    for tf in ["m5", "m15", "h1", "h4", "d1"]:
        c = checks.get(f"bar_count_{tf}", {})
        status = "✅" if c.get("pass") else "❌"
        print(f"  {status} {tf.upper()}: {bar_counts.get(tf, 0):,} bars (min: {c.get('expected_min', '?'):,})")
    print()
    print("Integrity checks:")
    gap = checks.get("gap_check", {})
    status = "✅" if gap.get("pass") else "❌"
    print(
        f"  {status} Gap check: max gap {gap.get('max_gap_days', '?')} days, {gap.get('gaps_over_7_days', '?')} gaps >7d"  # noqa: E501
    )  # noqa: E501
    dr = checks.get("date_range", {})
    status = "✅" if dr.get("pass") else "❌"
    print(f"  {status} Date range: {dr.get('start', '?')} → {dr.get('end', '?')}")
    lat = checks.get("query_latency", {})
    status = "✅" if lat.get("pass") else "❌"
    print(f"  {status} Query latency: {lat.get('ms', '?')}ms (<100ms required)")
    nulls = checks.get("null_prices", {})
    status = "✅" if nulls.get("pass") else "❌"
    print(f"  {status} NULL prices: {nulls.get('count', '?')}")

    all_pass = all(c.get("pass", False) for c in checks.values())
    print()
    print(f"Overall: {'ALL CHECKS PASSED ✅' if all_pass else 'SOME CHECKS FAILED ❌'}")


if __name__ == "__main__":
    main()
