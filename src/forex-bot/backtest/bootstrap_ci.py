#!/usr/bin/env python3
"""Bootstrap resampling confidence intervals for backtest Profit Factor.

Computes a bootstrap CI for the profit factor (PF) metric by resampling
trade-level PnL values with replacement.  Returns the point estimate
(PF of the full sample) and the lower bound of the confidence interval.

Usage::

    python -m backtest.bootstrap_ci results.json
    python -m backtest.bootstrap_ci results.json --iterations 20000
    python -m backtest.bootstrap_ci results.json --confidence 0.99

Input JSON format (any of the following keys)::

    {"trades": [{"pnl": 12.5}, {"pnl": -8.3}, ...]}
    {"pnls": [12.5, -8.3, ...]}
    {"pnl": [12.5, -8.3, ...]}

Output (JSON to stdout)::

    {
      "profit_factor": 1.42,
      "ci_lower": 1.08,
      "ci_upper": 1.79,
      "confidence": 0.95,
      "iterations": 10000,
      "n_trades": 87,
      "gross_profit": 520.0,
      "gross_loss": 366.2
    }
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from typing import Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_ITERATIONS = 10_000
DEFAULT_CONFIDENCE = 0.95
DEFAULT_SEED = 42

PF_CAP = 99.0  # mirrors walk_forward_runner._sanitize_profit_factor
PF_EPSILON = 1e-12  # avoid division-by-zero when gross_loss is ~0


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_profit_factor(pnls: Sequence[float]) -> float:
    """Compute profit factor from a sequence of trade PnL values.

    PF = gross_profit / gross_loss  (both positive quantities).

    Returns ``0.0`` when there are no trades or all trades are break-even.
    Returns :data:`PF_CAP` when gross_loss is zero but gross_profit > 0
    (would be +Infinity).
    """
    if not pnls:
        return 0.0

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))

    if gross_loss < PF_EPSILON:
        if gross_profit < PF_EPSILON:
            return 0.0
        return PF_CAP

    pf = gross_profit / gross_loss
    if math.isnan(pf):
        return 0.0
    if math.isinf(pf):
        return PF_CAP
    return pf


def bootstrap_pf(
    pnls: Sequence[float],
    *,
    iterations: int = DEFAULT_ITERATIONS,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Bootstrap resampling CI for profit factor.

    Parameters
    ----------
    pnls
        Sequence of per-trade profit/loss values.
    iterations
        Number of bootstrap resamples.
    confidence
        Confidence level (0–1).  ``0.95`` → 95% CI.
    seed
        RNG seed for reproducibility.

    Returns
    -------
    dict with keys:
        ``profit_factor`` — point estimate from the full sample.
        ``ci_lower`` — lower bound of the confidence interval.
        ``ci_upper`` — upper bound of the confidence interval.
        ``confidence`` — confidence level used.
        ``iterations`` — number of bootstrap iterations.
        ``n_trades`` — number of trades in the input.
        ``gross_profit`` — sum of winning trades.
        ``gross_loss`` — absolute sum of losing trades.
    """
    n = len(pnls)

    # Degenerate cases
    if n == 0:
        return _empty_result(confidence, iterations)
    if n == 1:
        # Single trade — no distribution to sample from
        pf = compute_profit_factor(pnls)
        gp, gl = _gross(pnls)
        return {
            "profit_factor": round(pf, 6),
            "ci_lower": round(pf, 6),
            "ci_upper": round(pf, 6),
            "confidence": confidence,
            "iterations": iterations,
            "n_trades": n,
            "gross_profit": round(gp, 6),
            "gross_loss": round(gl, 6),
        }

    # Point estimate
    point_pf = compute_profit_factor(pnls)
    gp, gl = _gross(pnls)

    # Bootstrap
    rng = random.Random(seed)
    alpha = 1.0 - confidence
    lower_pct = alpha / 2.0 * 100  # e.g. 2.5 for 95% CI
    upper_pct = (1.0 - alpha / 2.0) * 100  # e.g. 97.5

    boot_pfs: list[float] = []
    pnls_list = list(pnls)  # ensure indexable

    for _ in range(iterations):
        sample = [pnls_list[rng.randrange(n)] for _ in range(n)]
        boot_pfs.append(compute_profit_factor(sample))

    boot_pfs.sort()
    ci_lower = _percentile(boot_pfs, lower_pct)
    ci_upper = _percentile(boot_pfs, upper_pct)

    return {
        "profit_factor": round(point_pf, 6),
        "ci_lower": round(ci_lower, 6),
        "ci_upper": round(ci_upper, 6),
        "confidence": confidence,
        "iterations": iterations,
        "n_trades": n,
        "gross_profit": round(gp, 6),
        "gross_loss": round(gl, 6),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gross(pnls: Sequence[float]) -> tuple[float, float]:
    """Return (gross_profit, gross_loss) as positive quantities."""
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    return gp, gl


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile on a pre-sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    # Clamp pct to [0, 100]
    pct = max(0.0, min(100.0, pct))
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return sorted_vals[lo]
    frac = rank - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _empty_result(confidence: float, iterations: int) -> dict:
    return {
        "profit_factor": 0.0,
        "ci_lower": 0.0,
        "ci_upper": 0.0,
        "confidence": confidence,
        "iterations": iterations,
        "n_trades": 0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
    }


def _parse_pnls(data: dict | list) -> list[float]:
    """Extract a list of PnL values from parsed JSON input.

    Accepts any of:
      ``{"trades": [{"pnl": 12.5}, ...]}``
      ``{"pnls": [12.5, ...]}``
      ``{"pnl": [12.5, ...]}``
      ``[12.5, -8.3, ...]``  (bare list)
    """
    if isinstance(data, list):
        return [float(x) for x in data]

    if isinstance(data, dict):
        for key in ("pnls", "pnl"):
            if key in data and isinstance(data[key], list):
                return [float(x) for x in data[key]]
        if "trades" in data and isinstance(data["trades"], list):
            trades = data["trades"]
            vals: list[float] = []
            for t in trades:
                if isinstance(t, dict) and "pnl" in t:
                    vals.append(float(t["pnl"]))
            return vals

    raise ValueError(
        "Unrecognised input format. Expected {'trades': [{'pnl': ...}, ...]}, "
        "{'pnls': [...]}, {'pnl': [...]}, or a bare list of floats."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backtest.bootstrap_ci",
        description="Bootstrap resampling CI for backtest Profit Factor.",
    )
    parser.add_argument(
        "results",
        type=str,
        help="Path to JSON file containing trade PnL data.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"Number of bootstrap resamples (default: {DEFAULT_ITERATIONS}).",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=DEFAULT_CONFIDENCE,
        help=f"Confidence level 0–1 (default: {DEFAULT_CONFIDENCE}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"RNG seed for reproducibility (default: {DEFAULT_SEED}).",
    )
    args = parser.parse_args(argv)

    # Read input
    results_path = args.results
    try:
        with open(results_path, "r") as f:
            raw = json.load(f)
    except FileNotFoundError:
        print(f"Error: file not found: {results_path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {results_path}: {exc}", file=sys.stderr)
        return 2

    # Parse PnL values
    try:
        pnls = _parse_pnls(raw)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    # Compute
    result = bootstrap_pf(
        pnls,
        iterations=args.iterations,
        confidence=args.confidence,
        seed=args.seed,
    )

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
