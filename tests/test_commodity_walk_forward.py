#!/usr/bin/env python3
"""
Walk-Forward Gate Validation for Commodity Strategies
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
from backtest.strategies import CommodityTrendStrategy, CommodityMeanReversionStrategy


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


def run_commodity_walk_forward(
    bars: list,
    pair: str = "XAUUSD",
    n_windows: int = 5,
    train_ratio: float = 0.6,
    test_ratio: float = 0.2,
) -> dict:
    """Run walk-forward validation for Commodity strategies.

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

    total = len(bars)
    window_size = total // n_windows
    if window_size < 200:
        return {"error": f"Not enough bars ({total}) for {n_windows} windows"}

    buffer_ratio = 1.0 - train_ratio - test_ratio
    if buffer_ratio < 0:
        buffer_ratio = 0.0

    trend_results = []
    mr_results = []

    print("=" * 80)
    print(" COMMODITY STRATEGIES — WALK-FORWARD BACKTEST")
    print("=" * 80)
    print(f" Pair: {pair} | Bars: {total} | Windows: {n_windows}")
    print(f" Split: train={train_ratio:.0%} test={test_ratio:.0%} buffer={buffer_ratio:.0%}")
    print(" FTMO Criteria: WR>55%, PF>1.3, Sharpe>0.5, MaxDD<5%")
    print("-" * 80)

    strategies = [
        CommodityTrendStrategy(fast_ema_period=20, slow_ema_period=50, adx_threshold=25.0),
        CommodityMeanReversionStrategy(bb_period=20, bb_std_dev=2.0),
    ]

    for w in range(n_windows):
        start = w * window_size
        end = (w + 1) * window_size if w < n_windows - 1 else total

        window_bars = bars[start:end]
        wlen = len(window_bars)

        train_end_idx = int(wlen * train_ratio)
        buffer_end_idx = int(wlen * (train_ratio + buffer_ratio))

        train_bars = window_bars[:train_end_idx]
        test_bars = window_bars[buffer_end_idx:]

        if len(test_bars) < 100:
            trend_results.append({
                "window_id": w,
                "error": "Insufficient test bars",
                "train_bars": len(train_bars),
                "test_bars": len(test_bars),
            })
            mr_results.append({
                "window_id": w,
                "error": "Insufficient test bars",
            })
            print(f"\n Window {w}: SKIP — insufficient bars")
            continue

        engine = MultiStrategyBacktestEngine(config, strategies)

        # Run on test data
        test_results = engine.run_all_strategies(test_bars)

        trend_m = test_results[strategies[0].name].metrics
        mr_m = test_results[strategies[1].name].metrics

        # FTMO GO/NO-GO criteria
        trend_passed = (
            trend_m.win_rate > 55
            and trend_m.profit_factor > 1.3
            and trend_m.max_drawdown_pct < 5.0
            and trend_m.sharpe_ratio > 0.5
        )
        mr_passed = (
            mr_m.win_rate > 55
            and mr_m.profit_factor > 1.3
            and mr_m.max_drawdown_pct < 5.0
            and mr_m.sharpe_ratio > 0.5
        )

        trend_results.append({
            "window_id": w,
            "train_start": str(train_bars[0].time) if train_bars else None,
            "train_end": str(train_bars[-1].time) if train_bars else None,
            "test_start": str(test_bars[0].time) if test_bars else None,
            "test_end": str(test_bars[-1].time) if test_bars else None,
            "train_bars": len(train_bars),
            "test_bars": len(test_bars),
            "test_metrics": _metrics_to_dict(trend_m),
            "passed_go_nogo": trend_passed,
        })

        mr_results.append({
            "window_id": w,
            "test_metrics": _metrics_to_dict(mr_m),
            "passed_go_nogo": mr_passed,
        })

        trend_status = "PASS" if trend_passed else "FAIL"
        mr_status = "PASS" if mr_passed else "FAIL"
        print(f"\n Window {w}:")
        print(f"  Trend: {trend_m.total_trades} trades, "
              f"WR={trend_m.win_rate:.1f}%, PF={trend_m.profit_factor:.2f}, "
              f"DD={trend_m.max_drawdown_pct:.2f}%, Sharpe={trend_m.sharpe_ratio:.2f} [{trend_status}]")
        print(f"  MR:    {mr_m.total_trades} trades, "
              f"WR={mr_m.win_rate:.1f}%, PF={mr_m.profit_factor:.2f}, "
              f"DD={mr_m.max_drawdown_pct:.2f}%, Sharpe={mr_m.sharpe_ratio:.2f} [{mr_status}]")

    def _aggregate(results):
        valid = [r for r in results if "error" not in r]
        if not valid:
            return {}

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
        return agg, valid

    trend_agg, trend_valid = _aggregate(trend_results)
    mr_agg, mr_valid = _aggregate(mr_results)

    # Print summary table
    print("\n" + "-" * 80)
    print(" COMMODITY TREND — PER-WINDOW RESULTS")
    print(f" {'Window':<8} {'Trades':>8} {'WR%':>8} {'PF':>8} "
          f"{'MaxDD%':>8} {'Sharpe':>8} {'PnL':>10} {'GO?':>6}")
    print(" " + "-" * 76)
    for w in trend_valid:
        tm = w["test_metrics"]
        go = "YES" if w.get("passed_go_nogo", False) else "NO"
        print(f" {w['window_id']:<8} {tm['trades']:>8} {tm['win_rate']:>8.1f} "
              f"{tm['profit_factor']:>8.2f} {tm['max_dd']:>8.2f} "
              f"{tm['sharpe']:>8.2f} {tm['total_pnl']:>10.2f} {go:>6}")
    for w in trend_results:
        if "error" in w:
            print(f" {w['window_id']:<8} ERROR: {w['error']}")

    print("\n" + "-" * 80)
    print(" COMMODITY MEAN REVERSION — PER-WINDOW RESULTS")
    print(f" {'Window':<8} {'Trades':>8} {'WR%':>8} {'PF':>8} "
          f"{'MaxDD%':>8} {'Sharpe':>8} {'PnL':>10} {'GO?':>6}")
    print(" " + "-" * 76)
    for w in mr_valid:
        tm = w["test_metrics"]
        go = "YES" if w.get("passed_go_nogo", False) else "NO"
        print(f" {w['window_id']:<8} {tm['trades']:>8} {tm['win_rate']:>8.1f} "
              f"{tm['profit_factor']:>8.2f} {tm['max_dd']:>8.2f} "
              f"{tm['sharpe']:>8.2f} {tm['total_pnl']:>10.2f} {go:>6}")
    for w in mr_results:
        if "error" in w:
            print(f" {w['window_id']:<8} ERROR: {w['error']}")

    print("\n" + "-" * 80)
    print(" AGGREGATE METRICS")
    print(" " + "-" * 76)
    trend_go = "GO" if trend_agg.get("go_nogo", False) else "NO-GO"
    mr_go = "GO" if mr_agg.get("go_nogo", False) else "NO-GO"
    print(f" Trend:         {trend_agg.get('windows_passed', 0)}/{trend_agg.get('total_windows', 0)} windows passed -> {trend_go}")
    print(f" Mean Reversion: {mr_agg.get('windows_passed', 0)}/{mr_agg.get('total_windows', 0)} windows passed -> {mr_go}")
    print("-" * 80)

    return {
        "trend": {"per_window": trend_results, "aggregated": trend_agg, "go_nogo": trend_agg.get("go_nogo", False)},
        "mean_reversion": {"per_window": mr_results, "aggregated": mr_agg, "go_nogo": mr_agg.get("go_nogo", False)},
    }


def main():
    data_dir = Path(__file__).parent.parent / "data" / "forex" / "historical"
    loader = CsvDataLoader()

    xauusd_file = data_dir / "XAUUSD_H1.csv"
    print(f"\nLoading data: {xauusd_file}")

    bars = loader.load(str(xauusd_file))
    print(f"  XAUUSD: {len(bars)} bars")
    print(f"  Period: {bars[0].time} to {bars[-1].time}")

    if len(bars) < 1000:
        print("ERROR: Insufficient data for walk-forward validation")
        sys.exit(1)

    results = run_commodity_walk_forward(
        bars,
        pair="XAUUSD",
        n_windows=5,
        train_ratio=0.6,
        test_ratio=0.2,
    )

    # Save report
    report_path = Path(__file__).parent.parent / "reports" / "commodity_walk_forward.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nJSON report saved: {report_path}")

    # Overall GO if at least one strategy passes
    overall_go = results["trend"]["go_nogo"] or results["mean_reversion"]["go_nogo"]
    return 0 if overall_go else 1


if __name__ == "__main__":
    sys.exit(main())
