#!/usr/bin/env python3
"""Crisis-window wrapper for download_dukascopy.py.

Fetches M1 tick data for predefined crisis windows across multiple FX pairs,
using the existing Dukascopy downloader. Each (event, pair, month) download is
isolated so one failure does not abort the run.

Usage:
    python scripts/download_dukascopy_crisis.py              # all 6 crises
    python scripts/download_dukascopy_crisis.py --crisis 2015_chf_unpeg
    python scripts/download_dukascopy_crisis.py --dry-run    # print plan, no fetch
    python scripts/download_dukascopy_crisis.py --quiet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the scripts package is importable when run directly
_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Import the existing downloader
from scripts.download_dukascopy import (
    DEFAULT_OUT_DIR,
    aggregate_month,
    month_already_downloaded,
    month_iter,
    write_month_csv,
)

# -----------------------------------------------------------------------------
# Crisis window definitions
# -----------------------------------------------------------------------------

PAIRS = ["GBPUSD", "USDJPY", "EURUSD", "EURCHF", "GBPJPY"]

CRISIS_WINDOWS = [
    {
        "event": "2008_gfc",
        "start": "2008-09",
        "end": "2008-11",
        "pairs": PAIRS,
    },
    {
        "event": "2015_chf_unpeg",
        "start": "2015-01",
        "end": "2015-01",
        "pairs": PAIRS,
    },
    {
        "event": "2020_covid",
        "start": "2020-03",
        "end": "2020-03",
        "pairs": PAIRS,
    },
    {
        "event": "2019_jpy_flash",
        "start": "2019-01",
        "end": "2019-01",
        "pairs": PAIRS,
    },
    {
        "event": "2022_boj_pivot",
        "start": "2022-06",
        "end": "2022-09",
        "pairs": PAIRS,
    },
    {
        "event": "2016_gbp_flash",
        "start": "2016-10",
        "end": "2016-10",
        "pairs": PAIRS,
    },
]


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------

def _log(msg: str, quiet: bool = False) -> None:
    if not quiet:
        print(msg, flush=True)


def run_crisis(crisis: dict, out_dir: Path, dry_run: bool = False, quiet: bool = False) -> dict:
    """Download all pairs/months for one crisis window.

    Returns a summary dict with per-pair success/failure counts.
    """
    event = crisis["event"]
    start = crisis["start"]
    end = crisis["end"]
    pairs = crisis["pairs"]

    months = list(month_iter(start, end))
    total_jobs = len(pairs) * len(months)

    _log(f"\n=== Crisis: {event} ({start}..{end}) ===", quiet)
    _log(f"    Pairs: {pairs}", quiet)
    _log(f"    Months: {len(months)} | Total jobs: {total_jobs}", quiet)

    if dry_run:
        _log(f"    [DRY RUN] Would fetch {total_jobs} (pair, month) combos", quiet)
        for pair in pairs:
            for year, month_idx0 in months:
                _log(f"      -> {pair} {year:04d}-{month_idx0 + 1:02d}", quiet)
        return {"event": event, "total": total_jobs, "ok": 0, "skipped": 0, "error": 0, "details": []}

    results = []
    ok = 0
    skipped = 0
    error = 0

    for pair in pairs:
        for year, month_idx0 in months:
            label = f"event={event} pair={pair} month={year:04d}-{month_idx0 + 1:02d}"

            # Resume check
            if month_already_downloaded(out_dir, pair, year, month_idx0):
                _log(f"  [{label}] status=skip (csv exists)", quiet)
                skipped += 1
                results.append({"pair": pair, "month": f"{year:04d}-{month_idx0 + 1:02d}", "status": "skip"})
                continue

            try:
                bars = aggregate_month(pair, year, month_idx0, log=lambda m: _log(f"    {m}", quiet))
                path = write_month_csv(out_dir, pair, year, month_idx0, bars)
                _log(f"  [{label}] status=ok ({len(bars)} bars -> {path.name})", quiet)
                ok += 1
                results.append({"pair": pair, "month": f"{year:04d}-{month_idx0 + 1:02d}", "status": "ok", "bars": len(bars)})
            except Exception as e:
                _log(f"  [{label}] status=error: {type(e).__name__}: {e}", quiet)
                error += 1
                results.append({"pair": pair, "month": f"{year:04d}-{month_idx0 + 1:02d}", "status": "error", "error": str(e)})

    _log(f"  Summary {event}: ok={ok} skipped={skipped} error={error} / total={total_jobs}", quiet)
    return {"event": event, "total": total_jobs, "ok": ok, "skipped": skipped, "error": error, "details": results}


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Crisis-window wrapper for the Dukascopy M1 downloader.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--crisis", default=None,
        help="Run a single crisis by event name (e.g. 2015_chf_unpeg). Default: all 6 crises.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would be fetched without downloading.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-month progress logging.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory (default: %(default)s)")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)

    # Select crises
    if args.crisis:
        selected = [c for c in CRISIS_WINDOWS if c["event"] == args.crisis]
        if not selected:
            print(f"ERROR: unknown crisis '{args.crisis}'. Available: {[c['event'] for c in CRISIS_WINDOWS]}", file=sys.stderr)
            return 2
    else:
        selected = CRISIS_WINDOWS

    _log("=== Dukascopy Crisis Downloader ===", args.quiet)
    _log(f"Crises: {[c['event'] for c in selected]}", args.quiet)
    _log(f"Output: {out_dir.resolve()}", args.quiet)
    if args.dry_run:
        _log("Mode: DRY RUN (no downloads)", args.quiet)

    all_summaries = []
    for crisis in selected:
        summary = run_crisis(crisis, out_dir, dry_run=args.dry_run, quiet=args.quiet)
        all_summaries.append(summary)

    # Final overview
    _log("\n=== Final Summary ===", args.quiet)
    total_ok = sum(s["ok"] for s in all_summaries)
    total_skip = sum(s["skipped"] for s in all_summaries)
    total_err = sum(s["error"] for s in all_summaries)
    for s in all_summaries:
        rate = (s["ok"] / s["total"] * 100) if s["total"] else 0
        _log(f"  {s['event']}: {s['ok']}/{s['total']} ok ({rate:.0f}%) — skip={s['skipped']} err={s['error']}", args.quiet)
    _log(f"  TOTAL: ok={total_ok} skip={total_skip} err={total_err}", args.quiet)

    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
