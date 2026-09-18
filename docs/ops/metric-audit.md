# Metric Audit — Standing Rule & Tool

> No metric may gate a decision until it has passed one independent audit.

This document captures the operating rule and the tool that enforces it. The
goal is simple: never trust an unaudited dashboard again.

## The rule

For any metric (win rate, drawdown, p95 latency, error rate, anything):

1. **Run an audit first.** Use `scripts/audit_metric.py` to independently
   recompute the value and diff it against the dashboard's claim.
2. **If the audit flags** (ratio > 2x — see below), the metric is **not allowed
   to drive any decision** until the divergence is investigated.
3. **A flagged audit auto-opens a `[FINDING]` card** on the workboard when run
   with `--open-finding`. This is durable evidence that the divergence was seen.
4. **Every audit row goes into `data/health/metric-audit-log.jsonl`** (an
   append-only log). Truncating this log is a Sev-2 incident — it's the
   forensic record of which metrics were ever checked.

## Threshold

The flag threshold is **ratio > 2.0**, where

    ratio = |claimed - actual| / max(|actual|, 1e-6)

The threshold was chosen so a 2x divergence between dashboard and ground truth
is treated as broken until proven otherwise. A 1.5x divergence is a yellow
flag you should investigate but not panic over. A 37.5x divergence — the 2026-
06-28 incident where a dashboard claimed 77% win rate and the truth was 2% —
is what this rule exists to catch.

Changing the threshold requires:
- Updating `DELTA_RATIO_THRESHOLD` in `scripts/audit_metric.py`.
- Updating this document.
- Re-running `pytest tests/test_audit_metric.py -q` and verifying the planted
  divergence fixture still flags.

## The 2026-06-28 incident (calibration)

A dashboard reported **0.77** win rate. The trade journal, recomputed
independently, showed **0.02**. The dashboard had been gating capital-allocation
decisions for weeks. The result: decisions were being made against a metric
that did not reflect reality, by a factor of ~37x.

`tests/test_audit_metric.py::test_planted_divergence_77_vs_2_is_flagged` is the
calibration fixture. It exists so that:

- A future change to the auditor that breaks detection will be caught by CI.
- The threshold can be retuned with a concrete, runnable witness to its
  intent.

If this test ever fails, the auditor is broken and dashboards must not be
trusted until it is fixed.

## How to run an audit

```bash
# Direct numeric values
python3 scripts/audit_metric.py \
    --metric win_rate \
    --claim 0.77 \
    --truth 0.02 \
    --open-finding

# Values read from files
python3 scripts/audit_metric.py \
    --metric sharpe \
    --claim-file reports/sharpe_dashboard.txt \
    --truth-file reports/sharpe_journal.txt \
    --open-finding

# Values produced by shell commands
python3 scripts/audit_metric.py \
    --metric pnl \
    --claim-shell 'jq .pnl dashboard.json' \
    --truth-shell 'python3 scripts/recompute_pnl.py trades.jsonl' \
    --open-finding
```

### What the script does

1. Resolves the `claimed` and `actual` values from exactly one of `--Xxx`,
   `--Xxx-file`, or `--Xxx-shell` per side.
2. Emits one JSONL line to stdout: `{metric, claimed, actual, delta, ratio,
   threshold, flagged, timestamp_utc}`.
3. Appends the same row to `--jsonl-log` (default `data/health/metric-audit-
   log.jsonl`). Use `--no-log` to skip the append (e.g. in dry-run previews).
4. If the audit flags and `--open-finding` is set, the script invokes
   `workboard_create` to open a `[FINDING]` card titled after the metric and
   the divergence magnitude. Failure of the workboard CLI is surfaced but does
   not block the row emission — the row is the durable receipt.

### Exit codes

- `0` — clean (delta within threshold).
- `1` — flagged (delta exceeds threshold). The JSONL row is still emitted.
- `2` — usage error (bad input, missing source, non-numeric value).

## Adoption

Wiring this tool into the metric-publishing pipeline is a separate workboard
card (filed on the same sprint). Until that card is closed, audits must be run
manually before any new metric is allowed to gate a decision.

## History

- **2026-06-28** — 77% vs 2% win-rate incident (calibration witness).
- **2026-08-31** — Tool v1 shipped under card `56276b4c`.
