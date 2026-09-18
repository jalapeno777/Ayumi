#!/usr/bin/env python3
"""
Metric audit tool — independent recomputation and divergence detection.

Kills the "77% claimed vs 2% actual" class of unaudited-dashboard failures.

Usage:
    python3 scripts/audit_metric.py --metric <name> --claim <float> --truth <float>
        [--jsonl-log <path>] [--open-finding]

The script:
  1. Reads the dashboard "claimed" value (the figure a dashboard asserts).
  2. Reads the independently recomputed "truth" value (what the metric actually is).
  3. Emits one JSONL line: metric, claimed, actual, delta, ratio, flagged.
  4. If |claimed - actual| / max(actual, epsilon) > 2.0, the row is flagged.
  5. By default, the script writes the JSONL line to stdout AND appends it to
     the canonical append-only log (data/health/metric-audit-log.jsonl).
  6. With --open-finding, a "metric-audit-flagged" FINDING card is opened on the
     workboard describing the divergence.

Standing rule: any metric that has not passed one audit is not allowed to gate
a decision. Run an audit before relying on any new number.

Exit codes:
  0 — audit clean (delta <= 2x).
  1 — divergence flagged (delta > 2x). The audit JSONL row is still emitted.
  2 — usage error.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

# The standing-rule threshold is 2x. Tuned once, fixed thereafter. Changing it
# requires re-running the calibration fixture under tests/test_audit_metric.py.
DELTA_RATIO_THRESHOLD = 2.0

# Epsilon avoids divide-by-zero on tiny denominators. Picked so a 1-percentage-
# point move on a small denominator still registers a ratio.
EPSILON = 1e-6

DEFAULT_LOG_PATH = "data/health/metric-audit-log.jsonl"


class UsageError(Exception):
    """Raised on a usage-level failure that should exit with code 2."""


def _resolve_value(arg_value: str | None, file_value: str | None, shell_value: str | None) -> float:
    """Resolve one side of the audit from the mutually exclusive input flags.

    Exactly one of (arg, --file, --shell) must be provided.
    """
    provided = [v is not None for v in (arg_value, file_value, shell_value)]
    if sum(provided) != 1:
        raise UsageError(
            "audit_metric: provide exactly one of --claim/--truth, "
            "--claim-file/--truth-file, or --claim-shell/--truth-shell"
        )
    if arg_value is not None:
        return float(arg_value)
    if file_value is not None:
        text = Path(file_value).read_text(encoding="utf-8").strip()
        return float(text)
    if shell_value is not None:
        result = subprocess.run(
            shell_value,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    raise UsageError("audit_metric: unreachable — no value source provided")


def _compute_ratio(claimed: float, actual: float) -> float:
    """Ratio of divergence to actual. EPSILON keeps it defined near zero."""
    return abs(claimed - actual) / max(abs(actual), EPSILON)


def _ensure_finite(name: str, value: float) -> None:
    """Reject NaN / +Infinity / -Infinity as a usage error.

    Non-finite inputs make the divergence gate undefined: NaN comparisons
    return False (so a NaN-tainted audit would emit ``flagged: false`` and
    silently bypass the >2x rule), and ±Infinity yields non-standard JSON
    values. Catch them before any row is built or logged.
    """
    if not math.isfinite(value):
        raise UsageError(
            f"audit_metric: --{name} must be a finite real number, got {value!r}"
        )


def _build_row(metric: str, claimed: float, actual: float) -> dict:
    delta = claimed - actual
    ratio = _compute_ratio(claimed, actual)
    flagged = ratio > DELTA_RATIO_THRESHOLD
    return {
        "metric": metric,
        "claimed": claimed,
        "actual": actual,
        "delta": delta,
        "ratio": ratio,
        "threshold": DELTA_RATIO_THRESHOLD,
        "flagged": flagged,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _append_jsonl(path: Path, row: dict) -> None:
    """Append the row to the JSONL log. Caller is responsible for log file
    permissions; this function never truncates."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _open_finding(row: dict) -> None:
    """Best-effort attempt to open a workboard FINDING card for the divergence.

    Failures here are surfaced but do not block the audit emission — the row
    is the durable receipt, the FINDING is a workflow courtesy. A broken
    workboard CLI should never silently hide a flagged audit.
    """
    try:
        cmd = [
            "workboard_create",
            "--title",
            f"[FINDING] Metric audit divergence: {row['metric']} "
            f"({row['claimed']:.4f} claimed vs {row['actual']:.4f} actual, "
            f"ratio {row['ratio']:.2f}x)",
            "--notes",
            "Auto-opened by scripts/audit_metric.py because ratio "
            f"{row['ratio']:.2f}x exceeds {DELTA_RATIO_THRESHOLD}x threshold.\n"
            "Standing rule: no metric may gate a decision without passing one "
            "audit. Investigate the dashboard source and the recomputation path.",
            "--priority",
            "high",
            "--labels",
            "[FINDING]",
            "[METRIC-AUDIT]",
            "--agentId",
            "reina",
        ]
        subprocess.run(cmd, check=False, capture_output=True, text=True)
    except Exception as exc:  # pragma: no cover — defensive only
        print(f"audit_metric: could not open FINDING card: {exc}", file=sys.stderr)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independently audit a metric against its dashboard claim."
    )
    parser.add_argument("--metric", required=True, help="Metric name being audited.")
    parser.add_argument("--claim", help="Dashboard-claimed value (float).")
    parser.add_argument(
        "--claim-file",
        help="Path to a file containing the dashboard-claimed value (float).",
    )
    parser.add_argument(
        "--claim-shell",
        help="Shell command whose stdout is the dashboard-claimed value.",
    )
    parser.add_argument("--truth", help="Independently recomputed truth (float).")
    parser.add_argument(
        "--truth-file",
        help="Path to a file containing the independently recomputed truth.",
    )
    parser.add_argument(
        "--truth-shell",
        help="Shell command whose stdout is the independently recomputed truth.",
    )
    parser.add_argument(
        "--jsonl-log",
        default=os.environ.get("METRIC_AUDIT_LOG", DEFAULT_LOG_PATH),
        help=f"Append-only JSONL log path (default: {DEFAULT_LOG_PATH}).",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Skip appending to the JSONL log (still emits to stdout).",
    )
    parser.add_argument(
        "--open-finding",
        action="store_true",
        help="Open a FINDING card when the audit is flagged.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    try:
        claimed = _resolve_value(args.claim, args.claim_file, args.claim_shell)
        actual = _resolve_value(args.truth, args.truth_file, args.truth_shell)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"audit_metric: could not parse numeric value: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"audit_metric: source failed: {exc}", file=sys.stderr)
        return 2

    try:
        _ensure_finite("claim", claimed)
        _ensure_finite("truth", actual)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    row = _build_row(args.metric, claimed, actual)

    print(json.dumps(row, sort_keys=True))

    if not args.no_log:
        _append_jsonl(Path(args.jsonl_log), row)

    if row["flagged"] and args.open_finding:
        _open_finding(row)

    return 1 if row["flagged"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
