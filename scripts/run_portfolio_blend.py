#!/usr/bin/env python3
"""Portfolio Blend Testing — AYUAA-481

Combines all passing strategies into a unified portfolio, filters unprofitable ones,
tests correlation, optimizes weights across multiple methods, runs walk-forward
validation, and evaluates against FTMO criteria.
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
    parser.add_argument(
        "--weight-method",
        type=str,
        default="combined_score",
        choices=["inverse_variance", "equal_risk", "profit_factor", "sharpe_weighted", "combined_score"],
        help="Weight optimization method",
    )
    parser.add_argument("--no-filter", action="store_true", help="Disable strategy filtering")
    parser.add_argument("--compare", action="store_true", help="Compare all weight methods")
    args = parser.parse_args()

    from backtest.portfolio_blend import (
        WEIGHT_METHODS,
        build_passing_strategy_specs,
        format_portfolio_report,
        run_portfolio_blend,
    )

    print("=" * 80)
    print("PORTFOLIO BLEND TESTING — AYUAA-481")
    print("=" * 80)
    print()

    specs = build_passing_strategy_specs(DATA_DIR)
    print(f"Loading {len(specs)} strategy specs:")
    for s in specs:
        print(f"  - {s.name} ({s.pair} {s.timeframe})")
    print()

    enable_filter = not args.no_filter
    best_result = None
    best_method = args.weight_method
    filtered_out: list = []

    if args.compare:
        print("COMPARING ALL WEIGHT METHODS")
        print("=" * 80)
        comparison = {}
        for method_name in WEIGHT_METHODS:
            result = run_portfolio_blend(
                strategy_specs=specs,
                initial_balance=args.balance,
                n_walk_forward_windows=args.windows,
                weight_method=method_name,
                enable_filter=enable_filter,
            )
            m = result.combined_metrics
            comparison[method_name] = {
                "wr": m.win_rate,
                "pf": m.profit_factor,
                "sharpe": m.sharpe_ratio,
                "dd": m.max_drawdown_pct,
                "pnl": m.total_pnl,
                "ftmo": result.ftmo_passed,
                "wf_go": result.walk_forward.go_nogo if result.walk_forward else False,
            }
            wf_score = 0
            if result.walk_forward and result.walk_forward.aggregated:
                a = result.walk_forward.aggregated
                wf_score = a.mean_win_rate * 100 + a.mean_profit_factor + a.mean_sharpe_ratio

            score = (
                (10 if result.ftmo_passed else 0)
                + (10 if comparison[method_name]["wf_go"] else 0)
                + m.profit_factor * 2
                + m.sharpe_ratio
                + wf_score
            )
            comparison[method_name]["score"] = score

            if best_result is None or score > comparison[best_method].get("score", 0):
                best_result = result
                best_method = method_name

            if method_name == "combined_score":
                _, filtered_out = _get_filtered(specs, args.balance, enable_filter)

        print(f"{'Method':<20} {'WR%':>6} {'PF':>7} {'Sharpe':>7} {'DD%':>7} {'PnL':>10} {'FTMO':>6} {'WF GO':>6} {'Score':>7}")
        print("-" * 90)
        for method_name, c in sorted(comparison.items(), key=lambda x: -x[1].get("score", 0)):
            ftmo_str = "PASS" if c["ftmo"] else "FAIL"
            wf_str = "GO" if c["wf_go"] else "NO"
            print(
                f"{method_name:<20} {c['wr']:>6.1f} {c['pf']:>7.2f} {c['sharpe']:>7.2f} "
                f"{c['dd']:>7.2f} ${c['pnl']:>9.2f} {ftmo_str:>6} {wf_str:>6} {c['score']:>7.1f}"
            )
        print()
        print(f"Best method: {best_method}")
        print()
    else:
        t0 = time.time()
        best_result = run_portfolio_blend(
            strategy_specs=specs,
            initial_balance=args.balance,
            n_walk_forward_windows=args.windows,
            weight_method=args.weight_method,
            enable_filter=enable_filter,
        )
        elapsed = time.time() - t0
        best_method = args.weight_method
        filtered_out = _get_filtered(specs, args.balance, enable_filter)[1]
        print(f"Completed in {elapsed:.1f}s\n")

    report = format_portfolio_report(best_result, filtered_strategies=filtered_out if filtered_out else None)
    print(report)

    output_path = args.output or str(REPORTS_DIR / "portfolio_blend_results.json")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    report_data = {
        "weight_method": best_method,
        "strategy_filter_enabled": enable_filter,
        "filtered_strategies": [
            {"key": f.key, "reason": f.reason} for f in filtered_out
        ],
        "ftmo_passed": best_result.ftmo_passed,
        "ftmo_criteria": best_result.ftmo_criteria,
        "weights": best_result.weights.weights,
        "correlation_average": best_result.correlation.average_correlation,
        "correlation_matrix": best_result.correlation.matrix,
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
                "in_blend": key in best_result.weights.weights,
            }
            for key, ec in best_result.individual_results.items()
        },
        "combined": {
            "win_rate": best_result.combined_metrics.win_rate,
            "profit_factor": best_result.combined_metrics.profit_factor,
            "sharpe_ratio": best_result.combined_metrics.sharpe_ratio,
            "max_drawdown_pct": best_result.combined_metrics.max_drawdown_pct,
            "total_pnl": best_result.combined_metrics.total_pnl,
            "total_pnl_pct": best_result.combined_metrics.total_pnl_pct,
            "starting_balance": best_result.combined_metrics.starting_balance,
            "ending_balance": best_result.combined_metrics.ending_balance,
        },
        "walk_forward": None,
    }

    if best_result.walk_forward:
        wf = best_result.walk_forward
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

    if args.compare:
        report_data["method_comparison"] = comparison

    with open(output_path, "w") as f:
        json.dump(report_data, f, indent=2)
    print(f"Report saved: {output_path}")


def _get_filtered(specs, balance, enable_filter):
    if not enable_filter:
        return [], []
    from backtest.portfolio_blend import filter_strategies
    from backtest.portfolio_blend import run_portfolio_blend as _run_blend
    result = _run_blend(
        strategy_specs=specs,
        initial_balance=balance,
        n_walk_forward_windows=0,
        enable_filter=True,
    )
    return result.individual_results, filter_strategies(result.individual_results)[1]


if __name__ == "__main__":
    main()
