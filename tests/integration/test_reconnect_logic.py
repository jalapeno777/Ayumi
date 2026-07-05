"""BQ-1335: Tests for stuck-state reconnect logic in ForwardTestEngine.

Validates that a stuck RECONNECTING/FAILED spot feed is detected and a
forced reconnect happens within ~60s, instead of waiting up to 15 minutes
under the previous stale_tick_threshold_sec=900 default.

Test strategy: direct engine manipulation with a mock market feed.
No live cTrader connection required. Time is patched via freezegun-style
monkeypatching of time.monotonic / datetime.now.
"""

from __future__ import annotations

import sys
import threading
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from adapters.ctrader.connection_state import ConnectionState, ConnectionStateManager
from adapters.ctrader.forward_test_engine import ForwardTestConfig, ForwardTestEngine


@pytest.fixture(autouse=True)
def _ctrader_stubs(monkeypatch):
    """Install ctrader_open_api stubs per-test (auto-restored by monkeypatch)."""
    pkg = types.ModuleType("ctrader_open_api")
    pkg.__path__ = []
    pkg.Client = MagicMock
    pkg.TcpProtocol = MagicMock
    monkeypatch.setitem(sys.modules, "ctrader_open_api", pkg)

    client_mod = types.ModuleType("ctrader_open_api.client")
    client_mod.Client = MagicMock
    monkeypatch.setitem(sys.modules, "ctrader_open_api.client", client_mod)

    msgs_pkg = types.ModuleType("ctrader_open_api.messages")
    msgs_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "ctrader_open_api.messages", msgs_pkg)

    pb_mod = types.ModuleType("ctrader_open_api.protobuf")
    class _Pb:
        @staticmethod
        def extract(msg):
            return msg
    pb_mod.Protobuf = _Pb
    monkeypatch.setitem(sys.modules, "ctrader_open_api.protobuf", pb_mod)

    msgs_mod = types.ModuleType("ctrader_open_api.messages.OpenApiMessages_pb2")
    for _name in [
        "ProtoOASymbolsListReq", "ProtoOASubscribeSpotsReq",
        "ProtoOAUnsubscribeSpotsReq", "ProtoOASymbolByIdReq",
        "ProtoOANewOrderReq", "ProtoOAClosePositionReq",
        "ProtoOAAmendOrderReq", "ProtoOACancelOrderReq",
        "ProtoOAReconcileReq", "ProtoOAAmendPositionSLTPReq",
        "ProtoOAExecutionEvent", "ProtoOAOrderErrorEvent",
        "ProtoOAAccountAuthReq", "ProtoOAApplicationAuthReq",
        "ProtoOAGetTrendbarsReq",
    ]:
        setattr(msgs_mod, _name, type(_name, (), {"__init__": lambda self, **kw: None}))
    monkeypatch.setitem(sys.modules, "ctrader_open_api.messages.OpenApiMessages_pb2", msgs_mod)

    model_mod = types.ModuleType("ctrader_open_api.messages.OpenApiModelMessages_pb2")
    class _OT: MARKET = 0; LIMIT = 1; STOP = 2
    class _TS: BUY = 0; SELL = 1
    class _TIF: GOOD_TILL_CANCEL = 0
    class _ET: ORDER_CANCELLED = 0; ORDER_REJECTED = 1
    model_mod.ProtoOAOrderType = _OT
    model_mod.ProtoOATradeSide = _TS
    model_mod.ProtoOATimeInForce = _TIF
    model_mod.ProtoOAExecutionType = _ET
    monkeypatch.setitem(sys.modules, "ctrader_open_api.messages.OpenApiModelMessages_pb2", model_mod)


def _drive_to_state(state_mgr: ConnectionStateManager, target: ConnectionState) -> None:
    """Drive a fresh ConnectionStateManager to a target state via valid transitions."""
    if target == ConnectionState.DISCONNECTED:
        return  # already there
    for step in (
        ConnectionState.CONNECTING,
        ConnectionState.CONNECTED,
        ConnectionState.APP_AUTHENTICATING,
        ConnectionState.ACCT_AUTHENTICATING,
        ConnectionState.AUTHENTICATED,
    ):
        state_mgr.transition_to(step, reason="test_setup")
        if step == target:
            return
    if target == ConnectionState.RECONNECTING:
        state_mgr.transition_to(ConnectionState.RECONNECTING, reason="test")
    elif target == ConnectionState.FAILED:
        state_mgr.transition_to(ConnectionState.FAILED, reason="test")
    elif target == ConnectionState.DEGRADED:
        state_mgr.transition_to(ConnectionState.DEGRADED, reason="test")
    elif target == ConnectionState.AUTHENTICATED:
        return  # already there




def _make_engine_with_mock_feed() -> ForwardTestEngine:
    """Build an engine with a mock market feed exposing a state_manager.

    The engine isn't fully started — these tests poke at private state to
    drive _check_connection_health() and _attempt_reconnect() directly.
    """
    config = ForwardTestConfig(
        symbol="GBPUSD",
        symbols=["GBPUSD"],
        live_mode=False,
        use_openapi_feed=False,
        health_monitor_interval_sec=5.0,
        # BQ-1335: 60s is the new default — keep it explicit so a regression
        # to 900s would surface here.
        stale_tick_threshold_sec=60.0,
        reconnect_delay_sec=1.0,
        max_reconnect_delay_sec=10.0,
        max_reconnect_attempts=5,
    )
    engine = ForwardTestEngine(config=config, strategies=[])

    # Wire a mock market feed with a real ConnectionStateManager.
    state_mgr = ConnectionStateManager(name="market_feed_mock")
    mock_feed = MagicMock()
    mock_feed.is_running = True
    mock_feed.state_manager = state_mgr
    mock_feed.start = MagicMock(return_value=True)
    mock_feed.stop = MagicMock()
    mock_feed.on_tick = MagicMock()
    engine._market_feed = mock_feed
    engine._state_mgr = state_mgr  # convenience handle for tests
    engine._running = True

    # Pre-arm health so _check_connection_health doesn't bail immediately.
    engine._health.last_tick_at = datetime.now(timezone.utc)
    engine._last_reconnect_attempt_at = 0.0
    engine._reconnect_delay = config.reconnect_delay_sec
    return engine


class TestReconnectLogic(unittest.TestCase):
    """Validate BQ-1335 reconnect-state detection."""

    # ------------------------------------------------------------------
    # Test 1: stale ticks trigger reconnect within 60s
    # ------------------------------------------------------------------
    def test_stale_ticks_triggers_reconnect_within_60s(self):
        """When feed stops sending ticks, reconnect fires within 60s."""
        engine = _make_engine_with_mock_feed()
        # Drive the feed to AUTHENTICATED so it's "operational".
        _drive_to_state(engine._state_mgr, ConnectionState.AUTHENTICATED)

        # Set last_tick_at to 90s ago — past both 60s stale threshold and 5s backoff.
        engine._health.last_tick_at = datetime.now(timezone.utc) - timedelta(seconds=90)

        with patch("adapters.ctrader.forward_test_engine._is_forex_market_closed",
                   return_value=False), \
             patch.object(engine, "_attempt_reconnect") as mock_reconnect:
            engine._check_connection_health()
            self.assertTrue(
                mock_reconnect.called,
                "_attempt_reconnect should fire when stale ticks exceed 60s threshold",
            )

    # ------------------------------------------------------------------
    # Test 2: RECONNECTING state triggers forced reconnect after 60s
    # ------------------------------------------------------------------
    def test_reconnecting_state_triggers_force_reconnect(self):
        """State=RECONNECTING for >60s forces _attempt_reconnect even with fresh ticks."""
        engine = _make_engine_with_mock_feed()
        # Simulate connection in stuck RECONNECTING state.
        _drive_to_state(engine._state_mgr, ConnectionState.RECONNECTING)

        # Pretend we've been stuck for 90s.
        engine._reconnect_stuck_at = time.monotonic() - 90.0
        # Fresh ticks (would normally make connection look healthy).
        engine._health.last_tick_at = datetime.now(timezone.utc)

        with patch("adapters.ctrader.forward_test_engine._is_forex_market_closed",
                   return_value=False), \
             patch.object(engine, "_attempt_reconnect") as mock_reconnect:
            engine._check_connection_health()
            self.assertTrue(
                mock_reconnect.called,
                "Stuck RECONNECTING state for >60s should force _attempt_reconnect",
            )
            # Backoff gate should have been bypassed.
            self.assertEqual(
                engine._last_reconnect_attempt_at, 0.0,
                "Backoff gate must be bypassed for forced stuck-state reconnect",
            )

    # ------------------------------------------------------------------
    # Test 3: Successful reconnect resets _reconnect_stuck_at and recovers state
    # ------------------------------------------------------------------
    def test_reconnect_recovers_to_authenticated(self):
        """After _attempt_reconnect, feed restarts and state recovers."""
        engine = _make_engine_with_mock_feed()
        _drive_to_state(engine._state_mgr, ConnectionState.RECONNECTING)
        engine._reconnect_stuck_at = time.monotonic() - 90.0

        # Force reconnect — this calls _start_market_feed (mocked True).
        # Use the real method so we can assert side effects.
        engine._attempt_reconnect()

        # _start_market_feed (mocked True) increments reconnection_successes
        # and resets _reconnect_stuck_at.
        self.assertIsNone(
            engine._reconnect_stuck_at,
            "_reconnect_stuck_at must reset to None on successful reconnect",
        )
        self.assertEqual(engine._health.reconnection_successes, 1)
        self.assertEqual(engine._health.reconnection_attempts, 0)

    # ------------------------------------------------------------------
    # Test 4: Market-closed hours block reconnect
    # ------------------------------------------------------------------
    def test_market_closed_skips_reconnect(self):
        """is_forex_market_closed()=True should block stuck-state reconnect."""
        engine = _make_engine_with_mock_feed()
        _drive_to_state(engine._state_mgr, ConnectionState.RECONNECTING)
        engine._reconnect_stuck_at = time.monotonic() - 90.0

        with patch("adapters.ctrader.forward_test_engine._is_forex_market_closed",
                   return_value=True),              patch.object(engine, "_attempt_reconnect") as mock_reconnect:
            engine._check_connection_health()
            self.assertFalse(
                mock_reconnect.called,
                "Reconnect must NOT fire during forex market close",
            )

    # ------------------------------------------------------------------
    # Test 5: Backoff gate respected unless forced by stuck state
    # ------------------------------------------------------------------
    def test_backoff_gate_respected(self):
        """Normal flow respects backoff gate; stuck-state path bypasses it."""
        engine = _make_engine_with_mock_feed()
        # Authenticated, fresh ticks, but backoff gate active.
        _drive_to_state(engine._state_mgr, ConnectionState.AUTHENTICATED)
        engine._health.last_tick_at = datetime.now(timezone.utc)
        # Stale ticks NOT triggered — connection is healthy.
        # Backoff gate: last attempt was 0s ago (so gate is open).
        engine._last_reconnect_attempt_at = time.monotonic()

        with patch.object(engine, "_attempt_reconnect") as mock_reconnect:
            # Force a reconnect attempt while backoff is active.
            # Healthy connection → should return early without calling reconnect.
            engine._check_connection_health()
            self.assertFalse(
                mock_reconnect.called,
                "Healthy state should not call _attempt_reconnect",
            )

        # Now simulate stuck FAILED state with backoff gate set high.
        _drive_to_state(engine._state_mgr, ConnectionState.FAILED)
        engine._reconnect_stuck_at = time.monotonic() - 90.0
        # Last attempt 30s ago — well within default reconnect_delay.
        engine._last_reconnect_attempt_at = time.monotonic() - 30.0

        with patch("adapters.ctrader.forward_test_engine._is_forex_market_closed",
                   return_value=False), \
             patch.object(engine, "_attempt_reconnect") as mock_reconnect:
            engine._check_connection_health()
            self.assertTrue(
                mock_reconnect.called,
                "Stuck-state path must bypass the backoff gate",
            )


if __name__ == "__main__":
    unittest.main()
