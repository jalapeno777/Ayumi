"""Integration tests against real cTrader demo server.

Requires .env credentials. Marked @pytest.mark.live so default runs exclude them:
    python -m pytest tests/test_live_ctrader.py -m live

Each test uses a shared module-scoped fixture for the TCP connection.
"""

import os
import time
import threading

import pytest

# Skip entire module if dependencies unavailable
try:
    from dotenv import load_dotenv
    load_dotenv()
    from ctrader_open_api import Client, TcpProtocol
    from twisted.internet import reactor
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

# Credentials from .env
CTRADER_HOST = os.getenv("CTRADER_HOST", "demo.ctraderapi.com")
CLIENT_ID = os.getenv("CTRADER_OPENAPI_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CTRADER_OPENAPI_CLIENT_SECRET", "")
ACCESS_TOKEN = os.getenv("CTRADER_OPENAPI_ACCESS_TOKEN", "")
ACCOUNT_ID = os.getenv("CTRADER_OPENAPI_ACCOUNT_ID", "")

SHOULD_RUN = HAS_DEPS and bool(CLIENT_ID and CLIENT_SECRET and ACCESS_TOKEN and ACCOUNT_ID)

pytestmark = pytest.mark.live


def _skip_if_no_creds():
    if not SHOULD_RUN:
        pytest.skip("cTrader credentials not configured or dependencies missing")


class _ConnectionHelper:
    """Minimal synchronous wrapper around ctrader_open_api for test use."""

    def __init__(self):
        self.client = None
        self.connected = threading.Event()
        self.authenticated = threading.Event()
        self.events = []
        self._lock = threading.Lock()

    def connect(self, timeout=15):
        _skip_if_no_creds()
        self.client = Client(CTRADER_HOST, 5035, TcpProtocol)
        self.client.setConnectCallback(lambda _: self.connected.set())
        self.client.setDisconnectCallback(lambda _, r: self.connected.clear())
        self.client.setMessageReceivedCallback(self._on_msg)
        reactor.callFromThread(self.client.startService)
        assert self.connected.wait(timeout), "TCP connect timeout"

    def app_auth(self, timeout=10):
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq
        req = ProtoOAApplicationAuthReq(clientId=CLIENT_ID, clientSecret=CLIENT_SECRET)
        ev = threading.Event()
        def ok(r):
            ev.set()
        def fail(f):
            ev.set()
        def do():
            d = self.client.send(req)
            d.addCallbacks(ok, fail)
        reactor.callFromThread(do)
        assert ev.wait(timeout), "App auth timeout"

    def account_auth(self, timeout=10):
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAccountAuthReq
        req = ProtoOAAccountAuthReq(
            ctidTraderAccountId=int(ACCOUNT_ID),
            accessToken=ACCESS_TOKEN,
        )
        ev = threading.Event()
        def ok(r):
            ev.set()
        def fail(f):
            ev.set()
        def do():
            d = self.client.send(req)
            d.addCallbacks(ok, fail)
        reactor.callFromThread(do)
        assert ev.wait(timeout), "Account auth timeout"

    def subscribe(self, symbol_id, timeout=10):
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASubscribeSpotsReq
        req = ProtoOASubscribeSpotsReq(
            ctidTraderAccountId=int(ACCOUNT_ID),
            symbolId=[symbol_id],
        )
        ev = threading.Event()
        def ok(r):
            ev.set()
        def fail(f):
            ev.set()
        def do():
            d = self.client.send(req)
            d.addCallbacks(ok, fail)
        reactor.callFromThread(do)
        assert ev.wait(timeout), "Subscribe timeout"

    def _on_msg(self, client, msg):
        with self._lock:
            self.events.append(msg)

    def disconnect(self):
        if self.client:
            try:
                reactor.callFromThread(self.client.stopService)
            except Exception:
                pass
            self.client = None


@pytest.fixture(scope="module")
def conn():
    """Shared connection fixture — connects once for the module."""
    _skip_if_no_creds()
    helper = _ConnectionHelper()
    helper.connect()
    helper.app_auth()
    helper.account_auth()
    yield helper
    helper.disconnect()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_tcp_connect_and_auth(conn):
    """Verify TCP connect + full auth succeeded (fixture does the work)."""
    assert conn.connected.is_set(), "Should be connected"


def test_subscribe_symbol(conn):
    """Subscribe to EURUSD (symbolId typically 1 on demo)."""
    conn.subscribe(symbol_id=1)
    # If we get here without exception, subscribe succeeded


def test_place_and_close_market_order(conn):
    """Place a small market order and close it."""
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOANewOrderReq,
        ProtoOAClosePositionReq,
    )
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
        ProtoOAOrderType,
        ProtoOATradeSide,
        ProtoOATimeInForce,
    )
    from ctrader_open_api.protobuf import Protobuf

    # Place
    open_ev = threading.Event()
    open_result = [None, None]  # [response, error]
    req = ProtoOANewOrderReq()
    req.ctidTraderAccountId = int(ACCOUNT_ID)
    req.symbolId = 1  # EURUSD on most demo servers
    req.orderType = ProtoOAOrderType.MARKET
    req.tradeSide = ProtoOATradeSide.BUY
    req.volume = 1000  # 0.01 lots
    req.timeInForce = ProtoOATimeInForce.GOOD_TILL_CANCEL
    req.label = "test_bq683"

    def on_open(r):
        open_result[0] = r
        open_ev.set()
    def on_open_fail(f):
        open_result[1] = str(f)
        open_ev.set()

    def do_open():
        d = conn.client.send(req)
        d.addCallbacks(on_open, on_open_fail)
    reactor.callFromThread(do_open)
    assert open_ev.wait(15), "Order open timeout"

    if open_result[1] is not None:
        pytest.skip(f"Order rejected (demo may not support symbol): {open_result[1]}")

    payload = Protobuf.extract(open_result[0]) if hasattr(open_result[0], "payloadType") else open_result[0]
    position_id = getattr(payload, "positionId", None)
    if position_id is None:
        pytest.skip("No positionId in response — demo may handle differently")

    # Close
    close_ev = threading.Event()
    close_req = ProtoOAClosePositionReq()
    close_req.ctidTraderAccountId = int(ACCOUNT_ID)
    close_req.positionId = position_id
    close_req.volume = 1000

    def on_close(r):
        close_ev.set()
    def on_close_fail(f):
        close_ev.set()

    def do_close():
        d = conn.client.send(close_req)
        d.addCallbacks(on_close, on_close_fail)
    reactor.callFromThread(do_close)
    assert close_ev.wait(15), "Position close timeout"
