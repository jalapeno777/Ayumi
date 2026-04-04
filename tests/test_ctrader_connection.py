import os
import unittest
from unittest.mock import MagicMock, patch

from ctrader.connection import (
    CTraderConnection,
    MissingCredentialError,
    FIXConnectionError,
    _build_fix_message,
    _checksum,
    _load_credentials,
    SOH,
)

SAMPLE_CREDS = {
    "CTRADER_HOST": "h.fix.ctrader.com",
    "CTRADER_SSL_PORT": "9200",
    "CTRADER_PLAIN_PORT": "9210",
    "CTRADER_ACCOUNT": "12345",
    "CTRADER_PASSWORD": "secret123",
    "CTRADER_SENDER_COMP_ID": "sender",
    "CTRADER_TARGET_COMP_ID": "CSERVER",
    "CTRADER_SENDER_SUB_ID": "TRADE",
    "CTRADER_QUOTE_SENDER_SUB_ID": "QUOTE",
}


def _set_env(creds: dict[str, str]) -> None:
    for key, value in creds.items():
        os.environ[key] = value


def _clear_env() -> None:
    for key in list(SAMPLE_CREDS.keys()):
        os.environ.pop(key, None)


class TestChecksum(unittest.TestCase):
    def test_known_checksum(self):
        body = "8=FIX.4.4\x019=5\x0135=A\x01"
        result = _checksum(body)
        expected = sum(ord(c) for c in body) % 256
        self.assertEqual(result, f"{expected:03d}")

    def test_checksum_format_three_digits(self):
        body = "test"
        result = _checksum(body)
        self.assertEqual(len(result), 3)
        self.assertTrue(result.isdigit())

    def test_checksum_wraps_at_256(self):
        body = "A" * 256
        result = _checksum(body)
        self.assertEqual(int(result), 0)

    def test_checksum_different_inputs(self):
        self.assertNotEqual(_checksum("abc"), _checksum("abd"))


class TestBuildFixMessage(unittest.TestCase):
    def test_message_starts_with_begin_string(self):
        msg = _build_fix_message({35: "A"}, 1)
        self.assertTrue(msg.startswith("8=FIX.4.4\x01"))

    def test_body_length_is_correct(self):
        msg = _build_fix_message({35: "A", 49: "SENDER", 56: "TARGET"}, 1)
        fields = msg.split(SOH)
        body_len_field = [f for f in fields if f.startswith("9=")][0]
        body_len = int(body_len_field[2:])

        after_9 = msg.index("9=" + body_len_field[2:] + SOH)
        before_10 = msg.index("10=")
        actual_body_len = before_10 - after_9 - len("9=") - len(str(body_len)) - 1
        self.assertEqual(body_len, actual_body_len)

    def test_checksum_matches(self):
        msg = _build_fix_message({35: "A"}, 1)
        fields = msg.split(SOH)
        checksum_field = [f for f in fields if f.startswith("10=")][0]
        claimed = int(checksum_field[3:])

        before_10 = msg.index("10=")
        body_for_checksum = msg[:before_10]
        expected = sum(ord(c) for c in body_for_checksum) % 256
        self.assertEqual(claimed, expected)

    def test_message_ends_with_soh(self):
        msg = _build_fix_message({35: "A"}, 1)
        self.assertTrue(msg.endswith(SOH))

    def test_logon_message_has_all_required_tags(self):
        tags = {
            35: "A",
            49: "SENDER",
            56: "TARGET",
            34: "1",
            52: "20260101-00:00:00.000",
            50: "TRADE",
            98: "0",
            108: "30",
            553: "12345",
            554: "pass",
        }
        msg = _build_fix_message(tags, 1)
        for tag in [35, 49, 56, 34, 52, 50, 98, 108, 553, 554]:
            self.assertIn(f"{tag}=", msg)


class TestLoadCredentials(unittest.TestCase):
    def setUp(self):
        _clear_env()

    def tearDown(self):
        _clear_env()

    def test_missing_required_vars_raises(self):
        with self.assertRaises(MissingCredentialError) as ctx:
            _load_credentials()
        self.assertIn("CTRADER_ACCOUNT", str(ctx.exception))

    def test_all_required_vars_loaded(self):
        _set_env(SAMPLE_CREDS)
        creds = _load_credentials()
        self.assertEqual(creds["CTRADER_HOST"], "h.fix.ctrader.com")
        self.assertEqual(creds["CTRADER_SSL_PORT"], "9200")
        self.assertEqual(creds["CTRADER_ACCOUNT"], "12345")
        self.assertEqual(creds["CTRADER_PASSWORD"], "secret123")
        self.assertEqual(creds["CTRADER_SENDER_COMP_ID"], "sender")
        self.assertEqual(creds["CTRADER_TARGET_COMP_ID"], "CSERVER")
        self.assertEqual(creds["CTRADER_SENDER_SUB_ID"], "TRADE")

    def test_optional_vars_included_when_set(self):
        _set_env(SAMPLE_CREDS)
        creds = _load_credentials()
        self.assertIn("CTRADER_PLAIN_PORT", creds)
        self.assertEqual(creds["CTRADER_PLAIN_PORT"], "9210")
        self.assertIn("CTRADER_QUOTE_SENDER_SUB_ID", creds)

    def test_optional_vars_omitted_when_not_set(self):
        required_only = {
            k: v
            for k, v in SAMPLE_CREDS.items()
            if k not in ["CTRADER_PLAIN_PORT", "CTRADER_QUOTE_SENDER_SUB_ID"]
        }
        _set_env(required_only)
        creds = _load_credentials()
        self.assertNotIn("CTRADER_PLAIN_PORT", creds)
        self.assertNotIn("CTRADER_QUOTE_SENDER_SUB_ID", creds)

    def test_partial_missing_raises(self):
        _set_env({"CTRADER_HOST": "host"})
        with self.assertRaises(MissingCredentialError) as ctx:
            _load_credentials()
        self.assertIn("CTRADER_SSL_PORT", str(ctx.exception))


class TestCTraderConnection(unittest.TestCase):
    def setUp(self):
        _set_env(SAMPLE_CREDS)

    def tearDown(self):
        _clear_env()

    def test_init_loads_credentials(self):
        conn = CTraderConnection()
        self.assertEqual(conn._creds["CTRADER_HOST"], "h.fix.ctrader.com")

    def test_init_with_explicit_credentials(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        self.assertEqual(conn._creds["CTRADER_HOST"], "h.fix.ctrader.com")

    def test_initial_state_not_connected(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        self.assertFalse(conn.is_connected)

    def test_build_logon_message_format(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        msg = conn._build_logon_message()
        self.assertIn("35=A", msg)
        self.assertIn("49=sender", msg)
        self.assertIn("56=CSERVER", msg)
        self.assertIn("50=TRADE", msg)
        self.assertIn("98=0", msg)
        self.assertIn("108=30", msg)
        self.assertIn("553=12345", msg)
        self.assertIn("554=secret123", msg)
        self.assertTrue(msg.endswith(SOH))

    def test_build_logon_message_password_not_logged(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        msg = conn._build_logon_message()
        self.assertIn("554=", msg)
        self.assertNotIn("554=***", msg)

    def test_build_market_data_request(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        msg = conn._build_market_data_request("EURUSD")
        self.assertIn("35=V", msg)
        self.assertIn("146=EURUSD", msg)

    def test_market_data_increments_seq_num(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        _ = conn._build_logon_message()
        seq_before = conn._msg_seq_num
        conn._build_market_data_request("EURUSD")
        self.assertEqual(conn._msg_seq_num, seq_before + 1)

    def test_disconnect_when_not_connected(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        conn.disconnect()
        self.assertFalse(conn.is_connected)

    def test_send_market_data_request_when_not_connected_raises(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        with self.assertRaises(FIXConnectionError):
            conn.send_market_data_request("EURUSD")

    def test_connect_success(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        mock_socket = MagicMock()

        logon_response = (
            f"8=FIX.4.4{SOH}9=5{SOH}35=A{SOH}49=CSERVER{SOH}56=sender{SOH}10=123{SOH}"
        )

        mock_socket.recv.return_value = logon_response.encode("ascii")

        with (
            patch(
                "ctrader.connection.socket.create_connection", return_value=MagicMock()
            ),
            patch("ctrader.connection.ssl.create_default_context") as mock_ctx,
            patch.object(conn, "_recv_message", return_value=logon_response),
        ):
            mock_ssl_socket = MagicMock()
            mock_ctx.return_value.wrap_socket.return_value = mock_ssl_socket

            conn.connect()

            self.assertTrue(conn.is_connected)
            mock_ssl_socket.sendall.assert_called_once()
            sent_data = mock_ssl_socket.sendall.call_args[0][0]
            self.assertIn(b"35=A", sent_data)

    def test_connect_rejects_non_logon_response(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        bad_response = (
            f"8=FIX.4.4{SOH}9=5{SOH}35=3{SOH}49=CSERVER{SOH}56=sender{SOH}10=123{SOH}"
        )

        mock_ssl_socket = MagicMock()

        with (
            patch(
                "ctrader.connection.socket.create_connection", return_value=MagicMock()
            ),
            patch("ctrader.connection.ssl.create_default_context") as mock_ctx,
            patch.object(conn, "_recv_message", return_value=bad_response),
        ):
            mock_ctx.return_value.wrap_socket.return_value = mock_ssl_socket

            with self.assertRaises(FIXConnectionError) as ctx:
                conn.connect()
            self.assertIn("MsgType=3", str(ctx.exception))
            self.assertFalse(conn.is_connected)

    def test_disconnect_sends_logout(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        mock_socket = MagicMock()
        conn._socket = mock_socket
        conn._connected = True

        conn.disconnect()

        mock_socket.sendall.assert_called_once()
        sent_data = mock_socket.sendall.call_args[0][0]
        self.assertIn(b"35=5", sent_data)
        mock_socket.close.assert_called_once()
        self.assertFalse(conn.is_connected)

    def test_disconnect_handles_socket_error(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        mock_socket = MagicMock()
        mock_socket.sendall.side_effect = OSError("broken")
        mock_socket.close.side_effect = OSError("broken")
        conn._socket = mock_socket
        conn._connected = True

        conn.disconnect()
        self.assertFalse(conn.is_connected)
        self.assertIsNone(conn._socket)

    def test_parse_msg_type_logon(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        raw = f"8=FIX.4.4{SOH}9=5{SOH}35=A{SOH}49=CSERVER{SOH}10=000{SOH}"
        self.assertEqual(conn._parse_msg_type(raw), "A")

    def test_parse_msg_type_heartbeat(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        raw = f"8=FIX.4.4{SOH}9=5{SOH}35=0{SOH}49=CSERVER{SOH}10=000{SOH}"
        self.assertEqual(conn._parse_msg_type(raw), "0")

    def test_parse_msg_type_empty_for_missing(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        raw = f"8=FIX.4.4{SOH}9=5{SOH}49=CSERVER{SOH}10=000{SOH}"
        self.assertEqual(conn._parse_msg_type(raw), "")

    def test_custom_heartbeat_interval(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS, heartbeat_interval=60)
        msg = conn._build_logon_message()
        self.assertIn("108=60", msg)

    def test_sending_time_format(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        time_str = conn._get_sending_time()
        self.assertRegex(time_str, r"^\d{8}-\d{2}:\d{2}:\d{2}\.\d{3}$")

    def test_send_market_data_request_returns_message(self):
        conn = CTraderConnection(credentials=SAMPLE_CREDS)
        conn._socket = MagicMock()
        conn._connected = True
        msg = conn.send_market_data_request("GBPUSD")
        self.assertIn("35=V", msg)
        self.assertIn("146=GBPUSD", msg)
        conn._socket.sendall.assert_called_once()


class TestCredentialSecurity(unittest.TestCase):
    def test_password_never_in_message_repr(self):
        _set_env(SAMPLE_CREDS)
        conn = CTraderConnection()
        conn._build_logon_message()
        repr_str = repr(conn)
        self.assertNotIn("secret123", repr_str)
        _clear_env()


if __name__ == "__main__":
    unittest.main()
