# Ayumi Sprint — 2026-06-12

**Goal:** Clear Ayumi BQ backlog through triage → autobuild pipeline.
**Forward test:** LIVE, stable (1948 ticks, 0 errors, auth fix committed `7af7a73`).

---

## Phase 1: Triage — DONE ✅

**Archived (resolved today):**
- BQ-614 — cTrader auth failure (resolved: ProtoMessage double-wrap fix)
- BQ-680 — Reconnection with jitter backoff (resolved: state machine + backoff)
- BQ-664 — Forward test TP1 + connection death detection (resolved: auth fix)
- BQ-117 — Logging namespace (superseded by BQ-122)
- BQ-118 — Logging namespace (superseded by BQ-122)

**Not Ayumi (recategorize):**
- BQ-102, BQ-592, BQ-234 — Ava learning/personality items

**Deferred:**
- BQ-615 — Order book snapshot (feature doesn't exist yet)
- BQ-133 — Spread regime classifier (nice-to-have, no production pain)

---

## Phase 2: Autobuild Sprint — 7 items, ~10 SP

| # | BQ | Title | SP | Verdict | Pipeline |
|---|-----|-------|----|---------|----------|
| 1 | BQ-345 | Signal Engine Bar-Close Audit | 1.5 | READY | Plan→Council(2)→Build→Validate |
| 2 | BQ-369 | Wire Kelly Criterion | 1 | READY | Plan→Council(2)→Build→Validate |
| 3 | BQ-508 | Regime Labels on Walk-Forward | 2 | READY | Plan→Council(2)→Build→Validate |
| 4 | BQ-774 | Forward Test Resilience Tests | 1 | RESPEC | Plan→Council(2)→Build→Validate |
| 5 | BQ-681 | Token Manager (proactive refresh) | 2 | RESPEC | Plan→Council(2)→Build→Validate |
| 6 | BQ-687 | Strategy Interface Standardization | 1.5 | RESPEC | Plan→Council(3)→Build→Validate |
| 7 | BQ-685 | Per-Strategy Isolation + FTMO | 3 | READY | Plan→Council(3)→Build→Validate |

**Build order:** 1→2→3 (ready, low SP) → 4→5 (respec, medium) → 6→7 (design work, higher SP)

**Deferred to next sprint:**
- BQ-545 (trend+ATR validation, 1.5 SP) — needs backtest data
- BQ-504 (London ORB, 2 SP) — extends existing strategy
- BQ-615 (order book, 1 SP) — feature doesn't exist

---

## Phase 3: Validation + Post-mortem
- Verify all built items against acceptance criteria
- Forward test stability check (1hr uptime, no reconnect loops)
- Sprint post-mortem: `docs/post-mortems/sprint-ayumi-2026-06-12.md`

## Model chain: zai/glm-5.1 → minimax-m3 → kimi-k2.6 → gemma4 → gpt-5.5
## Max concurrent subagents: 2
## Total SP: ~12 across sprint
