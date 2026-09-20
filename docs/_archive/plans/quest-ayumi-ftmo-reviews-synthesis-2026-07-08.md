# Quest Review Synthesis — Ayumi FTMO Path (2026-07-07)
**Ava (orchestrator) — 2026-07-08**

Three reviewers, all **APPROVE-WITH-FINDINGS**. The plan is structurally sound for an operational-layer reset but underestimates the strategy-validity problem and over-pitches Phase 3. ~5 SP of revisions + Craig decisions needed before sprint dispatch.

**Per-reviewer confidence the plan passes FTMO as written:**
- Rei (devil's advocate): **0.25** — "will most likely run 8–10 weeks, ship a clean operational layer, and fail Phase 7 because no strategy has been shown to be FTMO-passable."
- Sora (trading domain): implicit "directionally right, sequenced wrong" — recommends scope down to XAUUSD-only before any portfolio expansion
- Kaito (implementation auditor): implicit "proceed with 8 must-fix findings" — primarily code/architecture concerns

---

## Consensus Findings (all 3 reviewers raised these)

### 1. **FTMO risk config is inconsistent across the codebase** (BLOCKING)
Five separate definitions disagree on daily-loss / total-DD / max-positions. FTMO 1-Step = 3% / 10%; the code sits at 4% / 7% (YAML), 5% / 10% (FTMOConfig default), and 7% total-DD (SLPositionSizer). Pick one canonical source. **All three reviewers independently raised this.**

### 2. **The plan's central premise is wrong**
Plan treats "10 strategies, 0 trades" as a coordination problem. **Sora** (with evidence) and **Kaito** both note: the forward test is generating signals (10 generated, 2 traded, 2 `signals_failed_live` per hb#33). Bottleneck is **live-execution bugs** (balance oscillation card 4b5205be, USDJPY TP 100x card 35f550e8, Amend SL/TP timeouts, uncommitted `signals_failed_live` reconciliation defense), not strategy R&D. Phase 1A should focus audit on the execution path first.

### 3. **Phase 3 over-pitches — "1 strategy per category" is unreachable on current data**
Per Sora's read of the **2026-07-03 SRMR+ walk-forward revalidation report**: only **XAUUSD passes** (5/5 windows, PF 8.0, Sharpe 13.68, max DD 0.60%). USDJPY is borderline (1/5, Sharpe -0.01). **EURUSD and GBPUSD are NO-GO at H1 resolution.** The plan treats Phase 3 as greenfield when the WF report explicitly recommends "scope down to XAUUSD-only for the MVP forward-test shortlist." Per Rei, the plan's Phase 3 budget (4–5 SP, 3 weeks) is wildly insufficient given the team's 3-month history of failing to find profitable strategies.

### 4. **Phase 4's per-trade confidence is the wrong primitive**
Sora: per-trade confidence is a downstream filter, not a sizing primitive. FTMO rewards realized edge per (strategy, symbol, regime) bucket. **Re-frame Phase 4 as "edge-weighted risk allocator"** with rolling realized R-multiple expectancy feeding `sl_position_sizer.risk_per_trade_pct`.

### 5. **Existing infrastructure should be referenced, not duplicated** (Kaito primary)
The plan proposes DRY_RUN, L0–L4 tiers, paper-broker simulator, drift detector, structured heartbeat — most of which already exist under different names:
- `ForwardTestConfig.live_mode` + `execution_mode` (consistency check at forward_test_engine.py:117-138)
- `PaperTrader` (adapters/ctrader/paper_trader.py)
- `AnomalyMonitor` (engine/anomaly_monitor.py — already detects data_silence, zero_signals, zero_pnl_variance)
- `HealthMonitor` (engine/health_monitor.py — already emits `[B5 Health]` / `[S1 Health]`)
- `KillSwitchManager` (adapters/ctrader/kill_switch.py — `kill`, `freeze`, per-strategy freeze)
- `remediation_validated.flag` (already populated, auto-recreating)
- `common/resource_limits.py` (cpu_limited, memory_capped — exist but **not used by any production script**)
- `data/forward_test.pid` (single-process lock, not referenced)

### 6. **Self-healing tier model is upside-down for the actual failure surface** (Rei primary)
12 of the last 13 documented failure modes are **code-level bugs**, not operational drift. The plan's L2/L3 (parameter tweak / strategy disable) would mask them while the underlying correctness bug continues to corrupt trades. **Required guard: L2/L3 must check git log for recent commits to the affected file; if a code change has been merged in the last 7 days, escalate to L4 (card) regardless of tier.**

### 7. **Resource caps are aspirational until wired** (Kaito)
Plan says "CPU 20%, memory 2GB" but `cpu_limited` / `memory_capped` are only used by `conftest.py`. No `scripts/run_*.py` wraps its `main()`. Optuna sweep runner uses `ProcessPoolExecutor` with no resource limits. **Needs an explicit PR that wires the limiters into every runner script.**

### 8. **Five-engine duplication unaddressed** (Kaito primary)
Phase 2 of the plan risks adding a 6th engine on top of the existing 5 (`ForwardTestEngine`, `TradingOrchestrator`, `MultiStrategyOrchestrator`, `SignalOrchestrator`, `BlendForwardTestRunner`). Kai's 2026-04-17 codebase assessment flagged this as critical; the 2026-04-24 state audit confirmed "two forward test architectures exist." **Phase 2 needs a consolidation plan, not just "modularize."**

---

## Reviewer-Specific High-Priority Items

### Kaito (8 findings, all blocking before sprint execution)
1. **MUST:** Declare canonical engine + consolidation path before Phase 2
2. **MUST:** Reconcile 3+ FTMO risk-config sources (pick 1-Step: 3%/10%)
3. **MUST:** Inventory + reference existing monitoring (AnomalyMonitor, HealthMonitor, KillSwitchManager)
4. **MUST:** Wire `cpu_limited` / `memory_capped` into every `scripts/run_*.py` (separate card)
5. Phase 1A: Add acceptance test that distinguishes "engine running" from "real signals firing"
6. Phase 1B: Specify wrap-vs-replace relationship with existing `PaperTrader`
7. Phase 5: Add multi-regime walk-forward (3.5yr H1 bars cover 2020 covid, 2022 inflation, 2024 carry unwind)
8. Phase 7: Replace "variance < 10%" with concrete success criteria (kill switch activations = 0, trade count per session, per-strategy fill latency)
9. **Higher-priority investigation:** `forward_test_health.json` shows account down 6.86% with 0 closed trades — where is the loss coming from?

### Rei (3 SP additional pre-work + 2-3 SP re-spec)
1. **Phase 0 (NEW, 0.5 SP, 1 day):** preconditions — forward test ≥24h stable uptime, `2893597d` flag-deletion fix merged, `data/.credentials` exists 0600, no `.env` builder access, all reliability-sprint cards closed
2. **Phase 1A +1.5 SP:** Strategy qualification sub-gate — numeric walk-forward on current 10 strategies against criteria (Sharpe ≥ 0.5, WR ≥ 55%, ≥3/5 WF windows positive, MaxDD < 5%); documented per-strategy PASS/FAIL/NEEDS-RESEARCH
3. **FTMO rule pinning (0.5 SP):** commit to 1-Step vs 2-Step with rationale, update FTMOConfig defaults, implement best-day rule (50% of positive days' profit — currently absent)
4. **Drift detection calibrated (0.25 SP):** justify 7d/14d/5d/10d against actual sprint cadence (recent sprints = 1–3 days)
5. **Self-healing tier model corrected:** L2/L3 git-log guard, L1 process-restart guard, L3 cold-strategy threshold
6. **Phase 7 entry gate (0.5 SP):** `2c5d684a` live-fire card closed, `2893597d` flag-deletion fix merged, ≥14-day paper-trading sub-gate, demo credentials verified, best-day rule implemented

### Sora (5 priorities + 19 sub-items)
- **P1 (blocking, Phase 1A must surface):**
  1. Reconcile 5 FTMO risk definitions
  2. Investigate 2 `signals_failed_live` with specific commands in §7
  3. Commit or revert the uncommitted `signals_failed_live reconciliation defense` (+10 lines)
  4. Fix `CsvDataLoader.load_parquet.reset_index()` (1-line bug blocking FX-major M15 WF)
- **P2 (Phase 3):**
  5. Adopt WF revalidation recommendation — scope down to XAUUSD-only
  6. Drop "1 strategy per category" acceptance criterion
  7. Disable `srmr_audusd_h1`, `srmr_usdchf_h1`, `srmr_usdcad_h1` (no historical data — latent bug)
  8. Move FX majors to M15 before declaring any strategy NO-GO
- **P3 (risk):** concurrent-risk check, best-day-rule tracker, CET-midnight daily-loss reset
- **P4 (Phase 4 pivot):** edge-weighted risk allocator, lower `live_fire_min_confidence` to 0.55, drop Sharpe-improvement acceptance criterion
- **P5:** consolidate 9 backtest engines → 2, slippage model per-pair, minimum trade count guardrail (15/window), latency model (100ms minimum)

---

## Craig Decisions Needed (4 decisions)

### Decision 1: FTMO rule pinning (Rei + Sora + Kaito)
**Pick one:**
- **A) FTMO 1-Step** (3% daily / 10% total / no min trading days) — recommended by all three; matches team's existing FTMO doc; ICT/SMC-friendly; conservative daily-loss envelope
- **B) FTMO 2-Step** (5% daily / 10% total / 4 min trading days) — looser daily-loss but harder for a system that hasn't shown steady edge
- **C) Defer** until Phase 1A's strategy-qualification sub-gate produces results

### Decision 2: Strategy scope — XAUUSD-only vs full 4-category mix (Sora + Rei)
**Pick one:**
- **A) XAUUSD-only forward test** — recommended by Sora (only validated edge), Rei (Phase 3 budget unrealistic for 4-category); path: validate single-strategy/single-symbol live, then expand
- **B) XAUUSD + USDJPY** — Sora's secondary recommendation if USDJPY SRMR+ retunes to ≥3/5 WF at M15
- **C) 4-category portfolio** (current plan) — REI/Sora both flag as unreachable on current data
- **D) Defer scope decision until after Phase 1A strategy-qualification sub-gate**

### Decision 3: Pre-quest gate (Phase 0, Rei's recommendation)
**Pick one:**
- **A) Add Phase 0 (1 day, 0.5 SP):** preconditions including closing `2c5d684a` live-fire card and `2893597d` flag-deletion FINDING
- **B) Skip Phase 0:** start Phase 1A immediately, accept that pre-existing open cards will block forward test
- **C) Auto-close known blockers first:** close `2c5d684a` and `2893597d` as separate cards before quest starts (more SP, more thorough)

### Decision 4: Plan revision path (process)
**Pick one:**
- **A) I revise the plan now** (~1 SP), incorporating all P1-P2 findings, then re-route to council for review-of-revision, then dispatch builders
- **B) I revise the plan now and dispatch builders in parallel** (faster, but reviewers' findings don't get re-verified)
- **C) Send reviewers' findings to you as a brief, you revise the plan**
- **D) Park the quest, address high-priority debt first** (`2893597d` flag-deletion, `2c5d684a` live-fire, FTMO risk config reconciliation) and revisit the quest in 1 week

---

## Recommended Path (my read)

**Decision 4 → A, then 1 → A, then 2 → A (with B as fallback), then 3 → C.**

Reasoning:
- 1A is the only realistic FTMO target for ICT/SMC and matches existing team doc
- XAUUSD-only is the only validated edge; scope down before expanding
- Closing `2893597d` and `2c5d684a` first is lower-risk than discovering they block the forward test mid-sprint
- Revising the plan before re-dispatch catches the consensus findings once instead of bleeding them into 7 phases of rework
- ~5 SP of revisions is cheap relative to the cost of running a 6-10 week sprint that fails Phase 7

**If Craig approves the recommended path, immediate work:**
1. Close `2893597d` flag-deletion FINDING (Tsukasa card, ~0.5 SP)
2. Close `2c5d684a` TP/SL live-fire verification (operator action on broker — 0.25 SP)
3. Reconcile FTMO risk config (1-Step canonical, ~0.5 SP)
4. Revise plan at `$AYUMI_ROOT/docs/plans/quest-ayumi-ftmo-2026-07-07.md` (~1 SP)
5. Re-route revised plan to council for review-of-revision (3 reviewers, ~30 min)
6. Decompose into sprint cards + dispatch

**Estimated total before sprint starts:** ~3 SP, 3-5 days wall-clock.

---

*Synthesis by Ava — 2026-07-08 — based on Sora, Kaito, Rei reviews*
*Review files: `/root/.openclaw/council-workspace/data/{sora,kaito,rei}-reviews/quest-ayumi-ftmo-2026-07-07.md`*