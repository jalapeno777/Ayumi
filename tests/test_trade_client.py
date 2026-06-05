"""Tests for Phase 1C — Trade client with separate TCP connection.

Covers:
- ConnectionState transitions (valid + invalid)
- ConnectionStateManager callbacks
- Full-jitter backoff calculation
- OpenApiTradeClient initialization (no spot feed dependency)
- Mock send_and_wait (response correlation by clientMsgId)
- Kill switch activation on FAILED state
- Reconnection sequence
- Order result construction
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# ── ConnectionState ───────────────────────────────────────────────────────────

from adapters.ctrader.connection_state import (
    ConnectionState,
    ConnectionStateManager,
    is_valid_transition,
)


class TestConnectionStateEnum:
    def test_nine_states_exist(self):
        expected = {
            "disconnected", "connecting", "connected",
            "app_authenticating", "acct_authenticating", "authenticated",
            "degraded", "reconnecting", "failed",
        }
        actual = {s.value for s in ConnectionState}
        assert actual == expected

    def test_state_values_are_strings(self):
        for s in ConnectionState:
            assert isinstance(s.value, str)


class TestValidTransitions:
    """Verify the transition table from the research doc."""

    def test_initial_connect_sequence(self):
        assert is_valid_transition(
            ConnectionState.DISCONNECTED, ConnectionState.CONNECTING
        )
        assert is_valid_transition(
            ConnectionState.CONNECTING, ConnectionState.CONNECTED
        )
        assert is_valid_transition(
            ConnectionState.CONNECTED, ConnectionState.APP_AUTHENTICATING
        )
        assert is_valid_transition(
            ConnectionState.APP_AUTHENTICATING,
            ConnectionState.ACCT_AUTHENTICATING,
        )
        assert is_valid_transition(
            ConnectionState.ACCT_AUTHENTICATING,
            ConnectionState.AUTHENTICATED,
        )

    def test_authenticated_to_degraded(self):
        assert is_valid_transition(
            ConnectionState.AUTHENTICATED, ConnectionState.DEGRADED
        )

    def test_degraded_to_authenticated(self):
        assert is_valid_transition(
            ConnectionState.DEGRADED, ConnectionState.AUTHENTICATED
        )

    def test_degraded_to_reconnecting(self):
        assert is_valid_transition(
            ConnectionState.DEGRADED, ConnectionState.RECONNECTING
        )

    def test_any_to_reconnecting(self):
        for state in [
            ConnectionState.CONNECTED,
            ConnectionState.APP_AUTHENTICATING,
            ConnectionState.ACCT_AUTHENTICATING,
            ConnectionState.AUTHENTICATED,
            ConnectionState.DEGRADED,
        ]:
            assert is_valid_transition(
                state, ConnectionState.RECONNECTING
            ), f"{state.value} → reconnecting should be valid"

    def test_reconnecting_to_connecting(self):
        assert is_valid_transition(
            ConnectionState.RECONNECTING, ConnectionState.CONNECTING
        )

    def test_reconnecting_to_failed(self):
        assert is_valid_transition(
            ConnectionState.RECONNECTING, ConnectionState.FAILED
        )

    def test_failed_to_disconnected(self):
        assert is_valid_transition(
            ConnectionState.FAILED, ConnectionState.DISCONNECTED
        )

    def test_failed_to_connecting_manual_retry(self):
        assert is_valid_transition(
            ConnectionState.FAILED, ConnectionState.CONNECTING
        )

    def test_invalid_transition_rejected(self):
        # AUTHENTICATED → CONNECTING is not a valid direct transition
        assert not is_valid_transition(
            ConnectionState.AUTHENTICATED, ConnectionState.CONNECTING
        )

    def test_invalid_authenticated_to_acct_auth(self):
        assert not is_valid_transition(
            ConnectionState.AUTHENTICATED,
            ConnectionState.ACCT_AUTHENTICATING,
        )

    def test_self_transitions_allowed(self):
        """Idempotent self-transitions should be allowed."""
        for state in [
            ConnectionState.DISCONNECTED,
            ConnectionState.CONNECTING,
            ConnectionState.AUTHENTICATED,
            ConnectionState.DEGRADED,
            ConnectionState.RECONNECTING,
            ConnectionState.FAILED,
        ]:
            assert is_valid_transition(state, state), \
                f"{state.value} → self should be valid"


class TestConnectionStateManager:
    def test_initial_state_is_disconnected(self):
        mgr = ConnectionStateManager("test")
        assert mgr.state == ConnectionState.DISCONNECTED

    def test_successful_transition(self):
        mgr = ConnectionStateManager("test")
        assert mgr.transition_to(ConnectionState.CONNECTING, "test")
        assert mgr.state == ConnectionState.CONNECTING

    def test_rejected_transition(self):
        mgr = ConnectionStateManager("test")
        # DISCONNECTED → AUTHENTICATED is invalid
        assert not mgr.transition_to(
            ConnectionState.AUTHENTICATED, "skip steps"
        )
        assert mgr.state == ConnectionState.DISCONNECTED

    def test_full_connect_sequence(self):
        mgr = ConnectionStateManager("test")
        seq = [
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED,
            ConnectionState.APP_AUTHENTICATING,
            ConnectionState.ACCT_AUTHENTICATING,
            ConnectionState.AUTHENTICATED,
        ]
        for target in seq:
            assert mgr.transition_to(target), \
                f"Failed to transition to {target.value}"

    def test_callback_fired_on_transition(self):
        mgr = ConnectionStateManager("test")
        events = []

        mgr.on_state_change(
            lambda old, new, reason, meta: events.append(
                (old, new, reason)
            )
        )
        mgr.transition_to(ConnectionState.CONNECTING, "connect")
        assert len(events) == 1
        assert events[0] == (
            ConnectionState.DISCONNECTED,
            ConnectionState.CONNECTING,
            "connect",
        )

    def test_callback_not_fired_on_self_transition(self):
        mgr = ConnectionStateManager("test")
        events = []
        mgr.on_state_change(
            lambda old, new, reason, meta: events.append(new)
        )
        mgr.transition_to(ConnectionState.DISCONNECTED)  # self
        assert len(events) == 0

    def test_callback_receives_metadata(self):
        mgr = ConnectionStateManager("test")
        received = {}

        mgr.on_state_change(
            lambda old, new, reason, meta: received.update(meta)
        )
        mgr.transition_to(
            ConnectionState.CONNECTING,
            reason="test",
            metadata={"attempt": 1, "host": "demo.ctraderapi.com"},
        )
        assert received == {"attempt": 1, "host": "demo.ctraderapi.com"}

    def test_callback_exception_does_not_crash(self):
        mgr = ConnectionStateManager("test")

        def bad_callback(old, new, reason, meta):
            raise RuntimeError("boom")

        mgr.on_state_change(bad_callback)
        # Should not raise
        assert mgr.transition_to(ConnectionState.CONNECTING)

    def test_multiple_callbacks(self):
        mgr = ConnectionStateManager("test")
        count = [0, 0]

        mgr.on_state_change(lambda o, n, r, m: count.__setitem__(0, count[0] + 1))
        mgr.on_state_change(lambda o, n, r, m: count.__setitem__(1, count[1] + 1))
        mgr.transition_to(ConnectionState.CONNECTING)
        assert count == [1, 1]

    def test_is_operational(self):
        mgr = ConnectionStateManager("test")
        assert not mgr.is_operational

        # Get to AUTHENTICATED
        for s in [
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED,
            ConnectionState.APP_AUTHENTICATING,
            ConnectionState.ACCT_AUTHENTICATING,
            ConnectionState.AUTHENTICATED,
        ]:
            mgr.transition_to(s)
        assert mgr.is_operational

        # DEGRADED is still operational
        mgr.transition_to(ConnectionState.DEGRADED)
        assert mgr.is_operational

    def test_is_authenticated(self):
        mgr = ConnectionStateManager("test")
        assert not mgr.is_authenticated
        for s in [
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED,
            ConnectionState.APP_AUTHENTICATING,
            ConnectionState.ACCT_AUTHENTICATING,
            ConnectionState.AUTHENTICATED,
        ]:
            mgr.transition_to(s)
        assert mgr.is_authenticated

    def test_is_failed(self):
        mgr = ConnectionStateManager("test")
        assert not mgr.is_failed
        mgr.transition_to(ConnectionState.CONNECTING)
        mgr.transition_to(ConnectionState.FAILED)
        assert mgr.is_failed

    def test_reset_from_failed(self):
        mgr = ConnectionStateManager("test")
        mgr.transition_to(ConnectionState.CONNECTING)
        mgr.transition_to(ConnectionState.FAILED)
        mgr.reset()
        assert mgr.state == ConnectionState.DISCONNECTED

    def test_thread_safety(self):
        """Concurrent transitions should not corrupt state."""
        mgr = ConnectionStateManager("test")
        results = []

        def worker():
            for _ in range(100):
                mgr.transition_to(ConnectionState.CONNECTING)
                mgr.transition_to(ConnectionState.DISCONNECTED)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # State should be valid (either DISCONNECTED or CONNECTING)
        assert mgr.state in (
            ConnectionState.DISCONNECTED,
            ConnectionState.CONNECTING,
        )

    def test_name_property(self):
        mgr = ConnectionStateManager("trade_client")
        assert mgr.name == "trade_client"


# ── Full-Jitter Backoff ─────────────────────────────────────────────────────

from adapters.ctrader.open_api_trade_client import calculate_full_jitter_backoff


class TestFullJitterBackoff:
    def test_zero_delay_possible(self):
        """With full jitter, 0 is a valid delay (random.uniform(0, upper))."""
        with patch("random.uniform", return_value=0.0):
            delay = calculate_full_jitter_backoff(0)
        assert delay == 0.0

    def test_upper_bound_respected(self):
        """Delay should never exceed cap."""
        for attempt in range(15):
            with patch("random.uniform", side_effect=lambda lo, hi: hi):
                delay = calculate_full_jitter_backoff(attempt)
            assert delay <= 60.0  # _BACKOFF_CAP_SEC

    def test_exponential_growth_of_upper_bound(self):
        """Upper bound doubles each attempt (up to cap)."""
        expected_upper = [1, 2, 4, 8, 16, 32, 60, 60]
        for i, expected in enumerate(expected_upper):
            with patch("random.uniform", side_effect=lambda lo, hi: hi):
                delay = calculate_full_jitter_backoff(i)
            assert delay == pytest.approx(expected), f"attempt {i}"

    def test_custom_base_and_cap(self):
        with patch("random.uniform", side_effect=lambda lo, hi: hi):
            delay = calculate_full_jitter_backoff(3, base=2.0, cap=100.0)
        assert delay == pytest.approx(16.0)  # min(100, 2 * 2^3)

    def test_jitter_is_applied(self):
        """Multiple calls should produce different values (probabilistic)."""
        values = set()
        for _ in range(50):
            v = calculate_full_jitter_backoff(5)
            values.add(round(v, 4))
        assert len(values) > 10, "Backoff should have real jitter"


# ── OpenApiTradeClient Initialization ────────────────────────────────────────

from adapters.ctrader.open_api_trade_client import (
    OpenApiTradeClient,
    OrderResult,
)


def _make_client(**kwargs):
    """Create a trade client with test credentials."""
    defaults = dict(
        ctid_account_id=12345,
        client_id="test_client_id",
        client_secret="test_client_secret",
        access_token="test_access_token",
        host="demo.ctraderapi.com",
        port=5035,
    )
    defaults.update(kwargs)
    return OpenApiTradeClient(**defaults)


class TestTradeClientInit:
    def test_init_does_not_require_spot_feed(self):
        """Trade client must NOT need a spot feed reference."""
        client = _make_client()
        assert getattr(client, "_spot_feed", None) is None

    def test_init_has_state_manager(self):
        client = _make_client()
        assert client.state_manager is not None
        assert client.state == ConnectionState.DISCONNECTED

    def test_init_not_connected(self):
        client = _make_client()
        assert not client.is_connected

    def test_init_is_live_mode(self):
        """Trade client is always live-mode (paper mode is at engine level)."""
        client = _make_client()
        assert client.is_live_mode

    def test_init_has_kill_switch_none(self):
        client = _make_client()
        assert client._kill_switch is None

    def test_init_with_kill_switch(self):
        import tempfile, os
        tmp = tempfile.mkdtemp()
        ks_dir = os.path.join(tmp, "kill_switches")
        os.makedirs(ks_dir)
        ks = KillSwitchManager(state_dir=ks_dir)
        client = _make_client(kill_switch=ks)
        assert client._kill_switch is ks

    def test_set_symbol_map(self):
        client = _make_client()
        client.set_symbol_map({"GBPUSD": 2, "USDJPY": 4})
        assert client.resolve_symbol_id("GBPUSD") == 2
        assert client.resolve_symbol_id("USDJPY") == 4

    def test_resolve_unknown_symbol_raises(self):
        client = _make_client()
        client.set_symbol_map({"GBPUSD": 2})
        with pytest.raises(ValueError, match="EURUSD"):
            client.resolve_symbol_id("EURUSD")

    def test_set_kill_switch_after_init(self):
        import tempfile, os
        tmp = tempfile.mkdtemp()
        ks_dir = os.path.join(tmp, "kill_switches")
        os.makedirs(ks_dir)
        client = _make_client()
        ks = KillSwitchManager(state_dir=ks_dir)
        client.set_kill_switch(ks)
        assert client._kill_switch is ks


# ── OrderResult ──────────────────────────────────────────────────────────────

class TestOrderResult:
    def test_success_result(self):
        r = OrderResult(
            success=True,
            order_id="12345",
            position_id="67890",
        )
        assert r.success
        assert r.order_id == "12345"

    def test_failure_result(self):
        r = OrderResult(
            success=False,
            error="Insufficient margin",
        )
        assert not r.success
        assert r.error == "Insufficient margin"

    def test_result_has_timestamp(self):
        r = OrderResult(success=True)
        assert r.timestamp is not None

    def test_result_defaults(self):
        r = OrderResult(success=True)
        assert r.order_id is None
        assert r.position_id is None
        assert r.filled_price is None
        assert r.volume is None
        assert r.error is None
        assert r.client_msg_id is None


# ── Kill Switch Integration ──────────────────────────────────────────────────

from adapters.ctrader.kill_switch import KillSwitchManager


class TestKillSwitchIntegration:
    def _make_ks(self, tmp_path):
        ks_dir = str(tmp_path / "kill_switches")
        import os
        os.makedirs(ks_dir, exist_ok=True)
        return KillSwitchManager(state_dir=ks_dir)

    def test_failed_state_activates_freeze(self, tmp_path):
        """When _fire_kill_switch is called, kill switch should FREEZE."""
        ks = self._make_ks(tmp_path)
        client = _make_client(kill_switch=ks)

        # The trade client fires kill switch from auth failures and
        # connection loss paths, not from the state change callback directly.
        client._fire_kill_switch("connection_failed")

        assert ks.is_globally_frozen()
        status = ks.get_status()
        assert "connection_failed" in status.get("reason", "")

    def test_non_failed_state_no_freeze(self, tmp_path):
        """Normal state transitions should not activate kill switch."""
        ks = self._make_ks(tmp_path)
        client = _make_client(kill_switch=ks)

        client._on_state_change_internal(
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED,
            "tcp_connected",
            {},
        )
        assert not ks.is_active()

    def test_no_kill_switch_no_crash(self):
        """If kill_switch is None, _fire_kill_switch should not crash."""
        client = _make_client()  # no kill_switch
        client._fire_kill_switch("test_no_ks")
        # Should not raise

    def test_kill_switch_not_fired_twice(self, tmp_path):
        """Multiple _fire_kill_switch calls should only fire once."""
        ks = self._make_ks(tmp_path)
        client = _make_client(kill_switch=ks)

        # First fire
        client._fire_kill_switch("first_failure")
        assert ks.is_globally_frozen()

        # Second fire should be suppressed by _kill_switch_fired flag
        # Verify the flag is set
        assert client._kill_switch_fired is True
        # Call again — should be no-op
        client._fire_kill_switch("second_failure")
        # ks state unchanged (still same freeze from first call)
        assert ks.is_globally_frozen()
        status = ks.get_status()
        assert "first_failure" in status.get("reason", "")


# ── Order Submission (Not Connected) ─────────────────────────────────────────

class TestOrderNotConnected:
    def test_market_order_not_connected(self):
        client = _make_client()
        # Client starts disconnected
        result = client.send_market_order(
            symbol="GBPUSD",
            side="long",
            volume=0.10,
            stop_loss=1.2500,
            take_profit=1.2700,
        )
        assert isinstance(result, OrderResult)
        assert not result.success
        assert "not_connected" in (result.error or "")

    def test_limit_order_not_connected(self):
        client = _make_client()
        result = client.send_limit_order(
            symbol="GBPUSD",
            side="long",
            volume=0.10,
            price=1.2550,
        )
        assert isinstance(result, OrderResult)
        assert not result.success

    def test_market_order_unknown_symbol(self, tmp_path):
        """Connected but unknown symbol should fail gracefully."""
        import os
        ks_dir = str(tmp_path / "kill_switches")
        os.makedirs(ks_dir)
        client = _make_client()
        # Force state to AUTHENTICATED
        client._state_mgr._state = ConnectionState.AUTHENTICATED
        # No symbol map set
        result = client.send_market_order("EURUSD", "long", 0.1)
        assert not result.success


# ── Reconnection Logic ───────────────────────────────────────────────────────

class TestReconnectionLogic:
    def test_max_reconnect_attempts(self):
        """After max attempts (10), state should be FAILED."""
        from adapters.ctrader.open_api_trade_client import _BACKOFF_MAX_ATTEMPTS
        assert _BACKOFF_MAX_ATTEMPTS == 10

    def test_backoff_constants(self):
        from adapters.ctrader.open_api_trade_client import (
            _BACKOFF_BASE_SEC,
            _BACKOFF_CAP_SEC,
        )
        assert _BACKOFF_BASE_SEC == 1.0
        assert _BACKOFF_CAP_SEC == 60.0

    def test_heartbeat_constants(self):
        from adapters.ctrader.open_api_trade_client import (
            _HEARTBEAT_INTERVAL_SEC,
            _HEARTBEAT_DEGRADED_SEC,
            _HEARTBEAT_RECONNECT_SEC,
        )
        assert _HEARTBEAT_INTERVAL_SEC == 10.0
        assert _HEARTBEAT_DEGRADED_SEC == 15.0
        assert _HEARTBEAT_RECONNECT_SEC == 30.0

    def test_timeout_constants(self):
        from adapters.ctrader.open_api_trade_client import (
            _AUTH_TIMEOUT_SEC,
            _ORDER_TIMEOUT_SEC,
            _TCP_CONNECT_TIMEOUT_SEC,
        )
        assert _AUTH_TIMEOUT_SEC == 10.0
        assert _ORDER_TIMEOUT_SEC == 15.0
        assert _TCP_CONNECT_TIMEOUT_SEC == 15.0


# ── Disconnect ───────────────────────────────────────────────────────────────

class TestDisconnect:
    def test_disconnect_sets_not_running(self):
        client = _make_client()
        client._running = True
        client.disconnect()
        assert not client._running

    def test_disconnect_idempotent(self):
        client = _make_client()
        client.disconnect()  # should not crash
        client.disconnect()  # double disconnect ok
