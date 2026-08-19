# Pre-Mortem: london_breakout_retest

**Strategy:** London Breakout + Retest (Asian range → London breakout → retest entry)
**Type:** Breakout — session range with retest confirmation
**Pairs:** XAUUSD M15 (primary), EURUSD M15
**FTMO Context:** 1-Step Standard, $100K account, 3% daily DD, 10% total DD

---

## How does this strategy LOSE?

1. **Breakout is real but retest never comes.** The strategy detects a London open breakout above/below the Asian range, then waits for price to retest the broken level. In strong momentum sessions (NFP week, risk-off flight), price runs 30-50 pips on XAUUSD without looking back. The 16-bar (4-hour) retest window expires, and the strategy never enters. The best moves are missed entirely.

2. **Retest is actually a reversal — price falls back through.** The strategy enters when price retests the Asian high/low and "holds" (close above for longs, below for shorts). But the retest tolerance is `1.0 × ATR` — on XAUUSD M15 where ATR is $2-3, that's a $2-3 window. Price can fall back through the Asian high by 2 ATR and still be "in tolerance." The entry is taken at a level where support has already failed, and the trade reverses immediately.

3. **Asian range is meaningless — too tight or too wide.** The `min_asian_range_pips=8.0` and `max_asian_range_pips=60.0` define acceptable range. But 8 pips on EURUSD is noise (a single bank transaction creates this). 60 pips on XAUUSD is already a trend — the "breakout" is just continuation. The range filter doesn't distinguish between meaningful consolidation and random noise.

4. **SL placement uses the full Asian range width.** Stop loss is at Asian low - 0.5 × ATR for longs (or Asian high + 0.5 × ATR for shorts). For a 40-pip Asian range on XAUUSD, the SL is 40+ pips away from entry. That's a 2-3% risk on a single trade if position sizing isn't adjusted — catastrophic for FTMO's 3% daily DD limit if even one trade hits SL.

5. **Hardcoded UTC session hours don't track DST.** `asian_start_utc=0, asian_end_utc=7, trade_start_utc=7` assumes fixed UTC offset. But London shifts to BST (+1) in summer. During summer, London opens at 06:00 UTC, not 07:00. The strategy starts looking for breakouts an hour late, and the "Asian range" includes an extra hour of London pre-market activity.

---

## What market regime BREAKS it?

**Range-bound London session with no directional follow-through.** The strategy's core assumption is that the London open brings volume and direction. On days with no clear catalyst, London just chops around the Asian range. Price "breaks out" by 3-5 pips, immediately falls back, the retest triggers, and then price continues falling through the Asian range. The strategy is entering on noise.

**Risk-off gap-and-go.** When markets gap on the London open (weekend risk events, Sunday night gaps), the gap counts as the "breakout." The retest comes as price partially fills the gap — but the gap was structural, not session-driven. The trade enters at the mid-point of gap fill and gets stopped out when the trend resumes.

**XAUUSD during gold-specific catalysts.** Gold has unique drivers (real yields, safe-haven flows, central bank buying). A London breakout on gold triggered by a European session news event (e.g., ECB surprise) is fundamentally different from a session-range breakout. The strategy treats all London breakouts the same, but gold-specific catalysts produce different price behavior.

---

## What data assumption might be WRONG?

1. **Asian range as a consolidation proxy.** The strategy assumes the Asian session is "quiet consolidation." But Asian session for XAUUSD includes Tokyo commodity trading and can be highly volatile — especially during BOJ announcements or Asian geopolitical events. The Asian "range" may already contain the day's move, leaving London with nothing to break out from.

2. **Breakout buffer of 3.0 pips is too small for gold.** `buffer_pips=3.0` is designed for EURUSD. On XAUUSD where 1 pip = $0.01, a 3-pip buffer is $0.03 — well within the bid-ask spread. The breakout detection fires on noise that looks like a 3-pip move but is just spread.

3. **Retest tolerance scaled by ATR, not by range size.** `retest_tolerance_atr=1.0` means the retest window scales with current volatility, not with the size of the Asian range. A 50-pip range with low ATR has a tight retest tolerance; a 10-pip range with high ATR has a loose one. The tolerance should scale with range geometry.

4. **Single-day Asian range assumption.** The strategy computes Asian range for `target_day` using the day-of-month. On Mondays after weekend gaps, the Asian range doesn't reflect the prior week's context. On Fridays before weekend risk, the Asian range may be artificially compressed.

---

## Kill criteria (pre-committed)

- **Daily DD > 3%** → stop trading for the day (FTMO 1-Step hard limit)
- **Total DD > 10%** → stop trading entirely (FTMO account loss)
- **10 consecutive losses** → pause + review (session breakout strategies should have 45-55% win rate)
- **Live win rate < backtest win rate - 15%** → kill (backtest assumed unrealistically)
- **Sharpe ratio < 0 (live) for 30 consecutive trading days** → kill
- **DST transition weeks (March, November)** → pause for 2 weeks; session timing is unreliable
- **SL distance > 1.5% of account** on any single trade → reduce position size immediately

---

## Position sizing discipline

- **Max risk per trade:** 0.5% of account ($500 on $100K) — must adjust for wide Asian ranges
- **Range-adjusted sizing:** If Asian range > 40 pips (XAUUSD) or > 25 pips (EURUSD), reduce risk to 0.3% — wider stops mean proportionally smaller size
- **Max concurrent positions:** 1 (never stack London breakout on XAUUSD + EURUSD simultaneously — they're correlated during risk events)
- **Max daily trades:** 1 (by design — only one breakout+retest per day)
- **Day-of-week filter:** Avoid Mondays (weekend gap noise) and Fridays (position-closing distortion)

---

## What would make me ABANDON this?

**Live win rate < 35% after 40 trades with PF < 0.8.** London breakout strategies live and die by win rate — the TP structure (1R/2R/3R) means average win is ~1.5R. At 35% win rate, expected value per trade is 0.35 × 1.5R - 0.65 × 1R = -0.125R. That's a slow bleed with no recovery path.

**3 consecutive weeks where the retest window expires without entry on valid breakouts.** This indicates the market structure has shifted — London breakouts are running without retests (gap-and-go regime). The strategy's entry mechanism is obsolete for current conditions. Re-evaluate the retest premise entirely.

**Single trade loses > 2% of account (67% of daily DD limit).** With proper sizing this shouldn't happen. If it does, either the Asian range was miscomputed, the SL was hit by a gap (not priced in the model), or position sizing has a bug. Immediate halt and investigation required.
