# Pre-Mortem: ttc_xauusd

**Strategy:** TTC XAUUSD M15 (Triangulation Trading System, Optuna-optimized)
**Type:** Multi-factor confidence scoring with swing structure
**Pair:** XAUUSD (Gold / US Dollar)
**Timeframe:** M15
**FTMO Context:** 1-Step Standard, $100K account, 3% daily DD, 10% total DD

---

## How does this strategy LOSE?

1. **Optuna overfitting to historical XAUUSD data.** The parameters were optimized on a specific historical window. XAUUSD is notoriously sensitive to macro regime — gold can trend for months in one direction, then completely change behavior on a Fed pivot. The optimized parameters (especially `mw_base_confidence: 0.45`, `negative_weight: 0.25`) may capture a pattern that existed in the training data but doesn't persist live.

2. **Monkeypatching creates silent parameter drift.** The strategy monkeypatches module-level constants in `tts_strategy.py` at import time. If any other code imports `tts_strategy` first (e.g., in a multi-strategy backtest), the patching may not take effect — or worse, parameters from one strategy bleed into another. This produces trades with wrong parameters, leading to unexpected losses.

3. **Kill zone boost is negative (`-0.15`).** The Optuna optimization found that kill zone activity *reduces* confidence for XAUUSD. This is counter-intuitive and may be an artifact of the training period. If the live market reverses this relationship (kill zones become high-probability for XAUUSD), the strategy will systematically avoid its best setups.

4. **XAUUSD volatility exceeds SL assumptions.** Gold M15 bars regularly range 30-50 pips ($3-5). If the strategy's SL is set based on Optuna's optimized ATR/structure levels, a single volatile M15 bar can blow through the stop in one tick. The confidence scoring doesn't account for tail risk — a 0.6 confidence trade with a 50-pip SL is riskier than a 0.4 confidence trade with a 15-pip SL.

5. **HTF trend penalty misfires in ranging markets.** The `htf_opposing_penalty: -0.05` penalizes signals against the higher-timeframe trend. But in ranging markets, the "HTF trend" flips frequently based on the lookback window. The penalty can suppress good signals when the market is transitioning from range to trend.

---

## What market regime BREAKS it?

**Fed decision / FOMC week.** Gold is hyper-sensitive to US monetary policy. During FOMC statement releases, rate decisions, or Fed chair press conferences, XAUUSD can move $20-50 in minutes. The M15 confidence scoring system isn't designed for this kind of discontinuous jump — signals generated before the announcement are based on stale information.

**Safe-haven flight (geopolitical crisis).** When geopolitical risk spikes (war, pandemic, financial crisis), gold gaps up violently. The strategy may try to short into the rally (mean reversion bias from the confidence model) and get stopped out repeatedly.

**Dollar index regime shift.** XAUUSD is inversely correlated with DXY. If the Dollar enters a sustained strengthening cycle (e.g., Fed hawkish pivot), gold trends down for months. The strategy's swing-based approach may generate counter-trend signals that consistently fail.

---

## What data assumption might be WRONG?

1. **Spread assumption for XAUUSD.** Gold spreads are typically 20-40 cents ($0.20-0.40, or 2-4 "pips" in gold terms). During volatility, spreads can widen to $1-2. The strategy's confidence model doesn't penalize wide-spread entries — a 0.5 confidence trade with a $1 spread has a significant breakeven hurdle.

2. **Optuna training period representativeness.** The parameters were optimized on a specific historical window. If that window was a bull market for gold (2023-2024 rally), the strategy may be long-biased. Live trading in a bear market would systematically fail.

3. **Swing lookback of 3 bars is very short.** `swing_lookback: 3` on M15 means the strategy only looks at the last 45 minutes to define swing structure. This is noisy — a single volatile bar can define a false swing point, leading to bad entries.

4. **`history_bars: 50` may be insufficient.** 50 bars of M15 = 12.5 hours. For a strategy trading gold, this is less than one full trading day. The confidence model may not have enough context to distinguish a genuine setup from noise.

---

## Kill criteria (pre-committed)

- **Daily DD > 3%** → stop trading for the day (FTMO 1-Step hard limit)
- **Total DD > 10%** → stop trading entirely (FTMO account loss)
- **10 consecutive losses** → pause + review (gold strategies can stack losses fast in trending markets)
- **Live win rate < backtest win rate - 15%** → kill (overfitting confirmed)
- **Sharpe ratio < 0 (live) for 30 consecutive trading days** → kill
- **Average adverse slippage > $0.50 per trade** → investigate execution quality, may need broker change

---

## Position sizing discipline

- **Max risk per trade:** 0.5% ($500 on $100K) — XAUUSD volatility warrants conservative sizing
- **Max concurrent positions:** 1 (gold-only strategy, no diversification benefit from multiple entries)
- **Max daily trades:** 3 (M15 strategy can generate many signals; cap prevents overtrading)
- **News blackout:** No new entries 30 minutes before/after high-impact USD news (CPI, NFP, FOMC)

---

## What would make me ABANDON this?

**Live profit factor < 1.0 for 30 consecutive trading days.** XAUUSD strategies have higher variance than FX pairs, so I need a longer window to distinguish noise from failure. 30 trading days = ~6 weeks, giving 30-90 live trades of sample. If PF is still under 1.0 after that, the Optuna parameters are overfit.

**Two separate incidents of > 2% single-trade loss.** This means the SL is not containing risk properly — either the stop is too wide, slippage is extreme, or a gap event occurred. Either way, the strategy's risk model is broken for live gold trading and needs a fundamental rethink.
