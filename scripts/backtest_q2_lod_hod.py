#!/usr/bin/env python3
"""
BACKTEST Q2: LOD/HOD Stop Hit Rate Analysis

What % of trades get stopped at LOD/HOD vs intrabar volatility?

Outputs:
- % of trades stopped at the LOD/HOD level specifically
- % stopped inside the candle (intrabar spike through)
- Average slippage when stop is hit
- Optimal stop buffer (pips beyond LOD/HOD?)
"""

import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest import (
    BacktestConfig,
    MultiStrategyBacktestEngine,
    MACrossStrategy,
    CsvDataLoader,
)
from backtest.engine import ExitReason, TradeDirection, TradeOutcome


def categorize_stop_loss(trade, bars, lookback=5):
    """
    Categorize stop loss hit type:
    - LOD_LEVEL / HOD_LEVEL: price reached SL exactly at candle extreme, confirming the level
    - INTRABAR_SPIKE: price exceeded SL significantly beyond the recent range, then pulled back
    - THRU_LEVEL: price simply closed through the level (no rejection)
    """
    entry_idx = trade.entry_bar_index
    exit_idx = min(trade.exit_bar_index, len(bars) - 1)
    exit_bar = bars[exit_idx]

    recent_bars = bars[max(0, entry_idx - lookback) : entry_idx + 1]

    pip_value = 0.0001
    threshold_pips = 2.0  # Within 2 pips = level hit

    if trade.direction == TradeDirection.SHORT:
        hod_level = max(b.high for b in recent_bars)
        sl_diff_from_hod = (hod_level - trade.stop_loss) / pip_value

        # HOD_LEVEL: exit_bar.high reached or slightly exceeded SL, close below SL (rejection)
        if (
            exit_bar.high >= trade.stop_loss
            and exit_bar.close < trade.stop_loss
            and abs(exit_bar.high - trade.stop_loss) / pip_value <= threshold_pips
        ):
            return "HOD_LEVEL", sl_diff_from_hod

        # INTRABAR_SPIKE: exit_bar.high significantly exceeded SL, close below
        if exit_bar.high > trade.stop_loss and exit_bar.close < trade.stop_loss:
            return "INTRABAR_SPIKE", (exit_bar.high - trade.stop_loss) / pip_value

        # THRU_LEVEL: price just closed through SL (no rejection pattern)
        return "THRU_LEVEL", (exit_bar.high - trade.stop_loss) / pip_value

    else:  # LONG
        lod_level = min(b.low for b in recent_bars)
        sl_diff_from_lod = (trade.stop_loss - lod_level) / pip_value

        # LOD_LEVEL: exit_bar.low reached or slightly dipped below SL, close above SL (rejection)
        if (
            exit_bar.low <= trade.stop_loss
            and exit_bar.close > trade.stop_loss
            and abs(exit_bar.low - trade.stop_loss) / pip_value <= threshold_pips
        ):
            return "LOD_LEVEL", sl_diff_from_lod

        # INTRABAR_SPIKE: exit_bar.low significantly dropped below SL, close above
        if exit_bar.low < trade.stop_loss and exit_bar.close > trade.stop_loss:
            return "INTRABAR_SPIKE", (trade.stop_loss - exit_bar.low) / pip_value

        # THRU_LEVEL: price just closed through SL (no rejection pattern)
        return "THRU_LEVEL", (trade.stop_loss - exit_bar.low) / pip_value


def find_optimal_buffer(stop_losses, bars, direction, lookback=5):
    """
    Find optimal buffer pips beyond LOD/HOD that would have avoided most stop outs.
    For each stop loss, calculate how far price exceeded the recent extreme.
    """
    if not stop_losses:
        return 0.0

    buffers = []
    for trade in stop_losses:
        entry_idx = trade.entry_bar_index
        recent_bars = bars[max(0, entry_idx - lookback) : entry_idx + 1]

        if direction == TradeDirection.SHORT:
            hod_level = max(b.high for b in recent_bars)
            exit_idx = min(trade.exit_bar_index, len(bars) - 1)
            exit_bar = bars[exit_idx]
            # How far did price go beyond HOD before reversing?
            max_excess = (exit_bar.high - hod_level) / 0.0001
        else:
            lod_level = min(b.low for b in recent_bars)
            exit_idx = min(trade.exit_bar_index, len(bars) - 1)
            exit_bar = bars[exit_idx]
            max_excess = (lod_level - exit_bar.low) / 0.0001

        buffers.append(max_excess)

    return round(sum(buffers) / len(buffers), 1) if buffers else 0.0


def run_q2_backtest(
    data_path: str,
    start_date: str = "2020-01-01",
    end_date: str = "2024-12-31",
) -> dict:
    """Run Q2 LOD/HOD Stop Hit Rate Analysis."""

    loader = CsvDataLoader()
    bars = loader.load(data_path)

    bars = [
        b
        for b in bars
        if b.time.strftime("%Y-%m-%d") >= start_date
        and b.time.strftime("%Y-%m-%d") <= end_date
    ]

    if len(bars) < 100:
        return {
            "question": "Q2",
            "error": f"Insufficient bars: {len(bars)}",
            "test_period": f"{start_date} to {end_date}",
            "instrument": "EURUSD",
            "timeframe": "H1",
            "sample_size": len(bars),
        }

    config = BacktestConfig(
        starting_balance=10000.0,
        risk_per_trade_pct=0.01,
        max_daily_drawdown_pct=0.05,
        max_total_drawdown_pct=0.10,
        spread_pips=1.5,
        commission_per_lot=3.5,
        leverage=100,
        min_confidence=0.50,
        min_confluences=1,
        min_risk_reward=1.0,
        max_open_trades=1,
        min_bars_before_signal=30,
        partial_close_enabled=False,
        trailing_stop_enabled=False,
        slippage_pips=0.2,
        pair="EURUSD",
    )

    strategy = MACrossStrategy(fast_period=9, slow_period=21, atr_multiplier=2.5)
    engine = MultiStrategyBacktestEngine(config, [strategy])

    try:
        result = engine.run_all_strategies(bars)
        metrics = result[strategy.name].metrics
    except Exception as e:
        return {"question": "Q2", "error": str(e)}

    trades = metrics.trades
    total_trades = len(trades)

    if total_trades == 0:
        return {
            "question": "Q2",
            "test_period": f"{start_date} to {end_date}",
            "instrument": "EURUSD",
            "timeframe": "H1",
            "sample_size": 0,
            "results": {
                "lod_hod_stop_rate": 0.0,
                "intrabar_spike_rate": 0.0,
                "breakeven_rate": 0.0,
                "avg_stop_buffer_pips": 0.0,
                "optimal_buffer_pips": 0.0,
            },
            "pass": False,
            "notes": "No trades generated",
        }

    stop_losses = [t for t in trades if t.exit_reason == ExitReason.STOP_LOSS]
    breakeven = [t for t in trades if t.outcome == TradeOutcome.BREAKEVEN]

    lod_hod_count = 0
    intrabar_count = 0
    slippage_samples = []

    for trade in stop_losses:
        stop_type, slippage = categorize_stop_loss(trade, bars)
        if stop_type in ("LOD_LEVEL", "HOD_LEVEL"):
            lod_hod_count += 1
        elif stop_type == "INTRABAR_SPIKE":
            intrabar_count += 1
            slippage_samples.append(slippage)

    lod_hod_rate = lod_hod_count / total_trades if total_trades > 0 else 0.0
    intrabar_rate = intrabar_count / total_trades if total_trades > 0 else 0.0
    breakeven_rate = len(breakeven) / total_trades if total_trades > 0 else 0.0

    avg_slippage = sum(slippage_samples) / len(slippage_samples) if slippage_samples else 0.0

    long_stops = [t for t in stop_losses if t.direction == TradeDirection.LONG]
    short_stops = [t for t in stop_losses if t.direction == TradeDirection.SHORT]

    optimal_long = find_optimal_buffer(long_stops, bars, TradeDirection.LONG)
    optimal_short = find_optimal_buffer(short_stops, bars, TradeDirection.SHORT)
    optimal_buffer = (
        (optimal_long + optimal_short) / 2 if (long_stops or short_stops) else 0.0
    )

    target_stop_rate = 0.40
    pass_criteria = lod_hod_rate <= target_stop_rate

    results = {
        "lod_hod_stop_rate": round(lod_hod_rate, 2),
        "intrabar_spike_rate": round(intrabar_rate, 2),
        "breakeven_rate": round(breakeven_rate, 2),
        "avg_stop_buffer_pips": round(avg_slippage, 2),
        "optimal_buffer_pips": round(optimal_buffer, 1),
    }

    return {
        "question": "Q2",
        "test_period": f"{start_date} to {end_date}",
        "instrument": "EURUSD",
        "timeframe": "H1",
        "sample_size": total_trades,
        "results": results,
        "pass": pass_criteria,
        "notes": f"Stop loss rate: {lod_hod_rate:.1%} (target: {target_stop_rate:.1%})",
    }


if __name__ == "__main__":
    data_path = Path(__file__).parent.parent / "data" / "forex" / "historical" / "EURUSD_H1.csv"

    if not data_path.exists():
        print(f"Data file not found: {data_path}")
        sys.exit(1)

    print("Running Q2: LOD/HOD Stop Hit Rate Analysis...")
    result = run_q2_backtest(str(data_path))

    print("\n" + "=" * 50)
    print("       BACKTEST Q2 RESULTS")
    print("=" * 50)
    print(f"\n  Sample Size:        {result.get('sample_size', 0)}")
    print(f"  Test Period:        {result.get('test_period', 'N/A')}")
    print(f"  Pass:               {result.get('pass', False)}")

    if "results" in result:
        r = result["results"]
        print(f"\n  LOD/HOD Stop Rate:   {r['lod_hod_stop_rate']:.1%}")
        print(f"  Intrabar Spike:     {r['intrabar_spike_rate']:.1%}")
        print(f"  Breakeven Rate:     {r['breakeven_rate']:.1%}")
        print(f"  Avg Slippage (pips):{r['avg_stop_buffer_pips']:.2f}")
        print(f"  Optimal Buffer:     {r['optimal_buffer_pips']:.1f} pips")

    print(f"\n  Notes: {result.get('notes', 'N/A')}")

    output_path = Path(__file__).parent.parent / "reports" / "backtest_q2_lod_hod.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n  Results saved to: {output_path}")

    print("\n" + json.dumps(result, indent=2))