#!/usr/bin/env python3
"""Portfolio Blend Testing — AYUAA-487

Combines all passing strategies into a unified portfolio, tests correlation,
optimizes weights, runs walk-forward validation, and evaluates against FTMO criteria.
"""

import argparse
import json
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

DATA_DIR = str(project_root / "data" / "forex" / "historical")
REPORTS_DIR = project_root / "reports"


def main() -> None:
    parser = argparse.ArgumentParser(description="Portfolio blend testing")
    parser.add_argument("--windows", type=int, default=5, help="Walk-forward windows")
    parser.add_argument("--balance", type=float, default=10000, help="Starting balance")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path")
    args = parser.parse_args()

    from backtest.portfolio_blend import (
        build_passing_strategy_specs,
        format_portfolio_report,
        run_portfolio_blend,
    )

    print("=" * 80)
    print("PORTFOLIO BLEND TESTING — AYUAA-487")
    print("=" * 80)
    print()

    specs = build_passing_strategy_specs(DATA_DIR)
    print(f"Loading {len(specs)} strategy specs:")
    for s in specs:
        print(f"  - {s.name} ({s.pair} {s.timeframe})")
    print()

    t0 = time.time()
    result = run_portfolio_blend(
        strategy_specs=specs,
        initial_balance=args.balance,
        n_walk_forward_windows=args.windows,
    )
    elapsed = time.time() - t0

    report = format_portfolio_report(result)
    print(report)
    print(f"\nCompleted in {elapsed:.1f}s")

    output_path = args.output or str(REPORTS_DIR / "portfolio_blend_results.json")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    report_data = {
        "ftmo_passed": result.ftmo_passed,
        "ftmo_criteria": result.ftmo_criteria,
        "weight_method": result.weights.method,
        "weights": result.weights.weights,
        "correlation_average": result.correlation.average_correlation,
        "correlation_matrix": result.correlation.matrix,
        "individual": {
            key: {
                "strategy": ec.strategy_name,
                "pair": ec.pair,
                "timeframe": ec.timeframe,
                "win_rate": ec.win_rate,
                "profit_factor": ec.profit_factor,
                "sharpe_ratio": ec.sharpe_ratio,
                "max_drawdown": ec.max_drawdown,
                "trade_count": ec.trade_count,
                "total_pnl": ec.total_pnl,
            }
            for key, ec in result.individual_results.items()
        },
        "combined": {
            "win_rate": result.combined_metrics.win_rate,
            "profit_factor": result.combined_metrics.profit_factor,
            "sharpe_ratio": result.combined_metrics.sharpe_ratio,
            "max_drawdown_pct": result.combined_metrics.max_drawdown_pct,
            "total_pnl": result.combined_metrics.total_pnl,
            "total_pnl_pct": result.combined_metrics.total_pnl_pct,
            "starting_balance": result.combined_metrics.starting_balance,
            "ending_balance": result.combined_metrics.ending_balance,
        },
        "walk_forward": None,
    }

    if result.walk_forward:
        wf = result.walk_forward
        report_data["walk_forward"] = {
            "go_nogo": wf.go_nogo,
            "per_window": [
                {
                    "window_index": m.window_index,
                    "win_rate": m.win_rate,
                    "profit_factor": m.profit_factor,
                    "max_drawdown": m.max_drawdown,
                    "sharpe_ratio": m.sharpe_ratio,
                    "trade_count": m.trade_count,
                    "total_pnl": m.total_pnl,
                    "passed_go_nogo": m.passed_go_nogo,
                }
                for m in wf.per_window
            ],
            "aggregated": (
                {
                    "mean_win_rate": wf.aggregated.mean_win_rate,
                    "std_win_rate": wf.aggregated.std_win_rate,
                    "mean_profit_factor": wf.aggregated.mean_profit_factor,
                    "std_profit_factor": wf.aggregated.std_profit_factor,
                    "mean_max_drawdown": wf.aggregated.mean_max_drawdown,
                    "std_max_drawdown": wf.aggregated.std_max_drawdown,
                    "mean_sharpe_ratio": wf.aggregated.mean_sharpe_ratio,
                    "std_sharpe_ratio": wf.aggregated.std_sharpe_ratio,
                    "mean_trade_count": wf.aggregated.mean_trade_count,
                    "mean_total_pnl": wf.aggregated.mean_total_pnl,
                    "windows_passed": wf.aggregated.windows_passed,
                    "total_windows": wf.aggregated.total_windows,
                }
                if wf.aggregated
                else None
            ),
        }

    with open(output_path, "w") as f:
        json.dump(report_data, f, indent=2)
    print(f"\nReport saved: {output_path}")


if __name__ == "__main__":
    main()
