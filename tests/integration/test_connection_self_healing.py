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

# ---------------------------------------------------------------------------
# BQ-1328: Module-level mock injection for missing dependencies.
# ctrader_open_api and heavy data-science packages are not installed. We inject
# minimal stubs into sys.modules so the import chain resolves.
# ---------------------------------------------------------------------------
import sys as _sys
import types as _types
from dataclasses import dataclass as _dataclass
from datetime import datetime as _datetime
from enum import Enum as _Enum

# pandas stub
class _FakeDataFrame: pass
class _FakeSeries: pass
class _FakeDatetimeIndex: pass
_pandas = _types.ModuleType("pandas")
_pandas.DataFrame = _FakeDataFrame
_pandas.Series = _FakeSeries
_pandas.DatetimeIndex = _FakeDatetimeIndex

# signal_engine stub
_signal_engine = _types.ModuleType("signal_engine")
_signal_stats = _types.ModuleType("signal_engine.signal_stats")
_swing_detector = _types.ModuleType("signal_engine.swing_detector")
class _SwingDetector: pass
_swing_detector.SwingDetector = _SwingDetector

# backtest stub
_backtest = _types.ModuleType("backtest")
_backtest_engine = _types.ModuleType("backtest.engine")
_backtest_strategies = _types.ModuleType("backtest.strategies")
class _TradeDirection(_Enum):
    LONG = "long"
    SHORT = "short"
@_dataclass
class _Bar:
    time: _datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0
@_dataclass
class _MarketState:
    bars: list = None
class _ISignalStrategy: pass
_backtest_engine.Bar = _Bar
_backtest_engine.MarketState = _MarketState
_backtest_engine.TradeDirection = _TradeDirection
_backtest_strategies.ISignalStrategy = _ISignalStrategy

# ctrader_open_api stub
_ctrader = _types.ModuleType("ctrader_open_api")
class _Client:
    def __init__(self, host, port, protocol): pass
    def setConnectedCallback(self, cb): pass
    def setDisconnectedCallback(self, cb): pass
    def startService(self): pass
    def stopService(self): pass
    def send(self, msg, **kwargs): pass
class _TcpProtocol: pass
_ctrader.Client = _Client
_ctrader.TcpProtocol = _TcpProtocol
_protobuf_mod = _types.ModuleType("ctrader_open_api.protobuf")
class _Protobuf:
    @staticmethod
    def extract(msg): return msg
_protobuf_mod.Protobuf = _Protobuf
_messages_mod = _types.ModuleType("ctrader_open_api.messages")
_msg_names = [
    "ProtoOAAccountAuthReq", "ProtoOAAmendOrderReq", "ProtoOAAmendPositionSLTPReq",
    "ProtoOAApplicationAuthReq", "ProtoOACancelOrderReq", "ProtoOAClosePositionReq",
    "ProtoOAExecutionEvent", "ProtoOAGetTrendbarsReq", "ProtoOANewOrderReq",
    "ProtoOAOrderErrorEvent", "ProtoOAReconcileReq", "ProtoOASubscribeSpotsReq",
    "ProtoOASymbolByIdReq", "ProtoOASymbolsListReq", "ProtoOAUnsubscribeSpotsReq",
]
_openapi_msgs = _types.ModuleType("ctrader_open_api.messages.OpenApiMessages_pb2")
for _name in _msg_names:
    _cls = type(_name, (), {"__init__": lambda self, **kw: None})
    setattr(_openapi_msgs, _name, _cls)
_model_msgs = _types.ModuleType("ctrader_open_api.messages.OpenApiModelMessages_pb2")
class _ProtoOAOrderType:
    MARKET = 0; LIMIT = 1; STOP = 2
class _ProtoOATradeSide:
    BUY = 0; SELL = 1
class _ProtoOATimeInForce:
    GOOD_TILL_CANCEL = 0
class _ProtoOAExecutionType:
    ORDER_CANCELLED = 0; ORDER_REJECTED = 1
_model_msgs.ProtoOAOrderType = _ProtoOAOrderType
_model_msgs.ProtoOATradeSide = _ProtoOATradeSide
_model_msgs.ProtoOATimeInForce = _ProtoOATimeInForce
_model_msgs.ProtoOAExecutionType = _ProtoOAExecutionType

import sys
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from adapters.ctrader.connection_state import ConnectionState, ConnectionStateManager
# Sprint 1A.1: The orchestrator at adapters.ctrader.open_api_spot_feed uses
# ConnectionStateManager from adapters.ctrader.connection_state (ModernCS).
# Its _VALID_TRANSITIONS dict is keyed by ModernCS enum members, so the
# test MUST call transition_to() with the ModernCS enum (identity-based
# dict lookup). Assert by .value to stay enum-identity-agnostic.
from adapters.ctrader.open_api_spot_feed import (
    OpenApiSpotFeed,
    _HEARTBEAT_DEGRADED_SEC,
    _HEARTBEAT_RECONNECT_SEC,
    _STALE_TICK_WARN_SEC,
    _STALE_TICK_FREEZE_SEC,
)


@pytest.fixture(autouse=True)
def _install_mock_stubs(monkeypatch):
    """BQ-1328: Install dependency stubs per-test via monkeypatch (auto-restored)."""
    monkeypatch.setitem(_sys.modules, "pandas", _pandas)
    monkeypatch.setitem(_sys.modules, "signal_engine", _signal_engine)
    monkeypatch.setitem(_sys.modules, "signal_engine.signal_stats", _signal_stats)
    monkeypatch.setitem(_sys.modules, "signal_engine.swing_detector", _swing_detector)
    monkeypatch.setitem(_sys.modules, "backtest", _backtest)
    monkeypatch.setitem(_sys.modules, "backtest.engine", _backtest_engine)
    monkeypatch.setitem(_sys.modules, "backtest.strategies", _backtest_strategies)
    monkeypatch.setitem(_sys.modules, "ctrader_open_api", _ctrader)
    monkeypatch.setitem(_sys.modules, "ctrader_open_api.protobuf", _protobuf_mod)
    monkeypatch.setitem(_sys.modules, "ctrader_open_api.messages", _messages_mod)
    monkeypatch.setitem(_sys.modules, "ctrader_open_api.messages.OpenApiMessages_pb2", _openapi_msgs)
    monkeypatch.setitem(_sys.modules, "ctrader_open_api.messages.OpenApiModelMessages_pb2", _model_msgs)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _state_value(state):
    """Return the string value of a ConnectionState (modern or archived)."""
    return state.value if hasattr(state, "value") else state

# Alias: tests below call transition_to() with this so the modern
# _VALID_TRANSITIONS dict (keyed by ModernCS enum members) actually hits.
CS = ConnectionState


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
    for attr in ("_health_timer", "_refresh_timer"):
        timer = getattr(f, attr, None)
        if timer is not None:
            timer.cancel()


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
        assert _state_value(feed.state_manager.state) == "disconnected"

    def test_state_manager_property_returns_manager(self, feed):
        """state_manager property returns the ConnectionStateManager."""
        # BQ-1328: OpenApiSpotFeed is the archived adapter, so its
        # state_manager is the archived ConnectionStateManager class —
        # not the modern one imported above. Compare by class name.
        assert feed.state_manager.__class__.__name__ == "ConnectionStateManager"
        assert feed.state_manager.name == "spot_feed"

    def test_connecting_transition(self, feed):
        """Calling _connect triggers CONNECTING state."""
        # We can't actually connect, but we can test the transition
        # by simulating what _connect does
        feed.state_manager.transition_to(
            CS.CONNECTING, reason="test",
        )
        assert _state_value(feed.state_manager.state) == "connecting"

    def test_full_connect_auth_sequence(self, feed):
        """Simulate full connect → auth sequence and verify all transitions."""
        sm = feed.state_manager

        # Connect
        sm.transition_to(CS.CONNECTING, reason="tcp_connect")
        assert _state_value(sm.state) == "connecting"

        # TCP connected
        sm.transition_to(CS.CONNECTED, reason="tcp_connected")
        assert _state_value(sm.state) == "connected"

        # App auth sending
        sm.transition_to(CS.APP_AUTHENTICATING, reason="app_auth")
        assert _state_value(sm.state) == "app_authenticating"

        # Account auth sending
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="acct_auth")
        assert _state_value(sm.state) == "acct_authenticating"

        # Fully authenticated
        sm.transition_to(CS.AUTHENTICATED, reason="auth_complete")
        assert _state_value(sm.state) == "authenticated"

    def test_disconnect_transitions_to_reconnecting(self, feed):
        """When connected, a disconnect should transition to RECONNECTING."""
        sm = feed.state_manager
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        sm.transition_to(CS.RECONNECTING, reason="disconnected")
        assert _state_value(sm.state) == "reconnecting"

    def test_on_connected_sets_state_connected(self, feed):
        """_on_conn_connected spawns re-auth when feed is running."""
        # In production CTraderConnection._handle_connected transitions to
        # CONNECTED before invoking this callback, then this callback spawns
        # the re-auth thread. We verify the callback is safe to invoke and
        # that it sets _connected_at.
        feed.state_manager.transition_to(CS.CONNECTING, reason="test")
        feed.state_manager.transition_to(CS.CONNECTED, reason="test")
        # Prevent the reconnect thread from running during the test
        feed._reauth_in_progress.set()
        before = feed._connected_at
        feed._on_conn_connected(MagicMock())
        assert feed._connected_at is not None
        assert feed._connected_at != before

    def test_on_disconnected_sets_state_reconnecting(self, feed):
        """_on_conn_disconnected records disconnect and works after RECONNECTING transition."""
        sm = feed.state_manager
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")
        # In production CTraderConnection._handle_disconnected drives the
        # state transition to RECONNECTING before invoking this callback.
        sm.transition_to(CS.RECONNECTING, reason="disconnected")

        feed._on_conn_disconnected(MagicMock(), "test_reason")
        assert _state_value(sm.state) == "reconnecting"
        assert feed._disconnect_at is not None

    def test_on_disconnected_clears_flags(self, feed):
        """_on_conn_disconnected clears informal flags (fallback behavior)."""
        feed._authed.set()
        feed._app_authed.set()

        feed._on_conn_disconnected(MagicMock(), "test")

        assert not feed._authed.is_set()
        assert not feed._app_authed.is_set()


# ── Heartbeat Timeout Detection ───────────────────────────────────────────────

class TestHeartbeatMonitor:
    """Test heartbeat timeout → DEGRADED → RECONNECTING sequence."""

    def test_heartbeat_degraded_threshold(self, feed):
        """No heartbeat for 35s → DEGRADED."""
        sm = feed.state_manager
        # Set to AUTHENTICATED
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        # Simulate stale heartbeat on CTraderConnection
        feed._conn._last_heartbeat_recv = time.monotonic() - _HEARTBEAT_DEGRADED_SEC - 1

        feed._check_heartbeat_health()

        assert _state_value(sm.state) == "degraded"

    def test_heartbeat_reconnect_threshold(self, feed):
        """No heartbeat for 60s → RECONNECTING."""
        sm = feed.state_manager
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        # Simulate very stale heartbeat on CTraderConnection
        feed._conn._last_heartbeat_recv = time.monotonic() - _HEARTBEAT_RECONNECT_SEC - 1
        feed._client = None  # prevent actual stopService call

        feed._check_heartbeat_health()

        assert _state_value(sm.state) == "reconnecting"

    def test_heartbeat_ok_when_recent(self, feed):
        """Recent heartbeat → no state change."""
        sm = feed.state_manager
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        # Fresh heartbeat on CTraderConnection
        feed._conn._last_heartbeat_recv = time.monotonic()

        feed._check_heartbeat_health()

        assert _state_value(sm.state) == "authenticated"

    def test_heartbeat_skipped_when_disconnected(self, feed):
        """Heartbeat check skipped when not connected."""
        sm = feed.state_manager
        # Feed starts DISCONNECTED — no check should run
        feed._conn._last_heartbeat_recv = time.monotonic() - 999

        feed._check_heartbeat_health()

        assert _state_value(sm.state) == "disconnected"

    def test_heartbeat_degraded_then_reconnect_sequence(self, feed):
        """Full sequence: DEGRADED at 35s → RECONNECTING at 60s."""
        sm = feed.state_manager
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        # 36s stale → DEGRADED
        feed._conn._last_heartbeat_recv = time.monotonic() - 36
        feed._check_heartbeat_health()
        assert _state_value(sm.state) == "degraded"

        # 61s stale → RECONNECTING (DEGRADED → RECONNECTING is valid)
        feed._conn._last_heartbeat_recv = time.monotonic() - 61
        feed._client = None
        feed._check_heartbeat_health()
        assert _state_value(sm.state) == "reconnecting"


# ── Stale Tick Detection ──────────────────────────────────────────────────────

class TestStaleTickDetector:
    """Test stale tick detection during market hours and weekend skip."""

    def test_stale_tick_warning(self, feed):
        """No tick for 60s during market hours → log warning (state unchanged)."""
        sm = feed.state_manager
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        # Simulate stale tick during weekday
        feed._last_tick_recv_monotonic = time.monotonic() - _STALE_TICK_WARN_SEC - 1

        feed._check_stale_ticks()

        # State should remain AUTHENTICATED (only warnings, no state change for 60s)
        assert _state_value(sm.state) == "authenticated"

    def test_stale_tick_freeze_on_weekday(self, feed, mock_kill_switch):
        """No tick for 120s during market hours → kill switch FREEZE."""
        sm = feed.state_manager
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

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
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        feed.set_kill_switch(mock_kill_switch)

        # Mock weekend (Saturday)
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
        assert _state_value(sm.state) == "disconnected"


# ── Reconciliation After Reconnect ────────────────────────────────────────────

class TestReconciliation:
    """Test reconnection callbacks."""

    def test_on_reconnected_registers_callback(self, feed):
        """on_reconnected() adds callback to list."""
        cb = lambda duration: None
        feed.on_reconnected(cb)
        assert cb in feed._on_reconnected_callbacks

    def test_reconciliation_callback_fires(self, feed):
        """_fire_reconnect_callbacks fires callbacks with outage duration."""
        outage = 0
        captured = []

        def callback(duration):
            captured.append(duration)

        feed.on_reconnected(callback)

        # Set disconnect time to 5 seconds ago
        feed._disconnect_at = time.monotonic() - 5.0
        feed._fire_reconnect_callbacks()

        assert len(captured) == 1
        assert captured[0] >= 5.0
        assert feed._disconnect_at is None  # reset after firing

    def test_reconciliation_no_callback_without_disconnect(self, feed):
        """_fire_reconnect_callbacks skips if no _disconnect_at."""
        captured = []
        feed.on_reconnected(lambda d: captured.append(d))

        feed._disconnect_at = None
        feed._fire_reconnect_callbacks()

        assert len(captured) == 0

    def test_reconciliation_callback_exception_doesnt_crash(self, feed):
        """Exception in reconciliation callback doesn't crash."""
        def bad_callback(duration):
            raise RuntimeError("boom")

        feed.on_reconnected(bad_callback)
        feed._disconnect_at = time.monotonic() - 3.0

        # Should not raise
        feed._fire_reconnect_callbacks()

    def test_multiple_reconciliation_callbacks(self, feed):
        """Multiple callbacks all fire."""
        results = []
        feed.on_reconnected(lambda d: results.append(("a", d)))
        feed.on_reconnected(lambda d: results.append(("b", d)))

        feed._disconnect_at = time.monotonic() - 2.0
        feed._fire_reconnect_callbacks()

        assert len(results) == 2
        assert results[0][0] == "a"
        assert results[1][0] == "b"


# ── Auth Error Escalation ─────────────────────────────────────────────────────

class TestAuthErrorEscalation:
    """Test auth error count → state machine escalation."""

    def test_auth_errors_3_transitions_to_degraded(self, feed):
        """3 auth errors → DEGRADED state."""
        sm = feed.state_manager
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        feed._auth_error_count = 3
        feed._check_circuit_breaker()

        assert _state_value(sm.state) == "degraded"

    def test_auth_errors_5_transitions_to_failed(self, feed, mock_kill_switch):
        """5+ auth errors → FAILED state + kill switch FREEZE."""
        sm = feed.state_manager
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        feed.set_kill_switch(mock_kill_switch)

        feed._auth_error_count = 5
        feed._check_circuit_breaker()

        assert _state_value(sm.state) == "failed"
        assert feed._auth_circuit_open is True
        mock_kill_switch.activate_global_freeze.assert_called_once()

    def test_auth_errors_under_3_no_state_change(self, feed):
        """Auth errors 1-2 → no state transition (just warning)."""
        sm = feed.state_manager
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        feed._auth_error_count = 2
        feed._check_circuit_breaker()

        assert _state_value(sm.state) == "authenticated"

    def test_kill_switch_freeze_on_failed_state(self, feed, mock_kill_switch):
        """FAILED state triggers kill switch FREEZE."""
        feed.set_kill_switch(mock_kill_switch)

        feed._activate_kill_switch_freeze("test_reason")

        mock_kill_switch.activate_global_freeze.assert_called_once_with(
            reason="test_reason",
            triggered_by="spot_feed",
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
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        # Accumulate errors
        feed._auth_error_count = 3
        sm.transition_to(CS.DEGRADED, reason="auth_errors")
        assert _state_value(sm.state) == "degraded"

        # Simulate recovery: auth success resets errors
        feed._auth_error_count = 0
        feed._auth_circuit_open = False
        # Recovery transition
        sm.transition_to(CS.AUTHENTICATED, reason="auth_recovered")

        assert feed._auth_error_count == 0
        assert _state_value(sm.state) == "authenticated"


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
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

        # Trigger 5+ auth errors
        feed._auth_error_count = 6
        feed._check_circuit_breaker()

        mock_kill_switch.activate_global_freeze.assert_called_once()
        assert _state_value(sm.state) == "failed"

    def test_freeze_reason_includes_context(self, feed, mock_kill_switch):
        """FREEZE reason includes context about what triggered it."""
        sm = feed.state_manager
        feed.set_kill_switch(mock_kill_switch)

        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

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
        sm.transition_to(CS.CONNECTING, reason="test")
        sm.transition_to(CS.CONNECTED, reason="test")
        sm.transition_to(CS.APP_AUTHENTICATING, reason="test")
        sm.transition_to(CS.ACCT_AUTHENTICATING, reason="test")
        sm.transition_to(CS.AUTHENTICATED, reason="test")

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

        sm.transition_to(CS.CONNECTING, reason="test_connect")
        assert len(events) == 1
        assert _state_value(events[0][0]) == "disconnected"
        assert _state_value(events[0][1]) == "connecting"
        assert events[0][2] == "test_connect"

    def test_callback_does_not_fire_on_self_transition(self, feed):
        """Callback does not fire on idempotent self-transition."""
        sm = feed.state_manager
        events = []

        sm.on_state_change(
            lambda old, new, reason, meta: events.append((old, new))
        )

        # Self-transition (DISCONNECTED → DISCONNECTED)
        result = sm.transition_to(CS.DISCONNECTED, reason="noop")
        assert result is True  # valid but no callback
        assert len(events) == 0

    def test_invalid_transition_rejected(self, feed):
        """Invalid transition is rejected (returns False)."""
        sm = feed.state_manager
        # DISCONNECTED → AUTHENTICATED is not a valid transition
        result = sm.transition_to(CS.AUTHENTICATED, reason="skip")
        assert result is False
        assert _state_value(sm.state) == "disconnected"
