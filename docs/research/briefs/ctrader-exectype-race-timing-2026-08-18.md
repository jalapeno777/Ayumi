# cTrader execType Race — Timing Analysis & Fix Recommendation

**Card:** 15f9ad0e (from Hayate) · **Brief:** Satsuki · **Date:** 2026-08-18 · **Consumer:** Hayate (ce6de98d PR review)
**Cross-refs:** ce6de98d (CRITICAL fix, ready), 0d7d7557 (B5 warning semantics), 591cbfe6 (feed degradation, open)

## Verdict (TL;DR)

**The inter-event race Hayate hypothesized is real but SECONDARY.** The primary failure is the **await-timeout → REJECTED misclassification**: all 4/4 orders today were marked `timeout_awaiting_event`/REJECTED locally *before any execution event arrived*, then filled at the broker. The ce6de98d fix as scoped (lenient `_pending_orders` handling) does **not** cover this — scope expansion recommended.

**Enum correction (material):** the card maps execType=2→Filled, 3→OrderStatus. Per the vendored proto (`OpenApiModelMessages_pb2.py`) and official docs (help.ctrader.com/open-api/model-messages, N=2 independent sources): **ORDER_ACCEPTED=2** ("Order passed validation"), **ORDER_FILLED=3**. There is no "OrderStatus" execution type. The broker sequence is ACCEPT(2)→FILLED(3) — normal, documented cTrader behavior, not a shift.

## Timing (Aug 18, N=4 XAUUSD long 0.16 lots, log resolution 1s)

| Order | ACCEPT→FILLED gap | Dup ACCEPT(2) | Late FILLED(3) re-emit |
|---|---|---|---|
| 315dcfa8 09:15:36 | <1s (same sec) | same sec | +44s (09:16:20) |
| 09a386e3 09:30:35 | <1s | same sec | +4m24s |
| faf03441 09:45:36 | <1s | same sec | +4m26s |
| ea3381e8 10:30:36 | <1s | same sec | +7m07s (10:37:43) |

**Median ACCEPT→FILLED: <1s.** Preceding each episode: cTrader send-and-wait stalls ≥14s (`get_balance` timeouts 5.0s ×2, e.g. 09:15:22 + 09:15:32 before order 1) — events arrived in a delayed burst ~1s *after* the local await expired.

## Historical comparison: UNANSWERABLE

Zero live fills exist in any retained log before today. Aug 11–17: `trades=0 live_fills=0` all week (launcher gate blocked orders — 2a2b4cf3). July runs: 0 trades. Only "fills" file is `forward_test.log.contaminated-20260711` (pytest output, not live). EXEC_EVENT instrumentation first appears today. **No baseline exists; treat "has the broker pattern shifted?" as unknown but un-evidenced — current pattern matches documented semantics.**

## Actual failure chain per order (4/4, from log + code read)

1. Transport stall → `event.wait(timeout+5)` expires → order → `late_fill_registry` (TTL 120s), marked **REJECTED** `timeout_awaiting_event`, `on_order_rejected` fires (`open_api_spot_feed.py` ~L1386–1397)
2. ACCEPT(2) arrives ~1s later → still in `_pending_orders` → **popped on ACCEPT** → falls through to FILLED branch (L1754+: only CANCELLED/REJECTED dispatch otherwise) → `on_order_filled` fires **on ACCEPT payload** (no executionPrice/positionId → naked-position stamping risk)
3. FILLED(3) arrives <1s later → pending empty → late_fill_registry MATCH → `on_order_filled` fires **again** with real payload
4. Dup ACCEPT(2) + late FILLED(3) → DROP (WARNING line's empty `clientOrderId` is a logging artifact of the clientMsgId-fallback reassignment)

**Net effect today:** strategy counted 4/4 as `signals_failed_live`, `trades=0 live_fills=0` all day — while broker filled 4/4; `daily_pnl=+$301.36`, dd −4.16%, positions tracked only by the 5-min sizer reconcile (which seeded 1 at 09:30:36). Unmanaged-but-lucky P&L. B5 warning text ("orders being rejected") is wrong — they're being filled (0d7d7557 overlap).

## Recommendation to ce6de98d review

1. **Terminal-event-only state machine** (the "overhaul" option): pop + mark only on FILLED(3)/PARTIAL_FILL(11)/CANCELLED(5)/REJECTED(7)/EXPIRED(6); ACCEPT(2) is informational (no pop, no FILLED status, no callback)
2. **Timeout → INDETERMINATE**, not REJECTED: stay in late_fill_registry; strategy must not increment `signals_failed_live` on timeout
3. **Dedupe `on_order_filled`** (skip re-fire if order already FILLED; update payload only)
4. B5 warning semantics fix (0d7d7557) + transport-stall root cause (overlaps 591cbfe6 feed degradation / token_age 12.4d)

**Confidence:** mechanism HIGH (4/4 log evidence, code-read, 2-source enum). Historical non-shift: UNANSWERABLE (no baseline) — flagged, not assumed.
**Freshness:** validated 2026-08-18 14:5xZ against live log + code. Invalidated by: cTrader OpenAPI proto update, adapter rewrite, or ce6de98d merge.
**Stopping condition:** question answered (timing quantified, historical baseline shown absent, fix verdict rendered). Unknowns: ms-resolution gap (logs are 1s), await-timeout constant value, transport-stall root cause (591cbfe6 scope).
