"""Comprehensive tests for EngineCore base class.

These tests cover the post-refactor EngineCore in ``engine.base``.
Key API differences from the old test suite:
- ``EngineCore.__init__`` now requires ``config: BacktestConfig``.
- ``Position`` was removed — trades are ``SimulatedTrade`` objects.
- ``PropFirmConfig`` was replaced by ``BacktestConfig.max_*_drawdown_pct``.
- ``ExecutionConfig`` was folded into ``BacktestConfig`` fields.
- The metrics object is ``BacktestMetrics`` from ``core.config`` and uses
  ``total_pnl``/``total_pnl_pct`` rather than ``total_return``.
"""

from __future__ import annotations  # noqa: I001

from datetime import datetime, timedelta

import pytest

from core.config import BacktestConfig, BacktestMetrics
from core.spread import SpreadModel
from core.types import (
    Bar,
    BarPeriod,
    ExitReason,
    SimulatedTrade,
    TradeDirection,
    TradeOutcome,
)
from engine.base import EngineCore, UNITS_PER_LOT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(
    close: float = 1.1000,
    timestamp: datetime | None = None,
    high: float | None = None,
    low: float | None = None,
) -> Bar:
    """Build a Bar object using the current ``core.types.Bar`` shape."""
    if timestamp is None:
        timestamp = datetime(2024, 1, 1, 10, 0)
    return Bar(
        time=timestamp,
        open=close - 0.0001,
        high=high if high is not None else close + 0.0002,
        low=low if low is not None else close - 0.0002,
        close=close,
        volume=100_000,
        period=BarPeriod.H1,
    )


def _make_signal(
    direction: TradeDirection = TradeDirection.LONG,
    entry: float = 1.1000,
    sl: float = 1.0950,
    tp1: float = 1.1100,
    tp2: float = 1.1150,
    tp3: float = 1.1200,
    confidence: float = 0.7,
) -> "SimulatedTrade":
    """Helper to fabricate a SimulatedTrade via _open_trade."""
    # Not a factory of signals — we build signal-equivalent inputs in tests
    # that need them. This helper exists so call sites that need a trade
    # object can use a uniform pattern.
    return SimulatedTrade(
        entry_bar_index=0,
        direction=direction,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestEngineCoreInit:
    def test_defaults(self):
        """Default BacktestConfig wires through EngineCore cleanly."""
        core = EngineCore(BacktestConfig())
        assert core.balance == 100_000.0
        assert core.config.starting_balance == 100_000.0
        assert core.config.max_daily_drawdown_pct == pytest.approx(0.05)
        assert core.config.max_total_drawdown_pct == pytest.approx(0.10)

    def test_custom_config(self):
        cfg = BacktestConfig(
            starting_balance=50_000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.03,
            max_total_drawdown_pct=0.06,
        )
        core = EngineCore(cfg)
        assert core.config.starting_balance == 50_000.0
        assert core.config.risk_per_trade_pct == pytest.approx(0.01)
        assert core.config.max_daily_drawdown_pct == pytest.approx(0.03)
        assert core.config.max_total_drawdown_pct == pytest.approx(0.06)

    def test_spread_model_override(self):
        """A custom SpreadModel is honored on the instance."""
        core = EngineCore(BacktestConfig(), SpreadModel(spread_pips=2.5, slippage_pips=0.3))
        assert isinstance(core.spread_model, SpreadModel)
        assert core.spread_model.spread_pips == pytest.approx(2.5)
        assert core.spread_model.slippage_pips == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_state(self):
        core = EngineCore(BacktestConfig(starting_balance=10_000.0))
        # Mutate state to simulate post-trade values
        core.balance = 9_000.0
        core.peak_balance = 11_000.0
        core.max_drawdown = 0.15
        core.max_daily_loss = 200.0
        core.total_spread_cost = 12.5
        core.total_commission_cost = 4.0
        core.rejected_signals = 3

        core._reset()

        assert core.balance == 10_000.0
        assert core.peak_balance == 10_000.0
        assert core.max_drawdown == 0.0
        assert core.max_daily_loss == 0.0
        assert core.total_spread_cost == 0.0
        assert core.total_commission_cost == 0.0
        assert core.rejected_signals == 0


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestCalculateMetrics:
    def test_empty_trades(self):
        core = EngineCore(BacktestConfig(starting_balance=10_000.0))
        m = core._calculate_metrics([], [10_000.0, 10_000.0])
        assert isinstance(m, BacktestMetrics)
        assert m.total_pnl == 0.0
        assert m.total_pnl_pct == 0.0
        assert m.sharpe_ratio == 0.0
        assert m.win_rate == 0.0
        assert m.profit_factor == 0.0
        assert m.total_trades == 0
        assert m.avg_holding_bars == 0.0
        assert m.winning_trades == 0
        assert m.losing_trades == 0

    def test_with_trades(self):
        """Mix of wins/losses yields sane metrics."""
        core = EngineCore(BacktestConfig(starting_balance=10_000.0))
        now = datetime(2024, 1, 1, 10, 0)
        t1 = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=2,
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            exit_price=1.1050,
            profit_loss=100.0,
            outcome=TradeOutcome.WIN,
            entry_time=now,
            exit_time=now + timedelta(hours=2),
        )
        t2 = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=4,
            direction=TradeDirection.SHORT,
            entry_price=1.1100,
            exit_price=1.1150,
            profit_loss=-50.0,
            outcome=TradeOutcome.LOSS,
            entry_time=now,
            exit_time=now + timedelta(hours=4),
        )
        t3 = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=1,
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            exit_price=1.1200,
            profit_loss=200.0,
            outcome=TradeOutcome.WIN,
            entry_time=now,
            exit_time=now + timedelta(hours=1),
        )
        curve = [10_000.0, 10_050.0, 10_100.0, 10_250.0]
        m = core._calculate_metrics([t1, t2, t3], curve)
        assert m.total_trades == 3
        assert m.winning_trades == 2
        assert m.losing_trades == 1
        assert m.win_rate == pytest.approx(2 / 3 * 100)
        assert m.profit_factor == pytest.approx(300.0 / 50.0)
        assert m.avg_holding_bars == pytest.approx((2 + 4 + 1) / 3)
        assert m.largest_win == pytest.approx(200.0)
        assert m.largest_loss == pytest.approx(-50.0)

    def test_all_losing_trades(self):
        core = EngineCore(BacktestConfig(starting_balance=10_000.0))
        now = datetime(2024, 1, 1, 10, 0)
        t1 = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=1,
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            exit_price=1.0900,
            profit_loss=-100.0,
            outcome=TradeOutcome.LOSS,
            entry_time=now,
            exit_time=now + timedelta(hours=1),
        )
        t2 = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=2,
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            exit_price=1.0950,
            profit_loss=-50.0,
            outcome=TradeOutcome.LOSS,
            entry_time=now,
            exit_time=now + timedelta(hours=2),
        )
        m = core._calculate_metrics([t1, t2], [10_000.0, 9_900.0, 9_850.0])
        assert m.winning_trades == 0
        assert m.losing_trades == 2
        assert m.win_rate == 0.0
        # No wins → profit_factor is 0
        assert m.profit_factor == 0.0


# ---------------------------------------------------------------------------
# Sharpe ratio
# ---------------------------------------------------------------------------


class TestCalculateSharpeRatio:
    def test_flat_equity(self):
        core = EngineCore(BacktestConfig())
        assert core._calculate_sharpe_ratio([10_000.0, 10_000.0, 10_000.0]) == 0.0

    def test_rising_equity(self):
        core = EngineCore(BacktestConfig())
        curve = [10_000.0, 10_100.0, 10_200.0, 10_300.0, 10_400.0]
        sharpe = core._calculate_sharpe_ratio(curve)
        assert sharpe > 0

    def test_insufficient_data(self):
        core = EngineCore(BacktestConfig())
        assert core._calculate_sharpe_ratio([10_000.0]) == 0.0
        assert core._calculate_sharpe_ratio([]) == 0.0

    def test_with_list(self):
        core = EngineCore(BacktestConfig())
        curve = [10_000.0, 10_100.0, 10_200.0, 10_300.0, 10_400.0]
        sharpe = core._calculate_sharpe_ratio(curve)
        assert sharpe > 0

    def test_custom_annualization(self):
        """Lower annualization factor yields smaller absolute Sharpe."""
        core_monthly = EngineCore(BacktestConfig(sharpe_annualization_factor=12.0))
        core_daily = EngineCore(BacktestConfig(sharpe_annualization_factor=252.0))
        curve = [10_000.0, 10_100.0, 10_200.0, 10_300.0, 10_400.0]
        sharpe_monthly = core_monthly._calculate_sharpe_ratio(curve)
        sharpe_daily = core_daily._calculate_sharpe_ratio(curve)
        # Daily annualization multiplies the result by sqrt(252/12) → larger
        assert abs(sharpe_monthly) < abs(sharpe_daily)


# ---------------------------------------------------------------------------
# Daily tracking
# ---------------------------------------------------------------------------


class TestDailyTracking:
    def test_same_day(self):
        core = EngineCore(BacktestConfig())
        t = datetime(2024, 1, 1, 12, 0)
        core._update_daily_tracking(t)
        assert core.current_day == t.date()
        # Set a sentinel, second call on same day shouldn't reset it
        core.daily_start_balance = 9_900.0
        t2 = datetime(2024, 1, 1, 14, 0)
        core._update_daily_tracking(t2)
        assert core.current_day == t.date()
        assert core.daily_start_balance == 9_900.0

    def test_new_day_resets(self):
        core = EngineCore(BacktestConfig())
        t1 = datetime(2024, 1, 1, 12, 0)
        core._update_daily_tracking(t1)
        core.balance = 9_900.0
        # Move to next day → should reset daily_start to current balance
        t2 = datetime(2024, 1, 2, 9, 0)
        core._update_daily_tracking(t2)
        assert core.current_day == t2.date()
        assert core.daily_start_balance == 9_900.0


# ---------------------------------------------------------------------------
# Drawdown checks
# ---------------------------------------------------------------------------


class TestDrawdownChecks:
    def test_max_drawdown_not_breached(self):
        core = EngineCore(BacktestConfig(starting_balance=10_000.0))
        assert core._is_max_drawdown_breached() is False

    def test_max_drawdown_breached(self):
        cfg = BacktestConfig(starting_balance=10_000.0, max_total_drawdown_pct=0.10)
        core = EngineCore(cfg)
        core.peak_balance = 10_000.0
        core.balance = 8_900.0  # 11% drawdown
        assert core._is_max_drawdown_breached() is True

    def test_daily_loss_not_breached(self):
        core = EngineCore(BacktestConfig(starting_balance=10_000.0))
        assert core._is_max_daily_loss_breached() is False

    def test_daily_loss_breached(self):
        cfg = BacktestConfig(starting_balance=10_000.0, max_daily_drawdown_pct=0.05)
        core = EngineCore(cfg)
        core.daily_start_balance = 10_000.0
        core.balance = 9_400.0  # 6% daily loss
        assert core._is_max_daily_loss_breached() is True


# ---------------------------------------------------------------------------
# Trade close / open
# ---------------------------------------------------------------------------


class TestCloseTrade:
    def _make_core(self, balance: float = 10_000.0) -> EngineCore:
        return EngineCore(BacktestConfig(starting_balance=balance))

    def _open_trade(
        self,
        core: EngineCore,
        direction: TradeDirection,
        entry: float,
        size: float = 1.0,
    ) -> SimulatedTrade:
        """Build a minimal SimulatedTrade for closing tests."""
        return SimulatedTrade(
            entry_bar_index=0,
            direction=direction,
            entry_price=entry,
            stop_loss=entry - 0.005 if direction == TradeDirection.LONG else entry + 0.005,
            take_profit_1=entry + 0.010 if direction == TradeDirection.LONG else entry - 0.010,
            take_profit_2=entry + 0.015 if direction == TradeDirection.LONG else entry - 0.015,
            take_profit_3=entry + 0.020 if direction == TradeDirection.LONG else entry - 0.020,
            lot_size=size * UNITS_PER_LOT,  # size is in lots; _close_trade expects units
            entry_time=datetime(2024, 1, 1, 10, 0),
        )

    def test_close_long_winner(self):
        core = self._make_core()
        trade = self._open_trade(core, TradeDirection.LONG, entry=1.1000)
        core._close_trade(
            trade,
            bar_index=1,
            exit_time=datetime(2024, 1, 2, 10, 0),
            exit_price=1.1100,
            reason=ExitReason.TAKE_PROFIT_1,
        )
        assert trade.exit_price == 1.1100
        assert trade.exit_reason == ExitReason.TAKE_PROFIT_1
        assert trade.outcome == TradeOutcome.WIN
        assert trade.profit_loss > 0
        # Balance increased by trade profit
        assert core.balance > core.config.starting_balance

    def test_close_short_winner(self):
        core = self._make_core()
        trade = self._open_trade(core, TradeDirection.SHORT, entry=1.1100)
        core._close_trade(
            trade,
            bar_index=1,
            exit_time=datetime(2024, 1, 2, 10, 0),
            exit_price=1.1000,
            reason=ExitReason.TAKE_PROFIT_1,
        )
        assert trade.exit_price == 1.1000
        assert trade.profit_loss > 0
        assert trade.outcome == TradeOutcome.WIN
        assert core.balance > core.config.starting_balance

    def test_close_long_loser(self):
        core = self._make_core()
        trade = self._open_trade(core, TradeDirection.LONG, entry=1.1000)
        core._close_trade(
            trade,
            bar_index=1,
            exit_time=datetime(2024, 1, 2, 10, 0),
            exit_price=1.0900,
            reason=ExitReason.STOP_LOSS,
        )
        assert trade.exit_price == 1.0900
        assert trade.profit_loss < 0
        assert trade.outcome == TradeOutcome.LOSS
        assert core.balance < core.config.starting_balance

    def test_close_records_balance_change(self):
        """A winning close increases peak_balance."""
        core = self._make_core()
        starting = core.balance
        trade = self._open_trade(core, TradeDirection.LONG, entry=1.1000)
        core._close_trade(
            trade,
            bar_index=1,
            exit_time=datetime(2024, 1, 2, 10, 0),
            exit_price=1.1200,
            reason=ExitReason.TAKE_PROFIT_3,
        )
        assert core.balance > starting


class TestCloseAllOpenTrades:
    def test_close_multiple(self):
        core = EngineCore(BacktestConfig(starting_balance=10_000.0))
        trades = [
            SimulatedTrade(
                entry_bar_index=0,
                direction=TradeDirection.LONG,
                entry_price=1.1000,
                stop_loss=1.0950,
                take_profit_1=1.1100,
                take_profit_2=1.1150,
                take_profit_3=1.1200,
                lot_size=1.0,
                entry_time=datetime(2024, 1, 1, 10, 0),
            ),
            SimulatedTrade(
                entry_bar_index=0,
                direction=TradeDirection.SHORT,
                entry_price=1.1100,
                stop_loss=1.1150,
                take_profit_1=1.0900,
                take_profit_2=1.0850,
                take_profit_3=1.0800,
                lot_size=1.0,
                entry_time=datetime(2024, 1, 1, 10, 0),
            ),
        ]
        bar = _make_bar(1.1000)
        closed = core._close_all_open_trades(trades, 1, bar.time, bar.close)
        assert len(closed) == 2
        for t in closed:
            assert t.exit_reason == ExitReason.END_OF_DATA
            assert t.exit_price == 1.1000


# ---------------------------------------------------------------------------
# BacktestMetrics dataclass
# ---------------------------------------------------------------------------


class TestBacktestMetricsDataclass:
    @staticmethod
    def _make_metrics(**overrides):
        defaults = dict(
            starting_balance=10_000.0,
            ending_balance=10_000.0,
            total_pnl=0.0,
            total_pnl_pct=0.0,
            win_rate=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            breakeven_trades=0,
            avg_win=0.0,
            avg_loss=0.0,
            largest_win=0.0,
            largest_loss=0.0,
            profit_factor=0.0,
            max_drawdown_pct=0.0,
            max_drawdown_dollar=0.0,
            max_daily_loss_dollar=0.0,
            sharpe_ratio=0.0,
            avg_risk_reward=0.0,
            expectancy=0.0,
            avg_holding_bars=0.0,
        )
        defaults.update(overrides)
        return BacktestMetrics(**defaults)

    def test_defaults(self):
        """All metric fields can be constructed via keyword args."""
        m = self._make_metrics()
        assert m.total_pnl == 0.0
        assert m.total_pnl_pct == 0.0
        assert m.sharpe_ratio == 0.0
        assert m.total_trades == 0

    def test_custom(self):
        m = self._make_metrics(
            ending_balance=11_000.0,
            total_pnl=1_000.0,
            total_pnl_pct=0.10,
            win_rate=60.0,
            sharpe_ratio=1.5,
        )
        assert m.total_pnl == 1_000.0
        assert m.total_pnl_pct == pytest.approx(0.10)
        assert m.win_rate == pytest.approx(60.0)
        assert m.sharpe_ratio == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# Determine-session helper
# ---------------------------------------------------------------------------


class TestDetermineSession:
    def test_london(self):
        from engine.base import determine_session

        assert determine_session(datetime(2024, 1, 1, 10, 0)) == "london"

    def test_asian(self):
        from engine.base import determine_session

        assert determine_session(datetime(2024, 1, 1, 3, 0)) == "asian"

    def test_outside(self):
        from engine.base import determine_session

        assert determine_session(datetime(2024, 1, 1, 22, 0)) == "outside"
