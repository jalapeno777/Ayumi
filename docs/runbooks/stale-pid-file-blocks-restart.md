# Runbook: Stale PID File Blocks Restart

## Symptom

```
PermissionError: [Errno 13] Permission denied: '/tmp/ayumi-worker.pid'
```

or

```
PermissionError: [Errno 13] Permission denied: '/tmp/ayumi-worker/worker.pid'
```

or

```
PermissionError: [Errno 13] Permission denied: 'data/forward_test.pid'
```

A service fails to start (or restart) because a PID file from a prior run is owned by a different user — typically `root` — and the current user cannot overwrite or delete it.

## Root Cause

After system maintenance, container rebuilds, or manual `sudo` invocations, stale PID files can be left behind in `/tmp` or `data/` owned by `root`. When the service restarts under its normal user (`TacoPants`), it cannot write to or remove the root-owned file, causing a `PermissionError` that blocks startup.

### Affected PID Files

| File | Owner (normal) | Owner (problem) | Service |
|------|----------------|-----------------|---------|
| `/tmp/ayumi-worker.pid` | TacoPants | root | Legacy watchdog (v1) |
| `/tmp/ayumi-worker/worker.pid` | TacoPants | root | Current watchdog (`ayumi_watchdog.py`) |
| `data/forward_test.pid` | TacoPants | root | Forward test engine |

### Historical Incidents

- **2026-07-26:** `/tmp/ayumi-worker.pid` left root-owned after container rebuild. Watchdog could not write PID file on restart. Sev-3, resolved manually.
- **2026-07-28:** Same pattern confirmed resolved. 14 stale root-owned PID files found in `/tmp` during audit (none in active use).

## Resolution

### Step 1: Identify the stale PID file

```bash
# Check common PID file locations
ls -la /tmp/ayumi-worker.pid /tmp/ayumi-worker/worker.pid /home/TacoPants/projects/Ayumi/data/forward_test.pid 2>/dev/null
```

Look for files owned by `root` instead of `TacoPants`.

### Step 2: Verify the PID is not actively in use

```bash
# Read the PID from the file
PID=$(cat /tmp/ayumi-worker.pid 2>/dev/null)

# Check if that process is running
ps -p "$PID" -o pid,user,comm 2>/dev/null
```

If the process is NOT running, the PID file is stale and safe to remove.

### Step 3: Remove the stale PID file

```bash
# Remove the stale file (requires sudo if owned by root)
sudo rm -f /tmp/ayumi-worker.pid
sudo rm -f /tmp/ayumi-worker/worker.pid
sudo rm -f /home/TacoPants/projects/Ayumi/data/forward_test.pid
```

### Step 4: Fix directory ownership (if needed)

```bash
# Ensure the watchdog runtime directory is owned by the correct user
sudo chown -R TacoPants:TacoPants /tmp/ayumi-worker/
sudo chown -R TacoPants:TacoPants /home/TacoPants/projects/Ayumi/data/
```

### Step 5: Restart the affected service

```bash
# Forward test (managed by systemd)
sudo systemctl restart ayumi-forward-test.service

# Watchdog (if running manually)
# Kill existing instance if any
pkill -f ayumi_watchdog.py
# Restart as the correct user
sudo -u TacoPants python3 /home/TacoPants/ayumi_watchdog.py &

# Or use the restart script for forward test
sudo -u TacoPants bash /home/TacoPants/projects/Ayumi/scripts/restart_forward_test.sh
```

## Verification

```bash
# Confirm the service is active
systemctl status ayumi-forward-test.service

# Confirm PID file has correct ownership
ls -la /tmp/ayumi-worker.pid /tmp/ayumi-worker/worker.pid data/forward_test.pid 2>/dev/null
# All should show TacoPants as owner

# Confirm the process is running
pgrep -f launch_blend_forward_test && echo "forward_test running"
pgrep -f ayumi_watchdog.py && echo "watchdog running"
```

## Prevention

1. **Never run services as root.** Always use the service user (`TacoPants`) or a dedicated service account.
2. **Use systemd management** (`ayumi-forward-test.service`) instead of manual process launches — systemd handles PID lifecycle automatically.
3. **Audit `/tmp` PID files periodically** — stale root-owned files indicate prior misconfiguration.
4. **Add PID file cleanup to deployment scripts** — remove old PID files before starting services.

## Related Files

- `ayumi_watchdog.py` (runtime: `/home/TacoPants/ayumi_watchdog.py`) — writes `/tmp/ayumi-worker/worker.pid`
- `scripts/launch_blend_forward_test.py` — writes `data/forward_test.pid`
- `scripts/restart_forward_test.sh` — manual restart with health verification
- `/etc/systemd/system/ayumi-forward-test.service` — systemd unit with `Restart=always`

## Cross-References

- Parent incident: card `52bfcac3` ([INFRA] Watchdog PermissionError on /tmp/ayumi-worker.pid)
- PID audit: 14 stale root-owned PID files found in `/tmp` (2026-07-28)
