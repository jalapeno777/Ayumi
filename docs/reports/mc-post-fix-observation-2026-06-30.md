# MC Post-Fix Observation Report — 2026-06-30

**Report time:** Tuesday, June 30, 2026 - 8:30 AM (America/Toronto) / 12:30 UTC

## 1. MC Tasks
- `data/ops/` contains cTrader credential health logs, but no MC task queue file.
- `.env.local` does not exist in the repo; no `MC_EVENT_TOKEN_AUTOBUILD` found in `.env*` files.
- **Status:** Cannot query MC task state — no token or local MC task cache found. No failures detected, but not verifiable.

## 2. BQ Status
- `build_queue/manifest.json`: **missing**.
- Drafts: 1 card (`BQ-1036.md` — .env token clobbering, HIGH, blocked on Craig preference).
- Completed: 1 card (`BQ-1382.md` — cTrader connection reliability, completed 2026-06-28).
- **Status:** No recent build queue activity. Last completed 2026-06-28.

## 3. LP Extraction Health
- `data/learning/extraction_health.jsonl`: **missing**.
- **Status:** No extraction health data available.

## 4. SD Dry-Run Status
- `data/audit/stage2_dry_run_decisions.jsonl`: **missing**.
- `data/audit/bar_close_audit.jsonl` exists, last entry 2025-03-07 (stale).
- **Status:** No stage-2 dry-run decision log found.

## 5. DIH Wrapper Status
- `data/ops/dreaming_wrapper_status.jsonl`: **missing**.
- `data/ops/gateway_memory_log.jsonl` last entry: 2026-06-14 (stale, ~16 days old).
- **Status:** No dreaming wrapper status log found; gateway memory log is stale.

## Summary
Several expected monitoring files are absent or stale:
- `build_queue/manifest.json`
- `data/learning/extraction_health.jsonl`
- `data/audit/stage2_dry_run_decisions.jsonl`
- `data/ops/dreaming_wrapper_status.jsonl`
- `.env.local` / `MC_EVENT_TOKEN_AUTOBUILD`

No active failures are visible, but health cannot be fully verified because the expected data sinks are not populated. Recommend ensuring the daily jobs that write these logs are scheduled and emitting.
