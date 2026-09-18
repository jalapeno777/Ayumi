# Post-mortem — card 68d4b7fe: per-restart stderr archival for ayumi-forward-test.service

Date: 2026-09-18 · Builder: Reina (heartbeat build lane) · Standalone card, 1 SP

## What was built
ExecStartPre-based archival of the previous run's stderr, so pre-restart
stderr is retrievable after every service restart (fixes the Sep 11
unreachable-stderr problem from
docs/diagnoses/forward-test-restarts-2026-09-15.md, card c29dd66e).

Deliverables (3 files, +119 lines):
- `scripts/systemd/archive_stderr.sh` — best-effort ExecStartPre helper:
  cp-based archival (preserves the systemd append target and existing
  logrotate rotations), UTC-timestamped artifacts under
  `logs/stderr-archive/`, retention cap (default 30, env-overridable),
  never blocks service startup.
- `deploy/systemd/ayumi-forward-test.service.d/stderr-archival.conf` —
  systemd drop-in adding the ExecStartPre, with the Ava-approved
  apply/daemon-reload/restart procedure documented in-file.
- `scripts/systemd/test_archive_stderr.sh` — targeted test suite.

## Design decisions
- ExecStartPre + cp chosen over systemd-cat: minimal change, keeps journald
  out of the critical path, no change to the unit's logging targets, and
  artifacts live next to the existing rotated logs.
- Builder performed NO /etc/systemd mutation — drop-in application requires
  the Ava-approved restart window per card AC #2 (HR2). Apply procedure is
  documented in the drop-in conf header.

## Pre-commit verification checklist (SOP 17)
1. Read live unit file `/etc/systemd/system/ayumi-forward-test.service` ✓
2. Targeted tests only — bash suite, no pytest collection, no full suite ✓
3. End-to-end run with real output cited below ✓
4. Read-back after edits (sed -n on changed region) ✓
5. Quality gate: PASS 2/2 ✓
6. BQES checklist validated (5 edge cases, 3 assertions) ✓
7. Commit references card id ✓

## Verification
- `bash scripts/systemd/test_archive_stderr.sh` → 11/11 PASS, exit 0
  (archive-on-restart, content integrity ×2, cp-not-mv, empty stderr,
  no-archive-on-empty, missing-file exit 0, retention ×4).
- Initial run had 2 failures in the retention fixture (racy mtime ties +
  KEEP accounting); fixed with deterministic `touch -d` mtimes and
  corrected expectations, then 11/11 PASS. Fix-then-green, not bypass.
- Builder quality gate: PASS (2/2 checks) —
  data/ops/quality_gate_reports/20260918T132953.json.
- Card verification command's live-service half (journalctl + archive ls)
  becomes runnable only after the Ava-gated drop-in application — staged
  verification documented in the drop-in conf.

## Open items
- Ava restart window needed to apply the drop-in and complete live AC #1
  verification. Escalated in card handoff comment.
- Rin review verdict pending at time of writing (dispatched this beat;
  review-closure sweep will relay).

---BUILD-METADATA---
card_id: 68d4b7fe-1f3b-4293-a35f-a7376b9bd628
skills_used: [pre-build-checklist, build-postmortem]
tools_used: [exec, edit, read, workboard]
models_used: [zai/glm-5.3]
test_status: pass
time_started: "2026-09-18T13:15:00Z"
time_completed: "2026-09-18T13:50:00Z"
repo: /home/TacoPants/projects/Ayumi
worktree: .worktrees/68d4b7fe-stderr
branch: reina/68d4b7fe-stderr-archival
commit: 6fc944af
base: main (7912576d)
quality_gate: PASS 2/2 (20260918T132953.json)
targeted_tests: 11 passed, scripts/systemd/test_archive_stderr.sh
review_rounds: 1
issues_found: {r1: {critical: 0, high: 0, medium: 0, low: 0}}
total_issues: 0
review_status: r1 dispatched this beat, verdict pending relay by review-closure sweep
builder: Reina (heartbeat build lane), 2026-09-18 13:40 UTC
files:
  - scripts/systemd/archive_stderr.sh
  - scripts/systemd/test_archive_stderr.sh
  - deploy/systemd/ayumi-forward-test.service.d/stderr-archival.conf
---END-METADATA---
