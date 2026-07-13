# Edge Hypothesis: Killzone Momentum

## HYPOTHESIS
When the prior session (Asian or London) establishes a defined range, the next session's "killzone" (London 07:00–10:00 UTC, NY 12:00–15:00 UTC, Overlap 12:00–16:00 UTC) produces a directional breakout of that range with above-average continuation probability — and entering on the *retest* of the broken level (rather than the initial breakout) captures the institutional re-pricing flow with favorable R:R asymmetry.

## MECHANISM
The edge rests on three documented structural facts:

1. **Session-range liquidity voids.** Asian session (00:00–07:00 UTC) is dominated by Tokyo flow and tends to *establish* a daily range rather than break one. London open (07:00 UTC) and NY open (12:00 UTC) see institutional flow expansion — that flow frequently sweeps the Asian/London range high or low as the first directional move, then *reverses* to fill the void. The strategy enters on this reversal at the retest of the broken level.

2. **Killzone timing (volatility clustering).** Per ICT and market-microstructure literature, London and NY opens see concentrated institutional order flow. This is not folklore: BIS Triennial Survey documents FX turnover peaks at 08:00 UTC (London) and 13:00 UTC (NY). The retest-within-killzone has higher WR than retests outside killzone because the liquidity to fill the void is on the other side of the order book.

3. **Retest + rejection candle confirmation.** The strategy requires a *bullish/bearish rejection candle* (defined wick ratio) at the retest level. This filters out "price-tagged-the-level" from "price-was-rejected-at-the-level" — the latter is the institutional footprint of absorption.

4. **ADX trend filter (ADX≥15) + EMA(50) trend direction.** Retests that align with the local EMA(50) trend produce continuation; counter-trend retests fail. ADX≥15 ensures enough trend strength that the breakout leg has follow-through.

5. **ATR-distance retest tolerance (1×ATR).** The retest must occur within 1×ATR of the broken level. Tight tolerance = high-quality setup; loose tolerance = noise.

The combination targets the institutional flow *during* the retest, not the initial breakout — exploiting the documented post-breakout liquidity void.

## TIMEFRAME ARBITRAGE
- **Timeframe:** M15 / H1 / M5 (XAUUSD preset). The retest window is 6–12 bars on M15 (1.5–3 hours) — the institutional rebalancing happens within this window or doesn't happen.
- **Information asymmetry:** The retail trader sees the breakout and enters immediately, getting stopped out on the retest. The institutional flow that caused the retest is invisible to retail — it appears as "noisy price action." The strategy explicitly waits for the rejection candle at the retest, capturing the institutional absorption.
- **Speed advantage:** None in execution; the strategy enters on the *retest*, which is 1–4 hours after the breakout. This is a *patience* edge, not a speed edge.
- **XAUUSD M5 preset:** The `m5_xauusd()` preset raises `min_session_range_pips` from 8 to 25 (gold M5 sessions are wider) and shortens `breakout_lookback_bars` from 12 to 8 (M5 resolves breakouts faster). The asymmetry is real and time-frame-specific.

## FAILURE MODE
The strategy stops working when:

1. **Range expansion day (no setup).** When Asian session range is > 60 pips on FX M15 or > 100 pips on XAUUSD M5, the breakout-and-retest pattern breaks down — the move is too large to retrace cleanly. **Observable trigger:** session_range_pips > 1.5× 20-day median.

2. **Central-bank event in killzone.** When NFP/CPI/FOMC falls inside London or NY killzone, the breakout becomes a *news-driven spike*, not a session-driven institutional move. Retests fail because no institutional flow is waiting on the other side. **Observable trigger:** high-impact event scheduled within the killzone window.

3. **Carry-trade trend day.** When a pair is trending on rates-differential repricing (e.g., JPY pairs during BOJ pivot), the session range gets destroyed in one direction without a retest. ADX often exceeds 25 in this regime — should be filtered, but the ADX gate is set to 15 (low).

4. **Low-liquidity sessions.** Asian session (when used as the prior range source) on Sundays or holidays produces unreliable ranges. **Observable trigger:** Asian session has < 50% of normal bar count.

5. **Mid-week news cascade (Wed/Thu).** Multiple data releases across two consecutive sessions can produce overlapping breakouts that the strategy mis-identifies.

6. **ADX≥15 is too permissive.** The strategy uses `adx_threshold=15` (research §A.4 relaxed from 20). On M5, ADX=15 is essentially baseline noise. False breakout rate increases substantially.

## EVIDENCE OUTSIDE BACKTEST
- **ICT/SMC literature:** The "Judas Swing" concept (false breakout at session open, then reversal) is the textbook pattern Killzone Momentum is built on. Documented in ICT student materials, "Trading in the Shadow of the Smart Money" (Huddleston 2021), and confirmed by inner-circle-trader trade journals.
- **Academic:** Andersen & Bollerslev (1997) "Intraday Periodicity and Volatility Persistence in FX Markets" documents the U-shaped intraday FX volatility pattern with peaks at London and NY opens. This is the structural reason killzones exist.
- **Academic (specific to strategy):** Osler (2003) "Currency Orders and Exchange Rate Dynamics: An Explanation for the Predictive Success of Technical Analysis" — documents that stop-loss orders cluster at session-range levels; the strategy's retest entry exploits the predictable behavior of these clustered orders.
- **BIS Triennial Survey (2022):** Documents 60%+ of FX turnover occurs within London/NY overlap window. The liquidity to fill the retest void is structural, not anecdotal.
- **Walk-forward reality:** SRF sweep: 7 cells tested (3 pairs × ~2 timeframes); EURUSD H1 has PF=2.06 but only 8 trades; GBPUSD H1 PF=2.04 with 7 trades; XAUUSD M5 PF=0.97 with 36 trades; everything else fails. The pattern: **EURUSD/GBPUSD H1 with 7–8 trades can pass, but sample size is too small to be statistically meaningful**. XAUUSD M5 produces 36 trades with PF=0.97 — sub-1.0 but close, and 1/5 windows passed.

## ALTERNATIVE EXPLANATIONS
Why the backtest might be misleading:

1. **Sample size is the dominant risk.** EURUSD H1: 8 trades → 7 winners to hit PF=2.06. Binomial probability for 7/8 at 50% baseline WR: ~3.5%. Not impossible, but not statistically robust. SRF sweep uses 5 walk-forward windows; only 1 passed on XAUUSD M5 (PF=0.97 < 1.3 gate).

2. **Session boundary hard-coded.** `_calculate_session_range` uses UTC hours directly. US/EU DST shifts mean the "London open" in UTC shifts twice a year. The strategy does not adjust for DST — meaning the killzone is wrong for ~50% of the year (depending on FX pair).

3. **Asian session fallback logic.** When Asian range is empty (Sunday, holidays), the strategy falls back to prior-day London — but the prior-day London was already broken during NY. The fallback produces phantom ranges.

4. **`breakout_lookback_bars=12` on M15 = 3 hours.** The retest window is 3 hours. On XAUUSD M5 with `lookback=8` = 40 minutes. Both are tight enough that many valid retests are missed.

5. **`_detect_prior_breakout` uses `atr * breakout_mult (0.3)`.** 0.3×ATR breakout threshold is small (~5 pips on FX M15, ~50 cents on gold M15). Many "breakouts" are just noise — they don't have institutional flow behind them.

6. **ADX=15 threshold is research-driven over-relaxation** (per research §A.4: "20 too restrictive on M5; 15 still requires mild trend"). This is a known over-fit that may not survive OOS.

## KILL CRITERIA
Observable conditions that should cause us to stop trading Killzone Momentum:

1. **PF < 1.3 on rolling 90-day window for the active (pair, timeframe).** SRF gate is PF≥1.3 AND windows_passed≥4/5. Current best is XAUUSD M5 PF=0.97 with 1/5 windows — below the gate.

2. **Trade count < 5 in any 30-day window.** Below this, statistics are not meaningful. Current XAUUSD M15 has 20 trades in 5 windows = ~4/window. Marginal.

3. **WR < 25% in 30 consecutive trades.** The strategy's WR ceiling is ~50% (rejection candle confirmation); below 25% signals structural failure.

4. **ADX < 12 across all pairs for 5+ sessions.** Regime has shifted to deep consolidation; killzone breakouts won't follow through.

5. **High-impact event within 30 minutes of killzone window AND a position is open.** Close position immediately. (Strategy does not implement this gate — known gap.)

6. **DST shift not handled for 7+ days.** (Strategy does not auto-adjust for DST — known gap.) Manually disable during the 2-week DST transition window.

**STATUS: MARGINAL — REFINE, DON'T SHIP.** The hypothesis is structurally sound and the academic evidence is robust. But the implementation has sample-size issues (most cells have <50 trades), ADX gate is too permissive (15), DST is not handled, and the SRF sweep shows 0/7 cells passing the go_nogo gate. Recommend: (a) fix DST handling, (b) raise ADX gate to 18–20 on H1, lower on M5, (c) widen retest tolerance to 1.5×ATR for XAUUSD M5 (gold retests are slower), (d) require trend confirmation from H4 EMA (cross-timeframe filter), (e) re-run sweep before deployment.