#!/usr/bin/env python3
"""
Walk-Forward Gate Validation for Statistical Arbitrage Strategy
FTMO Criteria: WR>55%, PF>1.3, Sharpe>0.5, 3/5 windows passing
"""

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "forex-bot"))

from backtest.engine import Bar, BacktestConfig, BacktestMetrics
from backtest.multi_strategy_engine import MultiStrategyBacktestEngine
from backtest.data_loader import CsvDataLoader
from backtest.stat_arb import StatArbStrategy


def _metrics_to_dict(m: BacktestMetrics) -> dict:
    return {
        "trades": m.total_trades,
        "win_rate": round(m.win_rate, 2),
        "profit_factor": round(m.profit_factor, 4),
        "sharpe": round(m.sharpe_ratio, 4),
        "max_dd": round(m.max_drawdown_pct, 2),
        "total_pnl": round(m.total_pnl, 2),
        "avg_rr": round(m.avg_risk_reward, 4),
        "expectancy": round(m.expectancy, 2),
    }


def run_stat_arb_walk_forward(
    bars_a: list,
    bars_b: list,
    pair_a: str = "EURUSD",
    pair_b: str = "GBPUSD",
    n_windows: int = 5,
    train_ratio: float = 0.6,
    test_ratio: float = 0.2,
) -> dict:
    """Run walk-forward validation for StatArb strategy with paired data.

    FTMO Criteria:
    - Win Rate > 55%
    - Profit Factor > 1.3
    - Sharpe Ratio > 0.5
    - Max Drawdown < 5%
    - At least 3/5 windows passing
    """
    config = BacktestConfig(
        starting_balance=10000.0,
        risk_per_trade_pct=0.01,
        max_daily_drawdown_pct=0.03,
        max_total_drawdown_pct=0.05,
        spread_pips=0.5,
        commission_per_lot=3.5,
        leverage=100,
        min_confidence=0.50,
        min_bars_before_signal=100,
        max_open_trades=1,
    )

    total = len(bars_a)
    window_size = total // n_windows
    if window_size < 200:
        return {"error": f"Not enough bars ({total}) for {n_windows} windows"}

    buffer_ratio = 1.0 - train_ratio - test_ratio
    if buffer_ratio < 0:
        buffer_ratio = 0.0

    results = []
    print("=" * 80)
    print(" STATISTICAL ARBITRAGE — WALK-FORWARD BACKTEST")
    print("=" * 80)
    print(f" Pair: {pair_a}/{pair_b} | Bars: {total} | Windows: {n_windows}")
    print(f" Split: train={train_ratio:.0%} test={test_ratio:.0%} buffer={buffer_ratio:.0%}")
    print(" FTMO Criteria: WR>55%, PF>1.3, Sharpe>0.5, MaxDD<5%")
    print("-" * 80)

    for w in range(n_windows):
        start = w * window_size
        end = (w + 1) * window_size if w < n_windows - 1 else total

        window_bars_a = bars_a[start:end]
        window_bars_b = bars_b[start:end]
        wlen = len(window_bars_a)

        train_end_idx = int(wlen * train_ratio)
        buffer_end_idx = int(wlen * (train_ratio + buffer_ratio))

        train_bars_a = window_bars_a[:train_end_idx]
        train_bars_b = window_bars_b[:train_end_idx]
        test_bars_a = window_bars_a[buffer_end_idx:]
        test_bars_b = window_bars_b[buffer_end_idx:]

        if len(test_bars_a) < 100:
            results.append({
                "window_id": w,
                "error": "Insufficient test bars",
                "train_bars": len(train_bars_a),
                "test_bars": len(test_bars_a),
            })
            print(f"\n Window {w}: SKIP — insufficient bars")
            continue

        # Create strategy with paired bars
        strategy = StatArbStrategy(
            lookback=60,
            entry_threshold=2.0,
            exit_threshold=0.0,
            stop_loss_threshold=3.0,
            atr_multiplier=2.0,
            pair_b_bars=train_bars_b + test_bars_b,
        )

        engine = MultiStrategyBacktestEngine(config, [strategy])

        # Run on training data (warm-up cointegration)
        _ = engine.run_all_strategies(train_bars_a)

        # Reset and run on test data
        strategy.reset()
        strategy.set_pair_b_bars(test_bars_b)
        test_results = engine.run_all_strategies(test_bars_a)
        test_m = test_results[strategy.name].metrics

        # FTMO GO/NO-GO criteria
        passed = (
            test_m.win_rate > 55
            and test_m.profit_factor > 1.3
            and test_m.max_drawdown_pct < 5.0
            and test_m.sharpe_ratio > 0.5
        )

        results.append({
            "window_id": w,
            "train_start": str(train_bars_a[0].time) if train_bars_a else None,
            "train_end": str(train_bars_a[-1].time) if train_bars_a else None,
            "test_start": str(test_bars_a[0].time) if test_bars_a else None,
            "test_end": str(test_bars_a[-1].time) if test_bars_a else None,
            "train_bars": len(train_bars_a),
            "test_bars": len(test_bars_a),
            "train_metrics": None,
            "test_metrics": _metrics_to_dict(test_m),
            "passed_go_nogo": passed,
        })

        status = "PASS" if passed else "FAIL"
        print(f"\n Window {w}: {status}")
        print(f"  Test: {test_m.total_trades} trades, "
              f"WR={test_m.win_rate:.1f}%, PF={test_m.profit_factor:.2f}, "
              f"DD={test_m.max_drawdown_pct:.2f}%, Sharpe={test_m.sharpe_ratio:.2f}")

    # Aggregate metrics
    valid = [r for r in results if "error" not in r]
    if not valid:
        return {"per_window": results, "aggregated": {}, "go_nogo": False}

    def _mean(key: str) -> float:
        vals = [w["test_metrics"][key] for w in valid]
        return sum(vals) / len(vals) if vals else 0.0

    def _std(key: str, mean: float) -> float:
        vals = [w["test_metrics"][key] for w in valid]
        if len(vals) < 2:
            return 0.0
        variance = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
        return math.sqrt(variance)

    keys = ["win_rate", "profit_factor", "sharpe", "max_dd", "total_pnl", "trades"]
    agg = {}
    for k in keys:
        m = _mean(k)
        agg[f"mean_{k}"] = round(m, 4)
        agg[f"std_{k}"] = round(_std(k, m), 4)

    passed_count = sum(1 for w in valid if w.get("passed_go_nogo", False))
    agg["windows_passed"] = passed_count
    agg["total_windows"] = len(valid)
    agg["go_nogo"] = len(valid) >= 3 and passed_count >= 3

    # Print summary table
    print("\n" + "-" * 80)
    print(" PER-WINDOW RESULTS")
    print(f" {'Window':<8} {'Trades':>8} {'WR%':>8} {'PF':>8} "
          f"{'MaxDD%':>8} {'Sharpe':>8} {'PnL':>10} {'GO?':>6}")
    print(" " + "-" * 76)

    for w in valid:
        tm = w["test_metrics"]
        go = "YES" if w.get("passed_go_nogo", False) else "NO"
        print(f" {w['window_id']:<8} {tm['trades']:>8} {tm['win_rate']:>8.1f} "
              f"{tm['profit_factor']:>8.2f} {tm['max_dd']:>8.2f} "
              f"{tm['sharpe']:>8.2f} {tm['total_pnl']:>10.2f} {go:>6}")

    for w in results:
        if "error" in w:
            print(f" {w['window_id']:<8} ERROR: {w['error']}")

    print("\n" + "-" * 80)
    print(" AGGREGATE METRICS")
    print(" " + "-" * 76)
    go_str = "GO" if agg["go_nogo"] else "NO-GO"
    print(f" Windows Passed: {passed_count}/{len(valid)} -> {go_str}")
    print(f" {'Metric':<20} {'Mean':>12} {'Std':>12}")
    print(" " + "-" * 44)
    labels = [
        ("Win Rate %", "win_rate"),
        ("Profit Factor", "profit_factor"),
        ("Sharpe Ratio", "sharpe"),
        ("Max Drawdown %", "max_dd"),
        ("Total PnL $", "total_pnl"),
        ("Trade Count", "trades"),
    ]
    for label, key in labels:
        print(f" {label:<20} {agg[f'mean_{key}']:>12.4f} {agg[f'std_{key}']:>12.4f}")
    print("-" * 80)

    return {
        "per_window": results,
        "aggregated": agg,
        "go_nogo": agg["go_nogo"],
    }


def main():
    data_dir = Path(__file__).parent.parent / "data" / "forex" / "historical"
    loader = CsvDataLoader()

    # Load EURUSD and GBPUSD as correlated pairs
    eurusd_file = data_dir / "EURUSD_H1.csv"
    gbpusd_file = data_dir / "GBPUSD_H1.csv"

    print(f"\nLoading data...")
    print(f"  Pair A: {eurusd_file}")
    print(f"  Pair B: {gbpusd_file}")

    bars_eur = loader.load(str(eurusd_file))
    bars_gbp = loader.load(str(gbpusd_file))

    print(f"  EURUSD: {len(bars_eur)} bars")
    print(f"  GBPUSD: {len(bars_gbp)} bars")

    # Align bars by time
    eur_times = {b.time: i for i, b in enumerate(bars_eur)}
    aligned_gbp = []
    aligned_eur = []
    for bar in bars_gbp:
        if bar.time in eur_times:
            aligned_gbp.append(bar)
            aligned_eur.append(bars_eur[eur_times[bar.time]])

    print(f"  Aligned: {len(aligned_eur)} bars")

    if len(aligned_eur) < 1000:
        print("ERROR: Insufficient aligned data for walk-forward validation")
        sys.exit(1)

    results = run_stat_arb_walk_forward(
        aligned_eur,
        aligned_gbp,
        pair_a="EURUSD",
        pair_b="GBPUSD",
        n_windows=5,
        train_ratio=0.6,
        test_ratio=0.2,
    )

    # Save report
    report_path = Path(__file__).parent.parent / "reports" / "stat_arb_walk_forward.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nJSON report saved: {report_path}")

    return 0 if results.get("go_nogo", False) else 1


if __name__ == "__main__":
    sys.exit(main())
