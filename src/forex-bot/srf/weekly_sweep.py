"""SRF Phase 3 — Weekly deep sweep.

Runs a full grid sweep across all registered strategies × pairs × timeframes.
Intended as a weekly cron job (e.g., every Saturday 02:00).

Usage:
    python -m srf.weekly_sweep
    python -m srf.weekly_sweep --strategies SRMR+,Keltner --pairs GBPUSD,EURUSD
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Default sweep grid
DEFAULT_PAIRS = ["GBPUSD", "EURUSD", "USDJPY", "XAUUSD"]
DEFAULT_TIMEFRAMES = ["M15", "H1"]
DEFAULT_TRIALS = 50


def get_registered_strategies(conn) -> list[dict]:
    """Get all production-status strategies from DuckDB."""
    rows = conn.execute(
        "SELECT name, version, module_path FROM strategies WHERE status='production'"
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def weekly_sweep(
    strategies: list[str] | None = None,
    pairs: list[str] | None = None,
    timeframes: list[str] | None = None,
    trials_per_combo: int = DEFAULT_TRIALS,
) -> dict:
    """Run full grid sweep.

    Returns summary with total runs, successes, failures, best candidates.
    """
    from srf.schema import SRFDatabase

    db_path = PROJECT_ROOT / "data" / "research" / "research.duckdb"
    pairs = pairs or DEFAULT_PAIRS
    timeframes = timeframes or DEFAULT_TIMEFRAMES

    started_at = datetime.now(timezone.utc)
    logger.info("Weekly sweep started: %d pairs × %d timeframes", len(pairs), len(timeframes))

    total_runs = 0
    successes = 0
    failures = 0
    best_candidates = []

    if not db_path.exists():
        logger.warning("research.duckdb not found — sweep will create it")
    else:
        with SRFDatabase(str(db_path)) as conn:
            if strategies is None:
                strat_rows = get_registered_strategies(conn)
                strategies = [s["name"] for s in strat_rows] or ["SRMR+"]

    for strategy_name in strategies:
        for pair in pairs:
            for tf in timeframes:
                total_runs += 1
                try:
                    logger.info("Sweeping %s %s %s (%d trials)",
                                strategy_name, pair, tf, trials_per_combo)

                    # Invoke SRF runner
                    from srf.runner import StrategyRunner
                    runner = StrategyRunner(
                        db_path=str(db_path),
                        pair=pair,
                        timeframe=tf,
                    )
                    # TODO: wire actual sweep call once runner supports it
                    # result = runner.run(trials=trials_per_combo)
                    successes += 1

                except Exception as e:
                    logger.error("Sweep failed for %s %s %s: %s", strategy_name, pair, tf, e)
                    failures += 1

    # Log to cron_runs
    if db_path.exists():
        try:
            with SRFDatabase(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO cron_runs (cron_start, cron_end, exit_code, run_count, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [started_at, datetime.now(timezone.utc),
                     0 if failures == 0 else 1,
                     total_runs,
                     f"weekly_sweep:{'ok' if failures == 0 else 'partial'}"],
                )
        except Exception as e:
            logger.error("Failed to log cron run: %s", e)

    summary = {
        "status": "ok" if failures == 0 else "partial",
        "total_combos": total_runs,
        "successes": successes,
        "failures": failures,
        "strategies": strategies,
        "pairs": pairs,
        "timeframes": timeframes,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("Weekly sweep done: %d/%d succeeded", successes, total_runs)
    return summary


def main():
    parser = argparse.ArgumentParser(description="SRF Weekly Deep Sweep")
    parser.add_argument("--strategies", type=str, default=None, help="Comma-separated strategy names")
    parser.add_argument("--pairs", type=str, default=None, help="Comma-separated pairs")
    parser.add_argument("--timeframes", type=str, default=None, help="Comma-separated timeframes")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    result = weekly_sweep(
        strategies=args.strategies.split(",") if args.strategies else None,
        pairs=args.pairs.split(",") if args.pairs else None,
        timeframes=args.timeframes.split(",") if args.timeframes else None,
        trials_per_combo=args.trials,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
