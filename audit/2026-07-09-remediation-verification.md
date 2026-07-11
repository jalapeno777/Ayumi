# Remediation Sprint — First-Hour Verification Report

**Card:** e2c9b0c8 (VERIFY first-hour post-restart)
**Service restart:** 2026-07-10 12:38:40 UTC
**Verification window:** 12:38:40 → 13:40:26 UTC (T+62min)
**Reported by:** Ava (cron 45242926)

## Summary: ⛔ FAIL — 2 acceptance criteria not met

| # | Criterion | Status | Detail |
|---|-----------|--------|--------|
| 1 | `stats_fails: 0` sustained | ✅ PASS | 0 throughout, confirmed in heartbeat_trading.json |
| 2 | Zero INVALID_REQUEST post-restart | ⛔ FAIL | 3 hits at 12:43:10 UTC (transient auth burst, recovered) |
| 3 | Zero Permission denied | ✅ PASS | None found |
| 4 | Zero Unknown instrument | ✅ PASS | Pre-restart USDCAD hits only (03:45), none post |
| 5 | ≥1 fill OR documented reason | ⚠️ DOCS | Zero fills. XAUUSD price-sanity guardrail rejecting all signals (decoder bug, entry_price=4,087,580 vs sane_max=5,000). Other 4 strategies evaluating but no signal conditions met. |
| 6 | positions_carried matches broker | ✅ PASS | positions=0, open_risk=$0.00, sizer/broker in sync |
| 7 | Verification report written | ✅ PASS | This file |

## Detailed Findings

### FAIL: INVALID_REQUEST at 12:43:10 UTC (3 events)
- `cTrader error [INVALID_REQUEST] tier=unknown: Malformed payload`
- `Auth fault requires escalation: malformed_request (INVALID_REQUEST) — failing closed`
- Cause: Token refresh attempted at ~T+5min post-restart. Refresh is DISABLED (manual rotation required). API client was reconstructed and connection recovered.
- **No recurrence in 57 minutes since** (12:43 → 13:40). Service has been stable.

### DOCS: Zero fills — XAUUSD decoder bug
- SRMR+ strategy IS generating signals for XAUUSD
- Price-sanity guardrail (Card 3) correctly rejecting them:
  - `entry_price=4,087,580.00000 exceeds sane_max=5,000.00`
  - `stop_loss=3,300,250.00000 exceeds sane_max=5,000.00`
- Root cause: `open_api_spot_feed._handle_spot_event` non-JPY path decoder bug (known)
- Other strategies (BB+RSI Mean Reversion, Donchian Breakout, Killzone Momentum, Session Breakout Asian): 28 evaluations each, all `no_signal` — normal market conditions

### Service health at T+62min
- `ticks_received`: 25,472 (advancing at ~6.5 ticks/sec)
- `bars_built`: 35
- `engine_running`: true
- `connection_state`: authenticated
- `balance`: $9,554.59 (starting $10,000)
- `drawdown`: 4.45%
- `halt`: NONE
- `uptime`: 3,692s
- Reconciliation: sizer/broker in sync, 0 positions, $0 open risk

## Recommendation
- Service is stable and not accumulating damage
- INVALID_REQUEST was transient (auth recovery on restart)
- Real blocker for fills is the XAUUSD decoder bug (separate card needed)
- **Do NOT pause service** — observation continues to produce valid health data
- Card should NOT pass verification — INVALID_REQUEST criterion failed
