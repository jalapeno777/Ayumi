# Portfolio Blend Evaluation — XAUUSD

**Symbol:** XAUUSD  
**Timeframes:** M15, H1  
**Starting balance:** $10,000.00  
**Risk per trade:** 0.5% = $50.00  
**Trade exit:** 3-leg partial exits (1/3 at 1R, 2R, 3R), time-stop 50 bars  
**Bars loaded:** M15=71747, H1=17948

## 1. Per-Strategy Breakdown

| Strategy | Timeframe | Trades | Wins | Losses | WR | Net P&L | Gross Win | Gross Loss | PF | Avg R |
|---|---|---|---|---|---|---|---|---|---|---|
| killzone_momentum | M15 | 1283 | 538 | 745 | 41.9% | $-7905.08 | $27582.20 | $35487.28 | 0.78 | -0.12R |
| killzone_momentum | H1 | 341 | 118 | 223 | 34.6% | $-4250.00 | $6366.67 | $10616.67 | 0.60 | -0.25R |
| srmr_plus | M15 | 503 | 159 | 344 | 31.6% | $-6307.68 | $10892.32 | $17200.00 | 0.63 | -0.25R |
| srmr_plus | H1 | 211 | 46 | 165 | 21.8% | $-5525.59 | $2724.41 | $8250.00 | 0.33 | -0.52R |
| volatility_regime_breakout | M15 | 1 | 0 | 1 | 0.0% | $-50.00 | $0.00 | $50.00 | 0.00 | -1.00R |
| volatility_regime_breakout | H1 | 1 | 0 | 1 | 0.0% | $-50.00 | $0.00 | $50.00 | 0.00 | -1.00R |
| donchian_atr_trend_v2 | M15 | 2006 | 815 | 1191 | 40.6% | $-16022.46 | $40401.61 | $56424.08 | 0.72 | -0.16R |
| donchian_atr_trend_v2 | H1 | 0 | 0 | 0 | n/a | $0.00 | $0.00 | $0.00 | n/a | n/a |
| dual_tf_squeeze_pro | M15 | 1427 | 646 | 781 | 45.3% | $-5364.28 | $31545.54 | $36909.82 | 0.85 | -0.08R |

### 1.1 Trade Outcome Breakdown

Each trade has 3 legs (1/3 position at TP1, TP2, TP3). A trade's outcome reflects the best TP reached before SL/time-stop:

| Strategy | Timeframe | SL | TP1 | TP2 | TP3 | TIME |
|---|---|---|---|---|---|---|
| killzone_momentum | M15 | 793 | 356 | 130 | 0 | 4 |
| killzone_momentum | H1 | 236 | 58 | 47 | 0 | 0 |
| srmr_plus | M15 | 371 | 0 | 132 | 0 | 0 |
| srmr_plus | H1 | 183 | 0 | 28 | 0 | 0 |
| volatility_regime_breakout | M15 | 1 | 0 | 0 | 0 | 0 |
| volatility_regime_breakout | H1 | 1 | 0 | 0 | 0 | 0 |
| donchian_atr_trend_v2 | M15 | 1248 | 606 | 131 | 0 | 21 |
| donchian_atr_trend_v2 | H1 | 0 | 0 | 0 | 0 | 0 |
| dual_tf_squeeze_pro | M15 | 832 | 530 | 62 | 0 | 3 |

**Observation:** All strategies show SL as the dominant outcome (60-90% of trades). 
This indicates the stop-loss is being hit before any take-profit level — the strategies are 
entering too late or with stops too tight for the prevailing XAUUSD volatility regime.

## 2. Blended Equity Curve

**Total trades:** 5773  
**Winners:** 2322 (40.2%)  
**Losers:** 3451  
**Gross profit:** $119512.76  
**Gross loss:** $164987.84  
**Overall PF:** 0.72  
**Net P&L:** $-45475.08 (-454.75%)  
**Final equity:** $-35,475.08  

**Max drawdown (peak-to-trough):** $45910.21 (439.96%)  
**Worst day:** 2026-02-13 — 6.50% of starting balance  
**Best day:** n/a (no cumulative profit)  

## 3. Per-Strategy Contribution to Total P&L

| Strategy | Trades | Net P&L | % of Total | Avg Trade |
|---|---|---|---|---|
| donchian_atr_trend_v2 (M15) | 2006 | $-16022.46 | +35.2% | $-7.99 |
| dual_tf_squeeze_pro (M15) | 1427 | $-5364.28 | +11.8% | $-3.76 |
| killzone_momentum (H1) | 341 | $-4250.00 | +9.3% | $-12.46 |
| killzone_momentum (M15) | 1283 | $-7905.08 | +17.4% | $-6.16 |
| srmr_plus (H1) | 211 | $-5525.59 | +12.2% | $-26.19 |
| srmr_plus (M15) | 503 | $-6307.68 | +13.9% | $-12.54 |
| volatility_regime_breakout (H1) | 1 | $-50.00 | +0.1% | $-50.00 |
| volatility_regime_breakout (M15) | 1 | $-50.00 | +0.1% | $-50.00 |

## 4. FTMO Viability Verdict

**FTMO 1-Step Standard requirements:**

| Criterion | Required | Actual | Pass? |
|---|---|---|---|
| Profit factor | ≥ 1.0 | 0.72 | ❌ |
| Max DD (peak-to-trough) | < 10% | 439.96% | ❌ |
| Max daily DD | < 5% | 6.50% | ❌ |
| Profit target | ≥ $1000 (+10%) | $-45475.08 (-454.75%) | ❌ |
| Best day rule | < 50% of profit | n/a | n/a |

### **Verdict: ❌ FAIL**

Failing criteria: max_dd_pct_lt_10, max_daily_dd_pct_lt_5, profit_target_10pct

**Bottom line:** The blend loses $45,475 (≈4.5× the starting balance) over the test window. 
No combination of these strategies can produce a viable FTMO submission on XAUUSD as currently configured. 
The negative expectancy is at the individual-strategy level, not the blend level — even picking the best 
single strategy (dual_tf_squeeze_pro, PF 0.85) loses $5,364 over the window. 
Diversification cannot offset a negative edge.

## 5. Strategy Correlation Matrix (Daily P&L)

| | donchian_atr_trend_v2 | dual_tf_squeeze_pro | killzone_momentum | srmr_plus | volatility_regime_breakout |
|---|---|---|---|---|---|
| donchian_atr_trend_v2 | +1.00 | +0.02 | +0.15 | -0.03 | +0.00 |
| dual_tf_squeeze_pro | +0.02 | +1.00 | -0.00 | +0.06 | +0.03 |
| killzone_momentum | +0.15 | -0.00 | +1.00 | -0.04 | +0.04 |
| srmr_plus | -0.03 | +0.06 | -0.04 | +1.00 | -0.06 |
| volatility_regime_breakout | +0.00 | +0.03 | +0.04 | -0.06 | +1.00 |

**Correlation interpretation:**
- |r| ≥ 0.7 → highly correlated (limited diversification)
- 0.3 ≤ |r| < 0.7 → moderate correlation
- |r| < 0.3 → low correlation (good diversification)

**No highly correlated pairs found.**

## 6. Recommendation

**Per-strategy inclusion decision (blend-level):**

- **DROP** `killzone_momentum` — net negative ($-12155.08)
- **DROP** `srmr_plus` — net negative ($-11833.27)
- **DROP** `volatility_regime_breakout` — net negative ($-100.00)
- **DROP** `donchian_atr_trend_v2` — net negative ($-16022.46)
- **DROP** `dual_tf_squeeze_pro` — net negative ($-5364.28)

**⚠️ No strategy meets the inclusion criteria.** The blended portfolio as defined is unviable.

**Root cause:** Every strategy in the blend has a sub-1.0 profit factor on XAUUSD over the 2022-2026 backtest window. With SL hitting on 60-90% of trades and TP1/TP2 only partial-exiting, the strategies are net negative. Combining negatively-correlated strategies cannot rescue a negative expectancy blend — the best PF (dual_tf_squeeze_pro at 0.85) still loses money per unit risk.

**Suggestions to consider (out of scope for this blend eval):**
1. Re-examine strategy parameters — the SL distance may be too tight for XAUUSD's 2022-2026 volatility expansion.
2. Investigate whether the strategies were tuned on a different dataset (e.g. FX H1) and are now mis-applied to XAUUSD M15/H1.
3. Consider a meta-strategy that filters signals by regime (e.g. only trade when volatility_regime_breakout's setup is active).
4. Run the same strategies on EURUSD/GBPUSD where they were originally tuned; XAUUSD may simply not be the right instrument.

## 7. Methodology Notes

- **Data source:** DuckDB at `data/ayumi_market.duckdb` (no CSV files used)
- **Signal generation:** bar-by-bar streaming with bounded rolling window (300 bars M15, 100 bars H1)
- **Memory-bounded:** strategies receive a fresh 300/100-bar window each bar; internal state maintained by strategy.dual_tf_squeeze_pro via on_bar()
- **Trade simulation:** entry at signal bar's close; 3-leg partial exits (1/3 at 1R/2R/3R); SL has priority on same bar; time-stop at 50 bars
- **Position sizing:** fixed 0.5% risk per trade ($50 on $10k)
- **Correlation:** Pearson correlation on daily P&L across strategies
- **Excluded:** DualTFSqueezePro on H1 (M15-only; aggregates to H1 internally)
