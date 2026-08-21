"""Tests for cTraderSession — TCP connection lifecycle with reactor bridge.

All network / SDK calls are mocked. No real cTrader connection is made.

Reactor bridge pattern (Amendment A1):
    caller thread → reactor.callFromThread(do_send) → event.wait()
    reactor thread → client.send() → deferred.addCallbacks → event.set()
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
from adapters.ctrader.protocols import SessionState
from adapters.ctrader.session import SendError, cTraderSession

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_mock_credentials():
    """Return a MagicMock credential store with canned values."""
    store = MagicMock()
    store.get.return_value = MagicMock(
        client_id="test_client",
        client_secret="test_secret",  # noqa: S106
        access_token="test_token",  # noqa: S106
        refresh_token="test_refresh",  # noqa: S106
        account_id=5795523,
        trader_login=5795523,
    )
    return store


def _make_mock_token_lifecycle():
    """Return a MagicMock token lifecycle."""
    tl = MagicMock()
    tl.ensure_valid.return_value = "valid_access_token"
    return tl


def _make_mock_deferred(result=None, error=None):
    """Create a mock Twisted Deferred that fires immediately.

    When addCallbacks(success_cb, error_cb) is called:
    - If *error* is set: error_cb is called with *error*
    - Otherwise: success_cb is called with *result*
    """
    deferred = MagicMock()

    def fake_add_callbacks(cb, eb):
        if error is not None:
            eb(error)
        else:
            cb(result)

    deferred.addCallbacks.side_effect = fake_add_callbacks
    return deferred


def _make_session(**kwargs):
    """Build a cTraderSession with mocked dependencies."""
    store = kwargs.pop("credential_store", _make_mock_credentials())
    tl = kwargs.pop("token_lifecycle", _make_mock_token_lifecycle())
    return cTraderSession(tl, store, **kwargs)


def _immediate_dispatch(fn, *args, **kwargs):
    """reactor.callFromThread replacement: execute immediately."""
    fn()


# ── Tests ──────────────────────────────────────────────────────────────────


class TestConnect:
    """connect() — TCP connect + app auth + account auth."""

    @patch("adapters.ctrader.session.Protobuf.extract")
    @patch("adapters.ctrader.session.reactor")
    @patch("adapters.ctrader.session.Client")
    def test_connect_calls_app_auth_then_account_auth(self, mock_client_cls, mock_reactor, mock_extract):
        """Verify connect() sends ProtoOAApplicationAuthReq first, then ProtoOAAccountAuthReq."""
        session = _make_session()

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Dispatch ALL reactor.callFromThread calls immediately
        def dispatch(fn, *args, **kwargs):
            fn()  # execute immediately
            if "startService" in str(fn):
                session._tcp_connected.set()  # simulate TCP connect

        mock_reactor.callFromThread.side_effect = dispatch

        # Track the order of message types sent via client.send()
        send_order = []

        def fake_send(message, **kwargs):
            msg_name = type(message).__name__
            send_order.append(msg_name)
            # Return a successful auth response deferred
            mock_payload = MagicMock()
            mock_payload.errorCode = ""  # empty = success
            mock_extract.return_value = mock_payload
            return _make_mock_deferred(result=MagicMock(payloadType=2101))

        mock_client.send.side_effect = fake_send
        mock_client.setMessageReceivedCallback = MagicMock()

        result = session.connect()

        assert result is True
        assert session.state == SessionState.CONNECTED
        assert send_order == ["ProtoOAApplicationAuthReq", "ProtoOAAccountAuthReq"]

    @patch("adapters.ctrader.session.Protobuf.extract")
    @patch("adapters.ctrader.session.reactor")
    @patch("adapters.ctrader.session.Client")
    def test_connect_uses_valid_token(self, mock_client_cls, mock_reactor, mock_extract):
        """Verify token_lifecycle.ensure_valid() is called during connect."""
        session = _make_session()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Dispatch ALL reactor.callFromThread calls immediately
        def dispatch(fn, *args, **kwargs):
            fn()
            if "startService" in str(fn):
                session._tcp_connected.set()

        mock_reactor.callFromThread.side_effect = dispatch

        mock_payload = MagicMock()
        mock_payload.errorCode = ""
        mock_extract.return_value = mock_payload
        mock_client.send.return_value = _make_mock_deferred(result=MagicMock())

        session.connect()

        session._token_lifecycle.ensure_valid.assert_called_once()


class TestSend:
    """send() — reactor bridge pattern."""

    @patch("adapters.ctrader.session.reactor")
    def test_send_returns_response_on_success(self, mock_reactor):
        """When the deferred fires success, send returns the response."""
        session = _make_session()
        session._client = MagicMock()

        expected_response = MagicMock(name="proto_response")
        mock_deferred = _make_mock_deferred(result=expected_response)
        session._client.send.return_value = mock_deferred

        mock_reactor.callFromThread.side_effect = _immediate_dispatch

        result = session.send(MagicMock(), "test_msg_id", timeout=5)

        assert result is expected_response

    @patch("adapters.ctrader.session.reactor")
    def test_send_returns_none_on_timeout(self, mock_reactor):
        """When event.wait returns False (timeout), send returns None."""
        session = _make_session()
        session._client = MagicMock()

        # Deferred that never fires callbacks (no side_effect on addCallbacks)
        mock_deferred = MagicMock()
        session._client.send.return_value = mock_deferred

        # reactor.callFromThread executes do_send, which sets up callbacks,
        # but since addCallbacks has no side_effect, event is never set.
        mock_reactor.callFromThread.side_effect = _immediate_dispatch

        with patch.object(threading.Event, "wait", return_value=False):
            result = session.send(MagicMock(), "test_timeout", timeout=0.01)

        assert result is None

    @patch("adapters.ctrader.session.reactor")
    def test_send_fires_event_on_errback(self, mock_reactor):
        """When the deferred errback fires, SendError is raised."""
        session = _make_session()
        session._client = MagicMock()

        failure_msg = "Connection reset"
        mock_deferred = _make_mock_deferred(error=failure_msg)
        session._client.send.return_value = mock_deferred

        mock_reactor.callFromThread.side_effect = _immediate_dispatch

        with pytest.raises(SendError) as exc_info:
            session.send(MagicMock(), "test_errback", timeout=5)

        assert failure_msg in str(exc_info.value)

    @patch("adapters.ctrader.session.reactor")
    def test_send_fires_event_on_exception(self, mock_reactor):
        """When client.send() itself raises, SendError is raised."""
        session = _make_session()
        session._client = MagicMock()
        session._client.send.side_effect = RuntimeError("boom")

        mock_reactor.callFromThread.side_effect = _immediate_dispatch

        with pytest.raises(SendError) as exc_info:
            session.send(MagicMock(), "test_exc", timeout=5)

        assert "boom" in str(exc_info.value)


class TestMessageRouting:
    """register_message_handler + _on_message."""

    def test_message_routing_by_payload_type(self):
        """Register a handler, call _on_message, verify handler fires."""
        session = _make_session()

        received = []

        def handler(msg):
            return received.append(msg)

        session.register_message_handler(2126, handler)

        mock_msg = MagicMock()
        mock_msg.payloadType = 2126
        session._on_message(MagicMock(), mock_msg)

        assert len(received) == 1
        assert received[0] is mock_msg

    def test_multiple_handlers_same_payload_type(self):
        """Multiple handlers for the same payload type all fire."""
        session = _make_session()

        calls = []
        session.register_message_handler(2100, lambda msg: calls.append("a"))
        session.register_message_handler(2100, lambda msg: calls.append("b"))

        mock_msg = MagicMock()
        mock_msg.payloadType = 2100
        session._on_message(None, mock_msg)

        assert calls == ["a", "b"]

    def test_no_handlers_no_crash(self):
        """Message with no registered handlers is silently ignored."""
        session = _make_session()
        mock_msg = MagicMock()
        mock_msg.payloadType = 9999
        session._on_message(None, mock_msg)  # should not raise


class TestDisconnect:
    @patch("adapters.ctrader.session.reactor")
    @patch("adapters.ctrader.session.Client")
    def test_disconnect_cleans_up(self, mock_client_cls, mock_reactor):
        """disconnect() calls client.stopService and resets state."""
        session = _make_session()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        session._client = mock_client
        session._set_state(SessionState.CONNECTED)

        stopped = []

        def original_dispatch(fn, *a, **kw):
            return stopped.append(fn)

        mock_reactor.callFromThread.side_effect = original_dispatch

        session.disconnect()

        assert any("stopService" in str(fn) for fn in stopped)
        assert session.state == SessionState.DISCONNECTED
        assert session.client is None


class TestSubscribe:
    @patch("adapters.ctrader.session.reactor")
    def test_subscribe_market_data(self, mock_reactor):
        """subscribe_market_data sends ProtoOASubscribeSpotsReq and transitions to SUBSCRIBED."""
        session = _make_session()
        session._client = MagicMock()
        session._set_state(SessionState.CONNECTED)

        mock_response = MagicMock()
        with patch.object(session, "send", return_value=mock_response) as mock_send:
            result = session.subscribe_market_data([1, 2, 3])

        assert result is True
        assert session.state == SessionState.SUBSCRIBED
        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][0]
        assert type(sent_msg).__name__ == "ProtoOASubscribeSpotsReq"

    def test_subscribe_returns_false_when_not_operational(self):
        """subscribe_market_data fails fast if session is not operational."""
        session = _make_session()
        result = session.subscribe_market_data([1, 2])
        assert result is False


class TestProperties:
    def test_initial_state_is_disconnected(self):
        session = _make_session()
        assert session.state == SessionState.DISCONNECTED
        assert session.is_operational is False

    def test_is_operational_when_connected(self):
        session = _make_session()
        session._set_state(SessionState.CONNECTED)
        assert session.is_operational is True

    def test_is_operational_when_subscribed(self):
        session = _make_session()
        session._set_state(SessionState.SUBSCRIBED)
        assert session.is_operational is True

    def test_is_not_operational_when_reconnecting(self):
        session = _make_session()
        session._set_state(SessionState.RECONNECTING)
        assert session.is_operational is False
