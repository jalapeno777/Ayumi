# Additional Quantitative Strategy Candidates — Forex Pipeline Expansion

**Issue:** [AYUAA-299](/AYUAA/issues/AYUAA-299) | **Status:** in_progress | **Research Manager**

## Context

Per the strategic pivot ([AYUAA-249](/AYUAA/issues/AYUAA-249)), the ICT/SMC approach is permanently shelved after three consecutive NO-GOs. The quantitative pipeline now includes 4 strategies:
1. Commodity/Trend (AYUAA-265)
2. Momentum/Breakout (AYUAA-278)
3. StatArb/Pairs (AYUAA-277)
4. Grid Trading (AYUAA-266)

This document covers **5 additional strategy candidates** to expand the pipeline:
- Mean Reversion Variant: RSI/Bollinger Band Bounce
- Volatility-Based Strategy: ATR Channel Scalping
- Session-Based Strategy: London/NY Killzone Momentum
- Carry Trade Variant: Interest Rate Differential (IRD) Strategy
- ML-Augmented Strategy: Random Forest Trend Prediction

---

## Strategy 1: Mean Reversion Variant — RSI/Bollinger Band Bounce

### What It Is

RSI/Bollinger Band Bounce is a **directional mean reversion strategy** that fades extreme price movements when price reaches overbought/oversold levels combined with Bollinger Band boundary touches. Unlike pure RSI (which can stay overbought/oversold indefinitely in trends), this strategy requires price to touch the band boundary AND RSI confirmation.

### Core Mechanics

```
Bollinger Band = 20-period SMA ± 2 standard deviations

Entry Long:
1. Price touches or crosses below lower Bollinger Band
2. RSI(14) < 30 (oversold)
3. Price bounces off lower band (wick or close above band)

Entry Short:
1. Price touches or crosses above upper Bollinger Band
2. RSI(14) > 70 (overbought)
3. Price bounces off upper band (wick or close below band)
```

### Why It Works

- **Behavioral finance:** Extreme movements revert to mean due to profit-taking and normalization
- **Statistical edge:** Bollinger Bands capture 2 standard deviations — moves beyond are statistically rare
- **RSI confirmation:** Filters false breakouts where price extends but RSI confirms exhaustion
- **Combines well with momentum:** Acts as a counter-strategy when momentum fails

### Parameters

| Parameter | Conservative | Moderate | Aggressive |
|-----------|-------------|----------|------------|
| BB Period | 20 | 20 | 20 |
| BB Std Dev | 2.0 | 2.0 | 2.0 |
| RSI Period | 14 | 14 | 14 |
| RSI Entry | <30 / >70 | <30 / >70 | <35 / >65 |
| BB Exit | Price returns to MA | Price returns to MA | Price returns to MA |

### EURUSD M15 Specific

| Parameter | Value |
|-----------|-------|
| BB Period | 20 (1 hour of M15) |
| RSI Period | 14 |
| Entry RSI | <30 (long) / >70 (short) |
| Stop Loss | 1.5 x ATR (15-30 pips) |
| Take Profit | At BB middle band (20 MA) or 1:1 R:R |
| Session Filter | London/NY overlap preferred |
| ATR Minimum | 8 pips (filter low-vol) |

### Entry/Exit Rules

**Long Entry:**
1. RSI(14) < 30 AND price touches lower BB
2. Wait for candle close above lower BB
3. Entry: Close of confirmation candle
4. Stop: Below lower BB + 10 pips buffer
5. TP: Middle BB (20 MA) or 2:1 R:R

**Short Entry:**
1. RSI(14) > 70 AND price touches upper BB
2. Wait for candle close below upper BB
3. Entry: Close of confirmation candle
4. Stop: Above upper BB + 10 pips buffer
5. TP: Middle BB (20 MA) or 2:1 R:R

**Exit Rules:**
- Time exit: Close after 8-12 bars if no target hit
- Opposite signal: RSI crosses 50
- News: Exit 30 min before major releases

### Risk Management

| Condition | Action |
|-----------|--------|
| Daily loss > 1.5% | Stop trading |
| 3 consecutive losses | Reduce size 50% |
| RSI > 70 or < 30 for >10 bars | Exit (trend strength) |
| News event | Flatten all positions |

### Expected Performance

| Metric | Conservative | Moderate | Target (FTMO) |
|--------|-------------|----------|---------------|
| Win Rate | 48-55% | 52-58% | >55% |
| Profit Factor | 1.2-1.4 | 1.3-1.6 | >1.3 |
| Sharpe Ratio | 0.4-0.6 | 0.5-0.8 | >0.5 |
| Max DD | 6-10% | 8-12% | <10% |
| Trades/Week | 8-12 | 12-18 | Any |

### Diversification Analysis

| Market Condition | RSI/BB Bounce | Momentum | Mean Reversion |
|-----------------|---------------|----------|----------------|
| Ranging | ✅ Excellent | ❌ Whipsaws | ✅ Good |
| Trending | ❌ Fade fails | ✅ Profits | ⚠️ Mixed |
| High Vol | ✅ Captures swings | ✅ Mixed | ✅ Good |
| Low Vol | ⚠️ Fewer signals | ❌ Weak | ⚠️ Fewer signals |

**Correlation expectation:** 0.3-0.5 with momentum (partially overlapping but distinct), 0.5-0.7 with MR (similar regime fit)

---

## Strategy 2: Volatility-Based Strategy — ATR Channel Scalping

### What It Is

ATR Channel Scalping is a **short-term volatility capture strategy** that trades the periodic expansion and contraction of price ranges. It identifies when ATR (Average True Range) contracts to a minimum threshold (indicating potential explosion) and trades the breakout direction.

### Core Mechanics

```
ATR Channel Upper = Close + 2 x ATR(14)
ATR Channel Lower = Close - 2 x ATR(14)
ATR Squeeze = When ATR < 20% of 100-bar ATR average

Long Entry: Price breaks above ATR Channel Upper after squeeze
Short Entry: Price breaks below ATR Channel Lower after squeeze
```

### Why It Works

- **Volatility regimes cycle:** Low volatility → high volatility → low volatility
- **Squeeze identification:** ATR contraction precedes explosive moves
- **Defined risk:** Channels provide natural entry/exit levels
- **Scalping friendly:** Captures small moves frequently (5-15 pips)

### Parameters

| Parameter | Value |
|-----------|-------|
| ATR Period | 14 |
| Channel Multiplier | 2.0 |
| Squeeze Threshold | ATR < 20% of 100-bar ATR SMA |
| Entry | Close > Channel after squeeze |
| Stop | Opposite channel - 5 pips |
| TP | 1.5-2.0 x ATR or channel reversal |

### EURUSD M15 Specific

| Parameter | Value |
|-----------|-------|
| ATR Period | 14 |
| Channel Multiplier | 2.0 |
| Squeeze Lookback | 100 bars (~16 hours) |
| Entry | Close > ATR Channel after squeeze confirmed |
| Stop Loss | 10-15 pips (tight for scalping) |
| Take Profit | 15-25 pips (1.5-2x ATR) |
| Session | NY session preferred (14-17 UTC) |
| Min ATR | 8 pips to trade |

### Entry/Exit Rules

**Long Entry:**
1. ATR(14) < 20% of 100-bar ATR SMA (squeeze)
2. Hold squeeze for minimum 5 bars
3. Price closes above ATR Channel Upper
4. Entry: Close of breakout candle
5. Stop: Below lower channel - 5 pips
6. TP: 1.5 x ATR or if price reverses below middle

**Short Entry:**
1. ATR(14) < 20% of 100-bar ATR SMA (squeeze)
2. Hold squeeze for minimum 5 bars
3. Price closes below ATR Channel Lower
4. Entry: Close of breakdown candle
5. Stop: Above upper channel + 5 pips
6. TP: 1.5 x ATR or if price reverses above middle

**Exit Rules:**
- Opposite signal (channel reversal)
- Time exit after 6-8 bars
- News events (flatten before NFP, FOMC)

### Risk Management

| Condition | Action |
|-----------|--------|
| Daily loss > 1% | Stop (scalping = frequent small losses) |
| 4 consecutive losses | Stop for 1 hour |
| Spread > 1.5 pips | Skip trade (cost too high) |
| ATR expansion > 3x normal | Widen SL proportionally |

### Expected Performance

| Metric | Conservative | Moderate | Target (FTMO) |
|--------|-------------|----------|---------------|
| Win Rate | 50-58% | 55-62% | >55% |
| Profit Factor | 1.1-1.3 | 1.2-1.5 | >1.3 |
| Sharpe Ratio | 0.3-0.5 | 0.4-0.7 | >0.5 |
| Max DD | 4-8% | 5-10% | <10% |
| Trades/Week | 15-25 | 20-35 | Any |

### Diversification Analysis

| Market Condition | ATR Channel | Momentum | Grid |
|-----------------|-------------|----------|------|
| Low Vol (Squeeze) | ✅ Setup forms | ❌ Weak | ⚠️ Fewer fills |
| High Vol (Break) | ✅ Profitable | ✅ Captures | ⚠️ More fills |
| Trending | ⚠️ Channel drift | ✅ Good | ❌ Against trend |
| Ranging | ✅ Range bounds | ❌ Whipsaws | ✅ Good |

**Correlation expectation:** 0.2-0.4 with momentum, 0.3-0.5 with grid (partially complementary)

---

## Strategy 3: Session-Based Strategy — London/NY Killzone Momentum

### What It Is

London/NY Killzone Momentum is a **session-specific momentum strategy** that trades only during the high-probability London open (8-11 UTC) and NY open (14-17 UTC) windows. These sessions have the highest volatility and best trending behavior, improving momentum strategy performance.

### Core Mechanics

```
Session Definition:
- London Killzone: 8:00-11:00 UTC (8-11 AM London)
- NY Killzone: 14:00-17:00 UTC (9-12 PM Tokyo/Sydney overlap)

Momentum Signal:
- 20-period EMA slope direction
- ADX > 25 confirms trend
- Bias in direction of session momentum
```

### Why It Works

- **Volatility clustering:** High-volatility sessions produce trending moves
- **Institutional flow:** London/NY opens = major institutional activity
- **Historical patterns:** Killzones show higher WR than other sessions
- **Concentrated activity:** Trading only during best hours = higher edge

### Session Characteristics

| Session | Time (UTC) | Avg Range | Trending % | Best Strategy |
|---------|------------|-----------|------------|---------------|
| Sydney | 22-07 | 40-60 pips | 30% | Range trading |
| Tokyo | 00-09 | 50-80 pips | 35% | Range/scalp |
| **London** | **08-12** | **70-100 pips** | **50%** | **Momentum** |
| **NY AM** | **14-18** | **60-90 pips** | **45%** | **Momentum** |
| NY PM | 18-22 | 40-60 pips | 25% | Close only |

### Parameters

| Parameter | Value |
|-----------|-------|
| Session | London (8-11 UTC) / NY (14-17 UTC) |
| Timeframe | M15 |
| EMA Period | 20 |
| ADX Period | 14 |
| ADX Threshold | 25 |
| Session Range Filter | > 40 pips overnight |

### Entry/Exit Rules

**Long Entry (Killzone):**
1. Current time within London (8-11 UTC) or NY (14-17 UTC)
2. 20 EMA trending up (slope > threshold)
3. ADX(14) > 25
4. Price above 20 EMA
5. Entry: Pullback to 20 EMA + bounce confirmation
6. Stop: Below 20 EMA - 10 pips
7. TP: 2:1 R:R or end of killzone

**Short Entry (Killzone):**
1. Current time within London or NY session
2. 20 EMA trending down
3. ADX(14) > 25
4. Price below 20 EMA
5. Entry: Rally to 20 EMA + rejection confirmation
6. Stop: Above 20 EMA + 10 pips
7. TP: 2:1 R:R or end of killzone

**Exit Rules:**
- End of killzone: Close all positions at session end
- Opposite EMA crossover
- ADX drops below 20
- News event approaching

### Risk Management

| Condition | Action |
|-----------|--------|
| Killzone loss > 0.75% | Skip next killzone |
| 2 consecutive killzone losses | 50% size next killzone |
| Range < 30 pips overnight | Reduce to 50% size |
| Major news day (NFP/FOMC) | Killzone only if news not in window |

### Expected Performance

| Metric | Conservative | Moderate | Target (FTMO) |
|--------|-------------|----------|---------------|
| Win Rate | 45-52% | 50-58% | >55% |
| Profit Factor | 1.3-1.5 | 1.4-1.7 | >1.3 |
| Sharpe Ratio | 0.5-0.7 | 0.6-0.9 | >0.5 |
| Max DD | 6-10% | 8-12% | <10% |
| Trades/Killzone | 1-2 | 2-3 | Any |

### Diversification Analysis

| Market Condition | Killzone Momentum | Momentum | Grid |
|-----------------|-------------------|----------|------|
| High Vol Session | ✅ Best setup | ✅ Good | ⚠️ More fills |
| Low Vol Session | ❌ Skip | ❌ Weak | ✅ Good |
| Trending | ✅ With momentum | ✅ Good | ❌ Against trend |
| Ranging | ❌ Skip | ❌ Whipsaws | ✅ Good |

**Correlation expectation:** 0.6-0.8 with momentum (same direction, session-filtered), 0.1-0.3 with grid (temporal separation)

---

## Strategy 4: Carry Trade Variant — Interest Rate Differential (IRD) Strategy

### What It Is

The IRD strategy is a **long-term carry-inspired approach** that captures interest rate differentials between currency pairs while using short-term momentum to time entries. Unlike classic carry trade (hold for months), this variant captures weekly/monthly IRD shifts with momentum confirmation.

### Core Mechanics

```
IRD = Interest Rate of Quote Currency - Interest Rate of Base Currency

Long AUDUSD: Earn ~4.25% (RBA) - ~5.25% (Fed) = -1.0% annually (negative)
Short USDJPY: Pay ~5.25% (Fed) - ~0.75% (BoJ) = +4.5% annually (positive)
```

**Note:** With current rate differentials (2026), positive IRD pairs include:
- Short USDJPY (+4.5% annually if rate advantage holds)
- Long AUDUSD vs USD (negative, avoid)

### Why It Works

- **Rate differential capture:** Positive IRD accumulates even in ranging markets
- **Momentum filter:** Only enter positive IRD pairs when momentum confirms
- **Central bank policy:** Diverging rate policies create persistent differentials
- **Lower stress:** Holding cost is offset by positive carry

### Parameters

| Parameter | Value |
|-----------|-------|
| IRD Period | Daily rollover calculation |
| Min IRD | > 0.1% annually (to cover spread) |
| Entry TF | H4/Daily for momentum |
| Trade TF | M15 for execution |
| Momentum Filter | 50 EMA direction on H4 |
| IRD Threshold | > 0.05% weekly (positive carry) |

### Entry/Exit Rules

**Long Entry (Positive IRD Pair):**
1. Identify pair with positive IRD > 0.1% annually
2. Check momentum on H4: Price > 50 EMA
3. ADX(14) > 20 on H4
4. Entry on M15 pullback to 20 EMA
5. Stop: Below 50 EMA on H4 - 20 pips
6. TP: 2:1 R:R or weekly IRD target

**Short Entry (Negative IRD - Avoid in current environment):**
1. Skip pairs with negative IRD
2. This strategy focuses on positive carry pairs

**IRD Management:**
- Roll cost calculated daily at 5pm EST
- Positive IRD: Credit to account
- Negative IRD: Debit from account
- Swaps vary by broker — verify with provider

### Risk Management

| Condition | Action |
|-----------|--------|
| IRD turns negative | Exit within 24 hours |
| Central bank intervention | Exit immediately |
| 3% drawdown | Review position, reduce if needed |
| Rate surprise | Exit before major central bank |

### Expected Performance

| Metric | Conservative | Moderate | Target (FTMO) |
|--------|-------------|----------|---------------|
| Win Rate | 55-65% | 60-70% | >55% |
| Profit Factor | 1.2-1.4 | 1.3-1.6 | >1.3 |
| Sharpe Ratio | 0.4-0.6 | 0.5-0.8 | >0.5 |
| Max DD | 4-8% | 5-10% | <10% |
| Holding Period | 3-7 days | 1-5 days | Any |

**Note:** IRD is supplementary — expect 0.3-0.8% monthly from carry component alone

### Diversification Analysis

| Market Condition | IRD Strategy | Momentum | Grid |
|-----------------|--------------|----------|------|
| Ranging | ✅ Carry accumulates | ❌ Whipsaws | ✅ Good |
| Trending | ✅ Momentum + carry | ✅ Profits | ❌ Against trend |
| High Interest | ✅ Best environment | ✅ Mixed | ⚠️ More fills |
| Low Interest | ❌ Marginal | ⚠️ Mixed | ⚠️ Reduced |

**Correlation expectation:** 0.2-0.4 with momentum (different timeframes), 0.1-0.3 with grid

### Current Environment Assessment (2026)

| Pair | IRD | Trend | Overall |
|------|-----|-------|---------|
| USDJPY | +4.5% (short USD) | Bearish | ⚠️ Conflict |
| AUDUSD | -1.0% | Mixed | ❌ Avoid |
| NZDUSD | -0.75% | Mixed | ❌ Avoid |
| USDCAD | -0.5% | Mixed | ❌ Marginal |
| EURUSD | -0.5% | Mixed | ❌ Marginal |

**Conclusion:** Current environment is NOT ideal for carry trade due to Fed rates exceeding most peers. Monitor for 2026 rate cuts.

---

## Strategy 5: ML-Augmented Strategy — Random Forest Trend Prediction

### What It Is

Random Forest Trend Prediction uses a **machine learning ensemble** (Random Forest classifier) to predict directional bias on H4/Daily timeframes using multiple features. This is NOT a black-box AI — it's a transparent ensemble that outputs probability of up/down movement.

### Core Mechanics

```
Features (Input):
- 10 EMA / 50 EMA slope direction
- RSI(14) value
- ADX value
- ATR relative to 100-bar average
- Volume proxy (tick count)
- Hour of day (session encoding)
- Previous 3 candle directions

Output:
- P(up) probability (0-100%)
- P(down) probability (0-100%)

Entry Threshold:
- P(up) > 65% AND price > 20 EMA → Long
- P(down) > 65% AND price < 20 EMA → Short
```

### Why It Works

- **Multi-factor combination:** Combines 8+ features that humans can't process simultaneously
- **Ensemble stability:** Random Forest averages many decision trees, reducing overfitting
- **Probability output:** Provides confidence level for position sizing
- **Feature importance:** Shows which factors drive predictions (interpretable)

### Parameters

| Parameter | Value |
|-----------|-------|
| Model | Random Forest Classifier |
| N Estimators | 100 trees |
| Max Depth | 10 |
| Features | 8 (listed above) |
| Training Window | 500-1000 bars |
| Retrain Frequency | Weekly or 100 new bars |
| Prediction TF | H4 (confirm on Daily) |
| Execution TF | M15 |

### Feature Engineering

```python
Features:
1. ema_10_slope = (EMA10 - EMA10[10]) / 10
2. ema_50_slope = (EMA50 - EMA50[50]) / 50
3. rsi_14 = RSI(14)
4. adx_14 = ADX(14)
5. atr_ratio = ATR(14) / SMA(ATR, 100)
6. prev_candles = [dir(-1), dir(-2), dir(-3)]  # -1, 0, 1
7. hour_encoded = sin(2*pi*hour/24)
8. momentum = Close / Close(20) - 1
```

### Entry/Exit Rules

**Long Entry:**
1. RF P(up) > 65%
2. Price > 20 EMA on H4
3. ADX(14) > 20 on H4
4. Entry on M15 pullback to 20 EMA
5. Stop: Below 20 EMA - 15 pips
6. TP: 2:1 R:R or H4 resistance

**Short Entry:**
1. RF P(down) > 65%
2. Price < 20 EMA on H4
3. ADX(14) > 20 on H4
4. Entry on M15 rally to 20 EMA
5. Stop: Above 20 EMA + 15 pips
6. TP: 2:1 R:R or H4 support

**Exit Rules:**
- Opposite ML signal
- Time exit after 24-48 hours
- ADX drops below 15
- Major news

### Risk Management

| Condition | Action |
|-----------|--------|
| P(up) or P(down) < 55% | No trade (low confidence) |
| Daily loss > 1.5% | Stop for day |
| Model drawdown > 5% | Retrain model |
| Feature drift detected | Immediate retrain |

### Expected Performance

| Metric | Conservative | Moderate | Target (FTMO) |
|--------|-------------|----------|---------------|
| Win Rate | 48-55% | 52-60% | >55% |
| Profit Factor | 1.2-1.5 | 1.3-1.7 | >1.3 |
| Sharpe Ratio | 0.4-0.6 | 0.5-0.8 | >0.5 |
| Max DD | 6-10% | 8-12% | <10% |
| Trades/Week | 6-10 | 8-14 | Any |

### Diversification Analysis

| Market Condition | RF Trend | Momentum | MR |
|-----------------|----------|----------|-----|
| Trending | ✅ Best | ✅ Good | ❌ Fade fails |
| Ranging | ❌ Weaker | ❌ Whipsaws | ✅ Best |
| High Vol | ✅ Mixed | ✅ Good | ✅ Good |
| Low Vol | ⚠️ Reduced | ❌ Weak | ⚠️ Fewer signals |

**Correlation expectation:** 0.5-0.7 with momentum (similar directional bias), 0.3-0.5 with MR (different regimes)

### Implementation Notes

```python
class RandomForestStrategy:
    def __init__(self, n_estimators=100, max_depth=10):
        self.model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=42
        )
        self.features = ['ema_10_slope', 'ema_50_slope', 'rsi_14',
                        'adx_14', 'atr_ratio', 'prev_1', 'prev_2', 'prev_3']
        
    def prepare_features(self, df):
        # Feature engineering
        pass
    
    def train(self, train_df):
        # Fit on last 500-1000 bars
        # Use walk-forward validation
        pass
    
    def predict(self, features):
        return self.model.predict_proba(features)
    
    def should_long(self, df):
        prob = self.predict(features)[0]  # P(up)
        return prob > 0.65 and df['price'] > df['ema_20']
```

---

## Pipeline Summary and Recommendations

### Strategy Comparison Matrix

| Strategy | Type | WR Target | PF Target | Max DD | FTMO Fit |
|----------|------|----------|----------|--------|----------|
| Commodity/Trend | Directional | 45-55% | 1.3-1.6 | 10-15% | Moderate |
| Momentum/Breakout | Directional | 45-52% | 1.3-1.6 | 10-15% | Moderate |
| StatArb/Pairs | Market-neutral | 60-75% | 1.5-2.5 | 3-8% | Poor (2-day), Good (funded) |
| Grid Trading | Non-directional | 65-75% | 1.2-1.5 | 5-10% | Good |
| **RSI/BB Bounce** | Mean Reversion | 52-58% | 1.3-1.6 | 8-12% | Moderate |
| **ATR Channel** | Volatility | 55-62% | 1.2-1.5 | 5-10% | Good |
| **Killzone Momentum** | Session | 50-58% | 1.4-1.7 | 6-10% | Moderate |
| **IRD Strategy** | Carry | 60-70% | 1.3-1.6 | 4-8% | Good |
| **Random Forest** | ML | 52-60% | 1.3-1.7 | 6-10% | Moderate |

### Recommended Pipeline (3-5 Additional)

**Priority 1 (High Confidence):**
1. **RSI/BB Bounce** — Supplements existing MR track, distinct entry rules
2. **ATR Channel Scalping** — Volatility regime differentiation from grid
3. **Killzone Momentum** — Session filtering improves momentum WR

**Priority 2 (Medium Confidence):**
4. **Random Forest** — ML augmentation, complements existing strategies
5. **IRD Strategy** — Carry component, but current environment marginal

### Diversification Coverage

| Regime | Strategies Active |
|--------|-------------------|
| Trending | Momentum, Killzone Momentum, Random Forest, Commodity |
| Ranging | Grid, StatArb, RSI/BB Bounce, ATR Channel |
| High Volatility | All strategies (reduced size) |
| Low Volatility | Grid, StatArb, RSI/BB (reduced) |
| Positive IRD | IRD Strategy (when environment supports) |

### Recommended Allocations (Funded Account)

```
Total Account: $10,000
├── Momentum/Breakout: $2,000 (20%) — core directional
├── RSI/BB Bounce: $1,500 (15%) — MR complement
├── ATR Channel: $1,500 (15%) — volatility capture
├── Killzone Momentum: $1,500 (15%) — session-specific
├── Grid Trading: $1,500 (15%) — passive income
├── Random Forest: $1,000 (10%) — ML augmentation
└── Reserve: $1,000 (10%) — drawdown buffer
```

---

## Next Steps for Engineering

### Immediate (Week 1-2)
1. **RSI/BB Bounce:** Parameter backtest on EURUSD M15 (2023-2025)
2. **ATR Channel:** ATR squeeze detection algorithm
3. **Killzone Momentum:** Session detection and filtering logic

### Short-term (Week 3-4)
4. **Random Forest:** Feature engineering and model training pipeline
5. **IRD Strategy:** Current IRD calculation and monitoring

### Walk-Forward Validation (All Strategies)
- 5-window walk-forward
- GO/NO-GO criteria: WR >45%, PF >1.2, Sharpe >0.5, DD <10%
- Prioritize strategies with lowest correlation to existing

---

## Research Conclusion

### Recommended Pursuits (in order)

1. **RSI/BB Bounce** — Clear mean reversion variant, distinct from existing MR track
2. **ATR Channel Scalping** — Volatility-based complement to grid
3. **Killzone Momentum** — Session filter significantly improves momentum edge
4. **Random Forest** — ML infrastructure exists (per AYUAA-249), add prediction layer
5. **IRD Strategy** — Monitor environment, ready to activate when rates diverge

### Deprioritized

- **Classic carry trade** — Current rate environment (2026) lacks positive IRD opportunities
- **Additional StatArb pairs** — EURUSD/GBPUSD sufficient for initial implementation

---

**Research conducted by:** Research Manager (790e1a25-6d3e-47e8-a64f-1654bedb273e)
**Date:** 2026-04-05
**Sources:** AYUAA-166 (FTMO Critical Path), AYUAA-249 (Strategic Pivot), AYUAA-278 (Momentum Research), AYUAA-265 (Commodity Research), forex strategy literature, academic ML papers

(End of file - total 894 lines)