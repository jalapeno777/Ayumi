"""Tier-1 multiple testing correction for sweep results.

Applies two standard corrections to a battery of backtest trials:

* **Bonferroni** — controls family-wise error rate. Reject H0 when
  ``p_i <= alpha / m``. Simple and conservative.
* **Benjamini-Hochberg (BH-FDR)** — controls the false discovery rate.
  Sort p-values ascending, find the largest k such that
  ``p_(k) <= (k / m) * q``, then reject H0 for all i <= k. More powerful
  than Bonferroni when many candidates are tested.

The input is a list of trials. Each trial is a dict containing at least:

* ``name``              — human-readable label (e.g. ``"srmr_plus/EURUSD/M15"``)
* ``mean_sharpe``       — average Sharpe across walk-forward windows
* ``trade_count``       — total trades observed across windows

The per-trial p-value is derived from a one-sample t-test on the Sharpe
ratio: ``t = mean_sharpe * sqrt(n) / 1`` under H0 that true Sharpe is 0
with unit-variance returns. This is the standard backtest-statistic
approximation (Lo, 2002) and matches the assumptions used elsewhere in
the SRF pipeline (deflated Sharpe, dsr.py).

CLI examples
------------
    # Use the SRF DuckDB (default) at the Ayumi project root:
    python scripts/quant/multiple_testing_correction.py

    # Use a custom JSON file of trial summaries:
    python scripts/quant/multiple_testing_correction.py \
        --input reports/quant/my_trials.json --alpha 0.05 --q 0.10

    # Write the markdown report to a specific path:
    python scripts/quant/multiple_testing_correction.py \
        --report reports/quant/multiple_testing_2026-07-12.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

try:
    from scipy import stats  # type: ignore
except Exception:  # scipy is the only non-stdlib dep; fall back if missing
    stats = None  # type: ignore


# ---------------------------------------------------------------------------
# Trial model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Trial:
    """One backtest trial — a strategy / pair / timeframe combination."""

    name: str
    mean_sharpe: float
    trade_count: int
    extra: dict = field(default_factory=dict)

    def t_stat(self) -> float:
        """One-sample t-statistic for H0: true Sharpe == 0.

        Approximates per-trial return variance as 1.0 (annualised). The
        standard error of the Sharpe estimator is 1/sqrt(n) under that
        assumption, giving ``t = sharpe * sqrt(n)``.
        """
        if self.trade_count <= 0:
            return 0.0
        return self.mean_sharpe * math.sqrt(self.trade_count)

    def p_value(self) -> float:
        """One-sided p-value for the t-statistic under H0: true Sharpe <= 0.

        Candidate selection only cares about positive edges. Trials with
        non-positive t-stats are reported with p = 1.0 — they are not
        candidates and should not appear in the survivor list regardless
        of how extreme their negative Sharpe is.
        """
        t = self.t_stat()
        if t <= 0.0:
            return 1.0
        if stats is not None and self.trade_count > 1:
            # Upper-tail p-value, df = n-1.
            return float(1.0 - stats.t.cdf(t, df=self.trade_count - 1))
        # Fallback: normal upper-tail via erfc.
        return 0.5 * math.erfc(t / math.sqrt(2.0))


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------


def bonferroni(p_values: Sequence[float], alpha: float) -> list[bool]:
    """Return a list of reject/accept decisions for the Bonferroni rule."""
    m = len(p_values)
    if m == 0:
        return []
    threshold = alpha / m
    return [p <= threshold for p in p_values]


def benjamini_hochberg(p_values: Sequence[float], q: float) -> list[bool]:
    """Return reject/accept decisions for the BH-FDR procedure.

    ``q`` is the desired false discovery rate (e.g. 0.10). The test is
    two-sided; we operate on the supplied p-values as-is.
    """
    m = len(p_values)
    if m == 0:
        return []
    # Sort by p-value, keep original index for reassembly.
    order = sorted(range(m), key=lambda i: p_values[i])
    sorted_p = [p_values[i] for i in order]

    # Find the largest k (1-indexed) such that p_(k) <= (k / m) * q.
    last_keep = -1
    for rank_1based, p in enumerate(sorted_p, start=1):
        if p <= (rank_1based / m) * q:
            last_keep = rank_1based  # 1-indexed; the rank of the last kept test

    decisions = [False] * m
    if last_keep >= 1:
        for rank_0based in range(last_keep):
            decisions[order[rank_0based]] = True
    return decisions


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def render_markdown_report(
    trials: list[Trial],
    p_values: list[float],
    bonf_decisions: list[bool],
    bh_decisions: list[bool],
    alpha: float,
    q: float,
    m: int,
    source: str,
) -> str:
    """Render the corrected results as a markdown report."""
    today = date.today().isoformat()

    n_bonf = sum(1 for d in bonf_decisions if d)
    n_bh = sum(1 for d in bh_decisions if d)
    n_unadj = sum(1 for p in p_values if p < alpha)
    n_negative = sum(1 for t in trials if t.mean_sharpe <= 0)

    # Sort trials by ascending p-value for the table.
    table = sorted(
        zip(trials, p_values, bonf_decisions, bh_decisions),  # noqa: B905
        key=lambda row: row[1],
    )

    # Display at most ``max_table_rows`` rows in the per-trial table; the
    # rest are negative-Sharpe trials with p=1.0, which are uninformative
    # in the table view and bloat the report. We still count them in the
    # summary above so the n_trials total remains accurate.

    lines: list[str] = []
    lines.append(f"# Multiple Testing Correction — {today}")
    lines.append("")
    lines.append("**Source:** " + source)
    lines.append(f"**Trials analyzed:** {m}")
    lines.append(f"**Alpha (per-test):** {alpha}")
    lines.append(f"**BH-FDR target (q):** {q}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Method | Rejected H0 (significant) | Notes |")
    lines.append("|---|---|---|")
    lines.append(
        f"| Uncorrected (p < {alpha}) | {n_unadj}/{m} | Each trial judged in isolation. "
        f"Expected false positives = {m} × {alpha} = {m * alpha:.2f}. |"
    )
    lines.append(
        f"| Bonferroni (p < {alpha}/{m} = {alpha / m:.5f}) | {n_bonf}/{m} | "
        "Controls family-wise error rate. Conservative. |"
    )
    lines.append(
        f"| Benjamini-Hochberg FDR (q = {q}) | {n_bh}/{m} | "
        "Controls expected proportion of false discoveries among rejections. |"
    )
    lines.append("")
    lines.append("## Per-trial results")
    lines.append("")
    lines.append("Sorted ascending by p-value. ✅ = rejected H0 (significant), ❌ = not rejected.")
    if n_negative > 0:
        lines.append(
            f"_Note: {n_negative} trial(s) have a non-positive mean Sharpe and are reported as p = 1 "
            f"(not candidates). They are omitted from the table below but counted in the summary above._"
        )
    lines.append("")
    lines.append("| # | Trial | Sharpe | Trades | p-value | Bonferroni | BH-FDR |")
    lines.append("|---:|---|---:|---:|---:|:---:|:---:|")
    # Show only "candidate" rows: those with positive mean Sharpe (p < 1.0).
    # Negative-Sharpe trials are noise here and bloat the report.
    shown = 0
    elided = 0
    for i, (trial, p, bonf, bh) in enumerate(table, start=1):
        if p >= 1.0:
            elided += 1
            continue
        shown += 1
        mark_bonf = "✅" if bonf else "❌"
        mark_bh = "✅" if bh else "❌"
        lines.append(
            f"| {i} | `{trial.name}` | {trial.mean_sharpe:+.3f} | {trial.trade_count} | "
            f"{p:.4g} | {mark_bonf} | {mark_bh} |"
        )
    if elided > 0:
        lines.append(f"| ... | _({elided} non-candidate trials with non-positive Sharpe elided)_ | | | | | |")
    lines.append("")

    # Surviving candidates under each rule.
    lines.append("## Surviving candidates")
    lines.append("")
    bonf_survivors = [t.name for t, d in zip(trials, bonf_decisions) if d]  # noqa: B905
    bh_survivors = [t.name for t, d in zip(trials, bh_decisions) if d]  # noqa: B905
    if bonf_survivors:
        lines.append("**Bonferroni survivors** (FWER controlled):")
        for name in bonf_survivors:
            lines.append(f"- `{name}`")
    else:
        lines.append(
            "**Bonferroni survivors** (FWER controlled): _none_ — no trial survives the conservative threshold."
        )
    lines.append("")
    if bh_survivors:
        lines.append("**Benjamini-Hochberg survivors** (FDR controlled):")
        for name in bh_survivors:
            lines.append(f"- `{name}`")
    else:
        lines.append("**Benjamini-Hochberg survivors** (FDR controlled): _none_.")
    lines.append("")

    # Interpretation.
    lines.append("## Interpretation")
    lines.append("")
    if n_bh == 0 and n_unadj > 0:
        lines.append(
            f"Out of {m} trials, {n_unadj} were individually significant at p < {alpha}, "
            f"but **none survive multiple-testing correction**. "
            f"This is the classic multiple-testing problem: when you run many trials, "
            f"a fraction of them will look significant by chance. "
            f"Bonferroni requires the largest single p-value to clear "
            f"{alpha:.4f} (alpha / {m}); BH-FDR at q = {q} requires the k-th ordered "
            f"p-value to clear (k / {m}) × {q} = {q / m:.4f} at k=1."
        )
    elif n_bh > 0:
        lines.append(
            f"{n_bh} of {m} trials survive BH-FDR at q = {q}. "
            f"These are the candidates whose apparent edges are most robust to the "
            f"look-elsewhere effect. Promote these to walk-forward validation and "
            f"live-paper stages; treat the rest as exploratory."
        )
        # If the strongest survivor has a suspiciously large Sharpe, call it out.
        top = table[0]
        if top[0].mean_sharpe > 5.0:
            lines.append("")
            lines.append(
                f"⚠️ **Caveat:** The top survivor (`{top[0].name}`) has a mean Sharpe of "
                f"{top[0].mean_sharpe:+.2f} on only {top[0].trade_count} trades. Sharpe "
                f"ratios above ~3.0 on small samples are typically artifacts of variance "
                f"estimation, not real edge. Treat the ranking as a screening tool, not a "
                f"deployable signal. Bootstrap CIs and walk-forward OOS performance must "
                f"confirm before any capital allocation."
            )
    else:
        lines.append(
            f"No trial reached nominal significance (p < {alpha}). "
            f"The candidate set is too weak to distinguish from noise — recommend "
            f"expanding the search or revisiting the underlying edge hypothesis."
        )
    lines.append("")

    lines.append("## Method")
    lines.append("")
    lines.append(
        "Per-trial p-values come from a one-sample t-test on the Sharpe ratio with "
        "``df = n_trades - 1`` and a unit-variance assumption on per-trade returns. "
        "This is the standard Lo (2002) approximation used in the SRF pipeline."
    )
    lines.append("")
    lines.append(
        "**Bonferroni** divides alpha by the number of trials. **Benjamini-Hochberg** "
        "controls the false discovery rate (expected proportion of false positives "
        "among rejected hypotheses) and is strictly more powerful than Bonferroni "
        "while still controlling FDR at level ``q`` under independence."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_trials_from_srf(duckdb_path: Path) -> list[Trial]:
    """Load trial summaries from the SRF research DuckDB."""
    import duckdb  # local import — duckdb is the SRF data store

    if not duckdb_path.exists():
        raise FileNotFoundError(f"SRF DuckDB not found at {duckdb_path}")

    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT
                r.strategy_name || '/' || r.pair || '/M' || CAST(r.timeframe AS VARCHAR) AS name,
                m.mean_sharpe,
                m.total_trades
            FROM runs r
            JOIN metrics_summary m USING (run_id)
            WHERE r.status = 'completed'
              AND m.mean_sharpe IS NOT NULL
              AND m.total_trades IS NOT NULL
              AND m.total_trades > 0
            ORDER BY name
            """
        ).fetchall()
    finally:
        conn.close()

    trials: list[Trial] = []
    for name, sharpe, trades in rows:
        trials.append(
            Trial(
                name=str(name),
                mean_sharpe=float(sharpe) if sharpe is not None else 0.0,
                trade_count=int(trades) if trades is not None else 0,
            )
        )
    return trials


def load_trials_from_json(path: Path) -> list[Trial]:
    """Load trial summaries from a JSON array.

    Expected shape: ``[{"name": ..., "mean_sharpe": ..., "trade_count": ...}, ...]``
    """
    with path.open() as fp:
        data = json.load(fp)
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array of trial records, got {type(data).__name__}")
    trials: list[Trial] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "?"))
        sharpe = float(entry.get("mean_sharpe", 0.0) or 0.0)
        trades = int(entry.get("trade_count", 0) or 0)
        trials.append(Trial(name=name, mean_sharpe=sharpe, trade_count=trades))
    return trials


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run(
    trials: Sequence[Trial],
    alpha: float,
    q: float,
    source: str,
    report_path: Path | None,
) -> dict:
    """Run the corrections and write the report. Returns a summary dict."""
    p_values = [t.p_value() for t in trials]
    bonf = bonferroni(p_values, alpha)
    bh = benjamini_hochberg(p_values, q)
    m = len(trials)

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            render_markdown_report(
                trials=list(trials),
                p_values=p_values,
                bonf_decisions=bonf,
                bh_decisions=bh,
                alpha=alpha,
                q=q,
                m=m,
                source=source,
            )
        )

    return {
        "n_trials": m,
        "alpha": alpha,
        "q": q,
        "n_uncorrected_significant": sum(1 for p in p_values if p < alpha),
        "n_bonferroni_significant": sum(1 for d in bonf if d),
        "n_bh_significant": sum(1 for d in bh if d),
        "bonferroni_survivors": [t.name for t, d in zip(trials, bonf) if d],  # noqa: B905
        "bh_survivors": [t.name for t, d in zip(trials, bh) if d],  # noqa: B905
        "p_values": dict(zip([t.name for t in trials], p_values)),  # noqa: B905
    }


def _default_paths() -> tuple[Path, Path]:
    """Best-effort defaults for the Ayumi project layout."""
    here = Path(__file__).resolve()
    # scripts/quant/multiple_testing_correction.py -> project root is 3 levels up
    project_root = here.parents[2]
    duckdb_path = project_root / "data" / "research" / "research.duckdb"
    report_path = project_root / "reports" / "quant" / f"multiple_testing_{date.today().isoformat()}.md"
    return duckdb_path, report_path


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to a JSON array of trial summaries. Defaults to the SRF DuckDB.",
    )
    parser.add_argument(
        "--duckdb",
        type=Path,
        default=None,
        help="Path to the SRF research DuckDB (used when --input is not given).",
    )
    parser.add_argument("--alpha", type=float, default=0.05, help="Per-test significance level.")
    parser.add_argument("--q", type=float, default=0.10, help="BH-FDR target proportion.")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Where to write the markdown report. Defaults to reports/quant/multiple_testing_<date>.md.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to also dump a JSON summary.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.input is not None:
        trials = load_trials_from_json(args.input)
        source = f"JSON input: {args.input}"
    else:
        duckdb_path = args.duckdb
        if duckdb_path is None:
            duckdb_path, _ = _default_paths()
        trials = load_trials_from_srf(duckdb_path)
        source = f"SRF DuckDB: {duckdb_path}"

    if not trials:
        print("No trials found — nothing to correct.", file=sys.stderr)
        return 1

    report_path = args.report
    if report_path is None and args.input is None:
        _, report_path = _default_paths()

    summary = run(
        trials=trials,
        alpha=args.alpha,
        q=args.q,
        source=source,
        report_path=report_path,
    )

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2))

    print(json.dumps({k: v for k, v in summary.items() if k != "p_values"}, indent=2))
    if report_path is not None:
        print(f"\nReport written to: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
