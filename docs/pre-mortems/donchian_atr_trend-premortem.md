# Pre-Mortem: donchian_atr_trend

**Strategy:** Donchian + ATR Trailing Trend
**Type:** Trend-following breakout with adaptive ATR stop
**Pairs:** XAUUSD, GBPUSD (M15, H1)
**FTMO Context:** 1-Step Standard, $100K account, 3% daily DD, 10% total DD

---

## How does this strategy LOSE?

1. **Whipsaw in ranging markets.** Donchian breakouts are classic trend-following — they excel in sustained trends and bleed steadily in ranges. The N-period high/low breakout fires false signals repeatedly when price oscillates within a narrow band. Each false breakout triggers entry + ATR stop exit = one full risk unit lost. In a tight range, 5-8 consecutive whipsaws can consume the entire daily DD budget.

2. **ATR stop is too tight in high-volatility breakouts.** The ATR trailing stop adapts to volatility, but during explosive breakouts (especially XAUUSD), realized volatility spikes *after* entry. The stop calculated at entry was based on pre-breakout ATR — which is lower. The stop gets hit on the first pullback before the trend resumes, even though the breakout direction was correct.

3. **ADX filter doesn't prevent choppy entries.** ADX > threshold is supposed to filter for trend strength, but ADX lags. By the time ADX confirms a trend, the initial breakout momentum may be exhausted. The strategy enters at the end of the move, catches the retracement, and stops out.

4. **Gap risk on session opens.** Donchian levels from the previous session create breakouts at session open. Weekend gaps (for H1) or session-open gaps (for M15) trigger entries at prices far from the breakout level. The ATR stop calculated on pre-gap data is meaningless — the position is instantly underwater.

5. **Trailing stop exits too early on slow trends.** ATR trailing stops are designed for strong trends. In a slow, grinding trend (common in EURUSD), price pulls back within ATR range frequently. The trailing stop gets hit on each pullback, locking in a small profit but missing the bulk of the trend move. Over time, the sum of small wins doesn't cover the false breakout losses.

---

## What market regime BREAKS it?

**Extended ranging market (low ADX for days/weeks).** Donchian systems have a known structural weakness: they require trends to pay for all the false breakouts. In a 2-3 week ranging market, the strategy can generate 15-20 false signals, each losing a full risk unit. This is the classic "death by a thousand cuts" for trend-followers.

**V-shaped reversals after breakout.** The strategy enters on a Donchian breakout, expecting continuation. A V-shaped reversal (price breaks out, then immediately reverses) is the worst case — entry is at the exact top/bottom of the move. The ATR stop gets hit quickly with maximum adverse excursion.

**Central bank intervention in XAUUSD.** Gold is subject to central bank buying/selling that creates artificial trends or reversals. A Donchian breakout triggered by central bank intervention may be a one-time event — the "trend" doesn't persist because the intervention is finite.

---

## What data assumption might be WRONG?

1. **Donchian period suitability.** The N-period Donchian channel assumes that N bars capture the relevant price range. Too short (N=10): too many false breakouts. Too long (N=55): entries are too late, catching only the tail of moves. The optimal N varies by market regime — a fixed N is always wrong some of the time.

2. **ATR period alignment.** ATR(14) is standard, but it measures recent volatility. After a volatility cluster (high ATR), the trailing stop is wide — the strategy takes on more risk than intended. After a quiet period (low ATR), the stop is tight — gets stopped on noise.

3. **Fill model on breakouts.** Backtests assume the breakout bar's close is achievable as an entry price. Live breakouts often gap through the Donchian level — by the time the signal is generated and the order sent, price has moved 5-15 pips beyond the level. This slippage is especially severe on XAUUSD breakouts.

4. **Stop-loss execution assumption.** The ATR trailing stop assumes execution at the stop level. In fast markets, stop orders become market orders and fill at the next available price — which can be significantly worse. A 20-pip stop can become a 35-pip loss in seconds.

---

## Kill criteria (pre-committed)

- **Daily DD > 3%** → stop trading for the day (FTMO 1-Step hard limit)
- **Total DD > 10%** → stop trading entirely (FTMO account loss)
- **10 consecutive losses** → pause + review (trend-followers can stack losses in ranges; 10 is the threshold where the regime is clearly adverse)
- **Live win rate < backtest win rate - 15%** → kill (win rate is already low for trend-followers; a further 15% drop means the edge is gone)
- **Sharpe ratio < 0 (live) for 30 consecutive trading days** → kill
- **6 consecutive months with negative expectancy** → kill (giving the strategy a full half-year to catch a trend)

---

## Position sizing discipline

- **Max risk per trade:** 0.5% ($500 on $100K) — trend-followers have low win rates; each loss must be small
- **Max concurrent positions:** 2 (XAUUSD + GBPUSD can diversify if trends are uncorrelated)
- **Max correlation:** If both pairs trend in the same direction (risk-on/off), count as 1 position for sizing
- **Max daily trades:** 3 (prevents overtrading during choppy sessions with multiple false breakouts)

---

## What would make me ABANDON this?

**Live profit factor < 0.8 for 42 consecutive trading days (2 months).** Trend-followers need time — their win rate is often 35-45% but the payoff ratio compensates. But if PF is under 0.8 after 42 days (~30-60 trades), the losses are mounting too fast for the winners to compensate. The strategy is catching false breakouts without catching the trends that should pay for them.

**Any single month where max consecutive losses > 12.** The system should be designed to survive 8-10 consecutive losses (standard for trend-followers). If it hits 12+, either the regime is permanently adverse (structurally ranging market) or the parameters are wrong. Either way, a fundamental review is needed before continuing.
