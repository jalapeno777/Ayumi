"""Tests for live execution wiring (T1) — OpenApiLiveClient changes."""
import sys
import pytest

sys.path.insert(0, "src/forex-bot")


class TestOpenApiLiveClientProperties:
    """Verify is_paper_mode and symbol resolution on OpenApiLiveClient."""

    @pytest.fixture
    def live_client(self):
        """Create a minimal OpenApiLiveClient without connecting."""
        from adapters.ctrader.open_api_live_client import OpenApiLiveClient
        client = OpenApiLiveClient(
            host="demo.ctraderapi.com",
            port=5035,
            client_id="test",
            client_secret="test",
            access_token="test",
            refresh_token="test",
            ctid_account_id=12345,
        )
        return client

    def test_is_paper_mode_returns_false(self, live_client):
        """Critical: must return False so PaperTrader enters live mode."""
        assert live_client.is_paper_mode is False

    def test_is_live_mode_returns_true(self, live_client):
        assert live_client.is_live_mode is True

    def test_set_symbol_map_and_resolve(self, live_client):
        """set_symbol_map + resolve_symbol_id must work together."""
        live_client.set_symbol_map({"EURUSD": 1, "GBPUSD": 2, "XAUUSD": 3})
        assert live_client.resolve_symbol_id("EURUSD") == 1
        assert live_client.resolve_symbol_id("GBPUSD") == 2
        assert live_client.resolve_symbol_id("XAUUSD") == 3

    def test_resolve_symbol_id_raises_on_unknown(self, live_client):
        """Fail-fast: unknown symbol must raise ValueError, not return None."""
        live_client.set_symbol_map({"EURUSD": 1})
        with pytest.raises(ValueError, match="not found in symbol map"):
            live_client.resolve_symbol_id("UNKNOWN_PAIR")

    def test_resolve_symbol_id_raises_when_no_map(self, live_client):
        """No map set at all — must raise ValueError."""
        with pytest.raises(ValueError):
            live_client.resolve_symbol_id("EURUSD")

    def test_symbol_map_overwrite(self, live_client):
        """Setting the map again should replace the old map."""
        live_client.set_symbol_map({"EURUSD": 1})
        live_client.set_symbol_map({"EURUSD": 99, "GBPUSD": 2})
        assert live_client.resolve_symbol_id("EURUSD") == 99
        assert live_client.resolve_symbol_id("GBPUSD") == 2
