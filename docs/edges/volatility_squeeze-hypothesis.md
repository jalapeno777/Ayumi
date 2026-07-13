# Edge Hypothesis: Volatility Squeeze Breakout

## HYPOTHESIS
**THIS STRATEGY HAS NO ARTICULABLE EDGE AS CURRENTLY IMPLEMENTED.** The volatility-squeeze hypothesis (Bollinger Bands contracting inside Keltner Channels predicts an explosive breakout) is academically valid, but the implementation has a logical contradiction that prevents it from ever trading: it requires `ADX ≥ 20` *during* the squeeze — and ADX during a squeeze is structurally *below* 20 (that's the definition of a squeeze). Zero trades across all 9 (pair × timeframe) cells in the SRF sweep confirms this is not a tuning problem; it's a logic bug.

## MECHANISM (INTENDED, BUT BROKEN)
The hypothesis is the well-known TTM Squeeze (John Carter, "Mastering the Trade," 2005):

1. **Volatility regime contraction.** Bollinger Band width < Keltner Channel width indicates volatility has compressed below its 14-period ATR baseline. This is the "calm before the storm" pattern.

2. **Volatility expansion signal.** When BBs re-expand outside KCs (squeeze release), the breakout is high-probability directional. Academic basis: volatility clustering (Cont 2001, "Empirical Properties of Asset Returns") — low-volatility regimes are followed by high-volatility regimes with above-average directional persistence.

3. **BB-inside-KC squeeze detection.** `bb_upper <= kc_upper AND bb_lower >= kc_lower`. Correct.

4. **Min squeeze bars (2–3) before entry.** Filters noise. Correct.

5. **ADX ≥ 20 required.** **THIS IS THE BUG.** During a squeeze, ADX is structurally low (5–15). The strategy's `_detect_squeeze_duration` requires ADX ≥ 20 to fire — but the squeeze is *active* precisely because volatility (and thus ADX) is low.

**Smoking gun from research §A.2:** "ADX on a squeeze regime is *always* low (that's the definition of a squeeze) — `adx >= 20` requires a strong trend to be active, which contradicts the squeeze condition."

## TIMEFRAME ARBITRAGE
- **Intended:** Squeeze detection works on any timeframe; release signal captures volatility expansion on M15/H1.
- **Actual:** Zero trades. No timeframe arbitrage realized.

## FAILURE MODE
The strategy fails *everywhere* because it never trades. The "failure mode" is not market-condition-specific — it's a structural logic contradiction.

## EVIDENCE OUTSIDE BACKTEST
The TTM Squeeze hypothesis is documented in:
- **John Carter, "Mastering the Trade" (2005):** Original formulation. Carter does NOT require ADX ≥ 20 during the squeeze — he fires on the *first* bar where BBs are outside KCs.
- **Market microstructure literature:** Cont (2001) "Empirical Properties of Asset Returns" — volatility clustering is robustly documented. The squeeze-release pattern is one expression of it.
- **Industry:** Many retail platforms include TTM Squeeze indicators (Thinkorswim, TradingView). The hypothesis is widely used.

But none of the documented implementations require ADX ≥ 20 *during* the squeeze. The Ayumi implementation added this as a regime filter and broke the strategy.

## ALTERNATIVE EXPLANATIONS
Why the backtest shows zero trades:

1. **Logic contradiction (confirmed).** Research §A.2 names this exactly: `adx >= 20` during squeeze is impossible by definition. **Smoking gun.**

2. **Session filter too restrictive.** `_passes_session_filter` requires LONDON or NY_AM. For GBPJPY H1 (preset), this filters out 70%+ of bars. Combined with the ADX bug, zero trades is inevitable.

3. **`min_confidence=0.55` floor.** Even when a signal generates, the confidence calculation produces values in 0.60–0.85 range — above the floor. So the floor is not the binding constraint. The ADX gate is.

4. **Min bars requirement is high.** `bb_period + kc_period + ema_period + adx_period + 5 = 73` bars minimum. On M15 that's ~18 hours of data. On H1 it's 3 days. Not the binding constraint but contributes to setup scarcity.

## KILL CRITERIA
Observable conditions that should cause us to stop trading Volatility Squeeze Breakout:

1. **Zero trades in any 30-day forward-test window.** (Current state: ZERO TRADES across 9 cells in walk-forward. **ALREADY TRIGGERED.**)

2. **Trades fire but PF < 1.0 over 30 trades.** (Cannot test — zero trades.)

3. **Squeeze bar count > 20 without ADX rising above 15.** The market is in deep consolidation; any breakout will be false.

4. **`_passes_session_filter` rejects > 80% of bars in a 24-hour window.** Session filter is too restrictive for the symbol (e.g., GBPJPY H1 on weekends).

**STATUS: KILL.** SRF sweep: 0/9 cells traded, 0/9 passed go_nogo. The implementation is broken — `adx >= 20` during a squeeze is logically impossible. This is not a tuning problem; the strategy file should be marked `DEPRECATED = True` and removed from production registry. If the TTM Squeeze hypothesis is desired, replace with `dual_tf_squeeze_pro.py` per research §B.2 (uses HTF regime confirmation instead of in-squeeze ADX, fixes the contradiction).