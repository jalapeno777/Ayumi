# Post-mortem — Card 16bb9977-05f3-4a87-b892-20b8f3cfb6df

## What
DH-003 (signal_stats.jsonl staleness) fired CRITICAL ~53h into a zero-signal
weekend because the writer is event-driven and only appends on signal events.
The check keyed on mtime alone and could not distinguish "no signals" (benign)
from "writer dead" (real failure).

## Change
`_ch_dh_signal_stats()` in scripts/daily_audit.py re-keyed on positive evidence:
1. `_recent_stats_fails()` — parses the most recent `stats_fails=` counter from
   [B5 Health] log lines (tail 20). `stats_fails > 0` → CRITICAL.
2. `_signals_since_last_write()` — forward_test_health.json carries a
   per-process `signals_generated` counter and `last_restart_at`. File mtime
   older than the restart with signals_generated > 0 means the engine observed
   signals this session with no corresponding write → CRITICAL
   (signals-without-writes).
3. No positive failure evidence → OK (weekend/closed or <24h stale), WARN only
   for >24h stale with market open and no evidence, with a "verify writer
   resumes" note. No CRITICAL on benign event-driven staleness.

## Verification
- Targeted probe only (HR4): `python3 -m pytest tests/test_daily_audit_dh003.py`
  → 8 passed (weekend 53h stale → OK; open-market zero-signal stale → not
  CRITICAL; stats_fails=3 → CRITICAL; signals-without-writes → CRITICAL;
  missing file → WARN escalated; fresh file → OK; helper detection logic;
  log parsing).
- `run_test_scope.sh` supports category scopes only (no per-file scope), so the
  single-file pytest invocation is the compliant targeted form. No full suite.
- Builder quality gate: PASS (8/8 checks) —
  data/ops/quality_gate_reports/20260918T045018.json.
- Backwards compatibility: DH-003 remains OK when the file is fresh; true
  failure paths now trip on positive evidence instead of mtime alone.

## BUILD-METADATA
- card_id: 16bb9977-05f3-4a87-b892-20b8f3cfb6df
- repo: /home/TacoPants/projects/Ayumi
- worktree: .worktrees/reina-16bb9977-dh003
- branch: reina/16bb9977-dh003
- commit: 3f99a60a8a2f963807750bf28a0ce2c2c6775657
- base: main (33bd1494)
- files: scripts/daily_audit.py (+120/-3), tests/test_daily_audit_dh003.py (+138 new)
- quality_gate: PASS 8/8 (20260918T045018.json)
- targeted_tests: 8 passed, tests/test_daily_audit_dh003.py
- builder: Reina (heartbeat build lane), 2026-09-18 04:50 UTC
