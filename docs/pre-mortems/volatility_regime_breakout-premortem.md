# Pre-Mortem: volatility_regime_breakout

**Strategy:** Volatility Regime Breakout (low-vol setup → breakout trigger with vol expansion)
**Type:** Breakout — regime detection with two-phase setup/trigger architecture
**Pairs:** EURUSD, GBPUSD, USDJPY, AUDUSD, XAUUSD (M15, H1)
**FTMO Context:** 1-Step Standard, $100K account, 3% daily DD, 10% total DD

---

## How does this strategy LOSE?

1. **Setup phase arms in low-vol, but breakout never comes within the window.** The strategy detects low ATR percentile (< 30th) and arms a 30-bar setup window (`setup_max_bars=30`). On M15, that's 7.5 hours. If the market stays in low-vol compression longer than 30 bars — common in summer sessions or pre-central-bank decision days — the setup expires without firing. Then volatility expands bar 31, and the strategy misses it entirely.

2. **Breakout fires in wrong direction — neutral trend allows both.** The trend EMA(20) gate allows entries in the trend direction OR when trend is neutral (`trend == 0`). During the low-vol setup phase, the EMA is structurally flat (low vol = no trend). So when the breakout comes, trend is almost always neutral, and the strategy can enter in either direction. A genuine breakout up triggers a long, but if the breakout was actually a liquidity sweep, the strategy is now positioned in the wrong direction.

3. **Vol expansion ratio of 1.5× is too strict for H1, too loose for M5.** The `vol_expansion_ratio=1.5` compares single-bar true range. On M15 XAUUSD, ~20% of bars pass this threshold (per code comments). On H1 EURUSD, far fewer bars pass — the strategy rarely triggers on higher timeframes. The same threshold serves two fundamentally different volatility regimes.

4. **ATR percentile lookback (50 bars) is too short for regime detection.** `_atr_percentile` compares current ATR against the prior 50 bars. On M15, that's 12.5 hours — less than one trading day. "Low volatility regime" should be defined over days or weeks, not hours. A quiet Asian session looks like a low-vol regime, but it's just time-of-day, not a structural compression that precedes expansion.

5. **Hard cap on SL (25 pips) clips exits on gold.** `hard_cap_sl_pips=25.0` with `atr_sl_multiplier=1.0` means the effective SL is min(ATR, 25 pips). On XAUUSD where ATR can be $3-5 (300-500 "pips" at $0.01/pip), the hard cap dominates and SL is always 25 pips — far too tight for gold's normal range. The trade gets stopped out on routine volatility, not on actual signal failure.

---

## What market regime BREAKS it?

**Sustained low-volatility grind with no breakout.** The strategy arms on low ATR percentile but needs a breakout to trigger. In prolonged low-volatility regimes (summer 2024 EURUSD chop, 50-pip daily ranges for weeks), the setup arms repeatedly but breakouts are small and false. Each false breakout hits the SL, and the strategy bleeds slowly.

**High-volatility regime with no setup phase.** When ATR is above the 30th percentile persistently (risk-off crisis, major news cycle), the setup phase never triggers. The strategy sits idle during the most profitable breakout conditions — high vol with clear direction — because it can't detect a "low-vol setup" in a high-vol environment.

**Mean-reverting chop after news.** The strategy arms on low-vol setup, then a news event creates a volatility spike that triggers the breakout. But the spike immediately reverts (typical post-news behavior). The strategy enters on the expansion, price reverses, SL hit. The setup was correct (low vol → expansion), but the directional trade is wrong.

---

## What data assumption might be WRONG?

1. **ATR percentile as a regime classifier.** Percentile ranking assumes the distribution of ATR values is stable. But ATR distributions shift across sessions (Asian vs. London), days of week, and seasons. A 30th percentile ATR on a quiet Wednesday is different from a 30th percentile on NFP Friday. The classifier conflates calendar-driven ATR variation with regime-driven variation.

2. **Range position (20-bar) as mean-reversion risk.** `range_position_max=0.70` requires price to be in the middle 70% of its 20-bar range. But after a low-vol setup phase, price is almost always near the middle of its range (that's what low vol means). This filter rarely actually rejects anything — it's a tautology.

3. **Breakout period (10 bars) for high/low detection.** The breakout uses a 10-bar lookback for recent high/low. On M15, that's 2.5 hours of price action. A 10-bar high on M15 is easily exceeded by a single volatile bar — it doesn't represent meaningful resistance/support. Breakouts from 10-bar highs are noise-level events.

4. **Pip value inference from price level.** When `symbol` is not set, the strategy infers pip size from `latest.close >= 50` (XAUUSD heuristic). This breaks for any symbol priced between 5 and 50 (e.g., USDJPY at ~150, GBPJPY at ~190). The strategy will compute incorrect pip values and SL distances.

---

## Kill criteria (pre-committed)

- **Daily DD > 3%** → stop trading for the day (FTMO 1-Step hard limit)
- **Total DD > 10%** → stop trading entirely (FTMO account loss)
- **10 consecutive losses** → pause + review parameters
- **Live win rate < backtest win rate - 15%** → kill (backtest assumed unrealistically)
- **Sharpe ratio < 0 (live) for 30 consecutive trading days** → kill
- **Setup expiry rate > 70%** (setup arms but never fires) over 50 setups → strategy's detection is out of sync with real breakouts; re-parameterize

---

## Position sizing discipline

- **Max risk per trade:** 0.5% of account ($500 on $100K) — conservative for FTMO 1-Step
- **Max concurrent positions:** 1 per symbol, max 2 total (only if uncorrelated — e.g., EURUSD + XAUUSD)
- **Max daily trades:** 4 (multiple setups may arm across symbols; 4+ indicates over-sensitivity)
- **Symbol-specific pip config:** Always set `VRBConfig.symbol` explicitly — never rely on price-level inference

---

## What would make me ABANDON this?

**Live profit factor < 0.80 for 40 consecutive trading days (8 weeks).** VRB is a two-phase strategy — setup + trigger. If the setup detection is wrong (arming in noise, not real compression), the PF will be consistently below 1.0 with no recovery path from parameter tuning. 8 weeks gives 20-50 trades of sample across multiple symbols and regimes.

**Win rate < 30% after 50 trades.** The strategy's R:R structure (TP1 at 1.5R, TP2 at 2R, TP3 at 3R) means it needs a ~30% win rate just to break even. Below 30% after 50 trades, the breakout detection is fundamentally wrong — the strategy is entering on noise, not real regime shifts.

**3 consecutive trades where the vol_expansion_ratio gate blocks entry on a clear breakout.** This indicates the 1.5× single-bar threshold is miscalibrated for current conditions. The strategy's setup detection works (it armed correctly), but the trigger is too strict. Needs immediate re-parameterization before continuing.
