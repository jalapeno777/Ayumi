#!/usr/bin/env python3
"""Export the matrix data subset (XAUUSD + GBPUSD M15 + H1) to a worker-local DuckDB.

Card 05fa0065 Phase 1b: the worker (ava-worker-local) needs its own DuckDB
data source containing ONLY the bars the 68-cell matrix consumes. The main
ayumi_market.duckdb is 53GB — copying it to the worker would burn hours +
disk and violate the "do NOT copy the 53GB DuckDB" directive. This script:

1. Opens the main DuckDB read-only.
2. SELECTs the bars matching (symbol, timeframe) for XAUUSD + GBPUSD × {M15, H1}.
3. Writes them to a fresh DuckDB at the target path (compressed + read-only
   compatible with the harness's AYUMI_DUCKDB_PATH override).
4. Records the SHA256 of the subset DB so the dispatcher can carry it in
   every cell descriptor for drift detection.

The export runs ONCE per sprint on the worker side (post-clone, pre-run).
Output is small (a few hundred MB) and verifiable via the db_sha.

Usage (on the worker after the Ayumi checkout is in place):
    python3 scripts/export_matrix_data_subset.py \
        --source-db /home/TacoPants/projects/Ayumi/data/ayumi_market.duckdb \
        --output-db /home/TacoPants/ayumi-data/matrix-2026-09-15.duckdb \
        --symbols XAUUSD,GBPUSD \
        --timeframes M15,H1

Prints a JSON line on success:
    {"db_sha": "<sha256>", "n_rows": <int>, "n_symbols": <int>, "output_path": "..."}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# Make ``src`` importable when invoked as a script (matches the runner's
# sys.path discipline).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import duckdb  # noqa: E402


# Card 05fa0065 spec: XAUUSD + GBPUSD × M15 + H1. Kept module-level so the
# dispatcher-side CLI default matches the worker-side export default
# (single source of truth = same script).
DEFAULT_SYMBOLS: tuple[str, ...] = ("XAUUSD", "GBPUSD")
DEFAULT_TIMEFRAMES: tuple[str, ...] = ("M15", "H1")


def _sha256_file(path: Path) -> str:
    """Streamed SHA256 over a local file (no full-file read)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def export_subset(
    *,
    source_db: Path,
    output_db: Path,
    symbols: list[str],
    timeframes: list[str],
) -> dict[str, object]:
    """Export ``symbols × timeframes`` from ``source_db`` to ``output_db``.

    Returns a result dict with ``db_sha``, ``n_rows``, ``n_symbols``,
    ``output_path``. The output DB has the canonical bars table the
    harness expects (``symbol``, ``timeframe``, ``timestamp_utc``,
    ``open``, ``high``, ``low``, ``close``, ``volume``, ``spread_pips``).
    """
    if not source_db.is_file():
        raise FileNotFoundError(f"source_db not found: {source_db}")
    output_db.parent.mkdir(parents=True, exist_ok=True)
    # Refuse to overwrite an existing target — the worker's worker_runner
    # trusts the db_sha is consistent. If the operator wants to refresh,
    # they delete the file first.
    if output_db.is_file():
        raise FileExistsError(
            f"output_db already exists: {output_db} — delete it first "
            f"if you want to refresh the export"
        )

    src_con = duckdb.connect(str(source_db), read_only=True)
    try:
        # Probe row count before writing (helps verify source has the data).
        placeholders = ",".join(["?"] * len(symbols))
        tf_placeholders = ",".join(["?"] * len(timeframes))
        count_query = (
            f"SELECT COUNT(*) FROM bars "
            f"WHERE symbol IN ({placeholders}) "
            f"AND timeframe IN ({tf_placeholders})"
        )
        n_rows = src_con.execute(
            count_query, [*symbols, *timeframes]
        ).fetchone()[0]
        if n_rows == 0:
            raise RuntimeError(
                f"source_db {source_db} has 0 rows for {symbols} × {timeframes}; "
                f"check the symbol/timeframe spelling"
            )
    finally:
        src_con.close()

    # Export via ATTACH — read source, write to fresh destination DB.
    # Uses parameterized queries (DuckDB ? placeholders) so symbol/tf
    # strings can never break out into SQL.
    src_con = duckdb.connect(str(source_db), read_only=True)
    dst_con = duckdb.connect(str(output_db))
    try:
        dst_con.execute(f"ATTACH '{source_db}' AS src_ro (READ_ONLY)")
        dst_con.execute(
            f"CREATE OR REPLACE TABLE bars AS "
            f"SELECT symbol, timeframe, timestamp_utc, open, high, low, "
            f"close, volume, spread_pips "
            f"FROM src_ro.bars "
            f"WHERE symbol IN ({placeholders}) "
            f"AND timeframe IN ({tf_placeholders}) "
            f"ORDER BY symbol, timeframe, timestamp_utc ASC",
            [*symbols, *timeframes],
        )
        # Confirm row count via the new DB.
        n_rows_exported = dst_con.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
        dst_con.execute("DETACH src_ro")
    finally:
        dst_con.close()
        src_con.close()

    db_sha = _sha256_file(output_db)
    return {
        "db_sha": db_sha,
        "n_rows": int(n_rows_exported),
        "n_symbols": len(symbols),
        "n_timeframes": len(timeframes),
        "symbols": list(symbols),
        "timeframes": list(timeframes),
        "output_path": str(output_db),
        "source_path": str(source_db),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="export_matrix_data_subset",
        description=(
            "Export the tournament matrix's data subset (XAUUSD + GBPUSD × "
            "M15 + H1) from the main DuckDB to a worker-local DuckDB. "
            "Card 05fa0065 Phase 1b: do NOT copy the 53GB full DB to the "
            "worker; export only the bars the 68 cells need."
        ),
    )
    parser.add_argument(
        "--source-db", required=True,
        help="Path to the main DuckDB (read-only).",
    )
    parser.add_argument(
        "--output-db", required=True,
        help="Path where the subset DuckDB will be written.",
    )
    parser.add_argument(
        "--symbols", default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated symbols to include (default: %(default)s)",
    )
    parser.add_argument(
        "--timeframes", default=",".join(DEFAULT_TIMEFRAMES),
        help="Comma-separated timeframes to include (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    timeframes = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]
    if not symbols or not timeframes:
        print("ERROR: --symbols and --timeframes must be non-empty", file=sys.stderr)
        return 2

    try:
        result = export_subset(
            source_db=Path(args.source_db).expanduser().resolve(),
            output_db=Path(args.output_db).expanduser().resolve(),
            symbols=symbols,
            timeframes=timeframes,
        )
    except (FileNotFoundError, FileExistsError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    # Single JSON line on stdout for the dispatcher to consume.
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
