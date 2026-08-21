"""Tests for CTraderHistoricalClient with mocked API responses."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest
from data.ctrader_client import (
    SYMBOL_NAME_MAP,
    TIMEFRAME_MAP,
    CTraderHistoricalClient,
)


@pytest.fixture
def mock_credentials():
    return {
        "client_id": "test_client_id",
        "client_secret": "test_secret",
        "account_id": 12345,
    }


@pytest.fixture
def client(mock_credentials):
    return CTraderHistoricalClient(
        client_id=mock_credentials["client_id"],
        client_secret=mock_credentials["client_secret"],
        access_token="test_access_token",  # noqa: S106
        refresh_token="test_refresh_token",  # noqa: S106
        trader_login=mock_credentials["account_id"],
    )


class TestConstants:
    def test_timeframe_map_has_all_common_timeframes(self):
        for tf in ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN"]:
            assert tf in TIMEFRAME_MAP

    def test_symbol_name_map(self):
        assert SYMBOL_NAME_MAP["EURUSD"] == "EUR/USD"
        assert SYMBOL_NAME_MAP["XAUUSD"] == "XAU/USD"


class TestResolveSymbol:
    def test_resolve_from_cache(self, client):
        client._symbol_cache = {"EUR/USD": (1, 5)}
        assert client._resolve_symbol("EURUSD") == (1, 5)

    def test_resolve_fuzzy_match(self, client):
        client._symbol_cache = {"EUR/USD": (1, 5)}
        assert client._resolve_symbol("EURUSD") == (1, 5)

    def test_resolve_exact_match(self, client):
        client._symbol_cache = {"EUR/USD": (1, 5)}
        assert client._resolve_symbol("EUR/USD") == (1, 5)

    def test_resolve_missing_raises(self, client):
        client._symbol_cache = {"EUR/USD": (1, 5)}
        with pytest.raises(ValueError, match="not found"):
            client._resolve_symbol("ZZZUSD")


class TestGetHistoricalBars:
    def test_unsupported_timeframe_raises(self, client):
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            client.get_historical_bars("EURUSD", "M99", "2026-01-01", "2026-01-02")

    @patch("data.ctrader_client._run_reactor")
    def test_get_historical_bars_returns_dataframe(self, mock_run, client):
        # Mock trendbar data
        mock_bars = [
            {
                "utc_timestamp_ms": 1735689600000,  # 2025-01-01 00:00 UTC
                "open": 1.0345,
                "high": 1.0360,
                "low": 1.0340,
                "close": 1.0355,
                "volume": 100,
            }
        ]
        mock_run.return_value = mock_bars
        client._symbol_cache = {"EUR/USD": (1, 5)}

        df = client.get_historical_bars("EURUSD", "M15", "2025-01-01", "2025-01-02")

        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
        assert len(df) == 1
        assert df.iloc[0]["Open"] == 1.0345

    @patch("data.ctrader_client._run_reactor")
    def test_get_historical_bars_empty(self, mock_run, client):
        mock_run.return_value = []
        client._symbol_cache = {"EUR/USD": (1, 5)}

        df = client.get_historical_bars("EURUSD", "M15", "2025-01-01", "2025-01-02")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]

    @patch("data.ctrader_client._run_reactor")
    def test_date_format_matches_existing(self, mock_run, client):
        """Verify date format matches existing CSV format: YYYY-MM-DD HH:MM"""
        ts = int(datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc).timestamp() * 1000)
        mock_run.return_value = [
            {
                "utc_timestamp_ms": ts,
                "open": 1.05,
                "high": 1.06,
                "low": 1.04,
                "close": 1.055,
                "volume": 50,
            }
        ]
        client._symbol_cache = {"EUR/USD": (1, 5)}

        df = client.get_historical_bars("EURUSD", "H1", "2026-01-01", "2026-02-01")

        assert df.iloc[0]["Date"] == "2026-01-15 14:30"


class TestDownloadAndSave:
    @patch("data.ctrader_client._run_reactor")
    def test_saves_csv(self, mock_run, client, tmp_path):
        ts = int(datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc).timestamp() * 1000)
        mock_run.return_value = [
            {
                "utc_timestamp_ms": ts,
                "open": 1.05,
                "high": 1.06,
                "low": 1.04,
                "close": 1.055,
                "volume": 50,
            }
        ]
        client._symbol_cache = {"EUR/USD": (1, 5)}

        filepath = str(tmp_path / "EURUSD_M15.csv")
        client.download_and_save("EURUSD", "M15", "2026-01-01", "2026-02-01", filepath, append=False)

        saved = pd.read_csv(filepath)
        assert len(saved) == 1
        assert list(saved.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]

    @patch("data.ctrader_client._run_reactor")
    def test_appends_to_existing(self, mock_run, client, tmp_path):
        _ = int(datetime(2025, 12, 31, 23, 45, tzinfo=timezone.utc).timestamp() * 1000)
        ts2 = int(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        mock_run.return_value = [
            {
                "utc_timestamp_ms": ts2,
                "open": 1.05,
                "high": 1.06,
                "low": 1.04,
                "close": 1.055,
                "volume": 50,
            }
        ]
        client._symbol_cache = {"EUR/USD": (1, 5)}

        filepath = str(tmp_path / "EURUSD_M15.csv")

        # Create existing file
        existing = pd.DataFrame(
            {
                "Date": ["2025-12-31 23:45"],
                "Open": [1.04],
                "High": [1.05],
                "Low": [1.03],
                "Close": [1.045],
                "Volume": [30],
            }
        )
        existing.to_csv(filepath, index=False)

        client.download_and_save("EURUSD", "M15", "2026-01-01", "2026-02-01", filepath, append=True)

        saved = pd.read_csv(filepath)
        assert len(saved) == 2
