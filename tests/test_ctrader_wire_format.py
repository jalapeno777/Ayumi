"""
Wire format contract tests for cTrader MarketDataRequest.

These tests verify the FIX protocol wire format emitted by
LiveMarketDataFeed's subscription message builder. The values
are dictated by the Spotware FIX spec:
- MarketDepth (tag 264) = 0 (full book)
- MDUpdateType (tag 265) = 0 (full refresh)

Regression guard: fe2ee93 silently broke this by setting 1/1,
causing zero ticks for 9 days (Apr 12-21).
"""

from unittest.mock import MagicMock, patch

import pytest
from adapters.ctrader.api_client import SOH
from adapters.ctrader.market_data_feed import LiveMarketDataFeed
from adapters.ctrader.models import cTraderCredentials


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
    feed._client = MagicMock()
    feed._client._send_message.return_value = True
    feed._running = True
    return feed


class TestSubscribeWireFormat:
    """Verify the FIX wire format of MarketDataRequest (35=V) subscribe messages."""

    def test_subscribe_market_depth_is_full_book(self, mock_feed):
        """MarketDepth (tag 264) must be '0' (full book) for cTrader.

        Tag 264=0 requests the full order book depth, which cTrader needs
        to stream bid/ask ticks. Setting 264=1 (top of book) on subscribe
        silently kills tick delivery — the root cause of the 9-day zero-tick
        incident (Apr 12-21, 2026).
        """
        mock_feed.subscribe("EUR/USD")
        assert mock_feed._client._send_message.called
        msg = mock_feed._client._send_message.call_args[0][0]
        wire = msg.to_wire()
        # Tag 264=0 must appear in the wire output
        assert "264=0" in wire, (
            f"MarketDepth tag 264 must be '0' (full book) for subscribe. "
            f"Got wire: {wire!r}"
        )

    def test_subscribe_md_update_type_is_full_refresh(self, mock_feed):
        """MDUpdateType (tag 265) must be '0' (full refresh) for cTrader.

        Tag 265=0 requests full refreshes on every tick update.
        Setting 265=1 (incremental) on subscribe silently kills tick delivery.
        """
        mock_feed.subscribe("EUR/USD")
        assert mock_feed._client._send_message.called
        msg = mock_feed._client._send_message.call_args[0][0]
        wire = msg.to_wire()
        assert "265=0" in wire, (
            f"MDUpdateType tag 265 must be '0' (full refresh) for subscribe. "
            f"Got wire: {wire!r}"
        )

    def test_subscribe_subscription_type_is_snapshot_plus_updates(self, mock_feed):
        """SubscriptionRequestType (tag 263) must be '1' (snapshot + updates)."""
        mock_feed.subscribe("EUR/USD")
        msg = mock_feed._client._send_message.call_args[0][0]
        wire = msg.to_wire()
        assert "263=1" in wire, "SubscriptionRequestType must be 1 (snapshot+updates)"

    def test_subscribe_includes_bid_and_ask_entry_types(self, mock_feed):
        """Must request both MDEntryType 0 (bid) and 1 (ask)."""
        mock_feed.subscribe("EUR/USD")
        msg = mock_feed._client._send_message.call_args[0][0]
        wire = msg.to_wire()
        assert "269=0" in wire, "Must include MDEntryType 0 (bid)"
        assert "269=1" in wire, "Must include MDEntryType 1 (ask)"

    def test_subscribe_returns_true_on_success(self, mock_feed):
        """subscribe() should return True after successful subscription."""
        result = mock_feed.subscribe("EUR/USD")
        assert result is True, "subscribe() must return True on success"

    def test_subscribe_returns_false_on_send_failure(self, quote_credentials):
        """subscribe() should return False when _send_message fails."""
        feed = LiveMarketDataFeed(quote_credentials)
        feed._client = MagicMock()
        feed._client._send_message.return_value = False
        feed._running = True

        result = feed.subscribe("EUR/USD")
        assert result is False
        assert 1 not in feed._subscriptions

    def test_subscribe_body_field_order(self, mock_feed):
        """Verify correct field ordering in body for cTrader compliance."""
        mock_feed.subscribe("EUR/USD")
        msg = mock_feed._client._send_message.call_args[0][0]

        # Check _body_field_list ordering
        body = msg._body_field_list
        tag_order = [tag for tag, _ in body]

        # Expected order: 262, 263, 264, 265, 267, 269, 269, 146, 55
        assert tag_order.index(262) < tag_order.index(263), "MDReqID before SubReqType"
        assert tag_order.index(263) < tag_order.index(264), "SubReqType before MarketDepth"
        assert tag_order.index(264) < tag_order.index(265), "MarketDepth before MDUpdateType"
        assert tag_order.index(265) < tag_order.index(267), "MDUpdateType before NoMDEntryTypes"
        assert tag_order.index(267) < tag_order.index(269), "NoMDEntryTypes before MDEntryType"
        assert tag_order.index(269) < tag_order.index(146), "MDEntryType before NoRelatedSym"


class TestUnsubscribeWireFormat:
    """Verify the FIX wire format of MarketDataRequest (35=V) unsubscribe messages."""

    def test_unsubscribe_market_depth_is_top_of_book(self, mock_feed):
        """Unsubscribe uses MarketDepth=1 (top of book) — this is correct per cTrader spec."""
        mock_feed.subscribe("EUR/USD")  # must subscribe first
        mock_feed._client._send_message.reset_mock()

        mock_feed.unsubscribe("EUR/USD")
        assert mock_feed._client._send_message.called
        msg = mock_feed._client._send_message.call_args[0][0]
        wire = msg.to_wire()
        # Unsubscribe uses 264=1 (top of book) — correct
        assert "264=1" in wire

    def test_unsubscribe_subscription_type_is_disable(self, mock_feed):
        """SubscriptionRequestType=2 disables the subscription."""
        mock_feed.subscribe("EUR/USD")
        mock_feed._client._send_message.reset_mock()

        mock_feed.unsubscribe("EUR/USD")
        msg = mock_feed._client._send_message.call_args[0][0]
        wire = msg.to_wire()
        assert "263=2" in wire, "Unsubscribe must use SubscriptionRequestType=2"


class TestSenderSubID:
    """Verify SenderSubID is set correctly in credentials passed to market data feed."""

    def test_run_live_paper_uses_quote_sender_sub_id(self):
        """run_live_paper._load_credentials() must set sender_sub_id='QUOTE'."""
        import run_live_paper
        creds = run_live_paper._load_credentials()
        assert creds.sender_sub_id == "QUOTE", (
            f"run_live_paper must use sender_sub_id='QUOTE' for market data port. "
            f"Got: {creds.sender_sub_id!r}"
        )

    def test_run_srmr_plus_forward_uses_quote_sender_sub_id(self):
        """run_srmr_plus_forward._load_credentials() must set sender_sub_id='QUOTE'."""
        import run_srmr_plus_forward
        creds = run_srmr_plus_forward._load_credentials()
        assert creds.sender_sub_id == "QUOTE", (
            f"run_srmr_plus_forward must use sender_sub_id='QUOTE' for market data port. "
            f"Got: {creds.sender_sub_id!r}"
        )
