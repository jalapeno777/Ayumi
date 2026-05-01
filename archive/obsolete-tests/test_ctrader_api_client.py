from adapters.ctrader.api_client import SOH, FIXClient, FIXMessage


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
