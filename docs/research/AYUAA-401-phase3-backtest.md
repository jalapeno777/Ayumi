# AYUAA-401 Phase 3 — Backtest Gate Results

**Date:** 2026-08-14
**Card:** 5f5bd129-2f8f-4eee-a436-10d53998ade1
**Sprint:** 042
**Status:** GATE FAILED — Do not deploy Markov sizing

---

## Infrastructure Status: FUNCTIONAL (after 2 fixes)

The Phase 3 backtest script (`scripts/quant/phase3_markov_backtest.py`) had two bugs that prevented execution:
1. **Line 152:** `tuple[BacktestMetrics := object, ...]` — walrus operator in annotation (SyntaxError). Fixed to `tuple[object, ...]`.
2. **Line 182:** `engine.run_all_strategies()` missing required `bars` argument. Fixed to `engine.run_all_strategies(bars)`.

After fixes, script ran successfully on all 3 pairs with full data loaded.

**Data coverage:**
- GBPUSD H1: 31,520 bars (2020-01-02 → 2026-07-10)
- EURUSD H1: 17,877 bars (2023-01-01 → 2025-12-31)
- USDJPY H1: 17,853 bars (2023-01-01 → 2025-12-31)

**Note:** EURUSD and USDJPY only have data from 2023 onward. The 2020-2024 baseline period for these pairs is effectively 2023-2024 only. GBPUSD has full 2020-2024 coverage.

---

## Results Summary

### GBPUSD (full 2020-2024 baseline)

| Period | Mode | Trades | Win% | Sharpe | MaxDD% | PF | R:R | PnL% |
|--------|------|--------|------|--------|--------|-----|-----|------|
| 2020-2024 | FIXED_FRACTIONAL | 780 | 20.8% | 0.068 | ~0% | 0.51 | 1.31 | ~0% |
| 2020-2024 | MARKOV_ADAPTIVE | 780 | 21.8% | 0.074 | ~0% | 0.53 | 1.30 | ~0% |
| 2025-2026 | FIXED_FRACTIONAL | 253 | 21.7% | 0.235 | ~0% | 0.56 | 1.31 | ~0% |
| 2025-2026 | MARKOV_ADAPTIVE | 253 | 22.1% | 0.239 | ~0% | 0.57 | 1.30 | ~0% |

**Sharpe Δ (baseline):** +0.006 | **Sharpe Δ (OOS):** +0.004
**Pearson r (OOS n=8385):** -0.141

### EURUSD (2023-2024 baseline only)

| Period | Mode | Trades | Win% | Sharpe | MaxDD% | PF | R:R | PnL% |
|--------|------|--------|------|--------|--------|-----|-----|------|
| 2023-2024 | FIXED_FRACTIONAL | 302 | 21.5% | 0.139 | ~0% | 0.55 | 1.24 | ~0% |
| 2023-2024 | MARKOV_ADAPTIVE | 302 | 22.2% | 0.145 | ~0% | 0.57 | 1.23 | ~0% |
| 2025-2026 | FIXED_FRACTIONAL | 184 | 19.6% | -0.148 | ~0% | 0.45 | 1.19 | ~0% |
| 2025-2026 | MARKOV_ADAPTIVE | 184 | 20.7% | -0.133 | ~0% | 0.47 | 1.19 | ~0% |

**Sharpe Δ (baseline):** +0.006 | **Sharpe Δ (OOS):** +0.015
**Pearson r (OOS n=6225):** -0.178

### USDJPY (2023-2024 baseline only)

| Period | Mode | Trades | Win% | Sharpe | MaxDD% | PF | R:R | PnL% |
|--------|------|--------|------|--------|--------|-----|-----|------|
| 2023-2024 | FIXED_FRACTIONAL | 387 | 19.1% | -0.175 | ~0% | 0.46 | 1.34 | ~0% |
| 2023-2024 | MARKOV_ADAPTIVE | 387 | 19.1% | -0.175 | 0.01% | 0.46 | 1.34 | ~0% |
| 2025-2026 | FIXED_FRACTIONAL | 210 | 20.0% | 0.288 | ~0% | 0.61 | 1.45 | ~0% |
| 2025-2026 | MARKOV_ADAPTIVE | 210 | 21.0% | 0.286 | ~0% | 0.62 | 1.42 | ~0% |

**Sharpe Δ (baseline):** +0.001 | **Sharpe Δ (OOS):** -0.002
**Pearson r (OOS n=6225):** -0.100

---

## Gate Verdict

| Criterion | Required | Actual | Verdict |
|-----------|----------|--------|---------|
| Sharpe improvement (baseline) | ≥0.15 on 2/3 pairs | +0.006, +0.006, +0.001 | **FAIL** — max improvement 0.006, need 0.15 |
| Sharpe improvement (OOS) | ≥0.10 on 2/3 pairs | +0.004, +0.015, -0.002 | **FAIL** — max improvement 0.015, need 0.10 |
| Max DD increase | ≤10% of baseline | All ~0% | **PASS** — negligible DD across all |
| Pearson r | < 0.7 | -0.141, -0.178, -0.100 | **PASS** — all strongly negative (orthogonal signals) |

### Overall Gate: **FAIL** (2 of 4 criteria failed)

---

## Analysis

### Key Findings

1. **Markov sizing provides negligible Sharpe improvement.** The best improvement was +0.015 Sharpe (EURUSD OOS), far below the 0.10 threshold. This suggests the Markov regime persistence signal does not meaningfully improve risk-adjusted returns when layered on top of the base MACross strategy.

2. **Win rate marginally improved.** Markov sizing consistently nudged win rate by ~0.5-1.1 percentage points (e.g., GBPUSD baseline: 20.8% → 21.8%). This is directionally correct but statistically weak.

3. **Drawdown impact is negligible.** Both sizing modes produced near-zero max drawdown, which is consistent with very small position sizes (risk_pct=1.0% with tiny trade PnL).

4. **Pearson correlation is negative.** All three pairs show slightly negative correlation (-0.10 to -0.18) between Markov confidence and regime.py confidence. This means the two signals are orthogonal — they capture different information. This is actually good for potential ensemble use, but it means Markov confidence doesn't reinforce regime confidence.

5. **PnL is near zero across all runs.** The MACross(5,13) strategy with these parameters is not profitable on H1 data. This is a **strategy problem**, not a sizing problem. Markov sizing can't fix a strategy that doesn't generate edge.

6. **Same trade count.** Markov sizing doesn't change which trades are taken — it only adjusts position size. The identical trade counts (780/780, 302/302, 387/387) confirm this.

### Why the Gate Failed

The Markov sizing layer is working correctly (it modifies position sizes based on regime persistence), but the effect is too small to move Sharpe meaningfully. The base strategy (MACross 5/13) has a profit factor of 0.46-0.57 (i.e., losing money), so no sizing layer can rescue it. Sizing optimization only matters when the underlying strategy has positive edge.

### Recommendation

**Do not deploy Markov adaptive sizing.** The gate criteria are not met. The Markov filter is architecturally sound (negative Pearson confirms it captures different information), but it needs testing on a profitable strategy to determine if it adds value.

**Next steps:**
- Re-test Markov sizing on a strategy with documented positive edge (e.g., SRMR+ on XAUUSD with PF=7.16)
- Consider that Markov persistence may be more valuable as a trade filter (skip low-persistence trades) than as a position sizer
- The two script bugs (walrus annotation, missing bars arg) should be fixed on main — they prevented execution for 82 dispatches

### Script Bugs Found

Two bugs in `scripts/quant/phase3_markov_backtest.py` prevented execution:
1. Line 152: `tuple[BacktestMetrics := object, ...]` → walrus operator in type annotation (SyntaxError)
2. Line 182: `engine.run_all_strategies()` → missing required `bars` positional argument

Both fixed via `sed` during Sprint 042 execution. These fixes should be committed to main.

---

## Raw Data

Full JSON results saved at: `docs/research/AYUAA-401-phase3-results.json`

---

## Conclusion

**Gate verdict: FAIL.** Markov adaptive sizing does not meet Sharpe improvement criteria on the MACross(5,13) H1 strategy. The filter is architecturally functional and captures orthogonal information (negative Pearson r), but cannot overcome the base strategy's lack of edge. Recommend re-testing on a profitable strategy.
