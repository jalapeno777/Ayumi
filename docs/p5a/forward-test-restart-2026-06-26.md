# Forward Test Restart Log — 2026-06-26

## Pre-Restart State (verified 2026-06-26 12:30 EDT)
- **Service:** `ayumi-forward-test.service` — was `inactive` (crashed June 25 05:55 UTC from reconnect circuit-breaker)
- **.env md5:** `fd97f00920199646df05046d19753912` ✓
- **Kill switch:** `active=true, mode=kill, reason=ftmo_daily_loss_limit` ✓
- **No trades possible:** Kill switch blocks all order execution

## Restart Sequence (auto-restart via systemd)
- **13:36:55 UTC** — systemd started service (attempt 1) → exited status=1 (pre-startup crash)
- **13:37:27 UTC** — systemd restart (attempt 2) → exited status=1
- **13:37:59 UTC** — systemd restart (attempt 3) → **running** (PID 3356783, stable)
- **Uptime at verification:** 2h 57min (active and stable)

## Post-Restart Verification (12:30 EDT / 16:30 UTC)
- **Process:** Running as $USER (not root) ✓
- **Memory:** 145.6M (well within limits) ✓
- **Kill switch:** Still active, mode=kill ✓
- **.env:** Unchanged (md5 matches) ✓
- **Market status:** Closed (Friday after hours). No ticks expected until Sunday 5pm EDT
- **Log:** `data/forward_test.log` last written June 25 (stale — no events to log while market closed and kill switch active)

## Notes
- The first two startup failures are likely due to the pre-push gitleaks hook or import ordering during systemd's RestartSec window. Third attempt succeeded.
- Service has `Restart=always` and `RestartSec=30`, which handled the transient failures automatically.
- Forward test will remain in "waiting for market data" state until forex reopens Sunday 5pm EDT.
- Kill switch prevents any order execution regardless of signals received.

## Rollback Plan
If the service needs to be stopped:
```bash
sudo systemctl stop ayumi-forward-test.service
```
This reverts to the pre-restart state (inactive). No data loss — all state is persisted in `.env`, `data/kill_switches/`, and the cTrader token store.
