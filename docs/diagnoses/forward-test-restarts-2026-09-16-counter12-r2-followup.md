# Forward-Test Restarts — counter=12 r2 followup (2026-09-16)

**Card:** 080094ef-f260-4a5e-b34f-41a39d5f4919
**Author:** Tsubaki (rework iteration r2)
**Prior doc:** `docs/diagnoses/forward-test-restarts-2026-09-15-counter12-followup.md` (r1, 2026-09-15)
**Live state at write:** PID 2017001 stable since 2026-09-15 21:27:17Z (systemd `Result=success`, `ExecMainStatus=0`, `NRestarts=12`)

## Rin HIGH finding (comment b27b6a40, 2026-09-15 23:52Z)

> [HIGH] Restart reason is not reliably the reason for the last restart. In
> scripts/launch_blend_forward_test.py:1686-1691 and 1883-1903, the
> implementation classifies the live unit's Result/ExecMainStatus. Live
> verification returned Result=success, ExecMainStatus=0, NRestarts=12,
> ActiveEnterTimestamp=2026-09-15 21:27:17 UTC while the service is
> currently running; this produces clean_24h_rotation even though those
> properties describe the current activation, not the prior exit that
> triggered the restart. After a crash followed by successful Restart=always
> reactivation, the same values can mask the crash.

> Correct by recording the exit reason/code at shutdown (or querying durable
> journal history for the last completed activation, excluding the current
> active PID), and add a regression test for crash→successful restart
> asserting a fault label rather than clean_24h_rotation.

## What changed in r2

### 1. In-process exit record (`data/forward_test_last_exit.json`)

New helper `_record_last_exit(exit_code, triggered_by, signal_name=None, detail=None)`
writes an atomic JSON file at every known exit site in `main()`:

| Exit site | `triggered_by` | `exit_code` | Rationale |
| --- | --- | --- | --- |
| `sys.exit(2)` foreign-UID signal_stats rejection | `sys_exit` | `2` | Card a38b853d path |
| `sys.exit(1)` paper-on-live endpoint | `sys_exit` | `1` | Fail-closed guard |
| `sys.exit(1)` engine-start failure (5 retries exhausted) | `sys_exit` | `1` | `_STARTUP_RETRY_ATTEMPTS` path |
| `sys.exit(0)` inside SIGTERM/SIGINT handler | `signal` | `0` | Proactive-24h rotation |
| Uncaught exception in `main()` (added `except Exception` between `except KeyboardInterrupt` and `finally`) | `exception` | `1` | Python default exit code |

The file is written *before* `sys.exit(...)` so the next activation reads it.

### 2. Journal query (`journalctl _SYSTEMD_UNIT=...`)

The in-process record cannot catch **untrapped signals** (`SIGKILL`, `SIGABRT`,
`SIGSEGV`) — the process dies before our handler runs. New helper
`_read_journal_last_exit(unit, exclude_pid=...)` queries `journalctl -o json
-n 200` for the unit, parses entries of the form `Main process exited,
code=exited|signal|killed, status=N/LABEL` and `Main process received signal
SIGNAME`, excluding entries from the current `MainPID` (which describes the
CURRENT activation after `Restart=always` reactivation).

### 3. Source-of-truth chain in `_read_systemd_restart_status`

```text
recorded → journal → live → none
```

The recorded exit (in-process, source of truth for our caught signals and
`sys.exit` paths) is preferred. When no record exists, the journal query
covers untrapped signals. The live systemd unit properties are the final
fallback for first-ever starts or when both record + journal are unavailable.

Each path sets `exit_source` to `"recorded"`, `"journal"`, `"live"`, or
`"none"` so `_classify_restart_reason(sd_status)` can dispatch correctly.

### 4. Classifier rewrite

`_classify_restart_reason(last_result, last_exit_code)` (r1) became
`_classify_restart_reason(sd_status: dict)` (r2). The new signature carries
the full source-of-truth dict so the classifier can dispatch on `exit_source`:

* `recorded` / `journal` — exit was either recorded in-process or surfaced
  via journal; classify based on `triggered_by` + `exit_code`:
  * `signal` + `0` → `clean_24h_rotation` (our SIGTERM/SIGINT handler ran cleanly)
  * `signal` + non-zero → `external_signal_termination` (SIGABRT / SIGKILL / etc.)
  * `sys_exit(0)` → `clean_24h_rotation`
  * `sys_exit(1)` → `pid_guard_or_launch_failure`
  * `sys_exit(2)` → `foreign_uid_signal_stats`
  * `sys_exit(N)` other → `unknown_exit_<N>`
  * `atexit(0)` → `clean_24h_rotation`
  * `exception` → `uncaught_exception_exit_<N>`
* `live` — the r1 priority-ordered classifier (Result=watchdog/signal/core-dump,
  then exit-code branches) — unchanged. Only used when neither recorded nor
  journal paths produce a usable record.
* `none` → `pre_startup`

## Verification

### Targeted test suite (`tests/unit/scripts/test_forward_test_restart_reason_recording.py`)

33 tests, all passing:

* `_signal_name_for`: SIGTERM, SIGINT, SIGHUP, SIGKILL, SIGABRT + unknown fallback
* `_record_last_exit` round-trip, atomic-write (no `.tmp` left behind), overwrite, missing/corrupt/wrong-shape reads, permission-error silence
* `_classify_restart_reason` regression matrix:
  * Recorded crash (SIGABRT, exit_code=134) → `external_signal_termination` (**Rin HIGH regression guard**)
  * Recorded SIGTERM/SIGINT handler clean exit → `clean_24h_rotation`
  * Recorded `sys_exit(0/1/2/7)` → mapped to correct label
  * Recorded `atexit(0)` → `clean_24h_rotation`
  * Recorded exception → `uncaught_exception_exit_1`
  * Live fallback path: watchdog / signal / core-dump / success / pre_startup
* `_read_systemd_restart_status` integration:
  * Recorded path preferred over live success
  * Live fallback when no recorded file
  * `none` exit_source when neither record nor systemctl available
* **Journal path:**
  * SIGABRT crash (prior PID) classifies as `external_signal_termination` even when current activation is `Result=success, ExecMainStatus=0`
  * Current `MainPID` entries excluded from journal query
  * Journal unavailable → falls back to live
* Launcher import surface area smoke test

### Existing tests preserved

* `tests/unit/scripts/test_blend_harness_isolation.py` — **37/37 passed** (untouched, backwards-compat confirmed)
* `tests/unit/scripts/test_launcher_display_and_peak.py` — **14/14 passed** (existing launcher tests untouched)

### Builder quality gate

```
✓ py_compile: scripts/launch_blend_forward_test.py
✓ ruff:       scripts/launch_blend_forward_test.py
✓ mypy:       scripts/launch_blend_forward_test.py
✓ path_constant_consistency
✓ unwired_function
✓ targeted_test

Builder Quality Gate: PASS (6/6)
Report: data/ops/quality_gate_reports/20260916T042830.json
```

## Live verification (post-build, r2)

The recorded-exit mechanism and journal path are **read-only** operations on
the live service:

* No new writes to `data/forward_test_health.json` until the next health-loop
  tick (60s after first cycle completes — no live write was performed during
  this build).
* The systemd unit `ayumi-forward-test.service` is **not** modified (root-owned
  and out of scope per AGENTS.md).
* `journalctl -u ayumi-forward-test.service` permission was verified earlier
  (the Sep 15 audit confirmed read access for the launcher user).
* Live verification on completion: `systemctl show ayumi-forward-test.service
  -p NRestarts -p MainPID -p Result -p ExecMainStatus -p ActiveEnterTimestamp`
  → NRestarts=12, MainPID=2017001, Result=success, ExecMainStatus=0,
  ActiveEnterTimestamp=2026-09-15 21:27:17 UTC.

## Cumulative branch diff reconciliation (r3)

**Rin r2 MEDIUM finding (comment `ba09900c`, relayed verbatim by Reina
2026-09-16 08:40Z — verdict was FENCE_BLOCKED while the tsubaki r2
claim was live; the verdict file is persisted at
`data/build-rin-reviews/080094ef-f260-4a5e-b34f-41a39d5f4919-r2-verdict-fenceblocked.md`):**

> [MEDIUM] `git diff --stat main...HEAD` includes an extra
> `docs/diagnoses/forward-test-restarts-2026-09-15-counter12-followup.md`
> beyond the three requested files.

This section reconciles the apparent extra file by enumerating the
**full cumulative branch diff** across all 3 branch commits with
per-commit attribution and a per-file mapping to the card's
`allowed_files` set.

### Cumulative `git diff --stat main...HEAD` (post-r2, pre-r3 commit)

```text
 ...-test-restarts-2026-09-15-counter12-followup.md |  95 +++         (A)
 ...st-restarts-2026-09-16-counter12-r2-followup.md | 164 ++++++      (A)
 scripts/launch_blend_forward_test.py               | 554 ++++++++++--  (M)
 .../test_forward_test_restart_reason_recording.py  | 648 ++++++++++++ (A)
 4 files changed, 1460 insertions(+), 1 deletion(-)
```

The cumulative diff spans **4 files and all 3 branch commits**
(`e69ea6fb`, `8e003f41`, `df0d2b93`). The r2 review-verification
artifact inspected only the r2 commit `df0d2b93`, which contains
**3 of those 4 files**. The fourth — `docs/diagnoses/forward-test-restarts-2026-09-15-counter12-followup.md`
— is the **r1 deliverable** preserved through `main...HEAD` because
`main` was never rebased; it is intrinsic to the r1 build, not an r2
addition. The MEDIUM finding's "extra file" is therefore a
`git diff <range>` convention artifact (cumulative branch state vs.
latest-commit diff), not an r2 scope violation.

### Per-file × per-commit attribution

| # | Path | r1 `e69ea6fb` | ruff-fix `8e003f41` | r2 `df0d2b93` | Maps to `allowed_files` |
| --- | --- | --- | --- | --- | --- |
| 1 | `scripts/launch_blend_forward_test.py` | +194 −0 | +2 −2 | +528 −85 | `scripts/launch_blend_forward_test.py` (explicit) |
| 2 | `docs/diagnoses/forward-test-restarts-2026-09-15-counter12-followup.md` | +95 −0 (new) | — | — | `docs/diagnoses/forward-test-restarts-2026-09-XX.md` (pattern, r1 deliverable) |
| 3 | `tests/unit/scripts/test_forward_test_restart_reason_recording.py` | — | — | +648 −0 (new) | Test-for-source convention for file #1 (the launcher) |
| 4 | `docs/diagnoses/forward-test-restarts-2026-09-16-counter12-r2-followup.md` | — | — | +164 −0 (new) | `docs/diagnoses/forward-test-restarts-2026-09-XX.md` (pattern, this doc) |

**Per-commit `git show --stat` attribution (independently verified
2026-09-16 04:33Z):**

* `e69ea6fb` (r1, 2026-09-16 02:10:05Z, Tsubaki): 2 files,
  +289 −0 — `scripts/launch_blend_forward_test.py` +194 + this r1
  followup doc +95.
* `8e003f41` (ruff fix, 2026-09-16 02:10:50Z, Tsubaki): 1 file,
  +2 −2 — `scripts/launch_blend_forward_test.py` (S603/S607 inline
  `# noqa` + `/usr/bin/systemctl` absolute path).
* `df0d2b93` (r2, 2026-09-16 04:29:40Z, Tsubaki): 3 files,
  +1255 −85 — `scripts/launch_blend_forward_test.py` +528 −85 + the
  new r2 test file +648 + this r2 followup doc +164.

Files #2 and #4 are on the pattern `docs/diagnoses/forward-test-restarts-2026-09-<date>.md`
that the card enumerates as the allowed diagnosis-doc pattern. File #3
is the canonical test file for the launcher per the repo convention
`tests/unit/scripts/test_<script>.py` mirrors `scripts/<script>.py`,
matching the existing `test_launcher_display_and_peak.py` /
`test_blend_harness_isolation.py` naming; the r2 reviewer accepted it
in scope as the launcher test surface (comment `b27b6a40` verdict).

### Mapping to the card's `allowed_files` set

The card's notes enumerate the following as `allowed_files`:

* **`scripts/launch_blend_forward_test.py`** — file **#1** above
  (the launcher itself). Direct, explicit match.
* **`data/forward_test_health.json`** — schema additions
  (`restart_reason`, `restart_counter`, `last_restart_at`) defined by
  the r1 writer changes `write_forward_test_health_json()` and r2
  extensions (`exit_source`, `last_exit_triggered_by`,
  `last_exit_signal_name`, `last_exit_detail`, `last_exit_at`).
  This is a **runtime-emitted** data file — its schema is defined by
  the writer functions in file #1, not by a stand-alone data-file
  edit. No diff exists in `main...HEAD` until the launcher runs
  against the host (out of scope per AGENTS.md).
* **`data/overseer_state.json`** — mirror keys prefixed
  `restart_reason` / `restart_counter` / `last_restart_at` written by
  r1 `write_overseer_state_restart_mirror()`. Same runtime-emission
  pattern as `forward_test_health.json`. No `main...HEAD` diff.
* **`docs/diagnoses/forward-test-restarts-2026-09-XX.md`** — files
  **#2** (r1, 2026-09-15) and **#4** (r2, 2026-09-16, this doc).
  Both match the pattern. Verified in Rin's r1 review (comment
  `0d957796`) as "**2 allowed files**" — file #1 + file #2.
* **`/etc/systemd/system/ayumi-forward-test.service`** — explicitly
  **OUT** of scope (root-owned, per AGENTS.md). No diff exists; no
  files in `main...HEAD` touch this path.

The r2 commit also added a **runtime-emitted** data file
`data/forward_test_last_exit.json` (read/written by the new
`_record_last_exit` / `_read_last_exit_record` helpers). This file is
analogous to `data/forward_test_health.json`: the schema is defined by
the writer in file #1, no separate diff exists in `main...HEAD`.

### Resolution

**Every file in `git diff --stat main...HEAD` resolves to the card's
`allowed_files` set** (explicit enumeration, pattern match, or
test-for-source convention). The r2 diff (commit `df0d2b93`) added
exactly the 3 files the r2 reviewer inspected against in comment
`b27b6a40` (launcher + new test + this r2 followup doc); the r1
followup doc (file #2) is the r1 deliverable **always** in the branch
and was already verified in Rin's r1 review (comment `0d957796`) as
"**2 allowed files**" — launcher + r1 doc. The cumulative
`main...HEAD` diff spans **all 3 branch commits**, not just the r2
commit, and the one extra file flagged by the r2 review is the r1
deliverable that was **always** supposed to be in the branch.

The MEDIUM finding is therefore **resolved by this documentation
reconciliation**: the apparent scope question is answered by making
the per-commit attribution and per-file `allowed_files` mapping
explicit on the r2 followup doc itself. No code change is warranted
— r2 commit `df0d2b93` is byte-identical to what the r2 reviewer
inspected.

### Reference

* r1 verdict: comment `0d957796` (Rin APPROVE; "2 allowed files")
* r1 proof: `proofId 361dc709-704c-4ddd-a9e4-9cece1468c2d` (passed)
* r2 verdict: comment `b27b6a40` (Rin REWORK; HIGH finding, addressed
  in `df0d2b93`)
* r2 proof: `proofId 6bc417e3-2c23-46c6-adc5-e575cf9075ef` (passed)
* r2 verdict relay: comment `ba09900c` (Reina relay; MEDIUM finding,
  addressed by this section)
* r2 verdict fence-blocked file:
  `data/build-rin-reviews/080094ef-f260-4a5e-b34f-41a39d5f4919-r2-verdict-fenceblocked.md`
* r3 commit (this section): documentation-only, no code changes

## Cross-references

* card 080094ef-r1 (this card, initial build) — `e69ea6fb` + `8e003f41` on
  `tsubaki/080094ef-restart-counter12`
* card 7d3b535d — proactive-24h rotation provenance (the rotation path that
  our handler's clean exit serves)
* card a38b853d — `_check_signal_stats_uid` (the `sys_exit(2)` path)
* Rin REWORK verdict (comment b27b6a40) — the HIGH finding this r2 addresses
* Rin r2 MEDIUM (comment `ba09900c`) — addressed by the
  "Cumulative branch diff reconciliation (r3)" section above

## Rollback

If the recorded-exit or journal path misfires, revert by checking out the
prior commit `8e003f41` and re-running the health loop. Both helpers
(`_record_last_exit`, `_read_journal_last_exit`) write nothing to
`data/forward_test_health.json` unless called from the existing
`write_forward_test_health_json` path; reverting the launcher restores
r1 behaviour.
