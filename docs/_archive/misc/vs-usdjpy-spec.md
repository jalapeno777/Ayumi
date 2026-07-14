# SPEC: Volatility Squeeze Breakout on USDJPY H1

**Issue:** [AYUAA-581](/AYUAA/issues/AYUAA-581)
**Type:** Strategy Research Spec
**Status:** Draft
**Research Manager**

---

## Executive Summary

Recommend **Volatility Squeeze Breakout on USDJPY H1** as the complementary strategy to pair with GBPUSD Session Range MR.

**Rationale:**
- **Complementary regime:** USDJPY is more trending/carry-sensitive than GBPUSD's ranging behavior
- **Correlation low:** USDJPY correlation to GBPUSD is ~0.3-0.5 vs 0.75+ for EURUSD-GBPUSD
- **Volume-free:** Uses ATR, Bollinger, Keltner, ADX — no volume dependency
- **Data available:** USDJPY H1 data confirmed present in historical dataset
- **Strategy exists:** `strategies/volatility_squeeze.py` already implemented

---

## Why Not Other Candidates

| Candidate | Reason to Defer |
|-----------|-----------------|
| XAUUSD Volatility Squeeze | Gold has extreme volatility spikes requiring very different parameters; gold-specific tuning not yet validated |
| MICS | Untested — would require full implementation before walk-forward |
| RWMR | Untested — adaptive lookback concept, no existing implementation |
| OFI | Untested — microstructure proxy needs validation against actual data quality |
| Session Range MR on USDJPY | Duplicates Session Range MR mechanism; need different regime type for complementarity |

---

## Strategy: Volatility Squeeze Breakout (USDJPY-H1)

### Core Logic

The Volatility Squeeze detects periods when Bollinger Bands contract inside Keltner Channels — indicating low volatility that typically precedes explosive moves. The strategy trades the breakout when volatility expands.

**Key differences from existing VolatilitySqueezeStrategy:**
- Use USDJPY-specific preset (tighter ATR multiplier for JPY pairs)
- Add momentum confirmation (RSI filter)
- Session filter limited to NY_AM + London overlap only

### Parameters (USDJPY-H1 Preset)

```python
USDJPY_H1_VS_PRESET = VolatilitySqueezeConfig(
    bb_period=20,
    bb_std_dev=2.0,
    kc_period=20,
    kc_atr_multiplier=1.5,        # tighter than EURUSD default 2.0
    squeeze_threshold=0.0,
    min_squeeze_bars=3,
    ema_period=50,               # longer EMA for USDJPY trending
    adx_period=14,
    adx_min=22,                  # higher threshold for cleaner signals
    atr_period=14,
    atr_sl_multiplier=1.5,
    tp1_rr=1.0,
    tp2_rr=2.0,
    tp3_rr=3.0,
    session_filter=True,
)
```

### Entry Conditions

1. **Squeeze detected:** BB upper ≤ KC upper AND BB lower ≥ KC lower for ≥ 3 consecutive bars
2. **Squeeze release:** BB exits outside KC (Bollinger breaks Keltner boundary)
3. **Trend confirmation:** ADX > 22 (not just present, but confirming trending)
4. **EMA alignment:** Price above EMA(50) for longs, below for shorts
5. **Session:** Within London overlap (12-16 UTC) or NY_AM (12-15 UTC)
6. **RSI filter:** RSI(14) < 70 for longs, RSI(14) > 30 for shorts (avoid extremes)

### Risk Management

- **Stop Loss:** 1.5 × ATR from entry
- **Take Profit:** 1.0× RR (TP1), 2.0× RR (TP2), 3.0× RR (TP3)
- **Position:** 1% risk per trade (FTMO compliant)
- **Max Daily Trades:** 3
- **Max Concurrent:** 1

---

## Walk-Forward Testing Plan

### Configuration
- **Pair:** USDJPY
- **Timeframe:** H1
- **Windows:** 5 (anchored, same as GBPUSD Session Range MR)
- **Train/Test:** 70/30 split
- **Spread:** 1.5 pips (USDJPY typical)

### Acceptance Criteria (Same as FTMO)
| Metric | Threshold |
|--------|-----------|
| Win Rate | >55% |
| Profit Factor | >1.5 |
| Max Drawdown | <5% |
| Sharpe Ratio | >0.5 |
| OOS Trades | 50+ |
| Profitable Windows | 3+ of 5 |

### Phase 1: Baseline Walk-Forward
Run existing VolatilitySqueezeStrategy with USDJPY_H1 preset against 5-window walk-forward.

**If 3+/5 windows pass:** Proceed to Phase 2 (parameter tuning)
**If 2/5 windows pass:** Tune parameters and re-run
**If 0-1/5 windows pass:** Fall back to XAUUSD variant

### Phase 2: Parameter Tuning (if needed)
Use Optuna with search space:
- `bb_std_dev`: 1.8 to 2.5 (step 0.1)
- `kc_atr_multiplier`: 1.2 to 2.0 (step 0.1)
- `min_squeeze_bars`: 2 to 5 (step 1)
- `adx_min`: 18 to 28 (step 2)
- `ema_period`: 20 to 100 (step 10)

### Phase 3: Validation
Run 50-trial Optuna optimization with 5-window CV objective = mean Sharpe ratio.

---

## Expected Performance

Based on similar strategies in our backtest history:

| Scenario | WR | PF | Sharpe | Windows Passed |
|----------|----|----|--------|----------------|
| Optimistic | 58-62% | 1.6-2.0 | 1.5-2.5 | 4-5/5 |
| Base case | 55-58% | 1.4-1.6 | 1.0-1.5 | 3-4/5 |
| Conservative | 52-55% | 1.2-1.4 | 0.5-1.0 | 3/5 |

**Confidence: MEDIUM-HIGH**
- Strategy type (volatility breakout) has historical edge on USDJPY
- JPY pairs respond well to range contraction signals
- Existing implementation reduces implementation risk

---

## Complementarity with GBPUSD Session Range MR

| Aspect | GBPUSD Session Range MR | USDJPY Volatility Squeeze |
|--------|------------------------|---------------------------|
| Timeframe | H1 | H1 |
| Market condition | Ranging (low ATR) | Trending/breakout (high ATR) |
| Session focus | London open (7-11 UTC) | NY_AM + overlap (12-16 UTC) |
| Signal type | Mean reversion | Momentum breakout |
| Typical holding | Hours | Hours to 1 day |
| Correlation | — | ~0.35 (low) |

**Combined exposure:** When GBPUSD Session Range MR is active (Asian/London open ranging), USDJPY Volatility Squeeze is typically dormant, and vice versa.

---

## Implementation Notes

1. Use existing `strategies/volatility_squeeze.py` as base
2. Create `strategies/volatility_squeeze_usdjpy.py` with USDJPY-specific preset
3. Add RSI filter to base strategy or make configurable
4. Walk-forward runner: `python -m backtest.runner --strategy volatility_squeeze_usdjpy --pair USDJPY --timeframe H1`
5. Use same runner as Session Range MR for consistency

---

## Next Steps

| Step | Owner | Time |
|------|-------|------|
| Phase 1: Baseline WF run | Junior Dev / Eval Engineer | 1-2 hours |
| Phase 2: Tune if needed | Research Manager | 2-4 hours |
| Phase 3: Optuna validation | Senior Dev | 4-8 hours |
| QA Gate | Sage | 1 hour |

---

**Recommended action:** Proceed to Phase 1 walk-forward run immediately.

**Estimated timeline:** 1-2 days to GO/NO-GO decision.

**Risks:**
- USDJPY may have different optimal parameters than our preset
- Walk-forward windows may show high variance (common for JPY during BOJ interventions)
- If 0/5 windows pass, fall back to XAUUSD variant

---

**Research conducted by:** Research Manager
**Date:** 2026-04-07
**For Engineering:** Run Phase 1 walk-forward, then determine next step based on results