# Strategy Factory — Restructured Plan (Post-Council)

**Status:** Draft for Craig review
**Date:** 2026-08-02
**Council consultation:** Nora, Kaito, Mika (2026-08-02)
**Parent spec:** `docs/roadmaps/strategy-factory/strategy-factory-implementation-spec.md` (803 lines, Tsubaki)
**Craig decisions:** Q1=B (regime-blind baseline dual-pass), Q2=A (split auto-replacement), Q3=A (4 workers constrained)

---

## Restructured Phase Plan

### Phase 0 — Regime Detector Validation (NEW)

**Trigger:** Council consensus that regime detector is the largest blast-radius component.
**Craig decision:** Q1=B — run sweep twice (regime-blind + regime-filtered), compare.

| Item | SP | Days |
|---|---|---|
| 0.1 Validate regime detector on known historical transitions (2020 COVID crash, 2022 Fed rate shock, 2023 yen carry unwind). Label accuracy must be ≥70% on transition periods. | 1.0 | 1 |
| 0.2 If accuracy <70%, tune detector parameters (WINDOW, ATR percentile thresholds, ADX thresholds) until minimum is met OR escalate to Craig with evidence | 0.5 | 0.5 |
| 0.3 Regime label distribution audit: verify all 4 labels (TRENDING, CHOPPY, VOLATILE, QUIET) have ≥15% representation across 2020-2026 | 0.5 | 0.5 |
| 0.4 Write regime validation report with per-event confusion matrix | 0.5 | 0.5 |

**Total Phase 0: 2.5 SP / ~2.5 days**

**Acceptance gate:**
- [ ] Detector accuracy ≥70% on 3+ known transition events
- [ ] All 4 regime labels have ≥15% distribution
- [ ] Report at `docs/factory/regime-validation-YYYY-MM-DD.md`
- [ ] If accuracy <70% after tuning: STOP, surface to Craig

---

### Phase A — Pipeline Assembly + Template Library (Parallel)

**Scope:** Wire existing components into factory driver AND build template library. Two lanes run in parallel.

**Lane A1: Pipeline (Strategy)**

| Item | SP | Days |
|---|---|---|
| A1.1 Implement OOS isolation in factory driver (last 6 months held out, `--unlock-oos` requires confirmation string, not just flag) | 0.5 | 0.5 |
| A1.2 Wire `run_blend_walkforward_for_dsr.py` into factory orchestrator CLI (`factory/run_factory.py`) | 1.0 | 1 |
| A1.3 Add `factory_runs` + `deploy_pool` DuckDB tables + schema (`factory/schema.sql`) | 0.5 | 0.5 |
| A1.4 Wire DSR annotation + tier rank + REJECT logging into factory driver | 0.5 | 0.5 |
| A1.5 Implement dual-mode regime support: `--regime-filter enabled\|disabled\|both` (runs sweep twice when `both`, stores results with regime_mode tag) | 1.0 | 1 |
| A1.6 Smoke run: 6 existing strategies × 1 pair × 1 TF × both regime modes = 12 cells; verify JSONL→DuckDB | 0.5 | 0.5 |

**Lane A2: Templates (Strategy)**

| Item | SP | Days |
|---|---|---|
| A2.1 Implement `StrategyTemplate` abstract base class + `ParamSpec` + `FactoryRegistry` | 1.0 | 1 |
| A2.2 Implement 5 archetype templates (momentum, mean_reversion, breakout, trend_following, session_based) | 4.0 | 3 |
| A2.3 Round-trip validation: each template instantiated with default params must produce IDENTICAL trade output to the original strategy on same data | 1.0 | 1 |
| A2.4 Tests: each template produces ≥1 valid strategy; Optuna can sample param_space | 1.0 | 1 |

**Lane A3: Tests (Tsubaki)**

| Item | SP | Days |
|---|---|---|
| A3.1 Unit tests: OOS isolation (date boundary leakage), tier rank edge cases, dual-regime-mode tagging | 1.0 | 1 |
| A3.2 Integration test: full pipeline on 6 strategies × 1 pair, both regime modes | 0.5 | 0.5 |

**Total Phase A: 12.0 SP / ~5 days (parallel lanes)**

**Acceptance gate:**
- [ ] Factory driver runs `python3 -m factory.run_factory --pilot --regime-filter both` end-to-end
- [ ] OOS isolation: date boundary test passes; `--unlock-oos` requires typed confirmation
- [ ] DSR tier assigned for every cell; REJECT cells logged with reason
- [ ] Round-trip test: all 5 templates reproduce original strategy trades exactly
- [ ] Dual-mode: regime-filtered and regime-blind results stored with `regime_mode` tag
- [ ] No regressions in existing test suite (6,450 tests)

---

### Phase B — Pilot Sweep (~80 cells, dual-pass)

**Scope:** Run the factory against a reduced matrix to validate the pipeline end-to-end and produce the regime-filtered vs regime-blind comparison.

| Item | SP | Days |
|---|---|---|
| B.1 Pilot sweep: 5 templates × 4 pairs × 2 TF × 2 regime modes (enabled + disabled) = 80 baseline cells × 2 = 160 regime-paired cells, 20 Optuna trials each | 2.0 | 2 |
| B.2 PBO computation for all Optuna-derived params | 0.5 | 0.5 |
| B.3 Regime comparison analysis: for each template×pair×TF cell, compare DSR tier under regime-filtered vs regime-blind. Pre-registered decision rule: regime gating is kept ONLY if it improves OOS Sharpe by >15% across ≥60% of cells | 1.0 | 1 |
| B.4 Pilot report with per-cell breakdown + regime comparison verdict | 0.5 | 0.5 |

**Total Phase B: 4.0 SP / ~4 days (including ~4h compute)**

**Acceptance gate:**
- [ ] Sweep completes within 6 hours wall-clock (4 workers, 160 cells)
- [ ] Regime comparison verdict: keep regime gating, drop it, or mixed (per-cell)
- [ ] If 0 cells produce Tier A/B in BOTH regime modes: pause factory, trigger Plan B review
- [ ] Forward test tick latency remained normal during sweep (no host contention)

---

### Phase C — Full Sweep (Go/No-Go Gate)

**Scope:** Full sweep with regime decision from Phase B applied. Target ≥3 Tier A/B.

| Item | SP | Days |
|---|---|---|
| C.1 Full sweep: 5 templates × 4 pairs × 2 TF × 50 trials = 1000 cells (regime mode per Phase B verdict) | 3.0 | 3 |
| C.2 Confirmation re-run: top 10 candidates re-validated with 100-trial Optuna + fresh random seed + MC stress test | 2.0 | 2 |
| C.3 Selection report: best candidates with full metrics, regime breakdown, correlation matrix | 1.0 | 1 |

**Total Phase C: 6.0 SP / ~6 days (including ~12h compute)**

**GO/NO-GO GATE:**
- [ ] ≥3 Tier A/B candidates confirmed by re-run
- [ ] PBO < 0.30 for all promoted candidates
- [ ] Pairwise correlation < 0.7 among top candidates
- [ ] Confirmation re-run reproduces DSR tiers within ±0.05 p-value
- [ ] **If <3 candidates: STOP. Surface to Craig with full report + Plan B options.**

---

### Phase D — Deploy + Monitor (Decay Alert-Only)

**Scope:** Deploy validated blend. Decay detector ships as ALERT-ONLY. Auto-replacement is deferred.

| Item | SP | Days |
|---|---|---|
| D.1 Wire blend driver to use deploy_pool composition + tier weights (Tier A: 50%, B: 30%, C: 20%) | 1.0 | 1 |
| D.2 Decay detector (rolling 60d Sharpe + DD + trade count) — alert-only, writes to decay_log + sends notification, NO automatic action | 1.5 | 1.5 |
| D.3 Paper test for 5 trading days with no execution errors | 0.5 | 5 (calendar) |
| D.4 Go live with tier weights, FTMO guard wired (daily DD, trailing drawdown, kill switch) | 1.0 | 1 |
| D.5 Add deploy_pool state + decay alerts to Hayate daily audit | 0.5 | 0.5 |
| D.6 Tests: decay alert triggers, tier weight calculation, FTMO guard thresholds | 1.0 | 1 |

**Total Phase D: 5.5 SP / ~8 calendar days (including 5-day paper test)**

**Acceptance gate:**
- [ ] 5 clean paper-trading days, zero execution errors
- [ ] Decay detector emits HEALTHY/WATCH/DECAY_ALERT for each deploy_pool member
- [ ] FTMO guard: daily DD tracking, 3% kill switch armed
- [ ] Daily audit includes deploy_pool state

**Auto-replacement gate (deferred):**
- [ ] After 14 trading days of stable decay detection evidence, separate go/no-go decision to activate auto-replacement
- [ ] Auto-replacement requires: cooldown ≥24h, max 1 replacement per 24h, manual go decision

---

### Phase E — Continuous Operation + Learning Feedback

**Scope:** Scheduling, dashboards, and the feedback loop from deployment back into template evolution.

| Item | SP | Days |
|---|---|---|
| E.1 OpenClaw cron: weekly pilot sweep (Sat 04:00 ET) | 0.5 | 0.5 |
| E.2 OpenClaw cron: monthly full sweep (1st Sun 02:00 ET) | 0.5 | 0.5 |
| E.3 Per-sweep report generator (markdown) | 0.5 | 0.5 |
| E.4 Learning feedback: deployed strategy performance → template param_space tuning hints (advisory, not automatic) | 1.5 | 1.5 |
| E.5 Runbook: `docs/runbooks/strategy-factory-runbook.md` | 1.0 | 1 |

**Total Phase E: 4.0 SP / ~4 days**

---

### Summary

| Phase | SP | Calendar | Key Gate |
|---|---|---|---|
| 0: Regime Validation | 2.5 | 2.5d | Detector ≥70% accuracy on transitions |
| A: Pipeline + Templates (parallel) | 12.0 | 5d | Round-trip + dual-mode smoke test |
| B: Pilot Sweep (dual-pass) | 4.0 | 4d | Regime verdict + pipeline validated |
| C: Full Sweep | 6.0 | 6d | ≥3 Tier A/B OR stop |
| D: Deploy + Monitor | 5.5 | 8d | 5 clean paper days + live |
| E: Continuous Operation | 4.0 | 4d | Cron + feedback loop |
| **Total** | **34.0** | **~29.5d (5-6 weeks)** | |

**With BQES overhead (+20%): ~40 SP / ~6 weeks realistic**

---

## Risk Assessment (Ranked Most → Least Risky)

### R1. Regime Detector Dual-Pass Ambiguity (CRITICAL)

**What:** Craig chose dual-pass (regime-blind + regime-filtered). The comparison between the two modes could produce ambiguous results — regime helps some templates, hurts others. The >15% OOS Sharpe improvement threshold is pre-registered but arbitrary. If the result is mixed, we face a judgment call with no clear right answer.

**Why it's #1:** The regime decision cascades into every downstream phase. Template design, sweep filtering, decay detection, and deployment allocation all depend on it. A wrong call here wastes weeks.

**Mitigations added to plan:**
- Phase 0 validates the detector BEFORE the dual-pass. If the detector can't label transitions ≥70% accuracy, the dual-pass is meaningless.
- Pre-registered decision rule in B.3: keep regime gating ONLY if >15% Sharpe improvement across ≥60% of cells. Mixed results (<60% improvement) → regime gating dropped (simpler pipeline wins).
- Phase B budget includes time for the comparison analysis (1.0 SP, not an afterthought).
- Fall-back: if comparison is ambiguous after pilot, default to regime-blind (Kaito's recommendation — simpler, fewer coupling points).

---

### R2. Template Abstraction Leakage (CRITICAL)

**What:** Templates wrap existing ISignalStrategy classes. The wrapping could subtly change behavior — different bar handling, spread application, session filtering, or indicator initialization. A wrapped strategy that produces different trades than the original invalidates all backtest comparisons.

**Why it's #2:** If templates don't faithfully reproduce original strategy behavior, the entire factory produces results disconnected from reality. This bug is silent — trades look reasonable, just different from what they should be.

**Mitigations added to plan:**
- A2.3 Round-trip validation is a HARD GATE: each template instantiated with default params must produce byte-identical trade output to the original strategy. This runs BEFORE any sweep.
- Test runs on 3 pairs × 2 timeframes with ≥100 bars.
- Any mismatch blocks Phase A exit.

---

### R3. Statistical False Discovery at Scale (HIGH)

**What:** 800-1000 cells with DSR at n_trials=2400. The 6/6 prior kill rate suggests the underlying strategies have no genuine edge. The factory could produce 0 survivors — or worse, 1-2 false positives that pass DSR by chance at the tail of the distribution.

**Why it's #3:** No amount of pipeline engineering fixes the absence of alpha. If the template space doesn't contain edge, the factory is a very sophisticated way to discover nothing.

**Mitigations added to plan:**
- Phase C confirmation re-run with fresh random seed (C.2). False positives won't reproduce.
- PBO < 0.30 as second gate (not just DSR).
- Pairwise correlation < 0.7 cap prevents deploying 3 "different" strategies that are actually the same trade.
- Hard go/no-go gate at Phase C: <3 survivors = STOP, not "try harder."
- Plan B documented in `docs/decisions/plan-b-statistical-failure.md` — expand to more pairs, different timeframes, or pause factory.

---

### R4. Optuna Search Space Misspecification (HIGH)

**What:** Each template defines its param_space. Too narrow → Optuna can't explore. Too wide → most trials are garbage. Parameter interactions (ATR period × ATR multiplier) can create non-linear failure modes. The spaces are designed from theory, not empirical validation.

**Why it's #4:** A misspecified search space means the factory explores the wrong neighborhood. You can't find edge in a region you're not searching.

**Mitigations added to plan:**
- Phase B pilot (80 cells × 20 trials) doubles as search-space validation. If no cell produces >0.5 Sharpe, the param space needs redesign before Phase C.
- Use Optuna's `param_importance` after pilot to identify irrelevant parameters. Drop them from Phase C.
- Wide/narrow variants tested on 1 template × 1 pair in A2.4.

---

### R5. Compute Contention / Host Stability (MEDIUM-HIGH)

**What:** 4 workers (reduced from 8) + nice/cpulimit, but host runs gateway + forward test + cron. 59GB DuckDB market data. I/O contention and memory pressure are realistic.

**Why it's #5:** A destabilized forward test means missed ticks, missed entries, or stale data — operational risk to any live trading.

**Mitigations added to plan:**
- Worker count capped at 4 (Craig approved).
- **CPU cap: 15% per worker** (`cpulimit -l 15`, down from 20% per Craig directive).
- `nice -n 19` on all factory processes.
- Forward test tick latency monitoring during sweeps — auto-pause if latency > 2s.
- DuckDB: `threads=1`, `memory_limit=384MB` per worker (down from 512MB).
- DuckDB read-only connections for factory workers (no write contention with forward test).
- Factory sweeps scheduled weekends / off-hours when possible.
- Per-cell 600s hard timeout prevents runaway processes.
- **Memory budget:** 4 workers × ~384MB DuckDB + ~256MB Python overhead = ~2.6GB compute, well within 31GB total.
- **Memory guard:** parent process monitors RSS; any worker exceeding 1GB is killed + logged.
- **CPU guard:** parent process samples `/proc/<pid>/stat` utime+stime every 30s; if average >18% over 60s window, worker is killed + logged.
- Crash recovery: worker failure writes to `factory_failures` table; pool continues with remaining workers.

---

### R6. OOS Isolation Enforcement (MEDIUM)

**What:** Last 6 months held out from optimization. Enforcement is software-based (`--unlock-oos` flag + date boundary check). Bugs in date boundary calculation could leak OOS data. Optuna could implicitly learn from OOS via precomputed regime labels or feature caches.

**Why it's #6:** OOS contamination invalidates all results silently. But it's a well-understood risk with established mitigation patterns.

**Mitigations added to plan:**
- A1.1: `--unlock-oos` requires typed confirmation string, not just flag presence.
- A3.1: Unit test for date boundary leakage (off-by-one, timezone, DST transitions).
- Data-layer assertion: chronological check in the loader, not just the factory driver.
- Regime label cache keyed by date range — labels generated only for train/val/test windows, never OOS.

---

### R7. Walk-Forward Window Calibration (MEDIUM)

**What:** 5 windows, 70/15/15 split, embargo 96 bars (M15). Windows could be dominated by a single regime. Trade counts per window could fall below the 15-trade warning threshold.

**Why it's #7:** Bad window config produces noisy statistics. But the config is close to established defaults and the issue is detectable.

**Mitigations added to plan:**
- Phase B pilot includes per-window regime distribution audit.
- Windows with >80% single regime flagged in report.
- Trade count <15 per window → WARNING, not silent pass.
- Embargo tested with autocorrelation check on trade residuals.

---

### R8. Decay Detector False Positives (MEDIUM → LOW after split)

**What:** Rolling 60-day thresholds could trigger on normal drawdown cycles. Baseline Sharpe from backtest may not match live conditions.

**Why it's #8 (lower after Craig's Q2=A split):** Alert-only mode means false positives are annoying, not capital-destroying. 14-day observation period before auto-replacement activation gives calibration data.

**Mitigations added to plan:**
- Alert-only for first 14 trading days (Craig approved Q2=A).
- Require 2 of 3 metrics (Sharpe + DD + trade count) to trigger, not just 1.
- Calibrate thresholds against backtest drawdown distribution during Phase D.3 paper test.
- Auto-replacement activation is a separate go/no-go decision with evidence.

---

### R9. DuckDB Concurrency / Storage Integrity (LOW-MEDIUM)

**What:** Factory writes to `factory.duckdb` while forward test reads `ayumi_market.duckdb`. Different files, so no direct write contention. But partial writes during crashes could corrupt factory results.

**Why it's #9:** Separate files mostly isolate the risk. DuckDB is ACID-compliant for single-writer.

**Mitigations added to plan:**
- Factory and forward test use different DuckDB files (already planned).
- WAL mode for factory DB.
- Crash recovery: verify DB integrity on factory startup.
- All writes in explicit transactions.
- Checkpoint after each cell completion.

---

### R10. BQES Process Overhead Underestimation (LOW)

**What:** 34.0 SP doesn't include BQES overhead (pre-build checklists, post-mortems, code review cycles). Real effort is ~40 SP.

**Why it's #10 (lowest):** Process overhead is predictable and manageable. It extends timeline but doesn't introduce technical risk.

**Mitigations added to plan:**
- Realistic calendar: 5-6 weeks, not 4-5.
- Front-load BQES infrastructure in Phase 0.
- Batch Rin code review across Phase A components (parallel lanes).
- Post-mortem template ready before Phase A starts.

---

*End of restructured plan. Ready for Craig review.*
