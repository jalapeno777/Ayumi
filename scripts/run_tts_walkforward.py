#!/usr/bin/env python3
"""
Walk-Forward Backtest — TTC/TBD Signal Engine (Multi-Instrument)

Runs walk-forward evaluation of TTSStrategy across 5 pairs:
EURUSD, GBPUSD, USDJPY, GBPJPY, XAUUSD

Supports M15, H1, H4, D1 timeframes.

Usage:
    python scripts/run_tts_walkforward.py [--pairs EURUSD GBPUSD] [--timeframe M15]
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "forex-bot"))

from backtest.engine import Bar
from backtest.strategies import TTSStrategy
from backtest.walk_forward_runner import run_strategy_walk_forward


PAIRS_CONFIG = {
    "EURUSD": {
        "csv": "data/forex/historical/EURUSD_{tf}.csv",
        "spread": 1.2,
    },
    "GBPUSD": {
        "csv": "data/forex/historical/GBPUSD_{tf}.csv",
        "spread": 1.5,
    },
    "USDJPY": {
        "csv": "data/forex/historical/USDJPY_{tf}.csv",
        "spread": 1.3,
    },
    "GBPJPY": {
        "csv": "data/forex/historical/GBPJPY_{tf}.csv",
        "spread": 2.0,
    },
    "XAUUSD": {
        "csv": "data/forex/historical/XAUUSD_{tf}.csv",
        "spread": 3.0,
    },
}

DEFAULT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "GBPJPY", "XAUUSD"]
DEFAULT_TIMEFRAME = "M15"
DEFAULT_WINDOWS = 5
DEFAULT_TRAIN_RATIO = 0.65
DEFAULT_VAL_RATIO = 0.15
DEFAULT_MIN_CONFIDENCE = 0.50
DEFAULT_MIN_QUALITY = 0.60


def load_bars(csv_path: str, tf: str) -> list[Bar]:
    df = pd.read_csv(csv_path)
    df["time"] = pd.to_datetime(df["Date"])
    df = df.sort_values("time").reset_index(drop=True)
    bars = [
        Bar(
            time=row["time"].to_pydatetime(),
            open=row["Open"],
            high=row["High"],
            low=row["Low"],
            close=row["Close"],
            volume=row.get("Volume", 0),
        )
        for _, row in df.iterrows()
    ]
    return bars


def run_pair(
    pair: str,
    tf: str,
    min_confidence: float,
    min_quality_score: float,
    n_windows: int,
    train_ratio: float,
    val_ratio: float,
) -> dict:
    cfg = PAIRS_CONFIG[pair]
    csv_path = cfg["csv"].format(tf=tf)
    spread = cfg["spread"]

    print(f"\n{'─' * 60}")
    print(f"  {pair} | {tf} | conf>={min_confidence} | qual>={min_quality_score}")
    print(f"{'─' * 60}")

    bars = load_bars(csv_path, tf)
    if len(bars) < 500:
        print(f"  SKIP — only {len(bars)} bars")
        return {"pair": pair, "tf": tf, "error": "Insufficient bars"}

    print(f"  Bars: {len(bars)} | {bars[0].time} → {bars[-1].time}")

    def factory() -> TTSStrategy:
        return TTSStrategy(
            symbol=pair,
            min_confidence=min_confidence,
            min_quality_score=min_quality_score,
            lookback=200,
        )

    result = run_strategy_walk_forward(
        bars=bars,
        strategy_factory=factory,
        pair=pair,
        n_windows=n_windows,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        spread_pips=spread,
        commission_per_lot=3.5,
    )

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="TTC/TBD Walk-Forward Backtest")
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=DEFAULT_PAIRS,
        choices=list(PAIRS_CONFIG.keys()),
    )
    parser.add_argument(
        "--timeframe",
        "--tf",
        default=DEFAULT_TIMEFRAME,
        choices=["M15", "H1", "H4", "D1"],
    )
    parser.add_argument("--windows", type=int, default=DEFAULT_WINDOWS)
    parser.add_argument("--train-ratio", type=float, default=DEFAULT_TRAIN_RATIO)
    parser.add_argument("--val-ratio", type=float, default=DEFAULT_VAL_RATIO)
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument("--min-quality", type=float, default=DEFAULT_MIN_QUALITY)
    parser.add_argument("--report-dir", default="reports/tts_walkforward")
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    print(f"\n{'═' * 60}")
    print(f"  TTC/TBD Walk-Forward — {args.timeframe}")
    print(f"  Pairs: {args.pairs}")
    print(
        f"  Windows: {args.windows} | Train: {args.train_ratio} | Val: {args.val_ratio}"
    )
    print(f"  Min confidence: {args.min_confidence} | Min quality: {args.min_quality}")
    print(f"{'═' * 60}")

    all_results = {}
    go_nogo = {}

    for pair in args.pairs:
        result = run_pair(
            pair=pair,
            tf=args.timeframe,
            min_confidence=args.min_confidence,
            min_quality_score=args.min_quality,
            n_windows=args.windows,
            train_ratio=args.train_ratio,
            val_ratio=args.val_ratio,
        )
        all_results[pair] = result

        # Extract go/nogo from walk-forward validator
        if isinstance(result, dict) and "aggregated" in result:
            agg = result["aggregated"]
            metrics = agg.get("aggregated_metrics", {})
            net_profit = metrics.get("net_profit", 0)
            win_rate = metrics.get("win_rate", 0)
            max_dd = metrics.get("max_drawdown_pct", 100)
            total_trades = metrics.get("total_trades", 0)

            # FTMO-style go/nogo
            passes = (
                total_trades >= 20
                and max_dd <= 5.0
                and net_profit > 0
                and win_rate >= 0.40
            )
            go_nogo[pair] = {
                "pass": passes,
                "net_profit": net_profit,
                "win_rate": win_rate,
                "max_dd": max_dd,
                "total_trades": total_trades,
            }
            status = "✅ GO" if passes else "❌ NO-GO"
            print(
                f"\n  {pair}: {status} | P&L: ${net_profit:.2f} | WR: {win_rate:.1%} | DD: {max_dd:.1%} | Trades: {total_trades}"
            )

    # Save report
    report_path = report_dir / f"tts_{args.timeframe}_{timestamp}.json"
    report = {
        "strategy": "TTSStrategy",
        "timeframe": args.timeframe,
        "config": {
            "min_confidence": args.min_confidence,
            "min_quality_score": args.min_quality,
            "n_windows": args.windows,
            "train_ratio": args.train_ratio,
            "val_ratio": args.val_ratio,
        },
        "per_pair": all_results,
        "go_nogo": go_nogo,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\nReport: {report_path}")

    # Summary table
    print(f"\n{'═' * 60}")
    print("  SUMMARY")
    print(f"{'═' * 60}")
    print(
        f"  {'Pair':<10} {'Net P&L':>12} {'WR':>8} {'DD':>8} {'Trades':>8} {'Verdict':<10}"
    )
    print(f"  {'─' * 60}")
    for pair, verdict in go_nogo.items():
        v = verdict
        status = "✅ GO" if v["pass"] else "❌ NO-GO"
        print(
            f"  {pair:<10} ${v['net_profit']:>10.2f} {v['win_rate']:>7.1%} {v['max_dd']:>7.1%} {v['total_trades']:>7} {status}"
        )
    print(f"  {'─' * 60}")

    go_count = sum(1 for v in go_nogo.values() if v["pass"])
    print(f"\n  {go_count}/{len(go_nogo)} pairs passed FTMO-style criteria")


if __name__ == "__main__":
    import json

    main()
