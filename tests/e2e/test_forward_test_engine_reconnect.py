"""Tests for ForwardTestEngine reconnect circuit-breaker (AYUAA-787)."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from adapters.ctrader.forward_test_engine import (
    _DEFAULT_MAX_RECONNECT_ATTEMPTS,
    ForwardTestConfig,
    ForwardTestEngine,
    _is_forex_market_closed,
)


class TestReconnectCircuitBreaker(unittest.TestCase):
    def _make_engine(self, max_attempts=5, **config_overrides):
        cfg = ForwardTestConfig(
            symbol="GBPUSD",
            max_reconnect_attempts=max_attempts,
            **config_overrides,
        )
        engine = ForwardTestEngine(config=cfg, strategies=[])
        engine._running = True
        engine._market_feed = MagicMock()
        engine._start_market_feed = MagicMock(return_value=False)
        return engine

    def test_reconnect_stops_engine_after_max_attempts(self):
        engine = self._make_engine(max_attempts=3)
        engine._reconnect_delay = 0.0

        for _ in range(3):
            engine._attempt_reconnect()

        assert engine._running is False
        assert engine._health.reconnection_attempts == 3

    def test_reconnect_counter_resets_on_successful_reconnect(self):
        engine = self._make_engine(max_attempts=5)
        engine._reconnect_delay = 0.0
        engine._start_market_feed = MagicMock(return_value=False)

        engine._attempt_reconnect()
        assert engine._health.reconnection_attempts == 1

        engine._start_market_feed = MagicMock(return_value=True)
        engine._market_feed.is_running = True
        engine._attempt_reconnect()
        assert engine._health.reconnection_attempts == 0

    def test_reconnect_does_not_trip_below_max(self):
        engine = self._make_engine(max_attempts=5)
        engine._reconnect_delay = 0.0

        for _ in range(4):
            engine._attempt_reconnect()

        assert engine._running is True
        assert engine._health.reconnection_attempts == 4

    def test_custom_max_reconnect_attempts(self):
        engine = self._make_engine(max_attempts=10)
        engine._reconnect_delay = 0.0

        for _ in range(9):
            engine._attempt_reconnect()

        assert engine._running is True

        engine._attempt_reconnect()
        assert engine._running is False

    def test_default_max_reconnect_attempts_constant(self):
        assert _DEFAULT_MAX_RECONNECT_ATTEMPTS == 20


class TestCheckConnectionHealthResetsCounter(unittest.TestCase):
    def _make_engine(self):
        cfg = ForwardTestConfig(symbol="GBPUSD")
        engine = ForwardTestEngine(config=cfg, strategies=[])
        engine._running = True
        return engine

    def test_healthy_connection_resets_reconnect_counter(self):
        engine = self._make_engine()
        engine._health.reconnection_attempts = 5

        mock_feed = MagicMock()
        mock_feed.is_running = True
        engine._market_feed = mock_feed
        engine._health.last_tick_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

        engine._check_connection_health()
        assert engine._health.reconnection_attempts == 0

    def test_unhealthy_connection_does_not_reset_counter(self):
        engine = self._make_engine()
        engine._health.reconnection_attempts = 3

        mock_feed = MagicMock()
        mock_feed.is_running = False
        engine._market_feed = mock_feed
        engine._health.last_tick_at = None
        engine._last_reconnect_attempt_at = 0.0
        engine._reconnect_delay = 0.0
        engine._start_market_feed = MagicMock(return_value=False)

        engine._check_connection_health()
        assert engine._health.reconnection_attempts == 4


class TestIsForexMarketClosed(unittest.TestCase):
    def test_friday_before_close(self):
        friday = datetime(2026, 4, 17, 21, 54, tzinfo=timezone.utc)
        with patch("adapters.ctrader.forward_test_engine.datetime") as mock_dt:
            mock_dt.now.return_value = friday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _is_forex_market_closed() is False

    def test_friday_after_close(self):
        friday = datetime(2026, 4, 17, 22, 0, tzinfo=timezone.utc)
        with patch("adapters.ctrader.forward_test_engine.datetime") as mock_dt:
            mock_dt.now.return_value = friday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _is_forex_market_closed() is True

    def test_friday_at_close_minute(self):
        friday = datetime(2026, 4, 17, 21, 55, tzinfo=timezone.utc)
        with patch("adapters.ctrader.forward_test_engine.datetime") as mock_dt:
            mock_dt.now.return_value = friday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _is_forex_market_closed() is True

    def test_saturday(self):
        sat = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)
        with patch("adapters.ctrader.forward_test_engine.datetime") as mock_dt:
            mock_dt.now.return_value = sat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _is_forex_market_closed() is True

    def test_sunday_before_open(self):
        sun = datetime(2026, 4, 19, 20, 59, tzinfo=timezone.utc)
        with patch("adapters.ctrader.forward_test_engine.datetime") as mock_dt:
            mock_dt.now.return_value = sun
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _is_forex_market_closed() is True

    def test_sunday_at_open(self):
        sun = datetime(2026, 4, 19, 21, 0, tzinfo=timezone.utc)
        with patch("adapters.ctrader.forward_test_engine.datetime") as mock_dt:
            mock_dt.now.return_value = sun
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _is_forex_market_closed() is False

    def test_monday_before_open(self):
        mon = datetime(2026, 4, 20, 0, 0, tzinfo=timezone.utc)
        with patch("adapters.ctrader.forward_test_engine.datetime") as mock_dt:
            mock_dt.now.return_value = mon
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _is_forex_market_closed() is True

    def test_monday_after_open(self):
        mon = datetime(2026, 4, 20, 22, 0, tzinfo=timezone.utc)
        with patch("adapters.ctrader.forward_test_engine.datetime") as mock_dt:
            mock_dt.now.return_value = mon
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _is_forex_market_closed() is False

    def test_wednesday(self):
        wed = datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc)
        with patch("adapters.ctrader.forward_test_engine.datetime") as mock_dt:
            mock_dt.now.return_value = wed
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _is_forex_market_closed() is False


class TestMarketClosedSuppressesReconnect(unittest.TestCase):
    def _make_engine(self):
        cfg = ForwardTestConfig(
            symbol="GBPUSD",
            stale_tick_threshold_sec=30.0,
        )
        engine = ForwardTestEngine(config=cfg, strategies=[])
        engine._running = True
        engine._last_reconnect_attempt_at = 0.0
        engine._reconnect_delay = 0.0
        engine._start_market_feed = MagicMock(return_value=False)
        return engine

    @patch(
        "adapters.ctrader.forward_test_engine._is_forex_market_closed",
        return_value=True,
    )
    def test_no_reconnect_when_market_closed_and_connected(self, mock_closed):
        engine = self._make_engine()
        engine._health.reconnection_attempts = 0

        mock_feed = MagicMock()
        mock_feed.is_running = True
        engine._market_feed = mock_feed
        engine._health.last_tick_at = datetime.now(timezone.utc) - timedelta(seconds=120)

        engine._check_connection_health()
        assert engine._health.reconnection_attempts == 0
        engine._start_market_feed.assert_not_called()

    @patch(
        "adapters.ctrader.forward_test_engine._is_forex_market_closed",
        return_value=True,
    )
    def test_reconnect_counter_resets_on_market_closed(self, mock_closed):
        engine = self._make_engine()
        engine._health.reconnection_attempts = 5

        mock_feed = MagicMock()
        mock_feed.is_running = True
        engine._market_feed = mock_feed
        engine._health.last_tick_at = datetime.now(timezone.utc) - timedelta(seconds=120)

        engine._check_connection_health()
        assert engine._health.reconnection_attempts == 0

    @patch(
        "adapters.ctrader.forward_test_engine._is_forex_market_closed",
        return_value=False,
    )
    def test_reconnect_still_fires_when_market_open_and_disconnected(self, mock_closed):
        engine = self._make_engine()

        mock_feed = MagicMock()
        mock_feed.is_running = False
        engine._market_feed = mock_feed
        engine._health.last_tick_at = None

        engine._check_connection_health()
        assert engine._health.reconnection_attempts == 1

    @patch(
        "adapters.ctrader.forward_test_engine._is_forex_market_closed",
        return_value=True,
    )
    def test_reconnect_fires_when_market_closed_and_feed_disconnected(self, mock_closed):
        engine = self._make_engine()

        mock_feed = MagicMock()
        mock_feed.is_running = False
        engine._market_feed = mock_feed
        engine._health.last_tick_at = None

        engine._check_connection_health()
        assert engine._health.reconnection_attempts == 1
