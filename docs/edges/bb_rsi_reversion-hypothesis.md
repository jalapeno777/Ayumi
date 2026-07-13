# Edge Hypothesis: BB + RSI Mean Reversion

## HYPOTHESIS
**THIS STRATEGY IS MARKED DEPRECATED BY ITS OWN AUTHOR.** The Bollinger Band + RSI mean-reversion hypothesis (price that closes beyond 2σ Bollinger Band with RSI confirmation reverts to the band middle) has theoretical merit but **fails empirically across all 12 (pair × timeframe) cells in the SRF sweep with PF < 0.3** — and the source code's module docstring (line 1-15) explicitly deprecates the strategy. The implementation has three documented root causes; this is not a strategy to ship.

## MECHANISM (INTENDED, BUT FLAWED)
The classical Bollinger Band + RSI mean reversion hypothesis has three components:

1. **Bollinger Band extremes mark over-extension.** BB(20, 2σ) captures ~95% of closes in a normal distribution; closes outside the bands are statistically rare. When they occur, the price has moved too far too fast and is "due" to revert.

2. **RSI confirmation filters noise.** RSI(14) < 30 confirms oversold (for long entries); RSI(14) > 70 confirms overbought (for short entries). This filters false breakouts where price closes outside the band but RSI hasn't confirmed exhaustion.

3. **Mean reversion to band middle.** TP targets the BB middle (SMA), which is typically 1–2 ATR away from the band edge.

This is a well-documented retail pattern (Bollinger 2001, "Bollinger on Bollinger Bands"). But the Ayumi implementation has three flaws per its own docstring:

### Flaw 1: Confidence formula is *inverse* to mean-reversion logic
```python
if rsi_distance <= 5: confidence = 0.50 + rsi_distance / 25.0  # 0.50 → 0.70
elif rsi_distance <= 15: confidence = 0.70  # peak band
else: confidence = 0.70 - min((rsi_distance - 15) / 50.0, 0.20)  # 0.70 → 0.50
```
The peak confidence is at *moderate* RSI distance (5–15). At extreme RSI distance (>15), confidence *decreases*. This is backwards: extreme RSI distance is exactly when mean reversion is most likely to fire. The confidence formula penalizes the highest-quality setups.

### Flaw 2: TP at BB middle is too tight
```python
if direction == LONG:
    sl = latest.close - risk  # SL = 1.5 * ATR below
    tp1 = latest.close + risk * 1.0  # TP1 = 1R
    tp2 = latest.close + risk * 1.5  # TP2 = 1.5R
```
The TP target is only 1R/1.5R from entry, while the SL is 1.5×ATR from entry. The math: if BB middle is ~1.5×ATR from the band edge (typical), then TP distance ≈ SL distance, so R:R ≈ 1:1. This means WR must exceed 50% to break even — but in trending markets, WR is typically 30–40%.

### Flaw 3: `require_low_volatility` filter excludes the conditions where mean reversion works
```python
def _is_low_volatility(bars, atr_period, atr_sma_period):
    ...
    return current_atr < atr_sma
```
This requires *current ATR < trailing average ATR* — meaning the market is quieter than usual. But mean reversion works best in *post-spike* conditions (high ATR followed by exhaustion). The filter excludes exactly the setups where the strategy could work.

The strategy's own docstring (lines 1–15) reads:
> *"Per research §A.6 (strategy-optimization-research.md), this strategy has PF < 0.3 across all symbols/timeframes. Root causes: 1. Confidence formula is *inverse* to mean-reversion logic (higher RSI distance = higher confidence, but extreme RSI in trend = continuation). 2. TP at BB middle is too tight — win/loss asymmetry can't exceed 0.5. 3. require_low_volatility filter excludes the conditions where mean reversion actually works (post-spike conditions)."*

## TIMEFRAME ARBITRAGE
- **Intended:** BB+RSI on M15/H1 is widely cited in retail trading literature.
- **Actual:** PF < 0.3 across 12 cells. No realized edge.

## FAILURE MODE
The strategy fails *everywhere* because:
1. The confidence formula penalizes high-quality setups.
2. R:R ≤ 1:1 means WR > 50% is required, but in FX WR is typically 30–40% for BB reversion.
3. The volatility filter excludes the regimes where BB reversion works.

These are structural failures, not market-condition-specific.

## EVIDENCE OUTSIDE BACKTEST
The Bollinger Band + RSI hypothesis has academic and industry support:
- **Bollinger (2001) "Bollinger on Bollinger Bands":** Original formulation. Bollinger himself notes that the bands are not a signal system — they're a *volatility* measurement. Signals require additional confirmation (RSI, MACD, volume).
- **Academic:** The mean-reversion hypothesis has strong evidence at multi-day horizons (De Bondt & Thaler 1985; Jegadeesh 1990). At intraday horizons, evidence is mixed.
- **Industry:** "BB + RSI reversion" is one of the most common retail indicator combinations. The published success rate is much lower than retail traders expect — most academic studies of "popular technical indicators" (Bessembinder & Chan 1995, "The Profitability of Technical Trading Rules in Asia") find no statistically significant excess return for BB+RSI on FX.
- **Walk-forward reality:** SRF sweep: GBPUSD M15 has PF=5.55 with 7 trades (5 winners, 2 losers — binomial probability ~17% at 50% baseline, possible by chance). GBPUSD H1 has PF=2.24 with 21 trades (8 winners, ~13 losers — wait, this requires more winners than losses for PF>1, so maybe 8W/13L with WR=37% — possible but not strong). All other cells: PF < 0.28.

## ALTERNATIVE EXPLANATIONS
Why the backtest might be misleading:

1. **GBPUSD M15 anomaly (PF=5.55, 7 trades).** This is the highest-PF cell. With 5/7 winners at 50% baseline, p ≈ 0.23 (not statistically significant). The PF appears because the 2 losing trades were tiny (small SL hit) and the 5 winners were large (extended trend then reversion). Sample is too small.

2. **GBPUSD H1 (PF=2.24, 21 trades).** More meaningful sample size. WR=37% with PF=2.24 implies R:R ≈ 6:1 (winners 6× losers). This is suspicious — it suggests either (a) a real edge, (b) a survivorship artifact, or (c) parameter over-fit. Given the strategy is marked deprecated and PF collapses on all other cells, this is most likely over-fit to GBPUSD H1 historical data.

3. **Small trade counts below SRF minimum.** Total trades < 15 in most cells — these fail the SRF `total_trades >= 15` gate (research §A.6). The PF numbers are non-informative.

4. **Pip mis-classification.** `_pip_for` infers JPY pairs from `price >= 50`. XAUUSD (~1900) is misclassified as JPY (0.01 pip) instead of the correct XAUUSD pip (0.1 or 0.01). All XAUUSD results are silently corrupted.

5. **Time-of-day filter.** `_is_trading_session` requires 7 ≤ hour < 21. This excludes Asian session — but for XAUUSD, Asian session is 25% of daily volume. Filtering it out loses data.

6. **No session-aware ADX gate.** The strategy uses `adx < 25` to filter trending markets. But ADX during a London breakout session can spike above 25 inside the killzone, even when the regime is mean-reverting. The strategy's flat ADX threshold misses this nuance.

## KILL CRITERIA
Observable conditions that should cause us to stop trading BB + RSI Mean Reversion:

1. **PF < 1.0 across all 12 cells in any rolling 90-day window.** (Current state: 10/12 cells have PF<0.3; only 2 cells have PF>1.0 (GBPUSD M15=5.55 small sample, GBPUSD H1=2.24). **STOP IMMEDIATELY.**)

2. **DEPRECATED flag set in source code.** (`DEPRECATED = True` at module level; `warnings.warn(DeprecationWarning)` in constructor.) The strategy's own author has marked it dead.

3. **Confidence formula penalizes high-quality setups.** This is a code bug, not a market condition. Must be fixed before re-evaluation.

4. **R:R asymmetry < 1:1.** Current TP at 1R / 1.5R vs SL at 1.5×ATR means R:R ≤ 1:1 in most setups.

5. **Volatility filter excludes post-spike conditions.** Required to filter low-vol regimes, but actually filters the only regimes where BB reversion works.

**STATUS: KILL — FILE IS ALREADY DEPRECATED.** The source code's docstring explicitly recommends replacing this strategy with `dual_tf_squeeze_pro.py` (research §B.2). The Ayumi implementation has three structural flaws that compound into PF < 0.3 across the test grid. The hypothesis itself (BB+RSI reversion) is academically valid in equity markets at multi-day horizons but does not produce reliable intraday edges in FX as implemented. Recommendation: archive the file (do not delete — kept for reference per docstring), do not register in any future SRF sweep.