#!/usr/bin/env python3
"""
Optuna-Based Bayesian Parameter Optimization for Volatility Squeeze Strategy

Runs Optuna TPE optimization with walk-forward validation objective.
Compares Optuna results against default parameters.

Usage:
    python scripts/run_volatility_squeeze_optuna.py [--trials N] [--pair PAIR] [--spread-pips FLOAT]
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
    float_range,
    int_range,
    categorical,
    SearchSpace,
)
from backtest import CsvDataLoader  # noqa: E402
from strategies.volatility_squeeze import (  # noqa: E402
    VolatilitySqueezeStrategy,
    VolatilitySqueezeConfig,
)
from quant.walk_forward import comparison_report  # noqa: E402

DATA_DIR = project_root / "data" / "forex" / "historical"
REPORT_DIR = project_root / "reports" / "optuna"

GBPUSD_PATH = DATA_DIR / "GBPUSD_H1.csv"
EURUSD_PATH = DATA_DIR / "EURUSD_H1.csv"
USDJPY_PATH = DATA_DIR / "USDJPY_H1.csv"

DEFAULT_CONFIG = {
    "n_windows": 5,
    "train_ratio": 0.70,
    "val_ratio": 0.15,
    "overlap_ratio": 0.20,
    "initial_balance": 10000.0,
    "spread_pips": None,
    "commission_per_lot": 3.5,
}

MAX_SHARPE_REPORT = 10.0

PRESETS = {
    "GBPUSD": VolatilitySqueezeConfig(
        bb_period=20,
        bb_std_dev=2.0,
        kc_period=20,
        kc_atr_multiplier=2.0,
        squeeze_threshold=0.0,
        min_squeeze_bars=3,
        ema_period=20,
        adx_period=14,
        adx_min=20,
        atr_period=14,
        atr_sl_multiplier=1.5,
        tp1_rr=1.0,
        tp2_rr=2.0,
        tp3_rr=3.0,
        session_filter=True,
        squeeze_release_mode="moderate",
    ),
    "EURUSD": VolatilitySqueezeConfig(
        bb_period=20,
        bb_std_dev=2.0,
        kc_period=20,
        kc_atr_multiplier=2.0,
        squeeze_threshold=0.0,
        min_squeeze_bars=2,
        ema_period=20,
        adx_period=14,
        adx_min=18,
        atr_period=14,
        atr_sl_multiplier=1.5,
        tp1_rr=1.0,
        tp2_rr=2.0,
        tp3_rr=3.0,
        session_filter=True,
        squeeze_release_mode="moderate",
    ),
    "USDJPY": VolatilitySqueezeConfig(
        bb_period=20,
        bb_std_dev=2.0,
        kc_period=20,
        kc_atr_multiplier=1.5,
        squeeze_threshold=0.0,
        min_squeeze_bars=3,
        ema_period=50,
        adx_period=14,
        adx_min=22,
        atr_period=14,
        atr_sl_multiplier=1.5,
        tp1_rr=1.0,
        tp2_rr=2.0,
        tp3_rr=3.0,
        session_filter=True,
    ),
}

DATA_FILES = {
    "GBPUSD": GBPUSD_PATH,
    "EURUSD": EURUSD_PATH,
    "USDJPY": USDJPY_PATH,
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
        tp2_rr=float_range("tp2_rr", 1.5, 3.0, step=0.1),
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


def _sanitize_float(value: float, cap: float = MAX_SHARPE_REPORT) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(-cap, min(cap, value))


def run_baseline(
    bars: List[Bar],
    pair: str,
    spread_pips: float | None,
) -> Any:
    preset = PRESETS.get(pair, VolatilitySqueezeConfig())
    strategy = VolatilitySqueezeStrategy(config=preset)
    config = dict(DEFAULT_CONFIG)
    if spread_pips is not None:
        config["spread_pips"] = spread_pips
    return run_strategy_walk_forward(
        bars=bars,
        strategy_factory=lambda: strategy,
        pair=pair,
        **config,
    )


def run_optuna(
    bars: List[Bar],
    pair: str,
    n_trials: int = 100,
    seed: int = 42,
    spread_pips: float | None = None,
) -> Any:
    search_space = volatility_squeeze_search_space()
    config = dict(DEFAULT_CONFIG)
    if spread_pips is not None:
        config["spread_pips"] = spread_pips
    optimizer = OptunaOptimizer(
        bars=bars,
        strategy_factory=make_strategy,
        pair=pair,
        search_space=search_space,
        n_trials=n_trials,
        seed=seed,
        **config,
    )
    return optimizer.optimize()


def get_top_n_results(optimizer: OptunaOptimizer, n: int = 3) -> List[Dict[str, Any]]:
    objective = optimizer.objective
    ranked = []
    for trial_num, wf_result in objective._results_by_trial.items():
        params = objective.get_params(trial_num)
        agg = wf_result.aggregated
        if agg is None:
            continue
        score = objective._composite_score(agg)
        if not wf_result.go_nogo:
            score -= 1.0
        ranked.append(
            {
                "trial_number": trial_num,
                "score": score,
                "params": params,
                "go_nogo": wf_result.go_nogo,
                "win_rate": _sanitize_float(agg.mean_win_rate, cap=1.0),
                "profit_factor": _sanitize_float(agg.mean_profit_factor, cap=50.0),
                "max_drawdown": _sanitize_float(agg.mean_max_drawdown, cap=1.0),
                "sharpe_ratio": _sanitize_float(agg.mean_sharpe_ratio),
                "trade_count": _sanitize_float(agg.mean_trade_count, cap=1000.0),
                "total_pnl": _sanitize_float(agg.mean_total_pnl, cap=1e6),
                "windows_passed": agg.windows_passed,
                "total_windows": agg.total_windows,
            }
        )
    ranked.sort(key=lambda x: x["score"], reverse=True)
    result = []
    for i, entry in enumerate(ranked[:n], 1):
        item = dict(entry)
        item["rank"] = i
        del item["trial_number"]
        result.append(item)
    return result


def _sanitize_report(data: Any, cap: float = MAX_SHARPE_REPORT) -> Any:
    if isinstance(data, float):
        return _sanitize_float(data, cap)
    if isinstance(data, dict):
        return {k: _sanitize_report(v, cap) for k, v in data.items()}
    if isinstance(data, list):
        return [_sanitize_report(v, cap) for v in data]
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optuna optimization for Volatility Squeeze"
    )
    parser.add_argument(
        "--trials", type=int, default=100, help="Number of Optuna trials"
    )
    parser.add_argument("--pair", type=str, default="GBPUSD", help="Currency pair")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--spread-pips",
        type=float,
        default=None,
        help="Spread in pips (default: use pair default from engine)",
    )
    parser.add_argument(
        "--top", type=int, default=3, help="Number of top results to include"
    )
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    pair = args.pair
    csv_path = DATA_FILES.get(pair)
    if csv_path is None or not csv_path.exists():
        print(f"Data file not found for {pair}: {csv_path}")
        sys.exit(1)

    loader = CsvDataLoader()
    bars = loader.load(str(csv_path))
    if not bars:
        print(f"No bars loaded for {pair}: {csv_path}")
        sys.exit(1)
    print(f"Loaded {len(bars)} bars for {pair}: {bars[0].time} -> {bars[-1].time}")

    spread_pips = args.spread_pips

    print(f"\n{'=' * 70}")
    print(f"  BASELINE: Default Volatility Squeeze Parameters ({pair})")
    print(f"  Spread: {spread_pips if spread_pips is not None else 'pair default'}")
    print(f"{'=' * 70}")
    baseline_wf = run_baseline(bars, pair, spread_pips)
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

    print(f"\n{'=' * 70}")
    print(f"  OPTUNA BAYESIAN OPTIMIZATION ({pair})")
    print(f"  Trials: {args.trials}, Seed: {args.seed}")
    print(f"  Spread: {spread_pips if spread_pips is not None else 'pair default'}")
    print(f"{'=' * 70}")

    search_space = volatility_squeeze_search_space()
    config = dict(DEFAULT_CONFIG)
    if spread_pips is not None:
        config["spread_pips"] = spread_pips
    optimizer = OptunaOptimizer(
        bars=bars,
        strategy_factory=make_strategy,
        pair=pair,
        search_space=search_space,
        n_trials=args.trials,
        seed=args.seed,
        **config,
    )
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

    top_results = get_top_n_results(optimizer, n=args.top)
    print(f"\n  Top {args.top} parameter sets:")
    for entry in top_results:
        print(
            f"    Rank {entry['rank']}: score={entry['score']:.4f}, "
            f"go_nogo={entry['go_nogo']}, trades={entry['trade_count']:.1f}"
        )

    print(f"\n{'=' * 70}")
    print(f"  COMPARISON: Default vs Optuna-Optimized ({pair})")
    print(f"{'=' * 70}")
    if opt_result.best_walk_forward and baseline_wf.aggregated:
        print(comparison_report(baseline_wf, opt_result.best_walk_forward))

    def window_to_dict(m) -> Dict[str, Any]:
        return {
            "window_index": m.window_index,
            "win_rate": _sanitize_float(m.win_rate, cap=1.0),
            "profit_factor": _sanitize_float(m.profit_factor, cap=50.0),
            "max_drawdown": _sanitize_float(m.max_drawdown, cap=1.0),
            "sharpe_ratio": _sanitize_float(m.sharpe_ratio),
            "trade_count": m.trade_count,
            "total_pnl": _sanitize_float(m.total_pnl, cap=1e6),
            "passed_go_nogo": m.passed_go_nogo,
        }

    report = {
        "strategy": "Volatility Squeeze Breakout",
        "pair": pair,
        "timeframe": "H1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_trials": args.trials,
        "seed": args.seed,
        "spread_pips": spread_pips if spread_pips is not None else "pair_default",
        "go_nogo_threshold": "3/5 windows",
        "baseline_preset": pair,
        "baseline": {
            "go_nogo": baseline_wf.go_nogo,
            "per_window": [window_to_dict(m) for m in baseline_wf.per_window],
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
            "per_window": (
                [window_to_dict(m) for m in opt_result.best_walk_forward.per_window]
                if opt_result.best_walk_forward
                else []
            ),
        },
        "top_parameter_sets": top_results,
    }

    if baseline_wf.aggregated:
        agg = baseline_wf.aggregated
        report["baseline"]["metrics"] = _sanitize_report(
            {
                "win_rate": agg.mean_win_rate,
                "profit_factor": agg.mean_profit_factor,
                "max_drawdown": agg.mean_max_drawdown,
                "sharpe_ratio": agg.mean_sharpe_ratio,
                "trade_count": agg.mean_trade_count,
                "total_pnl": agg.mean_total_pnl,
            }
        )
    if opt_result.best_walk_forward and opt_result.best_walk_forward.aggregated:
        agg = opt_result.best_walk_forward.aggregated
        report["optuna"]["metrics"] = _sanitize_report(
            {
                "win_rate": agg.mean_win_rate,
                "profit_factor": agg.mean_profit_factor,
                "max_drawdown": agg.mean_max_drawdown,
                "sharpe_ratio": agg.mean_sharpe_ratio,
                "trade_count": agg.mean_trade_count,
                "total_pnl": agg.mean_total_pnl,
            }
        )

    report = _sanitize_report(report)
    report_path = REPORT_DIR / f"{pair}_volatility_squeeze_optuna.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  Report saved: {report_path}")


if __name__ == "__main__":
    main()
