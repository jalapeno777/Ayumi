# Edge Hypothesis: Donchian ATR Trend

## HYPOTHESIS
Price trends on M15/H1 forex exhibit Donchian-channel breakout persistence — once price closes above the prior N-period high (or below the N-period low), the trend continues for enough additional bars to produce a positive expectancy when combined with an EMA trend filter and ATR-based trailing stop, exploiting the well-documented slow-information-diffusion anomaly in FX.

## MECHANISM
Donchian ATR Trend is a textbook trend-following strategy. Its edge comes from three documented market anomalies:

1. **Momentum persistence (behavioral + structural).** Academic literature (Jegadeesh & Titman 1993, "Returns to Buying Winners and Selling Losers") establishes that 6–12 month momentum in equities produces ~1% monthly excess return. Intraday equivalents are weaker but documented: Moskowitz, Ooi, Pedersen (2012) "Time Series Momentum" finds positive risk-adjusted returns across asset classes including FX at multi-week horizons. M15 trends compress this to hours, not months, but the underlying behavioral mechanism (herding, disposition effect, slow information diffusion) still operates.

2. **Adaptive ATR trailing stop (volatility matching).** Fixed-pip stops fail across volatility regimes; ATR(14) trailing stops scale naturally with current noise. Per research §A.5, the ATR trail is the *primary* exit — the strategy wins on the trailing stop, not the entry.

3. **EMA(50) trend filter (regime gate).** Longs only above EMA(50), shorts only below. This eliminates the majority of false breakouts that occur in mean-reverting regimes.

The combination targets the *trend leg* of FX moves — typically 30–60% of total price action (the rest being range/consolidation/chop). When ADX confirms trend strength (ADX ≥ 20), the breakout is more likely to persist.

## TIMEFRAME ARBITRAGE
- **Timeframe:** M15 / H1. Both tested in SRF sweep.
- **Information asymmetry:** None directly. Donchian breakouts are widely known. The edge, if any, comes from *execution discipline* — humans cut winners short, ride losers. The ATR trailing stop enforces discipline the human cannot.
- **Speed advantage:** Marginal. The breakout detection uses `bars[-(period+1):-1]` (excludes current bar), so the signal fires on the first qualifying close after the breakout. Sub-second latency helps with fill but not with the signal itself.
- **HTF trend:** The 50 EMA on M15/H1 is the local trend proxy; H4/D1 confirmation is not required but implied.

## FAILURE MODE
The strategy stops working when:

1. **Choppy / range-bound regime.** When ADX<20 for extended periods, Donchian breakouts fail repeatedly (false breakouts = whipsaws). SRF sweep: every cell has ADX≥20 enforced, yet mean PF=0.09 across 12 cells. This suggests ADX≥20 alone is insufficient as a regime gate. **Observable trigger:** ADX oscillating between 18–22 for 20+ bars (whipsaw zone).

2. **Whipsaw around major news events.** NFP, FOMC, ECB: the breakout detected on the post-news bar is often the *noise* of the news spike, not the start of a trend. The trend exhausts inside the next 4–8 bars. **Observable trigger:** bar immediately following a high-impact news release.

3. **Trend exhaustion in HTF.** When H4 trend has run > 8 ATRs, M15 Donchian breakouts become failed reversals. **Observable trigger:** distance from H4 EMA(50) > 5× H4 ATR.

4. **Friday afternoon / Sunday open thinness.** Friday 18:00–22:00 UTC and Sunday 22:00–Monday 02:00 UTC have wide spreads and unreliable breakouts. The strategy does not gate by session — a known gap.

5. **No cooldown around take-profit hits.** Cooldown of 5 bars (default `cooldown_bars=5`) is too short after a 3R win — the next bar's breakout is often a "trend exhaustion" bar, not a new trend start.

## EVIDENCE OUTSIDE BACKTEST
- **Academic (strong):** Moskowitz, Ooi, Pedersen (2012) "Time Series Momentum" — *Journal of Financial Economics* — finds time-series momentum works across 58 liquid instruments including FX. 12-month lookback, monthly rebalance. Intraday equivalents (M15/H1) are weaker but documented in commodity markets (Erb & Harvey 2006, "The Strategic and Tactical Value of Commodity Futures").
- **Academic (caveat):** The same literature documents *time-series momentum crashes* — long-only crash in March 2009, persistent reversals in 2008. The strategy is positive in aggregate but suffers long drawdown periods.
- **Industry:** The original "Turtle Trading" system (Dennis, Eckhardt 1983) was a 20/55-day Donchian breakout on futures; it produced 80%+ annualized returns 1984–1988. Modern Donchian trend-following is the basis of CTAs and managed-futures programs (SG CTA Index).
- **FX-specific:** FX trends are *shorter* and *weaker* than equity/commodity trends. Hurst, Ooi, Pedersen (2017) "A Century of Evidence on Trend-Following" documents FX trends work but with lower Sharpe than commodities.
- **Walk-forward reality:** SRF sweep shows Donchian ATR Trend produced 45+ trades per cell across 12 cells (mean ≈ 41 trades/cell), but mean PF=0.09 and 0/12 cells passed the go_nogo gate. This is *worse* than random (PF=1.0 = breakeven).

## ALTERNATIVE EXPLANATIONS
Why the backtest might be misleading:

1. **Look-ahead in Donchian computation.** `_donchian_high` uses `bars[-(period+1):-1]` — correctly excludes current bar. ✓ Clean.
2. **Cooldown state across bars.** The strategy uses `self._bars_since_signal` which persists across `evaluate()` calls. In a real backtest, this depends on the runner correctly calling `evaluate()` on every bar. If the runner skips bars, cooldown is broken.
3. **EMA(50) calculation period.** `_calculate_ema` requires `len(values) >= period`. If the runner passes fewer bars (e.g., during warmup), the EMA falls back to mean of available values — silently corrupting the trend filter.
4. **ADX threshold of 20 is universally low.** Most trend-following literature uses ADX≥25 as the regime gate. The 20 threshold likely catches too many false breakouts.
5. **`min_confidence=0.45` ceiling.** The confidence formula `min_confidence + (adx - adx_threshold) * 0.005 + breakout_dist/atr * 0.05` produces values in 0.45–0.85 range. Combined with engine-level `min_confidence=0.30` filter, this isn't the binding constraint. But the *signal frequency* and the confidence-value-to-edge mapping are not validated — the system may be filtering winners as aggressively as losers.
6. **PF=0.09 across 12 cells is not noise.** This is consistent — almost every cell loses money. This is more likely a *real* negative expectancy than a backtest artifact. The strategy's logic is sound; the parameters or the data regime simply don't reward it.

## KILL CRITERIA
Observable conditions that should cause us to stop trading Donchian ATR Trend:

1. **PF < 1.0 across all 12 cells in any rolling 90-day window.** (Current state: 0/12 cells pass PF≥1.0. Already triggering this criterion in walk-forward. **STOP IMMEDIATELY**.)

2. **WR < 35% across rolling 100 trades.** Trend-following strategies have inherently low WR; below 35% means R:R is collapsing too.

3. **Consecutive losing trades > 12.** Trend followers expect streaks; > 12 in a row signals regime shift or broken logic.

4. **ADX < 20 across all 4 pairs for 5+ sessions.** Regime has shifted to mean reversion; Donchian breakouts will fail.

5. **Max drawdown > 8% on any single cell in 90-day window.** Current max_dd is 5.6–6.0% across cells, but with PF=0.09, the drawdown is *uncompensated* (no expectation of recovery). This is not a viable strategy.

**STATUS: KILL.** SRF sweep shows 0/12 cells passed go_nogo; mean PF=0.09 is statistically indistinguishable from a losing strategy. The hypothesis (trend persistence in FX) is academically valid at multi-week horizons, but M15/H1 Donchian breakout with 20-period lookback and ADX≥20 gate is too noisy. Recommendation: archive the file; if trend-following is desired, build a longer-lookback Donchian (50+ bar) with stricter regime filter (ADX≥25 + H4 trend confirmation).