#!/usr/bin/env python3
"""
Optuna-Based Bayesian Parameter Optimization for Volatility Squeeze Strategy

Runs Optuna TPE optimization with walk-forward validation objective.
Compares Optuna results against default parameters (USDJPY_H1_PRESET).

Usage:
    python scripts/run_volatility_squeeze_optuna.py [--trials N] [--pair PAIR] [--seed S]
"""

import argparse
import json
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
    volatility_squeeze_search_space,
)
from backtest import CsvDataLoader  # noqa: E402
from strategies.volatility_squeeze import (  # noqa: E402
    VolatilitySqueezeStrategy,
    VolatilitySqueezeConfig,
    USDJPY_H1_PRESET,
    GBPJPY_H1_PRESET,
    EURUSD_H1_PRESET,
    XAUUSD_H1_PRESET,
)
from quant.walk_forward import comparison_report  # noqa: E402

DATA_DIR = Path("data/forex/historical")
REPORT_DIR = Path("reports/optuna")

PAIR_DATA_PATHS = {
    "USDJPY": DATA_DIR / "USDJPY_H1.csv",
    "GBPJPY": DATA_DIR / "GBPJPY_H1.csv",
    "EURUSD": DATA_DIR / "EURUSD_H1.csv",
    "XAUUSD": DATA_DIR / "XAUUSD_H1.csv",
}

PAIR_PRESETS: Dict[str, VolatilitySqueezeConfig] = {
    "USDJPY": USDJPY_H1_PRESET,
    "GBPJPY": GBPJPY_H1_PRESET,
    "EURUSD": EURUSD_H1_PRESET,
    "XAUUSD": XAUUSD_H1_PRESET,
}

DEFAULT_WF_CONFIG = {
    "n_windows": 5,
    "train_ratio": 0.70,
    "val_ratio": 0.15,
    "overlap_ratio": 0.20,
    "initial_balance": 10000.0,
    "spread_pips": 0.0,
    "commission_per_lot": 3.5,
}


def make_strategy(params: Dict[str, Any]) -> VolatilitySqueezeStrategy:
    config = VolatilitySqueezeConfig(**params)
    return VolatilitySqueezeStrategy(config=config)


def run_baseline(bars: List[Bar], pair: str) -> Any:
    preset = PAIR_PRESETS.get(pair, VolatilitySqueezeConfig())
    strategy = VolatilitySqueezeStrategy(config=preset)
    return run_strategy_walk_forward(
        bars=bars,
        strategy_factory=lambda: strategy,
        pair=pair,
        **DEFAULT_WF_CONFIG,
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
        **DEFAULT_WF_CONFIG,
    )
    return optimizer.optimize()


def _print_metrics(agg: Any, indent: str = "  ") -> None:
    print(f"{indent}Win Rate:      {agg.mean_win_rate:.4f}")
    print(f"{indent}Profit Factor: {agg.mean_profit_factor:.4f}")
    print(f"{indent}Max Drawdown:  {agg.mean_max_drawdown:.4f}")
    print(f"{indent}Sharpe Ratio:  {agg.mean_sharpe_ratio:.4f}")
    print(f"{indent}Trade Count:   {agg.mean_trade_count:.1f}")
    print(f"{indent}Total PnL:     {agg.mean_total_pnl:.2f}")
    print(f"{indent}Windows Pass:  {agg.windows_passed}/{agg.total_windows}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optuna optimization for Volatility Squeeze strategy"
    )
    parser.add_argument("--trials", type=int, default=100, help="Number of Optuna trials")
    parser.add_argument(
        "--pair", type=str, default="USDJPY", help="Currency pair (USDJPY, GBPJPY, EURUSD, XAUUSD)"
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    pair = args.pair.upper()
    csv_path = PAIR_DATA_PATHS.get(pair)
    if csv_path is None or not csv_path.exists():
        print(f"Data file not found for {pair}: {csv_path}")
        sys.exit(1)

    loader = CsvDataLoader()
    bars = loader.load(str(csv_path))
    if not bars:
        print(f"No bars loaded for {pair}: {csv_path}")
        sys.exit(1)
    print(f"Loaded {len(bars)} bars for {pair}: {bars[0].time} -> {bars[-1].time}")

    print(f"\n{'='*70}")
    print(f"  BASELINE: Default {pair} Volatility Squeeze Preset")
    print(f"{'='*70}")
    baseline_wf = run_baseline(bars, pair)
    if baseline_wf.aggregated:
        _print_metrics(baseline_wf.aggregated)
        print(f"  GO/NO-GO:      {'GO' if baseline_wf.go_nogo else 'NO-GO'}")

    print(f"\n{'='*70}")
    print(f"  OPTUNA BAYESIAN OPTIMIZATION ({pair})")
    print(f"  Trials: {args.trials}, Seed: {args.seed}")
    print(f"{'='*70}")

    opt_result = run_optuna(bars, pair, n_trials=args.trials, seed=args.seed)

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
        print("\n  Best walk-forward metrics:")
        _print_metrics(opt_result.best_walk_forward.aggregated, indent="    ")

    print(f"\n{'='*70}")
    print(f"  COMPARISON: Default Preset vs Optuna-Optimized ({pair})")
    print(f"{'='*70}")
    if opt_result.best_walk_forward and baseline_wf.aggregated:
        print(comparison_report(baseline_wf, opt_result.best_walk_forward))

    report = {
        "strategy": "volatility_squeeze",
        "pair": pair,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_trials": args.trials,
        "seed": args.seed,
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
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  Report saved: {report_path}")


if __name__ == "__main__":
    main()
