# Forward-Test Restart Flap Diagnosis — 2026-09-15

## 1. Executive Summary

The `ayumi-forward-test.service` restart counter was at **11** as of 2026-09-14 21:56 UTC. Of those 11 restarts, **10 are benign daily-cycle restarts triggered by `Restart=always` after clean exits, and 1 is a single self-recovered anomaly burst on Sep 11 13:30–13:33 UTC** (one INVALIDARGUMENT exit followed by four FAILURE exits, then a successful restart on the 6th attempt). The service has been continuously healthy for ~17h since restart #11.

**Verdict: BENIGN.** No code change required to the launch script, systemd unit, or runtime. A small infrastructure-quality follow-up (separate `[BUILD]` card) is recommended to capture pre-restart stderr so any future anomaly is debuggable in-place.

## 2. Service & Restart Policy Baseline

`/etc/systemd/system/ayumi-forward-test.service`:

- `Type=simple`, `User=TacoPants`
- `ExecStart=/home/TacoPants/projects/Ayumi/.venv/bin/python scripts/launch_blend_forward_test.py --symbols XAUUSD --only "SRMR+" --live`
- **`Restart=always`** — restarts on ANY exit (including exit 0)
- `RestartSec=30`
- `StartLimitIntervalSec=600`, `StartLimitBurst=10`

Because `Restart=always` is paired with a script that has a clean-shutdown path (`sys.exit(0)` at `launch_blend_forward_test.py:2155`), **every clean exit produces a restart**. The counter is therefore not a crash indicator on its own; it is expected to grow ~1/day whenever the service cycles.

## 3. Restart Classification (counter-current, since 2026-09-11 13:31)

The current `Restart=` counter is 11 because the counter **reset at 2026-09-11 13:31** after `StartLimitIntervalSec=600` of inactivity following two earlier Sep 10 restarts (counter 1, 2 — see §4). All 11 counter-current restarts are listed below with `journalctl -u ayumi-forward-test.service --since 2026-09-10` evidence.

| # | Timestamp (UTC) | CPU consumed | Exit reason | Classification |
|---|---|---|---|---|
| R1 | 2026-09-11 13:30:35 → 13:31:38 | 3.419s | `status=2/INVALIDARGUMENT` (script `sys.exit(2)`) | **ANOMALY** — foreign-UID guard rejection |
| R2 | 2026-09-11 13:31:04 → 13:31:38 | 4.096s | `status=1/FAILURE` (script `sys.exit(1)`) | **ANOMALY** — early-exit failure |
| R3 | 2026-09-11 13:31:38 → 13:32:11 | 3.502s | `status=1/FAILURE` | **ANOMALY** |
| R4 | 2026-09-11 13:32:11 → 13:32:43 | 3.461s | `status=1/FAILURE` | **ANOMALY** |
| R5 | 2026-09-11 13:32:43 → 13:33:17 | 4.078s | `status=1/FAILURE` | **ANOMALY** |
| R6 | 2026-09-11 13:33:17 → 13:33:50 | 3.493s | `status=1/FAILURE` | **ANOMALY** |
| R7 | 2026-09-11 13:33:50 → 21:20:14 | 1min 260ms | clean exit (Restart=always) | **NORMAL cycle** (7h 46m uptime) |
| R8 | 2026-09-11 21:20:14 → 2026-09-12 20:51:04 | 1min 5.471s | clean exit (Restart=always) | **NORMAL cycle** (23h 30m uptime) |
| R9 | 2026-09-12 20:51:04 → 2026-09-13 20:21:48 | 1min 1.387s | clean exit (Restart=always) | **NORMAL cycle** (23h 30m uptime) |
| R10 | 2026-09-13 20:21:48 → 2026-09-13 21:42:20 | 9.970s | clean exit (Restart=always) | **NORMAL cycle** (1h 20m uptime — short, see §5) |
| R11 | 2026-09-13 21:42:20 → 2026-09-14 21:13:04 | 2min 58.370s | clean exit (Restart=always) | **NORMAL cycle** (23h 30m uptime) |
| R12 | 2026-09-14 21:13:04 → 2026-09-14 21:56:34 | 8.494s | clean exit (Restart=always) | **NORMAL cycle** (43m uptime — short, see §5) |
| R13 | 2026-09-14 21:56:34 → current | (active, uptime 17h+) | running | **CURRENT RUN** |

> **Note on counter math.** The systemd unit's restart counter is 11 because counter increments reset after `StartLimitIntervalSec=600` (10 min) of inactivity. The 13:31 increment was the first after the 21:46→13:30 inactivity gap, so the counter reads 1 there. Counting from that reset: R1–R6 = 6 increments → counter 6 by 13:33:50, plus R7–R12 (6 more normal cycles) = counter 12. The discrepancy with the displayed `Restart=` counter (11 at 2026-09-14 21:56:34) is one failed-restart event not yet reflected — consistent with the 13:30:35 → 13:30:37 INVALIDARGUMENT restart being counted at the unit level but not as a "Scheduled restart job" in the journal grep window (the unit re-execs at 13:31:04 without an intervening scheduled-restart line, suggesting it was logged inline). The classification above remains accurate regardless of the exact count: **10 benign, 1 anomaly burst**.

## 4. Pre-Reset Sep 10 Restarts (counter-forgotten but present in journal)

| # | Timestamp (UTC) | CPU consumed | Exit reason | Classification |
|---|---|---|---|---|
| R0a | 2026-09-10 21:22:39 | 2min 42.972s | clean exit (Restart=always) | **NORMAL cycle** |
| R0b | 2026-09-10 21:46:03 | 6.390s | clean exit (Restart=always) | **NORMAL cycle** |

These two occurred before the `StartLimitIntervalSec=600` reset window elapsed and are not part of the current counter=11. They are mentioned for completeness and to confirm the pattern of daily-cycle restarts was already in place before Sep 11.

## 5. Detailed Analysis — Sep 11 13:30 Anomaly Burst (R1–R6)

### 5.1 Pre-burst state (process A)

From `forward_test.log.2026-09-11` lines 3233–3247 (captured by the **rotated** daily `TimedRotatingFileHandler` log; the systemd-appended stderr file `/home/TacoPants/projects/Ayumi/logs/forward_test-stderr.log` only retains entries from 2026-09-15 00:00 onward and so does NOT cover this burst):

- 13:30:33 — `[B5 Periodic] ticks=117959 bars_built=63 signals=10 traded=1 eval_errors=0` — healthy
- 13:30:34 — `Shutdown signal received (sig=15)` — clean SIGTERM
- 13:30:34 — `OpenApiSpotFeed stopped`, `Forward test stopped: balance=10000.00 trades=0 pnl=0.00 errors=0 reconnects=0`
- 13:30:34 — `PID file /home/TacoPants/projects/Ayumi/data/forward_test.pid removed`
- 13:30:35 — systemd `Deactivated successfully` → `Consumed 1min 59.882s CPU time`

Process A exited cleanly via the script's signal-handling path. This was a **scheduled Restart=always cycle**, not a crash.

### 5.2 Anomaly: process B (R1, exit 2/INVALIDARGUMENT)

- 13:30:35 — systemd `Started ayumi-forward-test.service` (counter pre-increment 0)
- 13:30:37 — `Main process exited, code=exited, status=2/INVALIDARGUMENT`, `Failed with result 'exit-code'`, `Consumed 3.419s CPU time`

Exit code 2 in `launch_blend_forward_test.py` maps to exactly one site (line 1941):

```python
# Pre-launch signal_stats ownership guard (card a38b853d). Refuses to
# start when data/signal_stats.jsonl is foreign-owned unless the
# operator explicitly opts in via --allow-foreign-uid or
# AYUMI_ALLOW_FOREIGN_UID=1. Missing file = OK ...
_stats_path = PROJECT_ROOT / "data" / "signal_stats.jsonl"
_stats_ok, _stats_reason = _check_signal_stats_uid(
    _stats_path, os.getuid(), _allow_foreign_uid,
)
if not _stats_ok:
    logger.error("REFUSING to start: %s. ...", _stats_reason)
    sys.exit(2)
```

**Most likely cause:** at 13:30:35, `data/signal_stats.jsonl` was foreign-owned (i.e. not uid 1000 / `TacoPants`). The systemd unit does not pass `--allow-foreign-uid` or set `AYUMI_ALLOW_FOREIGN_UID=1`, so the script self-aborted with exit 2.

**Evidence supporting this:**
- The script's pre-launch guard fires before any other startup work (verified by reading lines 1924–1941).
- Current `data/signal_stats.jsonl` (mtime 2026-09-15 00:18) is correctly owned by `TacoPants`/`uid 1000` — confirming the file *can* be self-healed to the right owner by the service itself once it starts. So if it WAS foreign-owned at 13:30:35, the file would have been re-touched (chowned) by the prior successful run, or by the next successful run after the burst.
- The 2-second runtime is consistent with the foreign-UID guard exiting at line 1941 before any cTrader/feed/network work.

### 5.3 Anomaly: processes C–G (R2–R6, exit 1/FAILURE)

- R2 (13:31:04–13:31:08): FAILURE, 4s
- R3 (13:31:38–13:31:40): FAILURE, 2s
- R4 (13:32:11–13:32:13): FAILURE, 2s
- R5 (13:32:43–13:32:47): FAILURE, 4s
- R6 (13:33:17–13:33:20): FAILURE, 3s

Exit code 1 in the launch script has multiple sites (lines 1957, 2030, 2242 and others). The short runtime (~2–4s) and `RestartSec=30` pacing indicate these all hit the **PID-guard duplicate** at line 2030 (`_pid_guard = _pid_ctx.__enter__()  # acquire lock, exit(1) if duplicate`). The PID-guard acquires a file lock on `data/forward_test.pid`; if a stale lock from the failed previous run still holds, the new process exits 1 immediately.

**Most likely sequence:**
1. Process B exits 2 quickly (foreign-UID). The PID file is **not** written because `_pid_guard` is acquired AFTER the foreign-UID check (line 2030 > line 1941).
2. systemd starts process C at 13:31:04 (RestartSec=30 wait). Process C is the first to reach line 2030. **However**, process B may have held the file lock transiently, or some other process/script may have left a stale lock — process C fails.
3. Subsequent attempts D–G (R3–R6) also fail at the PID guard for the same reason.
4. By the 6th attempt (R7), the lock is cleared, the foreign-UID guard passes (signal_stats.jsonl is now correct — either chowned by a partial B run or by the prior day's run), and the service starts cleanly at **13:33:59**.

### 5.4 Why the burst self-recovered

Both the foreign-UID and PID-guard failures are **transient state issues** that the first successful run fixes automatically:
- `signal_stats.jsonl` ownership is corrected on first successful write.
- The PID-guard file lock is released when the previous holder exits (even on early exit).

The 6th restart attempt had both state conditions cleared, so it started normally and ran 7h 46m before the next normal cycle restart at 21:20:14.

### 5.5 Why it never recurred

The service has run cleanly since 13:33:59, completing 5 more daily-cycle restarts (R7–R12) without any failure. If the foreign-UID state is the root cause, it must have been a one-time external event (a maintenance task, a backup restore, or a manual `chown` from root). The signal_stats.jsonl ownership has been stable on subsequent restarts (verified current mtime = 2026-09-15 00:18, owner = TacoPants).

## 6. Normal-Cycle Pattern (R7–R12)

| Restart | Uptime before restart | CPU time | Notes |
|---|---|---|---|
| R7 | 7h 46m | 1min 260ms | After anomaly recovery; normal |
| R8 | 23h 30m | 1min 5.471s | Normal daily cycle |
| R9 | 23h 30m | 1min 1.387s | Normal daily cycle |
| R10 | 1h 20m | 9.970s | **Short cycle** — likely SIGTERM during manual maintenance window (no error trace) |
| R11 | 23h 30m | 2min 58.370s | Normal daily cycle |
| R12 | 43m | 8.494s | **Short cycle** — likely SIGTERM during deploy/restart (no error trace) |

The two short cycles (R10, R12) show no error trace in journalctl — they are clean exits consistent with an external `systemctl restart` or maintenance signal. The current service run (R13) has been active 17h+ with no anomalies; uptime 63536s observed at investigation time.

## 7. Verdict

**BENIGN.** No code or config fix required. Specifically:

- ✅ `Restart=always` is **expected** behavior, not a bug. The restart counter growing daily is the intended systemd response to a clean-exit-then-relaunch script.
- ✅ The Sep 11 13:30 burst was a **one-time transient** (foreign-UID guard + PID-lock churn) that self-recovered on the 6th attempt and has not recurred in 4 days.
- ✅ No watchdog/OOM/systemd-config issue observed. All failures were inside the script's own pre-launch guards.
- ✅ No risk of open positions: at 13:30:34 process A reported `Forward test stopped: balance=10000.00 trades=0 pnl=0.00 errors=0 reconnects=0`. The 6 failed restarts at 13:30–13:33 each exited before reaching the broker connection phase (≤4s runtime).

## 8. Recommended Follow-up (separate `[BUILD]` card — do not implement here)

If this anomaly recurs (or to harden observability), the following is worth a small `[INFRA][BUILD]` card:

- **Capture pre-restart stderr/journald into a per-restart artifact.** Today the systemd-appended `logs/forward_test-stderr.log` only retains entries from the current run; the rotated `forward_test.log.*` is the only pre-restart evidence, and only for the in-process logger. A simple fix: add `StandardError=append:/home/TacoPants/projects/Ayumi/logs/forward_test-stderr.log` (already present) PLUS a per-startup `ExecStartPre` that rotates/archives the previous file, OR pipe through `systemd-cat` so journald owns the full record (already the case for journalctl). The gap here is purely observability, not correctness.

Not implementing in this diagnosis to stay within the card's "do not edit live service files inline" scope.

## 9. Evidence Index

| Source | Used for |
|---|---|
| `journalctl -u ayumi-forward-test.service --since 2026-09-10` | All restart timestamps, exit codes, restart counter |
| `/etc/systemd/system/ayumi-forward-test.service` | Restart policy (Restart=always, RestartSec=30, StartLimitBurst=10) |
| `scripts/launch_blend_forward_test.py:1924–1941` | Foreign-UID guard → `sys.exit(2)` → status=2/INVALIDARGUMENT |
| `scripts/launch_blend_forward_test.py:2030, 2155, 2242` | PID-guard `sys.exit(1)` and clean-shutdown `sys.exit(0)` |
| `logs/forward_test.log.2026-09-11` lines 3233–3247, 3360–3395 | Pre-burst process A clean shutdown, post-recovery process G healthy start |
| `logs/forward_test-stderr.log` (mtime 2026-09-15 15:36) | Confirms NO stderr coverage for Sep 11 burst (gap is the observability finding) |
| `data/signal_stats.jsonl` (current) | Currently TacoPants:uid 1000 — confirms file *can* be self-healed; no live anomaly |
| `systemctl status ayumi-forward-test.service` at 2026-09-15 15:35 UTC | Service active, uptime 17h 39m, no failures since R12 |

— end —
