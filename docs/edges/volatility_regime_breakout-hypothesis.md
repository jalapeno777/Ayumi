# Edge Hypothesis: Volatility Regime Breakout (VRB)

## HYPOTHESIS
**THIS STRATEGY HAS NO ARTICULABLE EDGE AS CURRENTLY IMPLEMENTED.** The volatility-regime-breakout hypothesis (low-vol regime preceding high-vol expansion with directional bias) is academically valid, but the implementation has a *logical contradiction in the strategy name itself*: it claims to detect "breakouts" but its conditions describe the *pre-breakout* snapshot — it signals on the "before" bar, not the "after" bar. Zero trades across all 9 (pair × timeframe) cells in the SRF sweep confirms this is a logic bug, not a tuning problem.

## MECHANISM (INTENDED, BUT BROKEN)
The hypothesis has two valid components:

1. **Volatility regime detection.** Compare current ATR(14) to its own trailing 50-bar distribution. If current ATR is below the 20th percentile, the market is in a low-volatility regime. This is correctly implemented (`_atr_percentile` returns the percentile of current ATR relative to trailing lookback).

2. **Volatility expansion follow-through.** Markets in low-vol regimes tend to *transition* to high-vol regimes with above-average directional persistence. This is the volatility-clustering effect (Cont 2001).

But the implementation contradicts itself:

- It requires **low ATR** (below 20th percentile of trailing distribution)
- It requires **range position < 0.50** (price in the middle of recent range)
- It requires **EMA(50) trend direction** (price above or below the trend)
- It signals *immediately* on the "low-vol snapshot" bar

**The contradiction:** After low-vol + middle-range, the trend is *flat*. The strategy is named "breakout" but its conditions describe *pre-breakout consolidation*. A breakout strategy needs (low vol BEFORE) → (high vol + directional move AFTER). This strategy looks at the "before" snapshot but signals on the "before" bar, not the "after" bar.

From research §A.3: "The logical contradiction: 'Breakout from a low-volatility regime with a confirmed trend' is essentially impossible. After low-vol, the trend is flat."

**Result:** The conditions are so restrictive (low ATR + low range position + clear trend) that almost no bar qualifies, *especially* during low-vol regimes when the trend is by definition flat. Combined with session filter (LONDON/NY_AM only), the strategy produces zero signals across all 9 cells.

## TIMEFRAME ARBITRAGE
- **Intended:** Detect vol regime on M15/H1, signal on expansion.
- **Actual:** Zero trades. No timeframe arbitrage realized.

## FAILURE MODE
The strategy fails *everywhere* because it never trades. The "failure mode" is structural, not market-condition-specific.

## EVIDENCE OUTSIDE BACKTEST
The volatility-regime hypothesis has strong academic support:
- **Cont (2001) "Empirical Properties of Asset Returns":** Volatility clustering is one of the most robust stylized facts in finance. Low-vol regimes transition to high-vol regimes.
- **Andersen & Bollerslev (1997):** FX volatility has regime-switching behavior; transition probabilities are documented.
- **Christensen & Prabhala (1998):** "The Relation Between Implied and Realized Volatility" — implied vol rises before realized vol expansion.
- **Industry:** "Volatility regime filters" are standard in CTA/managed-futures programs. They typically use *delayed* signals (look back at yesterday's vol, signal on today's bar) or *expansion* signals (vol rising, not low).

But none of these documented approaches require (low vol + middle range + clear trend) simultaneously. That's an internally contradictory condition set. The Ayumi implementation is broken.

## ALTERNATIVE EXPLANATIONS
Why the backtest shows zero trades:

1. **Logical contradiction (confirmed).** Research §A.3 names this exactly. The strategy conditions describe pre-breakout consolidation, but the name says breakout. **Smoking gun.**

2. **Range position filter is too tight.** `range_position_max=0.50` requires price to be in the *middle* of the trailing 20-bar range. On M15 with 20 bars = 5 hours, this is rarely the case at the moment when ATR is also at 20th percentile (because ATR is correlated with range width, and tight ranges put price near one extreme).

3. **Cooldown of 10 bars.** After a signal, no entry for 10 bars (~2.5 hours on M15). Combined with rarity of qualifying bars, this is mostly irrelevant — but it's also symptomatic: the strategy was tuned expecting frequent signals, which never materialized.

4. **Session filter excludes 70%+ of bars.** Only LONDON and NY_AM sessions qualify. Combined with the rarity of qualifying conditions, this filters out the few potential entries.

5. **`min_confidence=0.50` floor.** Even when a signal would generate, the confidence calculation produces values in 0.50–0.95 range — the floor is rarely binding.

6. **No actual volatility expansion signal.** The strategy has no condition for "ATR is rising" or "BBs have expanded outside KCs" or "current bar broke recent range." It only looks at the *static* snapshot. A strategy that doesn't include an expansion condition cannot detect expansion.

## KILL CRITERIA
Observable conditions that should cause us to stop trading Volatility Regime Breakout:

1. **Zero trades in any 30-day forward-test window.** (Current state: ZERO TRADES across 9 cells in walk-forward. **ALREADY TRIGGERED.**)

2. **Trades fire but PF < 1.0 over 30 trades.** (Cannot test — zero trades.)

3. **Strategy signals while ATR is rising (expansion phase) — but the strategy has no expansion gate.** This means even if it traded, it would signal too early.

4. **`_atr_percentile` returns 50.0 as default fallback** — when lookback is insufficient, percentile defaults to 50.0, which fails the `< 20.0` check. So warmup periods always produce no signals.

**STATUS: KILL.** SRF sweep: 0/9 cells traded, 0/9 passed go_nogo. The implementation is logically contradictory — it claims to be a breakout strategy but conditions describe pre-breakout consolidation. The strategy file should be marked `DEPRECATED = True` and removed from production registry.

If the vol-regime hypothesis is desired, replace with `dual_tf_squeeze_pro.py` per research §B.2, OR refactor this strategy as documented in research §A.3: "Low-vol regime detection, enter on next volatility expansion." The refactor would require: (a) detect low-vol regime (this works), (b) wait for vol expansion (BB outside KC, or ATR rising bar-over-bar), (c) enter on expansion bar with directional bias from HTF. This is a real strategy; the current code is not.