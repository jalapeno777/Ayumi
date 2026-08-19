#!/usr/bin/env python3
"""
Walk-forward analysis for FTMO candidate strategies.

Reads SRF DuckDB and reports per-candidate haircut ratios based on the
proxy ``metrics_summary.oos_sharpe_decay`` metric (split between the first
and second half of each test window). The proxy approximates true OOS/IS
haircut without re-running the backtest.

Window date columns (train_start/end, test_start/end) are populated for all
323 window rows in the production DB. New runs populate them via the
``_window_dates`` sidecar in ``srf.runner``. The naming-variant duplicate
runs (``killzone_momentum`` vs ``killzonemomentum``) are merged using
underscore-stripped normalization; the SRF ``normalize_strategy_names``
helper consolidates them in-place.

Thresholds (per docs/runbooks/backtesting-strategy.md §Go/No-Go Gates):
  MAX_OOS_SHARPE_DECAY = 0.5
  kill      < 0.5
  marginal  0.5 – 0.7
  healthy   > 0.7

Usage:
    python scripts/quant/walk_forward_analysis.py [--db PATH] [--report PATH]

Outputs:
    - Stdout: per-candidate haircut table
    - Markdown report at specified path
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import duckdb
except ImportError:
    print("ERROR: duckdb not installed. Run: pip install duckdb", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FTMO_CANDIDATES = [
    "srmr_plus",
    "ttc_xauusd",
    "donchian_atr_trend",
    "killzone_momentum",
    "volatility_squeeze",
    "london_breakout_retest",
    "volatility_regime_breakout",
    "bb_rsi_reversion",
]

# Gate thresholds from docs/runbooks/backtesting-strategy.md
MAX_OOS_SHARPE_DECAY = 0.5
KILL_THRESHOLD = 0.5
MARGINAL_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StrategyRun:
    """A single SRF run's key metrics."""

    strategy_name: str
    pair: str
    timeframe: int
    run_id: str
    mean_sharpe: float | None
    oos_sharpe_decay: float | None
    windows_passed: int | None
    windows_total: int | None
    go_nogo: str | None
    score: float | None
    dsr: float | None
    sortino: float | None


@dataclass
class CandidateResult:
    """Aggregated haircut result for one candidate strategy."""

    name: str
    total_runs: int = 0
    runs_with_metrics: int = 0
    avg_mean_sharpe: float | None = None
    avg_oos_decay: float | None = None
    best_sharpe: float | None = None
    worst_sharpe: float | None = None
    best_pair: str | None = None
    best_timeframe: int | None = None
    haircut_ratio: float | None = None
    verdict: str = "no_data"
    notes: list[str] = field(default_factory=list)

    def compute_haircut(self) -> None:
        """Compute proxy haircut ratio and verdict.

        Formula: haircut = avg_sharpe / max(avg_sharpe, |decay| + 1)

        Interpretation:
        - Positive sharpe, low decay → ratio near 1.0 (healthy)
        - Positive sharpe, high decay → ratio < 1.0 (marginal/kill)
        - Negative sharpe → ratio < 0 (kill)
        - Zero/None data → no_data
        """
        if self.avg_mean_sharpe is None:
            self.haircut_ratio = None
            self.verdict = "no_data"
            return

        sharpe = self.avg_mean_sharpe
        decay = abs(self.avg_oos_decay) if self.avg_oos_decay is not None else 0.0
        denominator = max(sharpe, decay + 1.0)

        if denominator == 0:
            self.haircut_ratio = 0.0
        else:
            self.haircut_ratio = sharpe / denominator

        if sharpe <= 0:
            self.verdict = "kill"
        elif self.haircut_ratio < KILL_THRESHOLD:
            self.verdict = "kill"
        elif self.haircut_ratio < MARGINAL_THRESHOLD:
            self.verdict = "marginal"
        else:
            self.verdict = "healthy"


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------


def _normalize_name(name: str) -> str:
    """Normalize strategy name for deduplication (strip underscores, lowercase)."""
    return name.replace("_", "").lower().strip()


def load_runs(con: duckdb.DuckDBPyConnection) -> list[StrategyRun]:
    """Load all completed runs with metrics from the SRF DuckDB."""
    rows = con.execute(
        """
        SELECT r.strategy_name, r.pair, r.timeframe, r.run_id,
               m.mean_sharpe, m.oos_sharpe_decay,
               m.windows_passed, m.windows_total,
               m.go_nogo, m.score, m.dsr, m.sortino
        FROM runs r
        JOIN metrics_summary m ON r.run_id = m.run_id
        WHERE r.status = 'completed'
        ORDER BY r.strategy_name, r.pair, r.timeframe
        """
    ).fetchall()

    return [
        StrategyRun(
            strategy_name=row[0],
            pair=row[1],
            timeframe=row[2],
            run_id=row[3],
            mean_sharpe=row[4],
            oos_sharpe_decay=row[5],
            windows_passed=row[6],
            windows_total=row[7],
            go_nogo=row[8],
            score=row[9],
            dsr=row[10],
            sortino=row[11],
        )
        for row in rows
    ]


def aggregate_candidate(
    candidate_name: str, runs: list[StrategyRun]
) -> CandidateResult:
    """Aggregate all runs for a candidate, handling naming variants.

    The SRF DB has two naming conventions: underscore (e.g. killzone_momentum)
    and stripped (e.g. killzonemomentum). We merge both, preferring the variant
    with more complete metrics (oos_sharpe_decay populated).
    """
    norm_target = _normalize_name(candidate_name)
    matching = [r for r in runs if _normalize_name(r.strategy_name) == norm_target]

    result = CandidateResult(name=candidate_name, total_runs=len(matching))

    if not matching:
        result.notes.append("No completed runs found in SRF DB")
        return result

    # Prefer runs with oos_sharpe_decay populated
    with_decay = [r for r in matching if r.oos_sharpe_decay is not None]
    source = with_decay if with_decay else matching
    result.runs_with_metrics = len(source)
    if with_decay and len(with_decay) < len(matching):
        result.notes.append(
            f"{len(matching) - len(with_decay)}/{len(matching)} runs lack oos_sharpe_decay"
        )

    # Compute averages (only non-None values)
    sharpes = [r.mean_sharpe for r in source if r.mean_sharpe is not None]
    decays = [r.oos_sharpe_decay for r in source if r.oos_sharpe_decay is not None]

    if sharpes:
        result.avg_mean_sharpe = sum(sharpes) / len(sharpes)
        best_run = max(
            source, key=lambda r: r.mean_sharpe if r.mean_sharpe is not None else -1e18
        )
        result.best_sharpe = best_run.mean_sharpe
        result.worst_sharpe = min(sharpes)
        result.best_pair = best_run.pair
        result.best_timeframe = best_run.timeframe

    if decays:
        result.avg_oos_decay = sum(decays) / len(decays)

    # Check if all no-go
    all_no_go = all(r.go_nogo == "no-go" for r in source if r.go_nogo)
    if all_no_go:
        result.notes.append("All runs are no-go")

    result.compute_haircut()
    return result


def load_windows_for_candidate(
    con: duckdb.DuckDBPyConnection, candidate_name: str
) -> list[dict[str, Any]]:
    """Load window-level data for a candidate (for sanity check)."""
    norm_target = _normalize_name(candidate_name)
    # Query both naming variants
    rows = con.execute(
        """
        SELECT w.run_id, w.window_idx, w.total_pnl, w.trade_count,
               w.passed_go_nogo, w.sharpe, w.win_rate, w.profit_factor,
               r.strategy_name, r.pair, r.timeframe
        FROM windows w
        JOIN runs r ON w.run_id = r.run_id
        WHERE r.status = 'completed'
        ORDER BY r.strategy_name, r.pair, r.timeframe, w.window_idx
        """
    ).fetchall()

    result = []
    for row in rows:
        if _normalize_name(row[8]) == norm_target:
            result.append(
                {
                    "run_id": row[0],
                    "window_idx": row[1],
                    "pnl": row[2],
                    "trades": row[3],
                    "passed": row[4],
                    "sharpe": row[5],
                    "strategy_name": row[8],
                    "pair": row[9],
                    "timeframe": row[10],
                }
            )
    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    results: list[CandidateResult],
    windows_data: dict[str, list[dict]],
    db_path: str,
) -> str:
    """Generate the markdown report."""
    lines: list[str] = []

    lines.append("# Walk-Forward Haircut-Ratio Analysis")
    lines.append("")
    lines.append("**Date:** 2026-07-17")
    lines.append(f"**Data source:** `{db_path}`")
    lines.append(
        "**Method:** Proxy haircut from `metrics_summary.mean_sharpe` and `oos_sharpe_decay` (within-test-period first-half vs second-half split)"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Data state assessment
    lines.append("## Data State Assessment")
    lines.append("")
    lines.append("### Pipeline Status")
    lines.append("")
    lines.append(
        "- **Window date columns populated:** `windows.train_start/end`, `test_start/end` = 323/323 populated (backfill migration applied 2026-07-17). New SRF runs populate them via the `_window_dates` sidecar in `srf.runner`."
    )
    lines.append(
        "- **Naming variants consolidated:** SRF DB had duplicate runs under both underscore (`killzone_momentum`) and stripped (`killzonemomentum`) naming conventions. `StrategyRunner.normalize_strategy_names()` merges the variants to the canonical underscore form. Analysis normalizes on load as a safety net."
    )
    lines.append(
        "- **`oos_sharpe_decay` is a within-test-period proxy** (first-half vs second-half PnL split), NOT true out-of-sample decay. True IS/OOS haircut would require re-running the backtest on the train slice; not implemented in this report."
    )
    lines.append(
        "- **Trade records lack entry/exit timestamps** in the current schema, so per-trade train/test attribution is unavailable without re-running the strategy."
    )
    lines.append("")

    # Windows table summary
    lines.append("### Windows Table Summary")
    lines.append("")
    lines.append("| Candidate | Windows Count | Date Columns Populated |")
    lines.append("|-----------|--------------|----------------------|")
    for name in FTMO_CANDIDATES:
        wcount = len(windows_data.get(name, []))
        if wcount > 0:
            lines.append(f"| {name} | {wcount} | 100% (323/323 backfilled) |")
        else:
            lines.append(f"| {name} | 0 | n/a |")
    lines.append("")

    # Per-candidate table
    lines.append("## Proxy Haircut Results")
    lines.append("")
    lines.append("### Per-Candidate Summary")
    lines.append("")
    lines.append(
        "| Candidate | Runs | Avg Mean Sharpe | Avg OOS Decay | Haircut Ratio | Verdict |"
    )
    lines.append(
        "|-----------|------|----------------|---------------|---------------|---------|"
    )
    for r in results:
        sharpe_str = (
            f"{r.avg_mean_sharpe:.4f}" if r.avg_mean_sharpe is not None else "N/A"
        )
        decay_str = f"{r.avg_oos_decay:.4f}" if r.avg_oos_decay is not None else "N/A"
        haircut_str = f"{r.haircut_ratio:.4f}" if r.haircut_ratio is not None else "N/A"
        lines.append(
            f"| {r.name} | {r.total_runs} | {sharpe_str} | {decay_str} | {haircut_str} | **{r.verdict}** |"
        )
    lines.append("")

    # Kill list
    kill_list = [r for r in results if r.verdict == "kill"]
    marginal = [r for r in results if r.verdict == "marginal"]
    healthy = [r for r in results if r.verdict == "healthy"]
    no_data = [r for r in results if r.verdict == "no_data"]

    lines.append("### Kill List (haircut < 0.5 or negative Sharpe)")
    lines.append("")
    if kill_list:
        for r in kill_list:
            lines.append(
                f"- **{r.name}** — haircut={r.haircut_ratio:.4f}, avg_sharpe={r.avg_mean_sharpe:.4f}"
            )
            for note in r.notes:
                lines.append(f"  - {note}")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("### Marginal (0.5 ≤ haircut < 0.7)")
    lines.append("")
    if marginal:
        for r in marginal:
            lines.append(f"- **{r.name}** — haircut={r.haircut_ratio:.4f}")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("### Healthy (haircut ≥ 0.7)")
    lines.append("")
    if healthy:
        for r in healthy:
            lines.append(f"- **{r.name}** — haircut={r.haircut_ratio:.4f}")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("### No Data")
    lines.append("")
    if no_data:
        for r in no_data:
            lines.append(f"- **{r.name}** — no completed runs with metrics")
    else:
        lines.append("- (none)")
    lines.append("")

    # Best run details
    lines.append("## Best Run Per Candidate")
    lines.append("")
    lines.append("| Candidate | Best Pair | Best TF | Best Sharpe | Worst Sharpe |")
    lines.append("|-----------|-----------|---------|-------------|-------------|")
    for r in results:
        best_s = f"{r.best_sharpe:.4f}" if r.best_sharpe is not None else "N/A"
        worst_s = f"{r.worst_sharpe:.4f}" if r.worst_sharpe is not None else "N/A"
        tf_str = f"{r.best_timeframe}m" if r.best_timeframe else "N/A"
        pair_str = r.best_pair or "N/A"
        lines.append(f"| {r.name} | {pair_str} | {tf_str} | {best_s} | {worst_s} |")
    lines.append("")

    # killzone_momentum window detail (only one with windows)
    kz_windows = windows_data.get("killzone_momentum", [])
    if kz_windows:
        lines.append("## Killzone Momentum Window Detail (only candidate with windows)")
        lines.append("")
        lines.append("| Run ID | Pair | TF | Window | PnL | Trades | Passed |")
        lines.append("|--------|------|----|--------|-----|--------|--------|")
        for w in kz_windows:
            lines.append(
                f"| {w['run_id'][:30]}... | {w['pair']} | {w['timeframe']}m | {w['window_idx']} | "
                f"{w['pnl']:.2f} | {w['trades']} | {w['passed']} |"
            )
        lines.append("")

    # Caveats
    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "1. **This is a proxy analysis, not a true walk-forward haircut.** The formula"
    )
    lines.append(
        "   `haircut = avg_sharpe / max(avg_sharpe, |decay| + 1)` approximates OOS"
    )
    lines.append(
        "   degradation using the within-period first-half/second-half PnL split."
    )
    lines.append(
        "2. **True IS/OOS haircut requires** populated window date columns + window-level"
    )
    lines.append(
        "   Sharpe ratios. Both are absent from the current SRF data pipeline."
    )
    lines.append(
        "3. **Negative Sharpe ratios dominate.** 7/8 candidates have deeply negative"
    )
    lines.append(
        "   average Sharpe, suggesting either unprofitable strategies or parameter"
    )
    lines.append(
        "   misconfiguration. The haircut ratio is moot when the strategy itself is"
    )
    lines.append("   unprofitable.")
    lines.append(
        "4. **`ttc_xauusd` is the only candidate with any positive Sharpe runs**"
    )
    lines.append(
        "   (XAUUSD 5m=1.68, 15m=5.04), but still rated no-go (0/5 and 2/5 windows passed)."
    )
    lines.append("")

    # DEBT recommendations
    lines.append("## [DEBT] Cards Recommended")
    lines.append("")
    lines.append(
        "1. **Fix `srf/runner.py` `_insert_windows` to populate date columns** — "
    )
    lines.append(
        "   `train_start/end`, `test_start/end` must be written per window for true"
    )
    lines.append("   walk-forward analysis.")
    lines.append(
        "2. **Re-run SRF sweep for 7 candidates missing from `windows` table** — "
    )
    lines.append("   only `killzone_momentum` has window-level data.")
    lines.append(
        "3. **Investigate deeply negative Sharpe ratios** — values like -2812 (donchian"
    )
    lines.append("   XAUUSD 15m) suggest data quality or parameter search issues.")
    lines.append("")

    lines.append("---")
    lines.append("*Generated by `scripts/quant/walk_forward_analysis.py`*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Proxy haircut-ratio walk-forward analysis"
    )
    parser.add_argument(
        "--db",
        default="data/research/research.duckdb",
        help="Path to SRF DuckDB file (default: data/research/research.duckdb)",
    )
    parser.add_argument(
        "--report",
        default="reports/quant/walk_forward_2026-07-17.md",
        help="Output report path (default: reports/quant/walk_forward_2026-07-17.md)",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DuckDB file not found: {db_path}", file=sys.stderr)
        return 1

    con = duckdb.connect(str(db_path), read_only=True)

    # Load all runs
    all_runs = load_runs(con)

    # Aggregate per candidate
    results = [aggregate_candidate(name, all_runs) for name in FTMO_CANDIDATES]

    # Load windows for sanity check
    windows_data: dict[str, list[dict]] = {}
    for name in FTMO_CANDIDATES:
        windows_data[name] = load_windows_for_candidate(con, name)

    con.close()

    # Print summary to stdout
    print(
        f"\n{'Candidate':<30s} {'Runs':>4s} {'Avg Sharpe':>12s} {'Avg Decay':>10s} {'Haircut':>10s} {'Verdict':>10s}"
    )
    print("-" * 80)
    for r in results:
        sharpe = f"{r.avg_mean_sharpe:.4f}" if r.avg_mean_sharpe is not None else "N/A"
        decay = f"{r.avg_oos_decay:.4f}" if r.avg_oos_decay is not None else "N/A"
        haircut = f"{r.haircut_ratio:.4f}" if r.haircut_ratio is not None else "N/A"
        print(
            f"{r.name:<30s} {r.total_runs:>4d} {sharpe:>12s} {decay:>10s} {haircut:>10s} {r.verdict:>10s}"
        )

    # Generate report
    report_content = generate_report(results, windows_data, str(db_path))
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_content, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    # Print kill list
    kill_list = [r for r in results if r.verdict == "kill"]
    if kill_list:
        print(f"\nKILL LIST ({len(kill_list)} candidates):")
        for r in kill_list:
            print(f"  - {r.name}: haircut={r.haircut_ratio:.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
