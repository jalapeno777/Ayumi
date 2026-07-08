#!/usr/bin/env python3
"""Migrate CSV OHLCV market data files to DuckDB.

Phase 8b of Ayumi's market data analytics roadmap.

Reads every `data/forex/historical/*.csv` that matches the
`<SYMBOL>_<TIMEFRAME>(_suffix)?.csv` pattern and writes the bars into
`data/ayumi_market.duckdb`. CSVs that are *not* OHLCV bars (feature
labels, walk-forward results, etc.) are skipped and logged.

Timestamp conventions (matches existing `data_loader.py`):
- `Date` column without timezone → treat as America/New_York local time,
  convert to UTC, store as Unix epoch seconds.
- `Datetime` column with timezone suffix (e.g. `+00:00`) → assume already
  UTC, parse the trailing offset.
- `timestamp` column without timezone → same as `Date` (NY-relative).

Idempotent: deleting/re-creating the database is the convention, but a
second run on the same DB drops rows for the same (symbol, timeframe)
before re-inserting, so file order doesn't matter.

Usage:
    python scripts/migrate_csv_to_duckdb.py [--db PATH] [--csv-dir PATH]

Default paths:
    --db       data/ayumi_market.duckdb
    --csv-dir  data/forex/historical

Outputs parity table to stdout AND to `data/ayumi_market_migration.parity.tsv`.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("migrate")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "ayumi_market.duckdb"
DEFAULT_CSV_DIR = PROJECT_ROOT / "data" / "forex" / "historical"

# Filename pattern: SYMBOL (e.g. XAUUSD) + "_" + TIMEFRAME (e.g. M15, H1, D1)
# Optional suffix (`_2026`, `_fresh`, ...). Both symbol and timeframe are
# upper-case letters + digits; timeframe MUST start with an uppercase
# letter followed by digits (e.g. M15, H1, D1), optionally combined with
# another letter (e.g. MN1).
FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z]{6})_(?P<tf>M(?:N)?\d{1,2}|H\d{1,2}|D\d{1,2}|W\d{1,2})(?:_(?P<suffix>[a-zA-Z0-9_]+))?\.csv$"
)

# Holdout start (per orchestrator: 2023+ rows are OOS holdout)
HOLDOUT_YEAR = 2023

# Symbols keyed off what the file pattern actually exposes (case-insensitive).
SYMBOL_DESCRIPTIONS = {
    "XAUUSD": "Gold vs US Dollar",
    "GBPUSD": "British Pound vs US Dollar",
    "EURUSD": "Euro vs US Dollar",
    "USDJPY": "US Dollar vs Japanese Yen",
    "GBPJPY": "British Pound vs Japanese Yen",
    "USDCAD": "US Dollar vs Canadian Dollar",
    "USDCHF": "US Dollar vs Swiss Franc",
}

# JPY pairs quote to 2 decimals (pip = 0.01). XAUUSD also quotes to 2
# decimals. Everything else quotes to 4 decimals (pip = 0.0001).
JPY_PAIR_PIP = 0.01
XAU_PAIR_PIP = 0.01
FX_PAIR_PIP = 0.0001


def pip_value_for(symbol: str) -> float:
    if symbol == "XAUUSD":
        return XAU_PAIR_PIP
    if symbol.endswith("JPY"):
        return JPY_PAIR_PIP
    return FX_PAIR_PIP


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

NY = "America/New_York"


def _parse_timestamp_series(series: pd.Series, file_label: str) -> pd.Series:
    """Parse a date-like Series into UTC pd.DatetimeIndex, return as Series."""
    s = series.astype(str)
    sample = s.iloc[0] if len(s) else ""

    # Pattern A: explicit ISO with timezone offset, e.g. '...+00:00'
    iso_tz_re = re.compile(r"[+-]\d{2}:?\d{2}$|Z$")
    if iso_tz_re.search(sample):
        ts = pd.to_datetime(s, utc=True, errors="coerce")
        if ts.isna().any():
            n_bad = int(ts.isna().sum())
            log.warning("[%s] %d rows failed ISO-UTC parse; dropping", file_label, n_bad)
        return ts

    # Pattern B: naive timestamp strings ("YYYY-MM-DD HH:MM[:SS]") → NY local
    ts = pd.to_datetime(s, errors="coerce")
    if ts.isna().any():
        n_bad = int(ts.isna().sum())
        log.warning("[%s] %d rows failed naive parse; dropping", file_label, n_bad)
    # Use NaT for both ambiguous and nonexistent — these DST-edge rows
    # correspond to wall-clock times that either don't exist (spring
    # forward) or exist twice (fall back). Forex market is closed at
    # those times anyway, so dropping is the honest thing. The few
    # edge rows that get hit by this will show up in bad_dropped.
    ts = ts.dt.tz_localize(NY, ambiguous="NaT", nonexistent="NaT")
    return ts.dt.tz_convert("UTC")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    log.info("Creating schema (bars, symbols, wf_results)")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS bars (
            timestamp_utc BIGINT,
            symbol        TEXT,
            timeframe     TEXT,
            open          DOUBLE,
            high          DOUBLE,
            low           DOUBLE,
            close         DOUBLE,
            volume        BIGINT,
            spread_pips   DOUBLE,
            is_holdout    BOOLEAN DEFAULT false
        );
        """
    )
    # The bars table doesn't have a UNIQUE/PRIMARY KEY constraint because
    # ON CONFLICT in DuckDB wants one. We express the natural key
    # (symbol, timeframe, timestamp_utc) via UNIQUE constraint below, but
    # only when the table is fresh. For an existing DB we leave the
    # schema as-is.
    if not con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'bars'"
    ).fetchone()[0]:
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_bars_pk "
            "ON bars(symbol, timeframe, timestamp_utc)"
        )
    # If we are running on an existing DB that was built before we added
    # this index, idempotently create it now (the migration will dedup).
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bars_unique "
        "ON bars(symbol, timeframe, timestamp_utc)"
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS symbols (
            symbol      TEXT PRIMARY KEY,
            pip_value   DOUBLE,
            description TEXT
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS wf_results (
            strategy  TEXT,
            symbol    TEXT,
            timeframe TEXT,
            params    JSON,
            metrics   JSON,
            run_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_bars_lookup ON bars(symbol, timeframe, timestamp_utc)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_bars_holdout ON bars(is_holdout)")


def populate_symbols(con: duckdb.DuckDBPyConnection) -> int:
    rows = [
        (sym, pip_value_for(sym), desc)
        for sym, desc in SYMBOL_DESCRIPTIONS.items()
    ]
    con.executemany(
        "INSERT INTO symbols(symbol, pip_value, description) VALUES (?, ?, ?) "
        "ON CONFLICT (symbol) DO UPDATE SET "
        "pip_value = EXCLUDED.pip_value, description = EXCLUDED.description",
        rows,
    )
    return len(rows)


def list_ohlcv_csvs(csv_dir: Path) -> list[Path]:
    out = []
    skipped = []
    for p in sorted(csv_dir.glob("*.csv")):
        m = FILENAME_RE.match(p.name)
        if not m:
            skipped.append(p.name)
            continue
        out.append(p)
    if skipped:
        log.info("Skipping non-OHLCV files: %s", skipped)
    return out


def migrate_file(con: duckdb.DuckDBPyConnection, csv_path: Path) -> dict:
    """Migrate one CSV. Returns dict with parity info."""
    m = FILENAME_RE.match(csv_path.name)
    symbol = m.group("symbol")
    timeframe = m.group("tf")
    suffix = m.group("suffix")

    log.info("Loading %s (symbol=%s tf=%s suffix=%s)",
             csv_path.name, symbol, timeframe, suffix or "-")

    # 1) Read with PyArrow (handles header auto-detection + types)
    try:
        table = pacsv.read_csv(
            str(csv_path),
            convert_options=pacsv.ConvertOptions(
                include_columns=None,
                auto_dict_encode=False,
                timestamp_parsers=["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"],
            ),
        )
    except Exception as exc:
        log.error("Failed to read %s: %s", csv_path.name, exc)
        return {"file": csv_path.name, "csv_rows": 0, "db_rows": 0,
                "match": False, "error": str(exc)}

    # 2) Normalise to pandas
    df = table.to_pandas()
    csv_row_count = len(df)

    # 3) Find date-like + OHLCV columns (case-insensitive)
    lower = {c.lower(): c for c in df.columns}
    ts_col = None
    for cand in ("date", "datetime", "timestamp", "time"):
        if cand in lower:
            ts_col = lower[cand]
            break
    if ts_col is None:
        log.error("[%s] no date-like column found; cols=%s", csv_path.name, list(df.columns))
        return {"file": csv_path.name, "csv_rows": csv_row_count, "db_rows": 0,
                "match": False, "error": "no-date-col"}
    cols_lower = {c.lower(): c for c in df.columns}
    open_c = cols_lower.get("open")
    high_c = cols_lower.get("high")
    low_c = cols_lower.get("low")
    close_c = cols_lower.get("close")
    if not all([open_c, high_c, low_c, close_c]):
        log.error("[%s] missing OHLC columns; cols=%s",
                  csv_path.name, list(df.columns))
        return {"file": csv_path.name, "csv_rows": csv_row_count, "db_rows": 0,
                "match": False, "error": "missing-ohlc"}

    # 4) Timestamp → UTC
    ts_utc = _parse_timestamp_series(df[ts_col], csv_path.name)

    # 5) Build clean DataFrame
    vol = pd.to_numeric(df.get(cols_lower.get("volume", "Volume"), 0),
                        errors="coerce").fillna(0).astype("int64")
    # pandas returns datetime64 in MICROSECONDS after tz_convert → divide by 1e6
    out = pd.DataFrame({
        "timestamp_utc": (ts_utc.astype("int64") // 1_000_000),  # µs → s
        "symbol": symbol,
        "timeframe": timeframe,
        "open": pd.to_numeric(df[open_c], errors="coerce"),
        "high": pd.to_numeric(df[high_c], errors="coerce"),
        "low": pd.to_numeric(df[low_c], errors="coerce"),
        "close": pd.to_numeric(df[close_c], errors="coerce"),
        "volume": vol,
        "spread_pips": pd.NA,  # populated below if ask cols present
    })
    # Drop rows with NaN prices or unparseable timestamps
    bad_mask = (
        out["timestamp_utc"].isna()
        | out["open"].isna() | out["high"].isna()
        | out["low"].isna() | out["close"].isna()
    )
    n_bad = int(bad_mask.sum())
    if n_bad:
        log.warning("[%s] dropping %d bad rows (NaN price or unparseable ts)",
                    csv_path.name, n_bad)
    out = out.loc[~bad_mask].copy()
    out["timestamp_utc"] = out["timestamp_utc"].astype("int64")

    # 6) is_holdout = year(timestamp_utc) >= HOLDOUT_YEAR
    year_utc = pd.to_datetime(out["timestamp_utc"], unit="s", utc=True).dt.year
    out["is_holdout"] = (year_utc >= HOLDOUT_YEAR).astype(bool)

    # 7) ask columns → spread_pips
    ask_open_c = cols_lower.get("ask_open")
    if ask_open_c is not None and open_c is not None:
        bid = pd.to_numeric(df.loc[out.index, open_c], errors="coerce")
        ask = pd.to_numeric(df.loc[out.index, ask_open_c], errors="coerce")
        price = bid.fillna(0)
        pv = price.apply(pip_value_for)
        spread = (ask - bid).abs() / pv
        out["spread_pips"] = spread

    # 8) DEDUP within the source CSV (rare but possible if a base file
    # has duplicate rows; keep the first occurrence).
    out = out.drop_duplicates(subset=["timestamp_utc"], keep="first")
    in_csv_dups = (csv_row_count - n_bad) - len(out)

    # 9) Insert (use a temp table so DuckDB doesn't have to infer types)
    con.register("staging_bars", out)
    # Use ON CONFLICT DO NOTHING so overlapping slices (e.g. fresh.csv
    # superseding the base file for a sub-range, or 2026 variants
    # redownloading the latest slice) cleanly accumulate without
    # overwriting earlier rows from other slices.
    con.execute(
        """
        INSERT INTO bars(
            timestamp_utc, symbol, timeframe,
            open, high, low, close, volume, spread_pips, is_holdout
        )
        SELECT
            timestamp_utc, symbol, timeframe,
            open, high, low, close, volume, spread_pips, is_holdout
        FROM staging_bars
        ON CONFLICT (symbol, timeframe, timestamp_utc) DO NOTHING
        """
    )
    con.unregister("staging_bars")

    db_count = con.execute(
        "SELECT COUNT(*) FROM bars WHERE symbol = ? AND timeframe = ?",
        [symbol, timeframe],
    ).fetchone()[0]
    # Match means the DB has at least as many rows for this symbol/tf
    # as the CSV contributed unique timestamps. (Cumulative: if base +
    # fresh both cover the same range the second file's rows are
    # silently skipped, so db_count may EXCEED the file's count, which
    # is still a valid parity outcome.)
    csv_unique = len(out)
    match = (db_count >= csv_unique)
    log.info("  rows: csv=%d clean=%d db=%d %s",
             csv_row_count, csv_unique, db_count,
             "OK" if match else "MISMATCH")

    return {
        "file": csv_path.name,
        "symbol": symbol,
        "timeframe": timeframe,
        "csv_rows": csv_unique,
        "csv_raw": csv_row_count,
        "bad_dropped": n_bad,
        "in_csv_dups": in_csv_dups,
        "db_rows": db_count,
        "match": match,
    }


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_random_samples(con: duckdb.DuckDBPyConnection, n: int = 10, seed: int = 42) -> list[dict]:
    """Pull N random (symbol, timeframe, ts) tuples and verify OHLC match.

    Uses deterministic hash-based selection so the same rows are checked
    every run. Each result is a unique (symbol, timeframe, ts) tuple.
    """
    rs = con.execute(
        f"""
        SELECT symbol, timeframe, timestamp_utc, open, high, low, close
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY symbol, timeframe, timestamp_utc
                ORDER BY symbol, timeframe, timestamp_utc
            ) AS rn
            FROM bars
        ) WHERE rn = 1
        ORDER BY hash(symbol || '|' || timeframe || '|' || CAST(timestamp_utc AS VARCHAR))
        LIMIT {n}
        """
    ).fetchall()
    results = []
    for sym, tf, ts, o_db, h_db, l_db, c_db in rs:
        # Find the source CSV. If multiple files cover this symbol/timeframe
        # (e.g. base + fresh + 2026 variants), pick the one that has
        # this exact timestamp.
        candidates = sorted(
            (PROJECT_ROOT / "data" / "forex" / "historical").glob(
                f"{sym}_{tf}*.csv"
            )
        )
        csv_path = None
        match_ohlc = None
        for cand in candidates:
            try:
                df = pd.read_csv(cand)
            except Exception:
                continue
            ts_col = next((c for c in df.columns if c.lower() in
                           ("date", "datetime", "timestamp")), None)
            if ts_col is None:
                continue
            ts_series = _parse_timestamp_series(df[ts_col], cand.name)
            match_utc = (ts_series.astype("int64") // 1_000_000).astype("int64")
            mask = match_utc == int(ts)
            if mask.any():
                csv_path = cand
                row = df.loc[mask].iloc[0]
                match_ohlc = (float(row["Open"]), float(row["High"]),
                              float(row["Low"]), float(row["Close"]))
                break
        if csv_path is None or match_ohlc is None:
            results.append({"symbol": sym, "timeframe": tf, "ts": ts,
                            "match": False, "reason": "no-csv-row"})
            continue
        csv_open, csv_high, csv_low, csv_close = match_ohlc
        ok = (abs(csv_open - o_db) < 1e-5 and abs(csv_high - h_db) < 1e-5
              and abs(csv_low - l_db) < 1e-5 and abs(csv_close - c_db) < 1e-5)
        results.append({
            "symbol": sym, "timeframe": tf, "ts": int(ts),
            "csv_ohlc": match_ohlc,
            "db_ohlc": (o_db, h_db, l_db, c_db),
            "match": ok,
            "source": csv_path.name,
        })
    return results


def verify_dst_boundaries(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Spot check 3 DST boundaries (Sunday-open timezone behaviour).

    2024-03-10: 01:59 NY (EST last minute) → 06:59 UTC
    2024-03-10: 03:00 NY (EDT after spring forward) → 07:00 UTC
    2024-11-03: 02:00 NY (EST after fall back) → 07:00 UTC
    """
    # Expected values from zoneinfo (Python standard library).
    from datetime import datetime
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
    cases = [
        ("2024-03-10 01:59:00", 6, 59),    # EST last minute → 06:59 UTC
        ("2024-03-10 03:00:00", 7, 0),     # EDT first post-gap → 07:00 UTC
        ("2024-11-03 02:00:00", 7, 0),     # EST after fall-back → 07:00 UTC
    ]
    results = []
    for ts_str, exp_h, exp_m in cases:
        naive = datetime.fromisoformat(ts_str)
        ts_ny = naive.replace(tzinfo=NY)
        ts_utc = ts_ny.astimezone(ZoneInfo("UTC"))
        expected_epoch = int(ts_utc.timestamp())
        actual = con.execute(
            f"SELECT epoch(CAST('{ts_str} America/New_York' AS TIMESTAMPTZ))"
        ).fetchone()
        actual_epoch = int(actual[0]) if actual else None
        results.append({
            "input": ts_str + " America/New_York",
            "expected_epoch": expected_epoch,
            "actual_epoch": actual_epoch,
            "match": actual_epoch == expected_epoch,
        })
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB output path")
    parser.add_argument("--csv-dir", default=str(DEFAULT_CSV_DIR), help="CSV source directory")
    parser.add_argument("--keep-db", action="store_true",
                        help="Reuse existing DB (default: delete and recreate)")
    args = parser.parse_args()

    db_path = Path(args.db)
    csv_dir = Path(args.csv_dir)

    if not args.keep_db and db_path.exists():
        log.info("Removing existing DB at %s", db_path)
        db_path.unlink()
        wal_path = db_path.with_suffix(".duckdb.wal")
        if wal_path.exists():
            wal_path.unlink()

    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    create_schema(con)
    n_symbols = populate_symbols(con)
    log.info("Populated %d symbols rows", n_symbols)

    csvs = list_ohlcv_csvs(csv_dir)
    log.info("Found %d OHLCV CSVs to migrate", len(csvs))

    parity = []
    for csv_path in csvs:
        r = migrate_file(con, csv_path)
        parity.append(r)

    # Summary
    total_csv = sum(r["csv_rows"] for r in parity)
    total_db = sum(r["db_rows"] for r in parity)
    log.info("Total migrated rows: csv=%d db=%d", total_csv, total_db)

    # Per-file parity table
    print()
    print("=" * 100)
    print(f"{'file':<35} {'sym':<8} {'tf':<5} {'csv':>8} {'db':>8} {'dropped':>8} match")
    print("-" * 100)
    for r in parity:
        print(f"{r['file']:<35} {r.get('symbol', '?'):<8} "
              f"{r.get('timeframe', '?'):<5} "
              f"{r['csv_rows']:>8} {r['db_rows']:>8} "
              f"{r.get('bad_dropped', 0):>8} "
              f"{'YES' if r['match'] else 'NO'}")
    print("=" * 100)

    # Save parity to TSV for downstream consumption
    tsv_path = db_path.with_name(db_path.stem + "_migration.parity.tsv")
    with open(tsv_path, "w") as f:
        f.write("file\tsymbol\ttimeframe\tcsv_rows\tcsv_raw\tbad_dropped\tdb_rows\tmatch\n")
        for r in parity:
            f.write("\t".join(str(r.get(k, "")) for k in
                              ["file", "symbol", "timeframe",
                               "csv_rows", "csv_raw", "bad_dropped",
                               "db_rows", "match"]) + "\n")
    log.info("Parity TSV → %s", tsv_path)

    # Sample verification
    samples = verify_random_samples(con, n=10)
    print()
    print("=" * 100)
    print("Random sample verification (10 rows)")
    print("=" * 100)
    n_match = 0
    for r in samples:
        ok = "MATCH" if r["match"] else "MISMATCH"
        if r["match"]:
            n_match += 1
        if "csv_ohlc" in r:
            print(f"  [{ok}] {r['symbol']:<8} {r['timeframe']:<5} "
                  f"ts={r['ts']:<12} csv={r['csv_ohlc']} db={r['db_ohlc']}")
        else:
            print(f"  [{ok}] {r['symbol']:<8} {r['timeframe']:<5} "
                  f"ts={r['ts']:<12} reason={r.get('reason', '')}")
    print(f"  Sample match rate: {n_match}/{len(samples)}")

    # DST boundary verification
    dst = verify_dst_boundaries(con)
    print()
    print("=" * 100)
    print("DST boundary verification")
    print("=" * 100)
    for r in dst:
        ok = "OK" if r["match"] else "FAIL"
        print(f"  [{ok}] input={r['input']} expected_epoch={r['expected_epoch']} "
              f"actual_epoch={r['actual_epoch']}")

    # Sanity checks
    n_bars = con.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
    n_holdout = con.execute("SELECT COUNT(*) FROM bars WHERE is_holdout").fetchone()[0]
    n_spread = con.execute(
        "SELECT COUNT(*) FROM bars WHERE spread_pips IS NOT NULL"
    ).fetchone()[0]
    print()
    print("=" * 100)
    print("Database totals")
    print("=" * 100)
    print(f"  bars total    : {n_bars}")
    print(f"  bars holdout  : {n_holdout} (year >= {HOLDOUT_YEAR})")
    print(f"  bars w/spread : {n_spread}")
    print(f"  symbols       : {n_symbols} rows")
    # Force a full checkpoint + vacuum so the next reader doesn't have
    # to replay (or fail replaying) the WAL. DuckDB 1.5.x sometimes
    # hits an internal assertion in WAL replay after a heavy write
    # workload; checkpointing avoids that.
    log.info("Final CHECKPOINT + VACUUM")
    try:
        con.execute("CHECKPOINT")
        con.execute("VACUUM")
    except Exception as exc:
        log.warning("checkpoint/vacuum failed: %s", exc)
    # Drop the WAL so reopens don't have to replay anything.
    con.close()
    wal_path = db_path.with_suffix(".duckdb.wal")
    if wal_path.exists() and args.keep_db:
        log.info("WAL still present after checkpoint: %s", wal_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
