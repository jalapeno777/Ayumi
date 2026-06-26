"""Tests for live execution wiring (T1) — OpenApiSpotFeed properties.

Validates that OpenApiSpotFeed exposes the correct properties for live trading mode.

(BQ-1037: previous version polluted sys.modules with MagicMock at import time,
breaking collection of other test files that needed the real ctrader_open_api
package. Fixed by importing the real module — ctrader_open_api is installed
and the import works fine.)
"""
import os
import pytest
from unittest.mock import MagicMock, patch


class TestOpenApiSpotFeedLiveProperties:
    """Verify is_paper_mode and is_connected on OpenApiSpotFeed."""

    @pytest.fixture
    def feed(self):
        """Create a minimal OpenApiSpotFeed without connecting."""
        from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed
        with patch("adapters.ctrader.connection.ReactorManager"):
            feed = OpenApiSpotFeed(
                ctid_account_id=12345,
                client_id="test",
                client_secret="***",
                access_token="***",
            )
        feed._reactor_manager = MagicMock()
        return feed

    def test_is_paper_mode_returns_false(self, feed):
        """Critical: must return False so PaperTrader enters live mode."""
        assert feed.is_paper_mode is False

    def test_is_connected_reflects_auth_state(self, feed):
        """is_connected mirrors ConnectionStateManager.is_authenticated."""
        from adapters.ctrader.connection_state import ConnectionState
        # DISCONNECTED → not authenticated
        feed._state_mgr._state = ConnectionState.DISCONNECTED
        assert feed.is_connected is False

        # AUTHENTICATED → authenticated
        feed._state_mgr._state = ConnectionState.AUTHENTICATED
        assert feed.is_connected is True

    def test_set_symbol_map_and_resolve(self, feed):
        """Symbol map + resolve_symbol_id must work together."""
        feed._name_to_id["EURUSD"] = 1
        feed._name_to_id["GBPUSD"] = 2
        feed._name_to_id["XAUUSD"] = 3
        assert feed.resolve_symbol_id("EURUSD") == 1
        assert feed.resolve_symbol_id("GBPUSD") == 2
        assert feed.resolve_symbol_id("XAUUSD") == 3

    def test_resolve_symbol_id_raises_on_unknown(self, feed):
        """Fail-fast: unknown symbol must raise ValueError."""
        feed._name_to_id["EURUSD"] = 1
        with pytest.raises(ValueError, match="not found"):
            feed.resolve_symbol_id("UNKNOWN_PAIR")

    def test_resolve_symbol_id_raises_when_no_map(self, feed):
        """No map entries — must raise ValueError."""
        with pytest.raises(ValueError):
            feed.resolve_symbol_id("EURUSD")

    def test_symbol_map_overwrite(self, feed):
        """Setting the map again should replace the old map."""
        feed._name_to_id["EURUSD"] = 1
        feed._name_to_id.clear()
        feed._name_to_id["EURUSD"] = 99
        feed._name_to_id["GBPUSD"] = 2
        assert feed.resolve_symbol_id("EURUSD") == 99
        assert feed.resolve_symbol_id("GBPUSD") == 2
