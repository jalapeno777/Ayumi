#!/usr/bin/env python3
"""
Ayumi Trial Log — Comprehensive strategy trial tracking.

Every backtest run, optuna sweep trial, manual parameter test, feature
evaluation, and strategy variant gets logged here.  The total trial count
feeds into the Deflated Sharpe Ratio (DSR) calculation to correct for
multiple-testing bias.

Usage
-----
Manual entry:

    python scripts/log_trial.py \
        --strategy EMA_Cross \
        --symbol XAUUSD \
        --result abandoned \
        --source manual \
        --sharpe 0.42 \
        --profit-factor 1.08 \
        --max-dd -0.15 \
        --note "fast/slow 10/55, tight SL"

Count trials (for DSR integration):

    python scripts/log_trial.py --count

Count trials filtered by symbol:

    python scripts/log_trial.py --count --symbol XAUUSD

Schema (JSONL — one JSON object per line)
-----------------------------------------
{
    "ts":             "2026-07-16T00:30:00Z",   # ISO-8601 UTC timestamp
    "strategy_name":  "EMA_Cross",              # strategy identifier
    "symbol":         "XAUUSD",                  # trading instrument
    "source":         "optuna",                  # optuna | backtest | manual | feature_eval
    "outcome":        "fail",                    # pass | fail | abandoned
    "sharpe":         0.42,                      # annualised Sharpe ratio (nullable)
    "profit_factor":  1.08,                      # gross profit / gross loss (nullable)
    "max_drawdown":   -0.15,                     # maximum drawdown as decimal (nullable)
    "config_hash":    "a1b2c3d4",                # short hash of config dict (nullable)
    "note":           "fast/slow 10/55"          # free-text context (nullable)
}

Integration notes
-----------------
Backtest runner and optuna sweep should import the ``log_trial`` function
and call it automatically after each run:

    from scripts.log_trial import log_trial
    log_trial(strategy_name="EMA_Cross", symbol="XAUUSD",
              source="backtest", outcome="pass", sharpe=1.2)

This module is dependency-free (stdlib only) so it can be imported from
anywhere in the pipeline without adding requirements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Resolve trial log path relative to project root (two levels up from this script)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRIAL_LOG_PATH = _PROJECT_ROOT / "data" / "ayumi" / "trial_log.jsonl"

VALID_SOURCES = {"optuna", "backtest", "manual", "feature_eval"}
VALID_OUTCOMES = {"pass", "fail", "abandoned"}


def _utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def config_hash(config: dict[str, Any]) -> str:
    """Compute a short 8-char hash from a config dictionary."""
    raw = json.dumps(config, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:8]


def log_trial(
    strategy_name: str,
    symbol: str,
    source: str,
    outcome: str,
    *,
    sharpe: float | None = None,
    profit_factor: float | None = None,
    max_drawdown: float | None = None,
    config_hash: str | None = None,
    note: str | None = None,
    log_path: Path = TRIAL_LOG_PATH,
) -> dict[str, Any]:
    """
    Append a single trial entry to the JSONL log.

    Parameters
    ----------
    strategy_name : str
        Strategy identifier (e.g. ``"EMA_Cross"``).
    symbol : str
        Trading instrument (e.g. ``"XAUUSD"``).
    source : str
        Trial source: ``optuna``, ``backtest``, ``manual``, ``feature_eval``.
    outcome : str
        Trial outcome: ``pass``, ``fail``, ``abandoned``.
    sharpe : float | None
        Annualised Sharpe ratio, if available.
    profit_factor : float | None
        Gross profit / gross loss ratio, if available.
    max_drawdown : float | None
        Maximum drawdown as a decimal (e.g. ``-0.15`` for -15%).
    config_hash : str | None
        Short hash of the config dict, if available.
    note : str | None
        Free-text context.
    log_path : Path
        Override path for testing.

    Returns
    -------
    dict
        The entry dict that was written.

    Raises
    ------
    ValueError
        If ``source`` or ``outcome`` is not a recognised value.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid source '{source}'. Must be one of {VALID_SOURCES}")
    if outcome not in VALID_OUTCOMES:
        raise ValueError(
            f"Invalid outcome '{outcome}'. Must be one of {VALID_OUTCOMES}"
        )

    entry: dict[str, Any] = {
        "ts": _utc_now_iso(),
        "strategy_name": strategy_name,
        "symbol": symbol,
        "source": source,
        "outcome": outcome,
        "sharpe": sharpe,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "config_hash": config_hash,
        "note": note,
    }

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

    return entry


def count_trials(
    symbol: str | None = None,
    strategy: str | None = None,
    log_path: Path | str = TRIAL_LOG_PATH,
) -> int:
    """
    Count total logged trials, optionally filtered by symbol or strategy.

    This function is intended for DSR integration — pass the result as
    ``N`` in the Deflated Sharpe Ratio formula.
    """
    log_path = Path(log_path)
    if not log_path.exists():
        return 0

    count = 0
    with open(log_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if symbol and entry.get("symbol") != symbol:
                continue
            if strategy and entry.get("strategy_name") != strategy:
                continue
            count += 1
    return count


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ayumi trial log — track every strategy config tested.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--strategy", type=str, help="Strategy name (e.g. EMA_Cross)")
    parser.add_argument("--symbol", type=str, help="Trading symbol (e.g. XAUUSD)")
    parser.add_argument(
        "--source",
        type=str,
        choices=sorted(VALID_SOURCES),
        help="Trial source",
    )
    parser.add_argument(
        "--result",
        type=str,
        choices=sorted(VALID_OUTCOMES),
        help="Trial outcome",
    )
    parser.add_argument("--sharpe", type=float, default=None, help="Sharpe ratio")
    parser.add_argument(
        "--profit-factor", type=float, default=None, help="Profit factor"
    )
    parser.add_argument(
        "--max-dd",
        type=float,
        default=None,
        help="Max drawdown as decimal (e.g. -0.15 for -15%%)",
    )
    parser.add_argument(
        "--config-hash", type=str, default=None, help="Short hash of config dict"
    )
    parser.add_argument("--note", type=str, default=None, help="Free-text context")
    parser.add_argument(
        "--count",
        action="store_true",
        help="Print total trial count and exit (for DSR integration)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --- Count mode ---
    if args.count:
        n = count_trials(symbol=args.symbol, strategy=args.strategy)
        print(n)
        return 0

    # --- Log mode: validate required fields ---
    missing = [
        name
        for name, val in [
            ("--strategy", args.strategy),
            ("--symbol", args.symbol),
            ("--source", args.source),
            ("--result", args.result),
        ]
        if not val
    ]
    if missing:
        parser.error(f"Missing required arguments: {', '.join(missing)}")

    entry = log_trial(
        strategy_name=args.strategy,
        symbol=args.symbol,
        source=args.source,
        outcome=args.result,
        sharpe=args.sharpe,
        profit_factor=args.profit_factor,
        max_drawdown=args.max_dd,
        config_hash=args.config_hash,
        note=args.note,
    )
    print(
        f"Logged trial #{count_trials()} — {entry['strategy_name']} ({entry['outcome']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
