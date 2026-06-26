import pytest
from adapters.ctrader.models import (
    AccountInfo,
    MarketDataSnapshot,
    Order,
    OrderStatus,
    OrderType,
    Position,
    PositionStatus,
    TradeDirection,
    TradeSignal,
    cTraderCredentials,
)


class TestTradeDirection:
    def test_long_direction(self):
        assert TradeDirection.LONG.value == "long"

    def test_short_direction(self):
        assert TradeDirection.SHORT.value == "short"

    def test_neutral_direction(self):
        assert TradeDirection.NEUTRAL.value == "neutral"


class TestOrderType:
    def test_market_order(self):
        assert OrderType.MARKET.value == "market"

    def test_limit_order(self):
        assert OrderType.LIMIT.value == "limit"

    def test_stop_order(self):
        assert OrderType.STOP.value == "stop"


class TestOrder:
    def test_order_creation(self):
        order = Order(
            order_id="TEST_001",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.1,
        )
        assert order.order_id == "TEST_001"
        assert order.symbol == "EURUSD"
        assert order.direction == TradeDirection.LONG
        assert order.volume == 0.1
        assert order.status == OrderStatus.PENDING

    def test_order_with_prices(self):
        order = Order(
            order_id="TEST_002",
            symbol="GBPUSD",
            direction=TradeDirection.SHORT,
            order_type=OrderType.MARKET,
            volume=0.2,
            price=1.2500,
            stop_loss=1.2550,
            take_profit=1.2400,
        )
        assert order.price == 1.2500
        assert order.stop_loss == 1.2550
        assert order.take_profit == 1.2400


class TestPosition:
    def test_position_creation(self):
        position = Position(
            position_id="POS_001",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            current_price=1.1000,
        )
        assert position.position_id == "POS_001"
        assert position.status == PositionStatus.OPEN

    def test_position_pnl_calculation_long(self):
        position = Position(
            position_id="POS_002",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            current_price=1.1010,
        )
        assert position.direction == TradeDirection.LONG


class TestTradeSignal:
    def test_trade_signal_creation(self):
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1050,
            take_profit_2=1.1100,
            take_profit_3=1.1150,
            volume=0.1,
            confidence=0.85,
            rationale="Test signal",
        )
        assert signal.symbol == "EURUSD"
        assert signal.direction == TradeDirection.LONG
        assert signal.confidence == 0.85


class TestcTraderCredentials:
    def test_credentials_creation(self):
        creds = cTraderCredentials(
            host="demo-uk-eqx-01.p.c-trader.com",
            port=5211,
            use_ssl=True,
            sender_comp_id="demo.ctrader.5795523",
            password="secret",
        )
        assert creds.host == "demo-uk-eqx-01.p.c-trader.com"
        assert creds.port == 5211
        assert creds.use_ssl is True


class TestAccountInfo:
    def test_account_info_creation(self):
        info = AccountInfo(
            account_id="5795523",
            balance=100000.0,
            equity=100500.0,
            margin_used=5000.0,
            margin_available=95500.0,
        )
        assert info.balance == 100000.0
        assert info.equity == 100500.0
        assert info.is_demo is True


class TestMarketDataSnapshot:
    def test_market_data_spread(self):
        snapshot = MarketDataSnapshot(
            symbol="EURUSD",
            bid=1.0990,
            ask=1.0995,
            last=1.0992,
        )
        assert snapshot.spread == pytest.approx(0.0005, rel=1e-9)

    def test_market_data_mid(self):
        snapshot = MarketDataSnapshot(
            symbol="EURUSD",
            bid=1.0990,
            ask=1.0995,
            last=1.0992,
        )
        assert snapshot.mid == pytest.approx(1.09925, rel=1e-9)
