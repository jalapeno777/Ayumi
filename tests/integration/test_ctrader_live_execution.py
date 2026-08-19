from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

pytest.skip("adapters.ctrader.api_client module removed", allow_module_level=True)

from adapters.ctrader.api_client import (
    FIX_REJECT_MESSAGES,
    FIXMessage,
    FIXRejectCode,
    get_reject_message,
)
from adapters.ctrader.models import (
    Order,
    OrderStatus,
    OrderType,
    TradeDirection,
    CTraderTradeSignal,
)
from adapters.ctrader.order_manager import (
    OrderManager,
)
from adapters.ctrader.paper_trader import PaperTrader
from adapters.ctrader.risk_guard import FTMOConfig


def _make_signal(**overrides) -> CTraderTradeSignal:
    defaults = dict(
        symbol="EURUSD",
        direction=TradeDirection.LONG,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1100,
        take_profit_2=1.1150,
        take_profit_3=1.1200,
        volume=0.1,
        confidence=0.85,
        rationale="Test signal",
    )
    defaults.update(overrides)
    return CTraderTradeSignal(**defaults)


class TestFIXRejectCode:
    def test_all_codes_have_messages(self):
        for code in FIXRejectCode:
            assert code in FIX_REJECT_MESSAGES, f"No message for {code.name}"

    def test_get_reject_message_known_code(self):
        msg = get_reject_message(26)
        assert "Insufficient funds" in msg

    def test_get_reject_message_unknown_code(self):
        msg = get_reject_message(9999)
        assert "Unknown reject code 9999" in msg

    def test_get_reject_message_with_text(self):
        msg = get_reject_message(26, "Only $50 available")
        assert "Insufficient funds" in msg
        assert "Only $50 available" in msg

    def test_get_reject_message_zero_code(self):
        msg = get_reject_message(0)
        assert "Unspecified" in msg

    def test_common_reject_codes(self):
        assert FIXRejectCode.INSUFFICIENT_FUNDS.value == 26
        assert FIXRejectCode.DUPLICATE_ORDER.value == 38
        assert FIXRejectCode.INSUFFICIENT_MARGIN.value == 102
        assert FIXRejectCode.TRADING_SESSION_CLOSED.value == 22


class TestFIXClientExecutionReport:
    def _make_fix_client(self):
        from adapters.ctrader.api_client import FIXClient
        from adapters.ctrader.models import cTraderCredentials

        creds = cTraderCredentials(
            host="localhost",
            port=5202,
            use_ssl=False,
            sender_comp_id="test",
            username="12345",
            password="pass",
        )
        return FIXClient(creds)

    def test_exec_type_new_sets_pending(self):
        client = self._make_fix_client()
        order = Order(
            order_id="ORD_001",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        client._pending_orders["ORD_001"] = order

        msg = FIXMessage(msg_type="8")
        msg.fields[11] = "ORD_001"
        msg.fields[150] = "0"
        msg.fields[39] = "A"

        filled_orders = []
        client.register_callback("on_order_new", lambda o, m: filled_orders.append(o))
        client._handle_execution_report(msg)

        assert order.status == OrderStatus.PENDING
        assert len(filled_orders) == 1

    def test_exec_type_fill(self):
        client = self._make_fix_client()
        order = Order(
            order_id="ORD_002",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        client._pending_orders["ORD_002"] = order

        msg = FIXMessage(msg_type="8")
        msg.fields[11] = "ORD_002"
        msg.fields[150] = "F"
        msg.fields[39] = "2"
        msg.fields[31] = "1.1005"
        msg.fields[32] = "10000"

        filled_orders = []
        client.register_callback(
            "on_order_filled", lambda o, m: filled_orders.append(o)
        )
        client._handle_execution_report(msg)

        assert order.status == OrderStatus.FILLED
        assert order.filled_price == 1.1005
        assert len(filled_orders) == 1

    def test_exec_type_cancelled(self):
        client = self._make_fix_client()
        order = Order(
            order_id="ORD_003",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        client._pending_orders["ORD_003"] = order

        msg = FIXMessage(msg_type="8")
        msg.fields[11] = "ORD_003"
        msg.fields[150] = "4"
        msg.fields[39] = "4"
        msg.fields[58] = "User requested"

        cancelled = []
        client.register_callback("on_order_cancelled", lambda o, m: cancelled.append(o))
        client._handle_execution_report(msg)

        assert order.status == OrderStatus.CANCELLED
        assert "User requested" in order.comment
        assert len(cancelled) == 1

    def test_exec_type_rejected_maps_code(self):
        client = self._make_fix_client()
        order = Order(
            order_id="ORD_004",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        client._pending_orders["ORD_004"] = order

        msg = FIXMessage(msg_type="8")
        msg.fields[11] = "ORD_004"
        msg.fields[150] = "8"
        msg.fields[39] = "8"
        msg.fields[371] = "26"
        msg.fields[58] = "Not enough money"

        rejected = []
        client.register_callback(
            "on_order_rejected", lambda o, m, r: rejected.append((o, r))
        )
        client._handle_execution_report(msg)

        assert order.status == OrderStatus.REJECTED
        assert "Insufficient funds" in order.comment
        assert len(rejected) == 1
        assert "Insufficient funds" in rejected[0][1]

    def test_exec_type_expired(self):
        client = self._make_fix_client()
        order = Order(
            order_id="ORD_005",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.LIMIT,
            volume=0.1,
            price=1.0950,
        )
        client._pending_orders["ORD_005"] = order

        msg = FIXMessage(msg_type="8")
        msg.fields[11] = "ORD_005"
        msg.fields[150] = "C"
        msg.fields[39] = "6"

        cancelled = []
        client.register_callback("on_order_cancelled", lambda o, m: cancelled.append(o))
        client._handle_execution_report(msg)

        assert order.status == OrderStatus.CANCELLED
        assert "expired" in order.comment.lower()

    def test_exec_type_partial_fill(self):
        client = self._make_fix_client()
        order = Order(
            order_id="ORD_006",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        client._pending_orders["ORD_006"] = order

        msg = FIXMessage(msg_type="8")
        msg.fields[11] = "ORD_006"
        msg.fields[150] = "1"
        msg.fields[39] = "1"
        msg.fields[31] = "1.1002"

        partials = []
        client.register_callback(
            "on_order_partial_fill", lambda o, m: partials.append(o)
        )
        client._handle_execution_report(msg)

        assert order.status == OrderStatus.PENDING
        assert order.filled_price == 1.1002
        assert len(partials) == 1

    def test_unknown_exec_type_does_not_crash(self):
        client = self._make_fix_client()
        order = Order(
            order_id="ORD_007",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        client._pending_orders["ORD_007"] = order

        msg = FIXMessage(msg_type="8")
        msg.fields[11] = "ORD_007"
        msg.fields[150] = "Z"

        client._handle_execution_report(msg)
        assert order.status == OrderStatus.PENDING


class TestOrderManagerLiveExecution:
    def test_execute_live_order_no_client(self):
        manager = OrderManager()
        result = manager.execute_live_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
        )
        assert result.success is False
        assert "no_live_client" in result.rejection_reason

    def test_execute_live_order_paper_mode(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = True
        manager = OrderManager(api_client=mock_api)
        result = manager.execute_live_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
        )
        assert result.success is False
        assert "paper mode" in result.error_message.lower()

    def test_execute_live_order_not_connected(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = False
        manager = OrderManager(api_client=mock_api)
        result = manager.execute_live_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
        )
        assert result.success is False
        assert "not_connected" in result.rejection_reason

    def test_execute_live_order_send_fails(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        mock_api.send_order.return_value = None
        manager = OrderManager(api_client=mock_api)
        result = manager.execute_live_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
        )
        assert result.success is False
        assert "send_failed" in result.rejection_reason

    def test_execute_live_order_success_immediate_fill(self):
        filled_order = Order(
            order_id="FIX_001",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
            status=OrderStatus.FILLED,
            filled_at=datetime.now(timezone.utc),
            filled_price=1.1005,
        )
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        mock_api.send_order.return_value = filled_order

        manager = OrderManager(api_client=mock_api)
        result = manager.execute_live_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
        )

        assert result.success is True
        assert result.order is not None
        assert result.position is not None
        assert result.position.symbol == "EURUSD"
        mock_api.send_order.assert_called_once()

    def test_execute_live_order_pending(self):
        pending_order = Order(
            order_id="FIX_002",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.LIMIT,
            volume=0.1,
            price=1.0950,
            status=OrderStatus.PENDING,
        )
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        mock_api.send_order.return_value = pending_order

        manager = OrderManager(api_client=mock_api)
        result = manager.execute_live_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            order_type=OrderType.LIMIT,
            price=1.0950,
        )

        assert result.success is True
        assert result.order is not None
        assert result.order.status == OrderStatus.PENDING
        assert result.position is None

    def test_execute_live_order_rejected(self):
        rejected_order = Order(
            order_id="FIX_003",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
            status=OrderStatus.REJECTED,
            comment="Insufficient funds: Not enough money",
        )
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        mock_api.send_order.return_value = rejected_order

        manager = OrderManager(api_client=mock_api)
        result = manager.execute_live_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
        )

        assert result.success is False
        assert "broker_rejected" in result.rejection_reason
        assert result.order.status == OrderStatus.REJECTED

    def test_execute_live_order_with_sl_tp(self):
        filled_order = Order(
            order_id="FIX_SLTP",
            symbol="GBPUSD",
            direction=TradeDirection.SHORT,
            order_type=OrderType.MARKET,
            volume=0.05,
            stop_loss=1.2650,
            take_profit=1.2500,
            status=OrderStatus.FILLED,
            filled_at=datetime.now(timezone.utc),
            filled_price=1.2600,
        )
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        mock_api.send_order.return_value = filled_order

        manager = OrderManager(api_client=mock_api)
        result = manager.execute_live_order(
            symbol="GBPUSD",
            direction=TradeDirection.SHORT,
            volume=0.05,
            stop_loss=1.2650,
            take_profit=1.2500,
        )

        assert result.success is True
        assert result.position is not None
        assert result.position.stop_loss == 1.2650
        assert result.position.take_profit == 1.2500
        mock_api.send_order.assert_called_once_with(
            symbol="GBPUSD",
            direction=TradeDirection.SHORT,
            order_type=OrderType.MARKET,
            volume=0.05,
            price=None,
            stop_loss=1.2650,
            take_profit=1.2500,
            comment="",
        )

    def test_set_api_client(self):
        manager = OrderManager()
        assert manager._api_client is None

        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        manager.set_api_client(mock_api)
        assert manager._api_client is mock_api
        mock_api.register_callback.assert_called()

    def test_wire_live_callbacks_on_init(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True

        OrderManager(api_client=mock_api)

        registered_events = [
            call.args[0] for call in mock_api.register_callback.call_args_list
        ]
        assert "on_order_filled" in registered_events
        assert "on_order_rejected" in registered_events
        assert "on_order_cancelled" in registered_events

    def test_wire_live_callbacks_warns_when_not_connected(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = False

        OrderManager(api_client=mock_api)

        mock_api.register_callback.assert_not_called()

    def test_no_duplicate_on_order_filled_for_local_sync_fill(self):
        filled_order = Order(
            order_id="FIX_DUP_001",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
            status=OrderStatus.FILLED,
            filled_at=datetime.now(timezone.utc),
            filled_price=1.1005,
        )
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        mock_api.send_order.return_value = filled_order

        fill_count = []
        mock_api.register_callback = MagicMock(
            side_effect=lambda event, cb: (
                fill_count.append(cb) if event == "on_order_filled" else None
            )
        )

        manager = OrderManager(api_client=mock_api)
        result = manager.execute_live_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
        )

        assert result.success is True
        assert len(fill_count) == 1

        async_callback = fill_count[0]
        async_callback(filled_order, MagicMock())

        callbacks_fired = []
        manager.register_callback(
            "on_order_filled", lambda o: callbacks_fired.append(o)
        )
        assert len(callbacks_fired) == 0


class TestPaperTraderLiveMode:
    def _make_live_api_mock(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        filled_order = Order(
            order_id="LIVE_001",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
            status=OrderStatus.FILLED,
            filled_at=datetime.now(timezone.utc),
            filled_price=1.1005,
        )
        mock_api.send_order.return_value = filled_order
        return mock_api

    def test_is_live_mode_false_without_client(self):
        trader = PaperTrader()
        assert trader.is_live_mode is False

    def test_is_live_mode_false_with_paper_mode(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = True
        mock_api.is_connected = True
        trader = PaperTrader(api_client=mock_api)
        assert trader.is_live_mode is False

    def test_is_live_mode_true_when_connected(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        trader = PaperTrader(api_client=mock_api)
        assert trader.is_live_mode is True

    def test_process_signal_routes_to_live_in_live_mode(self):
        mock_api = self._make_live_api_mock()
        config = FTMOConfig(
            min_risk_reward=1.0,
            max_position_size_pct=2.0,
        )
        trader = PaperTrader(
            ftmo_config=config, api_client=mock_api, starting_balance=100000.0
        )
        signal = _make_signal()
        result = trader.process_signal(signal)

        assert result.success is True
        mock_api.send_order.assert_called_once()

    def test_process_signal_routes_to_paper_in_paper_mode(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = True
        mock_api.is_connected = True
        config = FTMOConfig(
            min_risk_reward=1.0,
            max_position_size_pct=2.0,
        )
        trader = PaperTrader(
            ftmo_config=config, api_client=mock_api, starting_balance=100000.0
        )
        signal = _make_signal()
        result = trader.process_signal(signal)

        assert result.success is True
        mock_api.send_order.assert_not_called()

    def test_process_signal_risk_guard_blocks_live_order(self):
        mock_api = self._make_live_api_mock()
        config = FTMOConfig(min_risk_reward=5.0)
        trader = PaperTrader(
            ftmo_config=config, api_client=mock_api, starting_balance=100000.0
        )
        signal = _make_signal(
            entry_price=1.1000,
            stop_loss=1.0990,
            take_profit_1=1.1005,
        )
        result = trader.process_signal(signal)

        assert result.success is False
        mock_api.send_order.assert_not_called()

    def test_set_api_client(self):
        trader = PaperTrader()
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        trader.set_api_client(mock_api)
        assert trader.is_live_mode is True

        mock_api_paper = MagicMock()
        mock_api_paper.is_paper_mode = True
        trader.set_api_client(mock_api_paper)
        assert trader.is_live_mode is False

    def test_live_position_tracked_after_fill(self):
        mock_api = self._make_live_api_mock()
        config = FTMOConfig(
            min_risk_reward=1.0,
            max_position_size_pct=2.0,
        )
        trader = PaperTrader(
            ftmo_config=config, api_client=mock_api, starting_balance=100000.0
        )
        signal = _make_signal()
        trader.process_signal(signal)

        positions = trader.get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "EURUSD"
        assert positions[0].volume == 0.1


class TestFIXRejectCodeIntegration:
    def test_reject_session_level_maps_code(self):
        from adapters.ctrader.api_client import FIXClient
        from adapters.ctrader.models import cTraderCredentials

        creds = cTraderCredentials(
            host="localhost",
            port=5202,
            use_ssl=False,
            sender_comp_id="test",
            username="12345",
            password="pass",
        )
        client = FIXClient(creds)
        order = Order(
            order_id="ORD_REJ",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        client._pending_orders["ORD_REJ"] = order

        msg = FIXMessage(msg_type="3")
        msg.fields[11] = "ORD_REJ"
        msg.fields[371] = "102"
        msg.fields[58] = "Margin too low"

        rejected = []
        client.register_callback(
            "on_order_rejected", lambda o, m, r: rejected.append((o, r))
        )
        client._handle_reject(msg)

        assert order.status == OrderStatus.REJECTED
        assert "Insufficient margin" in order.comment
        assert len(rejected) == 1
        assert "Margin too low" in rejected[0][1]

    def test_reject_session_level_no_clord_id(self):
        from adapters.ctrader.api_client import FIXClient
        from adapters.ctrader.models import cTraderCredentials

        creds = cTraderCredentials(
            host="localhost",
            port=5202,
            use_ssl=False,
            sender_comp_id="test",
            username="12345",
            password="pass",
        )
        client = FIXClient(creds)

        msg = FIXMessage(msg_type="3")
        msg.fields[371] = "6"
        msg.fields[58] = "Not authorized"

        client._handle_reject(msg)
        assert len(client._pending_orders) == 0


class TestFIXRejectCodeUniqueValues:
    def test_no_duplicate_enum_values(self):
        values = [code.value for code in FIXRejectCode]
        assert len(values) == len(set(values)), (
            f"Duplicate enum values found: {[v for v in values if values.count(v) > 1]}"
        )

    def test_incorrect_numingroup_count_is_99(self):
        assert FIXRejectCode.INCORRECT_NUMINGROUP_COUNT.value == 99

    def test_not_authorized_action_is_not_98(self):
        assert FIXRejectCode.NOT_AUTHORIZED_ACTION.value != 98
        assert FIXRejectCode.NOT_AUTHORIZED_ACTION.value == 198


class TestFIXClientMultipleCallbacks:
    def test_register_multiple_callbacks_same_event(self):
        from adapters.ctrader.api_client import FIXClient
        from adapters.ctrader.models import cTraderCredentials

        creds = cTraderCredentials(
            host="localhost",
            port=5202,
            use_ssl=False,
            sender_comp_id="test",
            username="12345",
            password="pass",
        )
        client = FIXClient(creds)

        calls = []
        client.register_callback("on_order_filled", lambda o, m: calls.append("first"))
        client.register_callback("on_order_filled", lambda o, m: calls.append("second"))

        order = Order(
            order_id="MULTI_001",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        client._pending_orders["MULTI_001"] = order

        msg = FIXMessage(msg_type="8")
        msg.fields[11] = "MULTI_001"
        msg.fields[150] = "F"
        msg.fields[39] = "2"
        msg.fields[31] = "1.1005"
        msg.fields[32] = "10000"

        client._handle_execution_report(msg)

        assert len(calls) == 2
        assert calls == ["first", "second"]


class TestInputValidation:
    def test_execute_live_order_rejects_empty_symbol(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        manager = OrderManager(api_client=mock_api)

        result = manager.execute_live_order(
            symbol="",
            direction=TradeDirection.LONG,
            volume=0.1,
        )
        assert result.success is False
        assert "validation_error" in result.rejection_reason

    def test_execute_live_order_rejects_zero_volume(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        manager = OrderManager(api_client=mock_api)

        result = manager.execute_live_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0,
        )
        assert result.success is False
        assert "validation_error" in result.rejection_reason

    def test_execute_live_order_rejects_negative_volume(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        manager = OrderManager(api_client=mock_api)

        result = manager.execute_live_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=-0.1,
        )
        assert result.success is False
        assert "validation_error" in result.rejection_reason

    def test_execute_live_order_rejects_limit_without_price(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        manager = OrderManager(api_client=mock_api)

        result = manager.execute_live_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            order_type=OrderType.LIMIT,
        )
        assert result.success is False
        assert "validation_error" in result.rejection_reason

    def test_send_order_returns_none_on_empty_symbol(self):
        from adapters.ctrader.api_client import FIXClient
        from adapters.ctrader.models import cTraderCredentials

        creds = cTraderCredentials(
            host="localhost",
            port=5202,
            use_ssl=False,
            sender_comp_id="test",
            username="12345",
            password="pass",
        )
        client = FIXClient(creds)
        client._send_message = MagicMock(return_value=True)

        result = client.send_order(
            symbol="",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        assert result is None

    def test_send_order_returns_none_on_zero_volume(self):
        from adapters.ctrader.api_client import FIXClient
        from adapters.ctrader.models import cTraderCredentials

        creds = cTraderCredentials(
            host="localhost",
            port=5202,
            use_ssl=False,
            sender_comp_id="test",
            username="12345",
            password="pass",
        )
        client = FIXClient(creds)
        client._send_message = MagicMock(return_value=True)

        result = client.send_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0,
        )
        assert result is None

    def test_send_order_returns_none_on_send_failure(self):
        from adapters.ctrader.api_client import FIXClient
        from adapters.ctrader.models import cTraderCredentials

        creds = cTraderCredentials(
            host="localhost",
            port=5202,
            use_ssl=False,
            sender_comp_id="test",
            username="12345",
            password="pass",
        )
        client = FIXClient(creds)
        client._send_message = MagicMock(return_value=False)

        result = client.send_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        assert result is None
        assert "EURUSD" not in client._pending_orders


class TestLiveModePersistsOnDisconnect:
    def test_live_mode_stays_true_after_disconnect(self):
        mock_api = MagicMock()
        mock_api.is_paper_mode = False
        mock_api.is_connected = True
        trader = PaperTrader(api_client=mock_api)
        assert trader.is_live_mode is True

        mock_api.is_connected = False
        assert trader.is_live_mode is True
