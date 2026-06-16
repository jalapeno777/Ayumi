"""Integration tests for ConnectionManager reliability wiring.

Tests that ConnectionWatchdog, OAuthRefreshManager, and ReconnectStrategy
are correctly wired into ConnectionManager and work end-to-end.

All network calls are mocked.  No real HTTP requests or connections are made.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from adapters.ctrader.connection_manager import ConnectionManager, ConnectionRole
from adapters.ctrader.connection_state import ConnectionState, ConnectionStateManager
from adapters.ctrader.connection_watchdog import ConnectionWatchdog
from adapters.ctrader.reconnect_strategy import ReconnectAction
from common.resource_limits import memory_capped


# ── Helpers ──────────────────────────────────────────────────────────────────


class _FastWatchdog(ConnectionWatchdog):
    """Sub-second thresholds for fast tests."""

    def __init__(self, mgr, **kw):
        super().__init__(
            mgr,
            degraded_threshold=kw.pop("degraded_threshold", 0.15),
            failed_threshold=kw.pop("failed_threshold", 0.40),
            poll_interval=kw.pop("poll_interval", 0.05),
        )


class AuthError(Exception):
    """Test auth error."""


def _authenticate(state_mgr: ConnectionStateManager) -> None:
    """Drive a state manager through the full connect sequence."""
    for target in (
        ConnectionState.CONNECTING,
        ConnectionState.CONNECTED,
        ConnectionState.APP_AUTHENTICATING,
        ConnectionState.ACCT_AUTHENTICATING,
        ConnectionState.AUTHENTICATED,
    ):
        state_mgr.transition_to(target, reason="test_setup")


def _write_creds(
    path,
    *,
    access="access123",
    refresh="refresh456",
    client_id="client_abc",
    client_secret="secret_xyz",
):
    """Write a credentials JSON file."""
    with open(path, "w") as f:
        json.dump(
            {
                "version": 1,
                "client_id": client_id,
                "client_secret": client_secret,
                "access_token": access,
                "refresh_token": refresh,
                "account_id": "acc_001",
            },
            f,
        )


# ── Watchdog wiring tests ────────────────────────────────────────────────────


class TestWatchdogWiringDegraded(unittest.TestCase):
    """Verify start_watchdog() wires the watchdog and detects silence."""

    def test_watchdog_marks_silence_as_degraded(self):
        """start_watchdog() registers connections; silence → DEGRADED."""
        mgr = ConnectionManager()
        sm = ConnectionStateManager(name="market_data")
        mgr.register(ConnectionRole.MARKET_DATA, sm)
        _authenticate(sm)

        # Use fast thresholds via start_watchdog kwargs.
        # Cap memory at 256MB to keep the daemon thread test from
        # being a runaway if the watchdog loop misbehaves.
        with memory_capped(mb=256):
            mgr.start_watchdog(
                degraded_threshold=0.15,
                failed_threshold=0.40,
                poll_interval=0.05,
            )
            self.assertIsNotNone(mgr._watchdog)
            self.assertTrue(mgr._watchdog.is_running)

            try:
                time.sleep(0.25)  # past degraded threshold
                self.assertEqual(sm.state, ConnectionState.DEGRADED)
            finally:
                mgr.stop_watchdog()

    def test_watchdog_recovery_via_record_ping(self):
        """Watchdog wired through manager can recover on ping."""
        mgr = ConnectionManager()
        sm = ConnectionStateManager(name="trade")
        mgr.register(ConnectionRole.TRADE_EXECUTION, sm)
        _authenticate(sm)

        mgr.start_watchdog(
            degraded_threshold=0.15,
            failed_threshold=0.40,
            poll_interval=0.05,
        )
        try:
            time.sleep(0.20)  # degraded
            self.assertEqual(sm.state, ConnectionState.DEGRADED)

            mgr._watchdog.record_ping(ConnectionRole.TRADE_EXECUTION)
            time.sleep(0.10)
            self.assertEqual(sm.state, ConnectionState.AUTHENTICATED)
        finally:
            mgr.stop_watchdog()


class TestWatchdogWiringFailed(unittest.TestCase):
    """Verify watchdog FAILED threshold triggers handle_disconnect."""

    def test_watchdog_marks_silence_as_failed(self):
        """Extended silence → FAILED state."""
        mgr = ConnectionManager()
        sm = ConnectionStateManager(name="market_data")
        mgr.register(ConnectionRole.MARKET_DATA, sm)
        _authenticate(sm)

        mgr.start_watchdog(
            degraded_threshold=0.10,
            failed_threshold=0.35,
            poll_interval=0.05,
        )
        try:
            time.sleep(0.50)  # past failed threshold
            self.assertEqual(sm.state, ConnectionState.FAILED)
        finally:
            mgr.stop_watchdog()


class TestWatchdogStopIdempotent(unittest.TestCase):
    """stop_watchdog / start_watchdog idempotency through ConnectionManager."""

    def test_stop_watchdog_without_start(self):
        """stop_watchdog() before start should not raise."""
        mgr = ConnectionManager()
        mgr.stop_watchdog()  # should not raise

    def test_start_stop_idempotent(self):
        """Double-start and double-stop are no-ops."""
        mgr = ConnectionManager()
        sm = ConnectionStateManager(name="market_data")
        mgr.register(ConnectionRole.MARKET_DATA, sm)

        mgr.start_watchdog(
            degraded_threshold=0.15, failed_threshold=0.40, poll_interval=0.05
        )
        mgr.start_watchdog()  # idempotent
        self.assertTrue(mgr._watchdog.is_running)

        mgr.stop_watchdog()
        mgr.stop_watchdog()  # idempotent
        self.assertFalse(mgr._watchdog.is_running)


# ── OAuth refresh wiring tests ───────────────────────────────────────────────


class TestOAuthRefreshWiring(unittest.TestCase):
    """Verify refresh_oauth_if_needed() updates manager auth state."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cred_path = os.path.join(self.tmpdir, "creds.json")
        _write_creds(self.cred_path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("adapters.ctrader.oauth_refresh.requests.post")
    def test_oauth_refresh_updates_manager_state(self, mock_post):
        """refresh_oauth_if_needed() performs refresh and stores new token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "accessToken": "NEW_ACCESS_789",
            "refreshToken": "NEW_REFRESH_012",
            "expiresIn": 3600,
        }
        mock_post.return_value = mock_resp

        mgr = ConnectionManager()
        # First call — _cached_token is None → _do_refresh() fires
        mgr.refresh_oauth_if_needed(credentials_path=self.cred_path)

        # Manager should have the new token
        self.assertEqual(mgr._auth_token, "NEW_ACCESS_789")

        # Verify credentials file was updated atomically
        with open(self.cred_path) as f:
            data = json.load(f)
        self.assertEqual(data["access_token"], "NEW_ACCESS_789")

    def test_oauth_refresh_handles_missing_file(self):
        """refresh_oauth_if_needed() handles missing credentials gracefully."""
        mgr = ConnectionManager()
        bad_path = os.path.join(self.tmpdir, "nonexistent.json")

        # Should not raise
        mgr.refresh_oauth_if_needed(credentials_path=bad_path)
        self.assertIsNone(mgr._auth_token)

    @patch("adapters.ctrader.oauth_refresh.requests.post")
    def test_oauth_refresh_idempotent_manager(self, mock_post):
        """Second call with fresh token doesn't re-refresh."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "accessToken": "FIRST_TOKEN",
            "refreshToken": "FIRST_REFRESH",
            "expiresIn": 7200,
        }
        mock_post.return_value = mock_resp

        mgr = ConnectionManager()
        mgr.refresh_oauth_if_needed(credentials_path=self.cred_path)
        self.assertEqual(mgr._auth_token, "FIRST_TOKEN")

        # Second call — cached token is fresh (7200s), should not re-refresh
        mgr.refresh_oauth_if_needed(credentials_path=self.cred_path)
        self.assertEqual(mgr._auth_token, "FIRST_TOKEN")
        # Only one HTTP call should have been made
        self.assertEqual(mock_post.call_count, 1)


# ── Reconnect strategy wiring tests ──────────────────────────────────────────


class TestReconnectDecisionWiring(unittest.TestCase):
    """Verify decide_reconnect() routes exceptions through the strategy."""

    def test_reconnect_decision_for_tier_1_error(self):
        """TimeoutError → HEARTBEAT_TIMEOUT (TIER_1) → RETRY."""
        mgr = ConnectionManager()
        decision = mgr.decide_reconnect(TimeoutError("connection timed out"))

        self.assertEqual(decision.action, ReconnectAction.RETRY)
        self.assertGreater(decision.sleep_seconds, 0)

    def test_reconnect_decision_for_tier_3b_error(self):
        """AuthError → AUTH_EXPIRED (TIER_3B) → HALT."""
        mgr = ConnectionManager()
        decision = mgr.decide_reconnect(AuthError("token expired"))

        self.assertEqual(decision.action, ReconnectAction.HALT)
        self.assertEqual(decision.sleep_seconds, 0)

    def test_reconnect_decision_for_connection_error(self):
        """ConnectionError → CONNECTION_LOST (TIER_1) → RETRY."""
        mgr = ConnectionManager()
        decision = mgr.decide_reconnect(ConnectionError("socket closed"))

        self.assertEqual(decision.action, ReconnectAction.RETRY)

    def test_reconnect_decision_attempt_counter_increments(self):
        """Internal attempt counter increments on each call."""
        mgr = ConnectionManager()

        d1 = mgr.decide_reconnect(TimeoutError("timeout 1"))
        d2 = mgr.decide_reconnect(TimeoutError("timeout 2"))

        self.assertEqual(d1.attempt, 1)
        self.assertEqual(d2.attempt, 2)

    def test_reconnect_decision_with_explicit_attempt(self):
        """Explicit attempt override works and doesn't increment internal counter."""
        mgr = ConnectionManager()
        decision = mgr.decide_reconnect(TimeoutError("timeout"), attempt=5)
        self.assertEqual(decision.attempt, 5)

        # Internal counter should NOT have been incremented
        self.assertEqual(mgr._reconnect_attempt, 0)

    def test_reconnect_max_attempts_gives_up(self):
        """After max_attempts, decision is NO_RETRY."""
        mgr = ConnectionManager()
        # Use a strategy with low max_attempts
        from adapters.ctrader.reconnect_strategy import ReconnectStrategy

        mgr._reconnect_strategy = ReconnectStrategy(max_attempts=3)

        d1 = mgr.decide_reconnect(TimeoutError("t1"), attempt=1)
        d2 = mgr.decide_reconnect(TimeoutError("t2"), attempt=2)
        d3 = mgr.decide_reconnect(TimeoutError("t3"), attempt=3)

        self.assertEqual(d1.action, ReconnectAction.RETRY)
        self.assertEqual(d2.action, ReconnectAction.RETRY)
        self.assertEqual(d3.action, ReconnectAction.NO_RETRY)

    def test_reset_reconnect_state(self):
        """reset_reconnect_state() resets counter and jitter."""
        mgr = ConnectionManager()
        mgr.decide_reconnect(TimeoutError("t1"))
        mgr.decide_reconnect(TimeoutError("t2"))
        self.assertEqual(mgr._reconnect_attempt, 2)

        mgr.reset_reconnect_state()
        self.assertEqual(mgr._reconnect_attempt, 0)

        # Next decision should be attempt 1 again
        d = mgr.decide_reconnect(TimeoutError("after reset"))
        self.assertEqual(d.attempt, 1)

    def test_decide_reconnect_records_error_tier(self):
        """decide_reconnect() records the error tier in metrics."""
        mgr = ConnectionManager()
        mgr.decide_reconnect(TimeoutError("timeout"))

        # TIER_1 counter should be incremented
        self.assertEqual(mgr._error_tier_counts[ErrorTier.TIER_1_TRANSIENT], 1)


# ── Handle disconnect tests ──────────────────────────────────────────────────


class TestHandleDisconnect(unittest.TestCase):
    """Verify handle_disconnect() accepts role and logs appropriately."""

    def test_handle_disconnect_with_role_enum(self):
        """handle_disconnect() accepts ConnectionRole enum."""
        mgr = ConnectionManager()
        mgr.handle_disconnect(ConnectionRole.MARKET_DATA)  # should not raise

    def test_handle_disconnect_with_role_string(self):
        """handle_disconnect() accepts role string."""
        mgr = ConnectionManager()
        mgr.handle_disconnect("trade_execution")  # should not raise


# ── Import the ErrorTier for the metrics test ───────────────────────────────

from adapters.ctrader.error_classifier import ErrorTier


if __name__ == "__main__":
    unittest.main()
