"""Tests for SymbolInfo metadata and XAUUSD pip calculation fix (T4)."""
import sys
import pytest

sys.path.insert(0, "src/forex-bot")

from adapters.ctrader.models import SymbolInfo, SYMBOL_METADATA, get_symbol_info


class TestSymbolInfo:
    """Verify SymbolInfo dataclass and SYMBOL_METADATA entries."""

    def test_eurusd_metadata(self):
        info = get_symbol_info("EURUSD")
        assert info.pip_size == 0.0001
        assert info.pip_value_per_lot == 10.0

    def test_gbpusd_metadata(self):
        info = get_symbol_info("GBPUSD")
        assert info.pip_size == 0.0001
        assert info.pip_value_per_lot == 10.0

    def test_usdjpy_metadata(self):
        info = get_symbol_info("USDJPY")
        assert info.pip_size == 0.01
        assert info.pip_value_per_lot == 6.5

    def test_xauusd_metadata(self):
        """Critical: XAUUSD pip value must be ~$1/lot, NOT $10/lot."""
        info = get_symbol_info("XAUUSD")
        assert info.pip_size == 0.01
        assert info.pip_value_per_lot == 1.0, (
            f"XAUUSD pip_value_per_lot is {info.pip_value_per_lot}, expected 1.0. "
            "Wrong value would cause 10x position sizing error!"
        )
        assert info.lot_size == 100
        assert info.contract_size == 100.0

    def test_unknown_symbol_fallback(self):
        """Unknown symbols should fall back to FX defaults, not crash."""
        info = get_symbol_info("UNKNOWN")
        assert info.pip_size == 0.0001
        assert info.pip_value_per_lot == 10.0

    def test_case_insensitive_lookup(self):
        """Symbol lookup should be case-insensitive."""
        info = get_symbol_info("xauusd")
        assert info.pip_value_per_lot == 1.0

    def test_symbol_metadata_has_all_entries(self):
        """Ensure all required symbols are in the metadata dict."""
        for sym in ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]:
            assert sym in SYMBOL_METADATA, f"{sym} missing from SYMBOL_METADATA"

    def test_xauusd_not_treated_as_jpy_pair(self):
        """XAUUSD price > 50 but should NOT use JPY pip logic."""
        info = get_symbol_info("XAUUSD")
        assert info.pip_size == 0.01  # Same pip size as JPY pairs
        assert info.pip_value_per_lot == 1.0  # But different pip VALUE
