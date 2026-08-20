#!/usr/bin/env python3
"""Initialize SQLite database and migrate CSV data for Ayumi Forex."""

import sqlite3  # noqa: I001
import csv
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "forex.db"
DATA_DIR = Path(__file__).parent / "historical"


def create_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS candles (
            symbol     TEXT NOT NULL,
            timeframe  TEXT NOT NULL,
            timestamp  INTEGER NOT NULL,
            open       REAL,
            high       REAL,
            low        REAL,
            close      REAL,
            volume     REAL DEFAULT 0,
            PRIMARY KEY (symbol, timeframe, timestamp)
        );

        CREATE INDEX IF NOT EXISTS idx_candles_symbol_tf
            ON candles(symbol, timeframe);

        CREATE INDEX IF NOT EXISTS idx_candles_time
            ON candles(symbol, timeframe, timestamp);

        CREATE TABLE IF NOT EXISTS backtest_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_name    TEXT NOT NULL,
            symbol      TEXT,
            timeframe   TEXT,
            config_json TEXT,
            metrics_json TEXT,
            created_at  INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            backtest_id INTEGER REFERENCES backtest_results(id),
            symbol      TEXT,
            direction   TEXT,
            entry_time  INTEGER,
            exit_time   INTEGER,
            entry_price REAL,
            exit_price  REAL,
            sl_price    REAL,
            tp_price    REAL,
            lots        REAL,
            pnl         REAL,
            pips        REAL,
            outcome     TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_trades_backtest
            ON trades(backtest_id);
    """)
    conn.commit()


def parse_csv_file(csv_path: Path) -> list:
    """Parse a CSV file and return rows as dicts."""
    rows = []
    # Try to detect format
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def infer_symbol_timeframe(filename: str) -> tuple:
    """Extract symbol and timeframe from filename like EURUSD_M15.csv."""
    name = Path(filename).stem.upper()
    parts = name.rsplit("_", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return name, "D1"


def normalize_row(row: dict, symbol: str, timeframe: str) -> dict:
    """Normalize CSV row columns to standard names."""

    def get(keys, default=0.0):
        for k in keys:
            val = row.get(k)
            if val is not None:
                try:
                    return float(val.strip().replace(",", ""))
                except (ValueError, AttributeError):
                    continue
        return default

    # Timestamp detection
    ts_keys = ["timestamp", "time", "date", "datetime", "Date", "Time", "Local time"]
    ts_val = None
    for k in ts_keys:
        val = row.get(k, "").strip()
        if val:
            # Try unix timestamp first
            try:
                ts_val = int(float(val))
                break
            except ValueError:
                pass
            # Try ISO/standard date formats
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y.%m.%d %H:%M:%S",
                "%Y.%m.%d %H:%M",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M",
                "%Y-%m-%d",
                "%d.%m.%Y",
            ):
                try:
                    from datetime import datetime

                    ts_val = int(datetime.strptime(val, fmt).timestamp())
                    break
                except ValueError:
                    continue
            if ts_val is not None:
                break

    if ts_val is None:
        return None

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": ts_val,
        "open": get(["open", "Open", "Open price", "open_price"]),
        "high": get(["high", "High", "High price", "high_price"]),
        "low": get(["low", "Low", "Low price", "low_price"]),
        "close": get(["close", "Close", "Close price", "close_price"]),
        "volume": get(["volume", "Volume", "Vol.", "Tick_volume", "Real_volume"]),
    }


def migrate_csv(conn, csv_path: Path, batch_size=5000):
    """Migrate a single CSV file into the candles table."""
    symbol, timeframe = infer_symbol_timeframe(csv_path.name)
    print(f"  Migrating {csv_path.name} → {symbol}/{timeframe} ...")

    rows = parse_csv_file(csv_path)
    if not rows:
        print("    ⚠️  No rows found")
        return 0

    inserted = 0
    skipped = 0
    batch = []

    for row in rows:
        normalized = normalize_row(row, symbol, timeframe)
        if normalized is None:
            skipped += 1
            continue
        batch.append(
            (
                normalized["symbol"],
                normalized["timeframe"],
                normalized["timestamp"],
                normalized["open"],
                normalized["high"],
                normalized["low"],
                normalized["close"],
                normalized["volume"],
            )
        )

        if len(batch) >= batch_size:
            conn.executemany(
                "INSERT OR IGNORE INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
            inserted += conn.total_changes
            batch = []

    if batch:
        conn.executemany(
            "INSERT OR IGNORE INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            batch,
        )

    count = conn.execute(
        "SELECT COUNT(*) FROM candles WHERE symbol=? AND timeframe=?",
        (symbol, timeframe),
    ).fetchone()[0]

    print(f"    ✅ {count} candles ({skipped} rows skipped)")
    return count


def main():
    if DB_PATH.exists():
        print(f"⚠️  {DB_PATH} already exists. Remove it first to re-migrate.")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    print("Creating schema...")
    create_schema(conn)

    print("\nMigrating CSV files...")
    csv_files = sorted(DATA_DIR.glob("*.csv"))
    if not csv_files:
        print("  No CSV files found in", DATA_DIR)
    else:
        for csv_file in csv_files:
            migrate_csv(conn, csv_file)

    total = conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
    symbols = conn.execute("SELECT DISTINCT symbol FROM candles").fetchall()
    print(f"\n📊 Total candles in DB: {total:,}")
    print(f"   Symbols: {', '.join(s[0] for s in symbols)}")

    for s in symbols:
        tfs = conn.execute(
            "SELECT timeframe, COUNT(*), MIN(timestamp), MAX(timestamp) FROM candles WHERE symbol=? GROUP BY timeframe",
            s,
        ).fetchall()
        for tf, count, min_ts, max_ts in tfs:
            from datetime import datetime

            start = datetime.utcfromtimestamp(min_ts).strftime("%Y-%m-%d")
            end = datetime.utcfromtimestamp(max_ts).strftime("%Y-%m-%d")
            print(f"   {s[0]} {tf}: {count:,} candles ({start} → {end})")

    conn.commit()
    conn.close()
    print(f"\n✅ Database created at {DB_PATH}")


if __name__ == "__main__":
    main()
