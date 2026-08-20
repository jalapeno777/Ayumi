#!/usr/bin/env python3
"""Deflated Sharpe Ratio (DSR) with combined-criteria guard for backtest evaluation.

Implements the Deflated Sharpe Ratio per Bailey & López de Prado (2014) with
a combined-criteria gate: when the number of trades is below 30, the module
returns an "insufficient" verdict rather than relying on DSR alone.

This module provides both a standalone computation path (using numpy/scipy
when available) and a graceful fallback for environments without scipy.
It is designed to be importable by ``scripts/build_report.py`` and the
re-sweep pipeline.

Usage::

    python -m backtest.dsr --input strategy_results.json
    python -m backtest.dsr --pnls 0.01 -0.02 0.005 --n-trials 6 --name ttc_xauusd

Input JSON format (single strategy)::

    {
      "name": "ttc_xauusd",
      "pnls": [0.01, -0.02, 0.005, ...],
      "n_independent_trials": 6,
      "bar_period_minutes": 15,
      "risk_free_rate": 0.0
    }

Output (JSON to stdout)::

    {
      "name": "ttc_xauusd",
      "verdict": "sufficient",
      "n_trades": 49,
      "sharpe": 2.15,
      "dsr_pvalue": 0.031,
      "edge_probability": 0.969,
      "min_track_record_length": 32.5,
      "skewness": -0.12,
      "kurtosis": 3.45,
      "n_independent_trials": 6,
      "combined_criteria": {
        "sharpe_positive": true,
        "dsr_significant": true,
        "sufficient_trades": true,
        "verdict": "promote"
      }
    }
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_TRADES_FOR_DSR = 30
DEFAULT_N_INDEPENDENT_TRIALS = 6  # 6 strategies in the corrected re-sweep
DEFAULT_BAR_PERIOD_MINUTES = 60  # H1 default; M15=15, M5=5, etc.
DEFAULT_RISK_FREE_RATE = 0.0
DEFAULT_ALPHA = 0.05

# Forex annualization factors (24h market, 252 trading days)
TRADING_DAYS_PER_YEAR = 252
HOURS_PER_TRADING_DAY = 24


# ---------------------------------------------------------------------------
# Core DSR computation
# ---------------------------------------------------------------------------


def compute_sharpe(
    pnls: Sequence[float],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    bar_period_minutes: int = DEFAULT_BAR_PERIOD_MINUTES,
) -> float:
    """Compute annualised Sharpe ratio from per-trade PnL values.

    The per-trade returns are treated as independent observations from
    the trading period. The Sharpe is annualised using the forex
    convention of 252 × 24 = 6048 periods per year (adjusted for the
    bar period).

    Returns ``0.0`` when there are fewer than 2 trades or zero variance.
    """
    n = len(pnls)
    if n < 2:
        return 0.0

    mean_ret = sum(pnls) / n
    var = sum((p - mean_ret) ** 2 for p in pnls) / (n - 1)
    std = math.sqrt(var)
    if std < 1e-15:
        return 0.0

    excess = mean_ret - risk_free_rate

    # Annualisation factor
    if bar_period_minutes > 0:
        periods_per_year = (TRADING_DAYS_PER_YEAR * HOURS_PER_TRADING_DAY * 60) / bar_period_minutes
    else:
        periods_per_year = TRADING_DAYS_PER_YEAR * HOURS_PER_TRADING_DAY

    annual_factor = math.sqrt(periods_per_year)
    return (excess / std) * annual_factor


def compute_skewness(pnls: Sequence[float]) -> float:
    """Compute sample skewness of the return distribution."""
    n = len(pnls)
    if n < 3:
        return 0.0

    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    std = math.sqrt(var)
    if std < 1e-15:
        return 0.0

    skew = (n / ((n - 1) * (n - 2))) * sum(((p - mean) / std) ** 3 for p in pnls)
    return skew


def compute_kurtosis(pnls: Sequence[float]) -> float:
    """Compute excess kurtosis of the return distribution.

    Returns regular kurtosis (not excess), so normal distribution ≈ 3.0.
    """
    n = len(pnls)
    if n < 4:
        return 3.0  # normal default

    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    std = math.sqrt(var)
    if std < 1e-15:
        return 3.0

    # Excess kurtosis (Fisher's definition)
    kurt_excess = (n * (n + 1) / ((n - 1) * (n - 2) * (n - 3))) * sum(((p - mean) / std) ** 4 for p in pnls) - (
        3 * (n - 1) ** 2
    ) / ((n - 2) * (n - 3))

    # Convert to regular kurtosis (excess + 3)
    return kurt_excess + 3.0


def expected_max_sharpe(
    n_trials: int,
    variance: float,
    skewness: float,
    kurtosis: float,
) -> float:
    """Compute expected maximum Sharpe under multiple testing (Bailey & López de Prado 2014, Eq. 4).

    ``E[max_Z] ≈ sqrt(2*ln(n)) * (1 - γ/(2*ln(n)) + ...)``

    where γ ≈ 0.5772 (Euler-Mascheroni constant).

    Adjusted for non-normality via the provided moments.
    """
    if n_trials < 1:
        return 0.0

    euler_gamma = 0.5772156649015329

    # For n_trials = 1, expected max is just the mean (0 for standard normal)
    if n_trials == 1:
        # Non-normality adjustment
        adj = skewness / 6.0 * 0.0  # no selection effect with 1 trial
        return adj

    ln_n = math.log(n_trials)
    if ln_n < 1e-15:
        return 0.0

    # Expected max of n i.i.d. standard normals
    e_max = math.sqrt(2.0 * ln_n) * (1.0 - euler_gamma / (2.0 * ln_n))

    # Non-normality adjustment (Bailey Eq. 4):
    # The adjustment shifts the mean of the Sharpe distribution
    # SR_adj ≈ SR * (1 - skew*SR/6 + (kurt-3)*SR²/24)
    # For the expected max, we apply the correction to the variance term
    if variance > 0:
        # Adjusted variance considering skew and kurtosis
        adj_var = variance * (1 + (kurtosis - 3) / 4.0)
        e_max *= math.sqrt(adj_var) if adj_var > 0 else 1.0
        # Skew adjustment shifts the expected max asymmetrically
        e_max += skewness / 6.0 * variance

    return e_max


def deflated_sharpe_ratio(
    pnls: Sequence[float],
    n_independent_trials: int = DEFAULT_N_INDEPENDENT_TRIALS,
    bar_period_minutes: int = DEFAULT_BAR_PERIOD_MINUTES,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict:
    """Compute Deflated Sharpe Ratio with combined-criteria guard.

    Parameters
    ----------
    pnls
        Sequence of per-trade profit/loss values (as decimals or absolute).
    n_independent_trials
        Number of independent strategy trials in the sweep (for multiple-testing correction).
    bar_period_minutes
        Bar period in minutes for Sharpe annualisation (M5=5, M15=15, H1=60, H4=240, D1=1440).
    risk_free_rate
        Per-period risk-free rate (default 0.0).

    Returns
    -------
    dict with keys:
        ``name`` — strategy name (if provided via ``name`` key in input, else "unknown"``).
        ``verdict`` — "sufficient" or "insufficient" (based on MIN_TRADES_FOR_DSR).
        ``n_trades`` — number of trades.
        ``sharpe`` — annualised Sharpe ratio.
        ``dsr_pvalue`` — DSR p-value (probability the observed Sharpe could arise from luck).
        ``edge_probability`` — 1 - dsr_pvalue.
        ``min_track_record_length`` — minimum trades needed to reject H0 at α=0.05.
        ``skewness`` — return distribution skewness.
        ``kurtosis`` — return distribution kurtosis (regular, normal=3).
        ``n_independent_trials`` — trials used for correction.
        ``combined_criteria`` — dict with individual criteria flags and overall verdict.
    """
    n = len(pnls)

    # Insufficient trades guard
    if n < MIN_TRADES_FOR_DSR:
        sharpe = compute_sharpe(pnls, risk_free_rate, bar_period_minutes) if n >= 2 else 0.0
        return {
            "verdict": "insufficient",
            "n_trades": n,
            "sharpe": round(sharpe, 6),
            "dsr_pvalue": None,
            "edge_probability": None,
            "min_track_record_length": None,
            "skewness": round(compute_skewness(pnls), 6) if n >= 3 else 0.0,
            "kurtosis": round(compute_kurtosis(pnls), 6) if n >= 4 else 3.0,
            "n_independent_trials": n_independent_trials,
            "combined_criteria": {
                "sharpe_positive": sharpe > 0,
                "dsr_significant": False,
                "sufficient_trades": False,
                "verdict": "insufficient_trades",
                "note": f"Only {n} trades (minimum {MIN_TRADES_FOR_DSR} required for DSR). "
                f"Combined criteria gate: do NOT promote based on DSR alone.",
            },
        }

    # Sufficient trades — compute full DSR
    sharpe = compute_sharpe(pnls, risk_free_rate, bar_period_minutes)
    skew = compute_skewness(pnls)
    kurt = compute_kurtosis(pnls)

    # Sharpe standard error (Bailey & López de Prado 2014, Eq. 2)
    # SE[SR] = sqrt((1 - skew*SR + (kurt-3)/4 * SR²) / (n-1))
    # Recompute with non-annualised for the DSR formula
    mean_ret = sum(pnls) / n
    var_ret = sum((p - mean_ret) ** 2 for p in pnls) / (n - 1)
    std_ret = math.sqrt(var_ret)
    non_ann_sharpe = (mean_ret - risk_free_rate) / std_ret if std_ret > 1e-15 else 0.0

    sr_se_sq = (1.0 - skew * non_ann_sharpe + (kurt - 3.0) / 4.0 * non_ann_sharpe**2) / (n - 1)
    sr_se = math.sqrt(max(sr_se_sq, 1e-15))

    # Expected max Sharpe under multiple testing
    e_max = expected_max_sharpe(
        n_independent_trials,
        variance=1.0,  # standardised
        skewness=skew,
        kurtosis=kurt,
    )

    # DSR statistic (Bailey & López de Prado 2014, Eq. 5)
    # DSR = (SR_observed - E[max_SR]) / SE[SR]
    # We use the non-annualised Sharpe for this computation
    if sr_se > 1e-15:
        dsr_stat = (non_ann_sharpe - e_max) / sr_se
    else:
        dsr_stat = 0.0

    # P-value from normal CDF: P(Z >= dsr_stat)
    # Using the error function approximation
    dsr_pvalue = _normal_sf(dsr_stat)
    edge_probability = 1.0 - dsr_pvalue

    # Minimum track record length (Bailey & López de Prado 2014, Eq. 7)
    # MinTRL ≈ 1 + (1 - skew*SR + (kurt-3)/4*SR²) * (z_alpha / SR)²
    z_alpha = 1.6449  # z-value for α=0.05 (one-sided)
    if abs(non_ann_sharpe) > 1e-15:
        min_trl_num = 1.0 - skew * non_ann_sharpe + (kurt - 3.0) / 4.0 * non_ann_sharpe**2
        min_trl = 1.0 + min_trl_num * (z_alpha / non_ann_sharpe) ** 2
    else:
        min_trl = float("inf")

    # Combined criteria gate
    sharpe_positive = sharpe > 0
    dsr_significant = dsr_pvalue < DEFAULT_ALPHA if dsr_pvalue is not None else False
    sufficient_trades = n >= MIN_TRADES_FOR_DSR

    if sharpe_positive and dsr_significant and sufficient_trades:
        verdict = "promote"
    elif not sharpe_positive:
        verdict = "reject_negative_sharpe"
    elif not dsr_significant:
        verdict = "hold_dsr_not_significant"
    else:
        verdict = "hold"

    return {
        "verdict": "sufficient",
        "n_trades": n,
        "sharpe": round(sharpe, 6),
        "dsr_pvalue": round(dsr_pvalue, 6),
        "edge_probability": round(edge_probability, 6),
        "min_track_record_length": round(min_trl, 2) if math.isfinite(min_trl) else None,
        "skewness": round(skew, 6),
        "kurtosis": round(kurt, 6),
        "n_independent_trials": n_independent_trials,
        "combined_criteria": {
            "sharpe_positive": sharpe_positive,
            "dsr_significant": dsr_significant,
            "sufficient_trades": sufficient_trades,
            "verdict": verdict,
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normal_sf(x: float) -> float:
    """Survival function P(Z > x) for standard normal.

    Uses the complementary error function approximation.
    """
    # P(Z > x) = 0.5 * erfc(x / sqrt(2))
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def _parse_pnls(data: dict) -> list[float]:
    """Extract PnL list from input dict."""
    for key in ("pnls", "pnl", "returns"):
        if key in data and isinstance(data[key], list):
            return [float(v) for v in data[key]]

    if "trades" in data and isinstance(data["trades"], list):
        trades = data["trades"]
        vals: list[float] = []
        for t in trades:
            if isinstance(t, dict) and "pnl" in t:
                vals.append(float(t["pnl"]))
            elif isinstance(t, (int, float)):
                vals.append(float(t))
        if vals:
            return vals

    raise ValueError("Could not extract PnL values. Expected 'pnls', 'pnl', 'returns', or 'trades' key.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backtest.dsr",
        description="Deflated Sharpe Ratio with combined-criteria guard.",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=None,
        help="Path to JSON file with strategy results.",
    )
    parser.add_argument(
        "--pnls",
        type=float,
        nargs="+",
        default=None,
        help="Inline PnL values (alternative to --input).",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="unknown",
        help="Strategy name (default: unknown).",
    )
    parser.add_argument(
        "--n-trials",
        type=int,
        default=DEFAULT_N_INDEPENDENT_TRIALS,
        help=f"Number of independent strategy trials for multiple-testing correction (default: {DEFAULT_N_INDEPENDENT_TRIALS}).",  # noqa: E501
    )
    parser.add_argument(
        "--bar-minutes",
        type=int,
        default=DEFAULT_BAR_PERIOD_MINUTES,
        help=f"Bar period in minutes for Sharpe annualisation (default: {DEFAULT_BAR_PERIOD_MINUTES}).",
    )
    args = parser.parse_args(argv)

    # Get PnL values
    if args.input:
        try:
            with open(args.input, "r") as f:
                raw = json.load(f)
        except FileNotFoundError:
            print(f"Error: file not found: {args.input}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"Error: invalid JSON: {exc}", file=sys.stderr)
            return 2

        try:
            pnls = _parse_pnls(raw)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

        name = raw.get("name", args.name)
        n_trials = raw.get("n_independent_trials", args.n_trials)
        bar_min = raw.get("bar_period_minutes", args.bar_minutes)
    elif args.pnls:
        pnls = args.pnls
        name = args.name
        n_trials = args.n_trials
        bar_min = args.bar_minutes
    else:
        parser.error("Either --input or --pnls must be provided.")
        return 2

    result = deflated_sharpe_ratio(
        pnls,
        n_independent_trials=n_trials,
        bar_period_minutes=bar_min,
    )
    result["name"] = name

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
