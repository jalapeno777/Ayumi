#!/usr/bin/env python3
"""Download M1 historical OHLCV data from Dukascopy for Ayumi strategy testing.

Source: Dukascopy Bank free tick-data datafeed
        https://datafeed.dukascopy.com/datafeed/{PAIR}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5
Where MM and DD are 1-indexed (Jan=01, 1st=01) and HH is 0-indexed (00..23).
Each bi5 file is LZMA-compressed raw big-endian tick records. Each tick is 20 bytes:

    >IIIff  (4-byte ms timestamp, 4-byte ask, 4-byte bid,
             4-byte ask volume (float32, units of millions),
             4-byte bid volume (float32, units of millions))

We aggregate ticks into M1 (one-minute) bid OHLCV bars and write one CSV per
month per pair.

Output:
    data/forex/dukascopy/{PAIR}_M1_{YYYY-MM}.csv
    Columns: timestamp,open,high,low,close,volume   (lowercase, ISO 8601 UTC)

Resume: a per-month CSV is skipped if it already exists with >= 1 data row.

Usage:
    python scripts/download_dukascopy.py --start 2015-01 --end 2023-12 \\
        --pairs XAUUSD GBPUSD EURUSD USDJPY
    python scripts/download_dukascopy.py --start 2015-01 --end 2015-01 \\
        --pairs XAUUSD                       # smoke-test one pair / one month
"""
from __future__ import annotations

import argparse
import calendar
import csv
import io
import lzma
import os
import struct
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Default pairs — uppercase because the datafeed URL is case-sensitive.
DEFAULT_PAIRS = ["XAUUSD", "GBPUSD", "EURUSD", "USDJPY"]

# Price scales (divisor that turns the stored integer back into a real price).
#   * Most FX majors: 5-digit quotes, point = 0.00001  -> store = price * 100_000
#   * JPY pairs:      3-digit quotes, point = 0.001     -> store = price * 1_000
#   * XAUUSD:         3-digit quotes, point = 0.001     -> store = price * 1_000
PRICE_SCALES = {
    "XAUUSD": 1_000,
    "GBPUSD": 100_000,
    "EURUSD": 100_000,
    "USDJPY": 1_000,
}

BASE_URL = "https://datafeed.dukascopy.com/datafeed"

# byte layout
TICK_STRUCT = struct.Struct(">IIIff")  # ms, ask, bid, ask_vol_f32, bid_vol_f32
TICK_SIZE = TICK_STRUCT.size
assert TICK_SIZE == 20, "tick layout drift"

# Tick volume in Dukascopy is stored as a float32 in *millions of units*.
# 1.0 means 1,000,000 base-currency units (a "standard lot" for FX).
VOLUME_MULTIPLIER = 1_000_000.0

# HTTP request settings
DEFAULT_OUT_DIR = Path("data/forex/dukascopy")
# Per-request timeout. Dukascopy's CDN is flaky: some hours return in <5s,
# others hit the timeout. 20s keeps total wall time bounded while still
# allowing for slow first-attempt responses.
HTTP_TIMEOUT_SECS = 20
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Retry / pacing policy (per task spec)
RETRY_BACKOFFS = [5, 15, 45]   # seconds; one fewer than these
INTER_MONTH_SLEEP = 1.0        # sleep between complete month downloads

CSV_HEADER = ("timestamp", "open", "high", "low", "close", "volume")

# -----------------------------------------------------------------------------
# Networking helpers
# -----------------------------------------------------------------------------

def _http_get_bytes(url: str) -> bytes:
    """HTTP GET with strict timeout and a browser-like UA. Raises HTTPError on >=400.

    `Connection: close` is sent so each request opens a fresh TCP/TLS handshake;
    the Dukascopy CDN keeps reused connections in an unresponsive state after a
    few hits, which manifests as long read timeouts on the 4th-5th call in a
    rapid-fire run. Forcing `close` removes that pathology.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Connection": "close",
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECS) as resp:
        return resp.read()


def fetch_with_retries(url: str, *, log) -> bytes:
    """GET `url`, retrying on transient errors with exponential backoff.

    Empty bodies (HTTP 200 with 0 bytes) are returned as-is so the caller can
    notice that hour had no trades (weekends, holidays) without tripping a
    retry storm.

    404 (no such hour) is terminal so we don't waste 65s of backoff on weekends.
    503 (anti-abuse throttle) gets the longest backoff so we don't hammer the
    CDN back into a throttle.
    """
    last_err: Exception | None = None
    backoffs = [0] + RETRY_BACKOFFS
    for attempt, sleep_s in enumerate(backoffs, start=1):
        if sleep_s:
            log(f"    retry {attempt - 1}: sleeping {sleep_s}s")
            time.sleep(sleep_s)
        try:
            return _http_get_bytes(url)
        except urllib.error.HTTPError as e:
            # 404 (hour had no trades) is terminal — caller decides.
            if e.code == 404:
                raise
            last_err = e
            log(f"    retry {attempt}: HTTP {e.code} on {url}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            log(f"    retry {attempt}: {type(e).__name__}: {e}")
    raise RuntimeError(f"giving up on {url}: {last_err!r}")


# -----------------------------------------------------------------------------
# Tick parsing & M1 aggregation
# -----------------------------------------------------------------------------

def iter_ticks(blob: bytes) -> Iterator[tuple[int, int, int, float, float]]:
    """Yield (ms_within_hour, ask, bid, ask_vol_M, bid_vol_M) for every tick."""
    n = len(blob) - (len(blob) % TICK_SIZE)
    for off in range(0, n, TICK_SIZE):
        yield TICK_STRUCT.unpack_from(blob, off)


def aggregate_day_to_m1(
    pair: str,
    year: int,
    month_idx0: int,
    day: int,
    hour_ticks: Iterable[tuple[int, int, int, float, float]],
) -> Iterator[tuple[datetime, float, float, float, float, int]]:
    """Aggregate one day's worth of (ms, ask, bid, ask_vol, bid_vol) ticks into
    M1 bid OHLCV bars (one tuple per minute that has at least one tick).

    `month_idx0` is 0-indexed (matching Python datetime) even though the URL
    format is 1-indexed — the caller converts.
    """
    # bucket by minute-of-hour; then close them off at the end
    buckets: dict[int, dict] = {}

    for ms, _ask, bid, _av, bv in hour_ticks:
        # We aggregate on bid (Dukascopy's default M1 bars in JForex are bid-based).
        # Convert stored integer to real price; tie choice of ask-vs-bid to bid for
        # compatibility with the rest of Ayumi's data loaders.
        scale = PRICE_SCALES.get(pair.upper())
        if scale is None:
            raise ValueError(f"no price scale configured for pair {pair!r}")
        bid_px = bid / scale

        minute = ms // 60_000  # 0..59
        bucket = buckets.get(minute)
        if bucket is None:
            bucket = {
                "open": bid_px,
                "high": bid_px,
                "low": bid_px,
                "close": bid_px,
                "n_ticks": 0,
                "vol_M": 0.0,
            }
            buckets[minute] = bucket
        else:
            if bid_px > bucket["high"]:
                bucket["high"] = bid_px
            if bid_px < bucket["low"]:
                bucket["low"] = bid_px
            bucket["close"] = bid_px

        bucket["n_ticks"] += 1
        bucket["vol_M"] += bv  # store bid volume in millions; final volume later

    # Emit in minute order (0..59). The hour stamp combined with the minute
    # gives us the full UTC timestamp for the bar.
    for minute in sorted(buckets.keys()):
        b = buckets[minute]
        ts = datetime(
            year, month_idx0 + 1, day,
            hour=0, minute=minute,
            tzinfo=timezone.utc,
        ) - timedelta(hours=0)  # hour is encoded below; minute is 0..59
        # Build the timestamp with the *hour* baked in.
        ts = datetime(
            year, month_idx0 + 1, day,
            tzinfo=timezone.utc,
        ) + timedelta(minutes=minute)
        # Volume convention: integer tick count. This is by far the most
        # interpretable "volume" for Dukascopy data and matches what Ayumi's
        # existing loaders (e.g. CsvDataLoader → time-scaled) already accept.
        yield (ts, b["open"], b["high"], b["low"], b["close"], b["n_ticks"])


def aggregate_month(
    pair: str,
    year: int,
    month_idx0: int,
    log,
    max_hours: int = 0,
) -> list[tuple]:
    """Pull every hour-tick file for `pair/year/month`, aggregate into M1 bars.

    `max_hours` (when >0) caps the number of hour-files fetched. This is
    intended for `--max-hours` smoke tests; pass 0 (default) for the full month.

    Returns the list of (ts, o, h, l, c, v) tuples ready for CSV writing.
    """
    ndays = calendar.monthrange(year, month_idx0 + 1)[1]
    bars: dict[datetime, list] = {}
    hours_left = max_hours if max_hours and max_hours > 0 else None

    for day in range(1, ndays + 1):
        for hour in range(24):
            if hours_left is not None:
                if hours_left <= 0:
                    log(f"    hit --max-hours={max_hours} cap; stopping aggregation")
                    return [bars[k] for k in sorted(bars.keys())]
                hours_left -= 1
            url = (
                f"{BASE_URL}/{pair.upper()}"
                f"/{year:04d}/{month_idx0 + 1:02d}"  # URL uses 1-indexed month
                f"/{day:02d}/{hour:02d}h_ticks.bi5"
            )
            try:
                blob = fetch_with_retries(url, log=log)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    # 404 = no trades in this hour (weekend, holiday) — fine
                    continue
                log(f"    {pair} {year}-{month_idx0+1:02d}-{day:02d} {hour:02d}h: HTTP {e.code}, skipping hour")
                continue
            except Exception as e:
                log(f"    {pair} {year}-{month_idx0+1:02d}-{day:02d} {hour:02d}h: {type(e).__name__}: {e}")
                continue

            if not blob:
                # 0 bytes can mean the file exists but had no ticks for that hour
                continue

            try:
                decoded = lzma.decompress(blob)
            except lzma.LZMAError:
                log(f"    {pair} {year}-{month_idx0+1:02d}-{day:02d} {hour:02d}h: LZMA decode failure, skipping hour")
                continue

            if len(decoded) % TICK_SIZE != 0:
                log(f"    {pair} {year}-{month_idx0+1:02d}-{day:02d} {hour:02d}h: bad tick length {len(decoded)}, skipping")
                continue

            for bar in aggregate_day_to_m1(pair, year, month_idx0, day, iter_ticks(decoded)):
                ts, o, h, l, c, v = bar
                # Overwrite if duplicate timestamp (shouldn't happen; defensive).
                bars[ts] = [ts, o, h, l, c, v]

    return [bars[k] for k in sorted(bars.keys())]


# -----------------------------------------------------------------------------
# CSV I/O
# -----------------------------------------------------------------------------

def _csv_path(out_dir: Path, pair: str, year: int, month_idx0: int) -> Path:
    return out_dir / f"{pair.upper()}_M1_{year:04d}-{month_idx0 + 1:02d}.csv"


def write_month_csv(out_dir: Path, pair: str, year: int, month_idx0: int, bars: list) -> Path:
    path = _csv_path(out_dir, pair, year, month_idx0)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write atomically via a temp file.
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for ts, o, h, l, c, v in bars:
            w.writerow([
                ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                f"{o:.5f}",
                f"{h:.5f}",
                f"{l:.5f}",
                f"{c:.5f}",
                int(v),
            ])
    os.replace(tmp, path)
    return path


def month_already_downloaded(out_dir: Path, pair: str, year: int, month_idx0: int) -> bool:
    """Resume rule: skip if the target CSV exists and has at least one data row."""
    path = _csv_path(out_dir, pair, year, month_idx0)
    if not path.exists():
        return False
    try:
        with open(path, "rb") as f:
            # 1 line header + >= 1 data row = at least 2 lines
            line_count = sum(1 for _ in f)
        return line_count >= 2
    except OSError:
        return False


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


def month_iter(start: str, end: str) -> Iterator[tuple[int, int]]:
    """Yield (year, month_idx0) for every month in [start, end] inclusive.

    `start` and `end` are 'YYYY-MM' strings.
    """
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    cur = datetime(sy, sm, 1)
    end_dt = datetime(ey, em, 1)
    while cur <= end_dt:
        yield cur.year, cur.month - 1
        # advance one month
        if cur.month == 12:
            cur = datetime(cur.year + 1, 1, 1)
        else:
            cur = datetime(cur.year, cur.month + 1, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2015-01", help="First month, inclusive (YYYY-MM)")
    parser.add_argument("--end", default="2023-12", help="Last month, inclusive (YYYY-MM)")
    parser.add_argument("--pairs", nargs="+", default=DEFAULT_PAIRS,
                        help="Pairs to download (uppercase). Default: %(default)s")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                        help="Output directory (default: %(default)s)")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-month progress logging")
    parser.add_argument("--max-hours", type=int, default=0,
                        help="Cap on hour-files fetched per (pair, month). "
                             "0 = no cap (default). Useful for smoke tests.")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pairs = [p.upper() for p in args.pairs]
    bad = [p for p in pairs if p not in PRICE_SCALES]
    if bad:
        _log(f"ERROR: no price scale configured for: {bad}. Known: {sorted(PRICE_SCALES)}")
        return 2

    log = (lambda m: None) if args.quiet else _log

    _log(f"=== Dukascopy M1 downloader ===")
    _log(f"pairs    : {pairs}")
    _log(f"window   : {args.start} -> {args.end}")
    _log(f"out_dir  : {out_dir.resolve()}")
    _log(f"approx.  : {len(pairs)} pairs × {sum(1 for _ in month_iter(args.start, args.end))} months = "
          f"{len(pairs) * sum(1 for _ in month_iter(args.start, args.end))} (pair, month) jobs")

    runs = list(month_iter(args.start, args.end))
    total_jobs = len(pairs) * len(runs)
    completed = 0
    skipped = 0
    failed = 0

    for pair in pairs:
        for year, month_idx0 in runs:
            completed += 1
            label = f"{pair} {year:04d}-{month_idx0 + 1:02d}"
            if month_already_downloaded(out_dir, pair, year, month_idx0):
                _log(f"[{completed}/{total_jobs}] skip {label} (csv exists)")
                skipped += 1
                continue

            _log(f"[{completed}/{total_jobs}] downloading {label} ...")
            try:
                bars = aggregate_month(
                    pair, year, month_idx0, log=log, max_hours=args.max_hours,
                )
            except Exception as e:
                _log(f"  FAILED {label}: {type(e).__name__}: {e}")
                failed += 1
                continue

            if not bars:
                _log(f"  no ticks for {label}; writing empty csv with header only")
                path = write_month_csv(out_dir, pair, year, month_idx0, [])
                _log(f"  -> {path.name} (0 bars)")
            else:
                path = write_month_csv(out_dir, pair, year, month_idx0, bars)
                _log(f"  -> {path.name} ({len(bars)} M1 bars)")

            # Respectful pause between months — Dukascopy throttles hard.
            if not (pair == pairs[-1] and (year, month_idx0) == runs[-1]):
                time.sleep(INTER_MONTH_SLEEP)

    _log(f"=== done ===")
    _log(f"downloaded: {total_jobs - skipped - failed}, skipped: {skipped}, failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
