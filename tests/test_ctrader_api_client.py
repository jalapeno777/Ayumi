from adapters.ctrader.api_client import FIXMessage, FIXClient
from adapters.ctrader.models import cTraderCredentials


class TestFIXMessage:
    def test_create_empty_message(self):
        msg = FIXMessage()
        assert msg.fields == {}

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

    def test_to_string_single_field(self):
        msg = FIXMessage()
        msg.set_field(35, "D")
        result = msg.to_string()
        assert "35=D" in result
        assert msg.SOH in result

    def test_to_string_multiple_fields_sorted(self):
        msg = FIXMessage()
        msg.set_field(55, "EURUSD")
        msg.set_field(54, "1")
        msg.set_field(35, "D")
        result = msg.to_string()
        assert result == "35=D\x0154=1\x0155=EURUSD\x01"
        assert result.endswith(msg.SOH)

    def test_from_string(self):
        data = "35=D\x0154=1\x0155=EURUSD\x01"
        msg = FIXMessage.from_string(data)
        assert msg.get_field(35) == "D"
        assert msg.get_field(54) == "1"
        assert msg.get_field(55) == "EURUSD"

    def test_from_string_ignores_invalid(self):
        data = "35=D\x01invalid\x0154=1\x01"
        msg = FIXMessage.from_string(data)
        assert msg.get_field(35) == "D"
        assert msg.get_field(54) == "1"

    def test_msg_type_property(self):
        msg = FIXMessage()
        msg.set_field(35, "D")
        assert msg.msg_type == "D"

    def test_msg_type_none_when_missing(self):
        msg = FIXMessage()
        assert msg.msg_type is None


class TestFIXClientConstants:
    def test_protocol_version(self):
        assert FIXClient.PROTOCOL_VERSION == "FIX.4.4"

    def test_default_ports(self):
        assert FIXClient.DEFAULT_PORT == 5201
        assert FIXClient.SSL_PORT == 5211

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

    def test_logon_includes_auth_tags_553_554(self):
        creds = cTraderCredentials(
            host="localhost",
            port=5211,
            sender_comp_id="12345",
            password="secret",
        )
        client = FIXClient(creds)
        msg = FIXMessage()
        msg.set_field(client.TAG_MSG_TYPE, client.MSG_TYPE_LOGON)
        msg.set_field(98, "0")
        msg.set_field(108, str(client._heartbeat_interval))
        msg.set_field(141, "Y")
        msg.set_field(553, creds.sender_comp_id)
        msg.set_field(554, creds.password)
        result = msg.to_string()
        assert "553=12345" in result
        assert "554=secret" in result

    def test_no_field_separator_pipe(self):
        assert not hasattr(FIXMessage, "FIELD_SEPARATOR")

    def test_process_buffer_extracts_complete_messages(self):
        creds = cTraderCredentials(
            host="localhost",
            port=5211,
            sender_comp_id="12345",
            target_comp_id="cServer",
            sender_sub_id="TRADE",
        )
        client = FIXClient(creds)
        handled = []

        def capture(msg):
            handled.append(msg)

        client._handle_message = capture

        logon_body = "35=A\x0149=12345\x0156=cServer\x0134=1\x0152=20240101-00:00:00\x0150=TRADE\x0157=\x0198=0\x01108=30\x01141=Y\x01553=12345\x01554=secret\x01"
        body_len = len(logon_body)
        header = f"8=FIX.4.4\x019={body_len}\x01"
        checksum_input = header + logon_body
        chk = sum(ord(c) for c in checksum_input) % 256
        full_msg = checksum_input + f"10={chk:03d}\x01"

        remaining = client._process_buffer(full_msg.encode("latin-1"))
        assert len(handled) == 1
        assert handled[0].msg_type == "A"
        assert len(remaining) == 0

    def test_process_buffer_retains_partial_message(self):
        creds = cTraderCredentials(
            host="localhost",
            port=5211,
            sender_comp_id="12345",
            target_comp_id="cServer",
            sender_sub_id="TRADE",
        )
        client = FIXClient(creds)
        handled = []

        def capture(msg):
            handled.append(msg)

        client._handle_message = capture

        partial = b"8=FIX.4.4\x019=5\x0135="
        remaining = client._process_buffer(partial)
        assert len(handled) == 0
        assert len(remaining) == len(partial)

    def test_process_buffer_multiple_messages(self):
        creds = cTraderCredentials(
            host="localhost",
            port=5211,
            sender_comp_id="12345",
            target_comp_id="cServer",
            sender_sub_id="TRADE",
        )
        client = FIXClient(creds)
        handled = []

        def capture(msg):
            handled.append(msg)

        client._handle_message = capture

        hb_body = "35=0\x0149=12345\x0156=cServer\x0134=1\x0152=20240101-00:00:00\x0150=TRADE\x0157=\x01"
        hb_header = f"8=FIX.4.4\x019={len(hb_body)}\x01"
        hb_checksum_input = hb_header + hb_body
        hb_chk = sum(ord(c) for c in hb_checksum_input) % 256
        hb_msg = hb_checksum_input + f"10={hb_chk:03d}\x01"

        test_body = "35=1\x0149=12345\x0156=cServer\x0134=2\x0152=20240101-00:00:00\x0150=TRADE\x0157=\x01"
        test_header = f"8=FIX.4.4\x019={len(test_body)}\x01"
        test_checksum_input = test_header + test_body
        test_chk = sum(ord(c) for c in test_checksum_input) % 256
        test_msg = test_checksum_input + f"10={test_chk:03d}\x01"

        remaining = client._process_buffer((hb_msg + test_msg).encode("latin-1"))
        assert len(handled) == 2
        assert handled[0].msg_type == "0"
        assert handled[1].msg_type == "1"
        assert len(remaining) == 0
