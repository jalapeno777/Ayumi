from datetime import datetime, timedelta, timezone

import pytest
pytest.skip("adapters.ctrader.session_range_gbpusd module removed", allow_module_level=True)

from backtest.engine import (
    Bar,
    MarketState,
    SessionType,
    TradeDirection,
    StrategySignal,
)
from backtest.strategies import ISignalStrategy

from adapters.ctrader.models import (
    TradeDirection as CTraderDirection,
)
from adapters.ctrader.paper_trader import PaperTrader
from adapters.ctrader.signal_adapter import cTraderSignalAdapter
from adapters.ctrader.trade_logger import TradeLogger
from adapters.ctrader.session_range_gbpusd import (
    build_gbpusd_paper_trader,
    GBPUSD_FTMO_CONFIG,
    GBPUSD_POSITION_CONFIG,
    SYMBOL,
    SessionRangeGBPUSDConfig,
)


class _StubStrategy(ISignalStrategy):
    def __init__(self, signal=None):
        self._signal = signal
        self.evaluate_called = False

    @property
    def name(self) -> str:
        return "Stub"

    def evaluate(self, state):
        self.evaluate_called = True
        return self._signal


def _make_bars(count=70, base_time=None, session_hours=None):
    if base_time is None:
        base_time = datetime(2026, 4, 6, 3, 0, tzinfo=timezone.utc)
    if session_hours is None:
        session_hours = range(7, 11)
    bars = []
    price = 1.26000
    for i in range(count):
        t = base_time + timedelta(hours=i)
        if t.hour not in session_hours:
            t = t.replace(hour=session_hours[i % len(session_hours)])
        bar = Bar(
            time=t,
            open=price,
            high=price + 0.00030,
            low=price - 0.00030,
            close=price,
            volume=1000,
        )
        bars.append(bar)
        price += 0.00005
    return bars


def _make_backtest_signal(direction=TradeDirection.LONG):
    return StrategySignal(
        direction=direction,
        confidence=0.75,
        entry_price=1.26000,
        stop_loss=1.25800,
        take_profit_1=1.26200,
        take_profit_2=1.26400,
        take_profit_3=1.26400,
        rationale="test signal",
    )


class TestGBPUSDFTMOConfig:
    def test_daily_loss_limit_5pct(self):
        assert GBPUSD_FTMO_CONFIG.daily_loss_limit_pct == 0.05

    def test_total_drawdown_limit_10pct(self):
        assert GBPUSD_FTMO_CONFIG.total_drawdown_limit_pct == 0.10

    def test_max_positions_1(self):
        assert GBPUSD_FTMO_CONFIG.max_positions == 1

    def test_max_trades_per_day_5(self):
        assert GBPUSD_FTMO_CONFIG.max_trades_per_day == 5

    def test_min_risk_reward_1_0(self):
        assert GBPUSD_FTMO_CONFIG.min_risk_reward == 1.0

    def test_max_position_size_pct(self):
        assert GBPUSD_FTMO_CONFIG.max_position_size_pct == 0.50


class TestGBPUSDPositionConfig:
    def test_risk_per_trade_0_5pct(self):
        assert GBPUSD_POSITION_CONFIG.risk_per_trade_pct == 0.005

    def test_max_lot_0_5(self):
        assert GBPUSD_POSITION_CONFIG.max_lot_size == 0.5

    def test_min_lot_0_01(self):
        assert GBPUSD_POSITION_CONFIG.min_lot_size == 0.01


class TestBuildGBPUSDPaperTrader:
    def test_returns_trader_adapter_logger(self):
        strategy = _StubStrategy()
        trader, adapter, tlogger = build_gbpusd_paper_trader(strategy)
        assert isinstance(trader, PaperTrader)
        assert isinstance(adapter, cTraderSignalAdapter)
        assert isinstance(tlogger, TradeLogger)

    def test_adapter_uses_gbpusd_symbol(self):
        strategy = _StubStrategy()
        _, adapter, _ = build_gbpusd_paper_trader(strategy)
        assert adapter.strategy_name == "Stub"

    def test_trader_balance(self):
        strategy = _StubStrategy()
        trader, _, _ = build_gbpusd_paper_trader(
            strategy,
            SessionRangeGBPUSDConfig(starting_balance=50000.0),
        )
        assert trader.balance == 50000.0

    def test_trader_not_live(self):
        strategy = _StubStrategy()
        trader, _, _ = build_gbpusd_paper_trader(strategy)
        assert trader.is_live_mode is False

    def test_callbacks_registered(self):
        strategy = _StubStrategy()
        trader, _, _ = build_gbpusd_paper_trader(strategy)
        stats = trader.get_stats()
        assert stats.starting_balance == 100000.0


class TestSessionRangeGBPSUSDWiring:
    def test_signal_flows_through_adapter(self):
        signal = _make_backtest_signal()
        strategy = _StubStrategy(signal=signal)
        trader, adapter, tlogger = build_gbpusd_paper_trader(strategy)

        bars = _make_bars(70)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = adapter.evaluate_and_trade(state)

        assert strategy.evaluate_called
        assert result is not None
        assert result.symbol == SYMBOL
        assert result.direction == CTraderDirection.LONG

    def test_no_signal_returns_none(self):
        strategy = _StubStrategy(signal=None)
        trader, adapter, tlogger = build_gbpusd_paper_trader(strategy)

        bars = _make_bars(70)
        state = MarketState(bars=bars)
        result = adapter.evaluate_and_trade(state)

        assert strategy.evaluate_called
        assert result is None

    def test_low_confidence_signal_filtered(self):
        signal = _make_backtest_signal()
        signal.confidence = 0.30
        strategy = _StubStrategy(signal=signal)
        trader, adapter, tlogger = build_gbpusd_paper_trader(
            strategy,
            SessionRangeGBPUSDConfig(min_confidence=0.50),
        )

        bars = _make_bars(70)
        state = MarketState(bars=bars)
        result = adapter.evaluate_and_trade(state)

        assert result is None

    def test_paper_trade_creates_position(self):
        signal = _make_backtest_signal()
        strategy = _StubStrategy(signal=signal)
        trader, adapter, tlogger = build_gbpusd_paper_trader(strategy)

        bars = _make_bars(70)
        state = MarketState(bars=bars)
        adapter.evaluate_and_trade(state)

        positions = trader.get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == SYMBOL

    def test_trade_logged_on_execution(self):
        signal = _make_backtest_signal()
        strategy = _StubStrategy(signal=signal)
        trader, adapter, tlogger = build_gbpusd_paper_trader(strategy)

        bars = _make_bars(70)
        state = MarketState(bars=bars)
        adapter.evaluate_and_trade(state)

        summary = tlogger.get_summary()
        assert summary["open_positions"] == 1

    def test_pnl_tracking_after_close(self):
        signal = _make_backtest_signal()
        strategy = _StubStrategy(signal=signal)
        trader, adapter, tlogger = build_gbpusd_paper_trader(strategy)

        bars = _make_bars(70)
        state = MarketState(bars=bars)
        adapter.evaluate_and_trade(state)

        positions = trader.get_open_positions()
        assert len(positions) == 1

        trader.close_position(positions[0].position_id, 1.26100, "test_close")

        stats = trader.get_stats()
        assert stats.realized_pnl > 0

        summary = tlogger.get_summary()
        assert summary["total_trades"] == 1
        assert summary["wins"] == 1

    def test_risk_guard_allows_within_limits(self):
        config = SessionRangeGBPUSDConfig()
        strategy = _StubStrategy()
        trader, adapter, tlogger = build_gbpusd_paper_trader(strategy, config)

        bars = _make_bars(70)
        state = MarketState(bars=bars)

        strategy._signal = _make_backtest_signal()
        result = adapter.evaluate_and_trade(state)

        assert result is not None
        assert result.symbol == SYMBOL

        stats = trader.get_stats()
        assert stats.trades_executed == 1
        assert stats.signals_blocked_by_risk == 0


class TestTradeLogger:
    def test_summary_empty(self):
        tlogger = TradeLogger(strategy_name="test")
        summary = tlogger.get_summary()
        assert summary["total_trades"] == 0
        assert summary["wins"] == 0

    def test_log_and_summarize(self, tmp_path):
        tlogger = TradeLogger(log_dir=str(tmp_path), strategy_name="test")
        from adapters.ctrader.models import Order, OrderStatus, Position, PositionStatus

        order = Order(
            order_id="ORD_1",
            symbol="GBPUSD",
            direction=CTraderDirection.LONG,
            order_type=Order.__dataclass_fields__["order_type"].default,
            volume=0.1,
            filled_price=1.26000,
            stop_loss=1.25950,
            take_profit=1.26050,
            status=OrderStatus.FILLED,
            comment="test",
        )
        pos = Position(
            position_id="POS_1",
            symbol="GBPUSD",
            direction=CTraderDirection.LONG,
            volume=0.1,
            entry_price=1.26000,
            current_price=1.26100,
            stop_loss=1.25950,
            take_profit=1.26050,
            unrealized_pnl=10.0,
            status=PositionStatus.OPEN,
        )
        tlogger.log_trade_opened(order, pos)

        pos.status = PositionStatus.CLOSED
        pos.closed_price = 1.26100
        pos.closed_pnl = 10.0
        pos.closed_at = datetime.now(timezone.utc)
        tlogger.log_position_closed(pos)

        summary = tlogger.get_summary()
        assert summary["total_trades"] == 1
        assert summary["wins"] == 1
        assert summary["total_pnl"] == 10.0

        files = list(tmp_path.glob("*.csv"))
        assert len(files) == 1
