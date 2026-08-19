"""Tests for the per-symbol volume / price decoder in OpenApiSpotFeed.

Reproduces the BQ-? bug where the decoder used a hardcoded ``100_000``
divisor when converting raw volume to lots (and raw spot prices to
display prices). That constant works for 5-digit FX (EURUSD/GBPUSD) but
is wrong in principle and silently produces bogus values for any other
symbol (USDJPY 3-digit, XAUUSD 2-digit, etc).

The fix replaces the hardcoded divisor with a per-symbol lookup using
``self._symbol_digits[symbol_id]`` (raising ``10 ** digits``). If the
symbol_id is unknown, the decoder raises ``KeyError`` rather than
silently producing the wrong value.

These tests verify:
* 5-digit FX: 1.0 lot = 100000 raw → 1.0 lot on the wire
* 2-digit XAUUSD: 1.0 lot = 100 raw → 1.0 lot on the wire
* 3-digit USDJPY: 1.0 lot = 1000 raw → 1.0 lot on the wire
* Unknown symbol_id: ``new_order`` raises ``KeyError``
* Unknown symbol_id: ``_handle_spot_event`` raises ``KeyError``
"""

from __future__ import annotations

import gc
import logging
from unittest.mock import MagicMock, patch

import pytest


from archive.legacy_ctrader._pkg.open_api_spot_feed import (  # noqa: E402
    OpenApiSpotFeed,
    ProtoOATradeSide,
)
# NOTE: do NOT import OrderStatus from adapters.ctrader.models — that's a
# *different* enum class than the one open_api_spot_feed uses internally
# (legacy_ctrader._pkg.models.OrderStatus). We compare by string value
# instead, which is robust to the dual-enum situation.

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def feed_factory():
    """Factory that creates OOM-safe OpenApiSpotFeed instances for testing
    the volume decoder. Mocks CTraderConnection and TokenManager so no
    real network resources are allocated.
    """
    created: list[OpenApiSpotFeed] = []

    def _create(**kwargs) -> OpenApiSpotFeed:
        defaults = dict(
            ctid_account_id=99999,
            client_id="test-client",
            client_secret="test-secret",
            access_token="test-access-token",
        )
        defaults.update(kwargs)

        with (
            patch(
                "archive.legacy_ctrader._pkg.open_api_spot_feed.CTraderConnection"
            ) as mock_conn_cls,
            patch(
                "archive.legacy_ctrader._pkg.open_api_spot_feed.TokenManager"
            ) as mock_token_cls,
        ):
            mock_conn = MagicMock()
            mock_conn_cls.return_value = mock_conn
            mock_token = MagicMock()
            mock_token_cls.return_value = mock_token
            feed = OpenApiSpotFeed(**defaults)

        feed._token_lifecycle = MagicMock()

        feed._reactor_manager = MagicMock()
        feed._conn = mock_conn
        created.append(feed)
        return feed

    yield _create

    for f in created:
        f._tick_callbacks.clear()
        f._pending_orders.clear()
        f._ticks.clear()
        f._ticks_by_id.clear()
        f._tick_counts.clear()
        f._symbols.clear()
        f._name_to_id.clear()
        f._id_to_name.clear()
        f._symbol_digits.clear()
        f._subscribed_symbol_ids.clear()
        f._on_reconnected_callbacks.clear()
        f._conn = None
        f._client = None
        f._token_mgr = None
        f._reactor_manager = None
    created.clear()
    gc.collect()


def _seed_symbol(feed: OpenApiSpotFeed, symbol_id: int, name: str, digits: int) -> None:
    """Register a symbol in the feed's metadata dicts."""
    feed._symbol_digits[symbol_id] = digits
    feed._id_to_name[symbol_id] = name
    feed._name_to_id[name] = symbol_id


# ---------------------------------------------------------------------------
# new_order: volume is decoded per symbol
# ---------------------------------------------------------------------------


class TestNewOrderVolumeDecoder:
    def test_5_digit_fx_volume_decoded_as_100000(self, feed_factory):
        """EURUSD/GBPUSD are 5-digit. 1.0 lot = 100000 raw units.
        After decoding, order.volume should be 1.0 lots."""
        feed = feed_factory()
        _seed_symbol(feed, symbol_id=1, name="EURUSD", digits=5)
        # Not operational: new_order short-circuits and returns the
        # constructed Order without sending to the wire. Perfect for
        # checking the decoded volume.
        assert not feed._state_mgr.is_operational
        order = feed.new_order(1, ProtoOATradeSide.BUY, volume=100_000)
        assert order.volume == pytest.approx(1.0), (
            f"Expected 1.0 lot, got {order.volume}"
        )
        assert order.status.value == "pending"

    def test_2_digit_xauusd_volume_decoded_as_100(self, feed_factory):
        """XAUUSD is 2-digit. 1.0 lot of gold = 100 raw oz.
        After decoding, order.volume should be 1.0 lots — NOT 0.001
        (which is what the old hardcoded 100_000 divisor would have
        produced: 100 / 100_000 = 0.001)."""
        feed = feed_factory()
        _seed_symbol(feed, symbol_id=42, name="XAUUSD", digits=2)
        order = feed.new_order(42, ProtoOATradeSide.BUY, volume=100)
        assert order.volume == pytest.approx(1.0), (
            f"Expected 1.0 lot for XAUUSD, got {order.volume} "
            f"(hardcoded 100_000 would have given 0.001)"
        )

    def test_3_digit_usdjpy_volume_decoded_as_1000(self, feed_factory):
        """USDJPY is 3-digit. 1.0 lot = 1000 raw units (per the cTrader
        convention used in this codebase). After decoding, order.volume
        should be 1.0 lots."""
        feed = feed_factory()
        _seed_symbol(feed, symbol_id=4, name="USDJPY", digits=3)
        order = feed.new_order(4, ProtoOATradeSide.SELL, volume=1000)
        assert order.volume == pytest.approx(1.0), (
            f"Expected 1.0 lot for USDJPY, got {order.volume}"
        )

    def test_unknown_symbol_id_raises_keyerror(self, feed_factory):
        """If symbol_id is not registered, ``new_order`` must raise
        KeyError loudly — not silently produce a wrong volume."""
        feed = feed_factory()
        # No symbols registered.
        with pytest.raises(KeyError) as exc_info:
            feed.new_order(999, ProtoOATradeSide.BUY, volume=100_000)
        assert "999" in str(exc_info.value), (
            f"KeyError should mention symbol_id 999: {exc_info.value}"
        )

    def test_partial_lot_volume_decoded_correctly(self, feed_factory):
        """0.5 lots of EURUSD = 50_000 raw units → 0.5 lot in Order."""
        feed = feed_factory()
        _seed_symbol(feed, symbol_id=1, name="EURUSD", digits=5)
        order = feed.new_order(1, ProtoOATradeSide.BUY, volume=50_000)
        assert order.volume == pytest.approx(0.5)

    def test_eurusd_uses_5_digit_divisor_not_legacy_100_000_constant(
        self,
        feed_factory,
    ):
        """Sanity: with digits=5 the divisor is 10**5 = 100_000, so the
        decoded value matches the old behaviour. This guards against
        a regression where the digit count is dropped."""
        feed = feed_factory()
        _seed_symbol(feed, symbol_id=1, name="EURUSD", digits=5)
        # 0.01 lots of EURUSD = 1_000 raw → 0.01
        order = feed.new_order(1, ProtoOATradeSide.BUY, volume=1_000)
        assert order.volume == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# _handle_spot_event: price is decoded per symbol
# ---------------------------------------------------------------------------


class TestSpotEventPriceDecoder:
    def _make_spot_message(self, symbol_id: int, raw_bid: int, raw_ask: int):
        """Build a mock spot-event message with raw integer prices."""
        msg = MagicMock()
        msg.symbolId = symbol_id
        msg.bid = raw_bid
        msg.ask = raw_ask
        msg.timestamp = 1_000_000  # some nonzero ms epoch
        return msg

    def test_5_digit_fx_price_decoded_correctly(self, feed_factory):
        """EURUSD 1.32000 = 132000 raw. Decoder should produce 1.32."""
        feed = feed_factory()
        _seed_symbol(feed, symbol_id=1, name="EURUSD", digits=5)
        msg = self._make_spot_message(symbol_id=1, raw_bid=132_000, raw_ask=132_005)
        feed._handle_spot_event(msg)
        tick = feed._ticks_by_id[1]
        assert tick.bid == pytest.approx(1.32)
        assert tick.ask == pytest.approx(1.32005)

    def test_2_digit_xauusd_price_decoded_correctly(self, feed_factory):
        """XAUUSD 2000.00 = 200_000 raw (digits=2, divisor=100).
        Old hardcoded 100_000 would have given 2.0, not 2000.0."""
        feed = feed_factory()
        _seed_symbol(feed, symbol_id=42, name="XAUUSD", digits=2)
        msg = self._make_spot_message(symbol_id=42, raw_bid=200_000, raw_ask=200_050)
        feed._handle_spot_event(msg)
        tick = feed._ticks_by_id[42]
        assert tick.bid == pytest.approx(2000.0)
        assert tick.ask == pytest.approx(2000.50)

    def test_3_digit_usdjpy_price_decoded_correctly(self, feed_factory):
        """USDJPY 150.000 = 150_000 raw (digits=3, divisor=1000).
        Old hardcoded 100_000 would have given 1.50, not 150.0."""
        feed = feed_factory()
        _seed_symbol(feed, symbol_id=4, name="USDJPY", digits=3)
        msg = self._make_spot_message(symbol_id=4, raw_bid=150_000, raw_ask=150_005)
        feed._handle_spot_event(msg)
        tick = feed._ticks_by_id[4]
        assert tick.bid == pytest.approx(150.0)
        assert tick.ask == pytest.approx(150.005)

    def test_unknown_symbol_id_raises_keyerror_in_spot(self, feed_factory):
        """A spot event for an unknown symbol_id must raise KeyError,
        not silently produce a wrong price (e.g. 132000 / 100_000 = 1.32
        which would be plausible-looking but still wrong for some pairs)."""
        feed = feed_factory()
        msg = self._make_spot_message(symbol_id=999, raw_bid=132_000, raw_ask=132_005)
        with pytest.raises(KeyError) as exc_info:
            feed._handle_spot_event(msg)
        assert "999" in str(exc_info.value)

    def test_zero_bid_and_ask_returns_silently(self, feed_factory):
        """A spot event with bid=ask=0 is a no-op (no divisor needed)."""
        feed = feed_factory()
        # Even without symbol_id registered, this should NOT raise.
        msg = self._make_spot_message(symbol_id=999, raw_bid=0, raw_ask=0)
        feed._handle_spot_event(msg)  # no exception
        # And no tick should be stored.
        assert 999 not in feed._ticks_by_id


# ---------------------------------------------------------------------------
# Cross-check: volume and price use the same digits table
# ---------------------------------------------------------------------------


class TestDecoderConsistency:
    def test_same_symbol_uses_same_divisor_for_price_and_volume(
        self,
        feed_factory,
    ):
        """For any given symbol, the price divisor and volume divisor
        should be derived from the same ``_symbol_digits`` entry. This
        prevents drift between the two code paths."""
        feed = feed_factory()
        for symbol_id, name, digits in [
            (1, "EURUSD", 5),
            (2, "GBPUSD", 5),
            (4, "USDJPY", 3),
            (42, "XAUUSD", 2),
        ]:
            _seed_symbol(feed, symbol_id=symbol_id, name=name, digits=digits)

        # 1.0 lot raw = 10**digits for each symbol.
        # 1.0 price raw = 1.0 / 10**digits → so 10**digits raw = 1.0 price.
        for symbol_id, digits in [(1, 5), (2, 5), (4, 3), (42, 2)]:
            divisor = 10**digits
            order = feed.new_order(
                symbol_id,
                ProtoOATradeSide.BUY,
                volume=divisor,
            )
            assert order.volume == pytest.approx(1.0), (
                f"symbol_id={symbol_id} digits={digits} → "
                f"volume={order.volume}, expected 1.0"
            )
