#!/usr/bin/env python3
"""Crisis replay backtest runner — stress-test strategies through historical crisis events.

Loads M1 OHLCV data for well-known forex crisis windows, runs strategies through
each using the existing BacktestEngine, and computes survival metrics (max drawdown,
recovery bars, crisis-adjusted Sharpe) with pass/fail gates per SRB-AYUMI-010 §5.

Usage:
    python -m backtest.crisis_replay --strategies MyStrategy --crises 2015_chf_unpeg
    python -m backtest.crisis_replay --strategies all --output data/stress_test_results
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import pandas as pd

# Support both package import and direct script execution
try:
    from backtest.simple_engine import (
        BacktestConfig,
        BacktestMetrics,
        Bar,
        SimulatedTrade,
    )
    from engine.engine import BacktestEngine
except ImportError:
    # When run as script from src/forex-bot/backtest/crisis_replay.py
    # Load simple_engine.py directly to avoid heavy backtest/__init__.py
    from pathlib import Path as _Path
    import importlib.util as _ilu

    _FXBOT = _Path(__file__).resolve().parent.parent  # src/forex-bot/
    sys.path.append(str(_FXBOT))  # for core.types, engine, etc.

    _spec = _ilu.spec_from_file_location(
        "_simple_engine_standalone", str(_FXBOT / "backtest" / "simple_engine.py")
    )
    _se_mod = _ilu.module_from_spec(_spec)
    sys.modules["_simple_engine_standalone"] = _se_mod
    _spec.loader.exec_module(_se_mod)

    BacktestConfig = _se_mod.BacktestConfig
    BacktestMetrics = _se_mod.BacktestMetrics
    Bar = _se_mod.Bar
    from engine.engine import BacktestEngine

    SimulatedTrade = _se_mod.SimulatedTrade

logger = logging.getLogger("crisis_replay")


# ── Crisis Windows ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CrisisWindow:
    """A historical crisis event with date range and affected pairs."""

    event: str
    start: datetime
    end: datetime
    pairs: tuple[str, ...]
    description: str = ""


CRISIS_WINDOWS: list[CrisisWindow] = [
    CrisisWindow(
        event="2015_chf_unpeg",
        start=datetime(2015, 1, 9, tzinfo=timezone.utc),
        end=datetime(2015, 1, 16, tzinfo=timezone.utc),
        pairs=("EURUSD", "USDCHF", "GBPUSD"),
        description="Swiss National Bank removed EUR/CHF floor — massive CHF appreciation",
    ),
    CrisisWindow(
        event="2016_brexit",
        start=datetime(2016, 6, 23, tzinfo=timezone.utc),
        end=datetime(2016, 6, 30, tzinfo=timezone.utc),
        pairs=("GBPUSD", "EURUSD", "GBPJPY"),
        description="UK Brexit referendum — GBP flash crash + sustained volatility",
    ),
    CrisisWindow(
        event="2016_us_election",
        start=datetime(2016, 11, 8, tzinfo=timezone.utc),
        end=datetime(2016, 11, 11, tzinfo=timezone.utc),
        pairs=("USDJPY", "EURUSD", "GBPUSD"),
        description="US presidential election — Trump victory shock + reversal",
    ),
    CrisisWindow(
        event="2020_covid_crash",
        start=datetime(2020, 3, 9, tzinfo=timezone.utc),
        end=datetime(2020, 3, 20, tzinfo=timezone.utc),
        pairs=("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"),
        description="COVID-19 pandemic panic — global risk-off liquidation",
    ),
    CrisisWindow(
        event="2022_gbp_flash",
        start=datetime(2022, 9, 23, tzinfo=timezone.utc),
        end=datetime(2022, 9, 28, tzinfo=timezone.utc),
        pairs=("GBPUSD", "EURUSD", "GBPJPY"),
        description="UK mini-budget gilt crisis — GBP flash crash to 1.035",
    ),
    CrisisWindow(
        event="2022_fed_pivot",
        start=datetime(2022, 9, 13, tzinfo=timezone.utc),
        end=datetime(2022, 10, 13, tzinfo=timezone.utc),
        pairs=("USDJPY", "EURUSD", "GBPUSD"),
        description="Fed aggressive rate hike cycle — USD surge + bond market volatility",
    ),
]

_CRISIS_BY_EVENT: dict[str, CrisisWindow] = {cw.event: cw for cw in CRISIS_WINDOWS}


# ── Survival gates (SRB-AYUMI-010 §5) ───────────────────────────────────────────

MAX_DRAWDOWN_PCT = 7.0  # Strategy must not draw down more than 7%
MAX_RECOVERY_BARS = 20  # Must recover to prior peak within 20 M1 bars
MIN_SHARPE_RATIO = 0.3  # Crisis Sharpe must be ≥ 0.3 × baseline
DEFAULT_BASELINE_SHARPE = 1.0  # Fallback when no walk-forward data exists
_M1_BARS_PER_YEAR = 252 * 24 * 60  # Annualization factor for M1 Sharpe


# ── Strategy Protocol ───────────────────────────────────────────────────────────


class CrisisStrategy(Protocol):
    """Protocol for strategies that can be replayed through crisis windows."""

    def generate_signals(self, bars: list[Bar]) -> list[dict]:
        """Generate trading signals from bars.

        Returns list of signal dicts with keys:
            bar_index, direction (long/short), entry_price,
            stop_loss, take_profit_1/2/3, confidence, lot_size
        """
        ...


# ── Data Loading ─────────────────────────────────────────────────────────────────


def _months_range(start: datetime, end: datetime) -> list[tuple[int, int]]:
    """Yield (year, month) tuples in [start, end) range."""
    months: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def load_crisis_data(
    event_name: str,
    base_dir: Path | str = Path("data/forex/dukascopy"),
) -> dict[str, pd.DataFrame]:
    """Load M1 OHLCV data for a crisis event.

    Reads per-month CSVs named ``{PAIR}_M1_{YYYY}-{MM}.csv`` from *base_dir*,
    filters to ``[start, end]``, and returns a dict mapping pair → DataFrame.

    DataFrame columns: timestamp(open), open, high, low, close, volume.
    """
    if event_name not in _CRISIS_BY_EVENT:
        raise ValueError(
            f"Unknown crisis event '{event_name}'. "
            f"Available: {sorted(_CRISIS_BY_EVENT)}"
        )

    cw = _CRISIS_BY_EVENT[event_name]
    base = Path(base_dir)
    result: dict[str, pd.DataFrame] = {}

    months = _months_range(cw.start, cw.end)

    for pair in cw.pairs:
        frames: list[pd.DataFrame] = []
        for year, month in months:
            csv_path = base / f"{pair}_M1_{year}-{month:02d}.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path)
                frames.append(df)

        if not frames:
            logger.warning("No data files found for %s in %s", pair, base)
            continue

        combined = pd.concat(frames, ignore_index=True)

        # Normalize column names
        col_map = {c.lower(): c.lower() for c in combined.columns}
        combined.columns = [col_map.get(c.lower(), c.lower()) for c in combined.columns]

        # Parse timestamp column
        ts_col = None
        for candidate in ("timestamp", "time", "datetime", "date"):
            if candidate in combined.columns:
                ts_col = candidate
                break

        if ts_col is None:
            logger.warning(
                "No timestamp column found for %s (cols: %s)",
                pair,
                list(combined.columns),
            )
            continue

        combined[ts_col] = pd.to_datetime(combined[ts_col], utc=True, errors="coerce")
        combined = combined.dropna(subset=[ts_col])

        # Filter to crisis window
        mask = (combined[ts_col] >= cw.start) & (combined[ts_col] < cw.end)
        filtered = combined.loc[mask].sort_values(ts_col).reset_index(drop=True)

        if not filtered.empty:
            result[pair] = filtered

    return result


# ── Survival Metrics ──────────────────────────────────────────────────────────────


def survival_metrics(
    trades: list[SimulatedTrade],
    equity_curve: list[float],
    baseline_sharpe: float = DEFAULT_BASELINE_SHARPE,
) -> dict:
    """Compute survival metrics from trades and equity curve.

    Returns dict with:
        max_drawdown_pct: peak-to-trough drawdown (negative or zero)
        recovery_bars: bars from trough back to prior peak (0 if no drawdown)
        sharpe: annualized Sharpe ratio on M1 bar returns
        survival: bool — True if all 3 gates pass
        gates: per-gate pass/fail dict
    """
    # ── Max drawdown ──
    peak = equity_curve[0] if equity_curve else 0.0
    max_dd = 0.0
    trough_idx = 0
    peak_idx_at_trough = 0
    current_peak_idx = 0

    for i, val in enumerate(equity_curve):
        if val > peak:
            peak = val
            current_peak_idx = i
        dd = (val - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
            trough_idx = i
            peak_idx_at_trough = current_peak_idx

    max_drawdown_pct = max_dd * 100.0  # Negative percentage

    # ── Recovery bars ──
    if max_dd >= 0.0:
        recovery_bars = 0
    else:
        # Count bars from trough back to peak level that was in effect at trough
        recovery_target = (
            equity_curve[peak_idx_at_trough]
            if peak_idx_at_trough < len(equity_curve)
            else equity_curve[0]
        )
        recovery_bars = 0
        for i in range(trough_idx, len(equity_curve)):
            if equity_curve[i] >= recovery_target:
                break
            recovery_bars += 1
        if recovery_bars == len(equity_curve) - trough_idx:
            # Never recovered
            recovery_bars = len(equity_curve) - trough_idx

    # ── Sharpe on trade PnL ──
    pnl_values = [t.profit_loss for t in trades if hasattr(t, "profit_loss")]
    if len(pnl_values) < 2:
        sharpe = 0.0
    else:
        mean_pnl = sum(pnl_values) / len(pnl_values)
        variance = sum((p - mean_pnl) ** 2 for p in pnl_values) / len(pnl_values)
        std_pnl = math.sqrt(variance)
        if std_pnl == 0:
            sharpe = 0.0
        else:
            sharpe = (mean_pnl / std_pnl) * math.sqrt(_M1_BARS_PER_YEAR)

    # ── Gates ──
    sharpe_threshold = MIN_SHARPE_RATIO * baseline_sharpe

    gates = {
        "max_drawdown": abs(max_drawdown_pct) <= MAX_DRAWDOWN_PCT,
        "recovery_bars": recovery_bars <= MAX_RECOVERY_BARS,
        "sharpe_ratio": sharpe >= sharpe_threshold,
    }

    return {
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "recovery_bars": recovery_bars,
        "sharpe": round(sharpe, 4),
        "baseline_sharpe": baseline_sharpe,
        "sharpe_threshold": round(sharpe_threshold, 4),
        "survival": all(gates.values()),
        "gates": gates,
    }


# ── Crisis Replay ────────────────────────────────────────────────────────────────


def _df_to_bars(df: pd.DataFrame) -> list[Bar]:
    """Convert a DataFrame to a list of Bar objects."""
    ts_col = None
    for candidate in ("timestamp", "time", "datetime", "date"):
        if candidate in df.columns:
            ts_col = candidate
            break

    bars: list[Bar] = []
    for _, row in df.iterrows():
        ts = row[ts_col] if ts_col else datetime.now(timezone.utc)
        if isinstance(ts, str):
            ts = pd.to_datetime(ts, utc=True).to_pydatetime()
        elif hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()

        bar = Bar(
            time=ts,
            open=float(row.get("open", 0)),
            high=float(row.get("high", 0)),
            low=float(row.get("low", 0)),
            close=float(row.get("close", 0)),
            volume=float(row.get("volume", 0)),
        )
        bars.append(bar)
    return bars


def run_crisis_replay(
    strategy_cls: type | None = None,
    event_name: str = "2020_covid_crash",
    base_dir: Path | str = Path("data/forex/dukascopy"),
    initial_equity: float = 10000.0,
    baseline_sharpe: float = DEFAULT_BASELINE_SHARPE,
) -> dict:
    """Run a strategy through a single crisis window.

    Args:
        strategy_cls: Strategy class to instantiate (or None for equity-curve only).
        event_name: Crisis event name from CRISIS_WINDOWS.
        base_dir: Directory containing Dukascopy M1 CSV files.
        initial_equity: Starting balance for the backtest.
        baseline_sharpe: Baseline Sharpe for survival gate comparison.

    Returns:
        Dict with event, strategy, metrics, trades, equity_curve.
    """
    cw = _CRISIS_BY_EVENT.get(event_name)
    if cw is None:
        raise ValueError(f"Unknown crisis event: {event_name}")

    data = load_crisis_data(event_name, base_dir=base_dir)

    if not data:
        logger.warning("No data loaded for %s — returning empty result", event_name)
        return {
            "event": event_name,
            "strategy": strategy_cls.__name__ if strategy_cls else "none",
            "metrics": None,
            "trades": [],
            "equity_curve": [],
            "error": "no_data",
        }

    # Use the first available pair
    pair = cw.pairs[0]
    df = data.get(pair)
    if df is None or df.empty:
        first_pair = next(iter(data))
        df = data[first_pair]
        pair = first_pair

    bars = _df_to_bars(df)

    if len(bars) < 30:
        logger.warning(
            "Insufficient bars (%d) for %s — skipping", len(bars), event_name
        )
        return {
            "event": event_name,
            "strategy": strategy_cls.__name__ if strategy_cls else "none",
            "metrics": None,
            "trades": [],
            "equity_curve": [initial_equity],
            "error": "insufficient_bars",
        }

    # Configure and run engine
    config = BacktestConfig(
        starting_balance=initial_equity,
        pair=pair,
        min_bars_before_signal=30,
    )
    engine = BacktestEngine(config)
    result: BacktestMetrics = engine.run(bars)

    # Compute survival metrics
    sm = survival_metrics(result.trades, result.equity_curve, baseline_sharpe)

    return {
        "event": event_name,
        "strategy": strategy_cls.__name__ if strategy_cls else "none",
        "pair": pair,
        "metrics": sm,
        "trades": len(result.trades),
        "equity_curve": result.equity_curve,
        "backtest_metrics": {
            "total_pnl": round(result.total_pnl, 2),
            "win_rate": round(result.win_rate, 2),
            "max_drawdown_pct": round(result.max_drawdown_pct, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
        },
    }


def run_all_crises(
    strategy_classes: list[type] | None = None,
    output_dir: Path | str = Path("data/stress_test_results"),
    base_dir: Path | str = Path("data/forex/dukascopy"),
    initial_equity: float = 10000.0,
) -> dict:
    """Run strategies through all crisis windows and write reports.

    Args:
        strategy_classes: List of strategy classes to test.
        output_dir: Directory for output files.
        base_dir: Data directory for CSV files.
        initial_equity: Starting balance.

    Returns:
        Summary dict mapping strategy → event → result.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    strategies = strategy_classes or [None]
    summary: dict[str, dict[str, dict]] = {}

    # Try to load baseline Sharpe from walk-forward results
    baseline = _load_baseline_sharpe()

    for strat_cls in strategies:
        strat_name = strat_cls.__name__ if strat_cls else "baseline"
        strat_results: dict[str, dict] = {}

        for cw in CRISIS_WINDOWS:
            result = run_crisis_replay(
                strategy_cls=strat_cls,
                event_name=cw.event,
                base_dir=base_dir,
                initial_equity=initial_equity,
                baseline_sharpe=baseline,
            )
            strat_results[cw.event] = result

        summary[strat_name] = strat_results

        # Write per-strategy JSON
        strat_dir = out / strat_name
        strat_dir.mkdir(parents=True, exist_ok=True)
        report_path = strat_dir / "survival_report.json"
        with open(report_path, "w") as f:
            json.dump(strat_results, f, indent=2, default=str)

    # Write combined summary markdown
    _write_summary_md(summary, out / "_summary.md")

    return summary


def _load_baseline_sharpe(wf_dir: Path = Path("data/walk_forward_results")) -> float:
    """Load baseline Sharpe from walk-forward results, or fall back to default."""
    if wf_dir.exists():
        for json_file in wf_dir.glob("*.json"):
            try:
                with open(json_file) as f:
                    data = json.load(f)
                sharpe = data.get("sharpe_ratio") or data.get("sharpe")
                if sharpe and isinstance(sharpe, (int, float)) and sharpe > 0:
                    return float(sharpe)
            except (json.JSONDecodeError, OSError):
                continue
    logger.warning(
        "No walk-forward baseline found in %s — using default %.1f",
        wf_dir,
        DEFAULT_BASELINE_SHARPE,
    )
    return DEFAULT_BASELINE_SHARPE


def _write_summary_md(summary: dict, path: Path) -> None:
    """Write a markdown summary table of survival results."""
    lines = ["# Crisis Replay Survival Summary\n"]
    lines.append("| Strategy | Event | Max DD % | Recovery Bars | Sharpe | Survival |")
    lines.append("|----------|-------|----------|---------------|--------|----------|")

    for strat_name, events in summary.items():
        for event, result in events.items():
            metrics = result.get("metrics")
            if metrics:
                dd = metrics["max_drawdown_pct"]
                rec = metrics["recovery_bars"]
                sharpe = metrics["sharpe"]
                survived = "✅" if metrics["survival"] else "❌"
            else:
                dd = "N/A"
                rec = "N/A"
                sharpe = "N/A"
                survived = "⚠️"
            lines.append(
                f"| {strat_name} | {event} | {dd} | {rec} | {sharpe} | {survived} |"
            )

    lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    logger.info("Summary written to %s", path)


# ── CLI ──────────────────────────────────────────────────────────────────────────


def main():
    """CLI entry point for crisis replay."""
    parser = argparse.ArgumentParser(
        description="Crisis replay backtest runner — stress-test strategies through historical crises"
    )
    parser.add_argument(
        "--strategies",
        nargs="*",
        default=None,
        help="Strategy class names to test (or 'all' for discovery). Default: baseline only.",
    )
    parser.add_argument(
        "--crises",
        nargs="*",
        default=None,
        help=f"Crisis events to test. Available: {sorted(_CRISIS_BY_EVENT)}",
    )
    parser.add_argument(
        "--output-dir",
        default="data/stress_test_results",
        help="Output directory for reports (default: data/stress_test_results)",
    )
    parser.add_argument(
        "--data-dir",
        default="data/forex/dukascopy",
        help="Data directory with M1 CSV files (default: data/forex/dukascopy)",
    )
    parser.add_argument(
        "--equity",
        type=float,
        default=10000.0,
        help="Initial equity (default: 10000)",
    )

    args = parser.parse_args()

    # Determine which crises to run
    if args.crises:
        for c in args.crises:
            if c not in _CRISIS_BY_EVENT:
                print(
                    f"Error: Unknown crisis '{c}'. Available: {sorted(_CRISIS_BY_EVENT)}"
                )
                return 1

    # Run
    if args.strategies:
        print("Strategy discovery not implemented yet — running baseline only.")
        strategy_classes: list[type | None] = [None]
    else:
        strategy_classes = [None]

    try:
        summary = _run_selected_crises(
            strategy_classes=strategy_classes,
            output_dir=Path(args.output_dir),
            base_dir=Path(args.data_dir),
            initial_equity=args.equity,
            crisis_filter=args.crises,
        )

        # Print results
        for strat_name, events in summary.items():
            print(f"\n{'=' * 60}")
            print(f"Strategy: {strat_name}")
            print(f"{'=' * 60}")
            for event, result in events.items():
                metrics = result.get("metrics")
                if metrics:
                    status = "SURVIVED" if metrics["survival"] else "FAILED"
                    print(
                        f"  {event}: DD={metrics['max_drawdown_pct']:.2f}% "
                        f"Rec={metrics['recovery_bars']} "
                        f"Sharpe={metrics['sharpe']:.3f} "
                        f"[{status}]"
                    )
                else:
                    print(
                        f"  {event}: No data or error ({result.get('error', 'unknown')})"
                    )

        print(f"\nReports written to {args.output_dir}/")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _run_selected_crises(
    strategy_classes: list[type | None] | None = None,
    output_dir: Path | str = Path("data/stress_test_results"),
    base_dir: Path | str = Path("data/forex/dukascopy"),
    initial_equity: float = 10000.0,
    crisis_filter: list[str] | None = None,
) -> dict:
    """Run crises, optionally filtered to a subset."""
    global CRISIS_WINDOWS
    if crisis_filter:
        original = CRISIS_WINDOWS
        CRISIS_WINDOWS = [_CRISIS_BY_EVENT[c] for c in crisis_filter]
        try:
            return run_all_crises(
                strategy_classes, output_dir, base_dir, initial_equity
            )
        finally:
            CRISIS_WINDOWS = original
    return run_all_crises(strategy_classes, output_dir, base_dir, initial_equity)


if __name__ == "__main__":
    sys.exit(main())
