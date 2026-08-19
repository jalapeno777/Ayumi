# Pre-Mortem: volatility_squeeze

**Strategy:** Volatility Squeeze Breakout (TTM Squeeze — BB inside KC, fire on release)
**Type:** Breakout — volatility compression followed by expansion
**Pairs:** EURUSD, GBPUSD, USDJPY, AUDUSD, XAUUSD (H1, M15)
**FTMO Context:** 1-Step Standard, $100K account, 3% daily DD, 10% total DD

---

## How does this strategy LOSE?

1. **Squeeze releases in both directions — no directional edge.** The strategy fires when BBs exit KCs, using close vs. EMA(20) for direction. But a squeeze release often starts with a fakeout in one direction, reverses, then runs the other way. The first release bar triggers entry long (close > EMA), then price immediately reverses below EMA. The trade is stopped out on the fakeout, and the real move runs without us.

2. **`squeeze_release_mode = "any_release"` fires on noise.** The default config triggers on any squeeze release after just 2 bars of compression (`min_squeeze_bars=2`). Two bars of BB-inside-KC is statistical noise — not meaningful compression. The strategy generates signals on micro-squeezes that have no energy behind them, entering trades that drift sideways until the ATR stop hits.

3. **ADX gate was removed entirely.** The original ADX ≥ 15 filter was dropped because "ADX during a squeeze is structurally < 20." But ADX on the *release bar* — the actual signal bar — does carry information. Without any trend filter, the strategy enters breakouts in genuinely directionless markets where the "breakout" is just random volatility expanding, not a directional move.

4. **RSI filter is too narrow.** Long entries are blocked only when RSI ≥ 70, short entries only when RSI ≤ 30. Between 30-70 there's no RSI filtering at all. A squeeze release at RSI 65 (already overbought territory for the range) fires a long that's late to the move — the expansion already happened before the signal.

5. **XAUUSD preset has no session filter.** The XAUUSD config sets `session_filter=False`, meaning the strategy can fire during Asian session gold — a notoriously low-liquidity period where breakouts are unreliable and spreads are widest. Gold squeeze releases at 02:00 UTC are noise, not momentum.

---

## What market regime BREAKS it?

**Extended low-volatility chop with frequent micro-squeezes.** The strategy's strength is catching genuine volatility expansion after real compression. In a market that oscillates in a tight range — common in summer sessions or pre-central-bank decision weeks — BBs slip in and out of KCs every 2-3 bars. Each release triggers a trade, each trade is noise. The strategy bleeds death by a thousand cuts.

**News-driven volatility spikes that immediately reverse.** A squeeze release triggered by a headline (e.g., "Fed considering pause") creates one bar of expansion that looks like a breakout. The next bar reverses completely as the market re-prices. The strategy enters on the expansion bar and is stopped out on the reversal bar.

**Strong trend with no squeeze.** If the market is trending strongly with high ADX and BBs consistently outside KCs, the strategy never detects a squeeze — it waits for compression that never comes. It misses the best trending opportunities entirely.

---

## What data assumption might be WRONG?

1. **BB-inside-KC as a compression proxy.** The TTM Squeeze uses BB(20, 1.8-2.0) inside KC(20, 1.5-2.0). This is a specific parametric relationship — it assumes 20-bar lookback and these exact multipliers capture "compression." Different lookback periods (e.g., 10 or 50) may identify different — or no — compression regimes. The fixed lookback creates a single lens on a multi-timescale phenomenon.

2. **EMA(20) as the direction filter.** On a squeeze release, price often gaps away from EMA(20). But EMA(20) during a squeeze is flat — it has no directional information. Using close vs. flat EMA is a coin flip. The strategy would benefit from a longer EMA or a momentum oscillator for direction.

3. **Session filter assumes London/NY are always best.** The `_PREFERRED_SESSIONS` filter allows London and NY_AM only. But USDJPY often has valid squeeze breakouts during the Asian session (Tokyo open). The session filter excludes the best window for JPY pairs.

4. **ATR-based stops assume stable volatility.** SL is placed at 1.5 × ATR(14) from entry. But ATR was just compressed (that's what triggered the setup). The ATR reading on the release bar is artificially low — the stop is tighter than it should be for the post-squeeze volatility expansion that follows.

---

## Kill criteria (pre-committed)

- **Daily DD > 3%** → stop trading for the day (FTMO 1-Step hard limit)
- **Total DD > 10%** → stop trading entirely (FTMO account loss)
- **10 consecutive losses** → pause + review strategy parameters
- **Live win rate < backtest win rate - 15%** → kill (backtest assumed unrealistically)
- **Sharpe ratio < 0 (live) for 30 consecutive trading days** → kill (edge has decayed or never existed)
- **Average slippage on entry > 2 pips (FX) or $0.50 (XAUUSD)** → investigate broker conditions; squeeze releases are fast markets

---

## Position sizing discipline

- **Max risk per trade:** 0.5% of account ($500 on $100K) — conservative for FTMO 1-Step
- **Max concurrent positions:** 1 per symbol (prevents correlated EURUSD+GBPUSD+AUDUSD stacking)
- **Max daily trades:** 3 (squeeze releases should be infrequent; 3+ indicates noise regime)
- **Symbol isolation:** If XAUUSD and EURUSD both signal, trade XAUUSD only (gold squeezes are higher-quality)
- **Session cap:** No more than 2 trades in the same session (London or NY)

---

## What would make me ABANDON this?

**Live profit factor < 0.85 for 30 consecutive trading days (6 weeks).** A PF below 0.85 means the strategy is systematically losing with no sign of recovery. Squeeze breakouts should produce 1-3 trades per week per symbol — 30 days gives 15-40 trades of live sample across multiple pairs.

**5 consecutive squeeze releases that immediately reverse (within 2 bars).** This indicates the squeeze detection is identifying noise, not compression — the BB/KC relationship is too sensitive. The strategy's core premise (compression → expansion → directional move) is not playing out. This is a structural flaw requiring re-parameterization, not just bad luck.
