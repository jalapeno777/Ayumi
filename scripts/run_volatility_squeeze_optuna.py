#!/usr/bin/env python3
"""
Optuna-Based Bayesian Parameter Optimization for Volatility Squeeze Strategy

Runs Optuna TPE optimization with walk-forward validation objective on
USDJPY H1 Volatility Squeeze Breakout strategy. Outputs top-3 parameter
sets for walk-forward QA gate.

Usage:
    python scripts/run_volatility_squeeze_optuna.py [--trials N] [--top N]
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.engine import Bar  # noqa: E402
from backtest.walk_forward_runner import run_strategy_walk_forward  # noqa: E402
from backtest.parameter_sweep.optuna_optimizer import (  # noqa: E402
    OptunaOptimizer,
    SearchSpace,
    categorical,
    float_range,
    int_range,
)
from backtest import CsvDataLoader  # noqa: E402
from strategies.volatility_squeeze import (  # noqa: E402
    VolatilitySqueezeStrategy,
    VolatilitySqueezeConfig,
    USDJPY_H1_PRESET,
)
from quant.walk_forward import comparison_report  # noqa: E402

DATA_DIR = Path("data/forex/historical")
REPORT_DIR = Path("reports/optuna")

USDJPY_PATH = DATA_DIR / "USDJPY_H1.csv"

DEFAULT_CONFIG = {
    "n_windows": 5,
    "train_ratio": 0.70,
    "val_ratio": 0.15,
    "overlap_ratio": 0.20,
    "initial_balance": 10000.0,
    "spread_pips": 1.0,
    "commission_per_lot": 0.0,
}


def volatility_squeeze_search_space() -> SearchSpace:
    return SearchSpace(
        bb_period=int_range("bb_period", 10, 30),
        bb_std_dev=float_range("bb_std_dev", 1.2, 2.5, step=0.1),
        kc_period=int_range("kc_period", 10, 30),
        kc_atr_multiplier=float_range("kc_atr_multiplier", 0.8, 2.0, step=0.1),
        min_squeeze_bars=int_range("min_squeeze_bars", 1, 5),
        ema_period=int_range("ema_period", 15, 80, step=5),
        adx_period=int_range("adx_period", 10, 25),
        adx_min=float_range("adx_min", 10.0, 28.0, step=1.0),
        atr_period=int_range("atr_period", 10, 25),
        atr_sl_multiplier=float_range("atr_sl_multiplier", 1.0, 3.0, step=0.1),
        tp1_rr=float_range("tp1_rr", 0.5, 2.0, step=0.1),
        tp2_rr=float_range("tp2_rr", 1.0, 3.0, step=0.1),
        tp3_rr=float_range("tp3_rr", 2.0, 4.0, step=0.1),
        session_filter=categorical("session_filter", [True, False]),
        min_confidence=float_range("min_confidence", 0.45, 0.80, step=0.05),
        squeeze_release_mode=categorical(
            "squeeze_release_mode", ["strict", "moderate", "loose"]
        ),
    )


def make_strategy(params: Dict[str, Any]) -> VolatilitySqueezeStrategy:
    config = VolatilitySqueezeConfig(**params)
    return VolatilitySqueezeStrategy(config=config)


def run_baseline(bars: List[Bar], pair: str) -> Any:
    strategy = VolatilitySqueezeStrategy(config=USDJPY_H1_PRESET)
    return run_strategy_walk_forward(
        bars=bars,
        strategy_factory=lambda: strategy,
        pair=pair,
        **DEFAULT_CONFIG,
    )


def run_optuna(
    bars: List[Bar],
    pair: str,
    n_trials: int = 100,
    seed: int = 42,
) -> Any:
    search_space = volatility_squeeze_search_space()
    optimizer = OptunaOptimizer(
        bars=bars,
        strategy_factory=make_strategy,
        pair=pair,
        search_space=search_space,
        n_trials=n_trials,
        seed=seed,
        **DEFAULT_CONFIG,
    )
    return optimizer


def get_top_n_results(
    optimizer: OptunaOptimizer,
    n: int = 3,
) -> List[Dict[str, Any]]:
    objective = optimizer.objective
    results = []
    for trial_num in objective._results_by_trial:
        wf = objective.get_result(trial_num)
        params = objective.get_params(trial_num)
        if wf is None or wf.aggregated is None:
            continue
        agg = wf.aggregated
        score = objective._composite_score(agg)
        if not wf.go_nogo:
            score -= 1.0
        results.append({
            "rank": 0,
            "score": score,
            "params": params,
            "go_nogo": wf.go_nogo,
            "win_rate": agg.mean_win_rate,
            "profit_factor": agg.mean_profit_factor,
            "max_drawdown": agg.mean_max_drawdown,
            "sharpe_ratio": agg.mean_sharpe_ratio,
            "trade_count": agg.mean_trade_count,
            "total_pnl": agg.mean_total_pnl,
            "windows_passed": agg.windows_passed,
            "total_windows": agg.total_windows,
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(results[:n]):
        r["rank"] = i + 1
    return results[:n]


def _sanitize_float(value):
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        return None
    return value


def _sanitize_report(obj):
    if isinstance(obj, dict):
        return {k: _sanitize_report(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_report(v) for v in obj]
    return _sanitize_float(obj)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optuna optimization for Volatility Squeeze USDJPY H1"
    )
    parser.add_argument(
        "--trials", type=int, default=100, help="Number of Optuna trials"
    )
    parser.add_argument("--pair", type=str, default="USDJPY", help="Currency pair")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--top", type=int, default=3, help="Number of top parameter sets to output"
    )
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    pair = args.pair
    csv_path = USDJPY_PATH
    if not csv_path.exists():
        print(f"Data file not found for {pair}: {csv_path}")
        sys.exit(1)

    loader = CsvDataLoader()
    bars = loader.load(str(csv_path))
    if not bars:
        print(f"No bars loaded for {pair}: {csv_path}")
        sys.exit(1)
    print(f"Loaded {len(bars)} bars for {pair}: {bars[0].time} -> {bars[-1].time}")

    print(f"\n{'='*70}")
    print(f"  BASELINE: USDJPY_H1_PRESET Parameters ({pair})")
    print(f"{'='*70}")
    baseline_wf = run_baseline(bars, pair)
    if baseline_wf.aggregated:
        agg = baseline_wf.aggregated
        print(f"  Win Rate:     {agg.mean_win_rate:.4f}")
        print(f"  Profit Factor: {agg.mean_profit_factor:.4f}")
        print(f"  Max Drawdown:  {agg.mean_max_drawdown:.4f}")
        print(f"  Sharpe Ratio:  {agg.mean_sharpe_ratio:.4f}")
        print(f"  Trade Count:   {agg.mean_trade_count:.1f}")
        print(f"  Total PnL:     {agg.mean_total_pnl:.2f}")
        print(f"  Windows Pass:  {agg.windows_passed}/{agg.total_windows}")
        print(f"  GO/NO-GO:      {'GO' if baseline_wf.go_nogo else 'NO-GO'}")

    print(f"\n{'='*70}")
    print(f"  OPTUNA BAYESIAN OPTIMIZATION ({pair})")
    print(f"  Trials: {args.trials}, Seed: {args.seed}")
    print(f"{'='*70}")

    optimizer = run_optuna(bars, pair, n_trials=args.trials, seed=args.seed)
    opt_result = optimizer.optimize()

    print("\n  Optimization complete:")
    print(f"    Total trials:    {opt_result.n_trials}")
    print(f"    Completed:       {opt_result.study_summary.get('n_complete', 0)}")
    print(f"    Pruned:          {opt_result.study_summary.get('n_pruned', 0)}")
    print(f"    Best score:      {opt_result.best_value:.4f}")
    print(f"    GO/NO-GO:        {'GO' if opt_result.go_nogo else 'NO-GO'}")

    print("\n  Best parameters:")
    for key, value in sorted(opt_result.best_params.items()):
        print(f"    {key}: {value}")

    if opt_result.best_walk_forward and opt_result.best_walk_forward.aggregated:
        agg = opt_result.best_walk_forward.aggregated
        print("\n  Best walk-forward metrics:")
        print(f"    Win Rate:      {agg.mean_win_rate:.4f}")
        print(f"    Profit Factor: {agg.mean_profit_factor:.4f}")
        print(f"    Max Drawdown:   {agg.mean_max_drawdown:.4f}")
        print(f"    Sharpe Ratio:   {agg.mean_sharpe_ratio:.4f}")
        print(f"    Trade Count:    {agg.mean_trade_count:.1f}")
        print(f"    Total PnL:      {agg.mean_total_pnl:.2f}")
        print(f"    Windows Pass:   {agg.windows_passed}/{agg.total_windows}")

    top_n = get_top_n_results(optimizer, n=args.top)
    print(f"\n{'='*70}")
    print(f"  TOP-{args.top} PARAMETER SETS (for walk-forward QA gate)")
    print(f"{'='*70}")
    for entry in top_n:
        print(f"\n  Rank #{entry['rank']} (score={entry['score']:.4f}, "
              f"GO={'GO' if entry['go_nogo'] else 'NO-GO'})")
        print(f"    WR={entry['win_rate']:.4f} PF={entry['profit_factor']:.4f} "
              f"DD={entry['max_drawdown']:.4f} Sharpe={entry['sharpe_ratio']:.4f} "
              f"Trades={entry['trade_count']:.1f} "
              f"Windows={entry['windows_passed']}/{entry['total_windows']}")
        for k, v in sorted(entry["params"].items()):
            print(f"    {k}: {v}")

    print(f"\n{'='*70}")
    print(f"  COMPARISON: Baseline vs Optuna-Optimized ({pair})")
    print(f"{'='*70}")
    if opt_result.best_walk_forward and baseline_wf.aggregated:
        print(comparison_report(baseline_wf, opt_result.best_walk_forward))

    report = {
        "strategy": "Volatility Squeeze Breakout",
        "pair": pair,
        "timeframe": "H1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_trials": args.trials,
        "seed": args.seed,
        "baseline_preset": "USDJPY_H1_PRESET",
        "baseline": {
            "go_nogo": baseline_wf.go_nogo,
            "windows_passed": sum(
                1 for m in baseline_wf.per_window if m.passed_go_nogo
            ),
            "total_windows": len(baseline_wf.per_window),
        },
        "optuna": {
            "best_params": opt_result.best_params,
            "best_score": opt_result.best_value,
            "go_nogo": opt_result.go_nogo,
            "n_trials": opt_result.n_trials,
            "study_summary": opt_result.study_summary,
        },
        "top_parameter_sets": top_n,
    }
    if baseline_wf.aggregated:
        agg = baseline_wf.aggregated
        report["baseline"]["metrics"] = {
            "win_rate": agg.mean_win_rate,
            "profit_factor": agg.mean_profit_factor,
            "max_drawdown": agg.mean_max_drawdown,
            "sharpe_ratio": agg.mean_sharpe_ratio,
            "trade_count": agg.mean_trade_count,
            "total_pnl": agg.mean_total_pnl,
        }
    if opt_result.best_walk_forward and opt_result.best_walk_forward.aggregated:
        agg = opt_result.best_walk_forward.aggregated
        report["optuna"]["metrics"] = {
            "win_rate": agg.mean_win_rate,
            "profit_factor": agg.mean_profit_factor,
            "max_drawdown": agg.mean_max_drawdown,
            "sharpe_ratio": agg.mean_sharpe_ratio,
            "trade_count": agg.mean_trade_count,
            "total_pnl": agg.mean_total_pnl,
        }

    report_path = REPORT_DIR / f"{pair}_volatility_squeeze_optuna.json"
    sanitized = _sanitize_report(report)
    with open(report_path, "w") as f:
        json.dump(sanitized, f, indent=2, allow_nan=False)
    print(f"\n  Report saved: {report_path}")


if __name__ == "__main__":
    main()
