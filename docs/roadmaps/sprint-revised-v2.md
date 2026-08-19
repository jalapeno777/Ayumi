# Revised Strategy Factory Queue — Council-Reviewed
**Date:** 2026-07-22
**Status:** DRAFT — pending Craig approval
**Council confidence:** Unanimous REVISE → this plan incorporates all feedback

---

## What the Council Caught

1. **Compute math doesn't work.** Even charitable estimates show 5-14x oversubscription at 20% CPU cap with 2 builders. The original 5-track, 15-item sprint cannot finish in 48h.
2. **Overfit risk is severe.** 30 Optuna trials × N strategies × M symbols × K regimes = hundreds of parameter combinations on 5,000 effective bars. Multiple testing correction needed. Nested optimization (params → blend weights → FTMO target) compounds overfit.
3. **Tracks aren't parallel.** Hidden dependencies: A1→A2→B3 (harvest blocks FX params blocks FX strategies), D1→C1 (regime labels blocks optimization), C1→C2 (per-strategy sweeps block blend weights).
4. **Regime gate IS the alpha.** Strategies lose in isolation (PF=0.72). The gate filters 97% of trades to produce PF=1.74. Transferring this gate to FX pairs and new strategies is the single biggest unvalidated assumption.
5. **3/5 walk-forward windows passing = 40% failure rate.** This is a warning, not a baseline.

---

## Revised Plan: Continuous Queue Model

**Principle:** One item at a time. Run it, record results, move to next. No parallel optimization. No sprint deadline. Build incrementally.

**Success criteria:** Portfolio blend PF>1.15, DD<10%, daily DD<5%, ≥250 trades/year, walk-forward ≥4/5 windows pass.

### Queue (strictly ordered)

#### Q1: Validate Current Blend with Realistic Costs
**Why first:** Council showed the gated blend backtest may use 0.3 pip spread (forward test config) vs the 2.5 pip default. Must know if the edge survives realistic costs before expanding.
**Action:** Re-run gated blend backtest with spread=2.5, commission=$3.5/lot, slippage=0.2 on XAUUSD. Compare PF, net, DD to the 0.3-pip version.
**Time:** ~30 min compute
**Pass:** PF>1.15 with realistic costs → proceed to Q2
**Fail:** PF≤1.15 → tighten regime gates further before expanding; the edge is cost-sensitive

#### Q2: Gate Loosening Study (Close Volume Gap WITHOUT New Strategies)
**Why second:** Rei's key insight — the 7x volume gap might be closeable by loosening existing gates rather than adding strategies. Cheaper, faster, lower overfit risk.
**Action:** Systematically loosen each strategy's regime gate constraints by one notch at a time (e.g., KZ: ADX range [18,25]→[15,28], session expansion). Measure trade count + PF at each step. Find the Pareto frontier.
**Time:** ~2h compute
**Pass:** ≥100 trades/year at PF>1.2 → massive win, minimal effort
**Fail:** Volume doesn't scale or PF drops below 1.0 → proceed to Q3

#### Q3: USDJPY Profile + Validate (When Harvest Completes)
**Why third:** Symbol expansion is the highest-EV path to more trades, but only if the regime gate transfers. USDJPY is closest to XAUUSD in volatility character.
**Action:** Wait for harvest completion. Aggregate ticks to M15/H1 bars. Run regime profiling (same methodology as XAUUSD). Run gated blend backtest on USDJPY with XAUUSD-tuned gates. Measure trade count + PF.
**Time:** ~1h after harvest completes
**Pass:** PF>1.15 on USDJPY → add to blend, re-measure portfolio
**Fail:** PF≤1.15 → USDJPY needs its own gate tuning (card it for later, don't block queue)

#### Q4: Build B.3 London Breakout (XAUUSD-only, Single Strategy)
**Why fourth:** One new strategy, validated on XAUUSD where we have data, before attempting FX-native variants. Expected 30-50 trades/year.
**Action:** Build London Breakout Retest strategy. Implement ISignalStrategy interface. Smoke test on 5000 XAUUSD M15 bars. Full backtest with regime gates. Measure incremental trades + PF contribution to blend.
**Time:** ~3-4h (build + test)
**Pass:** Adds ≥30 trades/year at portfolio PF>1.15 → add to blend
**Fail:** 0 trades or PF drag → parameter adjustment, then defer if still failing

#### Q5: FX-Native Strategy Variants (EURUSD + GBPUSD)
**Why fifth:** FX expansion requires purpose-built strategies, not retuned XAUUSD params. Council was clear: regime gates don't transfer.
**Action:** Design KZ variant with FX-appropriate session windows (London/NY overlap), pip values, ATR thresholds. Build, test on EURUSD M15. Repeat for GBPUSD if EURUSD shows edge.
**Time:** ~4-6h per variant
**Pass:** PF>1.15 on FX pair → add to blend
**Fail:** No edge → confirm XAUUSD-only thesis, focus on optimization

#### Q6: Optuna Parameter Optimization (XAUUSD Only, Conservative)
**Why sixth:** Only after we have a stable multi-strategy blend. Optuna optimizes the BLEND, not individual strategies in isolation.
**Action:**
- Optimize per-strategy params on XAUUSD only (3-4 strategies max)
- Use 15 trials (not 30) — council showed 30 is noise-fitting on 5k bars
- Objective: blend Sharpe ratio with DD penalty (not raw PF)
- Walk-forward INSIDE each trial (not just at the end)
- Bonferroni correction: significance threshold = 0.05 / (15 × N_strategies)
**Time:** ~4-6h compute
**Pass:** Improvement over unoptimized blend at PF>1.15 → ship
**Fail:** No improvement → ship unoptimized blend, defer optimization

#### Q7: Confidence Engine (Post-Blend-Stable)
**Why last:** Confidence engine needs a stable strategy set to train on. If strategies change, the ML model needs retraining.
**Action:** Wire regime detector in shadow mode. Train RandomForest confidence learner on historical blend signals. Add spread/volatility/session gates. Measure false-positive rate.
**Time:** ~4-6h
**Pass:** Confidence gates reduce false signals by ≥20% → wire into forward test
**Fail:** No improvement → defer, ship without confidence layer

---

## Risk Mitigations (Council Requirements)

| Risk | Mitigation |
|------|------------|
| Overfit via Optuna | 15 trials max (not 30), walk-forward inside each trial, Bonferroni correction |
| Regime gate doesn't transfer to FX | Test on USDJPY first (closest to XAUUSD). FX-native variants are separate builds, not retunes |
| USDJPY harvest stalls | Q3 unblocks immediately when harvest completes; queue continues with Q4 in the meantime |
| Strategy crowding | Cap at 2 concurrent positions per symbol. Blend weight optimization includes correlation penalty |
| Cost sensitivity | Q1 validates with realistic costs BEFORE any expansion |
| Compute budget | One item at a time. No parallel sweeps. Each item has explicit time estimate |

---

## What Was Cut From Original Plan

- ❌ All 5 tracks running in parallel → ✅ Sequential queue
- ❌ 48-hour deadline → ✅ Continuous, one-at-a-time
- ❌ 4 new strategies in 48h → ✅ 1 new strategy (B.3), then iterate
- ❌ 30 Optuna trials × all symbols × all regimes → ✅ 15 trials, XAUUSD only, blend-level
- ❌ FX retuning (retuning XAUUSD params for FX) → ✅ FX-native variant builds (separate code)
- ❌ Confidence engine as parallel track → ✅ Deferred to Q7 (post-blend-stable)
- ❌ Risk infra as parallel track → ✅ Already wired in forward test; enhance incrementally

---

## Confidence Assessment

| Factor | Confidence | Reasoning |
|--------|------------|-----------|
| Current blend edge is real | 80% | PF=1.74 is strong but cost assumptions need validation (Q1) |
| Gate loosening closes some volume gap | 70% | Rei's argument is sound — Pareto frontier exists |
| USDJPY adds trades | 60% | Depends on regime gate transferability |
| B.3 London Breakout works | 50% | New strategy, unvalidated |
| FX-native variants work | 30% | Council was skeptical; FX showed zero edge with current approach |
| Optuna improves blend | 40% | High overfit risk on limited data |
| **Overall plan confidence** | **~72%** | **Sequential, validated at each step, with explicit fallbacks** |

**Path to 96%+ confidence:** Execute Q1-Q2 first (2-3 hours compute). If the blend survives realistic costs AND gate loosening adds volume, we're on solid ground before expanding. If either fails, we've saved 40+ hours of wasted optimization.

---

## Craig's Decision Points

1. **Approve queue model?** (sequential vs sprint)
2. **Q1 first?** (validate with realistic costs before anything else)
3. **Q2 gate loosening?** (try closing volume gap without new strategies first)
