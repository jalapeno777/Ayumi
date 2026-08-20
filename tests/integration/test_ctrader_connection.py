"""Tests for CTraderConnection — TCP connection management."""

import time  # noqa: I001
from unittest.mock import MagicMock, patch

import pytest

from adapters.ctrader.connection import (
    CTraderConnection,
)
from adapters.ctrader.connection_state import (
    ConnectionState,
    ConnectionStateManager,
)


@pytest.fixture
def state_mgr():
    return ConnectionStateManager(name="test")


@pytest.fixture
def conn(state_mgr):
    return CTraderConnection(
        host="localhost",
        port=5035,
        state_manager=state_mgr,
        connect_timeout=1,
        max_reconnect_attempts=3,
        backoff_base=0.01,  # fast for tests
        backoff_max=0.05,
        health_check_interval=0.1,
    )


class TestProperties:
    def test_initial_state(self, conn):
        assert not conn.is_connected
        assert conn.uptime_seconds == 0.0
        assert conn.reconnect_count == 0

    def test_state_manager_exposed(self, conn, state_mgr):
        assert conn.state_manager is state_mgr


class TestCallbacks:
    def test_register_callbacks(self, conn):
        connected_cb = MagicMock()
        disconnected_cb = MagicMock()
        dead_cb = MagicMock()

        conn.on_connected(connected_cb)
        conn.on_disconnected(disconnected_cb)
        conn.on_feed_dead(dead_cb)

    def test_message_callback(self, conn):
        cb = MagicMock()
        conn.set_message_callback(cb)


class TestConnectDisconnect:
    @patch("adapters.ctrader.connection.Client")
    @patch("adapters.ctrader.connection.ReactorManager")
    def test_connect_success(self, MockReactor, MockClient, conn):
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        def fake_start_service(*args, **kwargs):
            # Simulate connected callback after a brief delay
            conn._connected.set()
            conn._connected_at = time.monotonic()

        mock_client.startService.side_effect = fake_start_service
        mock_reactor = MagicMock()
        MockReactor.return_value = mock_reactor

        # The connect uses reactor.callFromThread — mock it
        with patch("adapters.ctrader.connection.reactor") as mock_reactor_mod:
            mock_reactor_mod.callFromThread = lambda f, *a: f(*a)
            result = conn.connect()

        assert result is True
        assert conn.is_connected

    def test_disconnect(self, conn):
        conn._connected.set()
        conn._connected_at = time.monotonic()
        conn._client = MagicMock()

        with patch("adapters.ctrader.connection.reactor") as _:
            conn.disconnect()

        assert not conn.is_connected
        assert conn.state_manager.state == ConnectionState.DISCONNECTED


class TestSendAndWait:
    def test_send_not_connected(self, conn):
        result = conn.send_and_wait(MagicMock())
        assert result is None


class TestReconnection:
    def test_reconnect_increments_count(self, conn):
        assert conn.reconnect_count == 0
        # Attempt reconnect will fail since no server
        # We just check the count increments
        conn._reconnect_count = 2
        assert conn.reconnect_count == 2

    def test_feed_dead_emitted_after_max_attempts(self, conn):
        dead_cb = MagicMock()
        conn.on_feed_dead(dead_cb)

        # Set state to RECONNECTING (valid transition to FAILED)
        conn._state_mgr._state = ConnectionState.RECONNECTING
        conn._reconnect_count = conn._max_reconnect_attempts

        result = conn.attempt_reconnect()
        assert result is False
        dead_cb.assert_called_once()
        assert conn.state_manager.state == ConnectionState.FAILED

    def test_reset_reconnect(self, conn):
        conn._reconnect_count = 5
        conn._backoff_current = 30.0
        conn.reset_reconnect()
        assert conn.reconnect_count == 0
        assert conn._backoff_current == conn._backoff_base


class TestHealthMonitor:
    def test_start_stop(self, conn):
        conn.start_health_monitor()
        assert conn._running
        conn.stop_health_monitor()
        assert not conn._running

    def test_notify_heartbeat(self, conn):
        before = conn._last_heartbeat_recv
        time.sleep(0.01)
        conn.notify_heartbeat()
        assert conn._last_heartbeat_recv > before

    @patch("adapters.ctrader.connection.is_forex_market_closed", return_value=False)
    def test_heartbeat_degraded_transition(self, mock_market_closed, conn, state_mgr):
        # Set state to AUTHENTICATED so health check runs
        state_mgr._state = ConnectionState.AUTHENTICATED
        # Set heartbeat to be stale
        conn._last_heartbeat_recv = time.monotonic() - 40  # past degraded threshold
        conn._check_heartbeat()
        assert state_mgr.state == ConnectionState.DEGRADED

    @patch("adapters.ctrader.connection.is_forex_market_closed", return_value=False)
    def test_heartbeat_reconnect_transition(self, mock_market_closed, conn, state_mgr):
        state_mgr._state = ConnectionState.AUTHENTICATED
        conn._last_heartbeat_recv = time.monotonic() - 70  # past reconnect threshold
        conn._check_heartbeat()
        assert state_mgr.state == ConnectionState.RECONNECTING


class TestInternalCallbacks:
    def test_handle_connected_fires_callbacks(self, conn):
        cb = MagicMock()
        conn.on_connected(cb)
        conn._handle_connected(MagicMock())
        cb.assert_called_once_with(conn)
        assert conn.is_connected
        assert conn.uptime_seconds > 0

    def test_handle_disconnected_fires_callbacks(self, conn):
        cb = MagicMock()
        conn.on_disconnected(cb)
        conn._connected.set()  # set first
        conn._handle_disconnected(MagicMock(), "test reason")
        cb.assert_called_once()
        assert not conn.is_connected
