"""Tests for H1-H5 sentinel-default pattern fixes (AYUAA-846)."""

from datetime import datetime

import pytest

from backtest.engine import (
    BacktestConfig,
    Bar,
    ExitReason,
    TradeDirection,
    TradeOutcome,
)
from backtest.engine import SimulatedTrade, StrategySignal


# ── H1: signal_router rejects zero/None TP1 ────────────────────────────────


def test_signal_router_skips_zero_tp():
    from engine.signal_router import SignalRouter
    from engine.protocol import CanonicalSignal

    router = SignalRouter(order_manager=None, portfolio_risk=None)

    signal = CanonicalSignal(
        strategy_id="test",
        symbol="EURUSD",
        direction=TradeDirection.LONG,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=0.0,
        confidence=0.8,
        timestamp=datetime.now(),
    )
    result = router.route(signal)
    assert result.action == "invalid_signal"
    assert "take_profit_1" in result.reason


def test_signal_router_skips_none_tp():
    from engine.signal_router import SignalRouter
    from engine.protocol import CanonicalSignal

    router = SignalRouter(order_manager=None, portfolio_risk=None)

    signal = CanonicalSignal(
        strategy_id="test",
        symbol="EURUSD",
        direction=TradeDirection.LONG,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=None,
        confidence=0.8,
        timestamp=datetime.now(),
    )
    result = router.route(signal)
    assert result.action == "invalid_signal"


# ── H2: walk_forward skips zero SL distance ───────────────────────────────


def test_walk_forward_skips_zero_sl_distance():
    from quant.walk_forward import _run_strategy_window

    class _NoTPStrategy:
        name = "no_tp"
        direction = TradeDirection.LONG

        def evaluate(self, state):
            return StrategySignal(
                direction=TradeDirection.LONG,
                entry_price=1.1000,
                stop_loss=1.1000,
                take_profit_1=0.0,
                take_profit_2=0.0,
                take_profit_3=0.0,
                confidence=0.8,
                rationale="test",
            )

    bars = [
        Bar(
            time=datetime(2024, 1, 1, 10, i),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1000,
        )
        for i in range(50)
    ]

    result = _run_strategy_window(
        strategy=_NoTPStrategy(),
        test_bars=bars,
        initial_balance=10000,
        risk_per_trade_pct=0.02,
    )
    assert len(result) == 0


# ── H3: metrics exclude OPEN trades ───────────────────────────────────────


def _make_trade(outcome, pnl, entry_bar=0, exit_bar=10):
    return SimulatedTrade(
        entry_bar_index=entry_bar,
        exit_bar_index=exit_bar,
        direction=TradeDirection.LONG,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1050,
        take_profit_2=1.1100,
        take_profit_3=1.1150,
        exit_price=1.1050,
        lot_size=0.1,
        risk_amount=50,
        pips=50,
        profit_loss=pnl,
        outcome=outcome,
        exit_reason=ExitReason.TAKE_PROFIT_1,
        entry_time=datetime(2024, 1, 1),
        exit_time=datetime(2024, 1, 2),
        confidence_score=0.7,
        confluence_count=1,
        rationale="test",
    )


def test_metrics_excludes_open_trades():
    from backtest.engine import BacktestEngine

    trades = [
        _make_trade(TradeOutcome.WIN, 100),
        _make_trade(TradeOutcome.LOSS, -50),
        _make_trade(TradeOutcome.OPEN, 0),
        _make_trade(TradeOutcome.OPEN, 0),
    ]

    engine = BacktestEngine(config=BacktestConfig(starting_balance=10000))
    engine.balance = 10050
    engine.max_drawdown = 0.01
    engine.peak_balance = 10050
    engine.max_daily_loss = 0.0
    engine.total_spread_cost = 0.0
    engine.total_commission_cost = 0.0

    metrics = engine._calculate_metrics(trades, [10000, 10050], rejected_signals=0)

    assert metrics.total_trades == 2
    assert metrics.winning_trades == 1
    assert metrics.losing_trades == 1
    assert metrics.win_rate == pytest.approx(50.0)


# ── H4: legacy engine TP1 hit returns correct exit ─────────────────────────


def test_legacy_engine_tp1_hit():
    from backtest.engine import BacktestEngine

    config = BacktestConfig(starting_balance=10000)
    engine = BacktestEngine(config=config)

    trade = SimulatedTrade(
        entry_bar_index=0,
        exit_bar_index=0,
        direction=TradeDirection.LONG,
        entry_price=1.0000,
        stop_loss=0.9950,
        take_profit_1=1.0050,
        take_profit_2=1.0100,
        take_profit_3=1.0150,
        exit_price=0.0,
        lot_size=0.1,
        risk_amount=50,
        pips=0,
        profit_loss=0,
        outcome=TradeOutcome.OPEN,
        exit_reason=ExitReason.STOP_LOSS,
        entry_time=datetime(2024, 1, 1),
        exit_time=datetime(2024, 1, 1),
        confidence_score=0.7,
        confluence_count=1,
        rationale="test",
    )

    bar_tp1 = Bar(
        time=datetime(2024, 1, 1, 10, 1),
        open=1.0030,
        high=1.0060,
        low=0.9980,
        close=1.0040,
        volume=1000,
    )

    exited, price, reason = engine._check_trade_exit(trade, bar_tp1)
    assert exited is True
    assert price == 1.0050
    assert reason == ExitReason.TAKE_PROFIT_1


def test_legacy_engine_tp1_hit_short():
    from backtest.engine import BacktestEngine

    config = BacktestConfig(starting_balance=10000)
    engine = BacktestEngine(config=config)

    trade = SimulatedTrade(
        entry_bar_index=0,
        exit_bar_index=0,
        direction=TradeDirection.SHORT,
        entry_price=1.0000,
        stop_loss=1.0050,
        take_profit_1=0.9950,
        take_profit_2=0.9900,
        take_profit_3=0.9850,
        exit_price=0.0,
        lot_size=0.1,
        risk_amount=50,
        pips=0,
        profit_loss=0,
        outcome=TradeOutcome.OPEN,
        exit_reason=ExitReason.STOP_LOSS,
        entry_time=datetime(2024, 1, 1),
        exit_time=datetime(2024, 1, 1),
        confidence_score=0.7,
        confluence_count=1,
        rationale="test",
    )

    bar_tp1 = Bar(
        time=datetime(2024, 1, 1, 10, 1),
        open=0.9980,
        high=1.0010,
        low=0.9940,
        close=0.9960,
        volume=1000,
    )

    exited, price, reason = engine._check_trade_exit(trade, bar_tp1)
    assert exited is True
    assert price == 0.9950
    assert reason == ExitReason.TAKE_PROFIT_1


# ── H5: order_manager no filled_price doesn't create position ───────────────


def test_order_manager_no_filled_price():
    from adapters.ctrader.models import Order, OrderStatus, OrderType
    from adapters.ctrader.order_manager import OrderManager

    om = OrderManager()

    order = Order(
        order_id="TEST_001",
        symbol="EURUSD",
        direction=TradeDirection.LONG,
        order_type=OrderType.MARKET,
        volume=0.01,
        price=0.0,
        stop_loss=None,
        take_profit=None,
        status=OrderStatus.FILLED,
        filled_at=datetime.now(),
        filled_price=None,
        comment="test",
    )

    position = om._create_position_from_order(order)
    assert position is None
