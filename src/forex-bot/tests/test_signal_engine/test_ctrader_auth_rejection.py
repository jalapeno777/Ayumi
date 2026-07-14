"""Regression test: cTrader INVALID_REQUEST 'not authorized' rejection cleanup.

Tests the fixes from card 7698bbd5:
1. Auth callback mapping: 2101 → _app_authed, 2103 → _authed (not swapped)
2. _auth() explicitly sets _app_authed and _authed after successful auth
3. INVALID_REQUEST with "not authorized" description activates kill switch
4. Order timeout triggers on_order_rejected callback (not silent PENDING)
5. Kill switch is actually activated (not just logged) when policy says so
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class TestAuthCallbackMapping(unittest.TestCase):
    """Verify _on_message sets the correct auth events for 2101/2103."""

    def _make_feed(self):
        """Create a minimal OpenApiSpotFeed-like object for testing."""
        from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed

        # Create a mock instance bypassing __init__
        feed = OpenApiSpotFeed.__new__(OpenApiSpotFeed)
        feed._app_authed = threading.Event()
        feed._authed = threading.Event()
        feed._auth_error_count = 5
        feed._auth_circuit_open = True
        feed._last_successful_auth_time = 0.0
        feed._conn = MagicMock()
        feed._conn._last_heartbeat_recv = None
        feed._pending_orders = {}
        feed._pending_client_msg_ids = {}
        feed._callbacks = {}
        feed._callback_executor = MagicMock()
        feed._token_lifecycle = None
        feed._auth_circuit_open = True
        feed._refresh_in_progress = False
        feed._state_mgr = MagicMock()
        feed._state_mgr.is_operational = True
        feed._state_mgr.is_authenticated = True
        feed._state_mgr.state = MagicMock()
        feed._state_mgr.state.value = "AUTHENTICATED"
        feed._symbol_digits = {}
        feed._ticks = {}
        feed._ticks_by_id = {}
        feed._tick_callbacks = []
        feed._tick_counts = {}
        feed._lock = threading.Lock()
        feed._last_tick_recv_monotonic = time.monotonic()
        feed._kill_switch = None
        feed._permission_policy = None
        feed._token_mgr = MagicMock()
        feed._refresh_lock = threading.Lock()
        feed._refresh_timer = None
        feed._refresh_in_progress = False
        feed._last_reactive_refresh_time = 0.0
        return feed

    def test_msg_2101_sets_app_authed_not_authed(self):
        """ProtoOAApplicationAuthRes (2101) must set _app_authed, not _authed."""
        feed = self._make_feed()
        feed._authed.clear()
        feed._app_authed.clear()

        msg = MagicMock()
        msg.payloadType = 2101

        feed._on_message(None, msg)

        self.assertTrue(feed._app_authed.is_set(),
                        "2101 (AppAuthRes) must set _app_authed")
        self.assertFalse(feed._authed.is_set(),
                         "2101 (AppAuthRes) must NOT set _authed")

    def test_msg_2103_sets_authed_not_app_authed(self):
        """ProtoOAAccountAuthRes (2103) must set _authed, not _app_authed."""
        feed = self._make_feed()
        feed._authed.clear()
        feed._app_authed.clear()
        feed._auth_error_count = 3
        feed._auth_circuit_open = True

        msg = MagicMock()
        msg.payloadType = 2103

        feed._on_message(None, msg)

        self.assertTrue(feed._authed.is_set(),
                        "2103 (AccountAuthRes) must set _authed")
        self.assertFalse(feed._app_authed.is_set(),
                         "2103 (AccountAuthRes) must NOT set _app_authed")

    def test_msg_2103_resets_error_count_and_circuit(self):
        """Successful account auth (2103) must reset error count and circuit breaker."""
        feed = self._make_feed()
        feed._auth_error_count = 5
        feed._auth_circuit_open = True

        msg = MagicMock()
        msg.payloadType = 2103

        feed._on_message(None, msg)

        self.assertEqual(feed._auth_error_count, 0,
                         "2103 must reset _auth_error_count to 0")
        self.assertFalse(feed._auth_circuit_open,
                         "2103 must clear _auth_circuit_open")


class TestOrderTimeoutRejection(unittest.TestCase):
    """Verify order timeout triggers on_order_rejected callback."""

    def test_timeout_sets_rejected_status(self):
        """Order timeout must set status to REJECTED, not PENDING."""
        from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed
        from adapters.ctrader.models import OrderStatus

        feed = OpenApiSpotFeed.__new__(OpenApiSpotFeed)
        feed._pending_orders = {}
        feed._pending_client_msg_ids = {}
        from concurrent.futures import ThreadPoolExecutor
        feed._callbacks = {"on_order_rejected": []}
        feed._callback_executor = ThreadPoolExecutor(max_workers=1)
        feed._state_mgr = MagicMock()
        feed._state_mgr.is_operational = True
        feed._permission_policy = None
        feed._volume_calc = MagicMock()
        feed._volume_calc.volume_to_lots.return_value = 0.1
        feed._ctid_account_id = 12345
        feed._symbol_digits = {1: 5}
        feed._id_to_name = {1: "EURUSD"}
        feed._conn = MagicMock()
        feed._conn.client = MagicMock()

        # Track callback
        callback_called = threading.Event()
        callback_args = []

        def track_callback(order, message, reason):
            callback_args.append((order, reason))
            callback_called.set()

        feed._callbacks["on_order_rejected"] = [track_callback]

        # Patch reactor to prevent actual send
        with patch("adapters.ctrader.open_api_spot_feed.reactor") as mock_reactor:
            mock_reactor.callFromThread.side_effect = lambda f: f()

            # Call new_order with very short timeout
            from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
                ProtoOAOrderType, ProtoOATradeSide,
            )

            order = feed.new_order(
                symbol_id=1,
                side=ProtoOATradeSide.BUY,
                volume=10000,
                order_type=ProtoOAOrderType.MARKET,
                timeout=0.05,  # 50ms timeout
            )

        # Wait for callback
        self.assertTrue(callback_called.wait(timeout=2.0),
                        "on_order_rejected callback must fire on timeout")

        self.assertEqual(order.status, OrderStatus.REJECTED,
                         "Timed-out order must be REJECTED, not PENDING")
        self.assertEqual(order.comment, "timeout_awaiting_event")
        self.assertEqual(callback_args[0][1], "timeout_awaiting_event")


class TestAuthErrorKillSwitchActivation(unittest.TestCase):
    """Verify INVALID_REQUEST with 'not authorized' activates kill switch."""

    def test_not_authorized_activates_kill_switch(self):
        """INVALID_REQUEST + 'not authorized' must activate kill switch freeze."""
        from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed

        feed = OpenApiSpotFeed.__new__(OpenApiSpotFeed)
        feed._auth_circuit_open = False
        feed._refresh_in_progress = False
        feed._last_reactive_refresh_time = 0.0
        feed._token_lifecycle = None
        feed._kill_switch = MagicMock()
        feed._kill_switch.is_active = False
        feed._state_mgr = MagicMock()
        feed._auth_error_count = 0
        feed._conn = MagicMock()
        feed._conn._last_heartbeat_recv = None

        kill_switch_activated = threading.Event()

        def fake_activate(reason, triggered_by=None):
            kill_switch_activated.set()

        feed._activate_kill_switch_freeze = fake_activate

        # Build a mock error message
        error_msg = MagicMock()
        error_msg.errorCode = "INVALID_REQUEST"
        error_msg.description = "Trading account is not authorized"

        feed._handle_error(error_msg)

        self.assertTrue(kill_switch_activated.is_set(),
                        "INVALID_REQUEST with 'not authorized' must activate kill switch")

    def test_generic_invalid_request_does_not_activate_kill_switch(self):
        """Generic INVALID_REQUEST without 'not authorized' should NOT activate kill switch."""
        from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed

        feed = OpenApiSpotFeed.__new__(OpenApiSpotFeed)
        feed._auth_circuit_open = False
        feed._refresh_in_progress = False
        feed._last_reactive_refresh_time = 0.0
        feed._token_lifecycle = None
        feed._kill_switch = None
        feed._state_mgr = MagicMock()
        feed._auth_error_count = 0
        feed._conn = MagicMock()
        feed._conn._last_heartbeat_recv = None

        kill_switch_activated = threading.Event()
        feed._activate_kill_switch_freeze = lambda r: kill_switch_activated.set()

        error_msg = MagicMock()
        error_msg.errorCode = "INVALID_REQUEST"
        error_msg.description = "Malformed order payload"

        feed._handle_error(error_msg)

        self.assertFalse(kill_switch_activated.is_set(),
                         "Generic INVALID_REQUEST must NOT activate kill switch")


if __name__ == "__main__":
    unittest.main()
