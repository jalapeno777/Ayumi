#!/usr/bin/env python3
"""Tests for backtest Q2 LOD/HOD Stop Hit Rate Analysis"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest import MACrossStrategy, MultiStrategyBacktestEngine, BacktestConfig, CsvDataLoader
from backtest.engine import ExitReason, TradeDirection, TradeOutcome


def categorize_stop_loss(trade, bars, lookback=5):
    """Categorize stop loss hit type for testing."""
    entry_idx = trade.entry_bar_index
    exit_idx = min(trade.exit_bar_index, len(bars) - 1)
    exit_bar = bars[exit_idx]

    recent_bars = bars[max(0, entry_idx - lookback) : entry_idx + 1]

    pip_value = 0.0001
    threshold_pips = 2.0

    if trade.direction == TradeDirection.SHORT:
        hod_level = max(b.high for b in recent_bars)

        if (
            exit_bar.high >= trade.stop_loss
            and exit_bar.close < trade.stop_loss
            and abs(exit_bar.high - trade.stop_loss) / pip_value <= threshold_pips
        ):
            return "HOD_LEVEL", (hod_level - trade.stop_loss) / pip_value

        if exit_bar.high > trade.stop_loss and exit_bar.close < trade.stop_loss:
            return "INTRABAR_SPIKE", (exit_bar.high - trade.stop_loss) / pip_value

        return "THRU_LEVEL", (exit_bar.high - trade.stop_loss) / pip_value

    else:
        lod_level = min(b.low for b in recent_bars)

        if (
            exit_bar.low <= trade.stop_loss
            and exit_bar.close > trade.stop_loss
            and abs(exit_bar.low - trade.stop_loss) / pip_value <= threshold_pips
        ):
            return "LOD_LEVEL", (trade.stop_loss - lod_level) / pip_value

        if exit_bar.low < trade.stop_loss and exit_bar.close > trade.stop_loss:
            return "INTRABAR_SPIKE", (trade.stop_loss - exit_bar.low) / pip_value

        return "THRU_LEVEL", (trade.stop_loss - exit_bar.low) / pip_value


def test_stop_categorization():
    """Test stop loss categorization logic."""
    loader = CsvDataLoader()
    bars = loader.load(
        str(Path(__file__).parent.parent / "data" / "forex" / "historical" / "EURUSD_H1.csv")
    )
    bars = [b for b in bars if b.time.strftime("%Y-%m-%d") >= "2020-01-01"][:500]

    config = BacktestConfig(
        starting_balance=10000,
        risk_per_trade_pct=0.01,
        max_daily_drawdown_pct=0.05,
        max_total_drawdown_pct=0.10,
        spread_pips=1.5,
        pair="EURUSD",
    )

    strategy = MACrossStrategy(fast_period=9, slow_period=21, atr_multiplier=2.5)
    engine = MultiStrategyBacktestEngine(config, [strategy])
    result = engine.run_all_strategies(bars)
    metrics = result[strategy.name].metrics

    assert len(metrics.trades) > 0, "Should generate trades"
    assert metrics.total_trades == len(metrics.trades), "Total trades should match"

    stop_losses = [t for t in metrics.trades if t.exit_reason == ExitReason.STOP_LOSS]
    assert len(stop_losses) > 0, "Should have some stop losses"

    categories = {"LOD_LEVEL": 0, "HOD_LEVEL": 0, "INTRABAR_SPIKE": 0, "THRU_LEVEL": 0}
    for trade in stop_losses:
        cat, _ = categorize_stop_loss(trade, bars)
        categories[cat] += 1

    print(f"Stop loss categories: {categories}")
    assert sum(categories.values()) == len(stop_losses), "All stops should be categorized"

    lod_hod = categories["LOD_LEVEL"] + categories["HOD_LEVEL"]
    intrabar = categories["INTRABAR_SPIKE"]
    total = len(stop_losses)
    print(f"LOD/HOD level hits: {lod_hod}/{total} = {lod_hod/total:.1%}")
    print(f"Intrabar spikes: {intrabar}/{total} = {intrabar/total:.1%}")


def test_breakeven_tracking():
    """Test that breakeven trades are tracked correctly."""
    loader = CsvDataLoader()
    bars = loader.load(
        str(Path(__file__).parent.parent / "data" / "forex" / "historical" / "EURUSD_H1.csv")
    )
    bars = [b for b in bars if b.time.strftime("%Y-%m-%d") >= "2020-01-01"][:500]

    config = BacktestConfig(
        starting_balance=10000,
        risk_per_trade_pct=0.01,
        max_daily_drawdown_pct=0.05,
        max_total_drawdown_pct=0.10,
        spread_pips=1.5,
        pair="EURUSD",
    )

    strategy = MACrossStrategy(fast_period=9, slow_period=21, atr_multiplier=2.5)
    engine = MultiStrategyBacktestEngine(config, [strategy])
    result = engine.run_all_strategies(bars)
    metrics = result[strategy.name].metrics

    breakeven = [t for t in metrics.trades if t.outcome == TradeOutcome.BREAKEVEN]
    assert metrics.breakeven_trades == len(breakeven), "Breakeven count should match"


if __name__ == "__main__":
    print("Running Q2 stop categorization tests...")
    test_stop_categorization()
    print("PASSED: stop_categorization")

    test_breakeven_tracking()
    print("PASSED: breakeven_tracking")

    print("\nAll Q2 tests passed!")