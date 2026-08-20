#!/usr/bin/env python3
"""Download missing XAUUSD tick data via Dukascopy .bi5 datafeed.

Uses direct HTTP downloads (not tick-vault library) to fetch .bi5 files,
decode them to CSV format matching existing harvester output, and place
them in the output/ directory for import_ticks.py to pick up.

Usage:
    python3 bi5_gap_fill.py --symbol XAUUSD --start 2023-01-01 --end 2023-12-31
    python3 bi5_gap_fill.py --symbol XAUUSD --start 2026-07-11 --end 2026-07-13
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import lzma
import struct
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import namedtuple

import httpx

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "output"

# Dukascopy .bi5 price scales
PRICE_SCALES = {
    "XAUUSD": 1000,
    "EURUSD": 100000,
    "GBPUSD": 100000,
    "USDJPY": 1000,
}

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
Tick = namedtuple("Tick", ["timestamp_ms", "bid", "ask", "bidVol", "askVol"])

# Rate limiting: stay under 5 req/s per IP
SEMAPHORE = asyncio.Semaphore(2)  # 2 concurrent requests max (stay safe)
RATE_LIMIT_DELAY = 0.5  # 500ms between requests per worker


def build_urls_for_day(symbol: str, day: datetime) -> list[str]:
    """Build 24 hourly .bi5 URLs for a single day."""
    # Dukascopy URL format: {BASE}/{SYMBOL}/{YYYY}/{MM-1}/{DD}/{HH}h_ticks.bi5
    # Month is 0-indexed!
    year = day.year
    month_zero = day.month - 1
    day_str = f"{day.day:02d}"
    urls = []
    for hour in range(24):
        url = f"{BASE_URL}/{symbol}/{year}/{month_zero:02d}/{day_str}/{hour:02d}h_ticks.bi5"
        urls.append((hour, url))
    return urls


def decode_bi5(data: bytes, symbol: str, day: datetime, hour: int) -> list[Tick]:
    """Decode .bi5 binary data into tick records.

    Format: LZMA-compressed, 20-byte big-endian records:
      4B: ms within hour (0-3599999)
      4B: ask price (uint, / price_scale)
      4B: bid price (uint, / price_scale)
      4B: ask volume (float32, millions)
      4B: bid volume (float32, millions)
    """
    if not data or len(data) == 0:
        return []

    scale = PRICE_SCALES.get(symbol, 100000)

    try:
        decompressed = lzma.decompress(data)
    except Exception as e:
        logger.warning("LZMA decompress failed for %s %s %02dh: %s", symbol, day.date(), hour, e)
        return []

    # Truncate to multiple of 20
    record_len = 20
    usable = len(decompressed) - (len(decompressed) % record_len)
    if usable == 0:
        return []

    ticks = []
    day_ms = int(day.replace(hour=0, minute=0, second=0, tzinfo=timezone.utc).timestamp() * 1000)

    for i in range(0, usable, record_len):
        chunk = decompressed[i:i + record_len]
        try:
            ms_in_hour = struct.unpack(">I", chunk[0:4])[0]
            ask_raw = struct.unpack(">I", chunk[4:8])[0]
            bid_raw = struct.unpack(">I", chunk[8:12])[0]
            ask_vol_m = struct.unpack(">f", chunk[12:16])[0]
            bid_vol_m = struct.unpack(">f", chunk[16:20])[0]
        except struct.error:
            continue

        timestamp_ms = day_ms + (hour * 3600 * 1000) + ms_in_hour
        bid = bid_raw / scale
        ask = ask_raw / scale

        ticks.append(Tick(
            timestamp_ms=timestamp_ms,
            bid=bid,
            ask=ask,
            bidVol=bid_vol_m * 1e6,
            askVol=ask_vol_m * 1e6,
        ))

    return ticks


def write_csv(ticks: list[Tick], symbol: str, output_path: Path) -> int:
    """Write ticks to CSV in Dukascopy harvester format."""
    if not ticks:
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write("timestamp,instrument,bid,ask,bidVol,askVol\n")
        for t in ticks:
            f.write(f"{t.timestamp_ms},{symbol},{t.bid:.5f},{t.ask:.5f},{t.bidVol:.2f},{t.askVol:.2f}\n")

    return len(ticks)


async def fetch_url(client: httpx.AsyncClient, url: str) -> bytes | None:
    """Fetch a .bi5 URL with rate limiting and retries."""
    async with SEMAPHORE:
        for attempt in range(3):
            try:
                await asyncio.sleep(RATE_LIMIT_DELAY)
                resp = await client.get(url, timeout=30.0)

                if resp.status_code == 200:
                    return resp.content
                elif resp.status_code == 404:
                    # No data for this hour (market closed) — normal
                    return None
                elif resp.status_code == 429:
                    # Rate limited — back off
                    delay = 2 ** attempt
                    logger.warning("429 rate limited, backing off %ds...", delay)
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.warning("HTTP %d for %s", resp.status_code, url)
                    return None
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout) as e:
                if attempt < 2:
                    delay = 2 ** attempt
                    logger.warning("Retry %d for %s: %s", attempt + 1, url[-40:], e)
                    await asyncio.sleep(delay)
                else:
                    return None
        return None


async def harvest_day(client: httpx.AsyncClient, symbol: str, day: datetime, existing_dates: set) -> tuple[int, int]:
    """Harvest all 24 hours for a single day. Returns (files_created, ticks_total)."""
    date_str = day.strftime("%Y%m%d")
    filename = f"{symbol}_{date_str}.csv"
    output_path = OUTPUT_DIR / filename

    # Skip if already exists AND has actual data (>100 bytes, not just header)
    if date_str in existing_dates and output_path.exists():
        if output_path.stat().st_size > 100:
            return 0, 0
        # File exists but is tiny — likely a failed write, remove and re-harvest
        output_path.unlink(missing_ok=True)

    urls = build_urls_for_day(symbol, day)

    # Fetch all 24 hours concurrently
    tasks = [fetch_url(client, url) for _, url in urls]
    results = await asyncio.gather(*tasks)

    # Decode all hours
    all_ticks = []
    for (hour, _), data in zip(urls, results):
        if data and len(data) > 0:
            ticks = decode_bi5(data, symbol, day, hour)
            all_ticks.extend(ticks)

    if not all_ticks:
        # Market closed or no data — write empty file to avoid re-fetching
        return 0, 0

    all_ticks.sort(key=lambda t: t.timestamp_ms)
    count = write_csv(all_ticks, symbol, output_path)

    return 1, count


async def harvest_range(symbol: str, start: datetime, end: datetime, existing_dates: set) -> dict:
    """Harvest a date range."""
    logger.info("Starting harvest: %s %s → %s (%d days)",
                symbol, start.date(), end.date(), (end - start).days)

    headers = {
        "User-Agent": "Mozilla/5.0 (Java Web Start/17.0)",
        "Connection": "close",
    }

    total_files = 0
    total_ticks = 0
    total_days = 0

    async with httpx.AsyncClient(http2=False, headers=headers) as client:
        current = start
        while current < end:
            # Skip weekends (forex market closed)
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            total_days += 1
            files, ticks = await harvest_day(client, symbol, current, existing_dates)

            if files > 0:
                total_files += files
                total_ticks += ticks
                logger.info("  %s: %d ticks → %s", current.date(), ticks, f"{symbol}_{current.strftime('%Y%m%d')}.csv")
            else:
                # Could be holiday or genuinely no data
                pass

            current += timedelta(days=1)

    logger.info("Harvest complete: %s", symbol)
    logger.info("  Days processed: %d", total_days)
    logger.info("  Files created: %d", total_files)
    logger.info("  Total ticks: %d", total_ticks)

    return {
        "days": total_days,
        "files": total_files,
        "ticks": total_ticks,
    }


def get_existing_dates(output_dir: Path, symbol: str) -> set:
    """Get set of date strings (YYYYMMDD) already harvested."""
    dates = set()
    for f in output_dir.glob(f"{symbol}_*.csv"):
        date_part = f.stem.replace(f"{symbol}_", "")
        if len(date_part) == 8 and date_part.isdigit():
            dates.add(date_part)
    return dates


def main():
    parser = argparse.ArgumentParser(description="Download missing tick data via .bi5 datafeed")
    parser.add_argument("--symbol", required=True, help="Symbol (e.g., XAUUSD)")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    symbol = args.symbol.upper()
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    existing = get_existing_dates(OUTPUT_DIR, symbol)
    logger.info("Found %d existing %s files in %s", len(existing), symbol, OUTPUT_DIR)

    result = asyncio.run(harvest_range(symbol, start, end, existing))

    print(f"\nDone: {result['files']} files, {result['ticks']:,} ticks across {result['days']} days")


if __name__ == "__main__":
    main()
