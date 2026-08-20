"""Unit tests for AbstractDataLoader ABC and concrete loader implementations.

Tests cover:
- ABC interface compliance (all abstract methods implemented)
- CsvDataLoader ABC methods (load_bars, get_available_symbols, get_date_range)
- DbDataLoader ABC methods (with DB unavailable → CSV fallback)
- Backward compatibility of existing file-based API
"""

from __future__ import annotations  # noqa: I001

import csv
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backtest.abstract_data_loader import AbstractDataLoader
from backtest.data_loader import CsvDataLoader
from backtest.db_data_loader import DbDataLoader
from backtest.engine import Bar


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_csv_dir():
    """Create a temporary directory with sample CSV files."""
    with tempfile.TemporaryDirectory() as d:
        d_path = Path(d)
        # Standard file
        with open(d_path / "EURUSD_M15.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            w.writerow(["2024-01-01 00:00:00", "1.0800", "1.0810", "1.0790", "1.0805", "1000"])
            w.writerow(["2024-01-01 00:15:00", "1.0805", "1.0820", "1.0800", "1.0815", "1200"])
            w.writerow(["2024-01-01 00:30:00", "1.0815", "1.0825", "1.0810", "1.0820", "800"])
        # XAUUSD file
        with open(d_path / "XAUUSD_H1.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            w.writerow(["2024-01-01 00:00:00", "2050.0", "2055.0", "2048.0", "2052.0", "500"])
            w.writerow(["2024-01-01 01:00:00", "2052.0", "2060.0", "2051.0", "2058.0", "600"])
        # Holdout suffix file
        with open(d_path / "EURUSD_M15_2026.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            w.writerow(["2026-01-01 00:00:00", "1.1000", "1.1010", "1.0990", "1.1005", "900"])
        # Non-matching file (should be ignored by symbol scanner)
        with open(d_path / "readme.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["col1", "col2"])
            w.writerow(["foo", "bar"])
        yield d_path


@pytest.fixture
def csv_loader(sample_csv_dir):
    return CsvDataLoader(csv_dir=sample_csv_dir)


# ──────────────────────────────────────────────────────────────────────
# ABC contract tests
# ──────────────────────────────────────────────────────────────────────


class TestAbstractDataLoaderContract:
    """Verify the ABC enforces implementation of abstract methods."""

    def test_cannot_instantiate_abc_directly(self):
        """AbstractDataLoader cannot be instantiated without implementing abstracts."""
        with pytest.raises(TypeError):
            AbstractDataLoader()

    def test_csv_loader_is_subclass(self, csv_loader):
        assert isinstance(csv_loader, AbstractDataLoader)

    def test_db_loader_is_subclass(self):
        loader = DbDataLoader(db_path="/nonexistent/path.db")
        assert isinstance(loader, AbstractDataLoader)

    def test_partial_implementation_fails(self):
        """A class that doesn't implement all abstracts cannot be instantiated."""

        class BadLoader(AbstractDataLoader):
            def load_bars(self, symbol, timeframe, *, start=None, end=None):
                return []

        with pytest.raises(TypeError):
            BadLoader()


# ──────────────────────────────────────────────────────────────────────
# CsvDataLoader ABC tests
# ──────────────────────────────────────────────────────────────────────


class TestCsvDataLoaderABC:
    """Test CsvDataLoader's implementation of AbstractDataLoader."""

    def test_load_bars_returns_bars(self, csv_loader):
        bars = csv_loader.load_bars("EURUSD", "M15")
        assert len(bars) == 3
        assert all(isinstance(b, Bar) for b in bars)

    def test_load_bars_empty_for_missing_symbol(self, csv_loader):
        bars = csv_loader.load_bars("GBPUSD", "M15")
        assert bars == []

    def test_load_bars_empty_for_missing_timeframe(self, csv_loader):
        bars = csv_loader.load_bars("EURUSD", "H1")
        assert bars == []

    def test_load_bars_with_start_filter(self, csv_loader):
        # CSV naive timestamps are parsed as US/Eastern then converted to UTC.
        # 2024-01-01 00:15:00 EST = 2024-01-01 05:15:00 UTC
        start = datetime(2024, 1, 1, 5, 15, tzinfo=timezone.utc)
        bars = csv_loader.load_bars("EURUSD", "M15", start=start)
        assert len(bars) == 2  # 05:15 and 05:30 UTC
        assert bars[0].time >= start

    def test_load_bars_with_end_filter(self, csv_loader):
        end = datetime(2024, 1, 1, 5, 15, tzinfo=timezone.utc)
        bars = csv_loader.load_bars("EURUSD", "M15", end=end)
        assert len(bars) == 2  # 05:00 and 05:15 UTC
        assert bars[-1].time <= end

    def test_load_bars_with_start_and_end(self, csv_loader):
        start = datetime(2024, 1, 1, 5, 15, tzinfo=timezone.utc)
        end = datetime(2024, 1, 1, 5, 15, tzinfo=timezone.utc)
        bars = csv_loader.load_bars("EURUSD", "M15", start=start, end=end)
        assert len(bars) == 1  # only 05:15 UTC

    def test_get_available_symbols(self, csv_loader):
        symbols = csv_loader.get_available_symbols()
        assert "EURUSD" in symbols
        assert "XAUUSD" in symbols
        # Non-matching file should be excluded
        assert "README" not in symbols
        assert "readme" not in symbols

    def test_get_available_symbols_sorted(self, csv_loader):
        symbols = csv_loader.get_available_symbols()
        assert symbols == sorted(symbols)

    def test_get_date_range(self, csv_loader):
        first, last = csv_loader.get_date_range("EURUSD", "M15")
        assert first is not None
        assert last is not None
        assert first <= last

    def test_get_date_range_missing_data(self, csv_loader):
        first, last = csv_loader.get_date_range("GBPUSD", "M15")
        assert first is None
        assert last is None

    def test_load_ticks_not_implemented(self, csv_loader):
        with pytest.raises(NotImplementedError):
            csv_loader.load_ticks("EURUSD", "M15")


# ──────────────────────────────────────────────────────────────────────
# CsvDataLoader backward compatibility
# ──────────────────────────────────────────────────────────────────────


class TestCsvDataLoaderBackwardCompat:
    """Ensure existing file-based API still works unchanged."""

    def test_load_by_filepath(self, csv_loader, sample_csv_dir):
        filepath = str(sample_csv_dir / "EURUSD_M15.csv")
        bars = csv_loader.load(filepath)
        assert len(bars) == 3

    def test_load_from_string(self, csv_loader):
        csv_content = "timestamp,open,high,low,close,volume\n2024-01-01 00:00:00,1.0800,1.0810,1.0790,1.0805,1000\n"
        bars = csv_loader.load_from_string(csv_content)
        assert len(bars) == 1

    def test_infer_timeframe(self, csv_loader):
        filepath = str(csv_loader.csv_dir / "EURUSD_M15.csv")
        bars = csv_loader.load(filepath)
        tf = csv_loader.infer_timeframe(bars)
        assert tf is not None

    def test_default_csv_dir(self):
        """CsvDataLoader() without args uses DEFAULT_CSV_DIR."""
        loader = CsvDataLoader()
        from backtest.data_loader import DEFAULT_CSV_DIR

        assert loader.csv_dir == DEFAULT_CSV_DIR


# ──────────────────────────────────────────────────────────────────────
# DbDataLoader ABC tests (DB unavailable → fallback)
# ──────────────────────────────────────────────────────────────────────


class TestDbDataLoaderABC:
    """Test DbDataLoader's implementation of AbstractDataLoader."""

    def test_load_bars_db_unavailable_falls_back(self, sample_csv_dir, tmp_path):
        loader = DbDataLoader(
            db_path=tmp_path / "nonexistent.duckdb",
            csv_dir=sample_csv_dir,
        )
        bars = loader.load_bars("EURUSD", "M15")
        assert len(bars) == 3
        assert all(isinstance(b, Bar) for b in bars)

    def test_get_available_symbols_db_unavailable(self, sample_csv_dir, tmp_path):
        loader = DbDataLoader(
            db_path=tmp_path / "nonexistent.duckdb",
            csv_dir=sample_csv_dir,
        )
        symbols = loader.get_available_symbols()
        assert "EURUSD" in symbols
        assert "XAUUSD" in symbols

    def test_get_date_range_db_unavailable(self, sample_csv_dir, tmp_path):
        loader = DbDataLoader(
            db_path=tmp_path / "nonexistent.duckdb",
            csv_dir=sample_csv_dir,
        )
        first, last = loader.get_date_range("EURUSD", "M15")
        assert first is not None
        assert last is not None

    def test_load_bars_with_start_end(self, sample_csv_dir, tmp_path):
        loader = DbDataLoader(
            db_path=tmp_path / "nonexistent.duckdb",
            csv_dir=sample_csv_dir,
        )
        start = datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc)
        end = datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc)
        bars = loader.load_bars("EURUSD", "M15", start=start, end=end)
        # DbDataLoader.load with start_ts/end_ts goes through DB path;
        # when DB unavailable, falls back to CSV (no ts filter in fallback)
        # so we get all bars. Verify we still get Bar objects.
        assert all(isinstance(b, Bar) for b in bars)


# ──────────────────────────────────────────────────────────────────────
# Integration: polymorphic usage
# ──────────────────────────────────────────────────────────────────────


class TestPolymorphicUsage:
    """Verify loaders can be used interchangeably via AbstractDataLoader."""

    def test_csv_loader_via_abc_interface(self, csv_loader):
        """CsvDataLoader can be used through AbstractDataLoader typing."""
        loader: AbstractDataLoader = csv_loader
        bars = loader.load_bars("XAUUSD", "H1")
        assert len(bars) == 2
        symbols = loader.get_available_symbols()
        assert "XAUUSD" in symbols
        first, last = loader.get_date_range("XAUUSD", "H1")
        assert first is not None

    def test_db_loader_via_abc_interface(self, sample_csv_dir, tmp_path):
        """DbDataLoader can be used through AbstractDataLoader typing."""
        loader: AbstractDataLoader = DbDataLoader(
            db_path=tmp_path / "nonexistent.duckdb",
            csv_dir=sample_csv_dir,
        )
        bars = loader.load_bars("XAUUSD", "H1")
        assert len(bars) == 2
