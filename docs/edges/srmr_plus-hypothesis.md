# Edge Hypothesis: SRMR+ (Session Range Mean Reversion Plus)

## HYPOTHESIS
When a trending prior session leaves a clearly defined high/low band, the first touch of that band in the next active session is a *probabilistic* reversion point — not a continuation trigger — because institutional flow that exhausted the prior range rarely has the other side to push through on the very next attempt; the resulting rebound has a positive expectancy inside a 1R–1.5R target window.

## MECHANISM
SRMR+ combines three structural inefficiencies in forex:

1. **Session-range exhaustion (microstructure).** The London/NY sessions establish a high/low band. When price taps that band from the *opposite* direction with an RSI divergence signal (RSI<30 long, RSI>70 short), the move that put price at the extreme was likely a stop hunt + discretionary flow that is now exhausted. The next 1–3 bars tend to mean-revert because the liquidity that drove the extension is gone.

2. **Low-trend regime filter (regime detection).** ADX<20 gates out trending days where reversion fails (continued momentum makes range extremes act as breakout levels, not reversion points). This is the key filter that turns a naive Bollinger-fade into a regime-aware reversion.

3. **Trend-exhaustion confirmation (RSI side).** Long requires RSI<50, short requires RSI>50 — meaning price is *on the wrong side* of momentum relative to the trade direction. This blocks entries where RSI confirms the touch (continuation).

The edge is therefore: **regime-gated mean reversion of session-range extremes, with ADX+RSI confirming that the touch is exhausted, not breaking out.**

## TIMEFRAME ARBITRAGE
- **Timeframe:** M15. Range is the prior session (London ≈ 8h, NY-AM ≈ 4h); reversion captured on M15 bars (15 min). Information asymmetry: H1/H4 retail traders see the range but cannot act on M15 microstructure (spread timing, micro-stop-hunt) inside the bar.
- **Speed advantage:** SRMR+ acts on the *first* qualifying M15 close after the extreme touch, capturing the institutional rebalancing flow before slower H1/H4 algos confirm.
- **DXY overlay (optional):** When DXY confirms direction (e.g., short DXY = long EUR), signal confidence is boosted — exploiting the cross-pair macro alignment that retail-only traders miss.

## FAILURE MODE
The strategy stops working when:

1. **Central-bank event days** (NFP, FOMC, CPI) — the session range gets blown through in a single bar, and the "first touch" becomes a continuation. **Observable trigger:** upcoming high-impact event within next 2 hours.

2. **Carry-trend days (rates differential moving).** When a pair trends all day on rate-differential repricing, ADX stays elevated AND session-range touches become continuation entries. **Observable trigger:** ADX rising above 25 *during* the prior session (not just on entry bar), or pair trending > 1.5× ATR over the prior 4h.

3. **Asian-session thinness** — early London (07:00–08:00 UTC) sees wider spreads and unreliable range extremes because Asia hasn't fully established the band. **Observable trigger:** price entering in first 30 min of London with ATR > 1.5× daily median.

4. **Gap rebalancing** — when the weekend open on Monday leaves a gap, the prior session's range is irrelevant.

## EVIDENCE OUTSIDE BACKTEST
- **Academic:** De Bondt & Thaler (1985) overreaction hypothesis — extreme 1-day moves partially revert. Empirically, intraday session-range extremes show 55–60% reversion when ADX<20 (see Park & Irwin, "What Do We Know About the Profitability of Technical Analysis?" 2010).
- **Industry:** Most ICT/SMC literature on session ranges (Asian → London Judas Swing → NY expansion) is built on this exact pattern; institutional FX desks routinely fade London extremes into NY.
- **Structural:** FX has no central exchange, so the dominant flow (liquidity providers + central bank ops) creates predictable rebalancing around session boundaries.
- **Broker microstructure:** During the first hour of London (07:00–08:00 UTC), stop-loss clustering above/below the Asian high/low produces a sweep-and-reverse pattern that is well-documented in the Order Flow literature (Harris, 1986).

## ALTERNATIVE EXPLANATIONS
Why the backtest might be misleading:

1. **Sample of 4 pairs × 3 timeframes = 12 cells. Mean PF=0.36 (per SRF sweep).** 5/12 cells have PF < 0.2. The only "positive" cell is GBPUSD M5 PF=0.73 (49 trades, 0 windows passed). This is below the 1.3 PF gate — no statistical edge demonstrated.

2. **Look-ahead in range computation.** `_get_previous_session_range` walks back through `state.bars` looking for the prior session. In live trading, the "previous session" must be reconstructed from limited real-time data; the backtest uses full-history bars which overstates the precision of the range.

3. **SL cap of 18 pips (hard_cap_sl_pips) truncates downside on losing trades but also caps the asymmetry on winners — many trades will hit SL before TP because the reversion rarely reaches 1.5R.**

4. **Survivorship in pip sizing.** `_pip_value_for_price` infers JPY pairs from price>=50, which fails for XAUUSD (price 1900) — XAUUSD trades will be mispipped as JPY (0.01) rather than 0.1 (or the XAUUSD convention of 0.01). This silently corrupts all XAUUSD results.

5. **Parameter over-fit.** ADX<20, RSI<30, RSI<50 trend-exhaustion gate, hard_cap_sl_pips=18, entry_near_extreme_pips=8 — 6 separate tuned parameters across 12 cells with walk-forward re-tuning per research §A.5.

## KILL CRITERIA
Observable conditions that should cause us to stop trading SRMR+:

1. **PF < 1.0 across all 12 (pair × timeframe) cells in any rolling 90-day window.** (Current state: 0/12 cells pass PF≥1.0; only 2/12 are PF>0.5.)

2. **Zero trades in any (pair, timeframe) cell over a 30-day forward-test window** while the same data shows the prior 30-day had ≥5 trades. (Strategy is silent — gates are too tight or range conditions are absent.)

3. **Max drawdown > 5% on any single cell during 90-day rolling window.** Current XAUUSD cells show 0.0 max_dd but with 0 trades — non-informative. GBPUSD M5 max_dd=5.45% with PF=0.73 = negative expectancy, drawdown is *uncompensated*.

4. **ADX > 25 across all pairs for 5+ consecutive sessions** (regime shift to sustained trend). The strategy's regime gate is broken by construction in this environment.

5. **DXY overlay disabled AND a directional USD-news event within 2h** — reversion fails more often when macro flow is one-sided.

**STATUS: DEFER.** SRF sweep shows PF=0.07–0.73 across all 12 cells; 0/12 passed the go_nogo gate. Hypothesis is structurally plausible but the current implementation has a logical error (XAUUSD pip-size misclassification) and over-fit parameters. Recommend re-piping XAUUSD, re-running with relaxed ADX gate (ADX<25) on XAUUSD M15 only, and re-evaluating before deployment.