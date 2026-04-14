"""Tests for ForwardTestEngine reconnect circuit-breaker (AYUAA-787)."""

import unittest
from unittest.mock import MagicMock

from adapters.ctrader.forward_test_engine import (
    ForwardTestConfig,
    ForwardTestEngine,
    _DEFAULT_MAX_RECONNECT_ATTEMPTS,
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
        engine._health.last_tick_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )

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
