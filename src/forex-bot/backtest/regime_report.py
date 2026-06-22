"""Regime Report Generator (BQ-508).

Formats per-regime walk-forward results as human-readable text and
machine-readable JSON. Writes to ``data/backtest/regime_report_<date>.json``.

Usage:
    from backtest.regime_report import generate_regime_report

    report_text = generate_regime_report(results)
    # Also writes JSON to data/backtest/regime_report_2026-06-19.json
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from quant.walk_forward import WalkForwardResults

logger = logging.getLogger(__name__)

# Default output directory for regime reports
DEFAULT_OUTPUT_DIR = Path("data/backtest")


def _format_pct(value: float, precision: int = 2) -> str:
    """Format a 0-1 float as percentage string."""
    return f"{value * 100:.{precision}f}%"


def _format_float(value: float, precision: int = 4) -> str:
    return f"{value:.{precision}f}"


def generate_regime_report(
    results: WalkForwardResults,
    output_dir: str | Path | None = None,
    report_date: str | None = None,
) -> str:
    """Generate a regime breakdown report from walk-forward results.

    Writes JSON output to ``<output_dir>/regime_report_<date>.json`` and
    returns a human-readable text report.

    Args:
        results: WalkForwardResults containing per-window metrics with regime labels.
        output_dir: Directory for JSON output. Defaults to ``data/backtest/``.
        report_date: Date string for filename (YYYY-MM-DD). Defaults to today.

    Returns:
        Formatted text report string.
    """
    # Extract regime breakdown from results (set by walk_forward_runner)
    regime_breakdown: dict[str, dict[str, Any]] = getattr(
        results, "_regime_breakdown", {}
    )

    # If no breakdown was computed, compute it on the fly
    if not regime_breakdown and results.per_window:
        from backtest.walk_forward_runner import aggregate_by_regime

        regime_breakdown = aggregate_by_regime(results.per_window)

    # Build JSON structure
    report_date_str = report_date or date.today().isoformat()

    # Per-window detail for JSON
    window_details = []
    for m in results.per_window:
        window_details.append(
            {
                "window": m.window_index,
                "regime_combined": m.regime_combined,
                "regime_volatility": m.regime_volatility,
                "regime_trend": m.regime_trend,
                "regime_session": m.regime_session,
                "btc_regime": m.btc_regime,
                "win_rate": round(m.win_rate, 6),
                "profit_factor": round(m.profit_factor, 6),
                "sharpe_ratio": round(m.sharpe_ratio, 6),
                "max_drawdown": round(m.max_drawdown, 6),
                "trade_count": m.trade_count,
                "total_pnl": round(m.total_pnl, 6),
                "passed_go_nogo": m.passed_go_nogo,
            }
        )

    json_payload = {
        "report_date": report_date_str,
        "total_windows": len(results.per_window),
        "regime_breakdown": regime_breakdown,
        "per_window": window_details,
    }

    # Write JSON
    out_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"regime_report_{report_date_str}.json"

    try:
        with json_path.open("w") as f:
            json.dump(json_payload, f, indent=2)
        logger.info("Regime report JSON written to %s", json_path)
    except OSError as exc:
        logger.error("Failed to write regime report JSON: %s", exc)

    # Build text report
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("REGIME PERFORMANCE REPORT")
    lines.append(f"Date: {report_date_str}")
    lines.append("=" * 80)
    lines.append("")

    # Summary
    agg = results.aggregated
    if agg:
        lines.append("OVERALL SUMMARY")
        lines.append("-" * 40)
        lines.append(f"  Total Windows:     {agg.total_windows}")
        lines.append(f"  Windows Passed:    {agg.windows_passed}")
        lines.append(f"  Mean Win Rate:     {_format_pct(agg.mean_win_rate)}")
        lines.append(f"  Mean Profit Factor:{_format_float(agg.mean_profit_factor)}")
        lines.append(f"  Mean Sharpe:       {_format_float(agg.mean_sharpe_ratio)}")
        lines.append(f"  Mean Max DD:       {_format_pct(agg.mean_max_drawdown)}")
        lines.append("")

    # Per-regime breakdown
    if regime_breakdown:
        lines.append("PER-REGIME BREAKDOWN")
        lines.append("-" * 80)
        header = (
            f"{'Regime':<40} {'N':>4} {'Reliability':<14} "
            f"{'Win%':>8} {'PF':>8} {'Sharpe':>8} {'MaxDD':>8}"
        )
        lines.append(header)
        lines.append("-" * 80)

        # Sort regimes by sample count descending
        for regime, stats in sorted(
            regime_breakdown.items(),
            key=lambda x: x[1]["sample_count"],
            reverse=True,
        ):
            lines.append(
                f"{regime:<40} "
                f"{stats['sample_count']:>4} "
                f"{stats['reliability']:<14} "
                f"{_format_pct(stats['mean_win_rate']):>8} "
                f"{_format_float(stats['mean_profit_factor']):>8} "
                f"{_format_float(stats['mean_sharpe_ratio']):>8} "
                f"{_format_pct(stats['mean_max_drawdown']):>8}"
            )
        lines.append("-" * 80)
        lines.append("")
    else:
        lines.append("No regime breakdown available.")
        lines.append("")

    # Per-window detail
    if results.per_window:
        lines.append("PER-WINDOW DETAIL")
        lines.append("-" * 100)
        header = (
            f"{'Win':>4} {'Regime':<35} {'BTC':<15} "
            f"{'WR':>8} {'PF':>8} {'DD':>8} {'Sh':>8} {'Tr':>6} {'GO?':>5}"
        )
        lines.append(header)
        lines.append("-" * 100)

        for m in results.per_window:
            lines.append(
                f"{m.window_index:>4} "
                f"{m.regime_combined:<35} "
                f"{m.btc_regime:<15} "
                f"{_format_pct(m.win_rate):>8} "
                f"{_format_float(m.profit_factor):>8} "
                f"{_format_pct(m.max_drawdown):>8} "
                f"{_format_float(m.sharpe_ratio):>8} "
                f"{m.trade_count:>6} "
                f"{'YES' if m.passed_go_nogo else 'NO':>5}"
            )
        lines.append("-" * 100)

    lines.append("")
    lines.append("Reliability flags:")
    lines.append("  exploratory = <3 samples (statistically unreliable)")
    lines.append("  tentative   = 3-9 samples (directional only)")
    lines.append("  robust      = ≥10 samples (meaningful signal)")
    lines.append("")
    lines.append("=" * 80)

    return "\n".join(lines)
