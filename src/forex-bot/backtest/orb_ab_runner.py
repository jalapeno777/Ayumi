#!/usr/bin/env python3
"""ORB A/B Test Runner — baseline vs ORB strategy comparison.

Runs both strategies over the same historical data and produces a
statistical comparison report covering:
    - Win rate
    - Profit factor
    - Sharpe ratio
    - Maximum drawdown
    - Total P&L
    - Average R:R
    - Trade count

Usage::

    python -m backtest.orb_ab_runner \\
        --data data/forex/historical/EURUSD_M15.csv \\
        --pair EURUSD \\
        --output docs/research/orb-ab-test-results.json

    # Or programmatically:
    from backtest.orb_ab_runner import run_ab_test, print_comparison
    result = run_ab_test(bars, pair="EURUSD")
    print_comparison(result)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# Add project root to path for standalone execution
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backtest.data_loader import CsvDataLoader  # noqa: E402, I001
from backtest.simple_engine import BacktestConfig, BacktestEngine  # noqa: E402
from backtest.types import Bar  # noqa: E402
from strategies.session_breakout_retest import SessionBreakoutStrategy  # noqa: E402
from strategies.orb import ORBStrategy  # noqa: E402


# ── Result containers ──────────────────────────────────────────────────────


@dataclass
class StrategyMetrics:
    """Metrics for a single strategy run."""

    name: str
    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    max_drawdown_dollar: float
    total_pnl: float
    total_pnl_pct: float
    avg_risk_reward: float
    expectancy: float
    winning_trades: int
    losing_trades: int


@dataclass
class ABTestResult:
    """Full A/B test result comparing baseline vs ORB."""

    pair: str
    timeframe: str
    baseline: StrategyMetrics
    variant: StrategyMetrics
    bars_processed: int
    date_range: str
    generated_at: str
    differences: dict[str, float] = field(default_factory=dict)
    winner: str = ""
    recommendation: str = ""


# ── Metric extraction ──────────────────────────────────────────────────────


def _extract_metrics(name: str, bt_metrics) -> StrategyMetrics:
    """Convert BacktestMetrics → StrategyMetrics."""
    return StrategyMetrics(
        name=name,
        total_trades=bt_metrics.total_trades,
        win_rate=bt_metrics.win_rate / 100.0 if bt_metrics.win_rate > 1 else bt_metrics.win_rate,
        profit_factor=bt_metrics.profit_factor,
        sharpe_ratio=bt_metrics.sharpe_ratio,
        max_drawdown_pct=bt_metrics.max_drawdown_pct,
        max_drawdown_dollar=bt_metrics.max_drawdown_dollar,
        total_pnl=bt_metrics.total_pnl,
        total_pnl_pct=bt_metrics.total_pnl_pct,
        avg_risk_reward=bt_metrics.avg_risk_reward,
        expectancy=bt_metrics.expectancy,
        winning_trades=bt_metrics.winning_trades,
        losing_trades=bt_metrics.losing_trades,
    )


# ── Runner ─────────────────────────────────────────────────────────────────


def _default_baseline_config(pair: str) -> dict:
    """Default SessionBreakout (London) baseline config."""
    return {
        "name": "Baseline (Session Breakout London)",
        "range_start_hour": 7,
        "range_end_hour": 8,
        "trade_start_hour": 8,
        "trade_end_hour": 16,
        "min_range_pips": 20,
        "max_range_pips": 80,
        "buffer_pips": 3,
        "sl_atr_multiplier": 2.0,
        "atr_period": 14,
        "min_range_bars": 20,
    }


def _default_orb_config(pair: str) -> dict:
    """Default ORB strategy config for the given pair."""
    return {
        "name": f"ORB London ({pair})",
        "session": "london",
        "range_start_hour": 7,
        "range_end_hour": 8,
        "trade_start_hour": 8,
        "trade_end_hour": 16,
        "breakout_buffer_pips": 2.0,
        "min_range_pips": 5.0,
        "max_range_pips": 40.0,
        "atr_period": 14,
        "sl_atr_multiplier": 1.5,
        "direction_filter": "both",
        "min_range_bars": 4,
        "h4_trend_filter": False,
        "rr_tp1": 1.0,
        "rr_tp2": 2.0,
        "rr_tp3": 3.0,
    }


def run_ab_test(
    bars: list[Bar],
    pair: str = "EURUSD",
    baseline_config: dict | None = None,
    orb_config: dict | None = None,
    backtest_config: BacktestConfig | None = None,
) -> ABTestResult:
    """Run baseline vs ORB over the same bars and return comparison.

    Args:
        bars: List of Bar objects (M15 or H1).
        pair: Trading pair symbol.
        baseline_config: Override SessionBreakout config.
        orb_config: Override ORB config.
        backtest_config: Override BacktestConfig.

    Returns:
        ABTestResult with metrics for both strategies.
    """
    if backtest_config is None:
        backtest_config = BacktestConfig(
            starting_balance=10_000.0,
            risk_per_trade_pct=0.005,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            spread_pips=1.5,
            commission_per_lot=3.5,
            min_confidence=0.50,
            min_risk_reward=1.0,
            max_open_trades=1,
            min_bars_before_signal=30,
            pair=pair,
        )

    baseline_cfg = baseline_config or _default_baseline_config(pair)
    orb_cfg = orb_config or _default_orb_config(pair)

    # ── Run baseline ──
    baseline_strategy = SessionBreakoutStrategy(baseline_cfg)
    baseline_engine = BacktestEngine(backtest_config)
    baseline_engine.strategy = baseline_strategy
    baseline_metrics = baseline_engine.run(bars)
    baseline_result = _extract_metrics("Baseline (Session Breakout)", baseline_metrics)

    # ── Run ORB ──
    orb_strategy = ORBStrategy(orb_cfg)
    orb_engine = BacktestEngine(backtest_config)
    orb_engine.strategy = orb_strategy
    orb_metrics = orb_engine.run(bars)
    orb_result = _extract_metrics("ORB Strategy", orb_metrics)

    # ── Compute differences ──
    diffs = {
        "win_rate_delta": orb_result.win_rate - baseline_result.win_rate,
        "profit_factor_delta": orb_result.profit_factor - baseline_result.profit_factor,
        "sharpe_delta": orb_result.sharpe_ratio - baseline_result.sharpe_ratio,
        "max_drawdown_delta_pct": orb_result.max_drawdown_pct - baseline_result.max_drawdown_pct,
        "pnl_delta": orb_result.total_pnl - baseline_result.total_pnl,
        "trade_count_delta": orb_result.total_trades - baseline_result.total_trades,
    }

    # ── Determine winner ──
    score_baseline = (
        baseline_result.win_rate * 0.30
        + min(baseline_result.profit_factor, 3.0) / 3.0 * 0.25
        + max(baseline_result.sharpe_ratio, 0) / 2.0 * 0.25
        + (1.0 - min(baseline_result.max_drawdown_pct / 20.0, 1.0)) * 0.20
    )
    score_orb = (
        orb_result.win_rate * 0.30
        + min(orb_result.profit_factor, 3.0) / 3.0 * 0.25
        + max(orb_result.sharpe_ratio, 0) / 2.0 * 0.25
        + (1.0 - min(orb_result.max_drawdown_pct / 20.0, 1.0)) * 0.20
    )

    if score_orb > score_baseline + 0.05:
        winner = "ORB"
        recommendation = (
            "ORB outperforms baseline on composite score "
            f"({score_orb:.3f} vs {score_baseline:.3f}). "
            "Advance to paper-trading validation."
        )
    elif score_baseline > score_orb + 0.05:
        winner = "Baseline"
        recommendation = (
            "Baseline outperforms ORB on composite score "
            f"({score_baseline:.3f} vs {score_orb:.3f}). "
            "Do not deploy ORB without parameter refinement."
        )
    else:
        winner = "Tie"
        recommendation = (
            f"No significant difference (baseline={score_baseline:.3f}, ORB={score_orb:.3f}). "
            "Refine ORB parameters or test on additional pairs before deciding."
        )

    # ── Date range ──
    if bars:
        first_date = bars[0].time.strftime("%Y-%m-%d")
        last_date = bars[-1].time.strftime("%Y-%m-%d")
        date_range = f"{first_date} to {last_date}"
    else:
        date_range = "N/A"

    return ABTestResult(
        pair=pair,
        timeframe="M15",
        baseline=baseline_result,
        variant=orb_result,
        bars_processed=len(bars),
        date_range=date_range,
        generated_at=datetime.utcnow().isoformat() + "Z",
        differences=diffs,
        winner=winner,
        recommendation=recommendation,
    )


# ── Output formatting ──────────────────────────────────────────────────────


def print_comparison(result: ABTestResult) -> None:
    """Pretty-print A/B comparison to stdout."""
    print("\n" + "=" * 70)
    print(f"  ORB A/B TEST — {result.pair} ({result.date_range})")
    print(f"  Bars: {result.bars_processed} | Generated: {result.generated_at}")
    print("=" * 70)

    print(f"\n{'Metric':<25} {'Baseline':>15} {'ORB':>15} {'Delta':>15}")
    print("-" * 70)

    def _row(label: str, baseline_val, orb_val, delta_val, fmt="{:.4f}"):
        print(f"  {label:<23} {fmt.format(baseline_val):>15} {fmt.format(orb_val):>15} {fmt.format(delta_val):>+15}")

    b = result.baseline
    o = result.variant
    d = result.differences

    _row("Win Rate", b.win_rate, o.win_rate, d["win_rate_delta"], "{:.2%}")
    _row(
        "Profit Factor",
        b.profit_factor,
        o.profit_factor,
        d["profit_factor_delta"],
        "{:.2f}",
    )
    _row("Sharpe Ratio", b.sharpe_ratio, o.sharpe_ratio, d["sharpe_delta"], "{:.2f}")
    _row(
        "Max DD %",
        b.max_drawdown_pct,
        o.max_drawdown_pct,
        d["max_drawdown_delta_pct"],
        "{:.2f}",
    )
    _row("Total P&L $", b.total_pnl, o.total_pnl, d["pnl_delta"], "{:.2f}")
    _row(
        "Avg R:R",
        b.avg_risk_reward,
        o.avg_risk_reward,
        b.avg_risk_reward - o.avg_risk_reward,
        "{:.2f}",
    )
    _row(
        "Expectancy $",
        b.expectancy,
        o.expectancy,
        o.expectancy - b.expectancy,
        "{:.2f}",
    )

    print(f"\n  {'Trade Count':<23} {b.total_trades:>15} {o.total_trades:>15} {d['trade_count_delta']:>+15}")
    print(f"  {'Winning Trades':<23} {b.winning_trades:>15} {o.winning_trades:>15}")
    print(f"  {'Losing Trades':<23} {b.losing_trades:>15} {o.losing_trades:>15}")

    print("\n" + "-" * 70)
    print(f"  WINNER: {result.winner}")
    print(f"  RECOMMENDATION: {result.recommendation}")
    print("=" * 70 + "\n")


def result_to_json(result: ABTestResult) -> str:
    """Serialize result to JSON string."""
    return json.dumps(asdict(result), indent=2)


# ── CLI entry point ────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="ORB A/B Test Runner")
    parser.add_argument(
        "--data",
        default="data/forex/historical/EURUSD_M15.csv",
        help="Path to CSV data file",
    )
    parser.add_argument("--pair", default="EURUSD", help="Trading pair")
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (default: stdout only)",
    )
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ERROR: Data file not found: {data_path}", file=sys.stderr)
        sys.exit(1)

    loader = CsvDataLoader(str(data_path))
    bars = loader.load_bars()

    if not bars:
        print("ERROR: No bars loaded from data file", file=sys.stderr)
        sys.exit(1)

    result = run_ab_test(bars, pair=args.pair)
    print_comparison(result)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result_to_json(result))
        print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    main()
