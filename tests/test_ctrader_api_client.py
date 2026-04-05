
from adapters.ctrader.api_client import FIXMessage, FIXClient


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
        assert result == "35=D|54=1|55=EURUSD\x01"
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
