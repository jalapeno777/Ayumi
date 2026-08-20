#!/usr/bin/env python3
"""Synthesize higher-timeframe OHLCV bars from a base TF (M1 preferred).

Phase 9b of Ayumi's market data analytics roadmap.

Given a base-TF OHLCV CSV (ideally M1), resample to higher timeframes:

    M1  -> M5,  M10, M15, M30, H1, H4
    M15 -> M30, H1, H4  (only if no M1 exists for the pair)

For every output bar:

    timestamp = first base TF bar in the window
    open      = first base TF bar in the window
    high      = max   base TF high
    low       = min   base TF low
    close     = last  base TF close
    volume    = sum   base TF volumes

Empty windows (no source bars in the bucket) are dropped. Two output
modalities are available:

    * Writes one CSV per (pair, target TF) to ``data/forex/synthesized/``.
      CSV files share the *exact* column layout of the source CSV
      (``timestamp,Open,High,Low,Close,Volume``) so downstream loaders
      can ingest them like any other Ayumi market-data file.
    * Optional ``--duckdb`` import: load each synthesized CSV into
      ``data/ayumi_market.duckdb`` via the ``bars`` table; uses
      ``ON CONFLICT (symbol, timeframe, timestamp_utc) DO NOTHING`` so
      re-runs cleanly accumulate without duplicates.

Usage::

    python scripts/synthesize_timeframes.py --duckdb \\
        --pairs EURUSD GBPUSD USDJPY XAUUSD
    python scripts/synthesize_timeframes.py --source-dir ... --out-dir ...
    python scripts/synthesize_timeframes.py  # dry-run preview, no write

Tests with the data that already exists in ``data/forex/historical/`` —
no Dukascopy download required.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("synthesize")

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "data" / "forex" / "historical"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "forex" / "synthesized"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "ayumi_market.duckdb"

# Base-TF minutes (lowercase key). Use these to label pandas resample strings.
TF_MINUTES: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M10": 10,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

# Pandas frequency strings per timeframe.
TF_FREQ: dict[str, str] = {
    "M1": "1min",
    "M5": "5min",
    "M10": "10min",
    "M15": "15min",
    "M30": "30min",
    "H1": "60min",
    "H4": "240min",
    "D1": "1D",
}

# Universal targets produced from any base TF whose period divides them all
# (so e.g. M15 -> M30, H1, H4 — M5 is *not* generated from a 15-minute base).
ALL_TARGETS: tuple[str, ...] = ("M5", "M10", "M15", "M30", "H1", "H4")

# Filename pattern mirrors scripts/download_dukascopy.py + scripts/migrate_csv_to_duckdb.py
# so symbol/timeframe inference stays consistent across the pipeline.
_FILENAME_RE = re.compile(
    r"^(?P<pair>[A-Z]{6})_(?P<tf>M(?:N)?\d{1,2}|H\d{1,2}|D\d{1,2})(?:_(?P<suffix>[a-zA-Z0-9_]+))?$"
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


@dataclass
class SynthResult:
    """One (pair, target_tf) row emitted by the synthesizer."""

    pair: str
    source_tf: str
    target_tf: str
    source_rows: int
    target_rows: int
    csv_path: Path = field(default_factory=Path)
    db_rows_inserted: int = 0


def parse_filename(path: Path) -> tuple[str, str] | None:
    """Return (pair, tf) from a CSV filename, or None if it isn't market data."""
    m = _FILENAME_RE.match(path.stem.upper())
    if not m:
        return None
    return m.group("pair"), m.group("tf")


def load_csv(path: Path) -> pd.DataFrame:
    """Load a CSV file and normalise it to the canonical 6-column layout.

    Returns a DataFrame with columns::

        timestamp (datetime64[ns, UTC]), open, high, low, close, volume

    Robust against the two existing on-disk dialects (the legacy
    ``Date,Open,High,Low,Close,Volume`` and the Dukascopy-style
    ``timestamp,Open,High,Low,Close,Volume``).
    """
    # Sniff the header so we can pick the timestamp column.
    with open(path, "r", newline="") as f:
        header = f.readline().strip().split(",")

    norm = {h.strip().lower(): h for h in header}
    ts_col = None
    for cand in ("timestamp", "date", "datetime", "time"):
        if cand in norm:
            ts_col = norm[cand]
            break
    if ts_col is None:
        raise ValueError(f"{path}: no timestamp column (header={header})")

    wanted = [ts_col, "Open", "High", "Low", "Close", "Volume"]
    try:
        df = pd.read_csv(path, usecols=wanted)
    except (ValueError, KeyError):
        df = pd.read_csv(path)

    df = df.rename(
        columns={
            ts_col: "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    if "timestamp" not in df.columns:
        df = df.rename(columns={df.columns[0]: "timestamp"})

    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    bad = int(ts.isna().sum())
    if bad == len(ts):
        raise ValueError(f"{path}: all timestamps unparseable")
    if bad:
        log.warning("[%s] dropped %d rows with unparseable timestamps", path.name, bad)
        df = df.loc[ts.notna()].copy()
        ts = ts.loc[ts.notna()]

    df["timestamp"] = ts
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    else:
        df["volume"] = 0

    df = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def select_targets(source_tf: str) -> list[str]:
    """Targets feasible from ``source_tf`` at integer-multiple granularity."""
    src = TF_MINUTES.get(source_tf)
    if src is None:
        return []
    out = []
    for tgt in ALL_TARGETS:
        tgt_m = TF_MINUTES[tgt]
        if tgt_m % src == 0 and tgt_m > src:
            out.append(tgt)
    return out


def resample(df: pd.DataFrame, source_tf: str, target_tf: str) -> pd.DataFrame:
    """Resample OHLCV rows from ``source_tf`` to ``target_tf``.

    Empty windows (no source bar in the bucket) are dropped — those are
    what would otherwise pollute the output with NaN bars.
    """
    freq = TF_FREQ[target_tf]
    indexed = df.set_index("timestamp")
    agg = indexed.resample(freq).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    # Empty buckets have NaN open (no "first" value) — drop them.
    return agg.dropna(subset=["open"]).reset_index()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    """Write synthesised bars to a CSV matching the source file's dialect."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use Dukascopy-style lowercase header + ISO 8601 UTC timestamp.
    # Same layout written by ``scripts/download_dukascopy.py``.
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for ts, o, h, low_val, c, v in df.itertuples(index=False, name=None):
            w.writerow(
                [
                    pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    f"{o:.5f}",
                    f"{h:.5f}",
                    f"{low_val:.5f}",
                    f"{c:.5f}",
                    int(v),
                ]
            )


# -----------------------------------------------------------------------------
# DuckDB import
# -----------------------------------------------------------------------------


def import_to_duckdb(
    df: pd.DataFrame,
    *,
    pair: str,
    target_tf: str,
    db_path: Path,
) -> int:
    """Insert synthesised rows into the existing ``bars`` table.

    Returns the number of rows actually inserted (conflicts are silently
    skipped by ``ON CONFLICT DO NOTHING``).
    """
    if df.empty:
        return 0
    # Force the timestamps to nanosecond precision before converting to
    # Unix epoch seconds. pandas resample returns datetime64[us] (or worse)
    # and the int64 representation is microseconds; dividing by 1e9 on
    # microseconds truncates aggressively and silently buckets distinct
    # timestamps into the same second, which trips the unique-index in
    # DuckDB with a “Data contains duplicates on indexed column(s)” error.
    ts_utc = pd.to_datetime(df["timestamp"], utc=True)
    # `tz_convert(None)` would give a tz-naive timestamp in UTC; explicit
    # `.tz_localize(None)` after UTC conversion avoids pandas' strict-mode
    # complaint about converting from a tz-aware to tz-naive dtype.
    ts_naive_ns = ts_utc.dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[ns]")
    seconds_int64 = (ts_naive_ns.astype("int64") // 1_000_000_000).astype("int64")
    is_holdout = pd.DatetimeIndex(ts_naive_ns).year >= 2023
    out = pd.DataFrame(
        {
            "timestamp_utc": seconds_int64,
            "symbol": pair,
            "timeframe": target_tf,
            "open": df["open"].astype("float64"),
            "high": df["high"].astype("float64"),
            "low": df["low"].astype("float64"),
            "close": df["close"].astype("float64"),
            "volume": df["volume"].astype("int64"),
            "spread_pips": 0.0,
            "is_holdout": is_holdout,
        }
    )

    con = duckdb.connect(str(db_path))
    try:
        con.register("staging_synth", out)
        before = con.execute(
            "SELECT COUNT(*) FROM bars WHERE symbol = ? AND timeframe = ?",
            [pair, target_tf],
        ).fetchone()[0]
        # Anti-join instead of ON CONFLICT: the ``bars`` table only has a
        # non-unique index on (symbol, timeframe, timestamp_utc), so DuckDB's
        # ``ON CONFLICT`` clause can't reference any PRIMARY KEY or UNIQUE
        # constraint and would error. Filtering out conflicts in a CTE
        # keeps the insert idempotent without modifying the schema.
        con.execute(
            """
            INSERT INTO bars(
                timestamp_utc, symbol, timeframe,
                open, high, low, close, volume,
                spread_pips, is_holdout
            )
            SELECT
                s.timestamp_utc, s.symbol, s.timeframe,
                s.open, s.high, s.low, s.close, s.volume,
                s.spread_pips, s.is_holdout
            FROM staging_synth s
            WHERE NOT EXISTS (
                SELECT 1 FROM bars b
                WHERE b.symbol = s.symbol
                  AND b.timeframe = s.timeframe
                  AND b.timestamp_utc = s.timestamp_utc
            )
            """
        )
        con.unregister("staging_synth")
        after = con.execute(
            "SELECT COUNT(*) FROM bars WHERE symbol = ? AND timeframe = ?",
            [pair, target_tf],
        ).fetchone()[0]
        return int(after - before)
    finally:
        con.close()


# -----------------------------------------------------------------------------
# Pipeline
# -----------------------------------------------------------------------------


def discover_pairs(
    source_dir: Path,
    pairs_filter: Iterable[str] = (),
) -> list[tuple[str, Path, str]]:
    """Return ``[(pair, csv_path, timeframe)]`` sorted by (pair, tf).

    Prefers M1 files when they exist; otherwise picks the smallest
    available TF for the pair. Multi-file pairs (e.g. base + ``_fresh``)
    take the alphabetically-first match — caller can override via
    ``--prefer-suffix``.
    """
    wanted = {p.upper() for p in pairs_filter} if pairs_filter else None
    by_pair: dict[str, list[tuple[str, Path, str]]] = {}
    if not source_dir.exists():
        return []
    for p in sorted(source_dir.glob("*.csv")):
        meta = parse_filename(p)
        if meta is None:
            continue
        pair, tf = meta
        if wanted is not None and pair not in wanted:
            continue
        by_pair.setdefault(pair, []).append((pair, p, tf))

    out: list[tuple[str, Path, str]] = []
    for pair, candidates in sorted(by_pair.items()):  # noqa: B007
        # Prefer smallest TF available, then by filename ascending.
        candidates.sort(key=lambda c: (TF_MINUTES.get(c[2], 10**6), c[1].name))
        out.append(candidates[0])
    return out


def synthesise_pair(
    pair: str,
    csv_path: Path,
    source_tf: str,
    targets: list[str],
    output_dir: Path,
    do_write_csv: bool,
    duckdb_path: Path | None,
) -> list[SynthResult]:
    """Resample one (pair, source_tf) file into all target timeframes."""
    try:
        df = load_csv(csv_path)
    except Exception as e:
        log.error("[%s] load failed: %s", csv_path.name, e)
        return []

    if df.empty:
        log.warning("[%s] empty source; nothing to synthesize", csv_path.name)
        return []

    feasible = [t for t in targets if TF_MINUTES[t] % TF_MINUTES[source_tf] == 0]
    if not feasible:
        log.warning(
            "[%s] source tf=%s cannot synthesize any of %s; skipping",
            csv_path.name,
            source_tf,
            targets,
        )
        return []

    log.info(
        "[%s] source tf=%s rows=%d  targets=%s",
        pair,
        source_tf,
        len(df),
        feasible,
    )

    results: list[SynthResult] = []
    for tgt in feasible:
        try:
            synth = resample(df, source_tf, tgt)
        except Exception as e:
            log.error("  -> %s resample failed: %s", tgt, e)
            continue

        out_path = output_dir / f"{pair}_{tgt}.csv"
        if do_write_csv:
            write_csv(synth, out_path)

        n_db = 0
        if duckdb_path is not None:
            try:
                n_db = import_to_duckdb(
                    synth,
                    pair=pair,
                    target_tf=tgt,
                    db_path=duckdb_path,
                )
            except Exception as e:
                log.error("  -> %s duckdb import failed: %s", tgt, e)

        results.append(
            SynthResult(
                pair=pair,
                source_tf=source_tf,
                target_tf=tgt,
                source_rows=len(df),
                target_rows=len(synth),
                csv_path=out_path,
                db_rows_inserted=n_db,
            )
        )
        log.info(
            "  -> %s: %d bars  csv=%s  db+=%d",
            tgt,
            len(synth),
            out_path.name if do_write_csv else "(skipped)",
            n_db,
        )

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source-dir",
        default=str(DEFAULT_SOURCE_DIR),
        help="Where to read source CSVs from (default: %(default)s)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Where to write synthesised CSVs (default: %(default)s)",
    )
    parser.add_argument(
        "--pairs",
        nargs="*",
        default=[],
        help="Restrict to these pairs (e.g. EURUSD XAUUSD). Default: all pairs.",
    )
    parser.add_argument(
        "--targets",
        nargs="*",
        default=list(ALL_TARGETS),
        help=f"Target timeframes to produce (default: {' '.join(ALL_TARGETS)})",
    )
    parser.add_argument(
        "--duckdb",
        action="store_true",
        help="Also import synthesised bars into the market DuckDB.",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="DuckDB path (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip both CSV writes and DuckDB imports (report only).",
    )
    args = parser.parse_args(argv)

    source_dir = Path(args.source_dir)
    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = discover_pairs(source_dir, args.pairs)
    if not candidates:
        log.error("No eligible OHLCV CSVs found in %s", source_dir)
        return 1

    log.info("Discovered %d pair(s) for synthesis", len(candidates))
    for pair, p, tf in candidates:
        log.info("  %s <- %s (source tf=%s)", pair, p.name, tf)

    db_path: Path | None = None
    if args.duckdb and not args.dry_run:
        db_path = Path(args.db_path)
        if not db_path.exists():
            log.error(
                "DuckDB not found at %s; rerun without --duckdb or migrate first.",
                db_path,
            )
            return 2

    all_results: list[SynthResult] = []
    for pair, p, tf in candidates:
        if args.dry_run:
            # Still dry-resample to compute counts without writing.
            try:
                df = load_csv(p)
            except Exception as e:
                log.error("[%s] load failed: %s", p.name, e)
                continue
            feasible = [t for t in args.targets if TF_MINUTES[t] % TF_MINUTES[tf] == 0]
            for tgt in feasible:
                try:
                    synth = resample(df, tf, tgt)
                except Exception as e:
                    log.error("  -> %s resample failed: %s", tgt, e)
                    continue
                all_results.append(
                    SynthResult(
                        pair=pair,
                        source_tf=tf,
                        target_tf=tgt,
                        source_rows=len(df),
                        target_rows=len(synth),
                    )
                )
                log.info(
                    "  [dry] %s -> %s: %d bars (from %d source rows)",
                    pair,
                    tgt,
                    len(synth),
                    len(df),
                )
            continue
        all_results.extend(synthesise_pair(pair, p, tf, args.targets, output_dir, True, db_path))

    # ---- Summary ---------------------------------------------------------
    log.info("=== synthesis summary ===")
    by_tf: dict[str, list[SynthResult]] = {}
    for r in all_results:
        by_tf.setdefault(r.target_tf, []).append(r)
    for tf in sorted(by_tf, key=lambda t: TF_MINUTES.get(t, 0)):
        rows = by_tf[tf]
        avg = sum(r.target_rows for r in rows) // max(1, len(rows))
        log.info(
            "  %s: %d pair(s), avg %d bars/pair (db_inserted=%d)",
            tf,
            len(rows),
            avg,
            sum(r.db_rows_inserted for r in rows),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
