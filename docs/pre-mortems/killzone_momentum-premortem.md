# Pre-Mortem: killzone_momentum

**Strategy:** Killzone Momentum (ICT/SMC-based breakout during killzone sessions)
**Type:** Session-based momentum breakout with retest confirmation
**Pairs:** EURUSD, GBPUSD (H1), XAUUSD (M5)
**FTMO Context:** 1-Step Standard, $100K account, 3% daily DD, 10% total DD

---

## How does this strategy LOSE?

1. **Killzone definition is static or DST-misaligned.** ICT killzones are specific time windows (e.g., London Killzone 02:00-05:00 EST, NY Killzone 07:00-10:00 EST). If the strategy uses hardcoded session hours that don't adjust for DST transitions, entries during the transition weeks (March, November) fire at the wrong time — either too early (before the real killzone) or too late (after the move has happened).

2. **Breakout is a liquidity sweep, not a real move.** ICT/SMC theory warns about "liquidity sweeps" — price breaks out of the killzone range to grab stop orders, then reverses sharply. The strategy's breakout detection (ATR multiplier + breakout lookback) can't distinguish a genuine momentum breakout from a liquidity sweep. The entry is at the sweep extreme, and the reversal stops it out within minutes.

3. **Retest tolerance is too wide (`1.0 × ATR`).** After a breakout, the strategy waits for price to retest the breakout level within `retest_tolerance_atr` (1.0 ATR). For XAUUSD M5 where ATR can be $2-3, this means retest is valid up to $3 away from the breakout — that's a huge window. The "retest" might just be price drifting back through the level, not a genuine support/resistance flip.

4. **ADX threshold is low (15.0).** Lowered from 20.0 to 15.0 to allow more signals. ADX 15 is barely above random — it barely distinguishes trending from ranging conditions. The filter is almost useless, letting in noise trades that look like momentum but have no directional conviction.

5. **Multiple TP levels spread risk thin.** TP1 at 1.0 RR, TP2 at 2.0 RR, TP3 at 3.0 RR. If the strategy scales out (1/3 at each TP), then a trade that hits TP1 and reverses captures only 0.33 RR. After losses (1.0+ RR each), a 33% win rate at 0.33 average win is a losing system.

---

## What market regime BREAKS it?

**Low-volume Asian session bleed.** Killzone momentum depends on volume-driven breakouts. During the Asian session (Tokyo/Sydney), volume is typically 30-40% of London/NY. Breakouts during Asian hours are often false — price lacks the order flow to sustain the move. If the strategy's killzone includes Asian hours, it generates low-quality signals.

**Choppy killzone with no directional bias.** ICT killzones work best when there's a clear narrative (e.g., risk-off, dollar strengthening). On days with no clear driver, the killzone is just noise — price bounces around without conviction. The ATR breakout multiplier fires on a volatility spike that has no fundamental backing.

**Post-news drift.** After a major news event (NFP, CPI), price often drifts sideways in a tight range for 2-4 hours. The killzone momentum strategy may interpret this drift as a breakout when price edges above the range, but there's no momentum behind it. The trade stalls and reverses.

---

## What data assumption might be WRONG?

1. **Killzone time windows are universally effective.** ICT theory claims specific time windows have higher probability. This is empirically debatable — the "killzone" effect may be an artifact of London/NY overlap volume, not a magical time window. If market structure changes (e.g., more 24-hour trading, algorithmic market-making), the killzone effect may weaken.

2. **Session range minimum (8 pips FX, 25 pips XAUUSD).** The minimum session range filters out quiet sessions. But 8 pips is very low for H1 EURUSD — a single bank transaction can create an 8-pip range. The filter doesn't ensure meaningful session activity, just any activity.

3. **ATR breakout multiplier (0.3).** This means price needs to move 0.3 × ATR beyond the session range to trigger a breakout. For EURUSD H1 where ATR is ~15 pips, that's only 4.5 pips — well within bid-ask spread + slippage. The breakout threshold is too sensitive, generating false signals.

4. **ATR SL multiplier (1.5).** The stop is placed 1.5 × ATR from entry. For XAUUSD M5 with ATR of $2, that's a $3 stop. Gold can move $3 in a single M5 bar — the stop is within one bar's range, making it almost guaranteed to get hit on any volatile bar.

---

## Kill criteria (pre-committed)

- **Daily DD > 3%** → stop trading for the day (FTMO 1-Step hard limit)
- **Total DD > 10%** → stop trading entirely (FTMO account loss)
- **10 consecutive losses** → pause + review (ICT/SMC strategies should have ~40-50% win rate; 10 straight losses indicates a structural problem)
- **Live win rate < backtest win rate - 15%** → kill (ICT strategies are win-rate dependent — they don't have the trend-follower's high payoff ratio to compensate)
- **Sharpe ratio < 0 (live) for 30 consecutive trading days** → kill
- **Killzone timing DST drift detected** → immediate pause during DST transition weeks (March/November) until session hours verified

---

## Position sizing discipline

- **Max risk per trade:** 0.5% ($500 on $100K) — standard for FTMO
- **Max concurrent positions:** 1 per session killzone (no stacking London + NY killzone entries on the same pair)
- **Max daily trades:** 5 (killzone windows are limited; cap prevents revenge trading after losses)
- **Scaling:** Consider full position with single TP rather than scaling out — ICT setups have binary outcomes (works or fails), not graduated success

---

## What would make me ABANDON this?

**Live win rate < 35% after 50 trades with PF < 1.0.** ICT/SMC strategies live and die by win rate — they're scalping momentum, not running trends. If the win rate is below 35% after 50 trades (about 2-3 months), the killzone premise doesn't hold for these pairs live. Unlike trend-followers, there's no structural reason to expect a sudden regime change to fix it.

**3 consecutive sessions where the "breakout" immediately reverses (liquidity sweep pattern).** This indicates the strategy is trading into institutional liquidity grabs, not genuine momentum. The ICT framework explicitly warns about this — if the strategy can't detect sweeps, it's fundamentally flawed and needs rework, not just parameter tuning.
