# Plan B — Total Statistical Failure Fallback Criteria

**Status:** v1.1 (post-DSR update — all 6 strategies killed)  
**Author:** Ava  
**Date:** 2026-08-01  
**Card:** `aee16605`  

---

## Purpose

Define what happens if DSR (Drawdown-Stability-Robustness) rejects most or all of the current 6-strategy pool. This is a **prevention document** — written before DSR results to avoid reactive decision-making under pressure.

**Result:** Scenario 3 triggered. All 6 strategies killed by DSR on XAUUSD. Best edge probability: 5.2% (SRMR+). Strategy factory is now the primary path. See `docs/roadmaps/strategy-factory/strategy-factory-vision-v1.md`.

**Context as of writing:**
- Forward test (Killzone Momentum, XAUUSD only) ran 18h on Jul 31 → 0 signals, 0 trades
- Balance flat at $10,114.45 for 2 consecutive days
- DSR last run Jul 8 on a different strategy pool (SRMR+, 160 trials)
- Current pool: killzone_momentum, dual_tf_squeeze_pro, donchian_atr_trend_v2, srmr_plus, london_breakout_retest, ttc_xauusd
- Walk-forward results may not exist for all strategies (investigation in progress)

---

## Tiered Threshold Zones

Rather than binary pass/fail, we use three zones per metric. A strategy lands in one zone per metric; overall tier is the worst zone across all three.

### Profit Factor (PF)

| Zone | Range | Meaning |
|------|-------|---------|
| 🟢 Green | PF ≥ 1.3 | Clear edge after costs |
| 🟡 Yellow | 1.1 ≤ PF < 1.3 | Marginal edge — deploy with reduced allocation |
| 🔴 Red | PF < 1.1 | No reliable edge — reject |

### Win Rate (WR)

| Zone | Range | Meaning |
|------|-------|---------|
| 🟢 Green | WR ≥ 45% | Sufficient hit rate for trend-following |
| 🟡 Yellow | 38% ≤ WR < 45% | Acceptable if payoff ratio compensates (≥1.5:1) |
| 🔴 Red | WR < 38% | Unlikely to survive drawdown periods |

### Maximum Drawdown (DD)

| Zone | Range | Meaning |
|------|-------|---------|
| 🟢 Green | DD < 8% | Well within FTMO 10% total DD limit |
| 🟡 Yellow | 8% ≤ DD < 10% | Approaching limit — reduce position sizing |
| 🔴 Red | DD ≥ 10% | FTMO violation territory — reject or halt |

### DSR-Specific

| Zone | Condition | Meaning |
|------|-----------|---------|
| 🟢 Green | DSR p-value < 0.05, Tier A/B | Statistically significant after multiple-testing correction |
| 🟡 Yellow | 0.05 ≤ p < 0.15, Tier C | Suggestive but not robust — paper trade only |
| 🔴 Red | p ≥ 0.15, REJECT tier | No statistical evidence of real edge |

---

## Outcome Scenarios

### Scenario 1: Majority pass DSR (≥4/6 green or yellow)
**Action:** Deploy validated strategies as blend. Drop red-tier strategies.
- Go-live with paper trade for 24-48h
- Then `--live` with validated subset
- Allocation: weighted by DSR tier (Tier A gets larger allocation)

### Scenario 2: Mixed results (2-3/6 pass)
**Action:** Deploy survivors + accelerate strategy factory roadmap.
- Small validated blend (2-3 strategies)
- Increased urgency for new strategy development
- Consider expanding to additional symbols (EURUSD, GBPUSD) to compensate for fewer strategies

### Scenario 3: All reject DSR (<2/6 pass)
**Action:** **Full pivot to strategy factory.** No live deployment until factory produces validated strategies.
- Halt forward test
- Strategy factory becomes #1 priority (see strategy factory scoping doc)
- Evaluate alternative approaches: different timeframes, different markets, mean-reversion vs momentum pivot
- Timeline: 2-4 weeks for factory to produce first validated candidates

### Scenario 4: Can't run DSR (insufficient backtest data)
**Action:** Run walk-forward backtests first, then DSR.
- This is the most likely immediate scenario given missing WF results
- Use weekend to generate backtest data for all 6 strategies
- DSR follows once WF results exist

---

## Ranked Fallback Options (if Scenario 3)

1. **Strategy Factory** (recommended) — systematic approach to generating and validating new strategies. Highest long-term ROI. See strategy factory scoping doc.
2. **Expand to new markets** — deploy existing strategies on EURUSD, GBPUSD, USDJPY where they may perform better. Risk: same strategies, different data — may still fail.
3. **Different timeframes** — test strategies on H1 or H4 instead of M15. Risk: changes strategy character entirely.
4. **Abandon blend approach** — focus on single best-performing strategy. Risk: concentration risk, no diversification benefit.
5. **Pause and research** — step back, study what's working in the market right now, build from market analysis rather than strategy library.

---

## Go/No-Go Criteria Per Fallback

| Fallback | Go Signal | No-Go Signal | Time to Evaluate |
|----------|-----------|--------------|------------------|
| Strategy Factory | Factory produces ≥1 Tier A/B strategy within 2 weeks | 4 weeks with 0 validated strategies | 2-4 weeks |
| Expand Markets | Existing strategy passes DSR on ≥1 new symbol | Fails on all major pairs | 1 week |
| Different Timeframes | Strategy shows PF > 1.2 on alternate TF | PF < 1.1 on all tested TFs | 3-5 days |
| Single-Strategy | Best survivor has PF > 1.3, DD < 8% | Best survivor has PF < 1.2 | Immediate |
| Pause & Research | Clear market regime thesis identified within 1 week | No actionable thesis after 2 weeks | 1-2 weeks |

---

## Review Schedule

- **After DSR results:** Update thresholds based on actual data. This doc is v1, pre-DSR.
- **After 30-day forward test:** Re-evaluate all zones against live performance.
- **Quarterly:** Review thresholds against FTMO performance and market regime changes.

---

## Key Principle

> The goal is not to prove strategies work — it's to find out which ones do, as fast as possible, and deploy only those. Failure is data. The factory is the real path to consistent revenue.
