# Next-Generation Strategy Candidates — Adaptive ML + Regime-Switching Research

**Issue:** [AYUAA-401](/AYUAA/issues/AYUAA-401) | **Status:** in_progress | **Research Manager**

## Context

Our quantitative strategy pipeline has had multiple NO-GOs:
- ICT/SMC-only strategies — NO-GO (too subjective)
- Commodity strategies (Trend + Mean Rev on XAUUSD) — NO-GO (indicators too restrictive for gold)
- Grid Trading — NO-GO
- Statistical Arbitrage — NO-GO
- Hybrid ICT/SMC + Quant overlay — NO-GO (2 consecutive failures triggered strategic reassessment)

We pivoted to a multi-timeframe diversification sprint with new H1/H4 strategies (Keltner Breakout, Supertrend+RSI, Session-Range Mean Reversion) currently in QA.

**This research defines the NEXT pipeline** — strategies targeting the highest probability of passing FTMO walk-forward gates.

---

## Executive Summary

This document specifies 6 strategy candidates across 4 research areas:

| # | Strategy | Type | Target WR | Target R:R | FTMO Fit |
|---|----------|------|-----------|------------|----------|
| 1 | HMM Regime Detector + Strategy Selector | Adaptive ML | 45-55% | 1.5-2.0 | High |
| 2 | LightGBM Rolling Window Predictor | Adaptive ML | 42-52% | 1.4-1.8 | High |
| 3 | Markov Regime-Switching Filter | Regime Filter | 40-50% | 1.5-2.0 | High |
| 4 | Volatility Regime Overlay | Regime Filter | 43-53% | 1.4-1.9 | High |
| 5 | Ensemble Voting + Dynamic Allocator | Ensemble | 45-55% | 1.5-2.0 | High |
| 6 | Order Flow Imbalance (OFI) Microstructure | Novel Tech | 40-50% | 1.6-2.2 | High |

**Recommended Priority Order:** 3 → 1 → 6 → 4 → 2 → 5

**Rationale:** Regime filters (3, 4) provide immediate improvement to existing strategies with lowest complexity. HMM selector (1) offers best risk-adjusted returns. OFI (6) is novel and uncorrelated. LightGBM (2) offers raw predictive power. Ensemble (5) combines all above.

---

## Research Area 1: Adaptive ML Strategies

### Strategy 1: HMM Regime Detector + Strategy Selector

#### Overview
A Hidden Markov Model (HMM) classifies market into Bull/Bear/Ranging regimes in real-time. Based on detected regime, a meta-controller selects the optimal base strategy from a predefined pool.

#### Theoretical Basis
- Markets exhibit regime-dependent behavior (Bull trends, Bear trends, Range consolidation)
- No single strategy works across all regimes (Trend followers fail in ranges, mean reversion fails in trends)
- HMM provides statistically principled regime detection using observed price sequences
- Regime transitions often precede actual trend changes (leading indicator potential)

#### Regime Detection Features
- **Price momentum:** 5, 13, 21-period returns
- **Volatility:** 14-period ATR percentile rank
- **Trend strength:** ADX 14-period
- **Mean reversion signal:** RSI 14-period distance from 50
- **Session context:** One-hot encoded session type

#### State Architecture
```
Hidden States (3):
  - BULL: Uptrend regime (ADX > 25, RSI > 55, positive momentum)
  - BEAR: Downtrend regime (ADX > 25, RSI < 45, negative momentum)
  - RANGE: Consolidation regime (ADX < 25, RSI near 50)
```

#### Strategy Pool Selection
| Regime | Selected Strategy | Rationale |
|--------|------------------|-----------|
| BULL | MACrossStrategy (fast=5, slow=13) | Ride uptrends |
| BEAR | MACrossStrategy (fast=5, slow=13) | Ride downtrends |
| RANGE | BBStrategy (period=20, std=2.0) | Mean reversion |

#### Entry/Exit Logic
```
1. Train HMM on 500+ bars historical data (rolling retrain monthly)
2. At each bar, compute feature vector from last 21 bars
3. Predict current regime using Viterbi algorithm
4. If regime changed from previous bar → generate new signal
5. Use selected strategy's signal with HMM confidence as multiplier
6. Confidence = HMM_state_probability * strategy_confidence
```

#### Risk Management
- **Max consecutive losses in same regime:** 3 → reduce position 50%
- **Regime stability filter:** Require 2+ consecutive same-regime bars before entry
- **Regime transition exit:** If regime changes after entry, exit at next bar open

#### Parameters to Optimize
| Parameter | Range | Step | Notes |
|-----------|-------|------|-------|
| lookback_period | 20-100 | 10 | For feature calculation |
| min_regime_stability_bars | 1-4 | 1 | Consecutive bars for confirmation |
| momentum_periods | [5,13,21], [4,12,20], [6,14,22] | - | Period combinations |
| position_size_reduction | 0.3-0.7 | 0.1 | After consecutive losses |

#### Walk-Forward Testing Plan
1. **In-sample:** 2019-01-01 to 2021-12-31 (3 years)
2. **Out-of-sample:** 2022-01-01 to 2023-12-31 (2 years)
3. **Walk-forward window:** 6-month train, 2-month test, 1-month retrain
4. **Validation:** Must achieve 8/10 FTMO criteria on OOS before live

#### Expected Performance
- **Win Rate:** 45-55% (regime selection avoids whipsaws)
- **Profit Factor:** 1.4-1.8
- **Max DD:** <10% (regime exits limit drawdowns)
- **Sharpe:** 1.2-1.6

---

### Strategy 2: LightGBM Rolling Window Predictor

#### Overview
Gradient boosting (LightGBM) trained on rolling windows predicts next-bar direction probability. Features encode multi-timeframe technical patterns. Predictions used to filter/confluence entries from base strategies.

#### Theoretical Basis
- LightGBM handles mixed feature types, missing values, and non-linear relationships
- Rolling window prevents look-ahead bias and adapts to regime changes
- Feature importance analysis reveals most predictive patterns
- Can combine 20+ features for robust signal generation

#### Feature Engineering

**Price-Based Features (14 features):**
```
Momentum: [5, 13, 21, 55]-period returns
RSI(14), RSI(28), RSI(56) - multiple timeframes
MACD histogram change
Bollinger Band position (price - SMA) / std
ATR percentile rank (14-period lookback)
ADX(14), -DI(14), +DI(14)
```

**Session Features (5 features):**
```
Asian session range breakout (bool)
London session range breakout (bool)
NY session range breakout (bool)
Session overlapping (bool)
Time since session open (hours)
```

**Cross-Timeframe Features (4 features):**
```
H4 trend direction (from H4 SMA 50)
H4 RSI position
Daily pivot proximity
Weekly range position
```

**Pattern Features (3 features):**
```
Inside bar (bool)
Outside bar (bool)
NR4 day (bool)
```

#### Model Configuration
```python
params = {
    'objective': 'binary',
    'metric': 'auc',
    'boosting_type': 'gbdt',
    'num_leaves': 31,
    'learning_rate': 0.05,
    'feature_fraction': 0.8,
    'bagging_fraction': 0.8,
    'bagging_freq': 5,
    'min_child_samples': 50,
    'reg_alpha': 0.1,
    'reg_lambda': 0.1,
}
```

#### Entry Rules
```
1. Compute feature vector for current bar
2. Predict probability P(up) using rolling-trained model
3. If P(up) > 0.58 AND base strategy says LONG → enter LONG
4. If P(up) < 0.42 AND base strategy says SHORT → enter SHORT
5. If 0.42 <= P(up) <= 0.58 → no trade (low confidence)
```

#### Risk Management
- **Position sizing:** `confidence * base_strategy.confidence` for risk scaling
- **Stop loss:** ATR-based, 2.0x multiplier (base strategy SL)
- **Max trades per day:** 3 (prevent overtrading)

#### Parameters to Optimize (Grid Search)
| Parameter | Range | Step |
|-----------|-------|------|
| rolling_window | 500-2000 bars | 250 |
| min_confidence_threshold | 0.55-0.65 | 0.02 |
| prediction_lookback | 1-3 bars | 1 |
| retrain_frequency | daily/weekly |

#### Walk-Forward Testing Plan
1. **Initial train:** 2018-01-01 to 2020-06-30
2. **Walk-forward:** 2-month rolling train, 1-week test
3. **Final validation:** 2023 full year OOS
4. **Feature importance monitoring:** Log top 5 features per retrain

#### Expected Performance
- **Win Rate:** 42-52% (filtered entries improve WR)
- **Profit Factor:** 1.4-1.8
- **Max DD:** <10%
- **Sharpe:** 1.0-1.4

---

## Research Area 2: Regime-Switching Approaches

### Strategy 3: Markov Regime-Switching Filter

#### Overview
A two-state Markov chain models trending vs. ranging markets. A regime filter gates entries from any base strategy, only allowing trades in favorable regimes.

#### Theoretical Basis
- Market regimes persist (trends continue, ranges continue)
- Regime transitions follow memoryless property (Markov assumption)
- Simple 2-state model more robust than complex multi-state HMM
- Filter approach allows combining with any existing strategy

#### Regime Definition
```
State 0 - RANGE:
  - ADX(14) < 25
  - 20-period SMA slope < 0.001
  - RSI(14) between 40-60

State 1 - TREND:
  - ADX(14) >= 25
  - 20-period SMA slope >= 0.001 OR RSI(14) < 40 OR RSI(14) > 60
```

#### Transition Probability Estimation
```python
# Estimate from historical data
P(range → range) = count_same_regime_consecutive / count_range_bars
P(trend → trend) = count_same_regime_consecutive / count_trend_bars
P(range → trend) = 1 - P(range → range)
P(trend → range) = 1 - P(trend → trend)
```

#### Entry Filter Logic
```
TREND FILTER:
  if regime == RANGE:
    if base_strategy_signal == LONG:
      return NEUTRAL (suppress long)
    elif base_strategy_signal == SHORT:
      return NEUTRAL (suppress short)
  else:
    return base_strategy_signal
```

#### Volatility-Adaptive Position Sizing
```python
if regime == TREND:
    # Higher vol in trends, reduce size
    position_multiplier = 0.8
    atr_multiplier = 2.5  # Wider SL
else:
    # Lower vol in ranges, increase size
    position_multiplier = 1.0
    atr_multiplier = 2.0
```

#### Parameters to Optimize
| Parameter | Range | Step |
|-----------|-------|------|
| adx_threshold | 20-30 | 2 |
| sma_slope_threshold | 0.0005-0.002 | 0.0005 |
| rsi_range_width | 15-25 | 5 |
| regime_stability_bars | 1-3 | 1 |

#### Walk-Forward Testing Plan
1. **Train period:** 2019-2020
2. **Test period:** 2021-2023 (3 years OOS)
3. **Walk-forward window:** Monthly retrain of transition probs
4. **Benchmark comparison:** Run identical base strategy with/without filter

#### Expected Performance
- **Win Rate:** 40-50% (filtered strategies improve WR in trend regimes)
- **Profit Factor:** 1.5-2.0 (range trades eliminated)
- **Max DD:** <8% (whipsaw losses removed)
- **Sharpe:** 1.3-1.7

---

### Strategy 4: Volatility Regime Overlay

#### Overview
ATR percentile rank classifies volatility into Low/Normal/High regimes. Position size and stop loss dynamically adjust based on volatility regime.

#### Theoretical Basis
- Volatility clusters (high vol follows high vol, low vol follows low vol)
- Position sizing should inversely scale with volatility
- ATR-based stops adapt to current market conditions
- Different regimes favor different strategies (low vol → mean reversion, high vol → breakout)

#### Volatility Regime Definition
```python
def classify_volatility(atr_percentile_rank: float) -> str:
    if atr_percentile_rank < 25:
        return "LOW"      # Compressed, expect expansion
    elif atr_percentile_rank > 75:
        return "HIGH"     # Expanded, expect compression
    else:
        return "NORMAL"   # Typical conditions
```

#### ATR Percentile Calculation
```python
def calculate_atr_percentile(bars: List[Bar], period: int = 14, lookback: int = 100) -> float:
    current_atr = calculate_atr(bars, period)
    historical_atrs = [calculate_atr(bars[i-period:i], period) for i in range(period, len(bars)-period, period)]
    rank = sum(1 for a in historical_atrs if a < current_atr) / len(historical_atrs)
    return rank
```

#### Dynamic Risk Management
| Vol Regime | Position Size | SL (ATR×) | TP (ATR×) | Max Daily Trades |
|------------|---------------|------------|-----------|------------------|
| LOW | 1.5x | 1.5 | 2.0 / 3.0 / 4.5 | 5 |
| NORMAL | 1.0x | 2.0 | 2.0 / 4.0 / 6.0 | 3 |
| HIGH | 0.5x | 3.0 | 1.5 / 3.0 / 4.5 | 2 |

#### Strategy Selection by Regime
```python
if vol_regime == "LOW":
    preferred_strategy = "BBStrategy"  # Mean reversion
elif vol_regime == "HIGH":
    preferred_strategy = "MACrossStrategy"  # Breakout/trend
else:
    preferred_strategy = "Any"  # Both work
```

#### Parameters to Optimize
| Parameter | Range | Step |
|-----------|-------|------|
| atr_lookback | 50-200 bars | 25 |
| low_vol_threshold | 15-30 percentile | 5 |
| high_vol_threshold | 70-85 percentile | 5 |
| low_vol_position_mult | 1.2-2.0 | 0.2 |
| high_vol_position_mult | 0.3-0.6 | 0.1 |

#### Walk-Forward Testing Plan
1. **Train:** 2018-2020
2. **Test:** 2021-2023 OOS
3. **Regime stability test:** Check regime durations average > 5 bars
4. **Synergy test:** Combine with Strategy 3 (Markov Filter)

#### Expected Performance
- **Win Rate:** 43-53%
- **Profit Factor:** 1.4-1.9
- **Max DD:** <9% (vol-adjusted sizing reduces tail risk)
- **Sharpe:** 1.2-1.6

---

## Research Area 3: Ensemble Methods

### Strategy 5: Ensemble Voting + Dynamic Allocator

#### Overview
Multiple uncorrelated strategies vote on direction. Dynamic allocation weights strategies based on recent performance (rolling Sharpe ratios).

#### Theoretical Basis
- Combining uncorrelated strategies reduces variance without reducing returns
- Dynamic weighting adapts to regime changes in strategy effectiveness
- Voting consensus provides confidence signal
- Meta-strategy superior to any individual component

#### Component Strategies
| # | Strategy | Type | Target | Confidence |
|---|----------|------|--------|------------|
| 1 | MACrossStrategy(5,13) | Trend | 40% | High |
| 2 | BBStrategy(20,2.0) | Mean Rev | 35% | Medium |
| 3 | SessionRangeStrategy | Range | 35% | Medium |
| 4 | ADXBreakoutStrategy | Breakout | 40% | High |
| 5 | RSIMomentumStrategy | Momentum | 38% | Medium |

#### Voting Logic
```python
def ensemble_vote(signals: List[StrategySignal], weights: List[float]) -> StrategySignal:
    long_votes = sum(w for s, w in zip(signals, weights) if s.direction == LONG)
    short_votes = sum(w for s, w in zip(signals, weights) if s.direction == SHORT)
    total_weight = sum(weights)
    
    if long_votes > 0.65 * total_weight:
        return LONG with confidence = long_votes / total_weight
    elif short_votes > 0.65 * total_weight:
        return SHORT with confidence = short_votes / total_weight
    else:
        return NEUTRAL
```

#### Dynamic Weight Adjustment
```python
def update_weights(rolling_window_sharpe: Dict[str, float]) -> Dict[str, float]:
    # Exponential moving average of Sharpe for each strategy
    # Weight proportional to positive Sharpe
    # Minimum weight: 0.1 (never fully exclude)
    # Maximum weight: 0.4 (never dominate)
    pass
```

#### Entry Rules
```
1. Generate signal from each component strategy
2. Calculate dynamic weights based on 21-day rolling Sharpe
3. Compute weighted vote
4. If vote confidence > 0.65 AND direction != NEUTRAL → enter
5. Entry price = current bar close
6. SL/TP = weighted average of component SLs/TPs
```

#### Risk Management
- **Max correlation filter:** If top 2 strategies correlation > 0.8, reduce position 50%
- **Drawdown circuit breaker:** If portfolio DD > 5%, reduce all weights by 50%
- **Minimum consensus:** Require 3+ strategies agree before entry

#### Parameters to Optimize
| Parameter | Range | Step |
|-----------|-------|------|
| min_vote_threshold | 0.55-0.70 | 0.05 |
| weight_lookback | 10-30 days | 5 |
| min_strategy_agreement | 2-4 strategies | 1 |
| drawdown_reduction_trigger | 3-7% | 1 |

#### Walk-Forward Testing Plan
1. **Train:** 2019-2021
2. **Test:** 2022-2023 OOS
3. **Correlation monitoring:** Rolling 21-day correlation between components
4. **Weight evolution tracking:** Log weights per rebalance

#### Expected Performance
- **Win Rate:** 45-55%
- **Profit Factor:** 1.5-2.0
- **Max DD:** <8% (diversification reduces drawdowns)
- **Sharpe:** 1.4-1.8

---

## Research Area 4: Novel Technical Approaches

### Strategy 6: Order Flow Imbalance (OFI) Microstructure

#### Overview
Order Flow Imbalance proxies derived from price and volume dynamics capture institutional order flow. OFI divergence from price predicts reversals.

#### Theoretical Basis
- Large institutions leave "footprints" in order flow
- Aggressive buying (sell volume > buy volume in down bars) indicates absorption
- OFI divergence from price often precedes reversals
- Microstructure signals work on all timeframes but best on H1+

#### OFI Calculation
```python
def calculate_ofi(bars: List[Bar]) -> float:
    """
    Order Flow Imbalance = Σ (bid volume - ask volume) proxy
    Simplified proxy: price change × volume direction
    """
    ofi = 0.0
    for i in range(len(bars) - 1):
        price_change = bars[i+1].close - bars[i+1].open
        volume_direction = 1 if price_change >= 0 else -1
        ofi += volume_direction * bars[i+1].volume
    return ofi

def calculate_ofi_smoothed(bars: List[Bar], period: int = 14) -> float:
    ofi_values = [calculate_ofi_segment(bars[max(0,i-period):i+1]) for i in range(len(bars))]
    return sum(ofi_values[-period:]) / period
```

#### OFI Features
| Feature | Calculation | Interpretation |
|---------|-------------|----------------|
| OFI_raw | Σ sign(Δprice) × volume | Raw flow direction |
| OFI_smoothed | 14-period SMA of OFI | Smoothed flow |
| OFI_gradient | OFI - OFI[5 bars ago] | Flow acceleration |
| OFI_percentile | Rank of current OFI in 100-bar window | Relative intensity |
| OFI_price_divergence | Correlation(OFI, price, 20 bars) | Divergence signal |

#### Entry Logic
```
LONG Entry Conditions:
  1. OFI_gradient > 0 (flow accelerating buy)
  2. Price near session low AND OFI > 0 (absorption)
  3. OFI_percentile > 70 (strong buying)
  4. Optional: OFI_price_divergence < -0.5 (bearish divergence = long signal)

SHORT Entry Conditions:
  1. OFI_gradient < 0 (flow accelerating sell)
  2. Price near session high AND OFI < 0 (absorption)
  3. OFI_percentile > 70 (strong selling)
  4. Optional: OFI_price_divergence > 0.5 (bullish divergence = short signal)
```

#### Session-Based Enhancement
```python
# London/NY overlap (8-12 EST) has highest volume = best OFI signals
if current_session == LONDON or current_session == NY_AM:
    ofi_significance_boost = 1.5
else:
    ofi_significance_boost = 1.0
```

#### Risk Management
- **OFI confirmation filter:** Require OFI_gradient and price direction agree
- **Stop loss:** 1.5 ATR (tight for H1 microstructure)
- **Position size:** 0.8x normal (novel signal = higher uncertainty)

#### Parameters to Optimize
| Parameter | Range | Step |
|-----------|-------|------|
| ofi_period | 10-30 | 5 |
| ofi_smoothed_period | 5-20 | 5 |
| gradient_lookback | 3-10 bars | 1 |
| percentile_lookback | 50-200 bars | 25 |
| entry_threshold_percentile | 60-80 | 5 |

#### Walk-Forward Testing Plan
1. **Train:** 2019-2021
2. **Test:** 2022-2023 OOS
3. **Session analysis:** Performance breakdown by session
4. **Volume analysis:** Correlation between OFI quality and volume levels

#### Expected Performance
- **Win Rate:** 40-50%
- **Profit Factor:** 1.6-2.2
- **Max DD:** <10%
- **Sharpe:** 1.2-1.6

---

## Implementation Notes

### ISignalStrategy Interface Compliance
All strategies implement:
```python
class ISignalStrategy:
    @property
    def name(self) -> str:
        raise NotImplementedError

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        raise NotImplementedError
```

### MarketState Extensions Required
For ML strategies, extend `MarketState` to include:
```python
@dataclass
class MarketState:
    bars: List[Bar]
    current_session: SessionType
    
    # New for ML strategies
    timeframe: str = "H1"  # Current timeframe being evaluated
    higher_timeframe_bars: List[Bar] = None  # H4 bars for MTF analysis
    pair: str = "EURUSD"
    
    @property
    def latest_bar(self) -> Bar:
        return self.bars[-1]
```

### Backtest Compatibility
All strategies must work with existing `BacktestConfig`:
- `risk_per_trade_pct: 0.01` (1% risk per trade)
- `max_daily_drawdown_pct: 0.02` (2% daily DD limit)
- `max_total_drawdown_pct: 0.05` (5% total DD limit)
- FTMO $10k challenge rules apply

---

## Recommended Testing Priority

| Phase | Strategy | Duration | Dependencies |
|-------|----------|----------|--------------|
| 1 | Strategy 3 (Markov Filter) | 1 week | None |
| 2 | Strategy 4 (Vol Regime) | 1 week | None |
| 3 | Strategy 1 (HMM Selector) | 2 weeks | Phase 1, 2 |
| 4 | Strategy 6 (OFI) | 2 weeks | None |
| 5 | Strategy 2 (LightGBM) | 3 weeks | Phase 1 |
| 6 | Strategy 5 (Ensemble) | 2 weeks | Phase 3, 4 |

**Estimated total time:** 8-10 weeks for full backtest pipeline

---

## Key Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Overfitting to historical data | Walk-forward validation, strict OOS criteria |
| ML model degradation | Monthly retraining, feature drift monitoring |
| Regime filter whipsaws | Require regime stability confirmation |
| Low signal frequency | Combine multiple strategies in ensemble |
| FTMO DD breaches | Dynamic position sizing, daily loss limits |

---

## Conclusion

The 6 strategies above represent the next generation of our trading system. They address the core weaknesses of previous NO-GO strategies:

1. **Subjectivity removed** — ML and regime models are data-driven
2. **Regime adaptability** — No single strategy forced to work in all conditions
3. **Ensemble robustness** — Uncorrelated strategies reduce drawdowns
4. **Microstructure edge** — OFI captures institutional flow

**Recommended first implementation:** Strategy 3 (Markov Regime Filter) — lowest complexity, immediate improvement to existing strategies, clear theoretical basis.

---

**Research conducted by:** Research Manager (790e1a25-6d3e-47e8-a64f-1654bedb273e)  
**Date:** 2026-04-05  
**Next Steps:** Move to implementation phase for Strategy 3 + 4, then HMM selector
