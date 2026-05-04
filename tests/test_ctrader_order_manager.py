from adapters.ctrader.models import PositionStatus, TradeDirection
from adapters.ctrader.order_manager import (
    OrderExecutionResult,
    OrderManager,
    PositionSizeConfig,
)


class TestPositionSizeConfig:
    def test_default_config(self):
        config = PositionSizeConfig()
        assert config.risk_per_trade_pct == 0.005
        assert config.max_lot_size == 1.0
        assert config.min_lot_size == 0.01
        assert config.default_lot_size == 0.1

    def test_custom_config(self):
        config = PositionSizeConfig(
            risk_per_trade_pct=0.01,
            max_lot_size=0.5,
            min_lot_size=0.02,
        )
        assert config.risk_per_trade_pct == 0.01
        assert config.max_lot_size == 0.5
        assert config.min_lot_size == 0.02


class TestOrderExecutionResult:
    def test_success_result(self):
        result = OrderExecutionResult(success=True)
        assert result.success is True
        assert result.error_message == ""

    def test_failure_result(self):
        result = OrderExecutionResult(success=False, error_message="Order rejected")
        assert result.success is False
        assert result.error_message == "Order rejected"


class TestOrderManager:
    def test_initialization(self):
        manager = OrderManager()
        assert manager.position_count == 0

    def test_initialization_with_config(self):
        config = PositionSizeConfig(max_lot_size=0.5)
        manager = OrderManager(position_config=config)
        assert manager.position_count == 0

    def test_calculate_position_size_standard_pair(self):
        manager = OrderManager()
        volume = manager.calculate_position_size(
            account_balance=100000.0,
            entry_price=1.1000,
            stop_loss=1.0950,
            symbol="EURUSD",
        )
        assert 0.01 <= volume <= 1.0

    def test_calculate_position_size_jpy_pair(self):
        manager = OrderManager()
        volume = manager.calculate_position_size(
            account_balance=100000.0,
            entry_price=110.00,
            stop_loss=109.50,
            symbol="USDJPY",
        )
        assert 0.01 <= volume <= 1.0

    def test_calculate_position_size_zero_sl_distance(self):
        manager = OrderManager()
        volume = manager.calculate_position_size(
            account_balance=100000.0,
            entry_price=1.1000,
            stop_loss=1.1000,
            symbol="EURUSD",
        )
        assert volume == manager._position_config.default_lot_size

    def test_calculate_position_size_respects_max_lot(self):
        config = PositionSizeConfig(max_lot_size=0.1)
        manager = OrderManager(position_config=config)
        volume = manager.calculate_position_size(
            account_balance=1000000.0,
            entry_price=1.1000,
            stop_loss=1.0950,
            symbol="EURUSD",
        )
        assert volume <= config.max_lot_size

    def test_execute_paper_order(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            comment="Test",
        )
        assert result.success is True
        assert result.position is not None
        assert result.position.symbol == "EURUSD"
        assert result.position.volume == 0.1

    def test_execute_market_order(self):
        manager = OrderManager()
        result = manager.execute_market_order(
            symbol="EURUSD",
            direction=TradeDirection.SHORT,
            volume=0.1,
            stop_loss=1.1050,
            take_profit=1.0900,
        )
        assert result.success is True
        assert result.order is not None

    def test_get_open_positions_empty(self):
        manager = OrderManager()
        positions = manager.get_open_positions()
        assert len(positions) == 0

    def test_get_open_positions_after_trade(self):
        manager = OrderManager()
        manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        positions = manager.get_open_positions()
        assert len(positions) == 1

    def test_close_position(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        position_id = result.position.position_id
        closed = manager.close_position(position_id, 1.1050, "manual")
        assert closed is not None
        assert closed.status == PositionStatus.CLOSED
        assert closed.closed_pnl != 0

    def test_close_nonexistent_position(self):
        manager = OrderManager()
        closed = manager.close_position("NONEXISTENT", 1.1050)
        assert closed is None

    def test_update_position(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        position_id = result.position.position_id
        updated = manager.update_position(position_id, 1.1050)
        assert updated is not None
        assert updated.current_price == 1.1050

    def test_get_position(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        position_id = result.position.position_id
        position = manager.get_position(position_id)
        assert position is not None
        assert position.position_id == position_id

    def test_get_total_unrealized_pnl(self):
        manager = OrderManager()
        manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        pnl = manager.get_total_unrealized_pnl()
        assert isinstance(pnl, float)

    def test_register_callback(self):
        manager = OrderManager()
        called = []
        manager.register_callback("on_order_filled", lambda o: called.append(o))
        manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
        )
        assert len(called) == 1

    def test_update_position_with_bid_ask_uses_bid_for_long_unrealized_pnl(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        position_id = result.position.position_id
        actual_entry = result.position.entry_price
        updated = manager.update_position(position_id, 1.1050, bid=1.1048, ask=1.1052)
        assert updated is not None
        expected_pnl = (1.1048 - actual_entry) * 0.1 * 100000
        assert abs(updated.unrealized_pnl - expected_pnl) < 0.01

    def test_update_position_with_bid_ask_uses_ask_for_short_unrealized_pnl(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.SHORT,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.1050,
        )
        position_id = result.position.position_id
        actual_entry = result.position.entry_price
        updated = manager.update_position(position_id, 1.0950, bid=1.0948, ask=1.0952)
        assert updated is not None
        expected_pnl = (actual_entry - 1.0952) * 0.1 * 100000
        assert abs(updated.unrealized_pnl - expected_pnl) < 0.01

    def test_update_position_without_bid_ask_falls_back_to_mid_price(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
        )
        position_id = result.position.position_id
        actual_entry = result.position.entry_price
        updated = manager.update_position(position_id, 1.1050)
        assert updated is not None
        expected_pnl = (1.1050 - actual_entry) * 0.1 * 100000
        assert abs(updated.unrealized_pnl - expected_pnl) < 0.01

    def test_stop_loss_triggers_with_real_bid_for_long(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        position_id = result.position.position_id
        updated = manager.update_position(position_id, 1.0949, bid=1.0948, ask=1.0952)
        assert updated is not None
        assert updated.status == PositionStatus.CLOSED
        assert abs(updated.closed_price - 1.0948) < 0.0001

    def test_stop_loss_triggers_with_real_ask_for_short(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.SHORT,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.1050,
        )
        position_id = result.position.position_id
        updated = manager.update_position(position_id, 1.1051, bid=1.1048, ask=1.1052)
        assert updated is not None
        assert updated.status == PositionStatus.CLOSED
        assert abs(updated.closed_price - 1.1052) < 0.0001

    def test_stop_loss_does_not_trigger_with_zero_bid_ask(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        position_id = result.position.position_id
        updated = manager.update_position(position_id, 1.0940, bid=0, ask=0)
        assert updated is not None
        assert updated.status == PositionStatus.OPEN

    def test_take_profit_triggers_with_real_ask_for_long(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        position_id = result.position.position_id
        updated = manager.update_position(position_id, 1.1099, bid=1.1098, ask=1.1102)
        assert updated is not None
        assert updated.status == PositionStatus.CLOSED
        assert abs(updated.closed_price - 1.1102) < 0.0001

    def test_take_profit_triggers_with_real_bid_for_short(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.SHORT,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.1050,
            take_profit=1.0900,
        )
        position_id = result.position.position_id
        updated = manager.update_position(position_id, 1.0901, bid=1.0898, ask=1.0902)
        assert updated is not None
        assert updated.status == PositionStatus.CLOSED
        assert abs(updated.closed_price - 1.0898) < 0.0001

    def test_paper_fill_long_uses_real_ask_with_slippage(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            bid=1.10500,
            ask=1.10520,
        )
        assert result.success
        assert result.order.filled_price >= 1.10520
        assert result.order.filled_price < 1.10520 + 0.0003

    def test_paper_fill_short_uses_real_bid_with_slippage(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.SHORT,
            volume=0.1,
            entry_price=1.1100,
            stop_loss=1.1150,
            take_profit=1.1000,
            bid=1.10980,
            ask=1.11000,
        )
        assert result.success
        assert result.order.filled_price <= 1.10980
        assert result.order.filled_price > 1.10980 - 0.0003

    def test_paper_fill_without_bid_ask_falls_back_to_signal_price(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert result.success
        assert result.order.filled_price >= 1.1000

    def test_paper_fill_zero_bid_ask_falls_back_to_signal_price(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
            bid=0.0,
            ask=0.0,
        )
        assert result.success
        assert result.order.filled_price >= 1.1000

    def test_paper_fill_real_ask_ignores_stale_signal_price(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.0900,
            stop_loss=1.0850,
            bid=1.10500,
            ask=1.10520,
        )
        assert result.success
        assert result.order.filled_price > 1.10500
        assert result.order.filled_price < 1.10520 + 0.0003
