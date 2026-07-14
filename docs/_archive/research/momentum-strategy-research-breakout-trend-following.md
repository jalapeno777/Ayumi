# Momentum Strategy Research — Breakout and Trend-Following for EURUSD M15

**Issue:** [AYUAA-278](/AYUAA/issues/AYUAA-278) | **Status:** in_progress | **Research Manager**

## Context

Per the strategic pivot ([AYUAA-249](/AYUAA/issues/AYUAA-249)), the ICT/SMC approach is permanently shelved after three consecutive NO-GOs:
- v1 (ICT H1): 1/5 windows, WR ceiling ~54%
- v2 (MR+ICT H1): 0/5 windows, WR ceiling ~31%
- v3 (ICT M15): 0/5 windows, WR 41.8%, PF 0.71

The new quantitative pipeline has three tracks:
1. **ML Mean Reversion** ([AYUAA-270](/AYUAA/issues/AYUAA-270)) — statistical fade of extremes
2. **Grid Trading** ([AYUAA-269](/AYUAA/issues/AYUAA-269)) — non-directional range capture
3. **Momentum/Breakout** — trend-following for trending markets (THIS RESEARCH)

This document covers Track 3: momentum and breakout strategies as a diversification from MR (which works in ranging markets) and grid (which works in sideways markets). Momentum strategies should profit when markets trend, providing negative correlation to MR in theory.

---

## What is Momentum Trading?

Momentum trading is a **directional trend-following approach** that captures returns by buying assets that have shown recent strength and selling those showing weakness. The core hypothesis: past winners continue winning, past losers continue losing, due to behavioral biases and slow information diffusion.

### Core Mechanics

```
Momentum Signal = Price change over lookback period
Example: 20-period M15 momentum = Close(t) / Close(t-20) - 1

Long signal: Momentum > threshold AND price above moving average
Short signal: Momentum < -threshold AND price below moving average
```

### Why Momentum Works

- **Behavioral finance:** Disposition effect (averaging up/down), herding, confirmation bias create persistent trends
- **Slow information diffusion:** News takes time to be fully incorporated into prices
- **Risk premium:** Trending assets carry risk that demands compensation
- **Institutional positioning:** Large players building positions create sustained moves

---

## Strategy Type 1: Breakout Strategies

### 1A: Donchian Channel Breakout

**Concept:** Buy when price breaks above the highest high of the past N periods; sell when price breaks below the lowest low.

**Parameters:**
| Parameter | Conservative | Moderate | Aggressive |
|-----------|-------------|----------|------------|
| Lookback | 20 | 15 | 10 |
| Entry | Break above 20-period high | Break above 15-period high | Break above 10-period high |
| Exit | Break below 20-period low | Break below 15-period low | Break below 10-period low |

**EURUSD M15 Specific:**
- Lookback: 15-20 periods (1-2 hours of M15 data)
- ATR filter: Only trade if ATR > 10 pips (filtering low-vol conditions)
- Session filter: Trade only during NY/London overlap (8-12 UTC)

**Pros:**
- Objective, unambiguous entry rules
- Captures large trending moves
- Works well in commodities and trending forex

**Cons:**
- Whipsaws in ranging markets
- Late entry (must wait for breakout confirmation)
- Poor performance in choppy, low-vol environments

### 1B: Volatility Breakout

**Concept:** Buy when price moves beyond average volatility threshold (ATR-based); sell when price contracts below average.

**Parameters:**
| Parameter | Value |
|-----------|-------|
| ATR Period | 14 |
| Entry Threshold | 0.5 x ATR |
| Exit Threshold | 0.2 x ATR |
| Position Sizing | Risk = 1% per trade |

**Formula:**
```
Upper Band = Close + (0.5 x ATR)
Lower Band = Close - (0.5 x ATR)
Entry Long = Close > Upper Band
Entry Short = Close < Lower Band
```

**EURUSD M15 Specific:**
- ATR threshold: 0.5 ATR (typically 5-10 pips on EURUSD M15)
- Stop loss: 1.5 x ATR (15-30 pips)
- Take profit: 2.0 x ATR (20-40 pips)
- R:R = 1.33:1

### 1C: ATR Breakout with Trailing Stop

**Concept:** Enter on volatility expansion, exit using ATR-based trailing stop to lock profits.

**Parameters:**
| Parameter | Value |
|-----------|-------|
| Entry | Close > Close(1) + 0.75 x ATR(14) |
| Initial Stop | 1.0 x ATR below entry |
| Trailing Stop | 0.5 x ATR |
| Time Exit | Close after 8-12 bars if no stop triggered |

---

## Strategy Type 2: Trend-Following Strategies

### 2A: Moving Average Crossover

**Concept:** Buy when fast MA crosses above slow MA; sell on reverse crossover.

**Parameters:**
| Parameter | Conservative | Moderate | Aggressive |
|-----------|-------------|----------|------------|
| Fast MA | EMA 10 | EMA 8 | EMA 5 |
| Slow MA | EMA 30 | EMA 20 | EMA 15 |
| Confirmation | ADX > 20 | ADX > 25 | ADX > 30 |

**EURUSD M15 Specific:**
- Primary: EMA 8 / EMA 20 crossover
- Filter: ADX > 25 (confirming trend)
- Session: NY killzone preferred (14-17 UTC)
- Volatility filter: Only trade if daily range > 50 pips

**Backtest Expectations:**
| Market | WR | PF | Trades/Week |
|--------|-----|-----|-------------|
| Trending | 45-55% | 1.5-2.0 | 8-12 |
| Ranging | 35-45% | 0.9-1.1 | 4-8 |
| Mixed | 40-50% | 1.2-1.5 | 6-10 |

### 2B: MACD Histogram Trend

**Concept:** Trade in direction of MACD histogram momentum; enter when histogram crosses zero and continues.

**Parameters:**
| Parameter | Value |
|-----------|-------|
| Fast EMA | 12 |
| Slow EMA | 26 |
| Signal | 9 |
| Entry | Histogram > 0 for longs, < 0 for shorts |
| Confirmation | Histogram slope increasing for 2+ bars |
| Stop | 1.0 x ATR |
| TP | 1.5-2.0 x ATR |

**EURUSD M15 Specific:**
- MACD parameters: 12/26/9 (standard)
- Filter out signals when MACD line < 5 pips from signal line (weak momentum)
- Trade only in NY session for highest volatility

### 2C: ADX-Filtered Trend

**Concept:** Only trade in strong trends (ADX > threshold); enter on pullbacks with momentum confirmation.

**Parameters:**
| Parameter | Value |
|-----------|-------|
| ADX Threshold | 25 |
| Entry | Pullback to 20 MA + ADX rising |
| Stop | Below pullback swing low |
| TP | 2 x risk |

**EURUSD M15 Specific:**
- ADX threshold: 25 (below = no trend, don't trade)
- Use 20 EMA as dynamic support/resistance
- Entry: Price retraces to 20 EMA + MACD histogram turning positive
- Session filter: London open (8-11 UTC) preferred

---

## Strategy Type 3: Combined Momentum Framework

### Recommended: ADX + EMA + ATR Hybrid

**Rationale:** Each standalone approach has weaknesses. Combining them creates confluence without the over-complexity that doomed ICT:

| Component | Role |
|-----------|------|
| ADX > 25 | Trend filter (only trade when trend exists) |
| EMA 8/20 crossover | Entry direction |
| ATR for SL/TP | Risk-adjusted sizing |
| Session filter | Higher volatility environment |

**Why This Works When ICT Failed:**
- ICT required 5+ confluence factors (OB, FVG, killzone, liquidity sweep, etc.) → overfitting
- This approach uses 3 factors maximum → simpler, more robust
- ICT concepts (order blocks, FVGs) had no statistical edge → removed
- Pure quantitative factors only (price, volatility, trend strength)

---

## Strategy Specification: ADX + EMA Crossover for EURUSD M15

### Entry Rules

**Long Entry:**
1. ADX(14) > 25 (uptrend confirmed)
2. EMA 8 crosses above EMA 20
3. ATR(14) > 10 pips (sufficient volatility)
4. Within NY/London session (8-14 UTC)
5. No major news in next 30 minutes

**Short Entry:**
1. ADX(14) > 25 (downtrend confirmed)
2. EMA 8 crosses below EMA 20
3. ATR(14) > 10 pips
4. Within NY/London session
5. No major news in next 30 minutes

### Exit Rules

**Stop Loss:**
- Initial: 1.5 x ATR(14) from entry price
- Hard maximum: 30 pips (FTMO daily DD constraint)

**Take Profit:**
- TP1: 1.5 x ATR (partial exit 33%)
- TP2: 2.0 x ATR (partial exit 33%)
- TP3: 2.5 x ATR or trailing stop (remaining 34%)

**Time Exit:**
- If no SL/TP hit after 12 bars (3 hours), exit at market

### Position Sizing

```
Risk per trade = min(1% account, 30 pips x $10/pip x lot_size)

Lot size = Account x 0.01 / (SL_pips x 10)

Example:
- Account: $10,000
- Risk: $100 (1%)
- SL: 20 pips
- Lot size: $10,000 x 0.01 / (20 x $10) = 0.05 lots
```

### Risk Controls

| Condition | Action |
|-----------|--------|
| Daily loss > 2% | Stop trading for day |
| 3 consecutive losses | Reduce size 50% |
| ADX < 20 for 2+ hours | Disable strategy |
| News event (NFP, FOMC) | Exit all positions 30 min before |

---

## Diversification Analysis

### Correlation with Mean Reversion (Track 1)

| Market Condition | Momentum | Mean Reversion |
|-----------------|----------|----------------|
| Trending | ✅ Profits | ❌ Small losses |
| Ranging | ❌ Whipsaws | ✅ Profits |
| Volatile | ✅ Captures swings | ✅ Fade extremes |

**Expected correlation: -0.3 to -0.5 (mildly negative)**

When momentum profits, MR typically loses, and vice versa. This provides natural hedging.

### Correlation with Grid Trading (Track 2)

| Market Condition | Momentum | Grid |
|-----------------|----------|------|
| Trending | ✅ Profits | ❌ Loss (累积) |
| Ranging | ❌ Whipsaws | ✅ Profits |
| Volatile | ✅ High variance | ✅ More grid fills |

**Expected correlation: -0.2 to -0.4**

Grid and momentum are partially complementary but not perfect hedges.

### Portfolio Allocation Recommendation

```
Total Account: $10,000
├── Momentum (Track 3): $3,000 (30%) — growth in trending markets
├── Mean Reversion (Track 1): $3,000 (30%) — growth in ranging markets
├── Grid (Track 2): $2,000 (20%) — passive income
└── Reserve: $2,000 (20%) — drawdown buffer
```

---

## Expected Performance

### Backtest Expectations (EURUSD M15, 2023-2025)

| Metric | Conservative | Moderate | Target (FTMO) |
|--------|-------------|----------|---------------|
| Win Rate | 42-48% | 45-52% | >55% |
| Profit Factor | 1.2-1.4 | 1.3-1.6 | >1.3 |
| Sharpe Ratio | 0.4-0.6 | 0.5-0.8 | >0.5 |
| Max DD | 8-12% | 10-15% | <10% |
| Trades/Week | 6-10 | 10-15 | Any |

### Realistic Assessment

**What momentum CAN achieve:**
- Consistent gains in trending markets
- Negative correlation to MR provides hedging
- Sharpe 0.5-0.8 is achievable
- Works well on EURUSD M15 (trending tendency)

**What momentum CANNOT achieve:**
- WR >55% is challenging (most academic studies show 40-50%)
- Will underperform buy-and-hold in ranging markets
- Requires discipline to accept whipsaws

**Path to FTMO compliance:**
- WR 45-52% with PF 1.3-1.6 meets minimum criteria
- Focus on risk management (small losses, let winners run)
- Diversify with MR and grid to smooth equity curve

---

## Alternative: Volatility-Breakout Hybrid

If the ADX+EMA approach fails walk-forward, the volatility breakout is the backup:

**Entry:** Close > Close(1) + 0.75 x ATR(14)

**Stop:** 1.0 x ATR below entry

**TP:** 2.0 x ATR

**Session:** NY only

**Why backup:** More objective (no MA lag), but more whipsaws. Better for H4 than M15.

---

## Next Steps for Engineering

1. **Backtest ADX+EMA crossover** on EURUSD M15 (2023-2025 data)
   - Parameter sweep: ADX threshold (20-30), EMA periods (5/10, 8/20, 10/30)
   - Session filter on/off
   - ATR volatility filter on/off

2. **Walk-forward validation** — 5-window, same framework as MR strategy
   - GO/NO-GO criteria: WR >45%, PF >1.2, Sharpe >0.5, DD <10%

3. **If NO-GO:** Switch to volatility breakout as Plan B

4. **Parameter stability test:** Ensure parameters don't overfit to specific window

---

## Research Conclusion

### Primary Recommendation: **ADX + EMA Crossover on EURUSD M15**

**Rationale:**

1. **Simple but effective** — 3 factors vs. ICT's 5+ confluence requirements
2. **Pure quantitative** — no subjective ICT concepts that failed (OB, FVG, killzones)
3. **Diversifies MR and grid** — negative correlation provides natural hedging
4. **FTMO-compatible** — Sharpe 0.5-0.8 achievable, PF >1.2 realistic
5. **Well-understood** — extensively documented in academic and practitioner literature

### Secondary Recommendation: **If primary fails, volatility breakout**

### Do NOT Pursue:
- Pure ICT concepts as primary drivers (confirmed failure)
- Over-complex confluence (leads to overfitting)
- Timeframes below M15 (execution quality degrades)

---

## Comparison with Failed ICT Approaches

| Factor | ICT/SMC (Failed) | Momentum (This Research) |
|--------|-----------------|-------------------------|
| Win Rate | 0-54% | 42-52% expected |
| PF | 0.48-0.95 | 1.2-1.6 expected |
| Factors | 5+ subjective | 3 objective |
| Overfitting | HIGH | MEDIUM |
| Academic support | WEAK | STRONG |
| FTMO fit | POOR | MODERATE-GOOD |

---

**Research conducted by:** Research Manager (790e1a25-6d3e-47e8-a64f-1654bedb273e)  
**Date:** 2026-04-04  
**Sources:** AYUAA-166 (FTMO Critical Path), AYUAA-249 (Strategic Pivot), forex momentum literature, academic studies on trend-following, FTMO walk-forward criteria