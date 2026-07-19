# Pre-Mortem: srmr_plus

**Strategy:** Session Range Mean Reversion Plus (SRMR+)
**Type:** Mean reversion — session extreme exhaustion
**Pairs:** EURUSD, GBPUSD (M15)
**FTMO Context:** 1-Step Standard, $100K account, 3% daily DD, 10% total DD

---

## How does this strategy LOSE?

1. **Trend persists through the session range.** SRMR+ enters when price touches the session extreme with low ADX (≤20). But a slow-grind trend can keep ADX under 20 while pushing further against the entry. The strategy fades the move, adds to the loss, and the session range keeps expanding. By the time ADX exceeds 20, the trade is already deep underwater.

2. **RSI oversold in a strong downtrend.** RSI < 30 is the entry trigger, but in a momentum-driven selloff, RSI can stay pinned below 30 for extended periods. Each bar that looks "oversold" is just more selling pressure. The mean reversion never comes — the pair closes the session 50-80 pips beyond the entry.

3. **Session range is too quiet.** The `session_range_min_pips` was lowered from 15.0 to 10.0 to allow quieter sessions. Quiet sessions have shallow ranges — the "extreme" is only 8 pips away (the `entry_near_extreme_pips` threshold). The trade enters at a meaningless level, scalps a tiny move or gets stopped out on noise.

4. **DXY overlay gives false confidence.** If `dxy_overlay=True`, the Dollar Index regime adjusts confidence. But DXY is a blunt instrument — a strong DXY doesn't guarantee EURUSD mean reversion. The overlay can push confidence above threshold for a trade that has no real edge.

5. **Multiple correlated entries stack up.** EURUSD and GBPUSD are highly correlated (~0.7-0.8). If SRMR+ fires on both in the same session, the effective risk is doubled. Without correlation limits in the strategy itself, a single adverse market move hits both positions.

---

## What market regime BREAKS it?

**Sustained trending regime with low ADX.** SRMR+ relies on ADX ≤ 20 to identify range-bound conditions. But ADX is a lagging indicator — it can stay low during the early phase of a trend before surging. By the time ADX confirms the trend, the mean reversion trade is underwater.

**High-impact news during the London/NY session.** NFP, CPI, or central bank announcements create violent directional moves that look like session extremes. SRMR+ enters fading the spike, but the move is fundamental, not technical. The trade gets stopped out within minutes.

**Gold/commodity-driven risk-off correlation.** When risk sentiment shifts sharply (flight to safety), EURUSD and GBPUSD can decouple from their normal session range behavior. The DXY surges, pairs plunge, and mean reversion signals are noise.

---

## What data assumption might be WRONG?

1. **Spread assumption.** The strategy assumes tight spreads (~1-2 pips on EURUSD). During volatile sessions or news events, spreads can widen to 5-10 pips. The `hard_cap_sl_pips` of 18.0 doesn't account for spread widening — effective risk is higher than modeled.

2. **Tick aggregation.** Backtests use M15 bars which aggregate ticks. The `entry_near_extreme_pips` threshold of 8.0 pips assumes the M15 high/low is close to the actual tick-level extreme. In fast markets, the M15 bar can miss the true extreme by several pips.

3. **Fill model.** Backtests assume instant fills at the signal price. Live entries during volatile sessions experience slippage — especially when entering near extremes where liquidity is thin. A 2-3 pip slippage on an 18-pip SL is a 11-17% increase in effective risk.

4. **Session range definition.** The strategy uses London/NY session hours. But session boundaries shift with DST changes. A hardcoded session range that doesn't track actual DST transitions will misidentify extremes during the transition periods.

---

## Kill criteria (pre-committed)

- **Daily DD > 3%** → stop trading for the day (FTMO 1-Step hard limit)
- **Total DD > 10%** → stop trading entirely (FTMO account loss)
- **10 consecutive losses** → pause + review strategy parameters
- **Live win rate < backtest win rate - 15%** → kill (backtest assumed unrealistically)
- **Sharpe ratio < 0 (live) for 30 consecutive trading days** → kill (edge has decayed or never existed)
- **Average spread on entry > 3 pips (EURUSD)** → investigate broker conditions, may need to pause

---

## Position sizing discipline

- **Max risk per trade:** 0.5% of account ($500 on $100K) — conservative for FTMO 1-Step
- **Max concurrent positions:** 1 per session (prevents correlated EURUSD+GBPUSD stacking)
- **Max daily trades:** 3 (session range extreme entries are limited by strategy design)
- **Correlation rule:** If EURUSD and GBPUSD both signal, pick the higher-confidence one only

---

## What would make me ABANDON this?

**Live profit factor < 0.9 for 21 consecutive trading days (1 calendar month).** A PF below 0.9 means the strategy is bleeding net capital with no sign of recovery. One month is enough to distinguish bad luck from a broken edge — SRMR+ trades 1-3 times per day, so 21 days gives 20-60 trades of live sample.

**A single session where the strategy loses > 2.5% (83% of daily DD limit).** This indicates a catastrophic failure mode — likely a news event or regime shift that the strategy can't handle. Pause immediately and investigate before resuming.
