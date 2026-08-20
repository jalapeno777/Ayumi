#!/usr/bin/env python3
"""
build_report.py — Revalidation 2026-07 Comparative Report Generator

Reads raw re-sweep results from docs/strategies/revalidation-2026-07/raw/_summary.json,
queries the research DuckDB for prior sweep metrics, and outputs a comparative
report (report.md) and strategy ranking (ranking.md).

Usage:
    python3 scripts/build_report.py [--db data/research/research.duckdb]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def load_new_sweep(raw_dir: str) -> dict:
    """Load the new re-sweep summary."""
    summary_path = os.path.join(raw_dir, "_summary.json")
    with open(summary_path) as f:
        return json.load(f)


def load_old_sweep(db_path: str) -> dict:
    """Load prior sweep metrics from the research DuckDB."""
    try:
        import duckdb
    except ImportError:
        print(
            "WARNING: duckdb not installed — old sweep data unavailable",
            file=sys.stderr,
        )
        return {}

    if not os.path.exists(db_path):
        print(
            f"WARNING: DuckDB not found at {db_path} — old sweep data unavailable",
            file=sys.stderr,
        )
        return {}

    con = duckdb.connect(db_path, read_only=True)

    # Map strategy names to their timeframes used in the re-sweep
    strategy_tf = {
        "ttc_xauusd": 15,
        "killzone_momentum": 60,
        "srmr_plus": 15,
        "london_breakout_retest": 15,
        "volatility_squeeze": 60,
        "volatility_regime_breakout": 15,
    }

    old_data = {}
    for strat, tf in strategy_tf.items():
        rows = con.execute(
            """
            SELECT r.run_id, r.strategy_name, r.timeframe, r.created_at,
                   m.mean_profit_factor, m.mean_win_rate, m.mean_sharpe,
                   m.mean_max_drawdown, m.total_trades, m.windows_passed,
                   m.windows_total, m.go_nogo
            FROM metrics_summary m
            JOIN runs r ON m.run_id = r.run_id
            WHERE r.pair = 'XAUUSD' AND r.strategy_name = ? AND r.timeframe = ?
            ORDER BY r.created_at DESC
            """,
            [strat, tf],
        ).fetchall()

        if rows:
            r = rows[0]  # Most recent pre-re-sweep run
            old_data[strat] = {
                "run_id": r[0],
                "profit_factor": r[4],
                "win_rate": r[5],
                "sharpe": r[6],
                "max_dd": r[7],
                "total_trades": r[8],
                "windows_passed": r[9],
                "windows_total": r[10],
                "go_nogo": r[11],
            }
    con.close()
    return old_data


def is_anomalous_go(s: dict) -> bool:
    """A strategy is anomalously GO if go_nogo=True but PF < 1.0.

    This detects the window-count vs profitability criteria conflict:
    a strategy can pass 3/5 windows (GO) while having PF < 1.0 (net losses).
    """
    return s.get("go_nogo", False) and s.get("profit_factor", 0) < 1.0


def fmt_delta(new: float, old: float | None, higher_better: bool = True) -> str:
    """Format a delta between old and new values."""
    if old is None or old == 0:
        if new is not None and new != 0:
            return f"NEW ({new:.3f})"
        return "N/A"
    delta = new - old
    sign = "+" if delta >= 0 else ""
    good = (delta > 0) == higher_better
    indicator = "✅" if good and delta != 0 else ("⚠️" if not good and delta != 0 else "")
    return f"{old:.3f} → {new:.3f} ({sign}{delta:.3f}) {indicator}"


def fmt_delta_raw(new: float | None, old: float | None, higher_better: bool = True) -> str:
    """Format delta without emoji (for markdown tables)."""
    if old is None:
        if new is not None:
            return f"N/A → {new:.3f}"
        return "N/A"
    if old == 0 and new == 0:
        return "0.000 → 0.000"
    delta = new - old if new is not None else 0
    sign = "+" if delta >= 0 else ""
    return f"{old:.3f} → {new:.3f} ({sign}{delta:.3f})"


def generate_report(new_data: dict, old_data: dict) -> str:
    """Generate the comparative report markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    params = new_data.get("canonical_params", {})

    lines = []
    lines.append("# Revalidation Report — July 2026")
    lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**Sweep date:** {new_data.get('generated_at', 'N/A')}")
    lines.append(f"**Strategies evaluated:** {new_data.get('total_strategies', 0)}")
    lines.append(f"**Walk-forward windows:** {new_data.get('n_windows', 5)}")
    lines.append("")
    lines.append("## Canonical Parameters (Corrected)")
    lines.append("")
    lines.append("| Parameter | Value |")
    lines.append("|---|---|")
    lines.append(f"| Initial Balance | ${params.get('initial_balance', 100000):,.0f} |")
    lines.append(f"| Risk per Trade | {params.get('risk_per_trade_pct', 0.005) * 100:.1f}% |")
    lines.append(f"| Daily DD Limit | {params.get('daily_dd_limit_pct', 0.03) * 100:.1f}% |")
    lines.append(f"| Max Open Trades | {params.get('max_open_trades', 3)} |")
    lines.append("")
    lines.append("> **⚠ PROVISIONAL:** All strategy decisions based on historical sweeps prior to")
    lines.append("> this revalidation are marked **PROVISIONAL** throughout this report. The")
    lines.append("> corrected FTMO parameters (0.5% risk, 3% daily DD, $100k balance) reflect")
    lines.append("> actual FTMO challenge conditions. Prior sweeps used incorrect parameters")
    lines.append("> (1% risk, 5% daily DD) that inflated trade counts and drawdown tolerance.")
    lines.append("")

    # Per-strategy comparison
    lines.append("## Per-Strategy Comparison (Old Sweep vs Re-Sweep)")
    lines.append("")
    lines.append("| Strategy | Pair | TF | Metric | Old Sweep | New Re-Sweep | Delta |")
    lines.append("|---|---|---|---|---|---|---|")

    for s in new_data["strategies"]:
        strat = s["strategy"]
        old = old_data.get(strat, {})
        pair = s.get("pair", "XAUUSD")
        tf = s.get("timeframe", "?")

        # Profit Factor
        old_pf = old.get("profit_factor")
        new_pf = s["profit_factor"]
        lines.append(f"| {strat} | {pair} | {tf} | **PF** | {fmt_delta_raw(new_pf, old_pf)} | | |")

        # Win Rate
        old_wr = old.get("win_rate")
        new_wr = s.get("win_rate")
        lines.append(f"| | | | **Win Rate** | {fmt_delta_raw(new_wr, old_wr)} | | |")

        # Sharpe
        old_sh = old.get("sharpe")
        new_sh = s.get("sharpe")
        lines.append(f"| | | | **Sharpe** | {fmt_delta_raw(new_sh, old_sh)} | | |")

        # Max DD
        old_dd = old.get("max_dd")
        new_dd = s.get("max_dd")
        lines.append(f"| | | | **Max DD** | {fmt_delta_raw(new_dd, old_dd, higher_better=False)} | | |")

        # Trades
        old_t = old.get("total_trades", 0)
        new_t = s.get("total_trades", 0)
        lines.append(
            f"| | | | **Trades** | {old_t or 0} → {new_t} ({'+' if new_t - (old_t or 0) >= 0 else ''}{new_t - (old_t or 0)}) | | |"  # noqa: E501
        )

        # Go/No-Go (normalize case: DB stores lowercase, report uses uppercase)
        old_go_raw = old.get("go_nogo", "N/A")
        old_go = old_go_raw.upper() if old_go_raw != "N/A" else "N/A"
        new_go = "GO" if s.get("go_nogo") else "NO-GO"
        change = ""
        if old_go != new_go and old_go != "N/A":
            change = "🔥 **STATUS CHANGE**" if new_go == "GO" else "📉 **STATUS CHANGE**"
        lines.append(f"| | | | **GO/NO-GO** | {old_go} → {new_go} {change} | | |")
        lines.append("| | | | | | | |")

    # Detailed analysis
    lines.append("## Detailed Analysis")
    lines.append("")

    for s in new_data["strategies"]:
        strat = s["strategy"]
        old = old_data.get(strat, {})
        lines.append(f"### {strat} ({s.get('pair', 'XAUUSD')} {s.get('timeframe', '?')})")
        lines.append("")

        new_go = "GO" if s.get("go_nogo") else "NO-GO"
        old_go_raw = old.get("go_nogo", "N/A")
        old_go = old_go_raw.upper() if old_go_raw != "N/A" else "N/A"
        old_pf = old.get("profit_factor")
        old_trades = old.get("total_trades", 0)

        if old:
            if old_go != new_go and old_go != "N/A":
                if new_go == "GO":
                    lines.append(f"- **Status: ↑ Newly passing** (was {old_go}, now GO)")
                    lines.append(
                        f"- PF improved: {old_pf:.3f} → {s['profit_factor']:.3f}"
                        if old_pf
                        else f"- PF: {s['profit_factor']:.3f}"
                    )
                    if old_trades == 0:
                        lines.append(
                            "- **Critical:** Old sweep generated 0 trades — strategy was untestable with prior params"
                        )
                else:
                    lines.append(f"- **Status: 📉 Newly failing** (was {old_go}, now NO-GO)")
            else:
                lines.append(f"- **Status: {new_go}** (unchanged from prior sweep)")
        else:
            lines.append(f"- **Status: {new_go}** (no prior sweep data for this strategy/TF combination)")

        lines.append(
            f"- Profit Factor: {s['profit_factor']:.3f} (95% CI: [{s.get('ci_lower', 0):.3f}, {s.get('ci_upper', 0):.3f}])"  # noqa: E501
        )
        lines.append(f"- Win Rate: {s.get('win_rate', 0):.1%}")
        lines.append(f"- Sharpe Ratio: {s.get('sharpe', 0):.3f}")
        lines.append(f"- Max Drawdown: {s.get('max_dd', 0):.2%}")
        lines.append(f"- Windows Passed: {s.get('windows_passed', 0)}/{s.get('total_windows', 5)}")
        lines.append(f"- Total Trades: {s.get('total_trades', 0)}")

        # Flag anomalies
        if s.get("ci_lower", 1) < 1.0 and new_go == "GO":
            lines.append(
                f"- ⚠ **CI concern:** Lower bound ({s.get('ci_lower', 0):.3f}) < 1.0 — profitability not statistically certain"  # noqa: E501
            )
        if old_trades == 0 and s.get("total_trades", 0) > 0:
            lines.append("- ⚠ **Old sweep had 0 trades** — comparison may not be meaningful")

        lines.append("")

    # Go/No-Go summary — split GO into clean and anomalous
    all_go = [s for s in new_data["strategies"] if s.get("go_nogo")]
    clean_go = [s for s in all_go if not is_anomalous_go(s)]
    anomalous_go = [s for s in all_go if is_anomalous_go(s)]
    nogo_strategies = [s for s in new_data["strategies"] if not s.get("go_nogo")]

    lines.append("## Go/No-Go Summary")
    lines.append("")
    lines.append(f"### ✅ GO ({len(clean_go)})")
    lines.append("")
    for s in sorted(clean_go, key=lambda x: x.get("profit_factor", 0), reverse=True):
        lines.append(
            f"1. **{s['strategy']}** — PF={s['profit_factor']:.2f}, Sharpe={s.get('sharpe', 0):.2f}, WR={s.get('win_rate', 0):.1%}"  # noqa: E501
        )
    lines.append("")
    if anomalous_go:
        lines.append(f"### ⚠ ANOMALOUS — Criteria Conflict ({len(anomalous_go)})")
        lines.append("")
        lines.append("These strategies have GO=true (passed ≥3/5 windows) but PF < 1.0 (net losses).")
        lines.append("**DO NOT DEPLOY until criteria conflict is resolved.**")
        lines.append("")
        for s in sorted(anomalous_go, key=lambda x: x.get("profit_factor", 0), reverse=True):
            lines.append(
                f"1. **{s['strategy']}** — PF={s['profit_factor']:.2f}, Sharpe={s.get('sharpe', 0):.2f}, WR={s.get('win_rate', 0):.1%} (GO by window count {s.get('windows_passed', 0)}/{s.get('total_windows', 5)}, but PF indicates losses)"  # noqa: E501
            )
        lines.append("")
    lines.append(f"### ❌ NO-GO ({len(nogo_strategies)})")
    lines.append("")
    for s in sorted(nogo_strategies, key=lambda x: x.get("profit_factor", 0), reverse=True):
        lines.append(
            f"1. **{s['strategy']}** — PF={s['profit_factor']:.2f}, Sharpe={s.get('sharpe', 0):.2f}, WR={s.get('win_rate', 0):.1%}"  # noqa: E501
        )
    lines.append("")

    # Status changes
    lines.append("## Status Changes (Old → New)")
    lines.append("")
    newly_passing = []
    newly_failing = []
    for s in new_data["strategies"]:
        strat = s["strategy"]
        old = old_data.get(strat, {})
        old_go_str = old.get("go_nogo", "").upper()
        new_is_go = s.get("go_nogo", False)

        if old_go_str == "NO-GO" and new_is_go:
            newly_passing.append(strat)
        elif old_go_str == "GO" and not new_is_go:
            newly_failing.append(strat)

    if newly_passing:
        lines.append("### ↑ Newly Passing")
        for strat in newly_passing:
            # Check if this strategy is anomalous (GO but PF < 1.0)
            strat_data = next((s for s in new_data["strategies"] if s["strategy"] == strat), None)
            if strat_data and is_anomalous_go(strat_data):
                lines.append(
                    f"- **{strat}** — ↑ Newly passing BY WINDOW COUNT ({strat_data.get('windows_passed', 0)}/{strat_data.get('total_windows', 5)}) but PF={strat_data['profit_factor']:.2f} indicates losses — criteria conflict, see anomaly section. Prior decisions are **PROVISIONAL**."  # noqa: E501
                )
            else:
                lines.append(
                    f"- **{strat}** — was NO-GO, now GO. Prior decisions to shelve this strategy are **PROVISIONAL**."
                )
    else:
        lines.append("### ↑ Newly Passing: None")

    if newly_failing:
        lines.append("### ↓ Newly Failing")
        for strat in newly_failing:
            lines.append(
                f"- **{strat}** — was GO, now NO-GO. Prior decisions to deploy this strategy need **immediate review**."
            )
    else:
        lines.append("### ↓ Newly Failing: None")

    lines.append("")

    # Anomaly section (between Status Changes and PROVISIONAL)
    anomalous = [s for s in new_data["strategies"] if is_anomalous_go(s)]
    if anomalous:
        lines.append("## ⚠ Anomaly: GO Flag vs Metrics Conflict")
        lines.append("")
        for s in anomalous:
            lines.append(f"### {s['strategy']}")
            lines.append("")
            lines.append(
                f"- **GO flag:** True (passed {s.get('windows_passed', 0)}/{s.get('total_windows', 5)} walk-forward windows)"  # noqa: E501
            )
            lines.append(f"- **Profit Factor:** {s['profit_factor']:.3f} — below 1.0, indicating net losses")
            lines.append(f"- **Sharpe Ratio:** {s.get('sharpe', 0):.3f} — negative")
            lines.append(f"- **CI lower bound:** {s.get('ci_lower', 0):.3f} — well below 1.0 profitability threshold")
            lines.append("")
            lines.append("**Root cause:** The GO/NO-GO gate uses window-count (≥3/5 passed) as its criterion,")
            lines.append(f"but PF={s['profit_factor']:.2f} means the strategy loses money on average. These two")
            lines.append("criteria conflict for this strategy.")
            lines.append("")
            lines.append("**Recommendation:** Resolve the criterion conflict BEFORE any FTMO deployment decision.")
            lines.append("Either:(a) add a PF ≥ 1.0 floor to the GO gate, or (b) accept window-count as sole")
            lines.append("criterion and document the risk. This is the issue parent card d8c5aead flagged")
            lines.append("for this report to address.")
            lines.append("")
            lines.append(f"**Status: DO NOT DEPLOY {s['strategy']} until this conflict is resolved.**")
            lines.append("")

    # Provisional decisions warning
    lines.append("## ⚠ PROVISIONAL Decisions Flag")
    lines.append("")
    lines.append("All strategy deployment, shelving, or parameter decisions made between the original")
    lines.append("sweep (Jul 13–19, 2026) and this revalidation (Jul 24, 2026) are **PROVISIONAL**.")
    lines.append("They were based on sweeps with incorrect FTMO parameters and must be re-evaluated")
    lines.append("against the corrected results in this report.")
    lines.append("")
    lines.append("**Affected decisions:**")
    lines.append("- Any strategy promoted to forward testing based on old sweep GO status")
    lines.append("- Any strategy archived based on old sweep NO-GO status")
    lines.append("- Any parameter optimization performed against old sweep metrics")
    lines.append("- The multiple testing correction (Jul 12) results — p-values were computed from")
    lines.append("  old sweep data and may change with corrected params")
    lines.append("")

    # Recommendation — exclude anomalous GO strategies from deploy recommendation
    lines.append("## Craig Recommendation")
    lines.append("")
    lines.append("Based on the corrected re-sweep results:")
    lines.append("")
    deploy_go = sorted(clean_go, key=lambda x: x.get("profit_factor", 0), reverse=True)
    if deploy_go:
        lines.append("**Proceed to FTMO live capital:**")
        for s in deploy_go:
            lines.append(f"- {s['strategy']} (PF={s['profit_factor']:.2f}, Sharpe={s.get('sharpe', 0):.2f})")
    lines.append("")
    not_deploy = sorted(
        nogo_strategies + anomalous_go,
        key=lambda x: x.get("profit_factor", 0),
        reverse=True,
    )
    if not_deploy:
        lines.append("**Do not deploy:**")
        for s in not_deploy:
            note = ""
            if is_anomalous_go(s):
                note = f" (⚠ ANOMALOUS: GO by window count but PF={s['profit_factor']:.2f} — criteria conflict, see anomaly section)"  # noqa: E501
            lines.append(f"- {s['strategy']} (PF={s['profit_factor']:.2f}){note}")
    lines.append("")
    lines.append("---")
    lines.append("*Generated by `scripts/build_report.py`*")

    return "\n".join(lines)


def generate_ranking(new_data: dict) -> str:
    """Generate the strategy ranking markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Sort by a composite score: PF (primary), Sharpe (secondary), WR (tertiary)
    strategies = sorted(
        new_data["strategies"],
        key=lambda s: (
            s.get("profit_factor", 0),
            s.get("sharpe", 0),
            s.get("win_rate", 0),
        ),
        reverse=True,
    )

    lines = []
    lines.append("# Strategy Ranking — Revalidation July 2026")
    lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append("**Source:** docs/strategies/revalidation-2026-07/raw/_summary.json")
    lines.append("")
    lines.append("Ranking derived from corrected FTMO parameter re-sweep. Sorted by Profit Factor")
    lines.append("(primary), Sharpe ratio (secondary), Win Rate (tertiary).")
    lines.append("")
    lines.append(
        "| Rank | Strategy | Pair | TF | PF | 95% CI | Sharpe | Win Rate | Max DD | GO/NO-GO | Windows | Trades |"
    )
    lines.append("|---:|---|---|---|---:|---|---:|---:|---:|---|---:|---:|")

    for i, s in enumerate(strategies, 1):
        is_go = s.get("go_nogo", False)
        pf = s.get("profit_factor", 0)
        # Anomalous: GO flag true but PF < 1.0 — show with warning marker
        if is_go and pf < 1.0:
            go_emoji = "⚠ GO*"
        elif is_go:
            go_emoji = "✅"
        else:
            go_emoji = "❌"
        ci_str = f"[{s.get('ci_lower', 0):.3f}, {s.get('ci_upper', 0):.3f}]"
        lines.append(
            f"| {i} | **{s['strategy']}** | {s.get('pair', '')} | {s.get('timeframe', '')} "
            f"| {s['profit_factor']:.3f} | {ci_str} "
            f"| {s.get('sharpe', 0):.3f} | {s.get('win_rate', 0):.1%} "
            f"| {s.get('max_dd', 0):.2%} | {go_emoji} "
            f"| {s.get('windows_passed', 0)}/{s.get('total_windows', 5)} "
            f"| {s.get('total_trades', 0)} |"
        )

    lines.append("")
    lines.append("## Tier Classification")
    lines.append("")
    lines.append("- **Tier S** (PF > 5.0, GO): Elite — deploy with confidence")
    lines.append("- **Tier A** (PF > 1.5, GO): Strong — deploy with monitoring")
    lines.append("- **Tier B** (PF > 1.0, GO): Marginal — deploy with caution, CI lower must be > 1.0")
    lines.append("- **Tier C** (PF < 1.0, NO-GO): Do not deploy")
    lines.append("- **Tier D** (PF < 0.5, NO-GO): Archive")
    lines.append("")
    lines.append("> **⚠ Anomaly note:** Strategies with GO=true but PF < 1.0 are marked `⚠ GO*` in the")
    lines.append("> table above. These passed the window-count gate (≥3/5) but have Profit Factors")
    lines.append("> indicating net losses. The GO flag and profitability criteria conflict.")
    lines.append("> **DO NOT DEPLOY these strategies until the criteria conflict is resolved.**")
    lines.append("")

    for s in strategies:
        pf = s["profit_factor"]
        is_go = s.get("go_nogo", False)
        if pf > 5.0 and is_go:
            tier = "S"
        elif pf > 1.5 and is_go:
            tier = "A"
        elif pf > 1.0 and is_go:
            tier = "B"
        elif pf < 0.5:
            tier = "D"
        else:
            tier = "C"
        s["_tier"] = tier

    for tier_name, tier_label in [
        ("S", "Elite"),
        ("A", "Strong"),
        ("B", "Marginal"),
        ("C", "Do not deploy"),
        ("D", "Archive"),
    ]:
        tier_strats = [s for s in strategies if s.get("_tier") == tier_name]
        if tier_strats:
            lines.append(f"### Tier {tier_name} — {tier_label}")
            for s in tier_strats:
                lines.append(f"- {s['strategy']} (PF={s['profit_factor']:.2f})")
            lines.append("")

    lines.append("---")
    lines.append("*Generated by `scripts/build_report.py`*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate revalidation-2026-07 comparative report")
    parser.add_argument(
        "--db",
        default="data/research/research.duckdb",
        help="Path to research DuckDB (default: data/research/research.duckdb)",
    )
    parser.add_argument(
        "--raw-dir",
        default="docs/strategies/revalidation-2026-07/raw",
        help="Directory with raw re-sweep JSON files",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/strategies/revalidation-2026-07",
        help="Output directory for report.md and ranking.md",
    )
    args = parser.parse_args()

    # Load data
    print(f"Loading new sweep data from {args.raw_dir}...")
    new_data = load_new_sweep(args.raw_dir)
    print(f"  {new_data.get('total_strategies', 0)} strategies found")

    print(f"Loading old sweep data from {args.db}...")
    old_data = load_old_sweep(args.db)
    print(f"  {len(old_data)} matching prior runs found")

    # Generate reports
    print("Generating report.md...")
    report = generate_report(new_data, old_data)
    report_path = os.path.join(args.output_dir, "report.md")
    os.makedirs(args.output_dir, exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report)
    print(f"  Written: {report_path}")

    print("Generating ranking.md...")
    ranking = generate_ranking(new_data)
    ranking_path = os.path.join(args.output_dir, "ranking.md")
    with open(ranking_path, "w") as f:
        f.write(ranking)
    print(f"  Written: {ranking_path}")

    print("Done.")


if __name__ == "__main__":
    main()
