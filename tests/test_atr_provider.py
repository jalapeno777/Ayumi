"""Tests for ATRProvider."""

import json
import os
import tempfile

import pytest

from confidence.providers import ATRProvider


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path


class TestATRProvider:

    def test_loads_existing_cache(self, cache_dir):
        path = cache_dir / "atr.json"
        path.write_text(json.dumps({"EURUSD": 0.0012}))
        provider = ATRProvider(cache_path=str(path))
        assert provider.get_atr("EURUSD") == 0.0012

    def test_missing_symbol_returns_none(self, cache_dir):
        provider = ATRProvider(cache_path=str(cache_dir / "atr.json"))
        assert provider.get_atr("NONEXISTENT") is None

    def test_update_and_persist(self, cache_dir):
        path = cache_dir / "atr.json"
        provider = ATRProvider(cache_path=str(path))
        provider.update_atr("GBPUSD", 0.0015)
        assert provider.get_atr("GBPUSD") == 0.0015
        # Verify persisted
        data = json.loads(path.read_text())
        assert data["GBPUSD"] == 0.0015

    def test_callable_interface(self, cache_dir):
        provider = ATRProvider(cache_path=str(cache_dir / "atr.json"))
        provider.update_atr("XAUUSD", 15.0)
        assert provider("XAUUSD") == 15.0

    def test_handles_corrupt_cache(self, cache_dir):
        path = cache_dir / "atr.json"
        path.write_text("NOT JSON")
        provider = ATRProvider(cache_path=str(path))
        assert provider.get_atr("EURUSD") is None

    def test_missing_file_loads_empty(self, cache_dir):
        provider = ATRProvider(cache_path=str(cache_dir / "nonexistent.json"))
        assert provider._cache == {}

    def test_update_overwrites(self, cache_dir):
        path = cache_dir / "atr.json"
        provider = ATRProvider(cache_path=str(path))
        provider.update_atr("EURUSD", 0.001)
        provider.update_atr("EURUSD", 0.002)
        assert provider.get_atr("EURUSD") == 0.002
