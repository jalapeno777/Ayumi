# Pre-Mortem: bb_rsi_reversion

**Strategy:** Bollinger Band + RSI Mean Reversion
**Type:** Mean reversion — BB extreme + RSI oversold/overbought fade
**Pairs:** EURUSD, GBPUSD, USDJPY, AUDUSD (H1, M15)
**FTMO Context:** 1-Step Standard, $100K account, 3% daily DD, 10% total DD

---

> **⚠️ DEPRECATED STRATEGY.** Per research §A.6 (strategy-optimization-research.md), this strategy has PF < 0.3 across all symbols/timeframes. It is kept for reference but should not be registered in new sweeps. Replacement: Dual-timeframe Squeeze Pro (`dual_tf_squeeze_pro.py`). This pre-mortem documents WHY it fails, which is critical context for evaluating the replacement.

---

## How does this strategy LOSE?

1. **Enters against strong trends — RSI oversold in a trend is continuation, not reversal.** The core flaw: RSI < 30 in a downtrend doesn't mean "oversold and due for a bounce." It means sellers are in control and pushing hard. The strategy enters long when price hits the lower BB and RSI < 30, but the "oversold" condition persists for extended periods in trending markets. The trade enters, the trend continues, and the BB lower band keeps expanding downward — the trade is underwater immediately.

2. **Confidence formula is inverted for mean reversion.** The code assigns higher confidence when RSI distance is moderate (5-15 points beyond threshold). But moderate RSI distance means the move is *developing* — it's not extreme enough to be a true exhaustion signal. The confidence peaks exactly where the mean-reversion edge is weakest (mid-range RSI extension) and penalizes the true extremes (RSI < 20) where mean reversion actually works.

3. **`require_low_volatility` filter excludes the conditions where mean reversion works.** The filter requires current ATR < ATR SMA (low volatility). But mean reversion works best *after* a volatility spike — the post-spike reversion is where the edge lives. By requiring low volatility, the strategy enters during quiet periods when BB touches are routine (not exhaustion signals) and misses the high-conviction post-spike reversions.

4. **TP at BB middle is too tight — win/loss asymmetry can't exceed 0.5.** TP1 is at 1.0R and TP2 at 1.5R. But the BB middle band is typically 10-15 pips from entry on EURUSD H1. If the SL is 1.5 × ATR (~22 pips), the actual R:R is 0.45-0.68R — less than 1:1. Even with a 55% win rate, the system loses money because losses are 1.5× larger than wins.

5. **ADX filter (25 max) is reasonable but not sufficient.** The strategy blocks entries when ADX > 25. But ADX is a lagging indicator — it can be 20 when the signal fires and spike to 35 two bars later as the trend accelerates. The filter checks ADX at entry time but doesn't protect against post-entry trend development.

---

## What market regime BREAKS it?

**Strong directional trend with periodic pullbacks.** This is the worst-case scenario. The trend creates BB touches and RSI extremes that look like mean-reversion setups. The strategy enters fading the trend. Price pulls back slightly (giving false hope), then resumes the trend. Each entry is stopped out. The strategy is structurally short gamma — it fights the dominant force in the market.

**Low-volatility range-bound market.** Paradoxically, the strategy's `require_low_volatility` filter funnels it into this regime. In a tight range, BB bands are narrow, so price touches them frequently. RSI oscillates between 35-65. The strategy enters on every BB touch, but the mean reversion target (BB middle) is only 5-8 pips away. Wins are tiny, losses (when range breaks) are full-size. Death by asymmetry.

**News-driven spike and genuine reversal.** The one scenario where mean reversion *should* work — a news spike that reverts — is filtered out by `require_low_volatility`. The post-spike environment has elevated ATR (above SMA), so the volatility filter blocks the entry. The strategy misses its highest-conviction setup.

---

## What data assumption might be WRONG?

1. **BB(20, 2.0) captures statistically significant extremes.** Standard BB assumes normal distribution of returns. FX returns have fat tails — a 2-standard-deviation move is not a 95th percentile event. It happens more frequently than the strategy assumes, especially during news events. The "extreme" that triggers entry is not extreme enough.

2. **RSI thresholds (30/70) are universal across pairs and timeframes.** RSI behavior differs across pairs (USDJPY trends differently than EURUSD) and timeframes (M5 RSI is noisier than H1). Fixed 30/70 thresholds may be too loose for some pairs (generating too many signals) and too tight for others (generating too few).

3. **BB width as a volatility proxy without checking if it's expanding.** The strategy checks if price touches the BB extreme, but doesn't check if BBs are expanding (widening) or contracting (narrowing). Entering when BBs are expanding means the extreme is moving away from the mean — the "target" is a moving finish line.

4. **Backtest fills assume entry at bar close.** The strategy evaluates on bar close and assumes entry at that price. But BB touches often happen intra-bar — by the close, price has already bounced off the BB. The signal fires at a price the market visited and rejected, not at a price available for entry.

---

## Kill criteria (pre-committed)

- **Daily DD > 3%** → stop trading for the day (FTMO 1-Step hard limit)
- **Total DD > 10%** → stop trading entirely (FTMO account loss)
- **5 consecutive losses** → pause immediately (mean reversion should have higher win rate; 5 straight losses suggests trend regime)
- **Live win rate < backtest win rate - 10%** → kill (tighter threshold than other strategies because PF is already low)
- **Sharpe ratio < 0 (live) for 21 consecutive trading days** → kill
- **Any single trade loses > 1.0% of account** → position sizing error; halt immediately

> **Note:** Given this strategy is deprecated (PF < 0.3 in backtest), the realistic kill criterion is: **do not deploy live.** The pre-mortem exists to document the failure modes for reference when evaluating the replacement (Dual-timeframe Squeeze Pro).

---

## Position sizing discipline

- **Max risk per trade:** 0.3% of account ($300 on $100K) — reduced from standard 0.5% due to known PF issues
- **Max concurrent positions:** 1 (mean reversion signals on correlated pairs like EURUSD+GBPUSD are not independent)
- **Max daily trades:** 2 (more than 2 BB touches per day indicates noise regime, not selective entries)
- **Never deploy without the ADX filter active** — ADX > 25 rejection is the only thing preventing full trend-fade destruction

---

## What would make me ABANDON this?

**Already abandoned.** Per research §A.6, this strategy has PF < 0.3 across all symbols/timeframes. The root causes are structural (inverted confidence, tight TP, counter-trend bias) not parametric. No parameter adjustment fixes these — the strategy's core logic is misaligned with how mean reversion actually works in FX markets.

**If reactivated for research purposes:** Live PF < 0.5 after 20 trades → immediate halt. The strategy is already known to be broken; any live test is purely confirmatory. 20 trades is sufficient to confirm the backtest finding.

**Replacement: Dual-timeframe Squeeze Pro** addresses the core flaws:
- Two-stage filter (H1 context + M15 entry) prevents counter-trend entries
- ADX gate on H1 ensures trend alignment
- Squeeze detection identifies compression → expansion (not fading extremes)
- Wider TP structure (1R/2R/3R) with proper R:R geometry
