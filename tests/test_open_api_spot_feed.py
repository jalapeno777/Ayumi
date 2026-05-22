"""Tests for OpenApiSpotFeed — tick callbacks, token refresh, reconnection, multi-symbol subscriptions."""

import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from adapters.ctrader.open_api_spot_feed import (
    OpenApiSpotFeed,
    _normalize_symbol_name,
)
# Reconnect constants were removed from the module; provide defaults for tests.
_MAX_RECONNECT_ATTEMPTS = getattr(
    __import__("adapters.ctrader.open_api_spot_feed", fromlist=["_MAX_RECONNECT_ATTEMPTS"]),
    "_MAX_RECONNECT_ATTEMPTS", 20,
)
_INITIAL_RECONNECT_DELAY = getattr(
    __import__("adapters.ctrader.open_api_spot_feed", fromlist=["_INITIAL_RECONNECT_DELAY"]),
    "_INITIAL_RECONNECT_DELAY", 5.0,
)
_MAX_RECONNECT_DELAY = getattr(
    __import__("adapters.ctrader.open_api_spot_feed", fromlist=["_MAX_RECONNECT_DELAY"]),
    "_MAX_RECONNECT_DELAY", 120.0,
)
_STABLE_CONNECTION_SECONDS = getattr(
    __import__("adapters.ctrader.open_api_spot_feed", fromlist=["_STABLE_CONNECTION_SECONDS"]),
    "_STABLE_CONNECTION_SECONDS", 60,
)
from adapters.ctrader.market_data_feed import Tick
from adapters.ctrader.models import SymbolInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feed(**kwargs) -> OpenApiSpotFeed:
    """Create an OpenApiSpotFeed with mock reactor manager so nothing touches the network."""
    defaults = dict(
        ctid_account_id=99999,
        client_id="test-client",
        client_secret="test-secret",
        access_token="test-access-token",
    )
    defaults.update(kwargs)
    with patch("adapters.ctrader.open_api_spot_feed.ReactorManager"):
        feed = OpenApiSpotFeed(**defaults)
    # Replace reactor references with a mock so callFromThread is safe
    feed._reactor_manager = MagicMock()
    return feed


def _make_spot_event(symbol_id=1, bid=108500, ask=108520, timestamp_ms=1715000000000):
    """Build a fake protobuf spot event message."""
    msg = MagicMock()
    msg.symbolId = symbol_id
    msg.bid = bid
    msg.ask = ask
    msg.timestamp = timestamp_ms
    return msg


# ---------------------------------------------------------------------------
# Symbol normalization
# ---------------------------------------------------------------------------

class TestNormalizeSymbolName:
    def test_slash_stripped_and_uppered(self):
        assert _normalize_symbol_name("EUR/USD") == "EURUSD"

    def test_underscore_stripped_and_uppered(self):
        assert _normalize_symbol_name("gbp_usd") == "GBPUSD"

    def test_mixed_separators(self):
        assert _normalize_symbol_name("EUR/USD_JPY") == "EURUSDJPY"

    def test_already_canonical(self):
        assert _normalize_symbol_name("EURUSD") == "EURUSD"

    def test_lowercase(self):
        assert _normalize_symbol_name("eurusd") == "EURUSD"


# ---------------------------------------------------------------------------
# on_tick callback path
# ---------------------------------------------------------------------------

class TestOnTickCallback:
    def setup_method(self):
        self.feed = _make_feed()
        # Seed symbol mappings so spot events can resolve names
        self.feed._id_to_name[1] = "EUR/USD"
        self.feed._id_to_name[2] = "GBP/USD"

    def test_callback_fires_with_correct_tick(self):
        received = []
        self.feed.on_tick(received.append)

        event = _make_spot_event(symbol_id=1, bid=108500, ask=108520)
        self.feed._handle_spot_event(event)

        assert len(received) == 1
        tick = received[0]
        assert tick.symbol_id == 1
        assert tick.bid == pytest.approx(1.08500)
        assert tick.ask == pytest.approx(1.08520)
        assert tick.spread == pytest.approx(0.00020)

    def test_callback_gets_correct_timestamp(self):
        received = []
        self.feed.on_tick(received.append)

        event = _make_spot_event(symbol_id=1, timestamp_ms=1715000000000)
        self.feed._handle_spot_event(event)

        expected_ts = datetime.fromtimestamp(1715000000000 / 1000, tz=timezone.utc)
        assert received[0].timestamp == expected_ts

    def test_symbol_normalization_in_ticks_dict(self):
        self.feed._handle_spot_event(_make_spot_event(symbol_id=1))
        assert "EURUSD" in self.feed.ticks

    def test_unsubscribed_symbol_still_processed(self):
        """Spot events arrive for any symbol — filtering is subscription-level, not event-level."""
        received = []
        self.feed.on_tick(received.append)
        # symbol_id=99 has no mapping — it still gets processed
        self.feed._handle_spot_event(_make_spot_event(symbol_id=99))
        assert len(received) == 1
        assert received[0].symbol_id == 99

    def test_malformed_zero_bid_ask_does_not_crash(self):
        """Completely empty tick (0,0) is silently skipped."""
        received = []
        self.feed.on_tick(received.append)
        event = _make_spot_event(bid=0, ask=0)
        self.feed._handle_spot_event(event)
        assert len(received) == 0

    def test_bid_ge_ask_rejected(self):
        received = []
        self.feed.on_tick(received.append)
        # bid == ask
        event = _make_spot_event(bid=108500, ask=108500)
        self.feed._handle_spot_event(event)
        assert len(received) == 0

    def test_spread_too_wide_rejected(self):
        received = []
        self.feed.on_tick(received.append)
        # 100-pip spread on EUR/USD — way too wide
        event = _make_spot_event(bid=108500, ask=115500)
        self.feed._handle_spot_event(event)
        assert len(received) == 0

    def test_callback_exception_does_not_kill_feed(self):
        bad_cb = MagicMock(side_effect=RuntimeError("boom"))
        ok_received = []
        self.feed.on_tick(bad_cb)
        self.feed.on_tick(ok_received.append)

        self.feed._handle_spot_event(_make_spot_event(symbol_id=1))
        assert len(ok_received) == 1  # second callback still fires

    def test_partial_tick_uses_last_known_prices(self):
        received = []
        self.feed.on_tick(received.append)

        # Full tick first
        self.feed._handle_spot_event(_make_spot_event(symbol_id=1, bid=108500, ask=108520))
        # Partial tick — only bid updated
        self.feed._handle_spot_event(_make_spot_event(symbol_id=1, bid=108510, ask=0))

        assert len(received) == 2
        assert received[1].bid == pytest.approx(1.08510)
        assert received[1].ask == pytest.approx(1.08520)  # carried over

    def test_partial_tick_no_prior_data_skipped(self):
        received = []
        self.feed.on_tick(received.append)
        # No prior tick for symbol_id=50
        self.feed._handle_spot_event(_make_spot_event(symbol_id=50, bid=108500, ask=0))
        assert len(received) == 0

    def test_tick_counts_increment(self):
        self.feed._handle_spot_event(_make_spot_event(symbol_id=1))
        self.feed._handle_spot_event(_make_spot_event(symbol_id=1))
        self.feed._handle_spot_event(_make_spot_event(symbol_id=2))
        counts = self.feed.tick_counts
        assert counts["EURUSD"] == 2
        assert counts["GBPUSD"] == 1

    def test_get_tick_returns_latest(self):
        self.feed._handle_spot_event(_make_spot_event(symbol_id=1, bid=108500, ask=108520))
        tick = self.feed.get_tick("EUR/USD")
        assert tick is not None
        assert tick.bid == pytest.approx(1.08500)

    def test_get_tick_normalizes_input(self):
        self.feed._handle_spot_event(_make_spot_event(symbol_id=1))
        assert self.feed.get_tick("eur_usd") is not None
        assert self.feed.get_tick("EURUSD") is not None


# ---------------------------------------------------------------------------
# Token refresh flow
# ---------------------------------------------------------------------------

class TestTokenRefresh:
    def test_refresh_token_read_from_env(self):
        with patch.dict("os.environ", {"CTRADER_OPENAPI_REFRESH_TOKEN": "env-token"}):
            feed = _make_feed()
        assert feed._refresh_token == "env-token"

    def test_refresh_token_defaults_empty(self):
        with patch.dict("os.environ", {}, clear=True):
            feed = _make_feed()
        assert feed._refresh_token == ""

    def test_refresh_success_updates_tokens(self):
        feed = _make_feed()
        feed._refresh_token = "old-refresh"

        # Mock the HTTP call and reactor
        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
        }

        with patch("adapters.ctrader.open_api_spot_feed.reactor") as mock_reactor, \
             patch("requests.post", return_value=mock_post_resp) as mock_post:
            mock_reactor.callFromThread = MagicMock()
            feed._refresh_token_and_reauth()

        assert feed._access_token == "new-access"
        assert feed._refresh_token == "new-refresh"
        mock_reactor.callFromThread.assert_called_once()

    def test_refresh_api_error_handled_gracefully(self):
        feed = _make_feed()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "errorCode": "SOME_ERROR",
            "description": "bad request",
        }

        import adapters.ctrader.open_api_spot_feed as mod
        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_response
        with patch.object(mod, "requests", mock_requests, create=True):
            feed._refresh_token = "old-refresh"
            feed._refresh_token_and_reauth()  # should not raise

        # access_token unchanged
        assert feed._access_token == "test-access-token"

    def test_refresh_network_failure_handled_gracefully(self):
        feed = _make_feed()
        import adapters.ctrader.open_api_spot_feed as mod
        mock_requests = MagicMock()
        mock_requests.post.side_effect = ConnectionError("network down")
        with patch.object(mod, "requests", mock_requests, create=True):
            feed._refresh_token = "old-refresh"
            feed._refresh_token_and_reauth()  # should not raise

    def test_auth_error_triggers_refresh(self):
        feed = _make_feed()
        mock_error = MagicMock()
        mock_error.errorCode = "CH_OAUTH_TOKEN_EXPIRED"
        mock_error.description = "token expired"

        with patch.object(feed, "_refresh_token_and_reauth") as mock_refresh:
            feed._handle_error(mock_error)
            mock_refresh.assert_called_once()

    def test_non_auth_error_does_not_trigger_refresh(self):
        feed = _make_feed()
        mock_error = MagicMock()
        mock_error.errorCode = "SOME_OTHER_ERROR"
        mock_error.description = "something else"

        with patch.object(feed, "_refresh_token_and_reauth") as mock_refresh:
            feed._handle_error(mock_error)
            mock_refresh.assert_not_called()


# ---------------------------------------------------------------------------
# Reconnection logic
# ---------------------------------------------------------------------------

class TestReconnection:
    def test_disconnect_triggers_reconnect_when_running(self):
        feed = _make_feed()
        feed._running = True

        with patch.object(feed, "_schedule_reconnect") as mock_sched:
            feed._on_disconnected(None, "connection lost")
            mock_sched.assert_called_once()

    def test_disconnect_does_not_reconnect_when_stopped(self):
        feed = _make_feed()
        feed._running = False

        with patch.object(feed, "_schedule_reconnect") as mock_sched:
            feed._on_disconnected(None, "connection lost")
            mock_sched.assert_not_called()

    def test_disconnect_does_not_reconnect_when_stop_event_set(self):
        feed = _make_feed()
        feed._running = True
        feed._stop_event.set()

        with patch.object(feed, "_schedule_reconnect") as mock_sched:
            feed._on_disconnected(None, "connection lost")
            mock_sched.assert_not_called()

    def test_reconnect_backoff_increases(self):
        feed = _make_feed()
        initial = feed._reconnect_delay

        feed._schedule_reconnect()
        after_first = feed._reconnect_delay
        assert after_first > initial

        feed._schedule_reconnect()
        after_second = feed._reconnect_delay
        assert after_second > after_first

    def test_reconnect_delay_capped_at_max(self):
        feed = _make_feed()
        feed._reconnect_delay = _MAX_RECONNECT_DELAY

        feed._schedule_reconnect()
        assert feed._reconnect_delay <= _MAX_RECONNECT_DELAY

    def test_max_reconnect_attempts_circuit_breaker(self):
        feed = _make_feed()
        feed._running = True
        feed._reconnect_attempts = _MAX_RECONNECT_ATTEMPTS

        # Should stop running, not schedule another
        with patch("threading.Timer") as mock_timer:
            feed._schedule_reconnect()
            mock_timer.assert_not_called()
        assert feed._running is False

    def test_reconnect_clears_state(self):
        feed = _make_feed()
        feed._running = True
        feed._connected.set()
        feed._authed.set()
        feed._app_authed.set()

        feed._on_disconnected(None, "lost")
        assert not feed._connected.is_set()
        assert not feed._authed.is_set()
        assert not feed._app_authed.is_set()

    def test_connected_sets_connected_at(self):
        feed = _make_feed()
        feed._on_connected(None)
        assert feed._connected_at is not None

    def test_do_reconnect_resubscribes_symbols(self):
        feed = _make_feed()
        feed._running = True
        feed._subscribed_symbol_ids = {1, 2}

        with patch.object(feed, "_connect", return_value=True), \
             patch.object(feed, "_auth", return_value=True), \
             patch.object(feed, "_subscribe_by_id") as mock_sub:
            feed._do_reconnect()
            assert mock_sub.call_count == 2

    def test_do_reconnect_schedules_retry_on_connect_failure(self):
        feed = _make_feed()
        feed._running = True

        with patch.object(feed, "_connect", return_value=False), \
             patch.object(feed, "_schedule_reconnect") as mock_sched:
            feed._do_reconnect()
            mock_sched.assert_called_once()


# ---------------------------------------------------------------------------
# Multi-symbol subscription
# ---------------------------------------------------------------------------

class TestMultiSymbolSubscription:
    def setup_method(self):
        self.feed = _make_feed()
        self.feed._name_to_id["EURUSD"] = 1
        self.feed._name_to_id["GBPUSD"] = 2
        self.feed._name_to_id["USDJPY"] = 3
        self.feed._id_to_name[1] = "EUR/USD"
        self.feed._id_to_name[2] = "GBP/USD"
        self.feed._id_to_name[3] = "USD/JPY"
        self.feed._symbol_digits[1] = 5
        self.feed._symbol_digits[2] = 5
        self.feed._symbol_digits[3] = 3

    def test_subscribe_multiple_symbols(self):
        with patch("adapters.ctrader.open_api_spot_feed.reactor") as mock_reactor:
            assert self.feed.subscribe("EUR/USD")
            assert self.feed.subscribe("GBP/USD")
            assert 1 in self.feed._subscribed_symbol_ids
            assert 2 in self.feed._subscribed_symbol_ids

    def test_unsubscribe_removes_symbol(self):
        with patch("adapters.ctrader.open_api_spot_feed.reactor") as mock_reactor:
            self.feed.subscribe("EUR/USD")
            self.feed.subscribe("GBP/USD")
            self.feed.unsubscribe("EUR/USD")
            assert 1 not in self.feed._subscribed_symbol_ids
            assert 2 in self.feed._subscribed_symbol_ids

    def test_ticks_route_to_correct_symbol(self):
        received = {"EURUSD": [], "GBPUSD": []}
        self.feed.on_tick(lambda t: received.setdefault(
            _normalize_symbol_name(self.feed._id_to_name.get(t.symbol_id, "")),
            []
        ).append(t))

        self.feed._handle_spot_event(_make_spot_event(symbol_id=1, bid=108500, ask=108520))
        self.feed._handle_spot_event(_make_spot_event(symbol_id=2, bid=126500, ask=126520))

        assert len(received["EURUSD"]) == 1
        assert len(received["GBPUSD"]) == 1
        assert received["EURUSD"][0].bid == pytest.approx(1.08500)
        assert received["GBPUSD"][0].bid == pytest.approx(1.26500)

    def test_subscribe_unknown_symbol_returns_false(self):
        assert self.feed.subscribe("UNKNOWN/PAIR") is False

    def test_subscribe_normalizes_name(self):
        with patch("adapters.ctrader.open_api_spot_feed.reactor"):
            assert self.feed.subscribe("eur_usd") is True
            assert 1 in self.feed._subscribed_symbol_ids

    def test_get_all_ticks(self):
        self.feed._handle_spot_event(_make_spot_event(symbol_id=1))
        self.feed._handle_spot_event(_make_spot_event(symbol_id=2))
        all_ticks = self.feed.get_all_ticks()
        assert "EURUSD" in all_ticks
        assert "GBPUSD" in all_ticks

    def test_get_spread(self):
        self.feed._handle_spot_event(_make_spot_event(symbol_id=1, bid=108500, ask=108520))
        assert self.feed.get_spread("EUR/USD") == pytest.approx(0.00020)

    def test_get_spread_no_tick(self):
        assert self.feed.get_spread("UNKNOWN") is None

    def test_multiple_callbacks_all_fire(self):
        cb1, cb2 = [], []
        self.feed.on_tick(cb1.append)
        self.feed.on_tick(cb2.append)
        self.feed._handle_spot_event(_make_spot_event(symbol_id=1))
        assert len(cb1) == 1 and len(cb2) == 1


# ---------------------------------------------------------------------------
# Static symbol fallback
# ---------------------------------------------------------------------------

class TestStaticSymbolsFallback:
    def test_populate_static_symbols(self):
        feed = _make_feed()
        feed._populate_static_symbols()
        assert feed._name_to_id["EURUSD"] == 1
        assert feed._name_to_id["GBPUSD"] == 2
        assert feed._name_to_id["USDJPY"] == 4
        assert feed._symbols_loaded.is_set()


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_is_running_default_false(self):
        feed = _make_feed()
        assert feed.is_running is False

    def test_symbols_returns_copy(self):
        feed = _make_feed()
        feed._symbols[1] = SymbolInfo(symbol_id=1, name="EUR/USD")
        copy = feed.symbols
        copy[99] = SymbolInfo(symbol_id=99, name="FAKE")
        assert 99 not in feed._symbols

    def test_ticks_returns_copy(self):
        feed = _make_feed()
        copy = feed.ticks
        copy["FAKE"] = Tick(symbol_id=99, bid=1.0, ask=1.1)
        assert "FAKE" not in feed._ticks
