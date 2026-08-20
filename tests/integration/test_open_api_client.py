"""Tests for CTraderOpenApiClient helpers (period mapping, price conversion, chunking)."""

import pytest  # noqa: I001
from datetime import datetime, timedelta, timezone

from adapters.ctrader.open_api_client import (
    PERIOD_MAP,
    PERIOD_SECONDS,
    calculate_chunks,
)


class TestPeriodMapping:
    def test_all_periods_have_enum(self):
        for p in ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]:
            assert p in PERIOD_MAP, f"{p} missing from PERIOD_MAP"

    def test_all_periods_have_seconds(self):
        for p in ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]:
            assert p in PERIOD_SECONDS, f"{p} missing from PERIOD_SECONDS"

    def test_period_seconds_values(self):
        assert PERIOD_SECONDS["M1"] == 60
        assert PERIOD_SECONDS["H1"] == 3600
        assert PERIOD_SECONDS["D1"] == 86400


class TestPriceConversion:
    """Test the relative price → actual price conversion used in get_trendbars."""

    @staticmethod
    def _convert_bar(low, delta_open, delta_high, delta_close, digits=5):
        """Replicate the conversion logic from CTraderOpenApiClient.get_trendbars."""
        divisor = 100000.0
        return {
            "open": round((low + delta_open) / divisor, digits),
            "high": round((low + delta_high) / divisor, digits),
            "low": round(low / divisor, digits),
            "close": round((low + delta_close) / divisor, digits),
        }

    def test_basic_conversion(self):
        # EUR/USD-like: low=108500, open_delta=50, high_delta=100, close_delta=-20
        prices = self._convert_bar(108500, 50, 100, -20)
        assert prices["low"] == 1.085
        assert prices["open"] == 1.0855
        assert prices["high"] == 1.086
        assert prices["close"] == 1.0848

    def test_jpy_pair(self):
        # USD/JPY-like: low=15400000 (for 154.000), with JPY digits=3
        prices = self._convert_bar(15400000, 3000, 8000, -1000, digits=3)
        assert prices["low"] == 154.0
        assert prices["open"] == 154.03
        assert prices["high"] == 154.08
        assert prices["close"] == 153.99

    def test_zero_deltas(self):
        prices = self._convert_bar(100000, 0, 0, 0)
        assert prices["open"] == prices["high"] == prices["low"] == prices["close"] == 1.0


class TestChunkCalculation:
    def test_single_chunk_for_small_range(self):
        """A range within max bars should be one chunk."""
        now = datetime.now(timezone.utc)
        start_ms = int((now - timedelta(hours=100)).timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)
        chunks = calculate_chunks("H1", start_ms, end_ms)
        # 100 hours = 100 bars, max 5760 → 1 chunk
        assert len(chunks) == 1

    def test_multiple_chunks_for_large_range(self):
        """D1 with a 20-year range should need multiple chunks."""
        now = datetime.now(timezone.utc)
        start_ms = int((now - timedelta(days=365 * 20)).timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)
        chunks = calculate_chunks("D1", start_ms, end_ms)
        # 7300 days / 5760 max = ~2 chunks
        assert len(chunks) >= 2

    def test_chunk_boundaries(self):
        """First chunk should start at start_ms, last should end at end_ms."""
        now = datetime.now(timezone.utc)
        start_ms = int((now - timedelta(days=365)).timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)
        chunks = calculate_chunks("D1", start_ms, end_ms)
        assert chunks[0][0] == start_ms
        assert chunks[-1][1] == end_ms

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            calculate_chunks("INVALID", 0, 1000000)

    def test_m1_needs_many_chunks(self):
        """M1 for 30 days needs many chunks (max 4 days per chunk)."""
        now = datetime.now(timezone.utc)
        start_ms = int((now - timedelta(days=30)).timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)
        chunks = calculate_chunks("M1", start_ms, end_ms)
        # 30 days / 4 days per chunk ≈ 8 chunks
        assert len(chunks) >= 7
