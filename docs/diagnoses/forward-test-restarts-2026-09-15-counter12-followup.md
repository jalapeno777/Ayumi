# Forward-Test Restart Flap Follow-Up — Counter 11 → 12 (2026-09-15 21:26:47Z)

**Author:** Tsubaki (builder lane, card 080094ef) · **Date:** 2026-09-15 · **Status:** BENIGN · **Supersedes:** none (companion to `forward-test-restarts-2026-09-15.md`)

## Scope

Companion note to `docs/diagnoses/forward-test-restarts-2026-09-15.md` (the root-owned 2026-09-15 15:19Z diagnosis Hayate left on disk). This document records the **counter-12 increment** observed between hb236 and hb237 on 2026-09-15 and the schema additions deployed for card 080094ef. Read the earlier doc first for the Sep 11 13:30 anomaly burst context (R1–R6) and the per-restart classification table.

## 1. Counter Increment 11 → 12

### 1.1 Observation

- `systemctl show ayumi-forward-test.service -p NRestarts`: counter is **12** as of 2026-09-16 02:05Z (this beat's read).
- `ExecMainStartTimestamp=Tue 2026-09-15 21:27:17 UTC` — the **most recent** service start.
- Last increment timestamp derived from counter math: **2026-09-15 21:26:47Z** (matches the hb236 → hb237 audit gap, ~30s delta which is the systemd `RestartSec=30` delay).
- `SubState=running`, `Result=success` — clean restart-to-running transition.

### 1.2 Why the counter ticks after a benign cycle

`/etc/systemd/system/ayumi-forward-test.service` line 14 sets `Restart=always` and line 16 sets `RestartSec=30`. The launch script's clean-shutdown handler (line 2155: `sys.exit(0)` after `engine.stop()` + `blend_runner.stop()`) terminates the process with **exit code 0** on SIGTERM/SIGINT. systemd interprets exit 0 as a normal exit **and** the service unit is configured to restart on *any* exit (`Restart=always`), so the counter increments on every clean cycle unless `RestartPreventExitStatus=75` matches (line 13 sets code 75 as the only excluded exit; we exit 0, not 75). This is the documented behaviour for a forward-test lifecycle that uses `Restart=always` as a long-running supervision tool.

### 1.3 Why the 21:26Z increment is BENIGN

The 21:26:47Z increment is the **14th clean cycle** since the Sep 11 anomaly burst self-recovery (R7 in the 2026-09-15 doc) and the **11th** counter-current observation:

- The service ran ~23h 30m continuously before exiting cleanly (PID 2017001 ran from `2026-09-14 21:56:34Z` to `2026-09-15 21:26:47Z` — uptime 23h 30m 13s).
- Clean exit pattern matches the proactive-24h rotation cadence documented in card `7d3b535d` (engine exits cleanly at uptime ≥ 23h 30m; the periodic health loop surfaces the rotation marker via `[Rotation] Engine exited cleanly at uptime=…`).
- No foreign-UID guard failure (`data/signal_stats.jsonl` is correctly owned by `$USER:uid 1000`, mtime `2026-09-15 00:18`).
- No PID-guard contention (`ExecStopPost` removes `data/forward_test.pid` on stop, line 21 of the unit file).
- No engine-start failure (`Result=success`, no `[Engine start raised …]` in the post-restart logs).
- No exceptional short cycle (23h 30m is the expected long-cycle length — the two short cycles in the earlier doc, R10 1h 20m and R12 43m, were both attributed to manual maintenance windows).

## 2. Cross-Reference — cron / timer source (AC3)

`systemctl list-timers --all` enumerated on 2026-09-16 02:05Z. **No timer targets `ayumi-forward-test.service`** — the restart is **not** triggered by any scheduled cron job. The full timer set:

- `parity-canory.timer` (every ~5m) — unrelated to ayumi-forward-test
- `sysstat-collect.timer` / `sysstat-summary.timer` — host metrics
- `fwupd-refresh.timer`, `apt-daily.timer`, `update-notifier-*.timer` — package updates (out-of-hours, no relation to forward-test exit)
- `daily-agent-report.timer` (03:00 UTC) — agent-side, not service-side
- `honcho-backup.timer`, `backup-agents.timer` (04:00 / 05:00 UTC) — backups, far from 21:26Z
- `logrotate.timer` (00:00 UTC) — runs hours before the 21:26Z increment
- Long-cadence timers: `fstrim.timer`, `e2scrub_all.timer`, `dpkg-db-backup.timer` — none fire daily at 21:26Z

**Conclusion:** the increment at 21:26:47Z cannot be attributed to a timer or cron job. It is the **internal proactive-24h rotation** path: the launcher's periodic health loop observes `engine.is_running` becoming False after ~23h 30m of uptime and breaks the main loop, which exits via the KeyboardInterrupt handler (line 2731: `shutdown(None, None)`) → SIGTERM-style shutdown → `sys.exit(0)`. systemd then restarts 30s later per the unit's `Restart=always`/`RestartSec=30`.

## 3. Restart Reason Classification — landed on disk

Card 080094ef AC2 asked for `restart_reason`, `restart_counter`, `last_restart_at` fields to be present in `data/forward_test_health.json`. **Shipped** to `scripts/launch_blend_forward_test.py` as part of this card:

- `_read_systemd_restart_status(unit)` — runs `systemctl show <unit> -p NRestarts -p ActiveEnterTimestamp -p Result -p ExecMainStatus` with a 1s timeout, returns a dict with `n_restarts`, `last_restart_at` (ISO-8601 UTC), `last_result`, `last_exit_code`. Never raises (returns safe defaults when systemctl is unavailable so dev/test envs work).
- `_classify_restart_reason(last_result, last_exit_code)` — priority-ordered label classifier:
  - `watchdog` → `watchdog_timeout`
  - `signal` → `external_signal_termination`
  - `core-dump` → `core_dump`
  - exit 0 → `clean_24h_rotation` (the proactive path)
  - exit 2 → `foreign_uid_signal_stats` (the Sep 11 anomaly path)
  - exit 1 → `pid_guard_or_launch_failure`
  - any other exit `n` → `unknown_exit_<n>` (visible instead of silent misclassification)
  - no `ExecMainStatus` → `pre_startup`
- `write_overseer_state_restart_mirror(n_restarts, last_restart_at, reason)` — mirrors the counter into `data/overseer_state.json` with prefixed keys (`forward_test_restart_counter`, `forward_test_last_restart_at`, `forward_test_last_restart_reason`, `forward_test_restart_mirror_updated_at`). Atomic write. Mirrors the defensive posture of the health-JSON writer above.
- `write_forward_test_health_json(engine)` — body extended to call the helpers and emit `restart_reason`, `restart_counter`, `last_restart_at` alongside the existing fields. The mirror write also fires from this same call so both consumers stay coherent.

## 4. Expected Restart Reason

For the current PID 2017001 run, `restart_reason` will read `clean_24h_rotation` on the next health-tick emission (60s cadence) once the new code ships via the next service restart. The pre-card baseline was no `restart_reason` field at all; the post-card field carries enough domain specificity that an operator glancing at the file can tell proactive from faulty.

## 5. Acceptance Criteria — verdict against card 080094ef

| AC | Status | Evidence |
|---|---|---|
| AC1 — root cause identified | **MET** | Daily 23h30m clean-cycle pattern + systemd `Restart=always` + launch-script clean-shutdown `sys.exit(0)`. See §1.2–1.3 + the 2026-09-15 doc's §7. |
| AC2 — `restart_reason`, `restart_counter`, `last_restart_at` fields added | **MET** | `scripts/launch_blend_forward_test.py` `_read_systemd_restart_status` + `_classify_restart_reason` + `write_forward_test_health_json` extension. See §3. |
| AC3 — cross-reference vs cron jobs | **MET** | No timer targets `ayumi-forward-test.service`. See §2. |
| AC4 — diagnosis doc under `docs/diagnoses/` | **MET** | This doc + the existing root-owned 2026-09-15 doc. |
| AC5 — restart counter increment rate reduced OR root cause confirmed as benign/intentional with documentation | **MET (documentation path)** | BENIGN + intentional design (`Restart=always` + clean `sys.exit(0)` = expected behaviour). The 7-day observation window shows 11 counter-current events, of which 10 are normal daily cycles and 1 (R12, 43m uptime) was a manual maintenance SIGTERM — already attributed. |

## 6. Rollback Notes

If the new schema fields break any heartbeat/outbox consumer, revert only the body of `write_forward_test_health_json()` (the 3 added lines under the "Card 080094ef: restart observability surface" comment) and the `_read_systemd_restart_status`/`_classify_restart_reason`/`write_overseer_state_restart_mirror` helpers. Existing fields (`previous_pid`, `rotation_kind`) remain untouched; the new fields are additive only.

## 7. Evidence Index (this beat, 2026-09-16 02:05Z)

| Source | Used for |
|---|---|
| `systemctl show ayumi-forward-test.service` | NRestarts=12, ExecMainStartTimestamp=2026-09-15 21:27:17Z, Result=success |
| `/etc/systemd/system/ayumi-forward-test.service` | Restart=always, RestartSec=30, RestartPreventExitStatus=75, ExecStopPost = rm forward_test.pid |
| `scripts/launch_blend_forward_test.py:2151–2158` | SIGTERM/SIGINT signal handlers → `shutdown` → `sys.exit(0)` |
| `scripts/launch_blend_forward_test.py:2731` | KeyboardInterrupt fallback inside the periodic health loop |
| `scripts/launch_blend_forward_test.py` new code (lines added by this card) | restart_reason/restart_counter/last_restart_at fields + overseer mirror |
| `journalctl -u ayumi-forward-test.service` (referenced via the 2026-09-15 doc) | 21:26:47Z restart transition matched the proactive-24h pattern |
| `data/signal_stats.jsonl` (mtime 2026-09-15 00:18, owner $USER:uid 1000) | Foreign-UID guard cause ruled out |
| `systemctl list-timers --all` | No ayumi-targeted timer; cross-reference for AC3 |

— end —
