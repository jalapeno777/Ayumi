"""Tests for the cTrader FIX Market Data Feed."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from adapters.ctrader.api_client import FIXMessage, SOH
from adapters.ctrader.market_data_feed import (
    DEFAULT_SYMBOLS,
    FOREX_PAIRS,
    LiveMarketDataFeed,
    MarketDataClient,
    SymbolInfo,
    Tick,
)
from adapters.ctrader.models import cTraderCredentials


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def quote_credentials():
    return cTraderCredentials(
        host="live-uk-eqx-01.p.c-trader.com",
        port=5211,
        use_ssl=True,
        sender_comp_id="live.ftmo.17087404",
        target_comp_id="cServer",
        sender_sub_id="QUOTE",
        username="17087404",
        password="test_password",
    )


@pytest.fixture
def mock_feed(quote_credentials):
    """Feed with mocked client (no real connection)."""
    feed = LiveMarketDataFeed(quote_credentials)
    # Mock the client so we don't need a real connection
    feed._client = MagicMock()
    feed._client._send_message.return_value = True
    feed._running = True
    return feed


# ---------------------------------------------------------------------------
# Tick tests
# ---------------------------------------------------------------------------

class TestTick:
    def test_tick_properties(self):
        tick = Tick(symbol_id=1, bid=1.15250, ask=1.15252)
        assert tick.spread == pytest.approx(0.00002, abs=1e-8)
        assert tick.mid == pytest.approx(1.15251, abs=1e-8)

    def test_tick_default_timestamp(self):
        tick = Tick(symbol_id=1, bid=1.0, ask=1.0)
        assert tick.timestamp is not None

    def test_tick_zero_spread(self):
        tick = Tick(symbol_id=1, bid=1.0, ask=1.0)
        assert tick.spread == 0.0


# ---------------------------------------------------------------------------
# SymbolInfo tests
# ---------------------------------------------------------------------------

class TestSymbolInfo:
    def test_default_symbols_populated(self):
        assert len(DEFAULT_SYMBOLS) >= 6
        assert DEFAULT_SYMBOLS[1] == "EUR/USD"
        assert DEFAULT_SYMBOLS[2] == "GBP/USD"

    def test_symbol_info_creation(self):
        info = SymbolInfo(symbol_id=1, name="EUR/USD")
        assert info.symbol_id == 1
        assert info.name == "EUR/USD"
        assert info.pip_size == 0.0001
        assert info.digits == 5


# ---------------------------------------------------------------------------
# LiveMarketDataFeed tests
# ---------------------------------------------------------------------------

class TestLiveMarketDataFeed:
    def test_init_resolves_symbols(self, quote_credentials):
        feed = LiveMarketDataFeed(quote_credentials)
        assert feed.name_to_id["EUR/USD"] == 1
        assert feed.name_to_id["GBP/USD"] == 2
        assert feed._resolve_id("EUR/USD") == 1
        assert feed._resolve_id("UNKNOWN") is None

    def test_subscribe_sends_correct_message(self, mock_feed):
        mock_feed.subscribe("EUR/USD")
        assert mock_feed._client._send_message.called
        msg = mock_feed._client._send_message.call_args[0][0]
        assert msg.msg_type == "V"
        assert 1 in mock_feed._subscriptions

    def test_subscribe_unknown_symbol(self, mock_feed):
        result = mock_feed.subscribe("UNKNOWN/PAIR")
        assert result is False
        assert not mock_feed._client._send_message.called

    def test_subscribe_idempotent(self, mock_feed):
        mock_feed.subscribe("EUR/USD")
        mock_feed.subscribe("EUR/USD")
        # Should only send once
        assert mock_feed._client._send_message.call_count == 1

    def test_unsubscribe(self, mock_feed):
        mock_feed.subscribe("EUR/USD")
        mock_feed._client._send_message.reset_mock()
        mock_feed.unsubscribe("EUR/USD")
        assert 1 not in mock_feed._subscriptions

    def test_get_tick_empty(self, mock_feed):
        assert mock_feed.get_tick("EUR/USD") is None

    def test_on_snapshot_updates_tick(self, mock_feed):
        # Simulate a MarketDataSnapshot
        msg = FIXMessage()
        msg.fields = {
            35: "W",
            55: "1",
            52: "20260406-02:30:00.000",
        }
        msg._raw_fields = [
            (55, "1"),
            (268, "2"),
            (269, "0"),
            (270, "1.15250"),
            (269, "1"),
            (270, "1.15252"),
        ]

        mock_feed._on_snapshot(msg)

        tick = mock_feed.get_tick("EUR/USD")
        assert tick is not None
        assert tick.bid == pytest.approx(1.15250, abs=1e-8)
        assert tick.ask == pytest.approx(1.15252, abs=1e-8)

    def test_on_snapshot_incomplete_ignored(self, mock_feed):
        msg = FIXMessage()
        msg.fields = {35: "W", 55: "1"}
        msg._raw_fields = [(55, "1"), (269, "0"), (270, "1.15250")]

        mock_feed._on_snapshot(msg)
        assert mock_feed.get_tick("EUR/USD") is None

    def test_get_all_ticks(self, mock_feed):
        msg = FIXMessage()
        msg.fields = {35: "W", 55: "1", 52: "20260406-02:30:00.000"}
        msg._raw_fields = [
            (55, "1"), (268, "2"), (269, "0"), (270, "1.0"), (269, "1"), (270, "1.1")
        ]
        mock_feed._on_snapshot(msg)

        all_ticks = mock_feed.get_all_ticks()
        assert "EUR/USD" in all_ticks

    def test_tick_callback(self, mock_feed):
        received = []
        mock_feed.on_tick(lambda t: received.append(t))

        msg = FIXMessage()
        msg.fields = {35: "W", 55: "1", 52: "20260406-02:30:00.000"}
        msg._raw_fields = [
            (55, "1"), (268, "2"), (269, "0"), (270, "1.0"), (269, "1"), (270, "1.1")
        ]
        mock_feed._on_snapshot(msg)

        assert len(received) == 1
        assert received[0].symbol_id == 1

    def test_forex_pairs_constant(self):
        assert "EUR/USD" in FOREX_PAIRS
        assert "GBP/USD" in FOREX_PAIRS
        assert len(FOREX_PAIRS) == 6


# ---------------------------------------------------------------------------
# FIXMessage repeating group tests
# ---------------------------------------------------------------------------

class TestFIXMessageRepeatingGroups:
    def test_body_field_list_preserves_order(self):
        msg = FIXMessage(msg_type="V")
        msg.set_body_field(267, "2")
        msg.set_body_field(269, "0")
        msg.set_body_field(269, "1")
        assert len(msg._body_field_list) == 3
        assert msg._body_field_list[0] == (267, "2")
        assert msg._body_field_list[1] == (269, "0")
        assert msg._body_field_list[2] == (269, "1")

    def test_to_wire_includes_repeated_fields(self):
        msg = FIXMessage(msg_type="V")
        msg.set_body_field(269, "0")
        msg.set_body_field(269, "1")
        wire = msg.to_wire()
        # Both 269 values should appear in wire format
        assert wire.count("269=0") == 1
        assert wire.count("269=1") == 1

    def test_from_wire_preserves_raw_fields(self):
        wire = f"35=W{SOH}55=1{SOH}268=2{SOH}269=0{SOH}270=1.15250{SOH}269=1{SOH}270=1.15252{SOH}"
        msg = FIXMessage.from_wire(wire)
        assert hasattr(msg, "_raw_fields")
        assert len(msg._raw_fields) >= 6
        # Flat dict should have last value for repeated tags
        assert msg.get_field(269) == "1"
        assert msg.get_field(270) == "1.15252"
