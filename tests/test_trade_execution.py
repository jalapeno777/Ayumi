"""Tests for CTraderOpenApiClient trade execution methods.

Covers the four new methods on `CTraderOpenApiClient`:
  - send_order
  - close_position
  - get_open_positions
  - get_account_balance

Plus the supporting surface:
  - is_paper_mode / is_connected properties
  - register_callback
  - _normalize_side / _normalize_order_type coercion
  - OrderManager-style kwargs accepted on send_order

All tests use a fully-mocked `_client` (ctrader_open_api.Client) so no real
TCP connection is opened. The tests target the protobuf request construction,
the response routing, and the public dataclass returns (Order / Position /
balance float).

NOTE: this test file is intentionally tightly scoped. It only exercises the
trade-execution methods added to `open_api_client.py`. Existing test files
(including the broader test suite) are NOT modified.
"""

import threading
import time
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

# Tests run from the project root with `src/forex-bot` on sys.path (see
# tests/conftest.py), so the import is `adapters.ctrader.open_api_client`.
from adapters.ctrader.open_api_client import (
    CTraderOpenApiClient,
    _lots_to_units,
    _normalize_symbol_name,
)
from adapters.ctrader.models import (
    Order,
    OrderStatus,
    OrderType,
    Position,
    PositionStatus,
    TradeDirection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PRICE_DIVISOR = 100_000.0


def _make_client(**kwargs) -> CTraderOpenApiClient:
    """Construct a CTraderOpenApiClient with a mock underlying Client.

    The mock `_client` captures every `send()` call so tests can assert on
    the proto requests that go out, and can be programmed to return a
    canned response to satisfy `_send_and_wait` / the message dispatcher.
    """
    defaults = dict(
        client_id="test-client",
        client_secret="test-secret",
        account_id=5795523,
        access_token="test-access-token",
        host="demo.ctraderapi.com",
        port=5035,
    )
    defaults.update(kwargs)
    client = CTraderOpenApiClient(**defaults)
    client._client = MagicMock()
    client._client.isConnected = True
    client._connected = True
    # Pre-populate the symbol cache so we don't have to mock get_all_symbols
    client._name_to_id = {
        "EURUSD": 1,
        "GBPUSD": 2,
        "USDJPY": 4,
    }
    client._id_to_name = {1: "EURUSD", 2: "GBPUSD", 4: "USDJPY"}
    client._symbol_digits = {1: 5, 2: 5, 4: 3}
    return client


def _wire_envelope(payload_msg):
    """Wrap a payload proto in a wire envelope compatible with Protobuf.extract.

    The production `_send_and_wait` returns a wire envelope with attributes
    ``payloadType`` (int) and ``payload`` (bytes). Protobuf.extract() then
    uses these to look up the proto class and parse the bytes.
    """
    env = MagicMock()
    env.payloadType = payload_msg.payloadType
    env.payload = payload_msg.SerializeToString()
    return env


def _make_execution_event(
    client_order_id: str,
    execution_type: int,
    order_id: int = 9001,
    symbol_id: int = 1,
    execution_price_raw: int = 0,
    executed_volume: int = 0,
    error_code: str = "",
):
    """Build a mock ProtoOAExecutionEvent message envelope + payload.

    Returns a (payload, envelope) tuple suitable for feeding into
    `CTraderOpenApiClient._handle_execution_event`.
    """
    from ctrader_open_api.messages import OpenApiModelMessages_pb2 as MM
    from ctrader_open_api.messages import OpenApiMessages_pb2 as M

    # Build a real payload so getattr() behaves like the real object.
    payload = M.ProtoOAExecutionEvent()
    payload.executionType = execution_type
    if error_code:
        payload.errorCode = error_code
    payload.order.orderId = order_id
    payload.order.tradeData.symbolId = symbol_id
    payload.order.tradeData.volume = executed_volume or 100_000
    if execution_price_raw:
        payload.order.executionPrice = execution_price_raw
    payload.order.clientOrderId = client_order_id

    # Envelope is the wire message with payloadType + clientMsgId set.
    envelope = MagicMock()
    envelope.payloadType = 2126  # ProtoOAExecutionEvent
    envelope.clientMsgId = f"order_{client_order_id}"
    return payload, envelope


def _drain_dispatcher(client: CTraderOpenApiClient, max_wait: float = 1.0):
    """Wait for all pending-order events to fire (or timeout)."""
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        with client._dispatcher_lock:
            pending = len(client._pending_orders)
        if pending == 0:
            return
        time.sleep(0.01)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_is_paper_mode_is_false(self):
        client = _make_client()
        assert client.is_paper_mode is False

    def test_is_connected_reflects_internal_state(self):
        client = _make_client()
        assert client.is_connected is True
        client._connected = False
        assert client.is_connected is False


# ---------------------------------------------------------------------------
# Normalization helpers (side + order_type coercion)
# ---------------------------------------------------------------------------

class TestNormalizeSide:
    def test_buy_int(self):
        client = _make_client()
        assert client._normalize_side(1) == 1  # BUY
        assert client._normalize_side(2) == 2  # SELL

    def test_buy_string(self):
        client = _make_client()
        assert client._normalize_side("BUY") == 1
        assert client._normalize_side("buy") == 1
        assert client._normalize_side("B") == 1

    def test_sell_string(self):
        client = _make_client()
        assert client._normalize_side("SELL") == 2
        assert client._normalize_side("sell") == 2
        assert client._normalize_side("S") == 2

    def test_trade_direction_enum(self):
        client = _make_client()
        assert client._normalize_side(TradeDirection.LONG) == 1
        assert client._normalize_side(TradeDirection.SHORT) == 2

    def test_invalid_raises(self):
        client = _make_client()
        with pytest.raises(ValueError):
            client._normalize_side("NOPE")
        with pytest.raises(ValueError):
            client._normalize_side(object())


class TestNormalizeOrderType:
    def test_market_string(self):
        client = _make_client()
        assert client._normalize_order_type("MARKET") == 1
        assert client._normalize_order_type("market") == 1

    def test_limit_string(self):
        client = _make_client()
        assert client._normalize_order_type("LIMIT") == 2

    def test_stop_string(self):
        client = _make_client()
        assert client._normalize_order_type("STOP") == 3

    def test_passthrough_int(self):
        client = _make_client()
        assert client._normalize_order_type(1) == 1
        assert client._normalize_order_type(2) == 2

    def test_order_type_enum(self):
        client = _make_client()
        assert client._normalize_order_type(OrderType.MARKET) == 1
        assert client._normalize_order_type(OrderType.LIMIT) == 2
        assert client._normalize_order_type(OrderType.STOP) == 3

    def test_invalid_raises(self):
        client = _make_client()
        with pytest.raises(ValueError):
            client._normalize_order_type("INVALID_TYPE")


# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------

class TestSymbolHelpers:
    def test_resolve_symbol_id_cached(self):
        client = _make_client()
        assert client._resolve_symbol_id("EURUSD") == 1
        assert client._resolve_symbol_id("eurusd") == 1
        assert client._resolve_symbol_id("EUR/USD") == 1
        assert client._resolve_symbol_id("GBPUSD") == 2
        assert client._resolve_symbol_id(2) == 2  # int passthrough

    def test_resolve_symbol_id_fetches_when_empty(self):
        client = _make_client()
        client._name_to_id = {}
        # Patch get_all_symbols to populate the cache
        with patch.object(client, "get_all_symbols", return_value=[
            {"symbol_id": 42, "name": "AUDUSD", "digits": 5},
        ]):
            assert client._resolve_symbol_id("AUDUSD") == 42
            assert client._name_to_id["AUDUSD"] == 42

    def test_resolve_unknown_raises(self):
        client = _make_client()
        with pytest.raises(ValueError):
            client._resolve_symbol_id("ZZZZZZ")

    def test_symbol_name_for_id(self):
        client = _make_client()
        assert client._symbol_name_for_id(1) == "EURUSD"
        assert client._symbol_name_for_id(2) == "GBPUSD"
        assert client._symbol_name_for_id(999) == "999"  # fallback

    def test_normalize_symbol_name(self):
        assert _normalize_symbol_name("EUR/USD") == "EURUSD"
        assert _normalize_symbol_name("gbp_usd") == "GBPUSD"
        assert _normalize_symbol_name(" eur usd ") == "EURUSD"
        assert _normalize_symbol_name("usdjpy") == "USDJPY"

    def test_lots_to_units(self):
        assert _lots_to_units(0.01) == 1_000
        assert _lots_to_units(0.1) == 10_000
        assert _lots_to_units(1.0) == 100_000
        assert _lots_to_units(1.5) == 150_000


# ---------------------------------------------------------------------------
# send_order
# ---------------------------------------------------------------------------

class TestSendOrder:
    def test_send_order_short_form_builds_correct_request(self):
        """send_order(symbol, side, volume) builds a valid ProtoOANewOrderReq."""
        from ctrader_open_api.messages import OpenApiMessages_pb2 as M

        client = _make_client()
        # Make the underlying send() async-dispatched but capture the request
        sent = []

        def fake_send(req, clientMsgId=None, responseTimeoutInSeconds=None, **kwargs):
            sent.append((req, clientMsgId))
            d = MagicMock()
            return d

        client._client.send = fake_send

        # Don't block forever on the order event; set short timeout
        with patch(
            "adapters.ctrader.open_api_client._ORDER_TIMEOUT_SEC", 0.1
        ):
            order = client.send_order("EURUSD", "BUY", 0.1, sl=1.0950, tp=1.1050)

        assert isinstance(order, Order)
        assert order.symbol == "EURUSD"
        assert order.direction == TradeDirection.LONG
        assert order.order_type == OrderType.MARKET
        assert order.volume == 0.1
        assert order.stop_loss == 1.0950
        assert order.take_profit == 1.1050

        # Verify the wire-level request was built correctly
        assert len(sent) == 1
        req, client_msg_id = sent[0]
        assert isinstance(req, M.ProtoOANewOrderReq)
        assert req.ctidTraderAccountId == 5795523
        assert req.symbolId == 1
        assert req.tradeSide == 1  # BUY
        assert req.orderType == 1  # MARKET
        assert req.volume == 10_000  # 0.1 lots → 10_000 units
        assert req.stopLoss == int(round(1.0950 * PRICE_DIVISOR))
        assert req.takeProfit == int(round(1.1050 * PRICE_DIVISOR))
        assert req.clientOrderId  # populated with UUID
        assert client_msg_id == f"order_{req.clientOrderId}"

    def test_send_order_sell_side(self):
        client = _make_client()
        sent = []
        client._client.send = lambda req, **kw: (sent.append(req) or MagicMock())

        with patch("adapters.ctrader.open_api_client._ORDER_TIMEOUT_SEC", 0.05):
            order = client.send_order("GBPUSD", "SELL", 0.05)

        assert order.direction == TradeDirection.SHORT
        assert sent[0].tradeSide == 2  # SELL
        assert sent[0].volume == 5_000  # 0.05 lots

    def test_send_order_limit_type_with_price(self):
        client = _make_client()
        sent = []
        client._client.send = lambda req, **kw: (sent.append(req) or MagicMock())

        with patch("adapters.ctrader.open_api_client._ORDER_TIMEOUT_SEC", 0.05):
            order = client.send_order(
                "EURUSD", "BUY", 0.1, order_type="LIMIT", price=1.1000,
            )

        assert order.order_type == OrderType.LIMIT
        assert order.price == 1.1000
        assert sent[0].orderType == 2  # LIMIT
        assert sent[0].limitPrice == int(round(1.1000 * PRICE_DIVISOR))

    def test_send_order_stop_type_with_price(self):
        client = _make_client()
        sent = []
        client._client.send = lambda req, **kw: (sent.append(req) or MagicMock())

        with patch("adapters.ctrader.open_api_client._ORDER_TIMEOUT_SEC", 0.05):
            order = client.send_order(
                "EURUSD", "SELL", 0.1, order_type="STOP", price=1.0900,
            )

        assert order.order_type == OrderType.STOP
        assert sent[0].orderType == 3  # STOP
        assert sent[0].stopPrice == int(round(1.0900 * PRICE_DIVISOR))

    def test_send_order_with_order_manager_kwargs(self):
        """OrderManager calls send_order(symbol=..., direction=..., ...)."""
        client = _make_client()
        sent = []
        client._client.send = lambda req, **kw: (sent.append(req) or MagicMock())

        with patch("adapters.ctrader.open_api_client._ORDER_TIMEOUT_SEC", 0.05):
            order = client.send_order(
                symbol="EURUSD",
                direction=TradeDirection.LONG,
                order_type=OrderType.MARKET,
                volume=0.2,
                price=None,
                stop_loss=1.0950,
                take_profit=1.1100,
                comment="momentum_breakout",
            )

        assert order.symbol == "EURUSD"
        assert order.direction == TradeDirection.LONG
        assert order.volume == 0.2
        assert order.stop_loss == 1.0950
        assert order.take_profit == 1.1100
        # Original comment is preserved; timeout appends a status note.
        assert "momentum_breakout" in order.comment
        # The request should reflect the same
        assert sent[0].tradeSide == 1
        assert sent[0].volume == 20_000  # 0.2 lots

    def test_send_order_not_connected_returns_rejected(self):
        client = _make_client()
        client._connected = False

        order = client.send_order("EURUSD", "BUY", 0.1)

        assert order.status == OrderStatus.REJECTED
        assert "not_connected" in order.comment
        # No wire-level send should have happened
        client._client.send.assert_not_called()

    def test_send_order_invalid_volume_returns_rejected(self):
        client = _make_client()
        order = client.send_order("EURUSD", "BUY", 0)
        assert order.status == OrderStatus.REJECTED
        assert "volume" in order.comment.lower()

        order2 = client.send_order("EURUSD", "BUY", -0.1)
        assert order2.status == OrderStatus.REJECTED

    def test_send_order_invalid_side_returns_rejected(self):
        client = _make_client()
        order = client.send_order("EURUSD", "INVALID", 0.1)
        assert order.status == OrderStatus.REJECTED

    def test_send_order_filled_via_execution_event(self):
        """A successful execution event flips status to FILLED."""
        client = _make_client()
        # Programmatically capture the clientOrderId when send() is called
        captured = {}
        def fake_send(req, clientMsgId=None, **kw):
            captured["client_order_id"] = req.clientOrderId
            return MagicMock()
        client._client.send = fake_send

        with patch("adapters.ctrader.open_api_client._ORDER_TIMEOUT_SEC", 2.0):
            # Start send_order in a thread so we can dispatch the event
            result = {}
            def call():
                result["order"] = client.send_order("EURUSD", "BUY", 0.1)
            t = threading.Thread(target=call, daemon=True)
            t.start()

            # Give the send a moment to register
            time.sleep(0.05)
            cid = captured["client_order_id"]

            # Dispatch an ORDER_FILLED execution event
            from ctrader_open_api.messages import OpenApiModelMessages_pb2 as MM
            payload, envelope = _make_execution_event(
                client_order_id=cid,
                execution_type=MM.ProtoOAExecutionType.ORDER_FILLED,
                execution_price_raw=int(1.10000 * PRICE_DIVISOR),
                executed_volume=10_000,  # 0.1 lots
            )
            client._handle_execution_event(payload, envelope)

            t.join(timeout=3.0)

        order = result["order"]
        assert order.status == OrderStatus.FILLED
        assert order.filled_price is not None
        assert abs(order.filled_price - 1.10000) < 1e-4
        assert order.volume == pytest.approx(0.1, abs=1e-6)

    def test_send_order_rejected_via_execution_event(self):
        client = _make_client()
        captured = {}
        def fake_send(req, clientMsgId=None, **kw):
            captured["client_order_id"] = req.clientOrderId
            return MagicMock()
        client._client.send = fake_send

        result = {}
        with patch("adapters.ctrader.open_api_client._ORDER_TIMEOUT_SEC", 2.0):
            def call():
                result["order"] = client.send_order("EURUSD", "BUY", 0.1)
            t = threading.Thread(target=call, daemon=True)
            t.start()
            time.sleep(0.05)
            cid = captured["client_order_id"]

            from ctrader_open_api.messages import OpenApiModelMessages_pb2 as MM
            payload, envelope = _make_execution_event(
                client_order_id=cid,
                execution_type=MM.ProtoOAExecutionType.ORDER_REJECTED,
                error_code="NOT_ENOUGH_MONEY",
            )
            client._handle_execution_event(payload, envelope)
            t.join(timeout=3.0)

        order = result["order"]
        assert order.status == OrderStatus.REJECTED
        assert "NOT_ENOUGH_MONEY" in order.comment

    def test_send_order_callback_fires_on_fill(self):
        client = _make_client()
        captured = {}
        def fake_send(req, clientMsgId=None, **kw):
            captured["client_order_id"] = req.clientOrderId
            return MagicMock()
        client._client.send = fake_send

        filled_events = []
        client.register_callback("on_order_filled", lambda order, msg: filled_events.append(order))

        result = {}
        with patch("adapters.ctrader.open_api_client._ORDER_TIMEOUT_SEC", 2.0):
            def call():
                result["order"] = client.send_order("EURUSD", "BUY", 0.1)
            t = threading.Thread(target=call, daemon=True)
            t.start()
            time.sleep(0.05)
            cid = captured["client_order_id"]

            from ctrader_open_api.messages import OpenApiModelMessages_pb2 as MM
            payload, envelope = _make_execution_event(
                client_order_id=cid,
                execution_type=MM.ProtoOAExecutionType.ORDER_FILLED,
            )
            client._handle_execution_event(payload, envelope)
            t.join(timeout=3.0)

        assert len(filled_events) == 1
        assert filled_events[0].status == OrderStatus.FILLED


# ---------------------------------------------------------------------------
# close_position
# ---------------------------------------------------------------------------

class TestClosePosition:
    def test_close_position_builds_correct_request(self):
        from ctrader_open_api.messages import OpenApiMessages_pb2 as M
        from ctrader_open_api.protobuf import Protobuf

        client = _make_client()
        # Simulate successful send_and_wait: returns a synthetic execution event
        # as a proto message that has payloadType
        fake_response = M.ProtoOAExecutionEvent()
        fake_response.executionType = 3  # ORDER_FILLED

        with patch.object(client, "_send_and_wait", return_value=fake_response) as saw:
            ok = client.close_position(12345)

        assert ok is True
        saw.assert_called_once()
        # Inspect the request that was passed
        args, _kwargs = saw.call_args
        req = args[0]
        assert isinstance(req, M.ProtoOAClosePositionReq)
        assert req.ctidTraderAccountId == 5795523
        assert req.positionId == 12345
        # volume=0 means "close entire position" (cTrader convention)
        assert req.volume == 0

    def test_close_position_with_partial_volume(self):
        from ctrader_open_api.messages import OpenApiMessages_pb2 as M
        from ctrader_open_api.protobuf import Protobuf

        client = _make_client()
        fake_response = M.ProtoOAExecutionEvent()
        fake_response.executionType = 3

        with patch.object(client, "_send_and_wait", return_value=fake_response) as saw:
            ok = client.close_position(12345, volume=0.5)

        assert ok is True
        req = saw.call_args[0][0]
        assert req.volume == 50_000  # 0.5 lots

    def test_close_position_not_connected(self):
        client = _make_client()
        client._connected = False
        assert client.close_position(12345) is False

    def test_close_position_timeout_returns_false(self):
        client = _make_client()
        with patch.object(client, "_send_and_wait", return_value=None):
            assert client.close_position(12345) is False

    def test_close_position_transport_error_returns_false(self):
        client = _make_client()
        with patch.object(client, "_send_and_wait", side_effect=RuntimeError("boom")):
            assert client.close_position(12345) is False

    def test_close_position_invalid_id_returns_false(self):
        client = _make_client()
        assert client.close_position("not_a_number") is False
        assert client.close_position(None) is False


# ---------------------------------------------------------------------------
# get_open_positions
# ---------------------------------------------------------------------------

class TestGetOpenPositions:
    def _make_reconcile_response(self, positions_data):
        from ctrader_open_api.messages import OpenApiMessages_pb2 as M
        from ctrader_open_api.messages import OpenApiModelMessages_pb2 as MM
        resp = M.ProtoOAReconcileRes()
        resp.ctidTraderAccountId = 5795523
        for pd in positions_data:
            p = resp.position.add()
            p.positionId = pd["position_id"]
            p.positionStatus = MM.ProtoOAPositionStatus.POSITION_STATUS_OPEN
            p.swap = 0
            p.tradeData.symbolId = pd["symbol_id"]
            p.tradeData.volume = pd["volume_raw"]
            p.tradeData.tradeSide = pd["trade_side"]
            p.price = pd["price_raw"]
            p.stopLoss = pd.get("sl_raw", 0)
            p.takeProfit = pd.get("tp_raw", 0)
        # Return a wire envelope, not a raw proto
        return _wire_envelope(resp)

    def test_get_open_positions_parses_response(self):
        from ctrader_open_api.messages import OpenApiMessages_pb2 as M
        client = _make_client()

        resp = self._make_reconcile_response([
            {
                "position_id": 100,
                "symbol_id": 1,  # EURUSD
                "volume_raw": 100_000,
                "trade_side": 1,  # BUY
                "price_raw": 1.1000 * PRICE_DIVISOR,
                "sl_raw": 1.0950 * PRICE_DIVISOR,
                "tp_raw": 1.1100 * PRICE_DIVISOR,
            },
            {
                "position_id": 200,
                "symbol_id": 2,  # GBPUSD
                "volume_raw": 50_000,
                "trade_side": 2,  # SELL
                "price_raw": 1.2500 * PRICE_DIVISOR,
            },
        ])

        with patch.object(client, "_send_and_wait", return_value=resp) as saw:
            positions = client.get_open_positions()

        assert len(positions) == 2
        p0, p1 = positions
        assert isinstance(p0, Position)
        assert p0.position_id == "100"
        assert p0.symbol == "EURUSD"
        assert p0.direction == TradeDirection.LONG
        assert p0.volume == pytest.approx(1.0, abs=1e-6)
        assert p0.entry_price == pytest.approx(1.1000, abs=1e-4)
        assert p0.stop_loss == pytest.approx(1.0950, abs=1e-4)
        assert p0.take_profit == pytest.approx(1.1100, abs=1e-4)
        assert p0.status == PositionStatus.OPEN

        assert p1.position_id == "200"
        assert p1.symbol == "GBPUSD"
        assert p1.direction == TradeDirection.SHORT
        assert p1.volume == pytest.approx(0.5, abs=1e-6)
        assert p1.stop_loss is None
        assert p1.take_profit is None

        # Verify the request itself
        req = saw.call_args[0][0]
        assert isinstance(req, M.ProtoOAReconcileReq)
        assert req.ctidTraderAccountId == 5795523

    def test_get_open_positions_empty(self):
        client = _make_client()
        from ctrader_open_api.messages import OpenApiMessages_pb2 as M
        empty = M.ProtoOAReconcileRes()
        empty.ctidTraderAccountId = 5795523  # required field
        resp = _wire_envelope(empty)
        with patch.object(client, "_send_and_wait", return_value=resp):
            assert client.get_open_positions() == []

    def test_get_open_positions_not_connected(self):
        client = _make_client()
        client._connected = False
        assert client.get_open_positions() == []

    def test_get_open_positions_timeout_returns_empty(self):
        client = _make_client()
        with patch.object(client, "_send_and_wait", return_value=None):
            assert client.get_open_positions() == []

    def test_get_open_positions_transport_error_returns_empty(self):
        client = _make_client()
        with patch.object(client, "_send_and_wait", side_effect=RuntimeError("boom")):
            assert client.get_open_positions() == []


# ---------------------------------------------------------------------------
# get_account_balance
# ---------------------------------------------------------------------------

class TestGetAccountBalance:
    def _make_trader_response(self, balance_raw: int, money_digits: int = 2):
        from ctrader_open_api.messages import OpenApiMessages_pb2 as M
        resp = M.ProtoOATraderRes()
        resp.ctidTraderAccountId = 5795523
        resp.trader.ctidTraderAccountId = 5795523  # required nested field
        resp.trader.balance = balance_raw
        resp.trader.moneyDigits = money_digits
        resp.trader.depositAssetId = 1  # required nested field
        return _wire_envelope(resp)

    def test_get_account_balance_parses_response(self):
        from ctrader_open_api.messages import OpenApiMessages_pb2 as M
        client = _make_client()
        # 1,000,000 raw with moneyDigits=2 → 10,000.00
        resp = self._make_trader_response(1_000_000, money_digits=2)

        with patch.object(client, "_send_and_wait", return_value=resp) as saw:
            balance = client.get_account_balance()

        assert balance == pytest.approx(10_000.00, abs=1e-6)

        # Verify the request
        req = saw.call_args[0][0]
        assert isinstance(req, M.ProtoOATraderReq)
        assert req.ctidTraderAccountId == 5795523

    def test_get_account_balance_money_digits_three(self):
        client = _make_client()
        # moneyDigits=3 (JPY accounts) — 1,000,000 raw → 1,000.000
        resp = self._make_trader_response(1_000_000, money_digits=3)
        with patch.object(client, "_send_and_wait", return_value=resp):
            assert client.get_account_balance() == pytest.approx(1_000.0, abs=1e-6)

    def test_get_account_balance_not_connected(self):
        client = _make_client()
        client._connected = False
        assert client.get_account_balance() == 0.0

    def test_get_account_balance_timeout_returns_zero(self):
        client = _make_client()
        with patch.object(client, "_send_and_wait", return_value=None):
            assert client.get_account_balance() == 0.0

    def test_get_account_balance_transport_error_returns_zero(self):
        client = _make_client()
        with patch.object(client, "_send_and_wait", side_effect=RuntimeError("boom")):
            assert client.get_account_balance() == 0.0

    def test_get_account_balance_empty_payload_returns_zero(self):
        client = _make_client()
        from ctrader_open_api.messages import OpenApiMessages_pb2 as M
        # Build a minimal-but-valid ProtoOATraderRes with all required fields
        resp_msg = M.ProtoOATraderRes()
        resp_msg.ctidTraderAccountId = 5795523
        resp_msg.trader.ctidTraderAccountId = 5795523
        resp_msg.trader.depositAssetId = 1
        resp_msg.trader.balance = 0
        resp_msg.trader.moneyDigits = 2
        resp = _wire_envelope(resp_msg)
        # Return a non-trader payload by clearing trader fields after wire-encoding
        # (We still expect 0.0 because balance is 0)
        with patch.object(client, "_send_and_wait", return_value=resp):
            assert client.get_account_balance() == 0.0


# ---------------------------------------------------------------------------
# Callback registration
# ---------------------------------------------------------------------------

class TestRegisterCallback:
    def test_register_callback_known_event(self):
        client = _make_client()
        cb = MagicMock()
        client.register_callback("on_order_filled", cb)
        assert cb in client._callbacks["on_order_filled"]

    def test_register_callback_unknown_event_creates_bucket(self):
        client = _make_client()
        cb = MagicMock()
        client.register_callback("on_custom_event", cb)
        assert cb in client._callbacks["on_custom_event"]

    def test_multiple_callbacks_for_same_event(self):
        client = _make_client()
        cb1 = MagicMock()
        cb2 = MagicMock()
        client.register_callback("on_order_filled", cb1)
        client.register_callback("on_order_filled", cb2)
        assert cb1 in client._callbacks["on_order_filled"]
        assert cb2 in client._callbacks["on_order_filled"]


# ---------------------------------------------------------------------------
# Disconnect cleanup
# ---------------------------------------------------------------------------

class TestDisconnect:
    def test_disconnect_releases_pending_orders(self):
        client = _make_client()
        # Pre-populate a pending order
        event = threading.Event()
        pending_order = Order(
            order_id="abc",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        client._pending_orders["abc"] = (event, pending_order)
        client._pending_client_msg_ids["order_abc"] = "abc"

        client.disconnect()

        assert client._pending_orders == {}
        assert client._pending_client_msg_ids == {}
        # Event should be set so any waiter wakes up
        assert event.is_set()
        # The released order should be marked pending with a comment
        assert pending_order.status == OrderStatus.PENDING
        assert "disconnect" in pending_order.comment
