#!/usr/bin/env python3
"""Promotion rule clean-receipt validator (card 5d7c068b).

Checks the 4 clean-receipt criteria from docs/trading/active-blade.md
§ Promotion Rule for a given quarter id, and prints per-criterion
pass/fail, a weighted score, and a promotion recommendation.

Quarter data source resolution order:
  1. --input <json file>
  2. data/promotion/<quarter>.json (relative to repo root)
  3. built-in sample for quarter id "2026Q4-test"

Input JSON schema:
{
  "quarter": "2026Q4",
  "orders": {"total": 120, "orphans": 0, "missed_exits": 0},
  "slippage_pips": {"median_vs_backtest": 0.31, "p95_vs_backtest": 1.2},
  "regime_hit_rate": 0.74,
  "incidents": {"sev1": 0, "sev2": 0, "traceable_to_active_edge": true}
}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

THRESHOLDS = {
    "order_fill_integrity": "no orphan orders, no missed exits",
    "slippage_median_max": 0.5,
    "slippage_p95_max": 1.5,
    "regime_hit_rate_min": 0.70,
}

WEIGHTS = {
    "order_fill_integrity": 0.30,
    "slippage_distribution": 0.25,
    "regime_hit_rate": 0.25,
    "incident_cleanliness": 0.20,
}

SAMPLE_2026Q4_TEST = {
    "quarter": "2026Q4-test",
    "orders": {"total": 118, "orphans": 0, "missed_exits": 0},
    "slippage_pips": {"median_vs_backtest": 0.28, "p95_vs_backtest": 1.1},
    "regime_hit_rate": 0.73,
    "incidents": {"sev1": 0, "sev2": 0, "traceable_to_active_edge": True},
}


def load_quarter(quarter: str, input_path: str | None) -> dict:
    if input_path:
        return json.loads(Path(input_path).read_text())
    candidate = REPO_ROOT / "data" / "promotion" / f"{quarter}.json"
    if candidate.is_file():
        return json.loads(candidate.read_text())
    if quarter == "2026Q4-test":
        return SAMPLE_2026Q4_TEST
    raise SystemExit(f"no quarter data for '{quarter}' (looked for {candidate})")


def check_order_fill_integrity(data: dict) -> tuple[bool, str]:
    orders = data.get("orders", {})
    orphans = int(orders.get("orphans", 0))
    missed = int(orders.get("missed_exits", 0))
    ok = orphans == 0 and missed == 0
    return ok, f"orphans={orphans}, missed_exits={missed} ({THRESHOLDS['order_fill_integrity']})"


def check_slippage(data: dict) -> tuple[bool, str]:
    slip = data.get("slippage_pips", {})
    median = float(slip.get("median_vs_backtest", float("inf")))
    p95 = float(slip.get("p95_vs_backtest", float("inf")))
    ok = median <= THRESHOLDS["slippage_median_max"] and p95 <= THRESHOLDS["slippage_p95_max"]
    return ok, (
        f"median={median:.3f}pip (max {THRESHOLDS['slippage_median_max']}), "
        f"p95={p95:.3f}pip (max {THRESHOLDS['slippage_p95_max']})"
    )


def check_regime_hit_rate(data: dict) -> tuple[bool, str]:
    rate = float(data.get("regime_hit_rate", 0.0))
    ok = rate >= THRESHOLDS["regime_hit_rate_min"]
    return ok, f"hit_rate={rate:.2%} (min {THRESHOLDS['regime_hit_rate_min']:.0%})"


def check_incident_cleanliness(data: dict) -> tuple[bool, str]:
    inc = data.get("incidents", {})
    sev1 = int(inc.get("sev1", 0))
    sev2 = int(inc.get("sev2", 0))
    traceable = bool(inc.get("traceable_to_active_edge", True))
    ok = not (traceable and (sev1 > 0 or sev2 > 0))
    return ok, f"sev1={sev1}, sev2={sev2}, traceable_to_active_edge={traceable}"


CRITERIA = {
    "order_fill_integrity": check_order_fill_integrity,
    "slippage_distribution": check_slippage,
    "regime_hit_rate": check_regime_hit_rate,
    "incident_cleanliness": check_incident_cleanliness,
}


def evaluate(data: dict) -> dict:
    results: dict[str, dict] = {}
    for name, fn in CRITERIA.items():
        ok, detail = fn(data)
        results[name] = {"pass": ok, "detail": detail, "weight": WEIGHTS[name]}
    all_pass = all(r["pass"] for r in results.values())
    score = sum(r["weight"] for r in results.values() if r["pass"])
    if all_pass:
        recommendation = "PROMOTE: quarter is clean — one Hold-class strategy may enter evaluation (Himari triage + Craig approval; see docs/trading/promotion-rubric.md)"
    else:
        failed = ", ".join(n for n, r in results.items() if not r["pass"])
        recommendation = f"DO NOT PROMOTE: failed criteria: {failed}"
    return {"quarter": data.get("quarter", "?"), "criteria": results, "all_pass": all_pass, "score": score, "recommendation": recommendation}


def render(verdict: dict) -> str:
    lines = [
        f"Promotion clean-receipt validation — quarter {verdict['quarter']}",
        "=" * 60,
    ]
    for name, r in verdict["criteria"].items():
        status = "PASS" if r["pass"] else "FAIL"
        lines.append(f"[{status}] {name} (weight {r['weight']:.2f}) — {r['detail']}")
    lines.append("=" * 60)
    lines.append(f"weighted score: {verdict['score']:.2f} / 1.00")
    lines.append(f"recommendation: {verdict['recommendation']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quarter", required=True, help="quarter id, e.g. 2026Q4")
    parser.add_argument("--input", help="explicit path to quarter JSON")
    parser.add_argument("--json", action="store_true", help="emit machine-readable verdict")
    args = parser.parse_args(argv)
    data = load_quarter(args.quarter, args.input)
    verdict = evaluate(data)
    if args.json:
        print(json.dumps(verdict, indent=2))
    else:
        print(render(verdict))
    return 0 if verdict["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
