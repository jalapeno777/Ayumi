# Quest: Ayumi FTMO Path

**Status:** Draft for Council Review
**Date:** 2026-07-07
**Owner:** Ava (orchestration), Craig (decisions)
**Trigger:** 3 months of struggling to get Ayumi off the ground. Need a coherent path to MVP and a true FTMO test.

---

## Objective

Get Ayumi to a state where it can pass an FTMO-style forward test on a cTrader demo account, with the system self-healing common operational issues without Ava babysitting it.

## Completion Condition (verifiable)

A forward test on cTrader demo running under FTMO rules/restrictions that passes FTMO challenge criteria. Verifiable via:

- Forward test log artifacts (cTrader demo account)
- Daily P&L meeting FTMO targets
- Drawdown within FTMO limits
- Self-healing log showing auto-remediation of common failures
- 30+ consecutive days of compliant forward testing

---

## Phases (proposed, ~17-22 SP, 6-10 weeks wall-clock)

### Phase 1A: Architecture & Signal Audit (3-4 SP, parallel with 1B)

**Why this exists:** 10 strategies, 0 active trades. Need to determine if the bottleneck is coordination (signal→risk→execution handoff), the strategy layer, or both.

**Deliverable:** Architecture audit doc with prioritized gap list. Symbol/signal evaluation. Honest read on what's broken and what's just unverified.

**Acceptance criteria:**
- Code-level audit of signal generation pipeline
- Audit of risk layer + execution handoff
- Audit of 10 current strategies (what triggers, what doesn't, why)
- Documented gap list with severity
- Recommendations for what to fix vs. redesign vs. drop

### Phase 1B: Hayate Checkpoint Design (2 SP, parallel with 1A)

**Why this exists:** Hayate's daily audit needs to know what to monitor. Catalog of failure modes + runbook per failure.

**Deliverable:** Checkpoint registry (YAML/JSON), runbook per failure mode, severity scoring, daily audit schedule.

**Acceptance criteria:**
- Catalog of >20 checkpoint types covering: system health, trading health, data health, pipeline health, north-star progress, kanban hygiene
- Runbook per checkpoint (detection → action)
- Severity classification (critical/high/medium/low)
- Drift detection rules baked in
- Auto-remediation tier (L0-L4) per checkpoint

### Phase 2: Infrastructure Modularization + Resource Caps (2-3 SP)

**Why this exists:** Backtests/optimization processes have caused system load issues (1.5GB RSS runaways observed). Python code needs to be properly modular.

**Deliverable:** Modular test/opt/backtest code, CPU throttling, memory budgets enforced, no runaway processes.

**Acceptance criteria:**
- Backtests run with explicit CPU/memory caps
- Memory budgets enforced (per-process and total)
- Modular architecture: tests, optimization, backtests, live trading each in own modules
- Stress test: 4h run does not exhaust system resources
- Documentation on how to add new backtests within caps

### Phase 3: Strategy R&D (4-5 SP)

**Why this exists:** Need winning combinations across strategies and symbols. Mix of grids, swing, short scalps, long-term.

**Deliverable:** Validated strategy set with backtest metrics (frequency × profitability). Symbol coverage expanded.

**Acceptance criteria:**
- At least 1 working strategy per category: grid, swing, short scalp, long-term
- Symbol coverage: minimum X symbols validated (TBD based on audit)
- Backtest metrics: trades/day, win rate, profit factor, max drawdown
- Combination testing: which strategies complement, which conflict
- Forward-testable strategy set (no paper-only)

### Phase 4: Confidence Engine (2-3 SP)

**Why this exists:** Per-trade risk adjustment based on signal strength + market conditions. Fine-tunes signals depending on conditions.

**Deliverable:** Working confidence engine integrated with risk layer.

**Acceptance criteria:**
- Confidence score per signal (0-1 scale)
- Risk sizing scales with confidence
- Market condition awareness (volatility, trend, news)
- Guardrails: max risk cap, min confidence floor
- Backtest showing confidence-adjusted risk improves Sharpe vs. fixed sizing

### Phase 5: Hayate Self-Healing Layer (2-3 SP)

**Why this exists:** Tiered auto-remediation. L0=read-only, L1=process restart, L2=parameter tweak within guards, L3=disable strategy, L4=code change (NEVER auto, always card). Each tier needs explicit guards and rollback. Escalation not retry (max 2 attempts).

**Deliverable:** Hayate operational with self-healing capabilities. Deep issues → Tsukasa card. Simple issues handled autonomously.

**Acceptance criteria:**
- Tiered blast radius implemented (L0-L4)
- Per-tier guards defined
- Escalation rule: 2 failed retries → card
- Runbooks executable as scripts
- Self-test: Hayate's own health monitored (last successful audit timestamp)
- Forward test "down" → auto-restart (L1) with rollback on failure

### Phase 6: Daily Audit + North-Star Tracking (1-2 SP)

**Why this exists:** Hayate daily audit at 1-4pm EDT. Drift detection on workboard and quest phases. Daily digest from Ava.

**Deliverable:** Daily audit cron, drift detection, daily Ava digest, kanban hygiene routines.

**Acceptance criteria:**
- Hayate daily audit cron at 1-4pm EDT window
- Drift detection: card "in progress" >7d → flag, >14d → escalate
- Phase drift detection: 5d no activity → flag, 10d → surface
- Daily Ava digest (3 bullets: what moved, what's blocked, what needs Craig)
- Kanban hygiene: archive done >72h, surface stale, reassign orphans
- Self-healer of self-healer: Hayate's own audit presence monitored

### Phase 7: FTMO Forward Test Run (1-2 SP)

**Why this exists:** The actual gauntlet. Run forward test under FTMO rules.

**Deliverable:** Forward test passing FTMO criteria.

**Acceptance criteria:**
- Forward test running under FTMO rules/restrictions
- 30+ consecutive compliant days
- Self-healing operational during run
- Daily reports to Craig
- P&L meeting FTMO targets within drawdown limits

---

## Phase Dependencies & Parallelization

```
1A (arch audit) ────┐
                    ├──→ Phase 2 (infra) ──→ Phase 3 (strategy R&D) ──→ Phase 4 (confidence) ──┐
1B (checkpoints) ───┘                                                                              ├──→ Phase 7 (FTMO run)
                                                  Phase 5 (self-healing) ──→ Phase 6 (daily audit) ┘
```

- Phase 1A and 1B run parallel
- Phase 2 can start once 1A completes (uses audit findings)
- Phase 5 (self-healing) can start as soon as 1B completes (uses checkpoint design)
- Phase 6 depends on Phase 5
- Phase 7 is gated on Phases 1-4 done + 5-6 done

**Realistic timeline:** 6-10 weeks wall-clock. FTMO forward test itself is 30+ days. Some phases overlap.

---

## Risks (preliminary — council to expand)

| ID | Risk | Severity | Mitigation |
|----|------|----------|------------|
| R1 | Architecture audit reveals fundamental redesign needed, blowing up timeline | High | Run audit early. Be honest if this happens. |
| R2 | Strategy R&D doesn't find winning combinations in available time | High | Lower bar: 1 profitable strategy beats 10 broken ones. |
| R3 | Self-healing adds complexity that creates new failure modes | Medium | Tiered blast radius, exhaustive testing of runbooks before activation. |
| R4 | Forward test fails FTMO criteria despite passing internal metrics | Medium | Pre-FTMO dry runs on demo. Realistic backtest vs forward expectations. |
| R5 | Drift/momentum system itself becomes stale | Medium | Hayate monitors Hayate. Daily Ava digest is structural, not aspirational. |

---

## Open Questions for Council

1. **Architecture audit depth:** Surface-level code review or deep audit including paper trading validation?
2. **Strategy mix ratios:** Any guidance on grid/swing/scalp balance for FTMO? FTMO rules favor consistency — does that bias the mix?
3. **Confidence engine primitives:** Is per-trade confidence the right primitive, or should there be per-strategy confidence, per-symbol, etc.?
4. **Self-healing test surface:** How do we test that self-healing works without breaking a real forward test?
5. **FTMO forward test scope:** What rules specifically? Are we modeling daily loss limit, max drawdown, profit target correctly?
6. **Daily digest format:** 3 bullets — is that the right shape, or should it be richer?
7. **Phase 1A + 1B parallel:** Does the council see risk in this, or does it make sense?

---

## Council Review Assignments

- **Kaito** (systems audit): Phase structure coherence. Architectural concerns with modularization. Resource cap sanity. Where could the build fail technically?
- **Rei** (devil's advocate): Biggest unstated assumptions. Single point of failure if one assumption is wrong. Worst-case realistic outcome. What are we missing?
- **Sora** (trading domain): Strategy R&D approach. Confidence engine primitive correctness. Symbol expansion. Strategy mix for FTMO. Backtest vs forward gap.

**Output path:** `/root/.openclaw/council-workspace/data/reviews/quest-ayumi-ftmo-{name}-2026-07-07.md`

**Constraint:** Review only. No workboard or card modifications.

---

## Drift Detection & Momentum (baked into design)

1. **Workboard drift:** Card "in progress" >7d without heartbeat → auto-flag to Ava. >14d → escalates to Craig.
2. **Phase drift:** Phase "in progress" with zero activity >5d → flagged. >10d → surface to Craig before starting new work.
3. **Daily Ava digest:** 3 bullets each evening — what moved, what's blocked, what needs Craig.
4. **No new work on stale work:** If 3 cards drifting, no new claims until they're shipped, stalled, or dropped.

---

*Last updated: 2026-07-07 23:45 EDT — draft for council review*