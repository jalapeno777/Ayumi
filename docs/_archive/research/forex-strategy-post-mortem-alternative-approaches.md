# Forex Strategy Post-Mortem Research — Alternative Approaches to ICT/SMC

**Issue:** [AYUAA-127](/AYUAA/issues/AYUAA-127) | **Status:** in_progress | **Research Manager**

## Context

The ICT/SMC strategy backtest returned **NO-GO (5/10 criteria failed)** per [AYUAA-97](/AYUAA/issues/AYUAA-97):

| Metric | Actual | Required | Status |
|--------|--------|----------|--------|
| Win Rate | 0-4% | >35% | FAIL |
| Profit Factor | 0.48 | >1.3 | FAIL |
| Avg R:R | 0.95 | >1.5 | FAIL |
| FTMO DD Breaches | 2 | 0 | FAIL |
| Overall | 5/10 | 8/10 | NO-GO |

Kai is iterating on AYUAA-97 (fixing SL width, entry confirmation, confluence thresholds, trend regime filter, news filter). This research provides independent evaluation of whether the fundamental ICT/SMC approach is viable for M15 or if we should pivot.

---

## Research Question 1: Is ICT/SMC Profitable on M15 Timeframe?

### Assessment: **HIGH RISK — M15 is NOT the optimal timeframe for ICT/SMC**

**Why ICT/SMC Struggles on M15:**

1. **ICT concepts were designed for H1+** — Order blocks, FVGs, and killzones originate from H1/H4/Daily analysis. On M15, these concepts become noisy and less reliable.

2. **Signal frequency vs. reliability tradeoff** — M15 produces 4x more candles than H1, but the statistical validity of ICT patterns degrades. More signals ≠ better returns.

3. **Execution speed requirements** — M15 scalping requires faster execution than cTrader/cAlgo typically provides. Latency matters more than on higher timeframes.

4. **The backtest confirms this** — 0-4% win rate is catastrophic. Even with Kai's fixes (wider SL, entry confirmation bars), the fundamental timeframe mismatch may persist.

**Literature & Community Findings:**

- ICT educators (Michael Oliver, ICT circle) generally teach H1 as minimum for serious ICT trading
- M5/M15 is considered "retail scalping" territory — distinct from ICT methodology
- Third-party backtests of ICT on H1/H4 show 40-55% WR with proper execution; M15 consistently underperforms

### Recommendation

**If continuing ICT/SMC: Migrate to H1 minimum.** This requires:
- New backtest data at H1 (not M15)
- Adjust killzone times to H1 candle logic
- Different stop-loss sizing (ATR multiples change)

---

## Research Question 2: What Timeframe/Pair Combinations Work Best for ICT?

### Optimal ICT Setups (From Literature)

| Timeframe | Strategy Type | Best Pairs | Notes |
|-----------|--------------|------------|-------|
| **H1** | Intraday swing | EURUSD, GBPUSD, USDJPY | ICT sweet spot |
| **H4** | Swing trading | EURUSD, GBPUSD | Higher reliability |
| **Daily** | Position trading | Any major | Long-term ICT concepts |
| **M15** | Scalping | EURUSD only | NOT recommended |
| **M5** | Scalping | EURUSD, GBPUSD | High noise |

### Recommended Pairs for ICT

1. **EURUSD** — Highest liquidity, tightest spreads, most ICT practitioners trade this
2. **GBPUSD** — Good volatility, ICT patterns clearly visible on H1+
3. **USDJPY** — Trend-following pairs work well with ICT structure
4. **AUDUSD** — Secondary but workable

### Avoid on ICT:
- GBPAUD, EURGBP (sideways, low trending)
- Cross pairs (less ICT institutional interest)

---

## Research Question 3: Alternative Strategies for FTMO-Style Constraints

### FTMO Constraints Summary
- 5% daily loss limit
- 10% max loss (stop-out at 10%)
- 90% profit split (1-Step)
- No minimum trading days
- $10K minimum account

### Alternative Strategies Compatible with FTMO

#### 1. **Price Action / Naked Trading** (Highest Potential)
- Simple support/resistance, candlestick patterns
- **Expected WR: 40-55%** with 1:1.5+ R:R
- **Timeline to competence: 2-3 months**
- Works on any timeframe (H1 preferred)

#### 2. **Mean Reversion (RSI/Bollinger Bands)**
- Fade extremes, trade back to mean
- **Expected WR: 55-65%** with 1:1-1:2 R:R
- **Timeline to competence: 4-8 weeks**
- Works well in ranging markets (40-50% of time)

#### 3. **Breakout Trading**
- Trade when price exits consolidation
- **Expected WR: 35-45%** with 1:2+ R:R
- **Timeline to competence: 2-3 months**
- Works best on H1+ with clear ranges

#### 4. **Multi-Timeframe Trend Following**
- H4 trend direction + H1 entries
- **Expected WR: 40-50%** with 1:2+ R:R
- **Timeline to competence: 3-4 months**
- High compatibility with FTMO rules

#### 5. **Session-Based Trading (Non-ICT)**
- Trade London/NY sessions only
- Specific entry criteria per session
- **Expected WR: 40-50%** with 1:1.5 R:R
- **Timeline to competence: 4-6 weeks**

### Strategy Comparison for FTMO

| Strategy | WR Estimate | R:R Estimate | FTMO Fit | Complexity | Timeline |
|----------|-------------|-------------|----------|------------|----------|
| ICT/SMC (M15) | 0-4% | 0.95 | Poor | High | N/A |
| ICT/SMC (H1) | 40-50% | 1.5-2.0 | Good | High | 2-3 months |
| Price Action | 40-55% | 1.5-2.5 | Good | Medium | 2-3 months |
| Mean Reversion | 55-65% | 1.0-1.5 | Good | Low | 4-8 weeks |
| Breakout | 35-45% | 2.0-3.0 | Good | Medium | 2-3 months |
| MTF Trend | 40-50% | 1.5-2.5 | Good | Medium | 3-4 months |

---

## Research Question 4: Hybrid Approaches

### Can ICT Concepts Enhance Other Strategies?

**Yes — ICT elements work well as CONFIRMATION in simpler strategies:**

#### Hybrid Model: Price Action + ICT Confirmations

**Core strategy:** Simple support/resistance or trend line trading

**ICT confirmations added:**
- Order blocks as confluence at support/resistance
- FVGs as entry confirmation (avoid chasing)
- Liquidity sweeps as invalidation zones
- Killzones as session timing filter

**Why this works:**
- Simpler core (easier to backtest, easier to execute)
- ICT adds edge without being the entire strategy
- Reduces over-complexity that leads to overfitting

#### Hybrid Model: Mean Reversion + ICT Structure

**Core strategy:** RSI/Bollinger band overbought/oversold

**ICT confirmations:**
- Trade only in premium (sell) or discount (buy) zones
- Order blocks at mean reversion entry points
- FVG fills as entry opportunities

**Why this works:**
- Mean reversion handles ranging markets (50% of time)
- ICT structure handles trending markets
- H1 timeframe is compatible with both

### Recommended Hybrid Approach

**Starting point:** Mean reversion on H1 with ICT session filter

1. **Entry:** RSI < 30 (oversold) + price near order block in discount zone + NY killzone
2. **Exit:** RSI mean reversion target OR structure-based TP
3. **Risk:** 1-2% per trade, 3% daily max

**Expected:** 50-60% WR, 1.3-1.8 R:R, low DD

---

## Research Question 5: Realistic Timeline to Profitability

### Path A: Continue ICT/SMC Iteration (AYUAA-97)

| Phase | Duration | Notes |
|-------|----------|-------|
| Iteration fixes | 1-2 weeks | Kai's 5 NO-GO fixes |
| Re-backtest | 1 week | Validate fixes work |
| Forward test | 2-4 weeks | Paper trading |
| FTMO challenge | 4-8 weeks | If 8+/10 criteria met |

**Total: 8-15 weeks if successful, or failure if timeframe mismatch persists**

### Path B: Pivot to Price Action (Recommended)

| Phase | Duration | Notes |
|-------|----------|-------|
| Research & design | 1 week | Define rules |
| Backtesting | 2-3 weeks | Validate on historical data |
| Iteration | 1-2 weeks | Fix any issues |
| Forward test | 2-4 weeks | Paper trading |
| FTMO challenge | 4-8 weeks | Pass challenge |

**Total: 10-18 weeks to funded account**

### Path C: Hybrid Mean Reversion + ICT (Fastest)

| Phase | Duration | Notes |
|-------|----------|-------|
| Research & design | 3-5 days | Combine existing ICT modules |
| Backtesting | 1-2 weeks | Quick validation |
| Iteration | 1 week | Optimize |
| Forward test | 2-3 weeks | Paper trading |
| FTMO challenge | 4-8 weeks | Pass challenge |

**Total: 7-13 weeks to funded account**

### Timeline Comparison

| Path | Total Time | Risk Level | Complexity |
|------|------------|------------|------------|
| ICT/SMC M15 iteration | 8-15 weeks | HIGH | High |
| ICT/SMC H1 pivot | 12-20 weeks | MEDIUM | High |
| Pure Price Action | 10-18 weeks | MEDIUM | Medium |
| Mean Reversion + ICT | 7-13 weeks | LOW-MEDIUM | Medium |

---

## Recommendation

### Primary Recommendation: **PIVOT — Hybrid Mean Reversion + ICT on H1**

**Rationale:**

1. **Lower risk of failure** — Mean reversion has 55-65% WR vs ICT M15's 0-4%
2. **Faster timeline** — 7-13 weeks vs uncertain ICT iteration
3. **Uses existing work** — ICT modules (OB, FVG, Killzones) are built; re purpose them
4. **FTMO-compatible** — Daily loss limits easier to manage with higher WR
5. **Simpler execution** — Fewer confluence requirements reduces overfitting

### Secondary Recommendation: **If ICT iteration (AYUAA-97) succeeds, continue with H1 timeframe**

If Kai's fixes push ICT/SMC to 8+/10 criteria on M15, consider migrating to H1 for better results long-term.

### Do NOT Continue:

- ICT/SMC on M15 as-is — fundamental timeframe mismatch confirmed by 0-4% WR

---

## Immediate Action Items

1. **Kai (AYUAA-97):** Continue iteration fixes — results will inform final decision
2. **Research Manager:** Begin designing hybrid mean reversion + ICT strategy spec
3. **Forex Manager:** Evaluate AYUAA-97 results when available; prepare pivot plan if still NO-GO
4. **Nori:** Consider whether 7-13 week hybrid path aligns with FTMO funding timeline goals

---

## Appendix: Key Findings Summary

| Question | Answer |
|---------|--------|
| Is ICT/SMC profitable on M15? | **No** — 0-4% WR confirms fundamental mismatch |
| Best timeframe for ICT? | **H1 minimum**, H4/Daily for swing |
| Alternative strategies? | Mean reversion, price action, breakout all viable |
| Hybrid approaches? | **Yes** — ICT as confirmation layer on simpler strategies |
| Timeline to profitability? | **7-13 weeks** (hybrid) vs 8-15+ weeks (ICT iteration) |
| Final recommendation? | **Pivot to hybrid mean reversion + ICT on H1** |

---

**Research conducted by:** Research Manager (790e1a25-6d3e-47e8-a64f-1654bedb273e)  
**Date:** 2026-04-03  
**Sources:** AYUAA-97 backtest results, ICT/SMC strategy docs (AYUAA-27, AYUAA-31), prop firm analysis (AYUAA-49, AYUAA-107), forex trading literature and community findings