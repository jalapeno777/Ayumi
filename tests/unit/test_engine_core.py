from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from core.config import BacktestConfig, BacktestMetrics
from core.pip import PipCalculator
from core.spread import SpreadModel
from core.types import (
    Bar,
    BarPeriod,
    ExitReason,
    MarketState,
    SessionType,
    SimulatedTrade,
    StrategySignal,
    TradeDirection,
    TradeOutcome,
)
from engine.base import EngineCore, UNITS_PER_LOT, determine_session
from engine.engine import BacktestEngine
from engine.mixins import CombineMethod, ProgressiveSLMixin


def _make_bar(
    idx: int,
    open: float = 1.1000,
    high: float = 1.1010,
    low: float = 1.0990,
    close: float = 1.1005,
) -> Bar:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc) + timedelta(hours=idx)
    return Bar(time=base, open=open, high=high, low=low, close=close)


def _make_signal(
    direction: TradeDirection = TradeDirection.LONG,
    confidence: float = 0.7,
    entry: float = 1.1000,
    sl: float = 1.0980,
    tp1: float = 1.1020,
    tp2: float = 1.1040,
    tp3: float = 1.1060,
    is_volatile: bool = False,
) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
        rationale="test",
        is_volatile=is_volatile,
    )


def _make_trade(
    direction: TradeDirection = TradeDirection.LONG,
    entry_price: float = 1.1000,
    stop_loss: float = 1.0980,
    tp1: float = 1.1020,
    tp2: float = 1.1040,
    tp3: float = 1.1060,
) -> SimulatedTrade:
    return SimulatedTrade(
        entry_bar_index=0,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
        exit_price=0.0,
        lot_size=0.1,
        risk_amount=500.0,
        pips=0.0,
        profit_loss=0.0,
        outcome=TradeOutcome.OPEN,
        entry_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        exit_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        confidence_score=0.7,
        rationale="test",
    )


class TestEngineCoreInit:
    def test_reset_state(self):
        config = BacktestConfig(starting_balance=50_000)
        core = EngineCore(config)
        assert core.balance == 50_000
        assert core.peak_balance == 50_000
        assert core.max_drawdown == 0.0
        assert core.current_day is None
        assert core.total_spread_cost == 0.0
        assert core.total_commission_cost == 0.0
        assert core.rejected_signals == 0

    def test_custom_spread_model(self):
        sm = SpreadModel(spread_pips=2.0, slippage_pips=0.5)
        config = BacktestConfig()
        core = EngineCore(config, spread_model=sm)
        assert core.spread_model.spread_pips == 2.0
        assert core.spread_model.slippage_pips == 0.5

    def test_default_spread_model(self):
        config = BacktestConfig(spread_pips=1.5, slippage_pips=0.3)
        core = EngineCore(config)
        assert core.spread_model.spread_pips == 1.5
        assert core.spread_model.slippage_pips == 0.3


class TestDailyTracking:
    def test_first_day_sets_daily_start(self):
        config = BacktestConfig()
        core = EngineCore(config)
        t = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        core._update_daily_tracking(t)
        assert core.current_day == t.date()
        assert core.daily_start_balance == config.starting_balance

    def test_new_day_records_daily_loss(self):
        config = BacktestConfig()
        core = EngineCore(config)
        core.balance = 99_000
        t1 = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
        core._update_daily_tracking(t1)
        core.daily_start_balance = 100_000
        core._update_daily_tracking(t2)
        assert core.max_daily_loss == 1000.0

    def test_same_day_no_update(self):
        config = BacktestConfig()
        core = EngineCore(config)
        core.balance = 99_000
        t = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        core._update_daily_tracking(t)
        core._update_daily_tracking(t)
        assert core.max_daily_loss == 0.0


class TestDrawdownChecks:
    def test_max_drawdown_not_breached(self):
        config = BacktestConfig(max_total_drawdown_pct=0.10)
        core = EngineCore(config)
        core.balance = 95_000
        assert not core._is_max_drawdown_breached()

    def test_max_drawdown_breached(self):
        config = BacktestConfig(max_total_drawdown_pct=0.10)
        core = EngineCore(config)
        core.balance = 89_000
        assert core._is_max_drawdown_breached()

    def test_max_daily_loss_breached(self):
        config = BacktestConfig(max_daily_drawdown_pct=0.05)
        core = EngineCore(config)
        core.daily_start_balance = 100_000
        core.balance = 94_000
        assert core._is_max_daily_loss_breached()

    def test_max_daily_loss_not_breached(self):
        config = BacktestConfig(max_daily_drawdown_pct=0.05)
        core = EngineCore(config)
        core.daily_start_balance = 100_000
        core.balance = 96_000
        assert not core._is_max_daily_loss_breached()


def _open_trade_via_core(
    core: EngineCore, signal: StrategySignal, bar: Bar, bar_index: int = 0
) -> SimulatedTrade:
    trade = core._open_trade(signal, bar, bar_index)
    assert trade is not None
    return trade


class TestCloseTrade:
    def test_close_long_winner(self):
        config = BacktestConfig()
        core = EngineCore(config)
        signal = _make_signal(entry=1.1000, sl=1.0980)
        bar = _make_bar(0)
        trade = _open_trade_via_core(core, signal, bar)
        exit_time = datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc)
        core._close_trade(trade, 10, exit_time, 1.1050, ExitReason.TAKE_PROFIT_3)
        assert trade.outcome == TradeOutcome.WIN
        assert trade.profit_loss > 0

    def test_close_short_winner(self):
        config = BacktestConfig()
        core = EngineCore(config)
        signal = _make_signal(direction=TradeDirection.SHORT, entry=1.1000, sl=1.1020)
        bar = _make_bar(0)
        trade = _open_trade_via_core(core, signal, bar)
        exit_time = datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc)
        core._close_trade(trade, 10, exit_time, 1.0950, ExitReason.TAKE_PROFIT_3)
        assert trade.outcome == TradeOutcome.WIN
        assert trade.profit_loss > 0

    def test_close_long_loser(self):
        config = BacktestConfig()
        core = EngineCore(config)
        signal = _make_signal(entry=1.1000, sl=1.0980)
        bar = _make_bar(0)
        trade = _open_trade_via_core(core, signal, bar)
        exit_time = datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc)
        core._close_trade(trade, 10, exit_time, 1.0960, ExitReason.STOP_LOSS)
        assert trade.outcome == TradeOutcome.LOSS
        assert trade.profit_loss < 0

    def test_close_updates_balance(self):
        config = BacktestConfig(starting_balance=100_000)
        core = EngineCore(config)
        signal = _make_signal(entry=1.1000, sl=1.0980)
        bar = _make_bar(0)
        trade = _open_trade_via_core(core, signal, bar)
        initial_balance = core.balance
        exit_time = datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc)
        core._close_trade(trade, 10, exit_time, 1.1050, ExitReason.TAKE_PROFIT_3)
        assert core.balance != initial_balance

    def test_close_records_spread_and_commission(self):
        config = BacktestConfig()
        core = EngineCore(config)
        signal = _make_signal(entry=1.1000, sl=1.0980)
        bar = _make_bar(0)
        trade = _open_trade_via_core(core, signal, bar)
        core._close_trade(
            trade,
            10,
            datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            1.1050,
            ExitReason.TAKE_PROFIT_3,
        )
        assert core.total_spread_cost > 0
        assert core.total_commission_cost > 0

    def test_close_updates_peak_balance(self):
        config = BacktestConfig(starting_balance=100_000)
        core = EngineCore(config)
        signal = _make_signal(entry=1.1000, sl=1.0980)
        bar = _make_bar(0)
        trade = _open_trade_via_core(core, signal, bar)
        core._close_trade(
            trade,
            10,
            datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            1.1100,
            ExitReason.TAKE_PROFIT_3,
        )
        assert core.peak_balance >= 100_000

    def test_close_zero_balance_clamped(self):
        config = BacktestConfig(starting_balance=100)
        core = EngineCore(config)
        core.balance = 100
        signal = _make_signal(entry=1.1000, sl=1.0800)
        bar = _make_bar(0)
        trade = _open_trade_via_core(core, signal, bar)
        core._close_trade(
            trade,
            10,
            datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            1.0800,
            ExitReason.STOP_LOSS,
        )
        assert core.balance >= 0


class TestCloseAllOpenTrades:
    def test_closes_all_trades(self):
        config = BacktestConfig()
        core = EngineCore(config)
        trade1 = _make_trade()
        trade2 = _make_trade()
        trade1.entry_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        trade2.entry_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        open_trades = [trade1, trade2]
        closed = core._close_all_open_trades(
            open_trades,
            100,
            datetime(2024, 1, 5, tzinfo=timezone.utc),
            1.1000,
        )
        assert len(closed) == 2
        assert len(open_trades) == 0
        assert trade1.exit_reason == ExitReason.END_OF_DATA
        assert trade2.exit_reason == ExitReason.END_OF_DATA


class TestOpenTrade:
    def test_open_long_trade(self):
        config = BacktestConfig()
        core = EngineCore(config)
        signal = _make_signal(entry=1.1000, sl=1.0980)
        bar = _make_bar(0, open=1.1000)
        trade = core._open_trade(signal, bar, 0)
        assert trade is not None
        assert trade.direction == TradeDirection.LONG
        assert trade.entry_price > 1.1000
        assert trade.lot_size > 0
        assert trade.outcome == TradeOutcome.OPEN

    def test_open_short_trade(self):
        config = BacktestConfig()
        core = EngineCore(config)
        signal = _make_signal(direction=TradeDirection.SHORT, entry=1.1000, sl=1.1020)
        bar = _make_bar(0, open=1.1000)
        trade = core._open_trade(signal, bar, 0)
        assert trade is not None
        assert trade.direction == TradeDirection.SHORT
        assert trade.entry_price < 1.1000

    def test_open_trade_zero_risk_returns_none(self):
        config = BacktestConfig()
        core = EngineCore(config)
        signal = _make_signal(entry=1.1000, sl=1.1002)
        bar = _make_bar(0)
        trade = core._open_trade(signal, bar, 0)
        assert trade is None

    def test_open_trade_custom_lot_size(self):
        config = BacktestConfig()
        core = EngineCore(config)
        signal = _make_signal()
        bar = _make_bar(0)
        trade = core._open_trade(signal, bar, 0, lot_size=0.5)
        assert trade is not None
        assert trade.lot_size == 0.5

    def test_open_trade_volatile_reduces_risk(self):
        config = BacktestConfig()
        core = EngineCore(config)
        normal_signal = _make_signal(is_volatile=False, entry=1.1000, sl=1.0980)
        volatile_signal = _make_signal(is_volatile=True, entry=1.1000, sl=1.0980)
        bar = _make_bar(0)
        normal = core._open_trade(normal_signal, bar, 0)
        core._reset()
        volatile = core._open_trade(volatile_signal, bar, 0)
        assert normal is not None and volatile is not None
        assert volatile.lot_size < normal.lot_size


class TestCalculateMetrics:
    def test_empty_trades(self):
        config = BacktestConfig()
        core = EngineCore(config)
        metrics = core._calculate_metrics([], [100_000])
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0
        assert metrics.profit_factor == 0.0

    def test_metrics_with_trades(self):
        config = BacktestConfig()
        core = EngineCore(config)
        t1 = _make_trade()
        t1.profit_loss = 500.0
        t1.outcome = TradeOutcome.WIN
        t1.exit_bar_index = 10
        t2 = _make_trade()
        t2.profit_loss = -200.0
        t2.outcome = TradeOutcome.LOSS
        t2.exit_bar_index = 20
        metrics = core._calculate_metrics([t1, t2], [100_000, 100_500, 100_300])
        assert metrics.total_trades == 2
        assert metrics.winning_trades == 1
        assert metrics.losing_trades == 1
        assert metrics.win_rate == 50.0
        assert metrics.avg_win == 500.0
        assert metrics.avg_loss == -200.0
        assert metrics.profit_factor == 2.5

    def test_profit_factor_capped_at_10(self):
        config = BacktestConfig()
        core = EngineCore(config)
        t = _make_trade()
        t.profit_loss = 500.0
        t.outcome = TradeOutcome.WIN
        t.exit_bar_index = 10
        metrics = core._calculate_metrics([t], [100_000, 100_500])
        assert metrics.profit_factor == 10.0

    def test_profit_factor_zero_when_no_trades(self):
        config = BacktestConfig()
        core = EngineCore(config)
        metrics = core._calculate_metrics([], [100_000])
        assert metrics.profit_factor == 0.0


class TestCalculateSharpeRatio:
    def test_empty_equity_curve(self):
        config = BacktestConfig()
        core = EngineCore(config)
        assert core._calculate_sharpe_ratio([]) == 0.0

    def test_single_point(self):
        config = BacktestConfig()
        core = EngineCore(config)
        assert core._calculate_sharpe_ratio([100_000]) == 0.0

    def test_flat_equity(self):
        config = BacktestConfig()
        core = EngineCore(config)
        assert core._calculate_sharpe_ratio([100_000, 100_000, 100_000]) == 0.0

    def test_positive_returns(self):
        config = BacktestConfig()
        core = EngineCore(config)
        curve = [100_000, 101_000, 102_000, 103_000]
        sharpe = core._calculate_sharpe_ratio(curve)
        assert sharpe > 0

    def test_negative_returns(self):
        config = BacktestConfig()
        core = EngineCore(config)
        curve = [100_000, 99_000, 98_000, 97_000]
        sharpe = core._calculate_sharpe_ratio(curve)
        assert sharpe < 0

    def test_uses_annualization_factor(self):
        config = BacktestConfig(sharpe_annualization_factor=252.0)
        core = EngineCore(config)
        curve = [100_000, 101_000, 99_000, 101_000]
        sharpe = core._calculate_sharpe_ratio(curve)
        assert sharpe > 0

    def test_different_annualization_changes_sharpe(self):
        core252 = EngineCore(BacktestConfig(sharpe_annualization_factor=252.0))
        core100 = EngineCore(BacktestConfig(sharpe_annualization_factor=100.0))
        curve = [100_000, 101_000, 99_000, 101_000, 100_500]
        s252 = core252._calculate_sharpe_ratio(curve)
        s100 = core100._calculate_sharpe_ratio(curve)
        assert s252 != s100


class TestProgressiveSLMixin:
    def _make_mixin(self):
        config = BacktestConfig()
        return ProgressiveSLMixin(config)

    def test_sl_moves_to_be_at_tp1_long(self):
        mixin = self._make_mixin()
        trade = _make_trade(direction=TradeDirection.LONG, entry_price=1.1000)
        bar = Bar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.1000,
            high=1.1025,
            low=1.0990,
            close=1.1020,
        )
        mixin._progressive_sl_update(trade, bar)
        assert trade._sl_moved_to_be is True
        assert trade.stop_loss >= trade.entry_price

    def test_sl_moves_to_tp1_at_tp2_long(self):
        mixin = self._make_mixin()
        trade = _make_trade(
            direction=TradeDirection.LONG, entry_price=1.1000, tp2=1.1040, tp1=1.1020
        )
        bar = Bar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.1000,
            high=1.1050,
            low=1.0990,
            close=1.1040,
        )
        mixin._progressive_sl_update(trade, bar)
        assert trade._sl_moved_to_tp1 is True
        assert trade.stop_loss == trade.take_profit_1

    def test_check_exit_stop_loss_long(self):
        mixin = self._make_mixin()
        trade = _make_trade(
            direction=TradeDirection.LONG, entry_price=1.1000, stop_loss=1.0980
        )
        bar = Bar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.0990,
            high=1.0995,
            low=1.0970,
            close=1.0980,
        )
        hit, price, reason = mixin._check_trade_exit(trade, bar)
        assert hit is True
        assert reason == ExitReason.STOP_LOSS
        assert price == 1.0980

    def test_check_exit_tp1_long(self):
        mixin = self._make_mixin()
        trade = _make_trade(
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            tp1=1.1020,
            tp2=1.1040,
            tp3=1.1060,
        )
        bar = Bar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.1000,
            high=1.1025,
            low=1.0995,
            close=1.1020,
        )
        hit, price, reason = mixin._check_trade_exit(trade, bar)
        assert hit is True
        assert reason == ExitReason.TAKE_PROFIT_1

    def test_check_exit_tp3_long(self):
        mixin = self._make_mixin()
        trade = _make_trade(direction=TradeDirection.LONG)
        bar = Bar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.1000,
            high=1.1070,
            low=1.0995,
            close=1.1060,
        )
        hit, price, reason = mixin._check_trade_exit(trade, bar)
        assert hit is True
        assert reason == ExitReason.TAKE_PROFIT_3

    def test_no_exit(self):
        mixin = self._make_mixin()
        trade = _make_trade(direction=TradeDirection.LONG)
        bar = Bar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1000,
        )
        hit, price, reason = mixin._check_trade_exit(trade, bar)
        assert hit is False

    def test_short_stop_loss(self):
        mixin = self._make_mixin()
        trade = _make_trade(
            direction=TradeDirection.SHORT, entry_price=1.1000, stop_loss=1.1020
        )
        bar = Bar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.1010,
            high=1.1030,
            low=1.1000,
            close=1.1020,
        )
        hit, price, reason = mixin._check_trade_exit(trade, bar)
        assert hit is True
        assert reason == ExitReason.STOP_LOSS

    def test_short_tp1(self):
        mixin = self._make_mixin()
        trade = _make_trade(
            direction=TradeDirection.SHORT,
            entry_price=1.1000,
            tp1=1.0980,
            tp2=1.0960,
            tp3=1.0940,
            stop_loss=1.1020,
        )
        bar = Bar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.1000,
            high=1.1005,
            low=1.0970,
            close=1.0980,
        )
        hit, price, reason = mixin._check_trade_exit(trade, bar)
        assert hit is True
        assert reason == ExitReason.TAKE_PROFIT_1

    def test_sl_moves_to_be_at_tp1_short(self):
        mixin = self._make_mixin()
        trade = _make_trade(
            direction=TradeDirection.SHORT,
            entry_price=1.1000,
            tp1=1.0980,
            tp2=1.0960,
            tp3=1.0940,
            stop_loss=1.1020,
        )
        bar = Bar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.1000,
            high=1.1005,
            low=1.0975,
            close=1.0980,
        )
        mixin._progressive_sl_update(trade, bar)
        assert trade._sl_moved_to_be is True
        assert trade.stop_loss <= trade.entry_price


class TestCombinedSignalMixin:
    def test_combine_weighted_long(self):
        engine = BacktestEngine(
            BacktestConfig(),
            strategies=[],
        )
        signals = [
            _make_signal(direction=TradeDirection.LONG, confidence=0.8, entry=1.1000),
            _make_signal(direction=TradeDirection.LONG, confidence=0.6, entry=1.1005),
        ]
        combined = engine._combine_signals(signals, CombineMethod.WEIGHTED)
        assert combined is not None
        assert combined.direction == TradeDirection.LONG
        assert combined.confidence == 0.7

    def test_combine_weighted_short_wins(self):
        engine = BacktestEngine(
            BacktestConfig(),
            strategies=[],
        )
        signals = [
            _make_signal(direction=TradeDirection.LONG, confidence=0.4),
            _make_signal(direction=TradeDirection.SHORT, confidence=0.8),
        ]
        combined = engine._combine_signals(signals, CombineMethod.WEIGHTED)
        assert combined is not None
        assert combined.direction == TradeDirection.SHORT

    def test_combine_below_threshold(self):
        engine = BacktestEngine(
            BacktestConfig(min_confidence=0.7),
            strategies=[],
        )
        signals = [
            _make_signal(direction=TradeDirection.LONG, confidence=0.3),
            _make_signal(direction=TradeDirection.LONG, confidence=0.35),
        ]
        combined = engine._combine_signals(signals, CombineMethod.WEIGHTED)
        assert combined is None

    def test_combine_empty(self):
        engine = BacktestEngine(BacktestConfig(), strategies=[])
        assert engine._combine_signals([]) is None

    def test_combine_voted_long_wins(self):
        engine = BacktestEngine(BacktestConfig(), strategies=[])
        signals = [
            _make_signal(direction=TradeDirection.LONG),
            _make_signal(direction=TradeDirection.LONG),
            _make_signal(direction=TradeDirection.SHORT),
        ]
        combined = engine._combine_signals(signals, CombineMethod.VOTED)
        assert combined is not None
        assert combined.direction == TradeDirection.LONG

    def test_combine_best(self):
        engine = BacktestEngine(BacktestConfig(), strategies=[])
        signals = [
            _make_signal(direction=TradeDirection.LONG, confidence=0.5),
            _make_signal(direction=TradeDirection.SHORT, confidence=0.9),
        ]
        combined = engine._combine_signals(signals, CombineMethod.BEST)
        assert combined is not None
        assert combined.direction == TradeDirection.SHORT
        assert combined.confidence == 0.9


class TestDetermineSession:
    def test_asian(self):
        t = datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc)
        assert determine_session(t) == "asian"

    def test_london(self):
        t = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        assert determine_session(t) == "london"

    def test_ny_am(self):
        t = datetime(2024, 1, 1, 14, 0, tzinfo=timezone.utc)
        assert determine_session(t) == "ny_am"

    def test_ny_pm(self):
        t = datetime(2024, 1, 1, 18, 0, tzinfo=timezone.utc)
        assert determine_session(t) == "ny_pm"

    def test_outside(self):
        t = datetime(2024, 1, 1, 21, 0, tzinfo=timezone.utc)
        assert determine_session(t) == "outside"

    def test_non_utc_converted(self):
        from datetime import timedelta as td

        t = datetime(2024, 1, 1, 15, 0, tzinfo=timezone(td(hours=5)))
        assert determine_session(t) == "london"


class TestBacktestEngineRunSingle:
    def test_run_single_with_mock_strategy(self):
        class AlwaysLongStrategy:
            name = "always_long"

            def evaluate(self, state: MarketState) -> StrategySignal:
                bar = state.latest_bar
                if bar.high > bar.low:
                    return _make_signal(
                        entry=bar.close,
                        sl=bar.close - 0.0020,
                        tp1=bar.close + 0.0010,
                        tp2=bar.close + 0.0020,
                        tp3=bar.close + 0.0030,
                    )
                return None

        config = BacktestConfig(min_bars_before_signal=5, max_open_trades=1)
        engine = BacktestEngine(config, strategies=[AlwaysLongStrategy()])
        bars = [_make_bar(i) for i in range(100)]
        metrics = engine.run_single(AlwaysLongStrategy(), bars)
        assert isinstance(metrics, BacktestMetrics)
        assert metrics.starting_balance == config.starting_balance

    def test_run_single_too_few_bars_raises(self):
        class DummyStrategy:
            name = "dummy"

            def evaluate(self, state):
                return None

        config = BacktestConfig(min_bars_before_signal=50)
        engine = BacktestEngine(config, strategies=[DummyStrategy()])
        with pytest.raises(ValueError):
            engine.run_single(DummyStrategy(), [_make_bar(0)])


class TestBacktestEngineRunAll:
    def test_run_all_strategies(self):
        class Strat1:
            name = "s1"

            def evaluate(self, state):
                return None

        class Strat2:
            name = "s2"

            def evaluate(self, state):
                return None

        config = BacktestConfig(min_bars_before_signal=5)
        engine = BacktestEngine(config, strategies=[Strat1(), Strat2()])
        bars = [_make_bar(i) for i in range(100)]
        results = engine.run_all(bars)
        assert "s1" in results
        assert "s2" in results
        for metrics in results.values():
            assert isinstance(metrics, BacktestMetrics)


class TestBacktestEngineRunCombined:
    def test_run_combined(self):
        class LongStrat:
            name = "long"

            def evaluate(self, state):
                bar = state.latest_bar
                return _make_signal(entry=bar.close, confidence=0.7)

        class ShortStrat:
            name = "short"

            def evaluate(self, state):
                bar = state.latest_bar
                return _make_signal(
                    direction=TradeDirection.SHORT, entry=bar.close, confidence=0.8
                )

        config = BacktestConfig(min_bars_before_signal=5, max_open_trades=1)
        engine = BacktestEngine(config, strategies=[LongStrat(), ShortStrat()])
        bars = [_make_bar(i) for i in range(100)]
        metrics = engine.run_combined(bars, CombineMethod.WEIGHTED)
        assert isinstance(metrics, BacktestMetrics)
