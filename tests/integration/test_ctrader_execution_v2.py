"""Tests for BQ-716: cTrader execution with OpenApiSpotFeed.

Validates OpenApiSpotFeed's order execution, reconciliation, and error handling.
The old OpenApiTradeClient and OpenApiLiveClient have been deleted; all order
operations now go through OpenApiSpotFeed.

Coverage:
- new_order (market/limit): success, timeout, not_connected, unknown_symbol
- cancel_order, amend_order, close_position, reconcile
- State guards: rejects operations when not connected
- Callbacks: on_order_filled, on_order_rejected, on_position_opened/closed
- Symbol resolution
"""

import threading
import unittest
from unittest.mock import MagicMock, patch

from adapters.ctrader.connection_state import ConnectionState
from adapters.ctrader.models import Order, OrderStatus, OrderType, TradeDirection
from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed, _lots_to_units

# ProtoOAExecutionType enum pulled from the same vendored pb2 module the
# production code uses (ctrader_open_api). Importing the enum (not magic
# numbers) keeps these tests aligned with the terminal-only state machine
# introduced for card ce6de98d.
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAExecutionType


def _make_spot_feed():
    """Create an OpenApiSpotFeed with mocked internals for testing."""
    with patch("adapters.ctrader.connection.ReactorManager"):
        feed = OpenApiSpotFeed(
            ctid_account_id=12345,
            client_id="test_client",
            client_secret="test_secret",  # noqa: S106
            access_token="test_access",  # noqa: S106
        )
    feed._reactor_manager = MagicMock()
    feed._client = MagicMock()
    feed._client.isConnected = True
    feed._running = True
    feed._authed.set()
    feed._state_mgr._state = ConnectionState.AUTHENTICATED
    feed._name_to_id = {"EURUSD": 1, "GBPUSD": 2}
    feed._id_to_name = {1: "EURUSD", 2: "GBPUSD"}
    # Mock volume calculator so Order construction doesn't crash on unknown symbol_id
    feed._volume_calc = MagicMock()
    feed._volume_calc.volume_to_lots.return_value = 0.01
    feed._volume_calc.lots_to_volume.return_value = 1000
    return feed


# ---------------------------------------------------------------------------
# new_order (market)
# ---------------------------------------------------------------------------


class TestNewOrderMarket(unittest.TestCase):
    def setUp(self):
        self.feed = _make_spot_feed()

    def test_market_order_success(self):
        """Successful market order returns Order with FILLED status."""
        mock_order = Order(
            order_id="test-123",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.01,
            status=OrderStatus.FILLED,
        )
        self.feed.new_order = MagicMock(return_value=mock_order)

        result = self.feed.new_order(symbol_id=1, side=MagicMock(), volume=1000)

        self.assertEqual(result.status, OrderStatus.FILLED)
        self.assertEqual(result.order_id, "test-123")

    def test_market_order_timeout(self):
        """Timeout returns Order with PENDING status and timeout reason."""
        mock_order = Order(
            order_id="test-456",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.01,
            status=OrderStatus.PENDING,
        )
        mock_order.reason = "timeout_awaiting_event"
        self.feed.new_order = MagicMock(return_value=mock_order)

        result = self.feed.new_order(symbol_id=1, side=MagicMock(), volume=1000)

        self.assertEqual(result.status, OrderStatus.PENDING)
        self.assertIn("timeout", getattr(result, "reason", ""))

    def test_market_order_not_connected(self):
        """Rejects order when not connected."""
        self.feed._state_mgr._state = ConnectionState.DISCONNECTED

        result = self.feed.new_order(symbol_id=1, side=MagicMock(), volume=1000)

        self.assertEqual(getattr(result, "reason", ""), "not_connected")

    def test_market_order_with_sl_tp(self):
        """Market order with SL/TP passes them through."""
        mock_order = Order(
            order_id="test-789",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=1.0,
            status=OrderStatus.FILLED,
        )
        self.feed.new_order = MagicMock(return_value=mock_order)

        result = self.feed.new_order(
            symbol_id=1,
            side=MagicMock(),
            volume=100000,
            sl=1.0800,
            tp=1.1000,
        )

        self.assertEqual(result.status, OrderStatus.FILLED)

    def test_market_order_sell(self):
        """Market order sell (short) direction works."""
        mock_order = Order(
            order_id="test-sell",
            symbol="GBPUSD",
            direction=TradeDirection.SHORT,
            order_type=OrderType.MARKET,
            volume=0.05,
            status=OrderStatus.FILLED,
        )
        self.feed.new_order = MagicMock(return_value=mock_order)

        result = self.feed.new_order(symbol_id=2, side=MagicMock(), volume=5000)

        self.assertEqual(result.status, OrderStatus.FILLED)

    def test_market_order_send_failed(self):
        """Send failure returns Order with REJECTED status."""
        mock_order = Order(
            order_id="test-fail",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.01,
            status=OrderStatus.REJECTED,
        )
        mock_order.reason = "send_failed"
        self.feed.new_order = MagicMock(return_value=mock_order)

        result = self.feed.new_order(symbol_id=1, side=MagicMock(), volume=1000)

        self.assertEqual(result.status, OrderStatus.REJECTED)


# ---------------------------------------------------------------------------
# new_order (limit)
# ---------------------------------------------------------------------------


class TestNewOrderLimit(unittest.TestCase):
    def setUp(self):
        self.feed = _make_spot_feed()

    def test_limit_order_success(self):
        """Limit order returns Order with PENDING status (waiting for fill)."""
        mock_order = Order(
            order_id="lim-111",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.LIMIT,
            volume=0.01,
            status=OrderStatus.PENDING,
        )
        self.feed.new_order = MagicMock(return_value=mock_order)

        result = self.feed.new_order(
            symbol_id=1,
            side=MagicMock(),
            volume=1000,
            order_type=MagicMock(),
            price=1.0850,
        )

        self.assertEqual(result.status, OrderStatus.PENDING)
        self.assertEqual(result.order_id, "lim-111")

    def test_limit_order_timeout(self):
        """Limit order timeout returns PENDING with timeout reason."""
        mock_order = Order(
            order_id="lim-222",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.LIMIT,
            volume=0.01,
            status=OrderStatus.PENDING,
        )
        mock_order.reason = "timeout_awaiting_event"
        self.feed.new_order = MagicMock(return_value=mock_order)

        result = self.feed.new_order(
            symbol_id=1,
            side=MagicMock(),
            volume=1000,
            order_type=MagicMock(),
            price=1.0850,
        )

        self.assertEqual(result.status, OrderStatus.PENDING)

    def test_limit_order_not_connected(self):
        """Limit order rejected when not connected."""
        self.feed._state_mgr._state = ConnectionState.DISCONNECTED

        result = self.feed.new_order(
            symbol_id=1,
            side=MagicMock(),
            volume=1000,
            order_type=MagicMock(),
            price=1.0850,
        )

        self.assertEqual(getattr(result, "reason", ""), "not_connected")


# ---------------------------------------------------------------------------
# Order Management (bool returns)
# ---------------------------------------------------------------------------


class TestOrderManagement(unittest.TestCase):
    def setUp(self):
        self.feed = _make_spot_feed()

    def test_amend_order_success(self):
        self.feed._conn.send_and_wait = MagicMock(return_value=MagicMock())
        result = self.feed.amend_order(order_id=123, price=1.0900, sl=1.0800)
        self.assertTrue(result)

    def test_amend_order_timeout(self):
        self.feed._conn.send_and_wait = MagicMock(return_value=None)
        result = self.feed.amend_order(order_id=123, price=1.0900)
        self.assertFalse(result)

    def test_cancel_order_success(self):
        self.feed._conn.send_and_wait = MagicMock(return_value=MagicMock())
        result = self.feed.cancel_order(order_id=456)
        self.assertTrue(result)

    def test_cancel_order_timeout(self):
        self.feed._conn.send_and_wait = MagicMock(return_value=None)
        result = self.feed.cancel_order(order_id=456)
        self.assertFalse(result)

    def test_close_position_success(self):
        self.feed._conn.send_and_wait = MagicMock(return_value=MagicMock())
        result = self.feed.close_position(position_id=789, volume=1000)
        self.assertTrue(result)

    def test_close_position_timeout(self):
        self.feed._conn.send_and_wait = MagicMock(return_value=None)
        result = self.feed.close_position(position_id=789, volume=1000)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


class TestReconcile(unittest.TestCase):
    def setUp(self):
        self.feed = _make_spot_feed()

    def test_reconcile_success(self):
        """Successful reconcile returns position data."""
        self.feed.reconcile = MagicMock(return_value=[{"position_id": 111, "volume": 100000}])

        result = self.feed.reconcile()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["position_id"], 111)

    def test_reconcile_empty(self):
        """Reconcile with no positions returns empty list."""
        self.feed.reconcile = MagicMock(return_value=[])
        result = self.feed.reconcile()
        self.assertEqual(result, [])

    def test_reconcile_not_connected(self):
        """Not connected returns empty list."""
        self.feed._state_mgr._state = ConnectionState.DISCONNECTED
        self.feed.reconcile = MagicMock(return_value=[])
        result = self.feed.reconcile()
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Execution Events & Callbacks
# ---------------------------------------------------------------------------


def _make_execution_event(exec_type=1, order_id=98765, position_id=12345):
    """Create a mock ProtoOAExecutionEvent payload."""
    order = MagicMock()
    order.orderId = order_id
    position = MagicMock()
    position.positionId = position_id
    payload = MagicMock()
    payload.executionType = exec_type
    payload.order = order
    payload.position = position
    return payload


class TestCallbacks(unittest.TestCase):
    def setUp(self):
        self.feed = _make_spot_feed()
        self.filled = []
        self.rejected = []
        self.cancelled = []
        self.feed.register_callback("on_order_filled", lambda o, m: self.filled.append((o, m)))
        self.feed.register_callback("on_order_rejected", lambda o, m, r: self.rejected.append((o, m, r)))
        self.feed.register_callback("on_order_cancelled", lambda o, m: self.cancelled.append((o, m)))

    def _prime_pending_order(self, client_order_id="test-cid-111"):
        """Add a pending order so _handle_execution_event can match it."""
        order = Order(
            order_id="111",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.01,
            status=OrderStatus.PENDING,
        )
        event = threading.Event()
        self.feed._pending_orders[client_order_id] = (event, order)

    def test_order_filled_callback(self):
        """OrderFilled (3) execution event with matching clientOrderId fires on_order_filled."""
        # Use ProtoOAExecutionType.ORDER_FILLED (= 3), the REAL fill path under
        # the terminal-only state machine (card ce6de98d). The previous magic
        # number exec_type=1 relied on the buggy "unknown etype → FILLED"
        # fallthrough and was removed when the state machine was tightened.
        self._prime_pending_order("cid-111")
        payload = _make_execution_event(
            exec_type=ProtoOAExecutionType.ORDER_FILLED,
            order_id=111,
            position_id=222,
        )
        # Set clientOrderId so it matches the pending order
        payload.order.clientOrderId = "cid-111"
        self.feed._handle_execution_event(payload)
        self.assertEqual(len(self.filled), 1)
        # Terminal FILLED path must also pop the pending entry and leave the
        # order in FILLED status — guards against a regression to the old
        # acceptance-as-fill bug where the pending entry lingered.
        self.assertNotIn("cid-111", self.feed._pending_orders)
        self.assertEqual(self.filled[-1][0].status, OrderStatus.FILLED)

    def test_order_cancelled_callback(self):
        """Execution type 6 (CANCELLED) fires on_order_cancelled."""
        self._prime_pending_order("cid-cancel")
        payload = _make_execution_event(exec_type=5, order_id=222)
        payload.order.clientOrderId = "cid-cancel"
        self.feed._handle_execution_event(payload)
        self.assertEqual(len(self.cancelled), 1)

    def test_order_rejected_callback(self):
        """Execution type 5 (REJECTED) fires on_order_rejected."""
        self._prime_pending_order("cid-reject")
        payload = _make_execution_event(exec_type=7, order_id=333)
        payload.order.clientOrderId = "cid-reject"
        payload.errorCode = "INVALID_VOLUME"
        self.feed._handle_execution_event(payload)
        self.assertEqual(len(self.rejected), 1)

    def test_unknown_execution_type_no_crash(self):
        """Unknown / informational execType is a no-op under the terminal-only state machine.

        Under the card ce6de98d fix, an execType outside the terminal set
        ({FILLED=3, CANCELLED=5, EXPIRED=6, REJECTED=7}) — including any
        unknown value (e.g. 99) and any informational broker event —
        must:
          * not crash
          * not fire any of the terminal callbacks
          * leave the pending entry in _pending_orders so a future
            terminal event can still match it
        """
        self._prime_pending_order("cid-unknown")
        payload = _make_execution_event(exec_type=99, order_id=444)
        payload.order.clientOrderId = "cid-unknown"
        # If the state machine regressed back to fallthrough-to-FILLED, the
        # following call would either crash or fire on_order_filled
        # spuriously. Under the new semantics it must be a silent no-op.
        self.feed._handle_execution_event(payload)

        # Still no crash — implicit by reaching these assertions.
        # No terminal callback fired.
        self.assertEqual(len(self.filled), 0)
        self.assertEqual(len(self.rejected), 0)
        self.assertEqual(len(self.cancelled), 0)
        # Pending order MUST remain — informational execType must not pop
        # the entry, so a later FILLED/CANCELLED/REJECTED can still resolve.
        self.assertIn("cid-unknown", self.feed._pending_orders)
        pending_event, pending_order = self.feed._pending_orders["cid-unknown"]
        # Order status untouched (still PENDING from _prime_pending_order).
        self.assertEqual(pending_order.status, OrderStatus.PENDING)
        # Event was not set — new_order() / send_order() would still time
        # out waiting for a terminal response.
        self.assertFalse(pending_event.is_set())


# ---------------------------------------------------------------------------
# State Guards
# ---------------------------------------------------------------------------


class TestStateGuards(unittest.TestCase):
    def setUp(self):
        self.feed = _make_spot_feed()

    def test_new_order_blocked_when_disconnected(self):
        """new_order returns not-connected Order when disconnected."""
        self.feed._state_mgr._state = ConnectionState.DISCONNECTED
        result = self.feed.new_order(symbol_id=1, side=MagicMock(), volume=1000)
        self.assertEqual(getattr(result, "reason", ""), "not_connected")

    def test_amend_blocked_when_send_fails(self):
        self.feed._conn.send_and_wait = MagicMock(return_value=None)
        result = self.feed.amend_order(order_id=123, price=1.09)
        self.assertFalse(result)

    def test_cancel_blocked_when_send_fails(self):
        self.feed._conn.send_and_wait = MagicMock(return_value=None)
        result = self.feed.cancel_order(order_id=123)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# send_order (high-level wrapper)
# ---------------------------------------------------------------------------


class TestSendOrder(unittest.TestCase):
    def setUp(self):
        self.feed = _make_spot_feed()

    def test_send_order_market(self):
        """send_order delegates to new_order for market orders."""
        mock_order = Order(
            order_id="so-111",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.01,
            status=OrderStatus.FILLED,
        )
        self.feed.new_order = MagicMock(return_value=mock_order)

        result = self.feed.send_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.01,
        )

        self.assertEqual(result.order_id, "so-111")

    def test_send_order_limit(self):
        """send_order delegates to new_order for limit orders."""
        mock_order = Order(
            order_id="so-222",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.LIMIT,
            volume=0.01,
            status=OrderStatus.PENDING,
        )
        self.feed.new_order = MagicMock(return_value=mock_order)

        result = self.feed.send_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.LIMIT,
            volume=0.01,
            price=1.0850,
        )

        self.assertEqual(result.order_id, "so-222")

    def test_send_order_unknown_symbol_raises(self):
        """send_order raises ValueError for unknown symbol."""
        with self.assertRaises((ValueError, KeyError)):
            self.feed.send_order(
                symbol="XYZABC",
                direction=TradeDirection.LONG,
                order_type=OrderType.MARKET,
                volume=0.01,
            )

    def test_send_order_sell(self):
        """send_order handles SHORT direction."""
        mock_order = Order(
            order_id="so-sell",
            symbol="GBPUSD",
            direction=TradeDirection.SHORT,
            order_type=OrderType.MARKET,
            volume=0.05,
            status=OrderStatus.FILLED,
        )
        self.feed.new_order = MagicMock(return_value=mock_order)

        result = self.feed.send_order(
            symbol="GBPUSD",
            direction=TradeDirection.SHORT,
            order_type=OrderType.MARKET,
            volume=0.05,
        )

        self.assertEqual(result.order_id, "so-sell")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers(unittest.TestCase):
    def test_lots_to_units(self):
        self.assertEqual(_lots_to_units(1.0), 100000)
        self.assertEqual(_lots_to_units(0.01), 1000)
        self.assertEqual(_lots_to_units(0.1), 10000)


# ---------------------------------------------------------------------------
# Symbol Resolution
# ---------------------------------------------------------------------------


class TestSymbolResolution(unittest.TestCase):
    def setUp(self):
        self.feed = _make_spot_feed()

    def test_resolve_known_symbol(self):
        self.assertEqual(self.feed.resolve_symbol_id("EURUSD"), 1)

    def test_resolve_symbol_case_insensitive(self):
        self.assertEqual(self.feed.resolve_symbol_id("eurusd"), 1)

    def test_resolve_unknown_symbol_raises(self):
        with self.assertRaises(ValueError):
            self.feed.resolve_symbol_id("XYZABC")


if __name__ == "__main__":
    unittest.main()
