#!/usr/bin/env python3
"""Initialize Ayumi market DuckDB with tick storage and bar aggregation.

Creates data/ayumi_market.duckdb with:
- ticks table (source of truth)
- bars table (pre-materialized OHLCV from ticks)
- generate_bars() function to rebuild bars at any timeframe

Usage:
    python3 scripts/init_tick_db.py [--db-path data/ayumi_market.duckdb]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

DEFAULT_DB_PATH = Path("data/ayumi_market.duckdb")


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))

    # --- Ticks table (source of truth) ---
    con.execute("""
        CREATE TABLE IF NOT EXISTS ticks (
            timestamp_ms BIGINT NOT NULL,
            symbol       TEXT NOT NULL,
            bid          DOUBLE NOT NULL,
            ask          DOUBLE NOT NULL,
            bid_vol      DOUBLE DEFAULT 0.0,
            ask_vol      DOUBLE DEFAULT 0.0
        )
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts
        ON ticks(symbol, timestamp_ms)
    """)
    con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ticks_unique
        ON ticks(timestamp_ms, symbol)
    """)

    # --- Bars table (pre-materialized for DbDataLoader compatibility) ---
    con.execute("""
        CREATE TABLE IF NOT EXISTS bars (
            symbol         TEXT NOT NULL,
            timeframe      TEXT NOT NULL,
            timestamp_utc  BIGINT NOT NULL,
            open           DOUBLE NOT NULL,
            high           DOUBLE NOT NULL,
            low            DOUBLE NOT NULL,
            close          DOUBLE NOT NULL,
            volume         BIGINT NOT NULL DEFAULT 0,
            spread_pips    DOUBLE DEFAULT 0.0
        )
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_bars_symbol_tf_ts
        ON bars(symbol, timeframe, timestamp_utc)
    """)

    # --- Meta table for tracking imports ---
    con.execute("""
        CREATE TABLE IF NOT EXISTS import_log (
            filename     TEXT UNIQUE NOT NULL,
            symbol       TEXT NOT NULL,
            row_count    BIGINT NOT NULL,
            imported_at  TEXT NOT NULL
        )
    """)

    con.close()
    print(f"✅ Initialized {db_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    args = ap.parse_args()
    init_db(args.db_path)
