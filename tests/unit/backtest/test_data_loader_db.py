"""Tests for backtest.data_loader DB-first loaders.

Phase 10a. These tests cover the DB-first / CSV-fallback surface exposed by
the module-level functions:

* :func:`load_data` — DB-first, fallback to ``CsvDataLoader``.
* :func:`load_holdout` — DB query ``WHERE is_holdout = true``.
* :func:`load_training` — DB query ``WHERE is_holdout = false``.

The tests use a self-contained temporary DuckDB file when the assertion
requires precise control over the data state (e.g. verifying the
``is_holdout`` filter splits correctly). Live-DB integration tests are
guarded with ``@unittest.skipUnless`` so the suite still passes when the
``data/ayumi_market.duckdb`` file is absent.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import timezone
from pathlib import Path

import duckdb

from _project_root import PROJECT_ROOT

from backtest.data_loader import (
    DEFAULT_CSV_DIR,
    DEFAULT_DB_PATH,
    load_data,
    load_holdout,
    load_training,
)

DB_PATH = PROJECT_ROOT / "data" / "ayumi_market.duckdb"


def _db_available() -> bool:
    return DB_PATH.exists()


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _write_csv(path: Path, lines: list[str]) -> Path:
    """Write a 6-column OHLCV CSV with the header CsvDataLoader expects."""
    path.write_text("Date,Open,High,Low,Close,Volume\n" + "\n".join(lines) + "\n")
    return path


def _populate_temp_db(
    db_path: Path,
    rows: list[tuple[int, str, str, float, float, float, float, int, float, bool]],
) -> None:
    """Build a tiny DuckDB ``bars`` table from a row list.

    Each tuple is ``(timestamp_utc, symbol, timeframe, open, high, low, close,
    volume, spread_pips, is_holdout)``. This mirrors the schema produced by
    the Phase 8b migration.
    """
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE bars (
                timestamp_utc BIGINT,
                symbol VARCHAR,
                timeframe VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                spread_pips DOUBLE,
                is_holdout BOOLEAN
            )
            """
        )
        con.executemany(
            """
            INSERT INTO bars
                (timestamp_utc, symbol, timeframe, open, high, low, close,
                 volume, spread_pips, is_holdout)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    finally:
        con.close()


# ──────────────────────────────────────────────────────────────────────
# Test 1 — DB-first loading returns correct bars
# ──────────────────────────────────────────────────────────────────────


class TestLoadDataDbFirst(unittest.TestCase):
    """DB-first happy-path test using a controlled temporary DuckDB."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.db_path = self.tmpdir / "test.duckdb"
        # 2024-01-01 through 2024-01-03 (UTC). Mix holdout=true/false.
        _populate_temp_db(
            self.db_path,
            [
                # (ts, symbol, tf, o, h, l, c, vol, spread, is_holdout)
                (1704067200, "EURUSD", "M15", 1.1000, 1.1010, 1.0990, 1.1005, 100, 0.5, False),
                (1704068100, "EURUSD", "M15", 1.1005, 1.1020, 1.1000, 1.1015, 120, 0.6, False),
                (1704069000, "EURUSD", "M15", 1.1015, 1.1030, 1.1010, 1.1025, 130, 0.5, False),
                (1704069900, "EURUSD", "M15", 1.1025, 1.1040, 1.1020, 1.1035, 140, 0.5, True),
                (1704070800, "EURUSD", "M15", 1.1035, 1.1050, 1.1030, 1.1045, 150, 0.5, True),
            ],
        )

    def test_load_data_returns_all_rows_from_db(self) -> None:
        bars = load_data("EURUSD", "M15", db_path=self.db_path)
        self.assertEqual(len(bars), 5)
        # First and last timestamps bracket the full window.
        self.assertEqual(int(bars[0].time.timestamp()), 1704067200)
        self.assertEqual(int(bars[-1].time.timestamp()), 1704070800)
        # All bars are tz-aware UTC.
        for bar in bars:
            self.assertEqual(bar.time.tzinfo, timezone.utc)
        # OHLC spot check.
        self.assertAlmostEqual(bars[0].open, 1.1000, places=6)
        self.assertAlmostEqual(bars[-1].close, 1.1045, places=6)


# ──────────────────────────────────────────────────────────────────────
# Test 2 — CSV fallback when DB file doesn't exist
# ──────────────────────────────────────────────────────────────────────


class TestLoadDataCsvFallbackMissingDb(unittest.TestCase):
    """When the DB file is absent, :func:`load_data` falls back to CSV."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.db_path = self.tmpdir / "no_such_db.duckdb"  # never created
        self.csv_dir = self.tmpdir / "csv"
        self.csv_dir.mkdir()
        _write_csv(
            self.csv_dir / "FALLBACK_M15.csv",
            [
                "2024-02-01 09:30:00,1.1000,1.1050,1.0950,1.1020,100",
                "2024-02-01 09:45:00,1.1020,1.1080,1.1010,1.1060,120",
                "2024-02-01 10:00:00,1.1060,1.1090,1.1050,1.1070,150",
            ],
        )

    def test_load_data_falls_back_to_csv_when_db_missing(self) -> None:
        bars = load_data(
            "FALLBACK",
            "M15",
            db_path=self.db_path,
            csv_dir=self.csv_dir,
        )
        self.assertEqual(len(bars), 3)
        # CsvDataLoader produces tz-aware UTC (parses ET then converts).
        for bar in bars:
            self.assertEqual(bar.time.tzinfo, timezone.utc)
        self.assertAlmostEqual(bars[0].open, 1.1000, places=6)
        self.assertAlmostEqual(bars[-1].close, 1.1070, places=6)

    def test_load_data_logs_which_loader_was_used(self) -> None:
        # Capture log output to verify the loader-name message is emitted.
        with self.assertLogs("backtest.data_loader", level="INFO") as cm:
            load_data(
                "FALLBACK",
                "M15",
                db_path=self.db_path,
                csv_dir=self.csv_dir,
            )
        self.assertTrue(
            any("CsvDataLoader fallback" in msg for msg in cm.output),
            f"expected CsvDataLoader fallback log, got: {cm.output}",
        )

    def test_load_data_returns_empty_when_no_db_and_no_csv(self) -> None:
        with self.assertLogs("backtest.data_loader", level="WARNING") as cm:
            bars = load_data(
                "GHOST",
                "M15",
                db_path=self.db_path,
                csv_dir=self.tmpdir,
            )
        self.assertEqual(bars, [])
        self.assertTrue(
            any("DB miss and no CSV" in msg for msg in cm.output),
            f"expected no-CSV warning, got: {cm.output}",
        )


# ──────────────────────────────────────────────────────────────────────
# Test 3 — CSV fallback when DB exists but has no data for the pair/tf
# ──────────────────────────────────────────────────────────────────────


class TestLoadDataCsvFallbackEmptyQuery(unittest.TestCase):
    """DB is present but the query returns 0 rows → CSV fallback fires."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.db_path = self.tmpdir / "test.duckdb"
        # DB has EURUSD M15 only.
        _populate_temp_db(
            self.db_path,
            [
                (1704067200, "EURUSD", "M15", 1.1, 1.2, 1.0, 1.15, 50, 0.5, True),
            ],
        )
        self.csv_dir = self.tmpdir / "csv"
        self.csv_dir.mkdir()
        _write_csv(
            self.csv_dir / "MISSING_M15.csv",
            [
                "2024-03-01 09:30:00,1.2000,1.2050,1.1950,1.2020,200",
                "2024-03-01 09:45:00,1.2020,1.2080,1.2010,1.2060,220",
            ],
        )

    def test_load_data_falls_back_to_csv_when_db_query_empty(self) -> None:
        # Request a symbol that the DB does not have → DB query returns empty
        # → falls back to CSV.
        bars = load_data(
            "MISSING",
            "M15",
            db_path=self.db_path,
            csv_dir=self.csv_dir,
        )
        self.assertEqual(len(bars), 2)
        self.assertAlmostEqual(bars[0].open, 1.2000, places=6)
        self.assertAlmostEqual(bars[-1].close, 1.2060, places=6)


# ──────────────────────────────────────────────────────────────────────
# Test 4 — load_holdout returns only is_holdout=true rows
# ──────────────────────────────────────────────────────────────────────


class TestLoadHoldout(unittest.TestCase):
    """:func:`load_holdout` filters on ``is_holdout = true``."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.db_path = self.tmpdir / "test.duckdb"
        # Three rows: 2 holdout (2024+), 1 training (early).
        _populate_temp_db(
            self.db_path,
            [
                (1700000000, "XAUUSD", "M15", 1800.0, 1810.0, 1790.0, 1805.0, 10, 0.5, False),  # 2023-11
                (1704067200, "XAUUSD", "M15", 1810.0, 1820.0, 1800.0, 1815.0, 20, 0.5, True),   # 2024-01
                (1704153600, "XAUUSD", "M15", 1820.0, 1830.0, 1810.0, 1825.0, 30, 0.5, True),   # 2024-01
            ],
        )

    def test_load_holdout_returns_only_holdout_true_rows(self) -> None:
        bars = load_holdout("XAUUSD", "M15", db_path=self.db_path)
        self.assertEqual(len(bars), 2)
        # Timestamps must be the two holdout rows.
        ts_values = [int(b.time.timestamp()) for b in bars]
        self.assertEqual(ts_values, [1704067200, 1704153600])
        # Spot-check the OHLC matches the is_holdout=true rows.
        self.assertAlmostEqual(bars[0].open, 1810.0, places=6)
        self.assertAlmostEqual(bars[1].close, 1825.0, places=6)
        # Every returned bar is tz-aware UTC.
        for bar in bars:
            self.assertEqual(bar.time.tzinfo, timezone.utc)

    def test_load_holdout_logs_db_hit_with_holdout_label(self) -> None:
        with self.assertLogs("backtest.data_loader", level="INFO") as cm:
            load_holdout("XAUUSD", "M15", db_path=self.db_path)
        self.assertTrue(
            any("is_holdout=holdout" in msg for msg in cm.output),
            f"expected holdout-tagged log, got: {cm.output}",
        )


# ──────────────────────────────────────────────────────────────────────
# Test 5 — load_training returns only is_holdout=false rows
# ──────────────────────────────────────────────────────────────────────


class TestLoadTraining(unittest.TestCase):
    """:func:`load_training` filters on ``is_holdout = false``."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.db_path = self.tmpdir / "test.duckdb"
        # Three rows: 1 training, 2 holdout.
        _populate_temp_db(
            self.db_path,
            [
                (1700000000, "XAUUSD", "M15", 1800.0, 1810.0, 1790.0, 1805.0, 10, 0.5, False),
                (1704067200, "XAUUSD", "M15", 1810.0, 1820.0, 1800.0, 1815.0, 20, 0.5, True),
                (1704153600, "XAUUSD", "M15", 1820.0, 1830.0, 1810.0, 1825.0, 30, 0.5, True),
            ],
        )

    def test_load_training_returns_only_holdout_false_rows(self) -> None:
        bars = load_training("XAUUSD", "M15", db_path=self.db_path)
        self.assertEqual(len(bars), 1)
        # Single training bar: ts=1700000000, open=1800.0.
        self.assertEqual(int(bars[0].time.timestamp()), 1700000000)
        self.assertAlmostEqual(bars[0].open, 1800.0, places=6)
        self.assertAlmostEqual(bars[0].close, 1805.0, places=6)

    def test_load_training_logs_db_hit_with_training_label(self) -> None:
        with self.assertLogs("backtest.data_loader", level="INFO") as cm:
            load_training("XAUUSD", "M15", db_path=self.db_path)
        self.assertTrue(
            any("is_holdout=training" in msg for msg in cm.output),
            f"expected training-tagged log, got: {cm.output}",
        )


# ──────────────────────────────────────────────────────────────────────
# Bonus — holdout CSV fallback uses the _2026.csv convention
# ──────────────────────────────────────────────────────────────────────


class TestLoadHoldoutCsvFallback(unittest.TestCase):
    """When DB is missing, ``load_holdout`` looks for ``{sym}_{tf}_2026.csv``."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.db_path = self.tmpdir / "no_such_db.duckdb"
        self.csv_dir = self.tmpdir / "csv"
        self.csv_dir.mkdir()
        _write_csv(
            self.csv_dir / "LEGACY_M15_2026.csv",
            [
                "2024-04-01 09:30:00,1.3000,1.3050,1.2950,1.3020,300",
                "2024-04-01 09:45:00,1.3020,1.3080,1.3010,1.3060,320",
            ],
        )

    def test_load_holdout_falls_back_to_underscore_2026_csv(self) -> None:
        bars = load_holdout(
            "LEGACY",
            "M15",
            db_path=self.db_path,
            csv_dir=self.csv_dir,
        )
        self.assertEqual(len(bars), 2)
        self.assertAlmostEqual(bars[0].open, 1.3000, places=6)


# ──────────────────────────────────────────────────────────────────────
# Live-DB integration tests (skipped when the real DB is absent)
# ──────────────────────────────────────────────────────────────────────


@unittest.skipUnless(_db_available(), "data/ayumi_market.duckdb not present")
class TestLiveDbIntegration(unittest.TestCase):
    """Sanity check against the real Phase 8b DuckDB."""

    def test_load_data_live_db_returns_bars(self) -> None:
        bars = load_data("XAUUSD", "H1")
        self.assertGreater(len(bars), 0)

    def test_load_holdout_live_db_returns_only_holdout_rows(self) -> None:
        # Cross-check that every returned bar is also present in the DB and
        # has is_holdout=true. We sample by timestamp to keep the assertion
        # cheap.
        bars = load_holdout("XAUUSD", "H1")
        self.assertGreater(len(bars), 0)
        con = duckdb.connect(str(DB_PATH), read_only=True)
        try:
            for bar in bars[:5]:
                ts = int(bar.time.timestamp())
                row = con.execute(
                    "SELECT is_holdout FROM bars WHERE symbol = ? "
                    "AND timeframe = ? AND timestamp_utc = ?",
                    ["XAUUSD", "H1", ts],
                ).fetchone()
                self.assertIsNotNone(row, f"DB row missing for ts={ts}")
                self.assertTrue(
                    row[0], f"is_holdout must be true for ts={ts}, got {row[0]}"
                )
        finally:
            con.close()


# ──────────────────────────────────────────────────────────────────────
# Defaults — module-level constants
# ──────────────────────────────────────────────────────────────────────


class TestModuleDefaults(unittest.TestCase):
    """Confirm the documented defaults are exposed on the module."""

    def test_default_db_path(self) -> None:
        self.assertEqual(DEFAULT_DB_PATH, Path("data/ayumi_market.duckdb"))

    def test_default_csv_dir(self) -> None:
        self.assertEqual(DEFAULT_CSV_DIR, Path("data/forex/historical"))


if __name__ == "__main__":
    unittest.main()