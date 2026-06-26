"""Tests for ConnectionWatchdog — heartbeat silence detection.

Uses fast thresholds (sub-second) so no test sleeps for real-world durations.
"""

from __future__ import annotations

import time
import unittest

from adapters.ctrader.connection_manager import ConnectionManager, ConnectionRole
from adapters.ctrader.connection_state import ConnectionState, ConnectionStateManager
from adapters.ctrader.connection_watchdog import ConnectionWatchdog


class _FastWatchdog(ConnectionWatchdog):
    """Subclass with sub-second thresholds for fast tests."""

    def __init__(self, mgr, **kw):
        super().__init__(
            mgr,
            degraded_threshold=kw.pop("degraded_threshold", 0.15),
            failed_threshold=kw.pop("failed_threshold", 0.40),
            poll_interval=kw.pop("poll_interval", 0.05),
        )


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


class TestWatchdogSilenceToDegraded(unittest.TestCase):

    def test_silence_triggers_degraded(self):
        mgr = ConnectionManager()
        sm = ConnectionStateManager(name="market_data")
        mgr.register(ConnectionRole.MARKET_DATA, sm)
        _authenticate(sm)

        wd = _FastWatchdog(mgr)
        wd.register(ConnectionRole.MARKET_DATA, sm)
        wd.start()

        try:
            time.sleep(0.25)  # past degraded threshold
            self.assertEqual(sm.state, ConnectionState.DEGRADED)
        finally:
            wd.stop()


class TestWatchdogSilenceToFailed(unittest.TestCase):

    def test_silence_triggers_failed(self):
        mgr = ConnectionManager()
        sm = ConnectionStateManager(name="trade")
        mgr.register(ConnectionRole.TRADE_EXECUTION, sm)
        _authenticate(sm)

        wd = _FastWatchdog(mgr)
        wd.register(ConnectionRole.TRADE_EXECUTION, sm)
        wd.start()

        try:
            time.sleep(0.50)  # past failed threshold
            self.assertEqual(sm.state, ConnectionState.FAILED)
        finally:
            wd.stop()


class TestWatchdogRecovery(unittest.TestCase):

    def test_ping_resets_degraded(self):
        mgr = ConnectionManager()
        sm = ConnectionStateManager(name="market_data")
        mgr.register(ConnectionRole.MARKET_DATA, sm)
        _authenticate(sm)

        wd = _FastWatchdog(mgr)
        wd.register(ConnectionRole.MARKET_DATA, sm)
        wd.start()

        try:
            time.sleep(0.20)  # past degraded
            self.assertEqual(sm.state, ConnectionState.DEGRADED)

            # Record a ping → should recover
            wd.record_ping(ConnectionRole.MARKET_DATA)
            time.sleep(0.10)
            self.assertEqual(sm.state, ConnectionState.AUTHENTICATED)
        finally:
            wd.stop()


class TestWatchdogStopIdempotent(unittest.TestCase):

    def test_stop_is_idempotent(self):
        mgr = ConnectionManager()
        sm = ConnectionStateManager(name="market_data")
        mgr.register(ConnectionRole.MARKET_DATA, sm)

        wd = _FastWatchdog(mgr)
        wd.register(ConnectionRole.MARKET_DATA, sm)

        # Stop without starting
        wd.stop()
        self.assertFalse(wd.is_running)

        # Start then stop twice
        wd.start()
        self.assertTrue(wd.is_running)
        wd.stop()
        self.assertFalse(wd.is_running)
        wd.stop()  # idempotent
        self.assertFalse(wd.is_running)

    def test_start_is_idempotent(self):
        mgr = ConnectionManager()
        sm = ConnectionStateManager(name="market_data")
        mgr.register(ConnectionRole.MARKET_DATA, sm)

        wd = _FastWatchdog(mgr)
        wd.register(ConnectionRole.MARKET_DATA, sm)

        wd.start()
        wd.start()  # should not spawn a second thread
        self.assertTrue(wd.is_running)
        wd.stop()


class TestWatchdogGetSilence(unittest.TestCase):

    def test_get_silence_returns_none_for_untracked(self):
        mgr = ConnectionManager()
        wd = _FastWatchdog(mgr)
        self.assertIsNone(wd.get_silence(ConnectionRole.MARKET_DATA))


if __name__ == "__main__":
    unittest.main()
