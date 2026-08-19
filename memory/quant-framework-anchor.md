# Quant Framework Anchor

_Central reference for trading framework decisions, ramp phases, and prop-firm integration._

_Last updated: 2026-07-19_

---

## Capital Ramp vs FTMO Window Reconciliation

**Decision Date:** Jul 19, 2026
**Decision Owner:** Craig
**Decision:** Option A — Ramp on demo first, then take FTMO challenge.

### Context

The Ayumi trading framework defines a phased capital ramp (Phase 1 through Phase 3+) that gradually increases position sizing and live exposure as the strategy blend proves stable. Separately, FTMO challenge windows (1-Step or 2-Step) impose their own profit targets, drawdown limits, and time constraints. These two timelines can conflict if a trader attempts to satisfy FTMO objectives while still in early ramp phases.

This section reconciles the two by establishing a clear gate: framework ramp phases run on demo first. FTMO challenge entry is conditional on ramp completion.

### Options Considered

#### Option A — Ramp on Demo First, Then FTMO (CHOSEN)

Run the full Phase 2 micro-live (4–8 weeks) on a demo account. Validate strategy blend stability — execution quality, drawdown behavior, signal-to-fill consistency — before entering any paid FTMO challenge. Only enter FTMO 1-Step or 2-Step once the ramp phase is complete and passing exit criteria.

| Pro | Con |
|-----|-----|
| No pressure from challenge clock during validation | Delays FTMO entry by 4–8 weeks |
| Strategy bugs surface on demo, not on a paid challenge | Opportunity cost (no funded trading during ramp) |
| Ramp exit criteria provide objective go/no-go signal | Requires discipline to not rush into FTMO |
| FTMO challenge then runs on a proven, stable system | |

#### Option B — Compress Ramp into FTMO Challenge Window

Enter an FTMO challenge immediately and use the challenge window itself as the ramp validation period. Compress early ramp phases into the challenge's profit-target timeline.

| Pro | Con |
|-----|-----|
| Fastest path to funded trading | High pressure — bugs or drawdown during ramp = challenge failure |
| No separate demo period needed | Conflates validation with evaluation |
| Saves calendar time if strategy is ready | FTMO rules (daily loss limits, min days) may force suboptimal trade selection during early ramp |

#### Option C — Parallel Ramp + FTMO

Run the demo ramp and an FTMO challenge simultaneously. Use the demo account for strategy validation while the FTMO challenge runs the same logic under challenge rules.

| Pro | Con |
|-----|-----|
| Hedged risk — demo validates while challenge earns | Split attention across two accounts with different rules |
| If challenge fails, demo data still informs next attempt | Drawdown handling differs between demo and challenge (daily loss limits) |
| Maximuses information gathered per unit time | Resource-intensive monitoring; psychological load of real-money challenge alongside demo |

### Decision: Option A — Ramp on Demo First

**Rationale (Craig, Jul 19 15:37 EDT):**

- Run the full Phase 2 micro-live (4–8 weeks) on demo account
- Validate strategy blend stability before entering any paid FTMO challenge
- Only enter FTMO 1-Step or 2-Step once ramp phase is complete and passing exit criteria
- No compression of ramp phases into challenge windows

### FTMO Entry Gate

**FTMO challenge entry requires ALL of the following ramp exit criteria to be met:**

1. **Phase 2 micro-live completed** — minimum 4 weeks of demo trading with the production strategy blend
2. **Drawdown within tolerance** — maximum drawdown during ramp period does not exceed the framework's Phase 2 drawdown threshold
3. **Execution quality verified** — no critical execution failures (missed fills, slippage anomalies, order path errors) in the final 2 weeks
4. **Signal-to-fill consistency** — strategy signal generation and order execution match backtested expectations within defined variance bands
5. **Strategy blend stability** — no component strategy has been disabled or hot-swapped during the final 2 weeks of the ramp

**Gate decision:** When all criteria are met → proceed to FTMO challenge entry (1-Step recommended for ICT/SMC per [FTMO risk parameters](../docs/forex/ftmo-challenge-risk-parameters-and-trade-plan.md)). If any criterion fails → extend ramp or re-evaluate strategy blend before FTMO entry.

### FTMO Challenge Path (Post-Ramp)

Once ramp exit criteria are satisfied:

1. **FTMO 1-Step** (recommended): 10% profit target, 3% max daily loss, 10% max total loss, no minimum trading days, 90% profit split
2. **FTMO 2-Step** (alternative): Two-phase with lower daily loss limits, 4-day minimum per phase, 80% profit split

See [FTMO Challenge Risk Parameters](../docs/forex/ftmo-challenge-risk-parameters-and-trade-plan.md) for full trade plan details.

---

_This document is the authoritative reference for ramp-to-FTMO transitions. Update when ramp phases change or FTMO rules are updated._
