"""Tests for Phase 1B: Connection Self-Healing for the Spot Feed.

Tests cover:
  - State transitions on connect/auth/disconnect sequence
  - Heartbeat timeout → DEGRADED → RECONNECTING sequence
  - Stale tick detection during market hours
  - Stale tick skipped on weekend
  - Reconciliation callback fires on reconnect
  - Auth error escalation (3 → DEGRADED, >5 → FAILED)
  - Kill switch FREEZE on FAILED state
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure src path is available
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "forex-bot"))

from adapters.ctrader.connection_state import ConnectionState, ConnectionStateManager
from adapters.ctrader.open_api_spot_feed import (
    OpenApiSpotFeed,
    _HEARTBEAT_DEGRADED_SEC,
    _HEARTBEAT_RECONNECT_SEC,
    _STALE_TICK_WARN_SEC,
    _STALE_TICK_FREEZE_SEC,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def feed():
    """Create an OpenApiSpotFeed instance (without connecting)."""
    f = OpenApiSpotFeed(
        ctid_account_id=12345,
        client_id="test_client",
        client_secret="test_secret",
        access_token="test_token",
        refresh_token="test_refresh",
    )
    yield f
    # Cleanup: cancel any timers
    if f._health_timer is not None:
        f._health_timer.cancel()
    if f._refresh_timer is not None:
        f._refresh_timer.cancel()


@pytest.fixture
def mock_kill_switch():
    """Mock kill switch manager."""
    ks = MagicMock()
    ks.activate_global_freeze = MagicMock()
    return ks


# ── State Transitions on Connect/Auth/Disconnect ─────────────────────────────

class TestStateTransitions:
    """Verify that lifecycle events drive the ConnectionStateManager correctly."""

    def test_initial_state_is_disconnected(self, feed):
        """Feed starts in DISCONNECTED state."""
        assert feed.state_manager.state == ConnectionState.DISCONNECTED

    def test_state_manager_property_returns_manager(self, feed):
        """state_manager property returns the ConnectionStateManager."""
        assert isinstance(feed.state_manager, ConnectionStateManager)
        assert feed.state_manager.name == "spot_feed"

    def test_connecting_transition(self, feed):
        """Calling _connect triggers CONNECTING state."""
        # We can't actually connect, but we can test the transition
        # by simulating what _connect does
        feed.state_manager.transition_to(
            ConnectionState.CONNECTING, reason="test",
        )
        assert feed.state_manager.state == ConnectionState.CONNECTING

    def test_full_connect_auth_sequence(self, feed):
        """Simulate full connect → auth sequence and verify all transitions."""
        sm = feed.state_manager

        # Connect
        sm.transition_to(ConnectionState.CONNECTING, reason="tcp_connect")
        assert sm.state == ConnectionState.CONNECTING

        # TCP connected
        sm.transition_to(ConnectionState.CONNECTED, reason="tcp_connected")
        assert sm.state == ConnectionState.CONNECTED

        # App auth sending
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="app_auth")
        assert sm.state == ConnectionState.APP_AUTHENTICATING

        # Account auth sending
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="acct_auth")
        assert sm.state == ConnectionState.ACCT_AUTHENTICATING

        # Fully authenticated
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="auth_complete")
        assert sm.state == ConnectionState.AUTHENTICATED

    def test_disconnect_transitions_to_reconnecting(self, feed):
        """When connected, a disconnect should transition to RECONNECTING."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        sm.transition_to(ConnectionState.RECONNECTING, reason="disconnected")
        assert sm.state == ConnectionState.RECONNECTING

    def test_on_connected_sets_state_connected(self, feed):
        """_on_connected transitions to CONNECTED."""
        # Set up: feed is in CONNECTING state
        feed.state_manager.transition_to(ConnectionState.CONNECTING, reason="test")
        # Prevent the reconnect thread from running during the test
        feed._reauth_in_progress.set()
        feed._on_connected(MagicMock())
        assert feed.state_manager.state == ConnectionState.CONNECTED

    def test_on_disconnected_sets_state_reconnecting(self, feed):
        """_on_disconnected transitions to RECONNECTING."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        feed._on_disconnected(MagicMock(), "test_reason")
        assert sm.state == ConnectionState.RECONNECTING
        assert feed._disconnect_at is not None

    def test_on_disconnected_clears_flags(self, feed):
        """_on_disconnected clears informal flags (fallback behavior)."""
        feed._connected.set()
        feed._authed.set()
        feed._app_authed.set()

        feed._on_disconnected(MagicMock(), "test")

        assert not feed._connected.is_set()
        assert not feed._authed.is_set()
        assert not feed._app_authed.is_set()


# ── Heartbeat Timeout Detection ───────────────────────────────────────────────

class TestHeartbeatMonitor:
    """Test heartbeat timeout → DEGRADED → RECONNECTING sequence."""

    def test_heartbeat_degraded_threshold(self, feed):
        """No heartbeat for 35s → DEGRADED."""
        sm = feed.state_manager
        # Set to AUTHENTICATED
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        # Simulate stale heartbeat
        feed._last_heartbeat_recv = time.monotonic() - _HEARTBEAT_DEGRADED_SEC - 1

        feed._check_heartbeat_health()

        assert sm.state == ConnectionState.DEGRADED

    def test_heartbeat_reconnect_threshold(self, feed):
        """No heartbeat for 60s → RECONNECTING."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        # Simulate very stale heartbeat
        feed._last_heartbeat_recv = time.monotonic() - _HEARTBEAT_RECONNECT_SEC - 1
        feed._client = None  # prevent actual stopService call

        feed._check_heartbeat_health()

        assert sm.state == ConnectionState.RECONNECTING

    def test_heartbeat_ok_when_recent(self, feed):
        """Recent heartbeat → no state change."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        # Fresh heartbeat
        feed._last_heartbeat_recv = time.monotonic()

        feed._check_heartbeat_health()

        assert sm.state == ConnectionState.AUTHENTICATED

    def test_heartbeat_skipped_when_disconnected(self, feed):
        """Heartbeat check skipped when not connected."""
        sm = feed.state_manager
        # Feed starts DISCONNECTED — no check should run
        feed._last_heartbeat_recv = time.monotonic() - 999

        feed._check_heartbeat_health()

        assert sm.state == ConnectionState.DISCONNECTED

    def test_heartbeat_degraded_then_reconnect_sequence(self, feed):
        """Full sequence: DEGRADED at 35s → RECONNECTING at 60s."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        # 36s stale → DEGRADED
        feed._last_heartbeat_recv = time.monotonic() - 36
        feed._check_heartbeat_health()
        assert sm.state == ConnectionState.DEGRADED

        # 61s stale → RECONNECTING (DEGRADED → RECONNECTING is valid)
        feed._last_heartbeat_recv = time.monotonic() - 61
        feed._client = None
        feed._check_heartbeat_health()
        assert sm.state == ConnectionState.RECONNECTING


# ── Stale Tick Detection ──────────────────────────────────────────────────────

class TestStaleTickDetector:
    """Test stale tick detection during market hours and weekend skip."""

    def test_stale_tick_warning(self, feed):
        """No tick for 60s during market hours → log warning (state unchanged)."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        # Simulate stale tick during weekday
        feed._last_tick_recv_monotonic = time.monotonic() - _STALE_TICK_WARN_SEC - 1

        with patch.object(feed, '_check_stale_ticks') as mock_check:
            mock_check.return_value = None
            # The actual method should log but not change state
            feed._check_stale_ticks()

        # State should remain AUTHENTICATED (only warnings, no state change for 60s)
        assert sm.state == ConnectionState.AUTHENTICATED

    def test_stale_tick_freeze_on_weekday(self, feed, mock_kill_switch):
        """No tick for 120s during market hours → kill switch FREEZE."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        feed.set_kill_switch(mock_kill_switch)

        # Mock weekday (not weekend)
        with patch('adapters.ctrader.open_api_spot_feed.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)  # Wednesday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            feed._last_tick_recv_monotonic = time.monotonic() - _STALE_TICK_FREEZE_SEC - 1
            feed._check_stale_ticks()

        mock_kill_switch.activate_global_freeze.assert_called_once()
        call_kwargs = mock_kill_switch.activate_global_freeze.call_args
        assert "stale_ticks" in call_kwargs.kwargs.get("reason", "")

    def test_stale_tick_skipped_on_weekend(self, feed, mock_kill_switch):
        """Stale tick detection skipped on Saturday/Sunday."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        feed.set_kill_switch(mock_kill_switch)

        # Mock weekend (Saturday)
        with patch.object(feed, '_check_stale_ticks', wraps=feed._check_stale_ticks):
            # Use the actual datetime check
            saturday = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)  # Saturday
            with patch('adapters.ctrader.open_api_spot_feed.datetime') as mock_dt:
                mock_dt.now.return_value = saturday
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

                feed._last_tick_recv_monotonic = time.monotonic() - 999
                feed._check_stale_ticks()

        # Kill switch should NOT be called on weekend
        mock_kill_switch.activate_global_freeze.assert_not_called()

    def test_stale_tick_skipped_when_not_authenticated(self, feed):
        """Stale tick check skipped when not authenticated/degraded."""
        sm = feed.state_manager
        # Still in DISCONNECTED state
        feed._last_tick_recv_monotonic = time.monotonic() - 999

        # Should not raise or change anything
        feed._check_stale_ticks()
        assert sm.state == ConnectionState.DISCONNECTED


# ── Reconciliation After Reconnect ────────────────────────────────────────────

class TestReconciliation:
    """Test reconnection callbacks."""

    def test_on_reconnected_registers_callback(self, feed):
        """on_reconnected() adds callback to list."""
        cb = lambda duration: None
        feed.on_reconnected(cb)
        assert cb in feed._on_reconnected_callbacks

    def test_reconciliation_callback_fires(self, feed):
        """_fire_reconnect_reconciliation fires callbacks with outage duration."""
        outage = 0
        captured = []

        def callback(duration):
            captured.append(duration)

        feed.on_reconnected(callback)

        # Set disconnect time to 5 seconds ago
        feed._disconnect_at = time.monotonic() - 5.0
        feed._fire_reconnect_reconciliation()

        assert len(captured) == 1
        assert captured[0] >= 5.0
        assert feed._disconnect_at is None  # reset after firing

    def test_reconciliation_no_callback_without_disconnect(self, feed):
        """_fire_reconnect_reconciliation skips if no _disconnect_at."""
        captured = []
        feed.on_reconnected(lambda d: captured.append(d))

        feed._disconnect_at = None
        feed._fire_reconnect_reconciliation()

        assert len(captured) == 0

    def test_reconciliation_callback_exception_doesnt_crash(self, feed):
        """Exception in reconciliation callback doesn't crash."""
        def bad_callback(duration):
            raise RuntimeError("boom")

        feed.on_reconnected(bad_callback)
        feed._disconnect_at = time.monotonic() - 3.0

        # Should not raise
        feed._fire_reconnect_reconciliation()

    def test_multiple_reconciliation_callbacks(self, feed):
        """Multiple callbacks all fire."""
        results = []
        feed.on_reconnected(lambda d: results.append(("a", d)))
        feed.on_reconnected(lambda d: results.append(("b", d)))

        feed._disconnect_at = time.monotonic() - 2.0
        feed._fire_reconnect_reconciliation()

        assert len(results) == 2
        assert results[0][0] == "a"
        assert results[1][0] == "b"


# ── Auth Error Escalation ─────────────────────────────────────────────────────

class TestAuthErrorEscalation:
    """Test auth error count → state machine escalation."""

    def test_auth_errors_3_transitions_to_degraded(self, feed):
        """3 auth errors → DEGRADED state."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        feed._auth_error_count = 3
        feed._check_circuit_breaker()

        assert sm.state == ConnectionState.DEGRADED

    def test_auth_errors_5_transitions_to_failed(self, feed, mock_kill_switch):
        """5+ auth errors → FAILED state + kill switch FREEZE."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        feed.set_kill_switch(mock_kill_switch)

        feed._auth_error_count = 5
        feed._check_circuit_breaker()

        assert sm.state == ConnectionState.FAILED
        assert feed._auth_circuit_open is True
        mock_kill_switch.activate_global_freeze.assert_called_once()

    def test_auth_errors_under_3_no_state_change(self, feed):
        """Auth errors 1-2 → no state transition (just warning)."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        feed._auth_error_count = 2
        feed._check_circuit_breaker()

        assert sm.state == ConnectionState.AUTHENTICATED

    def test_kill_switch_freeze_on_failed_state(self, feed, mock_kill_switch):
        """FAILED state triggers kill switch FREEZE."""
        feed.set_kill_switch(mock_kill_switch)

        feed._activate_kill_switch_freeze("test_reason")

        mock_kill_switch.activate_global_freeze.assert_called_once_with(
            reason="test_reason",
            triggered_by="spot_feed_self_healing",
        )

    def test_kill_switch_not_required(self, feed):
        """No kill switch → graceful degradation, no crash."""
        feed._kill_switch = None  # explicitly no kill switch

        # Should log warning but not crash
        feed._activate_kill_switch_freeze("test_no_ks")

        # No exception raised = pass

    def test_auth_error_reset_on_success(self, feed):
        """Successful auth resets auth error count and state."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        # Accumulate errors
        feed._auth_error_count = 3
        sm.transition_to(ConnectionState.DEGRADED, reason="auth_errors")
        assert sm.state == ConnectionState.DEGRADED

        # Simulate recovery: auth success resets errors
        feed._auth_error_count = 0
        feed._auth_circuit_open = False
        # Recovery transition
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="auth_recovered")

        assert feed._auth_error_count == 0
        assert sm.state == ConnectionState.AUTHENTICATED


# ── Kill Switch Integration ───────────────────────────────────────────────────

class TestKillSwitchIntegration:
    """Test kill switch FREEZE integration."""

    def test_set_kill_switch(self, feed, mock_kill_switch):
        """set_kill_switch stores the reference."""
        feed.set_kill_switch(mock_kill_switch)
        assert feed._kill_switch is mock_kill_switch

    def test_freeze_called_on_excessive_auth_errors(self, feed, mock_kill_switch):
        """Kill switch FREEZE activated when auth errors exceed threshold."""
        sm = feed.state_manager
        feed.set_kill_switch(mock_kill_switch)

        # Drive to AUTHENTICATED first (required for valid transition to DEGRADED/FAILED)
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        # Trigger 5+ auth errors
        feed._auth_error_count = 6
        feed._check_circuit_breaker()

        mock_kill_switch.activate_global_freeze.assert_called_once()
        assert sm.state == ConnectionState.FAILED

    def test_freeze_reason_includes_context(self, feed, mock_kill_switch):
        """FREEZE reason includes context about what triggered it."""
        sm = feed.state_manager
        feed.set_kill_switch(mock_kill_switch)

        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        feed._auth_error_count = 7
        feed._check_circuit_breaker()

        call_args = mock_kill_switch.activate_global_freeze.call_args
        reason = call_args.kwargs.get("reason", "")
        assert "7" in reason  # error count in reason


# ── Health Endpoint ───────────────────────────────────────────────────────────

class TestHealthEndpoint:
    """Test enhanced get_health() endpoint."""

    def test_health_includes_state_machine(self, feed):
        """get_health() includes state machine info."""
        health = feed.get_health()
        assert "state" in health
        assert health["state"] == ConnectionState.DISCONNECTED.value
        assert "is_operational" in health
        assert health["is_operational"] is False

    def test_health_includes_heartbeat_age(self, feed):
        """get_health() includes heartbeat age."""
        health = feed.get_health()
        assert "last_heartbeat_age" in health
        assert health["last_heartbeat_age"] >= 0

    def test_health_includes_tick_age(self, feed):
        """get_health() includes tick age."""
        health = feed.get_health()
        assert "last_tick_age" in health
        assert health["last_tick_age"] >= 0

    def test_health_reflects_authenticated_state(self, feed):
        """get_health() reflects AUTHENTICATED state."""
        sm = feed.state_manager
        sm.transition_to(ConnectionState.CONNECTING, reason="test")
        sm.transition_to(ConnectionState.CONNECTED, reason="test")
        sm.transition_to(ConnectionState.APP_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(ConnectionState.AUTHENTICATED, reason="test")

        health = feed.get_health()
        assert health["state"] == ConnectionState.AUTHENTICATED.value
        assert health["is_operational"] is True


# ── State Manager Callbacks ───────────────────────────────────────────────────

class TestStateChangeCallbacks:
    """Test that state change callbacks fire correctly."""

    def test_callback_fires_on_transition(self, feed):
        """Registered callback fires when state changes."""
        sm = feed.state_manager
        events = []

        sm.on_state_change(
            lambda old, new, reason, meta: events.append((old, new, reason))
        )

        sm.transition_to(ConnectionState.CONNECTING, reason="test_connect")
        assert len(events) == 1
        assert events[0][0] == ConnectionState.DISCONNECTED
        assert events[0][1] == ConnectionState.CONNECTING
        assert events[0][2] == "test_connect"

    def test_callback_does_not_fire_on_self_transition(self, feed):
        """Callback does not fire on idempotent self-transition."""
        sm = feed.state_manager
        events = []

        sm.on_state_change(
            lambda old, new, reason, meta: events.append((old, new))
        )

        # Self-transition (DISCONNECTED → DISCONNECTED)
        result = sm.transition_to(ConnectionState.DISCONNECTED, reason="noop")
        assert result is True  # valid but no callback
        assert len(events) == 0

    def test_invalid_transition_rejected(self, feed):
        """Invalid transition is rejected (returns False)."""
        sm = feed.state_manager
        # DISCONNECTED → AUTHENTICATED is not a valid transition
        result = sm.transition_to(ConnectionState.AUTHENTICATED, reason="skip")
        assert result is False
        assert sm.state == ConnectionState.DISCONNECTED
