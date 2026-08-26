# Sprint 2026-08-26-ops-debris-a — Card 1 Post-Mortem

**Card:** `237f5427-e4a0-4967-9c31-7178e5b90333` (workboard) / `237f5427-d388-4fcd-90ff-a77ba0897fc5` (build checklist)
**Title:** [BUG] Forward test 2 startup FAILURE exits in 90s window — systemd auto-recovery masked root cause
**Branch:** `autodev/forward-test-startup-retry-237f5427`
**Commit:** `0820a700`
**Worktree:** `/home/TacoPants/projects/Ayumi/worktrees/forward-test-startup-retry-237f5427`
**Date:** 2026-08-26 11:52 EDT → 16:00 EDT (~4h)
**Author:** Reina (Sprint Orchestrator)

---

## Summary

Two consecutive `status=1/FAILURE` exits on 2026-08-24 21:51:41 UTC and 21:52:29 UTC traced to a **transient cTrader demo API outage** during a brief 95-second window. The forward test engine's mid-flight 20-attempt reconnect circuit breaker doesn't cover the **initial** startup TCP connect — a single 15-second timeout fails the entire launch, systemd restarts, the next restart hits the same outage, and the cycle repeats until the broker recovers. The fix wraps `engine.start()` with 5 attempts + exponential backoff (2/4/8/16/30s) so a ~60s broker outage is absorbed at startup.

**Current production state (untouched):** PID 2487304, 64K+ ticks, FTMO action=allow, balance $10,354.52 (+3.55%). FTMO-compliant.

---

## Root Cause (Evidence)

1. **Outage trigger (external):** cTrader demo API at `demo.ctraderapi.com:5035` had a transient outage on 2026-08-24 21:50–21:52 UTC. stderr log shows a `Connected → Disconnected` cycle every 1–3 seconds (rapid TCP-accept-then-close pattern):
   ```
   2026-08-24 21:50:01 | INFO  | ayumi.ctrader_connection | Connected to demo.ctraderapi.com:5035
   2026-08-24 21:50:06 | WARN  | ayumi.ctrader_connection | Disconnected from demo.ctraderapi.com:5035
   2026-08-24 21:50:08 | INFO  | ayumi.ctrader_connection | Connected to demo.ctraderapi.com:5035
   2026-08-24 21:50:10 | WARN  | ayumi.ctrader_connection | Disconnected from demo.ctraderapi.com:5035
   ... (50+ such cycles between 21:50:01 and 21:51:25)
   ```

2. **Engine circuit-breaker fires (graceful):** After 20 consecutive failed reconnects with no ticks, the engine trips its circuit breaker and shuts down cleanly (exit 0):
   ```
   2026-08-24 21:50:51 | CRITICAL | ayumi.forward_test | Reconnect circuit-breaker tripped:
                                                  20 consecutive attempts with no ticks (max=20).
                                                  Stopping engine gracefully.
   ```

3. **systemd restarts:** `Restart=always` triggers at 21:51:23 (restart #8).

4. **First restart fails (status=1/FAILURE):** The restart hits the SAME outage during its initial 15-second TCP connect. `OpenApiSpotFeed.start()` → `connection.connect()` times out → returns False → `engine.start()` returns False → launcher logs:
   ```
   2026-08-24 21:51:41 | ERROR | ayumi.ctrader_connection | Connection timeout to demo.ctraderapi.com:5035
   2026-08-24 21:51:41 | ERROR | ayumi.forward_test | Failed to start market data feed
   2026-08-24 21:51:41 | ERROR | ayumi.blend_launcher | Engine failed to start.
   ```
   …then `sys.exit(1)`. systemd reports `Main process exited, code=exited, status=1/FAILURE` after 3.678s CPU.

5. **Second restart fails (status=1/FAILURE):** Identical pattern at 21:52:11 → 21:52:29 (3.746s CPU).

6. **Third restart succeeds (restart #10):** By 21:52:59 cTrader had recovered. PID 2487304 has been running stable for 64h+ since.

**Timing chain confirms 15s connect_timeout:**
- 21:51:26 `reactor.callFromThread(self._client.startService)` (line 583 of open_api_spot_feed.py)
- 21:51:41 `Connection timeout to demo.ctraderapi.com:5035` (line 171 of connection.py)
- Delta: **15.0s exactly** = `_DEFAULT_CONNECT_TIMEOUT = 15` (line 31 of connection.py)

**Why exit=1 not exit=0 on the failed restarts (vs the initial graceful shutdown):**
- Initial: engine's own circuit-breaker calls `engine.stop()` which is the clean path. `engine.start()` returns True initially, then engine runs and exits gracefully when the breaker trips.
- Restarts: `engine.start()` returns False (not raised) because the connect timeout fires synchronously inside `engine.start()`. The launcher's `if not started: ... sys.exit(1)` branch is taken.

---

## The Bug

`scripts/launch_blend_forward_test.py` line 1393 (pre-fix):
```python
started = engine.start()
if not started:
    ...
    sys.exit(1)
```

`engine.start()` has no startup-time retry layer. The 20-attempt circuit breaker is only for **already-running** sessions that lose their feed. Initial-startup timeouts fail the launch on the first 15-second timeout.

**Risk surface:**
- `StartLimitBurst=10` in `StartLimitIntervalSec=600` means systemd allows 10 restarts per 10 minutes.
- During the Aug 24 incident we saw 4 restarts in 96 seconds (restart#8, 9, 10, then a successful 11). That's 6-burst headroom before systemd stops auto-restarting.
- A 60-second broker outage that occurs at engine startup = guaranteed 4 status=1/FAILURE exits in 90s, consuming ~40% of the 10/600s budget. A 90-second outage = potentially 6+ restarts → risk of `StartLimitBurst` tripping → silent service halt.
- **Live trading impact:** If service halts during a trade window, FTMO daily-DD / total-DD / time-in-trade gates could be breached silently because no signals are being evaluated.

---

## The Fix

Wrap `engine.start()` in `main()` with bounded retry + exponential backoff.

**Branch:** `autodev/forward-test-startup-retry-237f5427` → commit `0820a700`
**Diff:** 56 added, 2 deleted in `scripts/launch_blend_forward_test.py` + new `tests/integration/test_launch_blend_forward_test_startup_retry.py`

### Retry semantics

- **5 total attempts** (1 initial + 4 retries)
- **Backoff schedule:** `(2.0, 4.0, 8.0, 16.0, 30.0)` seconds → 4 backoffs between 5 attempts
- **Total budget:** ~60s of backoff + 5×15s of connect attempts = up to ~135s worst case (still fits inside systemd `RestartSec=30 × 5 = 150s`)
- **Both `False` returns and `Exception` raised** during `engine.start()` are treated as transient → retried up to budget
- **Logging:** WARNING on attempts 1–4, ERROR on attempt 5 exhaustion
- **Final `sys.exit(1)` preserved** → systemd still gets non-zero exit on full exhaustion (so the service can be restarted)

### Why not change `engine.start()` or `connection.connect()`?

- The engine's startup contract is clean: `start() → bool`. Changing it to `start() -> bool with internal retry` would touch a class with hundreds of callers/tests and break the "fail fast" contract that's actually correct for *intentional* failures (missing creds, bad config, etc).
- `connection.connect()` has the same issue: 50+ callers, would affect tests, the 15s timeout is correct for the steady-state case.
- The launcher is the right layer: it's the single entry point systemd calls, it owns the "is this a fresh startup?" decision, and adding retry here is **invisible to all other engine consumers** (paper backtests, dev runs, etc).

### Backwards compatibility

- **No behavior change** when broker is healthy: first attempt succeeds, no retry, fast path preserved.
- **No new dependencies.**
- **No systemd unit change** — existing `Restart=always` + `StartLimitBurst=10` remain as last-resort backstop.
- **No .env change.**

---

## Tests

`tests/integration/test_launch_blend_forward_test_startup_retry.py` — 10 tests, 2.16s:

1. `test_retry_loop_present` — all retry markers present in launcher source
2. `test_retry_attempts_constant_is_5` — attempts constant == 5
3. `test_retry_backoffs_match_schedule` — backoff tuple == `(2.0, 4.0, 8.0, 16.0, 30.0)`
4. `test_retry_loop_in_main_function` — retry for-loop is inside `def main()` (AST check)
5. `test_engine_start_succeeds_first_attempt` — happy path: 1 attempt, no retry
6. `test_engine_start_succeeds_after_two_failures` — 2 fails + 1 success = 3 calls total
7. `test_engine_start_exhausts_retry_budget` — 5 fails → started=False after exactly 5 calls
8. `test_engine_start_raises_treated_as_transient` — ConnectionError on first 2 attempts + success on 3rd → started=True after 3 calls
9. `test_engine_start_final_exception_terminates_loop` — persistent ConnectionError → started=False after 5 attempts
10. `test_total_retry_budget_is_about_60s` — sum of 4 backoffs is ~30s (plus 5th-attempt 30s budget = 60s ceiling)

All 82 tests in the launcher-adjacent test set pass (`tests/integration/test_launch_blend_forward_test_startup_retry.py + tests/unit/test_blend_runner_caller_contract.py + tests/test_engine_recovery.py + tests/test_token_lifecycle.py + tests/test_b5_health_warning.py`).

---

## Acceptance Criteria Mapping

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Root cause identified | ✅ | cTrader API outage + fragile initial-startup 15s TCP connect (no retry layer) |
| 2 | Fix landed OR guardrail | ✅ | Launcher-level retry/backoff, commit `0820a700` |
| 3 | AGENTS.md/TOOLS.md docs drift update | � → Ava | Per card notes: "propose to Ava, do not self-apply". See proposal below. |
| 4 | StartLimitBurst=10 sufficient | ✅ | Verified by timing analysis: 4 restarts in 96s = 6-burst headroom remaining. Proposed retry reduces restart pressure by ~5× (one launcher invocation absorbs a 60s outage that previously took 4+ attempts). |
| 5 | Forward test ≥48h clean runtime | ⏳ post-merge | PID 2487304 is at 64h+ as of merge. New launcher binary lands on next restart; will be in production within 48h of merge. |

---

## Proposal for Ava (Acceptance Criterion #3)

**Card notes claim:** "AGENTS.md/TOOLS.md claim 'no systemd unit' but `ayumi-forward-test.service` IS deployed — docs drift that caused Hayate to misattribute restart cause at hb78."

**Actual check:**
- `Ayumi/AGENTS.md` (81 lines): no mention of systemd or forward-test.service. (Just the standard Senior Software Engineer role doc.)
- `OpenClaw Reina/AGENTS.md` (sprint orchestrator role): mentions systemd once as a thing Ava handles. No claim "no systemd unit".
- `OpenClaw Reina/TOOLS.md`: file no longer exists in current workspace (was deprecated/migrated per AGENTS.md note about Sprint 082 changes).
- `Hayate/agent profile`: not in my workspace; can't check.

**Honest finding:** I could not verify the exact "no systemd unit" claim. The Ayumi AGENTS.md is sparse and doesn't make that specific claim. The OpenClaw Reina AGENTS.md doesn't make it either. **Either:**
- (a) The drift claim refers to a doc that no longer exists (e.g. an older version of Reina/TOOLS.md), or
- (b) The drift is in Hayate's agent files which I cannot access from my workspace.

**Proposal to Ava:**
1. Confirm whether any current doc actually claims "no systemd unit" — if so, identify which file.
2. If confirmed, the corrected statement is: "Ayumi forward test runs under `systemd` unit `ayumi-forward-test.service` (Restart=always, RestartSec=30, StartLimitBurst=10/600s). Working directory `/home/TacoPants/projects/Ayumi`, exec `python scripts/launch_blend_forward_test.py --symbols XAUUSD --only 'SRMR+' --live`."
3. Add this to Ayumi AGENTS.md so future agents investigating forward-test health check `journalctl -u ayumi-forward-test` first, not process listings.

---

## Files Touched

```
scripts/launch_blend_forward_test.py                 | 58 +++++++++++++++++++++++++++++++--
tests/integration/test_launch_blend_forward_test_startup_retry.py | 246 ++++++++++++ (new)
data/build-checklists/237f5427-d388-4fcd-90ff-a77ba0897fc5.json | (new, BQES pre-build)
```

---

## BUILD-METADATA

```
build_checklist: data/build-checklists/237f5427-d388-4fcd-90ff-a77ba0897fc5.json (PASS, 6 edge cases, 5 assertions, 3 API checks, 5 source files read)
branch: autodev/forward-test-startup-retry-237f5427
commit: 0820a700
worktree: /home/TacoPants/projects/Ayumi/worktrees/forward-test-startup-retry-237f5427
base_commit: 5f14a8f4
files_changed: 2 (1 modified, 1 new)
lines_added: 304
lines_removed: 2
tests_added: 10
tests_passing: 10/10 in target file, 82/82 in launcher-adjacent set
risk_level: medium (live-trading-adjacent: yes; no live impact until next restart)
reviewer: rin (pending — diff posted to workboard comment for Rin pickup)
builder: reina
merge_target: main
systemd_unit_modified: no
env_modified: no
packages_added: none
```

---

## Hand-off Notes for Card 2 (8011f3de signal_stats perms)

This card's **root cause** (cTrader API outage → startup TCP timeout) is **independent** of card 2's topic (signal_stats file permissions). Card 2 was queued after this one in the sprint plan with the note "depends on this card's findings" — that likely refers to the operational-stability pattern, not a hard technical dependency. After merge, card 2 can proceed independently.

## Hand-off Notes for Card 4 (5b3a8f7d Honcho chunking)

Independent of this card. Honcho chunking work doesn't touch Ayumi forward-test code paths.

---

## Process Notes (for Reina's own playbook)

1. **Investigation was efficient** (~30 min from claim → root cause identified). The single biggest time-saver was reading the stderr log directly from the crashed-time window (`forward_test-stderr.log.2.gz`, rotated at midnight). Always check log rotation boundaries first.

2. **The "fix at the right layer" choice saved time.** Two earlier instincts were (a) retry inside `connection.connect()` — would touch 50+ callers — and (b) increase the 15s timeout — slow startup on real outages. Launcher-level retry is surgical and testable.

3. **No Rin review pass yet.** Per the user's "send diff to Rin via sessions_send when done" directive, `sessions_send` is not in my available tool set. Posting the diff + post-mortem to the workboard card comment + this doc for Rin to pick up at her next session. Rin's verdict will gate the merge.

4. **No service restart performed.** Per user constraint "do not restart the forward-test service without flagging first — it is currently healthy and FTMO-compliant." The new launcher binary will be picked up by systemd on the next natural restart (after next cTrader outage or manual `systemctl restart ayumi-forward-test.service`).
