#!/usr/bin/env python3
"""Overnight tick data harvest via Dukascopy REST datafeed API.

Downloads raw .bi5 tick files per hour, decompresses, and writes daily tick CSVs
matching the JForex harvester output format:
    timestamp,instrument,bid,ask,bidVol,askVol

Each symbol is processed year-by-year to keep memory bounded and provide
natural restart points.

Usage:
    nohup python3 scripts/harvest_ticks_overnight.py &
"""

from __future__ import annotations

import csv
import lzma
import struct
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path("/home/TacoPants/projects/Ayumi/tools/dukascopy-harvester/output")
LOG_FILE = OUTPUT_DIR.parent / "overnight_rest_log.txt"
PROGRESS_FILE = OUTPUT_DIR.parent / "overnight_rest_progress.json"

RATE_LIMIT_RPS = 4.0
MIN_INTERVAL = 1.0 / RATE_LIMIT_RPS
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]  # seconds

# Jobs: (symbol, start_date, end_date)
JOBS = [
    ("GBPUSD", date(2025, 4, 9), date(2026, 7, 11)),
    ("EURUSD", date(2020, 1, 1), date(2026, 7, 11)),
    ("XAUUSD", date(2020, 1, 1), date(2026, 7, 11)),
]

TICK_SIZE = 20
BASE_URL = "https://datafeed.dukascopy.com/datafeed"

# ── Helpers ─────────────────────────────────────────────────────────────────


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def fetch_url(url: str) -> bytes | None:
    """Fetch URL with retries, return raw bytes or None on failure."""
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})  # noqa: S310
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""  # 404 = no data for this hour/day (normal)
            log(f"  HTTP {e.code} for {url}, attempt {attempt + 1}/{MAX_RETRIES}")
        except Exception as e:
            log(f"  Error fetching {url}: {e.__class__.__name__}: {e}, attempt {attempt + 1}/{MAX_RETRIES}")

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
    return None  # All retries failed


def fetch_hour_ticks(symbol: str, dt: date, hour: int) -> list[tuple] | None:
    """Fetch and decode one hour of tick data. Returns list of (epoch_ms, bid, ask, bidVol, askVol) or None on error."""
    # Dukascopy URL: month is 0-indexed in some implementations, 1-indexed in others.
    # The working script (download_dukascopy.py) uses 0-indexed month: f"{month_idx0+1:02d}" → wait, let me check.
    # Actually from the working script: month_idx0 is 0-based, URL uses f"{month_idx0+1:02d}" which is 1-indexed.
    # And day is the actual day-of-month.
    url = f"{BASE_URL}/{symbol}/{dt.year}/{dt.month:02d}/{dt.day:02d}/{hour:02d}h_ticks.bi5"

    raw = fetch_url(url)
    if raw is None:
        return None  # Fetch error
    if len(raw) == 0:
        return []  # No data (404/empty)

    try:
        decompressed = lzma.decompress(raw)
    except Exception as e:
        log(f"  LZMA decompress failed for {url}: {e}")
        return []

    ticks = []
    n_records = len(decompressed) // TICK_SIZE
    for i in range(n_records):
        offset = i * TICK_SIZE
        ms_within_hour, ask_raw, bid_raw, ask_vol, bid_vol = struct.unpack_from(">IIIff", decompressed, offset)

        # Convert epoch: base is start of hour UTC
        hour_start_epoch = int(datetime(dt.year, dt.month, dt.day, hour, tzinfo=timezone.utc).timestamp())
        epoch_ms = hour_start_epoch * 1000 + ms_within_hour

        # Price conversion: raw int / 1_000_000
        # Point size varies by instrument but 1M divisor works for GBPUSD, EURUSD
        # For XAUUSD the raw values are larger (gold ~2000 = 2_000_000_000 raw)
        ask = ask_raw / 1_000_000
        bid = bid_raw / 1_000_000

        ticks.append((epoch_ms, symbol, bid, ask, bid_vol, ask_vol))

    return ticks


def write_day_csv(symbol: str, dt: date, all_ticks: list[tuple]):
    """Write ticks for one day to CSV."""
    filename = f"{symbol}_{dt.year}{dt.month:02d}{dt.day:02d}.csv"
    outpath = OUTPUT_DIR / filename

    with open(outpath, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "instrument", "bid", "ask", "bidVol", "askVol"])
        for tick in all_ticks:
            w.writerow(tick)

    return len(all_ticks)


def is_weekend(dt: date) -> bool:
    return dt.weekday() >= 5  # Sat=5, Sun=6


def year_chunks(start: date, end: date):
    """Yield (year_start, year_end) per year."""
    current = start
    while current <= end:
        year = current.year
        year_end = min(date(year, 12, 31), end)
        yield current, year_end, year
        current = date(year + 1, 1, 1)


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Clear previous log
    with open(LOG_FILE, "w") as f:
        f.write(f"Overnight REST harvest started {datetime.now()}\n")

    log("=" * 60)
    log("OVERNIGHT TICK HARVEST (REST API)")
    log(f"Rate limit: {RATE_LIMIT_RPS} req/s")
    log(f"Output: {OUTPUT_DIR}")
    log("=" * 60)

    total_ticks = 0
    total_days = 0
    total_errors = 0

    for symbol, start_date, end_date in JOBS:
        log(f"\n{'=' * 60}")
        log(f"  {symbol}: {start_date} → {end_date}")
        log(f"{'=' * 60}")

        for chunk_start, chunk_end, year in year_chunks(start_date, end_date):
            log(f"\n--- {symbol} year {year}: {chunk_start} → {chunk_end} ---")

            current = chunk_start
            year_ticks = 0
            year_days = 0
            year_errors = 0

            while current <= chunk_end:
                if is_weekend(current):
                    current += timedelta(days=1)
                    continue

                # Check if we already have this day's file
                fname = f"{symbol}_{current.year}{current.month:02d}{current.day:02d}.csv"
                if (OUTPUT_DIR / fname).exists():
                    current += timedelta(days=1)
                    continue

                day_ticks = []
                day_had_error = False

                for hour in range(24):
                    last_time = time.monotonic()

                    result = fetch_hour_ticks(symbol, current, hour)

                    if result is None:
                        log(f"  {symbol} {current} {hour:02d}h: FETCH ERROR")
                        day_had_error = True
                        year_errors += 1
                        continue

                    day_ticks.extend(result)

                    # Rate limit
                    elapsed = time.monotonic() - last_time
                    if elapsed < MIN_INTERVAL:
                        time.sleep(MIN_INTERVAL - elapsed)

                if day_ticks:
                    count = write_day_csv(symbol, current, day_ticks)
                    year_ticks += count
                    year_days += 1
                    if year_days % 50 == 0:
                        log(f"  {symbol} {current}: {year_days} days, {year_ticks:,} ticks so far for {year}")
                elif not day_had_error:
                    pass  # Holiday/no data, skip silently
                else:
                    total_errors += 1

                current += timedelta(days=1)

            total_ticks += year_ticks
            total_days += year_days
            log(f"  --- {symbol} {year} done: {year_days} days, {year_ticks:,} ticks, {year_errors} errors ---")

        log(f"\n  {symbol} COMPLETE: {total_days} days, {total_ticks:,} ticks total")

    log(f"\n{'=' * 60}")
    log(f"ALL DONE — {total_days} days, {total_ticks:,} ticks, {total_errors} errors")
    log(f"{'=' * 60}")

    # Write completion flag
    import json

    with open(OUTPUT_DIR.parent / "overnight_rest_complete.flag", "w") as f:
        json.dump(
            {
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "total_ticks": total_ticks,
                "total_days": total_days,
                "total_errors": total_errors,
            },
            f,
            indent=2,
        )


if __name__ == "__main__":
    main()
