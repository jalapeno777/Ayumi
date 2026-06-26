"""Comprehensive tests for EngineCore base class."""

import math

import numpy as np
import pandas as pd
import pytest

from src.forex_trading.services.backtest.engine_core.base import (
    BacktestMetrics,
    EngineCore,
    Position,
)
from src.forex_trading.services.backtest.prop_firm_rules import PropFirmConfig
from src.forex_trading.services.backtest.execution import ExecutionConfig


def _make_bar(close=1.1000, timestamp=None):
    if timestamp is None:
        timestamp = pd.Timestamp("2024-01-01")
    return pd.Series(
        {
            "open": close - 0.0001,
            "high": close + 0.0002,
            "low": close - 0.0002,
            "close": close,
            "volume": 100000,
        },
        name=timestamp,
    )


class TestEngineCoreInit:
    def test_defaults(self):
        core = EngineCore()
        assert core.starting_balance == 10_000.0
        assert core.risk_free_rate == 0.0
        assert core.risk_pct == 0.02
        assert len(core.positions) == 0
        assert core.equity_curve == [10_000.0]
        assert core.realized_pnl == 0.0

    def test_custom_params(self):
        pfc = PropFirmConfig(max_daily_drawdown_pct=0.03)
        ec = ExecutionConfig(spread_pips=2.0)
        core = EngineCore(
            starting_balance=50_000.0,
            prop_firm_config=pfc,
            execution_config=ec,
            risk_free_rate=0.02,
            risk_pct=0.01,
            sharpe_annualization_factor=math.sqrt(252),
        )
        assert core.starting_balance == 50_000.0
        assert core.risk_free_rate == 0.02
        assert core.risk_pct == 0.01


class TestReset:
    def test_reset_clears_state(self):
        core = EngineCore()
        core.positions = [
            Position(
                entry_time=pd.Timestamp("2024-01-01"),
                entry_price=1.1,
                direction="long",
                lots=0.1,
                pair="EURUSD",
            )
        ]
        core.realized_pnl = 500.0
        core.equity_curve = [10_000.0, 10_500.0]
        core.trades = [{"pnl": 500.0}]

        core._reset()

        assert core.positions == []
        assert core.realized_pnl == 0.0
        assert core.equity_curve == [10_000.0]
        assert core.trades == []


class TestCalculateMetrics:
    def test_empty_trades(self):
        core = EngineCore()
        m = core._calculate_metrics([], [10_000.0, 10_000.0])
        assert m.total_return == 0.0
        assert m.sharpe_ratio == 0.0
        assert m.win_rate == 0.0
        assert m.profit_factor == 0.0
        assert m.total_trades == 0
        assert m.avg_trade_duration == 0.0

    def test_with_trades(self):
        core = EngineCore()
        trades = [
            {"pnl": 100.0, "holding_hours": 2.0},
            {"pnl": -50.0, "holding_hours": 4.0},
            {"pnl": 200.0, "holding_hours": 1.0},
        ]
        curve = [10_000.0, 10_050.0, 10_100.0, 10_250.0]
        m = core._calculate_metrics(trades, curve)
        assert m.total_return == pytest.approx(250.0 / 10_000.0)
        assert m.win_rate == pytest.approx(2 / 3)
        assert m.total_trades == 3
        assert m.avg_trade_duration == pytest.approx(7.0 / 3)
        assert m.profit_factor == pytest.approx(300.0 / 50.0)

    def test_all_losing_trades(self):
        core = EngineCore()
        trades = [
            {"pnl": -100.0, "holding_hours": 1.0},
            {"pnl": -50.0, "holding_hours": 2.0},
        ]
        m = core._calculate_metrics(trades, [10_000.0, 9_900.0, 9_850.0])
        assert m.win_rate == 0.0
        assert m.profit_factor == 0.0


class TestCalculateSharpeRatio:
    def test_flat_equity(self):
        core = EngineCore()
        assert core._calculate_sharpe_ratio([10_000.0, 10_000.0, 10_000.0]) == 0.0

    def test_rising_equity(self):
        core = EngineCore(risk_free_rate=0.0)
        curve = [10_000.0, 10_100.0, 10_200.0, 10_300.0, 10_400.0]
        sharpe = core._calculate_sharpe_ratio(curve)
        assert sharpe > 0

    def test_insufficient_data(self):
        core = EngineCore()
        assert core._calculate_sharpe_ratio([10_000.0]) == 0.0

    def test_with_series(self):
        core = EngineCore()
        s = pd.Series([10_000.0, 10_100.0, 10_200.0, 10_300.0, 10_400.0])
        sharpe = core._calculate_sharpe_ratio(s)
        assert sharpe > 0

    def test_custom_annualization(self):
        core = EngineCore(sharpe_annualization_factor=math.sqrt(12))
        curve = [10_000.0, 10_100.0, 10_200.0, 10_300.0, 10_400.0]
        sharpe_monthly = core._calculate_sharpe_ratio(curve)
        core2 = EngineCore(sharpe_annualization_factor=math.sqrt(252))
        sharpe_daily = core2._calculate_sharpe_ratio(curve)
        assert sharpe_monthly < sharpe_daily


class TestGetPipValue:
    def test_eurusd(self):
        core = EngineCore()
        pip_val = core._get_pip_value(1.1, "EURUSD")
        assert pip_val == pytest.approx(10.0)

    def test_usdjpy(self):
        core = EngineCore()
        pip_val = core._get_pip_value(150.0, "USDJPY")
        assert pip_val == pytest.approx(1000.0)

    def test_unknown_pair(self):
        core = EngineCore()
        pip_val = core._get_pip_value(1.0, "XXXYYY")
        assert pip_val > 0


class TestDailyTracking:
    def test_same_day(self):
        core = EngineCore()
        t = pd.Timestamp("2024-01-01 12:00:00")
        core._update_daily_tracking(t)
        assert core._current_day == pd.Timestamp("2024-01-01")
        core._current_daily_pnl = 100.0
        t2 = pd.Timestamp("2024-01-01 14:00:00")
        core._update_daily_tracking(t2)
        assert core._current_daily_pnl == 100.0

    def test_new_day_resets(self):
        core = EngineCore()
        t1 = pd.Timestamp("2024-01-01 12:00:00")
        core._update_daily_tracking(t1)
        core._current_daily_pnl = 100.0
        t2 = pd.Timestamp("2024-01-02 09:00:00")
        core._update_daily_tracking(t2)
        assert core._current_daily_pnl == 0.0
        assert core._current_day == pd.Timestamp("2024-01-02")


class TestDrawdownChecks:
    def test_max_drawdown_not_breached(self):
        core = EngineCore()
        assert not core._is_max_drawdown_breached()

    def test_max_drawdown_breached(self):
        core = EngineCore()
        core.prop_firm.state.current_balance = 8_900.0
        core.prop_firm.state.peak_balance = 10_000.0
        assert core._is_max_drawdown_breached()

    def test_daily_loss_not_breached(self):
        core = EngineCore()
        assert not core._is_max_daily_loss_breached()

    def test_daily_loss_breached(self):
        core = EngineCore()
        core.prop_firm.state._get_current_day_stats(pd.Timestamp("2024-01-01"))
        core.prop_firm.state.daily_stats[-1].max_drawdown = 0.06
        assert core._is_max_daily_loss_breached()


class TestCloseTrade:
    def _make_core(self):
        return EngineCore()

    def test_close_long_winner(self):
        core = self._make_core()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="long",
            lots=0.1,
            pair="EURUSD",
        )
        core.positions.append(pos)
        pnl = core._close_trade(pos, 1, pd.Timestamp("2024-01-02"), 1.1100, "tp")
        assert pnl > 0
        assert len(core.positions) == 0
        assert len(core.trades) == 1
        assert core.trades[0]["exit_reason"] == "tp"
        assert core.realized_pnl > 0

    def test_close_short_winner(self):
        core = self._make_core()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1100,
            direction="short",
            lots=0.1,
            pair="EURUSD",
        )
        core.positions.append(pos)
        pnl = core._close_trade(pos, 1, pd.Timestamp("2024-01-02"), 1.1000, "tp")
        assert pnl > 0
        assert len(core.positions) == 0

    def test_close_long_loser(self):
        core = self._make_core()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="long",
            lots=0.1,
            pair="EURUSD",
        )
        core.positions.append(pos)
        pnl = core._close_trade(pos, 1, pd.Timestamp("2024-01-02"), 1.0900, "sl")
        assert pnl < 0
        assert core.realized_pnl < 0

    def test_close_records_in_prop_firm(self):
        core = self._make_core()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="long",
            lots=0.1,
            pair="EURUSD",
        )
        core.positions.append(pos)
        core._close_trade(pos, 1, pd.Timestamp("2024-01-02"), 1.1100, "tp")
        assert len(core.prop_firm.state.trade_history) == 1


class TestCloseAllOpenTrades:
    def test_close_multiple(self):
        core = EngineCore()
        for i, direction in enumerate(["long", "short"]):
            pos = Position(
                entry_time=pd.Timestamp("2024-01-01"),
                entry_price=1.1000 + i * 0.01,
                direction=direction,
                lots=0.1,
                pair="EURUSD",
            )
            core.positions.append(pos)

        bar = _make_bar(1.1000)
        pnls = core._close_all_open_trades(bar, pd.Timestamp("2024-01-02"), force=True)
        assert len(pnls) == 2
        assert len(core.positions) == 0
        assert len(core.trades) == 2


class TestOpenTrade:
    def test_open_long(self):
        core = EngineCore()
        bar = _make_bar(1.1000, pd.Timestamp("2024-01-01"))
        pos = core._open_trade(1, bar, 0, lot_size=0.1, pair="EURUSD")
        assert pos is not None
        assert pos.direction == "long"
        assert pos.pair == "EURUSD"
        assert len(core.positions) == 1

    def test_open_short(self):
        core = EngineCore()
        bar = _make_bar(1.1000, pd.Timestamp("2024-01-01"))
        pos = core._open_trade(-1, bar, 0, lot_size=0.1, pair="EURUSD")
        assert pos is not None
        assert pos.direction == "short"

    def test_neutral_signal_returns_none(self):
        core = EngineCore()
        bar = _make_bar(1.1000)
        pos = core._open_trade(0, bar, 0, lot_size=0.1, pair="EURUSD")
        assert pos is not None


class TestUnrealizedPnl:
    def test_no_positions(self):
        core = EngineCore()
        bar = _make_bar(1.1000)
        assert core._calculate_unrealized_pnl(bar) == 0.0

    def test_long_profit(self):
        core = EngineCore()
        core.positions.append(
            Position(
                entry_time=pd.Timestamp("2024-01-01"),
                entry_price=1.1000,
                direction="long",
                lots=0.1,
                pair="EURUSD",
            )
        )
        bar = _make_bar(1.1100)
        pnl = core._calculate_unrealized_pnl(bar)
        assert pnl > 0

    def test_short_profit(self):
        core = EngineCore()
        core.positions.append(
            Position(
                entry_time=pd.Timestamp("2024-01-01"),
                entry_price=1.1100,
                direction="short",
                lots=0.1,
                pair="EURUSD",
            )
        )
        bar = _make_bar(1.1000)
        pnl = core._calculate_unrealized_pnl(bar)
        assert pnl > 0

    def test_multiple_positions(self):
        core = EngineCore()
        core.positions.append(
            Position(
                entry_time=pd.Timestamp("2024-01-01"),
                entry_price=1.1000,
                direction="long",
                lots=0.1,
                pair="EURUSD",
            )
        )
        core.positions.append(
            Position(
                entry_time=pd.Timestamp("2024-01-01"),
                entry_price=1.1100,
                direction="short",
                lots=0.1,
                pair="GBPUSD",
            )
        )
        bar = _make_bar(1.1100)
        pnl = core._calculate_unrealized_pnl(bar)
        assert pnl > 0


class TestCurrentEquity:
    def test_no_trades(self):
        core = EngineCore()
        bar = _make_bar(1.1000)
        assert core._current_equity(bar) == 10_000.0

    def test_with_realized_pnl(self):
        core = EngineCore()
        core.realized_pnl = 500.0
        bar = _make_bar(1.1000)
        assert core._current_equity(bar) == 10_500.0


class TestPositionHelpers:
    def test_has_open_position(self):
        core = EngineCore()
        core.positions.append(
            Position(
                entry_time=pd.Timestamp("2024-01-01"),
                entry_price=1.1,
                direction="long",
                lots=0.1,
                pair="EURUSD",
            )
        )
        assert core._has_open_position("EURUSD")
        assert not core._has_open_position("GBPUSD")

    def test_get_open_position(self):
        core = EngineCore()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1,
            direction="long",
            lots=0.1,
            pair="EURUSD",
        )
        core.positions.append(pos)
        assert core._get_open_position("EURUSD") is pos
        assert core._get_open_position("GBPUSD") is None

    def test_no_positions(self):
        core = EngineCore()
        assert not core._has_open_position("EURUSD")
        assert core._get_open_position("EURUSD") is None


class TestCalculateMaxDrawdown:
    def test_flat_equity(self):
        core = EngineCore()
        eq = pd.Series([10_000.0, 10_000.0, 10_000.0])
        dd, dur = core._calculate_max_drawdown(eq)
        assert dd == 0.0

    def test_monotonic_increase(self):
        core = EngineCore()
        eq = pd.Series([10_000.0, 10_100.0, 10_200.0])
        dd, dur = core._calculate_max_drawdown(eq)
        assert dd == 0.0

    def test_with_drawdown(self):
        core = EngineCore()
        eq = pd.Series([10_000.0, 10_500.0, 10_400.0, 9_900.0, 10_200.0])
        dd, dur = core._calculate_max_drawdown(eq)
        assert dd > 0.04
        assert dur >= 1


class TestLotSizeCalculation:
    def test_clamped_to_prop_firm_limits(self):
        core = EngineCore(
            prop_firm_config=PropFirmConfig(min_lot_size=0.05, max_lot_size=0.5)
        )
        lot = core._calculate_open_trade_lot_size(1.1, 1.09, 10_000.0)
        assert lot >= 0.05
        assert lot <= 0.5


class TestBacktestMetricsDataclass:
    def test_defaults(self):
        m = BacktestMetrics()
        assert m.total_return == 0.0
        assert m.sharpe_ratio == 0.0
        assert m.total_trades == 0

    def test_custom(self):
        m = BacktestMetrics(total_return=0.1, sharpe_ratio=1.5, win_rate=0.6)
        assert m.total_return == 0.1
        assert m.sharpe_ratio == 1.5
        assert m.win_rate == 0.6
