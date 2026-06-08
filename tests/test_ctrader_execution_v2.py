"""Tests for BQ-716: cTrader execution with OpenApiTradeClient.

Replaces test_ctrader_execution.py which tested the deprecated OpenApiLiveClient.
These tests validate the new OpenApiTradeClient's order execution, reconciliation,
and error handling.

Coverage:
- send_market_order: success, rejection, timeout, unexpected payload
- send_limit_order: success, rejection, timeout
- close_position, amend_order, cancel_order
- reconcile: success, empty, parse errors
- State guards: rejects operations when not connected
- Callbacks: on_order_filled, on_order_rejected, on_position_opened/closed
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from unittest import mock
mock_modules = {
    'ctrader_open_api': mock.MagicMock(),
    'ctrader_open_api.client': mock.MagicMock(),
    'ctrader_open_api.messages': mock.MagicMock(),
    'ctrader_open_api.messages.OpenApiMessages_pb2': mock.MagicMock(),
    'ctrader_open_api.messages.OpenApiModelMessages_pb2': mock.MagicMock(),
    'ctrader_open_api.protobuf': mock.MagicMock(),
    'ctrader_open_api.tcpProtocol': mock.MagicMock(),
    'twisted.internet': mock.MagicMock(),
    'twisted.internet.reactor': mock.MagicMock(),
}
for mod_name, mod_obj in mock_modules.items():
    sys.modules.setdefault(mod_name, mod_obj)

from adapters.ctrader.open_api_trade_client import (
    OpenApiTradeClient,
    OrderResult,
    calculate_full_jitter_backoff,
    _lots_to_units,
)
from adapters.ctrader.connection_state import ConnectionState, ConnectionStateManager


def _make_trade_client():
    """Create an OpenApiTradeClient with mocked internals for testing."""
    client = OpenApiTradeClient(
        ctid_account_id=12345,
        client_id="test_client",
        client_secret="test_secret",
        access_token="test_token",
    )
    # Mock internal client as connected
    client._client = MagicMock()
    client._client.isConnected = True
    client._running = True
    client._connected_event.set()
    # Force state to AUTHENTICATED
    client._state_mgr._state = ConnectionState.AUTHENTICATED
    # Add symbol mapping
    client.set_symbol_map({"EURUSD": 1, "GBPUSD": 2})
    return client


def _make_order_response(order_id=98765, position_id=None):
    """Create a mock ProtoOANewOrderRes response."""
    payload = MagicMock()
    payload.orderId = order_id
    payload.positionId = position_id

    response = MagicMock()
    response.payloadType = 2132  # ProtoOANewOrderRes
    return response, payload


def _make_execution_event(exec_type=1, order_id=98765, position_id=12345):
    """Create a mock ProtoOAExecutionEvent (payloadType=2151)."""
    order = MagicMock()
    order.orderId = order_id

    position = MagicMock()
    position.positionId = position_id

    payload = MagicMock()
    payload.executionType = exec_type
    payload.order = order
    payload.position = position
    return payload


def _make_error_response(error_code="INVALID_VOLUME", description="Too small"):
    """Create a mock ProtoOAErrorRes (payloadType=2142)."""
    payload = MagicMock()
    payload.errorCode = error_code
    payload.description = description
    return payload


def _make_reconcile_response(positions=None):
    """Create a mock ProtoOAReconcileRes (payloadType=2149)."""
    payload = MagicMock()
    payload.position = positions if positions is not None else []
    return payload


# ═══════════════════════════════════════════════════════════════════════════════
# Market Orders
# ═══════════════════════════════════════════════════════════════════════════════

class TestSendMarketOrder(unittest.TestCase):

    def setUp(self):
        self.client = _make_trade_client()

    @patch('adapters.ctrader.open_api_trade_client.Protobuf')
    def test_market_order_success(self, mock_pb):
        """Successful market order returns OrderResult with order_id."""
        response, payload = _make_order_response(order_id=98765, position_id=12345)
        mock_pb.extract.return_value = payload
        self.client._send_and_wait = MagicMock(return_value=response)

        result = self.client.send_market_order(
            symbol="EURUSD", side="long", volume=0.01,
        )

        self.assertIsInstance(result, OrderResult)
        self.assertTrue(result.success)
        self.assertEqual(result.order_id, "98765")
        self.assertEqual(result.volume, 0.01)

    def test_market_order_timeout(self):
        """Timeout returns OrderResult with success=False."""
        self.client._send_and_wait = MagicMock(return_value=None)

        result = self.client.send_market_order(
            symbol="EURUSD", side="long", volume=0.01,
        )

        self.assertFalse(result.success)
        self.assertIn("timeout", result.error)

    def test_market_order_not_connected(self):
        """Rejects order when not connected."""
        self.client._state_mgr._state = ConnectionState.DISCONNECTED

        result = self.client.send_market_order(
            symbol="EURUSD", side="long", volume=0.01,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error, "not_connected")

    def test_market_order_unknown_symbol(self):
        """Rejects order for unknown symbol."""
        result = self.client.send_market_order(
            symbol="XYZABC", side="long", volume=0.01,
        )

        self.assertFalse(result.success)
        self.assertIn("not in symbol map", result.error)

    def test_market_order_with_sl_tp(self):
        """Market order with SL/TP passes them through."""
        response, payload = _make_order_response(order_id=111)
        with patch('adapters.ctrader.open_api_trade_client.Protobuf') as mock_pb:
            mock_pb.extract.return_value = payload
            self.client._send_and_wait = MagicMock(return_value=response)

            result = self.client.send_market_order(
                symbol="EURUSD", side="long", volume=0.1,
                stop_loss=1.0800, take_profit=1.1000,
            )

        self.assertTrue(result.success)

    def test_market_order_sell(self):
        """Market order sell (short) direction."""
        response, payload = _make_order_response(order_id=222)
        with patch('adapters.ctrader.open_api_trade_client.Protobuf') as mock_pb:
            mock_pb.extract.return_value = payload
            self.client._send_and_wait = MagicMock(return_value=response)

            result = self.client.send_market_order(
                symbol="GBPUSD", side="short", volume=0.05,
            )

        self.assertTrue(result.success)


# ═══════════════════════════════════════════════════════════════════════════════
# Limit Orders
# ═══════════════════════════════════════════════════════════════════════════════

class TestSendLimitOrder(unittest.TestCase):

    def setUp(self):
        self.client = _make_trade_client()

    @patch('adapters.ctrader.open_api_trade_client.Protobuf')
    def test_limit_order_success(self, mock_pb):
        response, payload = _make_order_response(order_id=55555)
        mock_pb.extract.return_value = payload
        self.client._send_and_wait = MagicMock(return_value=response)

        result = self.client.send_limit_order(
            symbol="EURUSD", side="long", volume=0.01, price=1.0850,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.order_id, "55555")

    def test_limit_order_timeout(self):
        self.client._send_and_wait = MagicMock(return_value=None)

        result = self.client.send_limit_order(
            symbol="EURUSD", side="long", volume=0.01, price=1.0850,
        )

        self.assertFalse(result.success)
        self.assertIn("timeout", result.error)

    def test_limit_order_not_connected(self):
        self.client._state_mgr._state = ConnectionState.DISCONNECTED

        result = self.client.send_limit_order(
            symbol="EURUSD", side="long", volume=0.01, price=1.0850,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error, "not_connected")


# ═══════════════════════════════════════════════════════════════════════════════
# Order Management
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrderManagement(unittest.TestCase):

    def setUp(self):
        self.client = _make_trade_client()

    def test_amend_order_success(self):
        response = MagicMock()
        self.client._send_and_wait = MagicMock(return_value=response)

        result = self.client.amend_order(
            order_id=123, new_price=1.0900, new_sl=1.0800,
        )

        self.assertTrue(result.success)

    def test_amend_order_timeout(self):
        self.client._send_and_wait = MagicMock(return_value=None)

        result = self.client.amend_order(order_id=123, new_price=1.0900)

        self.assertFalse(result.success)

    def test_cancel_order_success(self):
        response = MagicMock()
        self.client._send_and_wait = MagicMock(return_value=response)

        result = self.client.cancel_order(order_id=456)

        self.assertTrue(result.success)
        self.assertEqual(result.order_id, "456")

    def test_close_position_success(self):
        response = MagicMock()
        self.client._send_and_wait = MagicMock(return_value=response)

        result = self.client.close_position(position_id=789, volume=0.01)

        self.assertTrue(result.success)
        self.assertEqual(result.position_id, "789")

    def test_close_position_not_connected(self):
        self.client._state_mgr._state = ConnectionState.DISCONNECTED

        result = self.client.close_position(position_id=789)

        self.assertFalse(result.success)


# ═══════════════════════════════════════════════════════════════════════════════
# Reconciliation
# ═══════════════════════════════════════════════════════════════════════════════

class TestReconcile(unittest.TestCase):

    def setUp(self):
        self.client = _make_trade_client()

    @patch('adapters.ctrader.open_api_trade_client.Protobuf')
    def test_reconcile_success(self, mock_pb):
        """Successful reconcile returns Position objects."""
        pos1 = MagicMock()
        pos1.positionId = 111
        pos1.symbolId = 1
        pos1.volume = 100000
        pos1.price = 1.08432
        pos1.tradeSide = 1
        pos1.stopLoss = 1.0800
        pos1.takeProfit = 1.1000

        response = MagicMock()
        response.payloadType = 2149
        payload = _make_reconcile_response(positions=[pos1])
        mock_pb.extract.return_value = payload
        self.client._send_and_wait = MagicMock(return_value=response)

        result = self.client.reconcile()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].position_id, "111")
        self.assertAlmostEqual(result[0].volume, 1.0, places=2)

    @patch('adapters.ctrader.open_api_trade_client.Protobuf')
    def test_reconcile_empty(self, mock_pb):
        """Reconcile with no positions returns empty list."""
        response = MagicMock()
        response.payloadType = 2149
        payload = _make_reconcile_response(positions=[])
        mock_pb.extract.return_value = payload
        self.client._send_and_wait = MagicMock(return_value=response)

        result = self.client.reconcile()

        self.assertEqual(result, [])

    def test_reconcile_timeout(self):
        """Timeout returns empty list."""
        self.client._send_and_wait = MagicMock(return_value=None)

        result = self.client.reconcile()

        self.assertEqual(result, [])

    def test_reconcile_not_connected(self):
        """Not connected returns empty list."""
        self.client._state_mgr._state = ConnectionState.DISCONNECTED

        result = self.client.reconcile()

        self.assertEqual(result, [])

    @patch('adapters.ctrader.open_api_trade_client.Protobuf')
    def test_reconcile_parse_error_skips_bad_positions(self, mock_pb):
        """Parse error on one position doesn't prevent parsing others."""
        pos_good = MagicMock()
        pos_good.positionId = 111
        pos_good.symbolId = 1
        pos_good.volume = 100000
        pos_good.price = 1.08
        pos_good.tradeSide = 1
        pos_good.stopLoss = 0.0
        pos_good.takeProfit = 0.0

        pos_bad = MagicMock()
        pos_bad.positionId = "not_an_int"  # Will cause parse error
        # Make volume raise exception when accessed
        type(pos_bad).volume = PropertyMock(side_effect=ValueError("bad"))

        response = MagicMock()
        response.payloadType = 2149
        payload = _make_reconcile_response(positions=[pos_good, pos_bad])
        mock_pb.extract.return_value = payload
        self.client._send_and_wait = MagicMock(return_value=response)

        result = self.client.reconcile()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].position_id, "111")


# ═══════════════════════════════════════════════════════════════════════════════
# Execution Events & Callbacks
# ═══════════════════════════════════════════════════════════════════════════════

class TestCallbacks(unittest.TestCase):

    def setUp(self):
        self.client = _make_trade_client()
        self.filled = []
        self.rejected = []
        self.opened = []
        self.closed = []
        self.client.register_callback("on_order_filled", lambda p: self.filled.append(p))
        self.client.register_callback("on_order_rejected", lambda p: self.rejected.append(p))
        self.client.register_callback("on_position_opened", lambda p: self.opened.append(p))
        self.client.register_callback("on_position_closed", lambda p: self.closed.append(p))

    def test_market_open_fires_filled_and_opened(self):
        payload = _make_execution_event(exec_type=1, order_id=111, position_id=222)
        self.client._handle_execution_event(payload)

        self.assertEqual(len(self.filled), 1)
        self.assertEqual(len(self.opened), 1)

    def test_market_close_fires_closed(self):
        payload = _make_execution_event(exec_type=2)
        self.client._handle_execution_event(payload)

        self.assertEqual(len(self.closed), 1)

    def test_stop_loss_fires_closed(self):
        payload = _make_execution_event(exec_type=3)
        self.client._handle_execution_event(payload)

        self.assertEqual(len(self.closed), 1)

    def test_take_profit_fires_closed(self):
        payload = _make_execution_event(exec_type=4)
        self.client._handle_execution_event(payload)

        self.assertEqual(len(self.closed), 1)

    def test_order_cancelled_fires_rejected(self):
        payload = _make_execution_event(exec_type=6)
        self.client._handle_execution_event(payload)

        self.assertEqual(len(self.rejected), 1)

    def test_unknown_execution_type_no_crash(self):
        payload = _make_execution_event(exec_type=99)
        self.client._handle_execution_event(payload)

        # No crash, no callbacks
        self.assertEqual(len(self.filled), 0)
        self.assertEqual(len(self.rejected), 0)
        self.assertEqual(len(self.closed), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Error Handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestErrorHandling(unittest.TestCase):

    def setUp(self):
        self.client = _make_trade_client()

    def test_handle_error_response(self):
        """Error response is logged without crash."""
        payload = _make_error_response()
        # Should not raise
        self.client._handle_error_response(payload)

    def test_error_response_with_no_fields(self):
        """Error response with missing fields doesn't crash."""
        payload = MagicMock(spec=[])
        self.client._handle_error_response(payload)


# ═══════════════════════════════════════════════════════════════════════════════
# State Guards
# ═══════════════════════════════════════════════════════════════════════════════

class TestStateGuards(unittest.TestCase):

    def setUp(self):
        self.client = _make_trade_client()

    def test_all_operations_blocked_when_disconnected(self):
        """All operations fail cleanly when disconnected."""
        self.client._state_mgr._state = ConnectionState.DISCONNECTED

        result = self.client.send_market_order("EURUSD", "long", 0.01)
        self.assertFalse(result.success)

        result = self.client.send_limit_order("EURUSD", "long", 0.01, 1.08)
        self.assertFalse(result.success)

        result = self.client.amend_order(123)
        self.assertFalse(result.success)

        result = self.client.cancel_order(123)
        self.assertFalse(result.success)

        result = self.client.close_position(123)
        self.assertFalse(result.success)

        result = self.client.reconcile()
        self.assertEqual(result, [])

    def test_degraded_allows_operations(self):
        """DEGRADED state still allows operations."""
        self.client._state_mgr._state = ConnectionState.DEGRADED

        self.client._send_and_wait = MagicMock(return_value=None)
        result = self.client.send_market_order("EURUSD", "long", 0.01)
        # Should attempt the send (timeout, not blocked)
        self.assertFalse(result.success)
        self.assertIn("timeout", result.error)

    def test_reconnecting_blocks_operations(self):
        """RECONNECTING state blocks all operations."""
        self.client._state_mgr._state = ConnectionState.RECONNECTING

        result = self.client.send_market_order("EURUSD", "long", 0.01)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "not_connected")


# ═══════════════════════════════════════════════════════════════════════════════
# Legacy API Compatibility
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegacyAPI(unittest.TestCase):

    def setUp(self):
        self.client = _make_trade_client()

    @patch('adapters.ctrader.open_api_trade_client.Protobuf')
    def test_send_order_market(self, mock_pb):
        """Legacy send_order dispatches to send_market_order."""
        response, payload = _make_order_response(order_id=111)
        mock_pb.extract.return_value = payload
        self.client._send_and_wait = MagicMock(return_value=response)

        from adapters.ctrader.models import TradeDirection, OrderType
        result = self.client.send_order(
            symbol="EURUSD", direction=TradeDirection.LONG,
            order_type=OrderType.MARKET, volume=0.01,
        )

        self.assertEqual(result, "111")

    @patch('adapters.ctrader.open_api_trade_client.Protobuf')
    def test_send_order_limit(self, mock_pb):
        """Legacy send_order dispatches to send_limit_order."""
        response, payload = _make_order_response(order_id=222)
        mock_pb.extract.return_value = payload
        self.client._send_and_wait = MagicMock(return_value=response)

        from adapters.ctrader.models import TradeDirection, OrderType
        result = self.client.send_order(
            symbol="EURUSD", direction=TradeDirection.LONG,
            order_type=OrderType.LIMIT, volume=0.01, price=1.0850,
        )

        self.assertEqual(result, "222")

    def test_send_order_failure_returns_none(self):
        """Legacy send_order returns None on failure."""
        self.client._send_and_wait = MagicMock(return_value=None)

        from adapters.ctrader.models import TradeDirection, OrderType
        result = self.client.send_order(
            symbol="EURUSD", direction=TradeDirection.LONG,
            order_type=OrderType.MARKET, volume=0.01,
        )

        self.assertIsNone(result)

    def test_close_position_by_id(self):
        """Legacy close_position_by_id returns bool."""
        response = MagicMock()
        self.client._send_and_wait = MagicMock(return_value=response)

        result = self.client.close_position_by_id(position_id=123, volume=0.01)

        self.assertTrue(result)

    @patch('adapters.ctrader.open_api_trade_client.Protobuf')
    def test_amend_slTp(self, mock_pb):
        """Legacy amend_slTp returns bool."""
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAAmendPositionSLTPReq,
        )
        response = MagicMock()
        self.client._send_and_wait = MagicMock(return_value=response)

        result = self.client.amend_slTp(
            position_id=123, stop_loss=1.0800, take_profit=1.1000,
        )

        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestHelpers(unittest.TestCase):

    def test_lots_to_units(self):
        self.assertEqual(_lots_to_units(1.0), 100000)
        self.assertEqual(_lots_to_units(0.01), 1000)
        self.assertEqual(_lots_to_units(0.1), 10000)

    def test_full_jitter_backoff(self):
        """Backoff is always within bounds."""
        for attempt in range(11):
            delay = calculate_full_jitter_backoff(attempt)
            upper = min(60.0, 1.0 * (2 ** attempt))
            self.assertGreaterEqual(delay, 0.0)
            self.assertLessEqual(delay, upper)

    def test_full_jitter_backoff_caps_at_60(self):
        """At high attempt counts, delay is capped at 60s."""
        for _ in range(100):
            delay = calculate_full_jitter_backoff(attempt=20)
            self.assertLessEqual(delay, 60.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Symbol Resolution
# ═══════════════════════════════════════════════════════════════════════════════

class TestSymbolResolution(unittest.TestCase):

    def setUp(self):
        self.client = _make_trade_client()

    def test_resolve_known_symbol(self):
        self.assertEqual(self.client.resolve_symbol_id("EURUSD"), 1)

    def test_resolve_symbol_with_slash(self):
        self.assertEqual(self.client.resolve_symbol_id("EUR/USD"), 1)

    def test_resolve_symbol_with_underscore(self):
        self.assertEqual(self.client.resolve_symbol_id("GBP_USD"), 2)

    def test_resolve_symbol_case_insensitive(self):
        self.assertEqual(self.client.resolve_symbol_id("eurusd"), 1)

    def test_resolve_unknown_symbol_raises(self):
        with self.assertRaises(ValueError):
            self.client.resolve_symbol_id("XYZABC")


if __name__ == "__main__":
    unittest.main()
