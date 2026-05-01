"""Tests for the cTrader FIX Market Data Feed."""

from unittest.mock import MagicMock

import pytest
from adapters.ctrader.api_client import SOH, FIXMessage
from adapters.ctrader.market_data_feed import (
    DEFAULT_SYMBOLS,
    FOREX_PAIRS,
    LiveMarketDataFeed,
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
            (55, "1"),
            (268, "2"),
            (269, "0"),
            (270, "1.0"),
            (269, "1"),
            (270, "1.1"),
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
            (55, "1"),
            (268, "2"),
            (269, "0"),
            (270, "1.0"),
            (269, "1"),
            (270, "1.1"),
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


# ---------------------------------------------------------------------------
# MarketDataRequest wire format tests (AYUAA-776)
# ---------------------------------------------------------------------------


class TestMarketDataRequestWireFormat:
    def test_market_depth_is_zero(self, mock_feed):
        mock_feed.subscribe("EUR/USD")
        msg = mock_feed._client._send_message.call_args[0][0]
        assert msg.get_field(264) == "0"

    def test_md_update_type_is_zero(self, mock_feed):
        mock_feed.subscribe("EUR/USD")
        msg = mock_feed._client._send_message.call_args[0][0]
        assert msg.get_field(265) == "0"

    def test_subscription_type_is_snapshot_plus_updates(self, mock_feed):
        mock_feed.subscribe("EUR/USD")
        msg = mock_feed._client._send_message.call_args[0][0]
        assert msg.get_field(263) == "1"

    def test_no_md_entry_types_is_two(self, mock_feed):
        mock_feed.subscribe("EUR/USD")
        msg = mock_feed._client._send_message.call_args[0][0]
        assert msg.get_field(267) == "2"

    def test_bid_and_ask_entry_types_in_wire(self, mock_feed):
        mock_feed.subscribe("EUR/USD")
        msg = mock_feed._client._send_message.call_args[0][0]
        wire = msg.to_wire()
        assert "269=0" in wire
        assert "269=1" in wire

    def test_symbol_id_in_related_sym_group(self, mock_feed):
        mock_feed.subscribe("GBP/USD")
        msg = mock_feed._client._send_message.call_args[0][0]
        assert msg.get_field(146) == "1"
        wire = msg.to_wire()
        assert "55=2" in wire


# ---------------------------------------------------------------------------
# MarketDataIncrementalRefresh (35=X) tests
# ---------------------------------------------------------------------------


class TestMarketDataIncrementalRefresh:
    def _make_incremental_msg(
        self, entries: list[dict], symbol_id: int = 2, md_req_id: str = "SUB_0001"
    ) -> FIXMessage:
        """Build a FIXMessage mimicking a 35=X incremental refresh."""
        raw_fields: list[tuple[int, str]] = [
            (262, md_req_id),
            (268, str(len(entries))),
        ]
        for entry in entries:
            raw_fields.append((279, entry["action"]))
            if "entry_type" in entry:
                raw_fields.append((269, entry["entry_type"]))
            if "order_id" in entry:
                raw_fields.append((278, entry["order_id"]))
            if "symbol_id" in entry:
                raw_fields.append((55, str(entry["symbol_id"])))
            if "price" in entry:
                raw_fields.append((270, str(entry["price"])))

        msg = FIXMessage()
        msg.fields = {35: "X", 55: str(symbol_id), 52: "20260415-03:30:00.000"}
        msg._raw_fields = raw_fields
        return msg

    def test_new_bid_updates_tick(self, mock_feed):
        mock_feed._order_book[2] = {"bids": {}, "asks": {}}
        mock_feed._order_book[2]["asks"]["ord_ask_1"] = 1.35650

        msg = self._make_incremental_msg(
            [
                {
                    "action": "0",
                    "entry_type": "0",
                    "order_id": "ord_bid_1",
                    "price": 1.35643,
                },
            ]
        )
        mock_feed._on_incremental(msg)

        tick = mock_feed.get_tick("GBP/USD")
        assert tick is not None
        assert tick.bid == pytest.approx(1.35643, abs=1e-8)
        assert tick.ask == pytest.approx(1.35650, abs=1e-8)

    def test_new_ask_updates_tick(self, mock_feed):
        mock_feed._order_book[2] = {"bids": {}, "asks": {}}
        mock_feed._order_book[2]["bids"]["ord_bid_1"] = 1.35643

        msg = self._make_incremental_msg(
            [
                {
                    "action": "0",
                    "entry_type": "1",
                    "order_id": "ord_ask_1",
                    "price": 1.35650,
                },
            ]
        )
        mock_feed._on_incremental(msg)

        tick = mock_feed.get_tick("GBP/USD")
        assert tick is not None
        assert tick.bid == pytest.approx(1.35643, abs=1e-8)
        assert tick.ask == pytest.approx(1.35650, abs=1e-8)

    def test_change_updates_price(self, mock_feed):
        mock_feed._order_book[2] = {
            "bids": {"ord_bid_1": 1.35640, "ord_bid_2": 1.35638},
            "asks": {"ord_ask_1": 1.35650},
        }

        msg = self._make_incremental_msg(
            [
                {
                    "action": "1",
                    "entry_type": "0",
                    "order_id": "ord_bid_1",
                    "price": 1.35643,
                },
            ]
        )
        mock_feed._on_incremental(msg)

        tick = mock_feed.get_tick("GBP/USD")
        assert tick is not None
        assert tick.bid == pytest.approx(1.35643, abs=1e-8)

    def test_delete_removes_order(self, mock_feed):
        mock_feed._order_book[2] = {
            "bids": {"ord_bid_1": 1.35655, "ord_bid_2": 1.35643},
            "asks": {"ord_ask_1": 1.35650},
        }

        msg = self._make_incremental_msg(
            [
                {"action": "2", "entry_type": "0", "order_id": "ord_bid_1"},
            ]
        )
        mock_feed._on_incremental(msg)

        tick = mock_feed.get_tick("GBP/USD")
        assert tick is not None
        assert tick.bid == pytest.approx(1.35643, abs=1e-8)

    def test_multiple_entries_in_one_message(self, mock_feed):
        mock_feed._order_book[2] = {"bids": {}, "asks": {}}

        msg = self._make_incremental_msg(
            [
                {"action": "0", "entry_type": "0", "order_id": "b1", "price": 1.35640},
                {"action": "0", "entry_type": "0", "order_id": "b2", "price": 1.35643},
                {"action": "0", "entry_type": "1", "order_id": "a1", "price": 1.35650},
                {"action": "0", "entry_type": "1", "order_id": "a2", "price": 1.35648},
            ]
        )
        mock_feed._on_incremental(msg)

        tick = mock_feed.get_tick("GBP/USD")
        assert tick is not None
        assert tick.bid == pytest.approx(1.35643, abs=1e-8)
        assert tick.ask == pytest.approx(1.35648, abs=1e-8)

    def test_incremental_tick_callback_fired(self, mock_feed):
        received = []
        mock_feed.on_tick(lambda t: received.append(t))
        mock_feed._order_book[2] = {
            "bids": {"b1": 1.35640},
            "asks": {"a1": 1.35650},
        }

        msg = self._make_incremental_msg(
            [
                {"action": "1", "entry_type": "0", "order_id": "b1", "price": 1.35643},
            ]
        )
        mock_feed._on_incremental(msg)

        assert len(received) == 1
        assert received[0].symbol_id == 2
        assert received[0].bid == pytest.approx(1.35643, abs=1e-8)

    def test_incremental_ignored_for_non_x_messages(self, mock_feed):
        msg = FIXMessage()
        msg.fields = {35: "W", 55: "1", 52: "20260415-03:30:00.000"}
        msg._raw_fields = [
            (55, "1"),
            (268, "2"),
            (269, "0"),
            (270, "1.0"),
            (269, "1"),
            (270, "1.1"),
        ]
        mock_feed._on_incremental(msg)
        assert mock_feed.get_tick("EUR/USD") is None

    def test_incremental_no_raw_fields_ignored(self, mock_feed):
        msg = FIXMessage()
        msg.fields = {35: "X", 55: "2", 52: "20260415-03:30:00.000"}
        mock_feed._on_incremental(msg)
        assert mock_feed.get_tick("GBP/USD") is None

    def test_incremental_incomplete_book_no_update(self, mock_feed):
        mock_feed._order_book[2] = {"bids": {}, "asks": {}}
        msg = self._make_incremental_msg(
            [
                {"action": "0", "entry_type": "0", "order_id": "b1", "price": 1.35643},
            ]
        )
        mock_feed._on_incremental(msg)
        assert mock_feed.get_tick("GBP/USD") is None

    def test_snapshot_clears_order_book(self, mock_feed):
        mock_feed._order_book[2] = {"bids": {"b1": 1.35643}, "asks": {"a1": 1.35650}}
        msg = FIXMessage()
        msg.fields = {35: "W", 55: "2", 52: "20260415-03:30:00.000"}
        msg._raw_fields = [
            (55, "2"),
            (268, "2"),
            (269, "0"),
            (270, "1.35643"),
            (269, "1"),
            (270, "1.35650"),
        ]
        mock_feed._on_snapshot(msg)
        assert 2 not in mock_feed._order_book

    def test_stop_clears_order_book(self, mock_feed):
        mock_feed._order_book[2] = {"bids": {"b1": 1.0}, "asks": {"a1": 1.1}}
        mock_feed.stop()
        assert mock_feed._order_book == {}

    def test_unknown_entry_type_skipped(self, mock_feed):
        mock_feed._order_book[2] = {
            "bids": {"b1": 1.35643},
            "asks": {"a1": 1.35650},
        }
        msg = self._make_incremental_msg(
            [
                {
                    "action": "0",
                    "entry_type": "2",
                    "order_id": "trade_1",
                    "price": 1.35645,
                },
            ]
        )
        mock_feed._on_incremental(msg)
        assert mock_feed._order_book[2]["bids"] == {"b1": 1.35643}
        assert mock_feed._order_book[2]["asks"] == {"a1": 1.35650}

    def test_delete_nonexistent_order_no_error(self, mock_feed):
        mock_feed._order_book[2] = {
            "bids": {"b1": 1.35643},
            "asks": {"a1": 1.35650},
        }
        msg = self._make_incremental_msg(
            [
                {"action": "2", "entry_type": "0", "order_id": "nonexistent"},
            ]
        )
        mock_feed._on_incremental(msg)
        tick = mock_feed.get_tick("GBP/USD")
        assert tick is not None
        assert tick.bid == pytest.approx(1.35643, abs=1e-8)

    def test_cross_symbol_entries_isolated(self, mock_feed):
        """Entries with per-entry symbol_id go to their own order book."""
        mock_feed._order_book[1] = {"bids": {}, "asks": {"a_eur": 1.15255}}
        mock_feed._order_book[2] = {"bids": {}, "asks": {"a_gbp": 1.35650}}

        msg = self._make_incremental_msg(
            [
                {
                    "action": "0",
                    "entry_type": "0",
                    "order_id": "b_eur",
                    "symbol_id": 1,
                    "price": 1.15250,
                },
                {
                    "action": "0",
                    "entry_type": "0",
                    "order_id": "b_gbp",
                    "symbol_id": 2,
                    "price": 1.35643,
                },
            ],
            symbol_id=2,
        )
        mock_feed._on_incremental(msg)

        tick_eur = mock_feed.get_tick("EUR/USD")
        tick_gbp = mock_feed.get_tick("GBP/USD")
        assert tick_eur is not None
        assert tick_eur.bid == pytest.approx(1.15250, abs=1e-8)
        assert tick_eur.ask == pytest.approx(1.15255, abs=1e-8)
        assert tick_gbp is not None
        assert tick_gbp.bid == pytest.approx(1.35643, abs=1e-8)
        assert tick_gbp.ask == pytest.approx(1.35650, abs=1e-8)

    def test_cross_symbol_no_contamination(self, mock_feed):
        """Multi-symbol X message must not mix bids/asks across symbols."""
        mock_feed._order_book[1] = {"bids": {}, "asks": {}}
        mock_feed._order_book[2] = {"bids": {}, "asks": {}}

        msg = self._make_incremental_msg(
            [
                {
                    "action": "0",
                    "entry_type": "0",
                    "order_id": "b_eur",
                    "symbol_id": 1,
                    "price": 1.15250,
                },
                {
                    "action": "0",
                    "entry_type": "1",
                    "order_id": "a_eur",
                    "symbol_id": 1,
                    "price": 1.15255,
                },
                {
                    "action": "0",
                    "entry_type": "0",
                    "order_id": "b_gbp",
                    "symbol_id": 2,
                    "price": 1.35643,
                },
                {
                    "action": "0",
                    "entry_type": "1",
                    "order_id": "a_gbp",
                    "symbol_id": 2,
                    "price": 1.35650,
                },
            ],
            symbol_id=0,
        )
        mock_feed._on_incremental(msg)

        tick_eur = mock_feed.get_tick("EUR/USD")
        tick_gbp = mock_feed.get_tick("GBP/USD")
        assert tick_eur is not None
        assert tick_eur.spread == pytest.approx(0.00005, abs=1e-8)
        assert tick_gbp is not None
        assert tick_gbp.spread == pytest.approx(0.00007, abs=1e-8)
        assert tick_eur.spread > 0
        assert tick_gbp.spread > 0

    def test_inverted_spread_skipped(self, mock_feed):
        """Spread guard prevents emitting a tick when bid >= ask."""
        mock_feed._order_book[2] = {
            "bids": {},
            "asks": {},
        }

        msg = self._make_incremental_msg(
            [
                {
                    "action": "0",
                    "entry_type": "0",
                    "order_id": "b1",
                    "price": 1.36000,
                },
                {
                    "action": "0",
                    "entry_type": "1",
                    "order_id": "a1",
                    "price": 1.35000,
                },
            ],
            symbol_id=2,
        )
        mock_feed._on_incremental(msg)

        tick = mock_feed.get_tick("GBP/USD")
        assert tick is None

    def test_inverted_spread_does_not_corrupt_other_symbols(self, mock_feed):
        """Inverted spread on one symbol must not block a valid spread on another."""
        mock_feed._order_book[1] = {"bids": {}, "asks": {}}
        mock_feed._order_book[2] = {"bids": {}, "asks": {}}

        msg = self._make_incremental_msg(
            [
                {
                    "action": "0",
                    "entry_type": "0",
                    "order_id": "b_bad",
                    "symbol_id": 2,
                    "price": 1.36000,
                },
                {
                    "action": "0",
                    "entry_type": "1",
                    "order_id": "a_bad",
                    "symbol_id": 2,
                    "price": 1.35000,
                },
                {
                    "action": "0",
                    "entry_type": "0",
                    "order_id": "b_good",
                    "symbol_id": 1,
                    "price": 1.15250,
                },
                {
                    "action": "0",
                    "entry_type": "1",
                    "order_id": "a_good",
                    "symbol_id": 1,
                    "price": 1.15255,
                },
            ],
            symbol_id=0,
        )
        mock_feed._on_incremental(msg)

        tick_gbp = mock_feed.get_tick("GBP/USD")
        tick_eur = mock_feed.get_tick("EUR/USD")
        assert tick_gbp is None
        assert tick_eur is not None
        assert tick_eur.spread > 0

    def test_entry_without_symbol_id_falls_back_to_msg_level(self, mock_feed):
        msg = self._make_incremental_msg(
            [
                {
                    "action": "0",
                    "entry_type": "0",
                    "order_id": "b1",
                    "price": 1.35643,
                },
                {
                    "action": "0",
                    "entry_type": "1",
                    "order_id": "a1",
                    "price": 1.35650,
                },
            ],
            symbol_id=2,
        )
        mock_feed._order_book[2] = {"bids": {}, "asks": {}}
        mock_feed._on_incremental(msg)

        tick = mock_feed.get_tick("GBP/USD")
        assert tick is not None
        assert tick.bid == pytest.approx(1.35643, abs=1e-8)
        assert tick.ask == pytest.approx(1.35650, abs=1e-8)
