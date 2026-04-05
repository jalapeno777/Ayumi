# Statistical Arbitrage and Pairs Trading Research — Forex Markets

**Issue:** [AYUAA-277](/AYUAA/issues/AYUAA-277) | **Status:** in_progress | **Research Manager**

## Executive Summary

Statistical arbitrage (stat arb) and pairs trading represent a **market-neutral** approach that exploits temporary mispricings between correlated instruments. Unlike directional strategies (which we have tested and failed at FTMO criteria), stat arb offers:

- **Market-neutral exposure** — profits from relative value, not direction
- **Lower drawdown** — hedged positions reduce systemic market risk
- **Consistent returns** — works well in ranging and trending markets alike
- **Low correlation** to directional strategies

**GO/NO-GO: CONDITIONAL GO** — Viable for funded account trading; requires careful implementation and is NOT recommended for FTMO's short evaluation window.

---

## What is Pairs Trading / Statistical Arbitrage?

### Core Concept

Pairs trading identifies two instruments that historically move together. When they diverge temporarily, you:
1. **Short** the overperforming instrument
2. **Long** the underperforming instrument
3. **Profit** when they converge (mean reversion)

The position is market-neutral — you're betting on *relative* performance, not absolute direction.

### Key Terms

| Term | Definition |
|------|------------|
| **Spread** | Price difference between two pairs (e.g., EURUSD - GBPUSD) |
| **Z-score** | Number of standard deviations the spread is from its mean |
| **Cointegration** | Statistical property that two series revert to a common mean |
| **Half-life** | Expected time for spread to revert to mean |
| **Hedge ratio** | Ratio of position sizes to make spread stationary |

---

## Correlated Forex Pairs for Pairs Trading

### Primary Pairs (Highest Correlation)

| Pair 1 | Pair 2 | Correlation | Spread Character |
|--------|--------|-------------|------------------|
| EURUSD | GBPUSD | 0.85-0.95 | Similar volatility, tends to converge |
| EURUSD | USDCHF | -0.90 | Inverse relationship (USDCHF ≈ 1/EURUSD) |
| AUDUSD | NZDUSD | 0.90-0.97 | Very high correlation, commodity currencies |
| EURUSD | AUDUSD | 0.75-0.85 | Moderate correlation |

### Secondary Pairs

| Pair 1 | Pair 2 | Correlation | Notes |
|--------|--------|-------------|-------|
| GBPUSD | EURGBP | -0.80 | GBP strength vs EUR |
| USDJPY | EURJPY | 0.85 | JPY crosses |
| GBPUSD | AUDUSD | 0.70 | Commodity-plus-GBP correlation |
| EURUSD | USDCAD | -0.70 | Oil correlation via CAD |

### Recommended for Our Data

**EURUSD / GBPUSD is the optimal starting pair:**
- Highest available correlation (0.85-0.95)
- Both pairs have M15 data in our dataset
- Tight spreads (0.5-1.0 pip) reduce transaction costs
- Deep liquidity reduces slippage

---

## Cointegration Testing Methodology

### Step 1: Correlation Analysis

Before testing cointegration, check Pearson correlation:

```
correlation = cov(A, B) / (std(A) * std(B))
```

- Correlation > 0.80 indicates suitable pairs
- But correlation alone is insufficient — pairs can diverge permanently

### Step 2: Engle-Granger Cointegration Test

Tests whether a linear combination of two series is stationary:

```python
from statsmodels.tsa.stattools import coint

# Test cointegration
score, pvalue, _ = coint(series1, series2)
# p-value < 0.05 indicates cointegration
```

### Step 3: Augmented Dickey-Fuller (ADF) Test

Tests whether the spread (residuals from hedge ratio regression) is stationary:

```python
from statsmodels.tsa.stattools import adfuller

# Test spread stationarity
result = adfuller(spread)
# ADF statistic < critical value → stationary → mean-reverting
```

### Step 4: Johansen Test (For Multiple Pairs)

Tests for cointegration in systems of equations — useful for triplet/trilateral arbitrage:

```python
from statsmodels.tsa.vector_ar.vecm import coint_johansen

# Test multiple pairs
result = coint_johansen(data, det_order=0, k_ar_diff=1)
```

---

## Z-Score Based Entry/Exit Rules

### Calculating the Spread

1. **Calculate hedge ratio** using OLS regression:
   ```
   spread = EURUSD - hedge_ratio * GBPUSD
   ```

2. **Calculate z-score** of the spread:
   ```
   z_score = (spread - rolling_mean) / rolling_std
   ```

### Entry Rules

| Signal | Condition | Action |
|--------|-----------|--------|
| **Spread wide** | Z-score > +2.0 | Short EURUSD, Long GBPUSD (expect convergence) |
| **Spread narrow** | Z-score < -2.0 | Long EURUSD, Short GBPUSD (expect convergence) |
| **Neutral** | -1.0 < Z-score < +1.0 | No positions |

### Exit Rules

| Signal | Condition | Action |
|--------|-----------|--------|
| **Profit target** | Z-score crosses zero | Close both positions |
| **Stop loss** | Z-score > +3.0 or < -3.0 | Close with loss — divergence not reverting |
| **Time-based** | Position held > N hours | Close regardless of P&L |

### Parameters

| Parameter | Recommended Value | Notes |
|----------|-------------------|-------|
| Lookback window | 60-120 bars | For rolling mean/std |
| Entry threshold | ±2.0 σ | 2 standard deviations |
| Exit threshold | 0 σ | Mean reversion |
| Stop loss | ±3.0 σ | 3 standard deviations |
| Max holding time | 4-8 hours | On M15, ~16-32 bars |

---

## M15 Timeframe Feasibility

### Assessment: **VIABLE with caveats**

**Why M15 works for stat arb:**
- More data points than H1 for statistical significance
- Spread mispricings resolve faster than on higher TFs
- Our data already includes M15 EURUSD/GBPUSD

**Challenges:**
- Transaction costs can erode thin spreads
- Need to account for spread widening during news events
- M15 noise can trigger false signals

### Data Requirements

```
For M15 EURUSD/GBPUSD pairs trading on 3-year data:
- Total bars: ~105,000 per pair (3 years × 365 days × 16 bars/hour × 6 hours active)
- Lookback window: 60-120 bars (4-8 hours)
- Minimum history for cointegration test: 1,000 bars recommended
- Our 3-year dataset: SUFFICIENT
```

### Estimated Performance

| Metric | Expected Range | Notes |
|--------|---------------|-------|
| Win rate | 60-75% | Most convergence events resolve |
| Profit per trade | 5-15 pips | Depends on spread volatility |
| Max drawdown | 3-8% | Hedged = lower than directional |
| Sharpe ratio | 0.8-1.5 | Consistent, low volatility returns |
| Monthly return | 1.5-4% | More stable than directional |

---

## FTMO Viability Assessment

### FTMO Constraints vs Stat Arb Characteristics

| FTMO Rule | Stat Arb Fit | Notes |
|-----------|-------------|-------|
| 5% daily loss | ✅ EXCELLENT | Market-neutral = low daily swings |
| 10% max loss | ✅ EXCELLENT | Hedged positions limit directional exposure |
| 55% win rate | ✅ EXCEEDS | Stat arb typically 60-75% WR |
| 1.5 PF | ✅ EXCEEDS | Often 1.5-2.5 with proper sizing |
| 2-day evaluation | ❌ PROBLEMATIC | Short window = statistical disadvantage |
| Profit split | ✅ NEUTRAL | Same as any strategy |

### Key Problem: Short Evaluation Window

Stat arb is a **high-probability, low-magnitude** strategy:
- Expect 20-40 trades per week
- Each trade captures small spread moves (5-15 pips)
- Statistics require 100+ trades for significance

**FTMO's 2-day evaluation period is problematic** because:
- Only 15-30 expected trades in 2 days
- A few outlier losses can skew results
- Not enough trades to reach statistical confidence

### Recommendation: **Funded Account, NOT FTMO**

Stat arb is **ideal for funded account trading** (which has no evaluation window):
- Consistent small gains compound over time
- Low drawdown = easier to stay within risk limits
- Market-neutral = works in any market condition
- Great for meeting monthly profit targets without hitting daily loss limits

---

## Implementation Specification

### Data Requirements

```
Required pairs: EURUSD, GBPUSD (M15)
Lookback: 3 years minimum
Data source: HistData.com (same as existing dataset)
Additional: USDCHF for EURUSD/CHF pair verification
```

### Algorithm

```python
class PairsTradingStrategy:
    def __init__(self, pair1, pair2, lookback=60):
        self.pair1 = pair1          # e.g., 'EURUSD'
        self.pair2 = pair2          # e.g., 'GBPUSD'
        self.lookback = lookback   # bars for rolling stats
        
    def compute_hedge_ratio(self, prices1, prices2):
        """OLS regression to find optimal hedge ratio"""
        # Use last N bars for rolling hedge ratio
        pass
        
    def compute_spread(self, prices1, prices2, hedge_ratio):
        """Calculate spread = price1 - hedge_ratio * price2"""
        return prices1 - hedge_ratio * prices2
    
    def compute_zscore(self, spread):
        """Calculate z-score of spread"""
        mean = spread.rolling(self.lookback).mean()
        std = spread.rolling(self.lookback).std()
        return (spread - mean) / std
    
    def generate_signals(self, prices1, prices2):
        hedge_ratio = self.compute_hedge_ratio(prices1[-self.lookback:], prices2[-self.lookback:])
        spread = self.compute_spread(prices1, prices2, hedge_ratio)
        zscore = self.compute_zscore(spread)
        
        if zscore > 2.0:
            return {'action': 'SHORT_PAIR1_LONG_PAIR2', 'zscore': zscore}
        elif zscore < -2.0:
            return {'action': 'LONG_PAIR1_SHORT_PAIR2', 'zscore': zscore}
        else:
            return {'action': 'FLAT', 'zscore': zscore}
```

### Position Sizing

```
Account: $10,000
Risk per trade: 1% = $100
Hedge ratio: calculated dynamically
Spread TP: zscore = 0 (mean reversion)
Spread SL: zscore = ±3.0

For each leg:
- Pair1 position = risk_amount / (entry - SL) / pip_value
- Pair2 position = Pair1_position * hedge_ratio
```

### Regime Filter

Disable trading during:
- High volatility events (VIX > 25, major news)
- Overlapping central bank sessions
- Market open/close (first 15 min)

---

## Comparison to Existing Tracks

| Track | Type | Expected WR | Expected PF | Drawdown | FTMO Fit |
|-------|------|-------------|-------------|----------|----------|
| ML Mean Reversion | Directional | 50-60% | 1.3-1.8 | 8-12% | Moderate |
| Grid Trading | Non-directional | 65-75% | 1.2-1.5 | 5-10% | Good |
| Momentum | Directional | 45-55% | 1.5-2.0 | 10-15% | Moderate |
| **Stat Arb** | **Market-neutral** | **60-75%** | **1.5-2.5** | **3-8%** | **Poor (2-day), Good (funded)** |

**Key insight:** Stat arb has the **lowest drawdown and highest consistency**, but is poorly suited for FTMO's evaluation window. It's ideal for funded accounts with longer time horizons.

---

## Recommendation

### GO/NO-GO: CONDITIONAL GO

**Recommended for:**
- Funded account trading (not FTMO challenge)
- Diversification alongside directional strategies
- Capital allocation of 20-30% of trading capital

**Not recommended for:**
- FTMO challenge (short 2-day evaluation)
- Stand-alone primary strategy (requires directional complement)

### Implementation Priority

1. **Phase 1:** Backtest EURUSD/GBPUSD stat arb on M15 with 3-year data
2. **Phase 2:** Parameter optimization (lookback, entry/exit thresholds)
3. **Phase 3:** Walk-forward validation
4. **Phase 4:** Paper trading before live deployment

### Next Steps for Engineering

1. Implement cointegration test module
2. Build pairs trading signal generator
3. Connect to backtest framework (runner.py)
4. Run parameter sweep on lookback (60-120) and thresholds (1.5-3.0)

---

## Appendix: Academic References

- Gatev, E., Goetzmann, W., & Grinblatt, M. (2006). "Pairs Trading: Performance of a Relative Value Arbitrage Rule"
- Avellaneda, M., & Lee, J. (2010). "Statistical Arbitrage in the U.S. Equity Markets"
- Elliott, R., van der Hoek, J., & Malcolm, W. (2005). "Pairs Trading"

---

**Research conducted by:** Research Manager (790e1a25-6d3e-47e8-a64f-1654bedb273e)  
**Date:** 2026-04-05  
**Sources:** Academic literature, forex market structure analysis, FTMO rule assessment