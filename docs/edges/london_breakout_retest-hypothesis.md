# Edge Hypothesis: London Breakout Retest

## HYPOTHESIS
The Asian session (00:00–07:00 UTC) establishes a high/low range on XAUUSD and major FX pairs; the London open (07:00 UTC) generates an institutional breakout of that range with above-average continuation probability; entering on the *retest* of the broken Asian level within 4 hours captures the rebalancing flow at favorable R:R asymmetry.

## MECHANISM
Three documented structural facts:

1. **Asian session establishes the daily range.** Asian liquidity is dominated by Tokyo carry-trade and JPY-related flow. The Asian high/low become the day's key levels because London/NY open with directional flow that targets these levels first. ICT and Inner Circle Trader literature both emphasize this; the "Asian range → London Judas Swing → NY continuation" is the textbook pattern.

2. **London open concentrates institutional flow.** BIS Triennial Survey: ~30% of daily FX turnover happens in the 07:00–09:00 UTC window. The institutional flow has a directional bias (based on overnight news, EU economic data), and it sweeps the Asian range high or low as the *first* move. This is documented in Osler (2003) "Currency Orders and Exchange Rate Dynamics" — stop-loss clusters at session-range levels make the sweep predictable.

3. **Retest within 4 hours = institutional rebalancing.** After the breakout, the price often pulls back to the broken level. If the pullback holds (price stays above the broken Asian high for long, or below for short), it signals that institutional flow is on the *continuation* side. The strategy enters on this confirmation with a tight stop (Asian low/high ± 0.5×ATR) and 1R/2R/3R targets.

4. **Range filter (8–60 pips).** Filters out days where the Asian range is too narrow (no real level) or too wide (already trending, no clean breakout). The 8-pip lower bound matches the average FX M15 ATR; 60-pip upper bound matches FX M15 4×ATR.

5. **XAUUSD-tuned defaults.** Pip size = 0.01 for gold (vs 0.0001 for FX); `buffer_pips=3.0` matches gold's wider tick noise. The strategy's defaults are explicitly XAUUSD-tuned.

## TIMEFRAME ARBITRAGE
- **Timeframe:** M15 (primary), H1 (secondary). M15 captures the retest cleanly within the 4-hour window.
- **Information asymmetry:** The retail trader sees the breakout and enters immediately; they get stopped out on the retest. The strategy enters *after* the retest, capturing the institutional continuation.
- **Speed advantage:** None in execution; the edge is in *patience*. The 4-hour retest window is patient by design.
- **Session timing:** London open 07:00 UTC = 02:00 EST (winter) / 03:00 EST (summer). The strategy is hard-coded to UTC; traders in other timezones must convert.

## FAILURE MODE
The strategy stops working when:

1. **No clean Asian range.** When Asian session is thin (Sunday open, holidays), the range is unreliable. The strategy's `min_asian_range_pips=8` filter handles this, but noisy thin bars can pass the filter and produce phantom breakouts. **Observable trigger:** Asian session has < 50% of normal bar count.

2. **News-driven breakouts that don't retest.** When NFP, CPI, or central-bank rate decisions fall inside the London window, the breakout is news-driven — there is no institutional flow waiting on the other side to fill the retest. The breakout *continues* without a pullback. **Observable trigger:** high-impact news event within 1 hour of London open.

3. **Low-volatility regime.** When ATR is at multi-month lows (e.g., summer doldrums), the Asian range is narrow and the breakout lacks follow-through. The strategy's range filter rejects too-narrow ranges, but borderline cases slip through.

4. **Asian range already broken during NY-PM of prior day.** When the prior day's NY-PM broke the Asian range, the next day's Asian range is meaningless (it's a continuation of the prior move). The strategy does not detect this.

5. **Late London entries.** The strategy's `trade_end_utc=11` means last entry is at 11:00 UTC (4 hours after London open). If the breakout happens at 10:30 UTC and the retest at 11:15 UTC, the strategy misses it. Cooldown of 20 bars = 5 hours on M15 means the next day's London open is the earliest next entry — also misses some valid setups.

6. **DST shift mis-matches.** Hard-coded UTC hours; DST shifts in US/EU mean the "London open" in UTC is stable but the news-release timing relative to the killzone shifts. Not a strategy bug, but a deployment hazard.

## EVIDENCE OUTSIDE BACKTEST
- **ICT literature:** The Asian range → London Judas Swing → NY expansion is the textbook ICT setup, documented across ICT student materials and "Trading in the Shadow of the Smart Money" (Huddleston 2021). Inner Circle Trader forums have thousands of trade journals confirming the pattern.
- **Academic:** Andersen & Bollerslev (1997) "Intraday Periodicity and Volatility Persistence in FX Markets" — documents the U-shaped intraday volatility pattern with peaks at 08:00 UTC (London) and 13:00 UTC (NY). The London breakout pattern exploits this structural volatility clustering.
- **Osler (2003):** "Currency Orders and Exchange Rate Dynamics: An Explanation for the Predictive Success of Technical Analysis" — directly documents that stop-loss clusters at session-range levels make the breakout-and-retest pattern predictable.
- **BIS Triennial Survey (2022):** Documents 60%+ of FX turnover in London/NY overlap window. Structural reason for killzone effectiveness.
- **Walk-forward reality:** SRF sweep: 7 cells tested. EURUSD M15 has PF=4.00 with 6 trades (1/5 windows passed the trend filter, but no go_nogo pass). GBPUSD M5 PF=0.11 (22 trades, 0/5 passed). GBPUSD M15 PF=0.14 (35 trades, 0/5 passed). GBPUSD H1 PF=0.13 (45 trades, 0/5 passed). XAUUSD M15 PF=0.02 (11 trades, 0/5 passed). **The 4.0 PF on EURUSD M15 is a 6-trade sample — statistically meaningless.**

## ALTERNATIVE EXPLANATIONS
Why the backtest might be misleading:

1. **Sample size is critical.** 6 trades on EURUSD M15 → 6 winners to hit PF=4.0. Binomial probability for 6/6 at 50% baseline: ~1.5%. Plausible by chance alone.

2. **XAUUSD results.** The strategy's defaults are XAUUSD-tuned (`pip_value=0.01` for XAU, `symbol='XAUUSD'`), but the SRF sweep shows **XAUUSD H1: 0 trades, XAUUSD M5: 0 trades, XAUUSD M15: 11 trades with PF=0.02**. The XAUUSD-tuned defaults are *worse* on XAUUSD than on FX. This is a strong signal that the "XAUUSD primary" claim in the docstring is aspirational, not empirical.

3. **Min range filter bias.** The strategy rejects Asian ranges < 8 pips or > 60 pips. On XAUUSD M15, the Asian range is typically 50–150 pips — frequently > 60 pips, so most days are filtered out. The 11 XAUUSD M15 trades in 5 windows is consistent with this.

4. **Cooldown starvation.** `cooldown_bars=20` on M15 = 5 hours. After a signal, the strategy cannot fire again until the next day's London open. If a valid setup occurs in NY overlap (12:00–16:00 UTC), the strategy misses it.

5. **Look-ahead in Asian range computation.** `_compute_asian_range` walks back through bars looking for the current day's Asian session. In live trading, the Asian range is only known after 07:00 UTC; the strategy correctly requires this. ✓ Clean.

6. **Retest direction logic.** The strategy requires `latest.close > asian_high` (long) or `latest.close < asian_low` (short) on the retest bar. This means the retest bar must close *beyond* the broken level — not just touch it. Many valid "wick-and-close-back-inside" retests are missed.

7. **Trade count is too low to be statistically meaningful.** Mean trades per cell: ~20 in 5 windows = 4 trades/window. SRF minimum is 15 trades per cell — most cells fail this. The EURUSD M15 PF=4.0 cell has 6 trades, below the minimum-trade threshold.

## KILL CRITERIA
Observable conditions that should cause us to stop trading London Breakout Retest:

1. **PF < 1.3 on any rolling 90-day window.** (Current state: all cells fail this criterion. **STOP IMMEDIATELY** in walk-forward.)

2. **Trade count < 5 in any 30-day window.** Below this, statistics are not meaningful. Current mean is 4/window. **STOP.**

3. **WR < 30% in 30 consecutive trades.** The strategy's expected WR is 40–50%; below 30% signals structural failure.

4. **High-impact news within 1 hour of London open on 3+ consecutive days.** (Strategy does not gate for news — known gap. Manually disable.)

5. **ATR at multi-month low (below 25th percentile of trailing 90-day ATR) AND trade frequency drops.** Low-vol regime kills the breakout-follow-through.

6. **DST transition week** (2 weeks in March/November). Manually disable during these windows; the hard-coded UTC hours mis-align with the news release schedule.

**STATUS: KILL.** SRF sweep shows 0/7 cells passing go_nogo. The hypothesis is structurally sound (ICT literature + Osler 2003 + Andersen-Bollerslev 1997 all support the pattern), but the implementation has: (a) sample-size issues (4 trades/window mean), (b) XAUUSD defaults that fail on XAUUSD, (c) no news gate, (d) cooldown starvation, (e) range filter that excludes most XAUUSD days. Recommendation: archive the file. If the Asian-London breakout hypothesis is desired, build a cleaner version with: H4 trend filter, news event gate, relaxed cooldown (5 bars), XAUUSD pip-value fix, and broader range filter (10–100 pips for gold).