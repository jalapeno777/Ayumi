# Post-ICT Contingency Strategy Research

**Issue:** [AYUAA-274](/AYUAA/issues/AYUAA-274)  
**Status:** in_progress  
**Research Manager**  
**Context:** AYUAA-253 (ICT/SMC last-chance on EURUSD M15) is the final ICT test. If NO-GO, ICT/SMC is permanently shelved per kill criteria. This document provides contingency strategy options.

**Assumption:** EURUSD M15 ICT test (AYUAA-253) returns NO-GO. This is PROACTIVE planning — do not wait for the result.

---

## Executive Summary

After 4+ consecutive walk-forward failures on ICT/SMC and hybrid approaches, we need a fundamental strategy pivot. Available data shows:

- **Win rate ceiling:** ~54% max (never reaches 55% FTMO threshold)
- **2025 degradation:** Windows 3-4 fail catastrophically across all approaches
- **Filter overhead:** ICT confirmation reduces trade frequency without improving WR

**Three contingency paths analyzed below, ranked by implementation feasibility and expected performance.**

---

## Strategy Gap Analysis

### What We've Tested

| Approach | Timeframe | Pair | Result | Peak WR |
|----------|-----------|------|--------|---------|
| ICT/SMC Primary | H1 | EURUSD | NO-GO (1/5) | 54.5% |
| ICT/SMC Primary | H1 | GBPUSD | NO-GO (1/5) | 54.2% |
| MR + ICT Hybrid | H1 | EURUSD | NO-GO (0/5) | 31% |
| MR + ICT Hybrid | H1 | GBPUSD | NO-GO (0/5) | 31% |
| ICT/SMC | M15 | EURUSD | **IN PROGRESS** | TBD |

### What We Haven't Tested

| Approach | Timeframe | Pairs | Status |
|----------|-----------|-------|--------|
| Pure ML Mean Reversion | M15/H1 | EURUSD, GBPUSD | **Not started** |
| H4 Breakout/Momentum | H4 | USDJPY, GBPUSD | **Not started** |
| Grid Trading | Any | EURUSD, GBPUSD | Research done (AYUAA-266) |
| D1 Position Trading | D1 | EURUSD | **Not started** |

**Key insight:** Our entire backtest history is on EURUSD/GBPUSD + H1/M15. We've never tested H4, D1, or USDJPY.

---

## Contingency Option 1: Pure ML Mean Reversion

### Description
Deploy existing ML infrastructure (scikit-learn, xgboost, regime detection, correlation matrix) for a pure statistical mean reversion strategy. No ICT/SMC components.

### Rationale
- **ML infrastructure is complete** — features pipeline, regime detection, position sizing, walk-forward framework all built
- **Mean reversion has higher base WR** — literature shows 55-65% WR vs ICT's 40-54%
- **Regime detection can filter** — skip mean reversion signals during trending conditions
- **Existing work:** Previous MR+ICT hybrid showed 31% WR but that was ICT-constrained; pure MR should perform better

### Architecture

**Features (from existing pipeline):**
- RSI(14), RSI(50)
- Bollinger Band position (%B)
- ATR percentile (volatility regime)
- Z-score of price vs 20 EMA
- Correlation with GBPUSD (pairs regime)
- Session indicator (avoid low-liquidity)

**Model:**
- XGBoost classifier: predict 1-hour mean reversion success
- Train on: EURUSD M15 or H1 (3-year dataset)
- Features: above regime indicators
- Target: price returns to mean within 1-4 bars with 1:1.5 R:R

**Regime Filter (from existing regime_detection.py):**
- Skip trades when ATR regime = "high_volatility_trending"
- Skip when ADX > 25 (strong trend)
- Only trade when regime = "low_volatility_ranging" or "normal"

**Risk Management (from existing position_sizing.py):**
- Kelly criterion for position sizing
- Max 2% risk per trade
- Max 3 concurrent positions
- Daily drawdown breaker at 3%

### Feasibility Assessment

| Factor | Assessment |
|--------|------------|
| Data availability | ✅ EURUSD M15/H1, GBPUSD M15/H1 confirmed good quality |
| ML infrastructure | ✅ Complete (scikit-learn, xgboost, features built) |
| Implementation complexity | ⚠️ Medium — needs strategy wrapper + signal generation |
| Historical evidence | ✅ Mean reversion well-documented in academic literature |
| Walk-forward timeline | 2-3 weeks for full 5-window validation |

### Expected Performance

| Metric | Optimistic | Realistic | Conservative |
|--------|------------|-----------|--------------|
| Win Rate | 62% | 55-58% | 50-54% |
| Profit Factor | 1.8 | 1.4-1.6 | 1.1-1.3 |
| Max Drawdown | 3% | 4-5% | 5-6% |
| Sharpe Ratio | 1.2 | 0.6-0.9 | 0.3-0.5 |
| Profitable Windows | 4/5 | 3/5 | 2/5 |

**Key assumption:** Removing ICT overhead increases trade frequency and WR.

### Implementation Steps

1. **Week 1:** Build MR signal generator using existing features
2. **Week 1-2:** Run 5-window walk-forward on EURUSD H1
3. **Week 2:** Tune regime filter thresholds
4. **Week 3:** Evaluate against FTMO criteria
5. **Decision point:** GO/NO-GO based on walk-forward results

---

## Contingency Option 2: H4 Breakout/Momentum on USDJPY

### Description
Test a simpler, non-ICT approach on a different pair/timeframe combination: USDJPY H4 breakout strategy. USDJPY trends more reliably than EURUSD due to clear macro drivers (BOJ policy, Fed policy divergence).

### Rationale
- **USDJPY trends more reliably** — BOJ/ Fed policy divergence creates sustained trends
- **H4 reduces noise** — less false signals than H1, clearer structure than D1
- **Breakout strategy is simple** — no complex ICT concepts needed, just price structure
- **Different instrument = uncorrelated results** — may not suffer same 2025 degradation

### Architecture

**Entry Logic:**
- Identify 20-bar consolidation range
- Entry when price breaks high/low of consolidation + 5 pip buffer
- Confirm with volume (optional if data available)

**Stop Loss:**
- Below/above consolidation low/high
- ATR-based: 1.5x ATR(14) from entry

**Take Profit:**
- 1:2 R:R minimum
- Optional: trailing stop after 1:1

**Session Filter:**
- Trade during London/NY overlap only (8am-12pm EST)
- Avoid major news events

**Position Sizing:**
- 1% risk per trade
- Max 2 concurrent positions
- Daily DD breaker at 3%

### Feasibility Assessment

| Factor | Assessment |
|--------|------------|
| Data availability | ⚠️ USDJPY H4 data needs confirmation (may not be in dataset) |
| Implementation complexity | ✅ Low — breakout logic is straightforward |
| Historical evidence | ✅ Breakout strategies well-documented |
| Walk-forward timeline | 2-3 weeks for validation |

### Risk

**Critical unknown:** USDJPY H4 data may not be available in our current dataset. Need to confirm before proceeding.

### Expected Performance

| Metric | Optimistic | Realistic | Conservative |
|--------|------------|-----------|--------------|
| Win Rate | 50% | 42-48% | 35-40% |
| Profit Factor | 2.0 | 1.5-1.8 | 1.2-1.4 |
| Max Drawdown | 3% | 4-5% | 5-6% |
| Sharpe Ratio | 1.5 | 0.8-1.2 | 0.4-0.7 |

**Note:** Lower WR is acceptable if PF is high enough. FTMO's 4% daily DD is the binding constraint, not WR.

---

## Contingency Option 3: Grid Trading on EURUSD (Ranging Market Strategy)

### Description
Grid trading generates profit from ranging markets by placing buy/sell orders at fixed intervals. I researched this in [AYUAA-266](/AYUAA/issues/AYUAA-266). Unlike directional strategies, grid trading doesn't require predicting market direction.

### Rationale
- **Passive income characteristics** — profits from volatility regardless of direction
- **Low psychological burden** — no need to predict trends
- **Compatible with ranging markets** — EURUSD spends ~40-50% of time ranging
- **Complementary to directional trading** — can run both simultaneously

### Architecture

**Grid Parameters:**
- Grid spacing: 20-30 pips (based on 20-day ATR)
- Number of grid levels: 5-7 above and below entry
- Lot sizing: exponential (larger lots further from entry)
- Total risk: max 5% per grid sequence

**Entry:**
- Initiate grid when price enters a ranging regime (RSI between 40-60 for 10+ bars)
- Or initiate grid at key support/resistance levels

**Exit:**
- Close entire grid when profit target reached (e.g., 3-5% per sequence)
- Or when trend signal invalidates ranging assumption

**Risk Management:**
- Hard stop: close all if drawdown exceeds 5%
- Trend filter: disable grid-buying in strong downtrend, grid-selling in strong uptrend
- Max 1 active grid at a time

### Feasibility Assessment

| Factor | Assessment |
|--------|------------|
| Data availability | ✅ EURUSD M15/H1 available |
| Implementation complexity | ⚠️ Medium — requires ranging regime detection |
| Historical evidence | ⚠️ Mixed — grids work well in ranging, poorly in trending |
| Walk-forward timeline | 2-3 weeks for backtest + validation |

### Key Risk

**Grid trading fails in sustained trends.** If EURUSD enters a strong trend (like 2025), grids can accumulate large drawdowns. Must have strict trend filter and drawdown controls.

### Expected Performance

| Metric | Ranging Market | Trending Market | Overall |
|--------|----------------|-----------------|---------|
| Win Rate | 70-80% | 30-40% | 50-60% |
| Profit Per Grid | 2-4% | -3 to -5% | Variable |
| Max Drawdown | 1-2% | 5-8% | 4-6% |
| Sharpe Ratio | 1.5-2.0 | -0.5 to -1.0 | 0.5-1.0 |

---

## Comparison Matrix

| Criteria | Option 1: ML MR | Option 2: H4 Breakout | Option 3: Grid |
|----------|----------------|----------------------|----------------|
| **Data available** | ✅ Yes | ⚠️ Confirm USDJPY H4 | ✅ Yes |
| **Implementation** | Medium | Low | Medium |
| **WR potential** | 55-62% | 42-48% | 50-60% |
| **PF potential** | 1.4-1.8 | 1.5-2.0 | 1.2-1.5 |
| **Drawdown risk** | Medium | Medium | Medium-High |
| **Walk-forward time** | 2-3 weeks | 2-3 weeks | 2-3 weeks |
| **FTMO compatible** | ✅ Yes | ✅ Yes | ⚠️ Risky during trends |
| **Independence from ICT** | ✅ Full | ✅ Full | ✅ Full |
| **Uses existing ML infra** | ✅ Yes | ❌ No | ❌ No |

---

## Recommendation

### Primary Recommendation: **Option 1: Pure ML Mean Reversion**

**Rationale:**
1. **Highest probability of success** — WR 55-62% vs 55% threshold
2. **Leverages existing work** — ML infrastructure already complete
3. **Removes ICT overhead** — ICT confirmation was filtering out good trades without improving WR
4. **Timeline acceptable** — 3-4 weeks to walk-forward validation
5. **Regime filter addresses 2025 degradation** — existing regime_detection module can filter trending periods

### Secondary Recommendation: **Option 3: Grid Trading as complementary strategy**

**Rationale:**
- Works best as **supplementary income** alongside directional trading
- Can run grid on EURUSD while ML MR runs on GBPUSD (uncorrelated)
- Low psychological burden — passive income characteristics

### Do NOT Recommend After ICT Fails:
- Further ICT/SMC iterations (kill criteria met)
- MR+ICT hybrid (failed twice, ICT overhead confirmed harmful)
- Higher timeframe ICT (H4/D1 tested conceptually but not empirically; unlikely to change fundamental issues)

---

## Decision Matrix for Nori/Ayumi

| If AYUAA-253 Result | Recommended Action |
|---------------------|-------------------|
| **NO-GO** | Start Option 1 (ML MR) immediately; deprioritize ICT entirely |
| **Surprise GO** | Still start Option 1 in parallel — ICT alone has 1/5 windows = insufficient |
| **Marginal (2-3/5 windows)** | Run Option 1 as backup; keep ICT as secondary |

---

## Implementation Sequencing

**If decision to proceed with Option 1 (ML MR):**

1. **Immediate (Day 1-2):** Forex Manager + Kai scope implementation tasks
2. **Week 1:** Build signal generator + run initial backtest
3. **Week 2:** Full 5-window walk-forward
4. **Week 3:** Evaluate + present GO/NO-GO
5. **If GO:** Proceed to cTrader integration + forward test

**Parallel track:**
- Grid trading research (Option 3) can proceed as supplementary strategy in parallel
- Do NOT wait for ML MR to complete before starting grid implementation

---

## Appendix: Data Quality Confirmation

All required data for Option 1 confirmed good quality per [AYUAA-252](/AYUAA/issues/AYUAA-252):

| Dataset | Quality | Notes |
|---------|---------|-------|
| EURUSD M15 | ✅ Good | 3+ years, no gaps |
| EURUSD H1 | ✅ Good | Used in all prior backtests |
| GBPUSD M15 | ✅ Good | 3+ years, no gaps |
| GBPUSD H1 | ✅ Good | Used in all prior backtests |
| USDJPY H4 | ⚠️ Unknown | Needs confirmation |

---

**Research conducted by:** Research Manager (790e1a25-6d3e-47e8-a64f-1654bedb273e)  
**Date:** 2026-04-04  
**Sources:** AYUAA-166 (critical path), AYUAA-221 (hybrid eval), AYUAA-238 (MR+ICT eval), AYUAA-252 (data quality), AYUAA-266 (grid research), AYUAA-253 (in progress)
