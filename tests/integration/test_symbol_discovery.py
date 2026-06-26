"""Tests for symbol_discovery module."""

import pytest
pytest.skip("adapters.ctrader.symbol_discovery module removed", allow_module_level=True)

import json
import tempfile
from pathlib import Path

import pytest

from adapters.ctrader.symbol_discovery import (
    SymbolInfo,
    SymbolDiscovery,
    classify_symbol,
)


# --- classify_symbol tests ---

class TestClassifySymbol:
    def test_forex_major(self):
        assert classify_symbol("EUR/USD") == "forex_major"
        assert classify_symbol("GBP/USD") == "forex_major"
        assert classify_symbol("USD/JPY") == "forex_major"
        assert classify_symbol("NZD/USD") == "forex_major"

    def test_forex_minor(self):
        assert classify_symbol("EUR/GBP") == "forex_minor"
        assert classify_symbol("GBP/JPY") == "forex_minor"
        assert classify_symbol("AUD/NZD") == "forex_minor"

    def test_forex_exotic(self):
        assert classify_symbol("USD/TRY") == "forex_exotic"
        assert classify_symbol("USD/ZAR") == "forex_exotic"
        assert classify_symbol("EUR/NOK") == "forex_exotic"

    def test_commodity(self):
        assert classify_symbol("XAU/USD") == "commodity"
        assert classify_symbol("XAG/USD") == "commodity"
        assert classify_symbol("UKOIL") == "commodity"

    def test_index(self):
        assert classify_symbol("US30/USD") == "index"
        assert classify_symbol("NAS100/USD") == "index"

    def test_crypto(self):
        assert classify_symbol("BTC/USD") == "crypto"
        assert classify_symbol("ETH/USD") == "crypto"


# --- SymbolInfo tests ---

class TestSymbolInfo:
    def test_data_structure(self):
        info = SymbolInfo(symbol_id=1, name="EUR/USD", pip_size=0.0001, digits=5)
        assert info.symbol_id == 1
        assert info.name == "EUR/USD"
        assert info.pip_size == 0.0001
        assert info.digits == 5
        assert info.category == ""  # not auto-set in constructor

    def test_to_dict_roundtrip(self):
        info = SymbolInfo(symbol_id=1, name="EUR/USD", category="forex_major")
        d = info.to_dict()
        restored = SymbolInfo.from_dict(d)
        assert restored.symbol_id == info.symbol_id
        assert restored.name == info.name
        assert restored.category == "forex_major"

    def test_from_dict_extraneous_keys_ignored(self):
        d = {"symbol_id": 2, "name": "GBP/USD", "bogus_key": "should_be_ignored"}
        info = SymbolInfo.from_dict(d)
        assert info.symbol_id == 2
        assert info.name == "GBP/USD"
        assert not hasattr(info, "bogus_key")


# --- Cache tests ---

class TestCache:
    def test_save_and_load_cycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "symbols.json"
            # Create discovery with dummy credentials
            from adapters.ctrader.models import cTraderCredentials
            creds = cTraderCredentials(host="localhost", port=1234, use_ssl=False)
            disc = SymbolDiscovery(creds, cache_path=str(cache_path))

            # Manually populate
            disc._symbols = {
                1: SymbolInfo(symbol_id=1, name="EUR/USD", category="forex_major"),
                2: SymbolInfo(symbol_id=2, name="XAU/USD", category="commodity"),
            }
            disc.save_cache()

            # Load fresh
            disc2 = SymbolDiscovery(creds, cache_path=str(cache_path))
            loaded = disc2.get_all()
            assert len(loaded) == 2
            assert loaded[1].name == "EUR/USD"
            assert loaded[2].name == "XAU/USD"
            assert loaded[1].category == "forex_major"

    def test_load_from_empty_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "nonexistent.json"
            from adapters.ctrader.models import cTraderCredentials
            creds = cTraderCredentials(host="localhost", port=1234, use_ssl=False)
            disc = SymbolDiscovery(creds, cache_path=str(cache_path))
            assert disc.get_all() == {}


# --- get_by_category ---

class TestGetByCategory:
    def test_category_filtering(self):
        from adapters.ctrader.models import cTraderCredentials
        creds = cTraderCredentials(host="localhost", port=1234, use_ssl=False)
        disc = SymbolDiscovery(creds, cache_path="/tmp/nonexistent_test.json")

        disc._symbols = {
            1: SymbolInfo(symbol_id=1, name="EUR/USD", category="forex_major"),
            2: SymbolInfo(symbol_id=2, name="GBP/USD", category="forex_major"),
            3: SymbolInfo(symbol_id=3, name="XAU/USD", category="commodity"),
            4: SymbolInfo(symbol_id=4, name="EUR/GBP", category="forex_minor"),
        }

        majors = disc.get_by_category("forex_major")
        assert len(majors) == 2
        assert all(s.category == "forex_major" for s in majors)

        commodities = disc.get_by_category("commodity")
        assert len(commodities) == 1
        assert commodities[0].name == "XAU/USD"

        empty = disc.get_by_category("crypto")
        assert empty == []
