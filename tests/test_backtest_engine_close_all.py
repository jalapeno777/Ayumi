"""
Test for _close_all_open_trades bug fix.

When end of data is reached and multiple trades are open, each trade should be
closed at the LAST BAR's close price, not at another trade's exit price.
"""

from datetime import datetime

from backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    Bar,
    ExitReason,
    SimulatedTrade,
    TradeDirection,
    TradeOutcome,
)


def _make_bar(hour: int, close: float) -> Bar:
    """Helper to create a bar at a specific hour with a given close."""
    return Bar(
        time=datetime(2024, 1, 1, hour, 0),
        open=close,
        high=close + 0.0005,
        low=close - 0.0005,
        close=close,
        volume=1000.0,
    )


def _make_config() -> BacktestConfig:
    """Default config for testing."""
    return BacktestConfig(
        pair="XAUUSD",
        starting_balance=10_000.0,
        risk_per_trade_pct=0.01,
    )


class TestCloseAllOpenTradesExitPrice:
    """Tests for _close_all_open_trades using correct exit price."""

    def test_multiple_trades_closed_at_last_bar_close(self):
        """
        Two trades open at different entry prices should both be closed
        at the last bar's close price when data ends, not at each other's price.
        """
        config = _make_config()
        engine = BacktestEngine(config)

        # Create bars: trade opens at bar 1, another trade opens at bar 2,
        # backtest ends at bar 3
        bars = [
            _make_bar(9, 2000.0),   # bar 0 - first trade entry
            _make_bar(10, 2001.0),  # bar 1 - second trade entry
            _make_bar(11, 2002.5),  # bar 2 - last bar, end of data
        ]

        # Manually open two trades at different prices
        trade1 = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=-1,
            direction=TradeDirection.LONG,
            entry_price=2000.0,
            stop_loss=1995.0,
            take_profit_1=2005.0,
            take_profit_2=2010.0,
            take_profit_3=2015.0,
            exit_price=0.0,
            lot_size=0.1,
            risk_amount=10.0,
            pips=0.0,
            profit_loss=0.0,
            outcome=TradeOutcome.OPEN,
            exit_reason=ExitReason.STOP_LOSS,
            entry_time=bars[0].time,
            exit_time=bars[0].time,
            confidence_score=0.8,
            confluence_count=1,
            rationale="",
        )

        trade2 = SimulatedTrade(
            entry_bar_index=1,
            exit_bar_index=-1,
            direction=TradeDirection.LONG,
            entry_price=2001.0,
            stop_loss=1996.0,
            take_profit_1=2006.0,
            take_profit_2=2011.0,
            take_profit_3=2016.0,
            exit_price=0.0,
            lot_size=0.1,
            risk_amount=10.0,
            pips=0.0,
            profit_loss=0.0,
            outcome=TradeOutcome.OPEN,
            exit_reason=ExitReason.STOP_LOSS,
            entry_time=bars[1].time,
            exit_time=bars[1].time,
            confidence_score=0.8,
            confluence_count=1,
            rationale="",
        )

        open_trades = [trade1, trade2]

        # Force close at end of data - should use last bar's close (2002.5)
        last_bar = bars[-1]
        closed_trades = engine._close_all_open_trades(
            open_trades,
            len(bars) - 1,
            last_bar.time,
            last_bar.close,
        )

        # Both trades should be closed at the LAST BAR's close price
        assert len(open_trades) == 0, "All open trades should be cleared"
        assert len(closed_trades) == 2, "Both trades should be in closed_trades"

        # CRITICAL: both trades must have the SAME exit_price (the last bar's close).
        # Before the bug fix, trade1 would get trade2's exit_price and vice versa.
        exit_prices = [t.exit_price for t in closed_trades]
        assert exit_prices[0] == exit_prices[1], (
            f"Trades had different exit prices: {exit_prices[0]} vs {exit_prices[1]}. "
            f"They should both be closed at the same price (last bar close)."
        )
        assert trade1.exit_reason == ExitReason.END_OF_DATA
        assert trade2.exit_reason == ExitReason.END_OF_DATA

    def test_single_trade_closed_at_last_bar_close(self):
        """
        A single trade open at end of data should be closed at last bar's close.
        """
        config = _make_config()
        engine = BacktestEngine(config)

        bars = [
            _make_bar(9, 2000.0),   # bar 0 - trade entry
            _make_bar(10, 2002.5),  # bar 1 - last bar
        ]

        trade = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=-1,
            direction=TradeDirection.LONG,
            entry_price=2000.0,
            stop_loss=1995.0,
            take_profit_1=2005.0,
            take_profit_2=2010.0,
            take_profit_3=2015.0,
            exit_price=0.0,
            lot_size=0.1,
            risk_amount=10.0,
            pips=0.0,
            profit_loss=0.0,
            outcome=TradeOutcome.OPEN,
            exit_reason=ExitReason.STOP_LOSS,
            entry_time=bars[0].time,
            exit_time=bars[0].time,
            confidence_score=0.8,
            confluence_count=1,
            rationale="",
        )

        open_trades = [trade]

        last_bar = bars[-1]
        closed_trades = engine._close_all_open_trades(
            open_trades,
            len(bars) - 1,
            last_bar.time,
            last_bar.close,
        )

        assert len(open_trades) == 0
        assert len(closed_trades) == 1
        assert closed_trades[0].exit_reason == ExitReason.END_OF_DATA
