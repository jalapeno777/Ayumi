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

## Cross-references

* card 080094ef-r1 (this card, initial build) — `e69ea6fb` + `8e003f41` on
  `tsubaki/080094ef-restart-counter12`
* card 7d3b535d — proactive-24h rotation provenance (the rotation path that
  our handler's clean exit serves)
* card a38b853d — `_check_signal_stats_uid` (the `sys_exit(2)` path)
* Rin REWORK verdict (comment b27b6a40) — the HIGH finding this r2 addresses

## Rollback

If the recorded-exit or journal path misfires, revert by checking out the
prior commit `8e003f41` and re-running the health loop. Both helpers
(`_record_last_exit`, `_read_journal_last_exit`) write nothing to
`data/forward_test_health.json` unless called from the existing
`write_forward_test_health_json` path; reverting the launcher restores
r1 behaviour.
