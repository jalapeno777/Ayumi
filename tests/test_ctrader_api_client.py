from unittest.mock import MagicMock, patch
import time

from adapters.ctrader.api_client import (
    SOH,
    FIXClient,
    FIXMessage,
    _DEFAULT_HEARTBEAT_INTERVAL,
    _DEFAULT_HEARTBEAT_TIMEOUT_FACTOR,
)
from adapters.ctrader.models import cTraderCredentials


class TestFIXMessage:
    def test_create_empty_message(self):
        msg = FIXMessage()
        assert msg.fields == {}

    def test_create_with_msg_type(self):
        msg = FIXMessage(msg_type="D")
        assert msg.get_field(35) == "D"

    def test_set_and_get_field(self):
        msg = FIXMessage()
        msg.set_field(35, "D")
        assert msg.get_field(35) == "D"

    def test_set_field_returns_self(self):
        msg = FIXMessage()
        result = msg.set_field(35, "D")
        assert result is msg

    def test_get_nonexistent_field(self):
        msg = FIXMessage()
        assert msg.get_field(999) is None

    def test_set_body_field(self):
        msg = FIXMessage(msg_type="D")
        msg.set_body_field(55, "EURUSD")
        assert msg.get_field(55) == "EURUSD"

    def test_to_wire_includes_header(self):
        msg = FIXMessage(msg_type="A")
        msg.set_field(49, "sender")
        msg.set_field(56, "target")
        wire = msg.to_wire()
        assert wire.startswith("8=FIX.4.4\x01")
        assert "35=A\x01" in wire
        assert "49=sender\x01" in wire
        assert "56=target\x01" in wire
        assert "10=" in wire
        assert wire.endswith(SOH)

    def test_to_wire_checksum(self):
        """Verify checksum is correctly calculated."""
        msg = FIXMessage(msg_type="0")  # Heartbeat
        msg.set_field(49, "test")
        msg.set_field(56, "test")
        wire = msg.to_wire()
        # Extract checksum value
        checksum_str = wire[wire.rfind("10=") + 3 : wire.rfind(SOH)]
        checksum_val = int(checksum_str)
        # Recalculate
        msg_without_checksum = wire[: wire.rfind("10=")]
        expected = sum(msg_without_checksum.encode("ascii")) % 256
        assert checksum_val == expected

    def test_to_wire_body_length(self):
        """Verify BodyLength is correct."""
        msg = FIXMessage(msg_type="A")
        msg.set_field(49, "sender")
        msg.set_field(56, "target")
        msg.set_body_field(98, "0")
        wire = msg.to_wire()
        # Extract BodyLength
        bl_start = wire.find("9=") + 2
        bl_end = wire.find(SOH, bl_start)
        body_length = int(wire[bl_start:bl_end])
        # BodyLength = bytes from after tag-9 SOH to before tag-10
        after_9 = wire.find(SOH, bl_end) + 1
        before_10 = wire.rfind("10=")
        actual_body_len = len(wire[after_9:before_10].encode("ascii"))
        assert body_length == actual_body_len

    def test_to_wire_uses_soh_not_pipe(self):
        """Wire format must use SOH, not pipe separators."""
        msg = FIXMessage(msg_type="A")
        msg.set_field(49, "sender")
        msg.set_field(56, "target")
        wire = msg.to_wire()
        assert "|" not in wire
        assert SOH in wire

    def test_from_wire(self):
        wire = "35=D\x0154=1\x0155=EURUSD\x0110=XXX\x01"
        msg = FIXMessage.from_wire(wire)
        assert msg.get_field(35) == "D"
        assert msg.get_field(54) == "1"
        assert msg.get_field(55) == "EURUSD"

    def test_from_wire_ignores_invalid(self):
        wire = "35=D\x01invalid\x0154=1\x01"
        msg = FIXMessage.from_wire(wire)
        assert msg.get_field(35) == "D"
        assert msg.get_field(54) == "1"

    def test_msg_type_property(self):
        msg = FIXMessage(msg_type="D")
        assert msg.msg_type == "D"

    def test_msg_type_none_when_missing(self):
        msg = FIXMessage()
        assert msg.msg_type is None


class TestFIXClientConstants:
    def test_protocol_version(self):
        assert FIXClient.PROTOCOL_VERSION == "FIX.4.4"

    def test_message_types(self):
        assert FIXClient.MSG_TYPE_LOGON == "A"
        assert FIXClient.MSG_TYPE_LOGOUT == "5"
        assert FIXClient.MSG_TYPE_HEARTBEAT == "0"
        assert FIXClient.MSG_TYPE_TEST_REQUEST == "1"
        assert FIXClient.MSG_TYPE_REJECT == "3"
        assert FIXClient.MSG_TYPE_EXECUTION_REPORT == "8"
        assert FIXClient.MSG_TYPE_ORDER_CANCEL_REJECT == "9"
        assert FIXClient.MSG_TYPE_NEW_ORDER_SINGLE == "D"
        assert FIXClient.MSG_TYPE_ORDER_CANCEL_REQUEST == "F"

    def test_fix_tags(self):
        assert FIXClient.TAG_MSG_TYPE == 35
        assert FIXClient.TAG_SENDER_COMP_ID == 49
        assert FIXClient.TAG_TARGET_COMP_ID == 56
        assert FIXClient.TAG_CLORD_ID == 11
        assert FIXClient.TAG_ORDER_ID == 37
        assert FIXClient.TAG_SYMBOL == 55
        assert FIXClient.TAG_SIDE == 54
        assert FIXClient.TAG_EXEC_ID == 17

    def test_auth_tags(self):
        assert FIXClient.TAG_USERNAME == 553
        assert FIXClient.TAG_PASSWORD == 554


def _make_credentials() -> cTraderCredentials:
    return cTraderCredentials(
        host="localhost",
        port=5211,
        use_ssl=False,
        sender_comp_id="TEST",
        target_comp_id="cServer",
        sender_sub_id="QUOTE",
        username="12345",
        password="test",
    )


class TestFIXClientHeartbeatTimeout:
    def test_heartbeat_timeout_triggers_connection_lost_callback(self):
        creds = _make_credentials()
        client = FIXClient(creds, heartbeat_interval=1, heartbeat_timeout_factor=1.2)
        client._logged_in = True
        client._last_heartbeat_received = time.time() - 2.0
        client._last_heartbeat_sent = time.time()

        cb = MagicMock()
        client.register_callback("on_connection_lost", cb)

        client._check_heartbeat()

        cb.assert_called_once_with("heartbeat_timeout")
        assert client._connection_lost is True
        assert client.is_connected is False

    def test_heartbeat_timeout_does_not_fire_within_interval(self):
        creds = _make_credentials()
        client = FIXClient(creds, heartbeat_interval=30, heartbeat_timeout_factor=1.2)
        client._logged_in = True
        client._last_heartbeat_received = time.time() - 10.0
        client._last_heartbeat_sent = time.time()

        cb = MagicMock()
        client.register_callback("on_connection_lost", cb)

        client._check_heartbeat()

        cb.assert_not_called()
        assert client.is_connected is True

    def test_heartbeat_timeout_only_fires_once(self):
        creds = _make_credentials()
        client = FIXClient(creds, heartbeat_interval=1, heartbeat_timeout_factor=1.2)
        client._logged_in = True
        client._last_heartbeat_received = time.time() - 2.0
        client._last_heartbeat_sent = time.time()

        cb = MagicMock()
        client.register_callback("on_connection_lost", cb)

        client._check_heartbeat()
        client._check_heartbeat()

        cb.assert_called_once()

    def test_heartbeat_sends_when_interval_elapsed(self):
        creds = _make_credentials()
        client = FIXClient(creds, heartbeat_interval=1)
        client._logged_in = True
        client._last_heartbeat_sent = time.time() - 5.0
        client._last_heartbeat_received = time.time()
        client._socket = MagicMock()

        client._check_heartbeat()

        assert client._socket.send.called

    def test_is_connected_false_after_connection_lost(self):
        creds = _make_credentials()
        client = FIXClient(creds)
        client._logged_in = False
        client._connection_lost = True

        assert client.is_connected is False

    def test_is_connected_false_when_not_logged_in(self):
        creds = _make_credentials()
        client = FIXClient(creds)
        client._logged_in = False
        client._connection_lost = False

        assert client.is_connected is False

    def test_is_connected_true_when_logged_in_no_loss(self):
        creds = _make_credentials()
        client = FIXClient(creds)
        client._logged_in = True
        client._connection_lost = False

        assert client.is_connected is True

    def test_custom_heartbeat_interval(self):
        creds = _make_credentials()
        client = FIXClient(creds, heartbeat_interval=15)
        assert client._heartbeat_interval == 15

    def test_custom_heartbeat_timeout_factor(self):
        creds = _make_credentials()
        client = FIXClient(creds, heartbeat_timeout_factor=2.0)
        assert client._heartbeat_timeout_factor == 2.0

    def test_default_heartbeat_values(self):
        creds = _make_credentials()
        client = FIXClient(creds)
        assert client._heartbeat_interval == _DEFAULT_HEARTBEAT_INTERVAL
        assert client._heartbeat_timeout_factor == _DEFAULT_HEARTBEAT_TIMEOUT_FACTOR


class TestFIXClientRecvLoopConnectionLost:
    def test_recv_loop_sets_connection_lost_on_socket_close(self):
        creds = _make_credentials()
        client = FIXClient(creds, heartbeat_interval=60)
        client._logged_in = True
        client._running = True
        client._connection_lost = False

        cb = MagicMock()
        client.register_callback("on_connection_lost", cb)

        mock_socket = MagicMock()
        mock_socket.recv.return_value = b""
        client._socket = mock_socket

        client._recv_loop()

        assert client._logged_in is False
        assert client._connection_lost is True
        cb.assert_called_once_with("recv_loop_exited")

    def test_recv_loop_sets_connection_lost_on_error(self):
        creds = _make_credentials()
        client = FIXClient(creds, heartbeat_interval=60)
        client._logged_in = True
        client._running = True
        client._connection_lost = False

        cb = MagicMock()
        client.register_callback("on_connection_lost", cb)

        mock_socket = MagicMock()
        mock_socket.recv.side_effect = ConnectionResetError("reset")
        client._socket = mock_socket

        client._recv_loop()

        assert client._logged_in is False
        assert client._connection_lost is True
        cb.assert_called_once_with("recv_loop_exited")

    def test_recv_loop_no_callback_when_not_logged_in(self):
        creds = _make_credentials()
        client = FIXClient(creds, heartbeat_interval=60)
        client._logged_in = False
        client._running = True

        cb = MagicMock()
        client.register_callback("on_connection_lost", cb)

        mock_socket = MagicMock()
        mock_socket.recv.return_value = b""
        client._socket = mock_socket

        client._recv_loop()

        cb.assert_not_called()


class TestFIXClientHeartbeatThread:
    def test_heartbeat_thread_starts_and_stops(self):
        creds = _make_credentials()
        client = FIXClient(creds, heartbeat_interval=1)
        client._logged_in = True
        client._last_heartbeat_sent = time.time()
        client._last_heartbeat_received = time.time()

        client._start_heartbeat_thread()
        assert client._heartbeat_thread is not None

        client._stop_heartbeat.set()
        client._heartbeat_thread.join(timeout=3.0)
        assert not client._heartbeat_thread.is_alive()

    def test_heartbeat_thread_stops_on_disconnect(self):
        creds = _make_credentials()
        client = FIXClient(creds, heartbeat_interval=1)
        client._logged_in = True
        client._last_heartbeat_sent = time.time()
        client._last_heartbeat_received = time.time()

        client._start_heartbeat_thread()
        client.disconnect()
        assert client._heartbeat_thread is None


class TestFIXClientTCPKeepalive:
    def test_connect_sets_tcp_keepalive(self):
        creds = _make_credentials()
        client = FIXClient(creds)

        mock_socket = MagicMock()
        mock_ssl_socket = MagicMock()

        with (
            patch("socket.socket", return_value=mock_socket),
            patch("ssl.SSLContext") as mock_ssl_ctx,
        ):
            mock_ctx_instance = MagicMock()
            mock_ctx_instance.wrap_socket.return_value = mock_ssl_socket
            mock_ssl_ctx.return_value = mock_ctx_instance
            mock_ssl_ctx.PROTOCOL_TLS_CLIENT = 2

            creds.use_ssl = True
            client.connect()

        mock_socket.setsockopt.assert_any_call(1, 9, 1)


class TestFIXClientConnectionLostFlag:
    def test_connection_lost_reset_on_new_connect(self):
        creds = _make_credentials()
        client = FIXClient(creds)
        client._connection_lost = True
        client._logged_in = False

        mock_socket = MagicMock()
        mock_ssl_socket = MagicMock()
        mock_ssl_socket.send.return_value = 10

        with (
            patch("socket.socket", return_value=mock_socket),
            patch("ssl.SSLContext") as mock_ssl_ctx,
        ):
            mock_ctx_instance = MagicMock()
            mock_ctx_instance.wrap_socket.return_value = mock_ssl_socket
            mock_ssl_ctx.return_value = mock_ctx_instance
            mock_ssl_ctx.PROTOCOL_TLS_CLIENT = 2

            creds.use_ssl = True
            client.connect()

        assert client._connection_lost is False
