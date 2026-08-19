# Sprint Plan v2: Trade Volume Expansion → FTMO-Ready Blend
**Goal:** Reach ≥250 trades/year with PF>1.0, DD<10%, daily DD<5%
**Timeline:** 48 hours
**Constraint:** CPU capped at 20%, memory ≤2GB per process, max 2 builders

> **Revised per council review (Kaito/Rei/Mika/Liora).** Key changes:
> - Added Track 0: Loosen existing gates FIRST (Rei's recommendation)
> - Made dependency chain explicit — no fake parallelism (Kaito)
> - Added cut criteria — kill tracks that aren't producing (Mika)
> - Added OOS isolation window — no optimizer touches it (Kaito Loop C)
> - Locked regime detector before Optuna — no label drift (Kaito Loop A)
> - Frozen ML confidence during optimization — no distribution shift (Kaito Loop B)
> - Added spread/slippage cost to backtest (Liora)
> - Reduced scope: 3 tracks instead of 5, explicit kill gates

---

## Ground Rules (Council Mandates)

1. **OOS isolation:** Last 6 months of data (Jan 2026-Jul 2026) is held out. No optimizer touches it. Final validation only.
2. **Regime labels locked:** RegimeDetector config is FROZEN for the entire sprint. No tuning detector params.
3. **ML confidence frozen:** D2 (RandomForest) stays frozen during optimization. Rebuild only on final locked blend.
4. **Spread cost:** All backtests include 3-pip spread on XAUUSD, 1.5-pip on EURUSD/GBPUSD, 1.2-pip on USDJPY. PF must survive spread.
5. **Cut criteria:** If a track hasn't produced measurable progress in 4 hours, kill it and reallocate.

---

## Track 0: Gate Loosening (CHEAPEST, HIGHEST LEVERAGE)
> **Rei's insight:** Before adding strategies, loosen existing gates. Each gate relaxation that maintains PF directly adds trades at zero development cost.

**0.1: Systematic gate relaxation sweep** (inline, 2h)
Current gates reject 96-99% of bars. Test progressively wider gates:
- KZ: ADX [18,25] → try [15,28], [16,30], [18,25]+NY_AM session
- DualTF: {VOLATILE,CHOPPY} → try adding {QUIET}, or removing session restriction
- Donchian: ADX<30 → try ADX<35, ATR_pct<60
- SRMR+: QUIET+London → try adding CHOPPY, or adding NY_AM

For each loosened gate: run the full backtest, measure PF + trade count. If PF stays >1.3 with 2x more trades, keep the looser gate.

**Expected gain:** If gates can be loosened 2x while maintaining PF>1.3, that's ~76 trades/year from 38. Halves the gap.

**Kill gate:** If no loosened variant maintains PF>1.2, revert to original gates.

## Track 1: New Strategies (SEQUENTIAL, NOT PARALLEL)
> **Kaito's insight:** Building 3 strategies simultaneously creates coupling. Build one, validate, then next.

**1.1: B.3 London Breakout Retest (XAUUSD)** [builder, 4h]
- Asian range → London open breakout → retest entry
- Different session window from all existing strategies (fills dead hours)
- Build → unit test → regime profile → gate backtest
- **Kill gate:** If <20 trades on XAUUSD M15 full data, abandon.

**1.2: Mean-reversion for CHOPPY regime** [builder, 4h — only after 1.1 validated]
- RSI divergence + Bollinger band reversion, gated to CHOPPY only
- Fills the CHOPPY gap in blend coverage
- **Kill gate:** If <20 trades or PF<1.0 on CHOPPY bars, abandon.

## Track 2: Symbol Expansion (BLOCKED, STARTS WHEN HARVEST DONE)
> **Dependency chain:** harvest → aggregate → validate → profile → gate test

**2.1: USDJPY aggregate + validate** [builder, 2h — when harvest complete]
- Aggregate ticks → bars (M5, M15, H1)
- Gap analysis, tick density check

**2.2: USDJPY + FX regime profiling** [builder, 2h — after 2.1]
- Profile all strategies on USDJPY M15/H1
- Re-profile on EURUSD/GBPUSD with wider param ranges (lower session_range_pips, different ADX)

**2.3: FX parameter retuning** [inline, 3h — after 2.2]
- If profiling shows any edge: tune params per pair
- If no edge: document and skip. Don't force it.
- **Kill gate:** If FX profiling shows PF<0.8 in ALL regimes for a pair, skip that pair.

## Track 3: Optuna Optimization (LAST, AFTER STRATEGIES+SYMBOLS LOCKED)
> **Kaito's insight:** Optuna must run on a FIXED strategy/symbol set. Run it last.

**3.1: Per-strategy Optuna sweep** [builder, 4h — after Tracks 0-2 complete]
- Sweep entry params for each strategy on its validated symbol(s)
- 20 trials max per strategy×symbol (not 30 — compute budget)
- OOS window (Jan-Jul 2026) excluded from optimization
- **Kill gate:** If Optuna best doesn't beat default by >10% PF, keep defaults.

**3.2: Blend weight optimization** [inline, 2h — after 3.1]
- Use ml/blend_optimizer.py on locked strategy set + locked params
- Objective: maximize trades at PF>1.2, DD<8%

## Track 4: Validation (FINAL, NON-NEGOTIABLE)

**4.1: Full blend backtest with spread costs** [inline, 2h]
- All strategies, all validated symbols, regime gates, locked params
- Include spread/slippage modeling
- PF>1.0, DD<10%, ≥250 trades/year

**4.2: Walk-forward + Monte Carlo on OOS window** [inline, 1h]
- OOS = Jan-Jul 2026 (never seen by any optimizer)
- 3 windows, Monte Carlo 1,000 simulations
- ≥95% probability of profit

**4.3: FTMO viability verdict**
- PASS: Update forward test, start demo validation
- FAIL: Identify which component failed, iterate on that component only

---

## Execution Timeline (REAL dependency chain)

### Phase 1: Hours 0-4
- Track 0 (gate loosening) — inline
- Track 1.1 (London Breakout build) — builder 1
- USDJPY harvest continues in background

### Phase 2: Hours 4-8
- Track 0 results evaluated → keep/revert loosened gates
- Track 1.1 profiled → decision: keep or kill
- Track 2.1 (if harvest done: USDJPY aggregate) — builder 2

### Phase 3: Hours 8-16
- Track 1.2 (mean-reversion build, if 1.1 passed) — builder 1
- Track 2.2 (USDJPY + FX profiling) — builder 2
- Track 0 results integrated into forward test config

### Phase 4: Hours 16-24
- Track 2.3 (FX retuning, if profiling shows edge) — inline
- Profile new strategies (1.1, 1.2) by regime — builder 1
- Lock strategy set + symbol set

### Phase 5: Hours 24-32
- Track 3.1 (Optuna per-strategy sweep on LOCKED set) — builder 1
- Track 3.2 (blend weight opt, if 3.1 done) — inline

### Phase 6: Hours 32-40
- Track 4.1 (full blend backtest with spread costs)
- Track 4.2 (walk-forward + Monte Carlo on OOS)

### Phase 7: Hours 40-48
- Track 4.3 (FTMO verdict)
- If pass: update forward test, document everything
- If fail: targeted iteration on failed component
- Buffer for rework

## Risk Mitigations (Per Council)
1. **Overfit:** OOS window isolated. PBO computed on final blend.
2. **Scope:** 3 tracks + 1 validation track. Cut criteria per item. No scope expansion.
3. **Resources:** CPU/memory caps enforced. Optuna 20 trials max.
4. **Coupling:** Sequential dependency chain. No fake parallelism.
5. **Forward test:** Running blend stays untouched until validation passes. New config deployed only on PASS.

## Success Criteria
- [ ] Blend produces ≥250 trades/year in backtest (with spread costs)
- [ ] PF > 1.0 on full data (with spread)
- [ ] Max DD < 10%
- [ ] Monte Carlo: ≥95% probability of profit on OOS
- [ ] Walk-forward: ≥3/5 windows positive on OOS
