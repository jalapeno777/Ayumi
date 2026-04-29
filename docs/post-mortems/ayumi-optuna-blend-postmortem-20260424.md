# Post-Mortem: Optuna Blend Optimizer

**Date:** 2026-04-24
**Reviewer:** Mika (Risk Advisor)
**Scope:** `ml/blend_optimizer.py`, `strategies/registry.py`, `tests/test_blend_optimizer.py`
**Confidence Score:** 7.5/10

---

## Summary

Solid architectural foundation. Optuna integration is clean, score formula is defensible, and tests cover the critical paths. The system is **not production-ready** but is a correct Phase 1 scaffold. Two real risk items and several hard blockers before this touches live trading.

---

## 1. Optuna Search Space

**Verdict: Adequate with gaps**

What's covered:
- ✅ Binary activation per strategy (categorical True/False)
- ✅ Continuous weight per strategy (0.1–1.0)
- ✅ Per-strategy symbol subset selection
- ✅ Sniper and swarm threshold tuning

Missing dimensions:
- ⚠️ **Timeframe selection** — strategies declare multiple timeframes but the optimizer doesn't tune which ones are active. A strategy trading M15+H1+H4 blindly is different from one using only H1.
- ⚠️ **No weight normalization** — raw weights in [0.1, 1.0] aren't normalized. Optuna can learn "activate everything at 1.0" as a degenerate solution. Should softmax or normalize before backtest.
- ⚠️ **No interaction penalties** — two mean-reversion strategies on the same pair may overfit. No dimension penalizes overlap.
- ⚠️ **Sampler not specified** — defaults to TPESampler which is fine, but for categorical-heavy spaces like this, `GridSampler` warm-start or `NSGAIISampler` for multi-objective would be better long-term.

**Risk: Medium.** Search space works for Phase 1. Weight normalization should be fixed before increasing trial count.

---

## 2. Score Formula

**Verdict: Good, with one mathematical concern**

`score = win_rate × sqrt(trades) × (1 / (1 + dd_pct/100))`

Strengths:
- ✅ `sqrt(trades)` is the right concavity — rewards more data without over-rewarding high-frequency noise
- ✅ DD factor asymptotes to 0 as drawdown grows — correct penalty shape
- ✅ Simple, interpretable, no overfitting to meta-parameters

Concerns:
- ⚠️ **No Sharpe/profit-factor component** — win_rate alone doesn't capture magnitude of wins vs losses. A strategy with 60% WR but 1:2 R:R scores the same as 60% WR with 1:0.5 R:R. The backtest has `outcome_pnl` available — use it.
- ⚠️ **No penalty for strategy count** — more active strategies = more trades = higher `sqrt(trades)` bonus. This creates an incentive to activate everything. Should divide by `sqrt(active_count)` or similar.

**Recommendation:** Add profit factor or expectancy to the score. Even a simple `win_rate × avg_win / avg_loss` multiplier would help.

**Risk: Medium-High.** Current formula can be gamed by activating all strategies.

---

## 3. CPU Metering

**Verdict: Functional but fragile**

Implementation: `cpu_limit_percent` of `timeout_seconds` converted to a wall-clock budget.

Issues:
- ⚠️ **Wall-clock ≠ CPU time** — `time.monotonic()` measures elapsed time, not CPU time. A trial that blocks on I/O or sleeps still consumes budget. Use `time.process_time()` or `resource.getrusage()` for actual CPU measurement.
- ⚠️ **No per-trial timeout** — a single trial can hang indefinitely within the budget. Should add `trial.setTimeout()` or a per-trial alarm.
- ⚠️ **Pruning is passive** — only checks budget at trial start. A trial that runs for 50 seconds consuming most of the budget wastes resources before the next trial gets pruned.
- ✅ `TrialPruned` is the right mechanism — Optuna handles it cleanly.

**Risk: Low-Medium.** Works for controlled environments. Breaks under load or with slow backtests.

---

## 4. Synthetic Signal Generation

**Verdict: Adequate for development, dangerous for optimization**

What it does: Deterministic signals based on `hash()` with ~60% base win rate.

Critical issues:
- 🔴 **Optuna can game deterministic signals** — the optimizer will find the exact hash patterns that produce wins. It's optimizing against a known distribution, not learning generalizable blends. Results from synthetic optimization will not transfer to live signals.
- ⚠️ **`hash()` is non-deterministic across Python sessions** (PYTHONHASHSEED randomization). Different runs produce different "optimal" blends. Should seed explicitly.
- ⚠️ **No signal correlation modeling** — real strategy signals are correlated (market regimes affect all). Synthetic signals assume independence.
- ⚠️ **Fixed 60% win rate** — doesn't test how the blend handles bad strategies or regime changes.

**Recommendation:** This is acceptable as a integration test harness. **Do not use synthetic results for production blend decisions.** The priority should be wiring real historical signals from the signal engine.

**Risk: High.** Synthetic optimization results are misleading.

---

## 5. Roadmap Priority

| Priority | Item | Rationale |
|----------|------|-----------|
| **P0** | Wire real historical signals | Synthetic optimization produces non-transferable results. Everything else depends on real data. |
| **P1** | Score formula enhancement (profit factor + strategy count penalty) | Current formula has a known gaming vector. Fix before scaling trials. |
| **P1** | Weight normalization (softmax) | Prevents degenerate "all-on, all-max" solutions. |
| **P2** | Confidence gate tuning with historical data | Requires P0. Can then validate threshold sensitivity against real signal distributions. |
| **P2** | CPU metering fix (`process_time` + per-trial timeout) | Production hardening. |
| **P3** | ML feature pipeline enhancement | Nice-to-have. Doesn't block blend optimization. |
| **P3** | Daily performance analytics | Operational tooling. Separate concern from optimization. |

---

## Test Coverage Assessment

**10/10 tests pass.** Good coverage of:
- Score formula correctness
- Config creation
- Integration (single + multi strategy)
- Weight bounds
- CPU metering path
- Error case (get_best_blend before optimize)

Missing:
- No test for all-inactive strategies during optimization (returns 0 but isn't explicitly tested)
- No test for score formula with extreme drawdown (e.g., 100% DD)
- No test for PYTHONHASHSEED reproducibility

---

## Issues Summary

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | 🔴 High | Synthetic signals gameable by Optuna | Wire real historical signals (P0) |
| 2 | 🟠 Medium-High | Score formula rewards strategy count | Add profit factor + count penalty |
| 3 | 🟠 Medium | No weight normalization | Softmax before backtest |
| 4 | 🟡 Medium | `hash()` non-deterministic across runs | Use seeded RNG |
| 5 | 🟡 Low-Medium | Wall-clock CPU metering | Switch to `process_time` |
| 6 | 🟢 Low | No timeframe tuning dimension | Add in v2 search space |
| 7 | 🟢 Low | No per-trial timeout | Add trial-level guard |

---

## Next Build Recommendations

1. **Immediately:** Replace synthetic signals with real historical signal feed. This unblocks all downstream work.
2. **Same sprint:** Fix score formula — add profit factor multiplier and divide by `sqrt(active_count)`. Add softmax normalization to weights.
3. **Next sprint:** CPU metering hardening + confidence gate tuning against real data.
4. **Backlog:** Timeframe selection, multi-objective optimization, daily analytics.
