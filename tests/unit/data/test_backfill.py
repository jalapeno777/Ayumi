"""Tests for HistoricalDataBackfill module."""

import pytest

pytest.skip("adapters.ctrader.symbol_discovery module removed", allow_module_level=True)

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from adapters.ctrader.models import SymbolInfo, cTraderCredentials
from data.backfill import VALID_TIMEFRAMES, HistoricalDataBackfill


def _make_creds():
    return cTraderCredentials(host="localhost", port=1234, use_ssl=False)


def _make_backfill(tmpdir: str) -> HistoricalDataBackfill:
    return HistoricalDataBackfill(_make_creds(), data_dir=tmpdir)


def _make_sample_df(n=10) -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    return pd.DataFrame(
        {
            "timestamp": [now - timedelta(hours=i) for i in range(n)],
            "open": [1.0 + i * 0.001 for i in range(n)],
            "high": [1.001 + i * 0.001 for i in range(n)],
            "low": [0.999 + i * 0.001 for i in range(n)],
            "close": [1.0005 + i * 0.001 for i in range(n)],
            "volume": [100 + i * 10 for i in range(n)],
        }
    )


# --- CSV save format ---


class TestCSVSaveFormat:
    def test_csv_column_names_match_existing_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            df = _make_sample_df()
            path = bf._save_csv(df, "EUR/USD", "H1")

            saved = pd.read_csv(path)
            assert list(saved.columns) == [
                "Date",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
            ]
            assert len(saved) == 10


# --- Missing symbols detection ---


class TestMissingSymbols:
    def test_detects_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            bf._data_dir.mkdir(parents=True, exist_ok=True)
            (bf._data_dir / "EURUSD_H1.csv").write_text("Date,Open,High,Low,Close,Volume\n")

            discovered = {
                1: SymbolInfo(symbol_id=1, name="EUR/USD"),
                2: SymbolInfo(symbol_id=2, name="GBP/USD"),
            }

            missing = bf.get_missing_symbols(discovered, "H1")
            assert missing == ["GBP/USD"]

    def test_all_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            bf._data_dir.mkdir(parents=True, exist_ok=True)
            (bf._data_dir / "EURUSD_H1.csv").write_text("Date,Open,High,Low,Close,Volume\n")

            discovered = {
                1: SymbolInfo(symbol_id=1, name="EUR/USD"),
            }

            missing = bf.get_missing_symbols(discovered, "H1")
            assert missing == []


# --- Multiple symbol backfill with symbol_id dict ---


class TestMultipleBackfill:
    def test_accepts_dict_of_symbol_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            # No API creds set, so it will fall back to CSV
            results = bf.backfill_multiple({"EUR/USD": 1, "GBP/USD": 2}, "H1")
            # Without creds, Open API fails → CSV fallback → empty
            # But the call should not raise
            assert isinstance(results, dict)

    def test_accepts_list_of_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            results = bf.backfill_multiple(["EUR/USD", "GBP/USD"], "H1")
            assert isinstance(results, dict)

    def test_handles_errors_gracefully(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            # Should not raise even with invalid data
            results = bf.backfill_multiple({"BAD/PAIR": 99999}, "H1")
            assert isinstance(results, dict)

    def test_returns_paths_for_existing_csvs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            bf._data_dir.mkdir(parents=True, exist_ok=True)
            for sym in ["EURUSD", "GBPUSD"]:
                path = bf._data_dir / f"{sym}_H1.csv"
                df = _make_sample_df()
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df.to_csv(path, index=False)

            results = bf.backfill_multiple(["EUR/USD", "GBP/USD"], "H1")
            assert len(results) == 2
            for sym, path in results.items():  # noqa: B007
                assert Path(path).exists()


# --- Timeframe validation ---


class TestTimeframeValidation:
    def test_valid_timeframes(self):
        assert "M1" in VALID_TIMEFRAMES
        assert "H1" in VALID_TIMEFRAMES
        assert "D1" in VALID_TIMEFRAMES

    def test_invalid_timeframe_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            with pytest.raises(ValueError, match="Invalid timeframe"):
                bf.backfill_symbol("EUR/USD", "INVALID")


# --- Date range defaults ---


class TestDateRangeDefaults:
    def test_default_end_is_now(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            df = bf.backfill_symbol("EUR/USD", "H1")
            assert "timestamp" in df.columns

    def test_custom_date_range(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            end = datetime.now(timezone.utc).isoformat()
            df = bf.backfill_symbol("EUR/USD", "H1", start_date=start, end_date=end)
            assert "timestamp" in df.columns


# --- Empty result handling ---


class TestEmptyResultHandling:
    def test_empty_dataframe_has_correct_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            df = bf.backfill_symbol("NONEXISTENT/PAIR", "H1")
            assert list(df.columns) == [
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
            assert len(df) == 0

    def test_backfill_multiple_with_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bf = _make_backfill(tmpdir)
            results = bf.backfill_multiple(["FAKE/PAIR"], "H1")
            assert results == {}
