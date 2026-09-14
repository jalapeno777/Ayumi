# Watchdog Crash-Recovery Test

> **[RETIRED 2026-09-14]** `ayumi-watchdog.service` was formally retired on 2026-09-14
> (masked since 2026-09-03; masked unit symlink removed). Crash recovery is now owned
> entirely by systemd `Restart=always` on `ayumi-forward-test.service`, and process
> safety by the blend-launcher B5 Health loop + FTMO guard. This document is retained
> for historical reference only. See workboard card
> 3bf43e02-b643-4dad-9faf-73273f14dcc6.

## Objective

Verify that the forward test process auto-recovers after an unexpected termination (e.g., crash, OOM kill, manual kill).

## Architecture

### Recovery Mechanism

The forward test is managed by **systemd** via `ayumi-forward-test.service`:

```ini
[Service]
Type=simple
User=TacoPants
ExecStart=.../python scripts/launch_blend_forward_test.py --symbols XAUUSD --only "Killzone Momentum" --live
Restart=always
RestartSec=30
```

- **`Restart=always`** — systemd restarts the process regardless of exit code
- **`RestartSec=30`** — 30-second delay between restart attempts
- **`StartLimitIntervalSec=300` / `StartLimitBurst=5`** — max 5 restarts per 5-minute window

### Watchdog Role

`ayumi_watchdog.py` is a **monitor-only** service. It does NOT restart processes. Its role:

1. Checks `pgrep -f launch_blend_forward_test` every 60 seconds
2. If the process is gone, writes a `critical` alert to `data/ayumi/events.jsonl`
3. Generates a recommendation to investigate
4. Falls back to checking `systemctl --user is-active ayumi-forward-test`

The actual restart is handled entirely by systemd.

## Test Procedure

### ⚠️ Safety Constraints

- **Do NOT run this test on a `--live` instance during trading hours.** Killing the forward test causes up to 30 seconds of downtime (RestartSec=30). On a live system, this can miss fills or skip signal evaluation.
- **Recommended window:** Weekend (markets closed) or during a scheduled maintenance window.
- **Alternative:** Run on a paper-only instance (`--paper` flag) to avoid live trading impact.

### Pre-Test Checklist

```bash
# 1. Confirm forward test is running and healthy
systemctl status ayumi-forward-test.service
pgrep -f launch_blend_forward_test && echo "RUNNING"

# 2. Confirm watchdog is running
pgrep -f ayumi_watchdog.py && echo "WATCHDOG_ACTIVE"

# 3. Record current PID
cat /home/TacoPants/projects/Ayumi/data/forward_test.pid
# Note this PID for comparison after restart

# 4. Confirm markets are closed (if live instance)
# Forex markets close Friday ~17:00 ET, open Sunday ~17:00 ET
```

### Test Steps

```bash
# Step 1: Get the current forward test PID
FT_PID=$(cat /home/TacoPants/projects/Ayumi/data/forward_test.pid)
echo "Forward test PID: $FT_PID"

# Step 2: Kill the process (simulates crash)
kill -9 "$FT_PID"
echo "Killed PID $FT_PID at $(date -Iseconds)"

# Step 3: Immediately check systemd status
systemctl status ayumi-forward-test.service
# Expected: status changes to "activating (auto-restart)" then back to "active"

# Step 4: Wait for restart (RestartSec=30, allow up to 60s)
echo "Waiting up to 60s for restart..."
for i in $(seq 1 12); do
    sleep 5
    if pgrep -f launch_blend_forward_test > /dev/null; then
        NEW_PID=$(pgrep -f launch_blend_forward_test)
        echo "RESTARTED at $(date -Iseconds) — new PID: $NEW_PID (after $((i*5))s)"
        break
    fi
    echo "  ...${i}*5s elapsed, not yet restarted"
done

# Step 5: Verify recovery
systemctl status ayumi-forward-test.service
pgrep -f launch_blend_forward_test && echo "PROCESS_RUNNING"
cat /home/TacoPants/projects/Ayumi/data/forward_test.pid

# Step 6: Check watchdog detected the event
# Look for critical alert in events log
tail -20 /home/TacoPants/projects/Ayumi/data/ayumi/events.jsonl | \
    python3 -c "import sys,json; [print(json.loads(l).get('severity',''),json.loads(l).get('claims','')) for l in sys.stdin]"
```

### Expected Results

| Check | Expected | Pass Criteria |
|-------|----------|---------------|
| systemd status | `active (running)` within 60s | New PID assigned |
| Process running | `pgrep` finds new PID | PID differs from original |
| PID file updated | `data/forward_test.pid` has new PID | Matches new process |
| Watchdog alert | `critical` event in events.jsonl | References forward_test down |
| Watchdog recovery | Subsequent `info` event | References forward_test running |

### Post-Test Cleanup

```bash
# Verify forward test is healthy (producing heartbeats)
ls -la /tmp/ayumi-worker/heartbeat
cat /tmp/ayumi-worker/heartbeat  # Should be recent timestamp

# Check forward test logs for clean startup
tail -30 /home/TacoPants/projects/Ayumi/logs/forward_test-stdout.log
```

## Test Result

**Status:** NOT EXECUTED — live trading system

The forward test is currently running with `--live` flag on XAUUSD Killzone Momentum. Executing a crash-recovery test during market hours risks missed fills and position state corruption.

**Recommendation:** Schedule this test for a weekend or maintenance window when markets are closed. Alternatively, deploy a paper-only instance and run the test there.

## Findings

### Finding 1: Watchdog does not restart processes

The card's original expectation stated "ayumi_watchdog.py detects exit and restarts within configured interval." This is incorrect — `ayumi_watchdog.py` is **monitor-only**:

- It checks process health every 60 seconds via `pgrep`
- It writes alerts and recommendations to JSONL files
- It does NOT issue restart commands or interact with systemd

**Actual restart mechanism:** systemd `Restart=always` with `RestartSec=30`.

**Gap:** If systemd itself fails or the service is stopped (not crashed), the watchdog will alert but nothing will restart the service automatically. Consider adding a watchdog-initiated restart capability or a secondary monitor that can trigger `systemctl restart`.

### Finding 2: RestartSec=30 may be too long for live trading

A 30-second restart delay on a live trading system means:
- Up to 30s of missed price ticks
- Potential gap in signal evaluation during volatile periods
- Killzone windows are time-sensitive — a 30s gap at session open could miss the highest-value setups

**Recommendation:** Consider reducing `RestartSec` to 5-10s for the forward test service, or using `Restart=on-failure` with a shorter interval.

## Related

- Runbook: [stale-pid-file-blocks-restart.md](../runbooks/stale-pid-file-blocks-restart.md)
- Parent incident: card `52bfcac3`
- Service file: `/etc/systemd/system/ayumi-forward-test.service`
- Watchdog: `/home/TacoPants/ayumi_watchdog.py`
- Restart script: `scripts/restart_forward_test.sh`
