#!/usr/bin/env python3
"""CLI entry point for FTMO challenge simulation.

Usage::

    python -m forex_bot.backtest.run_ftmo_sim [options]

Examples::

    # Run with default settings
    python -m forex_bot.backtest.run_ftmo_sim

    # Custom account size and input file
    python -m forex_bot.backtest.run_ftmo_sim \\
        --input data/forex/historical/wf_results.csv \\
        --account-size 10000

    # Filter by strategy
    python -m forex_bot.backtest.run_ftmo_sim --strategy srmr_plus

    # Output to file
    python -m forex_bot.backtest.run_ftmo_sim --output results.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
import types
from pathlib import Path

# Project root for path resolution
# File: src/forex-bot/backtest/run_ftmo_sim.py → up 3 levels = workspace root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_BT_DIR = PROJECT_ROOT / "src" / "forex-bot" / "backtest"

# ── Import the ftmo_simulation module without triggering backtest/__init__.py
# The backtest package's __init__.py imports heavy deps (statsmodels etc.)
# that may not be installed. The FTMO simulation is self-contained, so we
# load it directly via importlib and stub the package.

if "backtest" not in sys.modules:
    _backtest_pkg = types.ModuleType("backtest")
    _backtest_pkg.__path__ = [str(_BT_DIR)]
    sys.modules["backtest"] = _backtest_pkg

_sim_path = _BT_DIR / "ftmo_simulation.py"
_spec = importlib.util.spec_from_file_location("backtest.ftmo_simulation", _sim_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["backtest.ftmo_simulation"] = _mod
_spec.loader.exec_module(_mod)

CSV_COLUMNS = _mod.CSV_COLUMNS
FTMOConfig = _mod.FTMOConfig
FTMOSimulation = _mod.FTMOSimulation

logger = logging.getLogger("ayumi.run_ftmo_sim")

DEFAULT_INPUT = "data/forex/historical/wf_results.csv"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run FTMO challenge simulation on walk-forward backtest results.",
    )
    parser.add_argument(
        "--input",
        "-i",
        default=DEFAULT_INPUT,
        help=f"Path to walk-forward results CSV (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--account-size",
        type=float,
        default=10_000.0,
        help="Starting account size in account currency (default: 10000)",
    )
    parser.add_argument(
        "--daily-loss-limit",
        type=float,
        default=0.05,
        help="Daily loss limit as fraction, e.g. 0.05 = 5%% (default: 0.05)",
    )
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=0.10,
        help="Max total drawdown as fraction (default: 0.10)",
    )
    parser.add_argument(
        "--profit-target",
        type=float,
        default=0.10,
        help="Profit target as fraction (default: 0.10)",
    )
    parser.add_argument(
        "--strategy",
        "-s",
        default=None,
        help="Filter to a specific strategy (default: all + per-strategy)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output JSON file path (default: stdout)",
    )
    parser.add_argument(
        "--no-stop-on-violation",
        action="store_true",
        help="Continue processing trades after violations (default: stop)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the FTMO simulation CLI.

    Returns:
        0 if all simulations passed, 1 if any failed.
    """
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config = FTMOConfig(
        account_size=args.account_size,
        daily_loss_limit_pct=args.daily_loss_limit,
        max_drawdown_pct=args.max_drawdown,
        profit_target_pct=args.profit_target,
    )

    input_path = Path(args.input)
    if not input_path.is_absolute():
        # Resolve relative to project root
        input_path = PROJECT_ROOT / args.input

    try:
        trades = FTMOSimulation.load_trades(input_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            f"\nExpected CSV format with columns: {','.join(CSV_COLUMNS)}",
            file=sys.stderr,
        )
        return 2
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not trades:
        print(
            "WARNING: No trades loaded from CSV. Output will be empty.", file=sys.stderr
        )

    sim = FTMOSimulation(config)

    if args.strategy:
        result = sim.run(
            trades,
            strategy_filter=args.strategy,
            stop_on_violation=not args.no_stop_on_violation,
        )
        output = {"results": {args.strategy: result.to_dict()}}
    else:
        results = sim.run_per_strategy(
            trades,
            stop_on_violation=not args.no_stop_on_violation,
        )
        output = {
            "results": {k: v.to_dict() for k, v in results.items()},
        }

    # Summary
    all_passed = (
        all(r["passed"] for r in output["results"].values())
        if output["results"]
        else False
    )
    output["summary"] = {
        "total_strategies": len(output["results"]),
        "passed": sum(1 for r in output["results"].values() if r["passed"]),
        "failed": sum(1 for r in output["results"].values() if not r["passed"]),
        "overall_pass": all_passed,
    }

    output_json = json.dumps(output, indent=2, default=str)

    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
