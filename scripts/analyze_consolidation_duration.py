#!/usr/bin/env python3
"""
BACKTEST Q5: Board Meeting Consolidation Duration

Analyzes consolidation periods in EURUSD H1 to determine optimal
consolidation duration before breakout. Identifies low-volatility
consolidation patterns and measures resulting breakout success.
"""

import pandas as pd
import json
import numpy as np
from pathlib import Path

DATA_PATH = (
    Path(__file__).parent.parent / "data" / "forex" / "historical" / "EURUSD_H1.csv"
)
OUTPUT_PATH = (
    Path(__file__).parent.parent / "reports" / "backtest_q5_consolidation_results.json"
)


def identify_consolidation_bars(df, lookback=20, threshold_pct=0.5):
    """Identify bars with unusually small range (potential consolidation)."""
    df = df.copy()
    df["Range"] = df["High"] - df["Low"]
    df["RangePct"] = df["Range"] / df["Close"]
    df["AvgRange"] = df["Range"].rolling(lookback).mean()
    df["StdRange"] = df["Range"].rolling(lookback).std()

    # Consolidation = range below threshold % of average
    df["IsConsolidation"] = df["RangePct"] < (
        df["RangePct"].rolling(lookback).mean() * threshold_pct
    )
    return df


def find_consolidation_periods(df, min_duration=3, max_duration=24):
    """Find consecutive consolidation periods of various lengths."""
    df = df.copy()
    df["InConsolidation"] = False

    # ATR-like measure for volatility
    df["TrueRange"] = np.maximum(
        df["High"] - df["Low"],
        np.maximum(
            abs(df["High"] - df["Close"].shift(1)),
            abs(df["Low"] - df["Close"].shift(1)),
        ),
    )
    df["ATR"] = df["TrueRange"].rolling(14).mean()
    df["RangePct"] = df["TrueRange"] / df["Close"]

    # Consolidation: ATR is below 70% of its 50-bar average (relaxed from 50%)
    df["AvgATR"] = df["ATR"].rolling(50).mean()
    df["IsLowVol"] = df["ATR"] < (df["AvgATR"] * 0.70)

    # Also require the consolidation range to be relatively tight
    df["RangeMA"] = df["TrueRange"].rolling(20).mean()
    df["IsTightRange"] = df["TrueRange"] < df["RangeMA"] * 0.75

    periods = []
    i = 0
    while i < len(df) - min_duration:
        if df.iloc[i]["IsLowVol"]:
            start_idx = i
            duration = 0
            tight_count = 0
            while i < len(df) and duration < max_duration:
                is_low_vol = df.iloc[i]["IsLowVol"]
                is_tight_range = df.iloc[i]["IsTightRange"]
                if not is_low_vol:
                    break
                duration += 1
                if is_tight_range:
                    tight_count += 1
                i += 1
            if (
                duration >= min_duration
                and (tight_count / duration if duration > 0 else 0) >= 0.6
            ):
                periods.append(
                    {
                        "start_idx": start_idx,
                        "end_idx": i - 1,
                        "duration_hours": duration,
                    }
                )
        else:
            i += 1

    return periods


def measure_breakout(df, period, take_profit_pct=0.01, stop_loss_pct=0.005):
    """Measure the breakout move after a consolidation period."""
    start_idx = period["start_idx"]
    end_idx = period["end_idx"]

    # Consolidation range
    cons_df = df.iloc[start_idx : end_idx + 1]
    cons_high = cons_df["High"].max()
    cons_low = cons_df["Low"].min()
    cons_range = cons_high - cons_low

    # Get post-consolidation bars (up to 24 bars / 24 hours)
    post_start = end_idx + 1
    post_end = min(end_idx + 25, len(df))
    post_df = df.iloc[post_start:post_end]

    if len(post_df) < 2:
        return None

    # Calculate breakout metrics
    post_high = post_df["High"].max()
    post_low = post_df["Low"].min()
    post_close = post_df.iloc[-1]["Close"]

    # Upside breakout: close above cons_high
    # Downside breakout: close below cons_low
    upside_breakout = post_close > cons_high
    downside_breakout = post_close < cons_low

    # Calculate pips moved after breakout
    if upside_breakout:
        move_pips = (post_close - cons_high) * 10000
    elif downside_breakout:
        move_pips = (cons_low - post_close) * 10000
    else:
        move_pips = 0

    # Was the breakout profitable (move > 15 pips or > 50% of consolidation range)?
    min_profitable_pips = 15
    profitable = abs(move_pips) > min_profitable_pips or abs(move_pips) > (
        cons_range * 10000 * 0.5
    )

    return {
        "cons_high": cons_high,
        "cons_low": cons_low,
        "cons_range_pips": cons_range * 10000,
        "post_high": post_high,
        "post_low": post_low,
        "post_close": post_close,
        "upside_breakout": upside_breakout,
        "downside_breakout": downside_breakout,
        "move_pips": round(move_pips, 1),
        "profitable": profitable,
        "breakout_type": "up"
        if upside_breakout
        else ("down" if downside_breakout else "none"),
    }


def analyze_consolidation():
    df = pd.read_csv(DATA_PATH)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    # Filter to test period: 2024-01-01 to 2025-12-31
    df = df[(df["Date"] >= "2024-01-01") & (df["Date"] <= "2025-12-31")].copy()
    df = df.reset_index(drop=True)

    print(f"Loaded {len(df)} bars from {df['Date'].min()} to {df['Date'].max()}")

    # Find consolidation periods
    periods = find_consolidation_periods(df, min_duration=3, max_duration=24)
    print(f"Found {len(periods)} consolidation periods (3-24 hours)")

    # Find short consolidation periods (1-2 hours) for below_3hr comparison
    short_periods = find_consolidation_periods(df, min_duration=1, max_duration=2)
    print(f"Found {len(short_periods)} short consolidation periods (1-2 hours)")

    # Measure breakouts
    results = []
    for period in periods:
        breakout = measure_breakout(df, period)
        if breakout:
            result = {
                "start_date": str(df.iloc[period["start_idx"]]["Date"].date()),
                "duration_hours": period["duration_hours"],
                **breakout,
            }
            results.append(result)

    # Short periods (1-2 hours) for below_3hr comparison
    short_results = []
    for period in short_periods:
        breakout = measure_breakout(df, period)
        if breakout:
            result = {
                "start_date": str(df.iloc[period["start_idx"]]["Date"].date()),
                "duration_hours": period["duration_hours"],
                **breakout,
            }
            short_results.append(result)

    print(f"Measured {len(results)} valid breakouts")

    # Analyze by consolidation duration buckets
    duration_buckets = {
        "1-2_hours": [],
        "3-4_hours": [],
        "5-6_hours": [],
        "7-8_hours": [],
        "9-12_hours": [],
        "13_plus_hours": [],
    }

    for r in results:
        d = r["duration_hours"]
        if d <= 2:
            duration_buckets["1-2_hours"].append(r)
        elif d <= 4:
            duration_buckets["3-4_hours"].append(r)
        elif d <= 6:
            duration_buckets["5-6_hours"].append(r)
        elif d <= 8:
            duration_buckets["7-8_hours"].append(r)
        elif d <= 12:
            duration_buckets["9-12_hours"].append(r)
        else:
            duration_buckets["13_plus_hours"].append(r)

    # Calculate success rates by bucket
    bucket_stats = {}
    for bucket_name, items in duration_buckets.items():
        if items:
            profitable_count = sum(1 for item in items if item["profitable"])
            total_moves = [
                item["move_pips"] for item in items if item["breakout_type"] != "none"
            ]
            success_rate = profitable_count / len(items) if items else 0
            avg_move = (
                sum(abs(m) for m in total_moves) / len(total_moves)
                if total_moves
                else 0
            )

            bucket_stats[bucket_name] = {
                "count": len(items),
                "profitable_count": profitable_count,
                "success_rate": round(success_rate, 3),
                "avg_move_pips": round(avg_move, 1),
            }
        else:
            bucket_stats[bucket_name] = {
                "count": 0,
                "profitable_count": 0,
                "success_rate": 0,
                "avg_move_pips": 0,
            }

    # Find optimal consolidation duration
    optimal_bucket = None
    best_success_rate = 0
    for bucket_name, stats in bucket_stats.items():
        if stats["count"] >= 5 and stats["success_rate"] > best_success_rate:
            best_success_rate = stats["success_rate"]
            optimal_bucket = bucket_name

    # Calculate overall stats for >= 3 hour threshold
    above_3hr = [r for r in results if r["duration_hours"] >= 3]
    below_3hr = short_results

    above_3hr_profitable = sum(1 for r in above_3hr if r["profitable"])
    below_3hr_profitable = sum(1 for r in below_3hr if r["profitable"])

    above_3hr_rate = above_3hr_profitable / len(above_3hr) if above_3hr else 0
    below_3hr_rate = below_3hr_profitable / len(below_3hr) if below_3hr else 0

    # Pass criteria: Consolidation >= 3 hours precedes 70%+ profitable breakouts
    pass_threshold = 0.70

    # For optimal duration, use the best performing bucket with sufficient samples
    optimal_hours = None
    optimal_rate = None
    optimal_avg_move = None

    if optimal_bucket:
        stats = bucket_stats[optimal_bucket]
        optimal_rate = stats["success_rate"]
        optimal_avg_move = stats["avg_move_pips"]
        if optimal_bucket == "1-2_hours":
            optimal_hours = 2
        elif optimal_bucket == "3-4_hours":
            optimal_hours = 4
        elif optimal_bucket == "5-6_hours":
            optimal_hours = 5
        elif optimal_bucket == "7-8_hours":
            optimal_hours = 8
        elif optimal_bucket == "9-12_hours":
            optimal_hours = 10
        else:
            optimal_hours = 15
    else:
        optimal_hours = 0
        optimal_rate = 0.0
        optimal_avg_move = 0.0

    # Build output
    output = {
        "question": "Q5",
        "test_period": "2024-01-01 to 2025-12-31",
        "instrument": "EURUSD",
        "timeframe": "H1",
        "sample_size": len(results),
        "results": {
            "optimal_consolidation_hours": optimal_hours,
            "profitable_breakout_rate_at_optimal": optimal_rate,
            "avg_resulting_move_pips": optimal_avg_move,
            "below_3hr_profitable_pct": below_3hr_rate,
            "above_3hr_profitable_pct": above_3hr_rate,
            "bucket_stats": bucket_stats,
        },
        "pass": above_3hr_rate >= pass_threshold,
        "notes": (
            f"{optimal_hours}-hour consolidation shows {optimal_rate * 100:.0f}% profitable breakout rate. <3hr shows {below_3hr_rate * 100:.0f}%."
            if optimal_hours is not None
            else "No optimal bucket with sufficient samples found."
        ),
    }

    print("=" * 60)
    print("BACKTEST Q5: Board Meeting Consolidation Duration")
    print("=" * 60)
    print(f"Test Period: {output['test_period']}")
    print(f"Sample Size: {len(results)} consolidation-breakout pairs")
    print("\nBreakout Success by Duration Bucket:")
    for bucket, stats in bucket_stats.items():
        print(
            f"  {bucket}: {stats['count']} samples, {stats['success_rate'] * 100:.1f}% profitable, avg {stats['avg_move_pips']:.1f} pips"
        )
    print(f"\n>= 3hr Success Rate: {above_3hr_rate * 100:.1f}%")
    print(f"< 3hr Success Rate: {below_3hr_rate * 100:.1f}%")
    print(
        f"\nOptimal Duration: {optimal_hours} hours ({optimal_rate * 100:.1f}% success)"
    )
    print(f"PASS (>=70%): {output['pass']}")
    print("=" * 60)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to: {OUTPUT_PATH}")

    return output


if __name__ == "__main__":
    analyze_consolidation()
