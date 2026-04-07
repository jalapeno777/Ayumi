# Contingency Strategy Research: If Parameter Sweeps Fail

**Issue:** [AYUAA-534](/AYUAA/issues/AYUAA-534) | **Status:** in_progress | **Research Manager**

## Parent: [AYUAA-489](/AYUAA/issues/AYUAA-489)

## Context

We are running parameter sweeps on 4 strategies (Supertrend RSI, Keltner, Momentum x2). Historical pass rate is 18% (2/11). If sweeps do not materially improve this, we need a fundamentally different approach ready to go.

## Executive Summary

The 8 NO-GO pattern reveals a structural problem: **indicator-based strategies with fixed parameters cannot survive regime changes**. Window 0 (2023) passes → Windows 3-4 (2024-2025) fail catastrophically. This is not a parameter problem — it's a strategy architecture problem.

The 5 contingency approaches below are structurally different from our current indicator-based strategies. They share one property: **they adapt to market conditions rather than having fixed parameters**.

---

## Strategy 1: Volatility-Adaptive Position Sizing (VAPS)

### Structural Difference

Instead of changing indicator parameters, this strategy keeps indicator logic fixed but **changes position size based on realized volatility regime**. This directly addresses the regime change failure pattern.

### Entry/Exit Logic

- Entry: Same as baseline strategy (any of our existing passing strategies)
- Exit: Same exit rules
- **Position size**: inversely proportional to ATR percentile (high vol = smaller size)

### Parameters to Optimize

| Parameter | Range | Notes |
|-----------|-------|-------|
| vol_lookback | [20, 50, 100] | ATR smoothing period |
| vol_low_threshold | [0.2, 0.3, 0.4] | ATR percentile below which size increases |
| vol_high_threshold | [0.7, 0.8, 0.9] | ATR percentile above which size decreases |
| size_min | [0.25, 0.5] | Minimum size multiplier |
| size_max | [1.5, 2.0] | Maximum size multiplier |

### Pairs/Timeframes

- EURUSD H1 (existing data, clear volatility regimes)
- GBPUSD H1 (high volatility sensitivity)

### Walk-Forward Viability Assessment

**HIGH.** Volatility-adaptive sizing is well-documented in academic literature. Our existing ATR infrastructure makes this straightforward to implement. This addresses the root cause of regime failures — not by detecting regime, but by making the strategy resilient to regime changes through position sizing.

### Expected Benefit

- Reduces catastrophic drawdowns in high-vol regimes (Windows 3-4)
- Preserves gains in low-vol regimes (Window 0)
- Estimated improvement: 1-2 additional windows passing

---

## Strategy 2: Rolling Window Mean Reversion (RWMR)

### Structural Difference

Fixed lookback parameters (RSI 14, BB 20) fail because the optimal lookback changes with regime. RWMR uses a **rolling optimization window** to continuously find the best lookback parameters.

### Entry/Exit Logic

- Entry: Price touching Bollinger Band + RSI below threshold (both adaptive)
- Exit: Mean reversion complete (price returns to median) OR stop at band opposite
- **Adaptive lookback**: For each bar, compute RSI/BB using lookback that performed best over last N candles

### Parameters to Optimize

| Parameter | Range | Notes |
|-----------|-------|-------|
| min_lookback | [5, 10, 14] | Shortest adaptive lookback |
| max_lookback | [20, 30, 50] | Longest adaptive lookback |
| lookback_step | [5, 10] | Step between lookbacks |
| optimization_window | [100, 200, 500] | Bars to use for lookback optimization |
| entry_threshold | [0.8, 1.0, 1.2] | BB std dev threshold for entry |

### Pairs/Timeframes

- EURUSD M15 (high trade frequency for lookback optimization)
- EURUSD H1 (Session-Range MR already passes — blend with RWMR could improve)

### Walk-Forward Viability Assessment

**MEDIUM-HIGH.** Adaptive lookback is more complex but addresses the specific failure mode of our mean reversion strategies (fixed parameters don't generalize across regimes).

### Risk

- Look-ahead bias in optimization_window — must be strictly non-overlapping with trade entry
- Computational cost higher (multiple lookbacks per bar)

---

## Strategy 3: Cross-Asset Statistical Arbitrage 2.0 (CASA)

### Structural Difference

Current StatArb is EURUSD-GBPUSD pairs trading. This approach extends to **triple-pair arbitrage and cross-asset basket trading**, exploiting relationships that are less sensitive to single-regime changes.

### Entry/Exit Logic

- Entry: Z-score of spread > threshold (long one asset, short another)
- Exit: Spread reverts to historical mean (z-score near 0)
- **New**: Triple-pair mode where spread = A - B + C (e.g., EURUSD - GBPUSD + USDJPY)

### Parameters to Optimize

| Parameter | Range | Notes |
|-----------|-------|-------|
| spread_lookback | [50, 100, 200] | Mean reversion lookback |
| entry_zscore | [1.5, 2.0, 2.5] | Z-score threshold for entry |
| exit_zscore | [0.0, 0.5] | Z-score threshold for exit |
| max_holding_hours | [4, 8, 24] | Time-based exit |
| pair_selection | [EURUSD_GBPUSD, EURUSD_GBPUSD_USDJPY, AUDUSD_USDCAD] | Which pairs to trade |

### Pairs/Timeframes

- EURUSD-GBPUSD (existing StatArb data)
- EURUSD-GBPUSD-USDJPY triple (cross-asset diversification)
- H1 timeframe (smoother signals than M15)

### Walk-Forward Viability Assessment

**MEDIUM.** Triple-pair arb is structurally different enough that it may pass where single-pair StatArb fails. However, correlation between EURUSD and GBPUSD (0.85) means triple extension may not add enough diversification.

### Key Insight

Add **USDJPY** to the pairs table — lower correlation to EURUSD (~0.30) means a EURUSD-GBPUSD-USDJPY basket has better diversification properties.

---

## Strategy 4: Dynamic Session Filter with Adaptive Windows

### Structural Difference

Current session filters use fixed time windows (e.g., London = 08:00-11:00 UTC). This approach uses **adaptive session boundaries** based on actual market activity patterns, not clock time.

### Entry/Exit Logic

- Entry: Same as Session-Range MR (price within range, session active)
- Exit: Same as Session-Range MR
- **Adaptive session**: Session start/end determined by first/last N bars with volume > threshold, not fixed clock hours

### Parameters to Optimize

| Parameter | Range | Notes |
|-----------|-------|-------|
| volume_threshold_pct | [0.5, 0.75, 1.0] | % of average volume to define session bounds |
| min_session_bars | [10, 20, 30] | Minimum bars for valid session |
| session_overlap_tolerance | [0.0, 0.2, 0.4] | How much sessions can overlap |
| range_calc_method | [simple, percentile, atr_normalized] | How to calculate session range |

### Pairs/Timeframes

- EURUSD H1 (Session-Range MR already passes — adaptive session could push to 5/5)
- GBPUSD H1 (5/5 already — could serve as control)

### Walk-Forward Viability Assessment

**MEDIUM.** This is a refinement of Session-Range MR, which already passes. The structural change (adaptive vs fixed session boundaries) is incremental but addresses the specific failure mode where fixed sessions reject valid setups.

### Risk

- Adaptive sessions may produce inconsistent session definitions across walk-forward windows (lessbacktesting-friendly)

---

## Strategy 5: Correlation-Weighted Ensemble (CWE)

### Structural Difference

Instead of equal-weight voting across strategies, this approach **weights each strategy by its correlation to current market conditions**. When strategies are uncorrelated (different regimes), ensemble performs better.

### Entry/Exit Logic

- Entry: Buy signal from weighted ensemble where weight_i = f(correlation(strategy_i, market_regime))
- Exit: Individual strategy exits, ensemble position closed when all components exit
- **Correlation weighting**: Compute rolling correlation of each strategy's equity curve to current regime indicator

### Parameters to Optimize

| Parameter | Range | Notes |
|-----------|-------|-------|
| correlation_window | [50, 100, 200] | Bars for correlation calculation |
| regime_indicator | [ADX, ATR_pct, VIX_proxy] | Which indicator defines regime |
| min_weight | [0.1, 0.2] | Minimum weight per strategy |
| max_strategies | [3, 4, 5] | Max strategies in ensemble |

### Pairs/Timeframes

- EURUSD H1 (multi-strategy compatible)
- Portfolio-level (run on all passing strategies combined)

### Walk-Forward Viability Assessment

**MEDIUM.** This is architecturally similar to the Regime Router (AYUAA-494) but uses correlation weighting instead of hard regime-based switching. The Regime Router NO-GO'd on EURUSD (1/5) while Session-Range MR passed (4/5) — CWE may avoid this by not hard-switching.

### Key Lesson from Regime Router Failure

The Regime Router failed because it **discarded** the good strategy (Session-Range MR) when regime was misdetected. CWE keeps all strategies in the ensemble with varying weights, avoiding the binary wrong-switch problem.

---

## Priority Order for Implementation

| Priority | Strategy | Rationale | Implementation Effort |
|----------|----------|-----------|----------------------|
| 1 | **VAPS** (Volatility-Adaptive Position Sizing) | Addresses root cause (regime), uses existing infrastructure, highest prior probability of success | Low (position sizing only, no strategy logic change) |
| 2 | **CWE** (Correlation-Weighted Ensemble) | Fixes Regime Router flaw, keeps all strategies active, well-documented approach | Medium (requires equity curve tracking) |
| 3 | **RWMR** (Rolling Window Mean Reversion) | Directly addresses fixed-lookback failure, Session-Range MR already passes (base case) | Medium (adaptive parameter logic) |
| 4 | **Adaptive Session Filter** | Refinement of passing strategy, incremental improvement | Low-Medium |
| 5 | **CASA** (Cross-Asset StatArb) | Requires USDJPY data, structural diversification but data dependency | Medium-High |

---

## Key Insight: Why Current Strategies Fail

Our indicator-based strategies have fixed parameters. When regime changes (2023 → 2024), the fixed parameters no longer match market behavior. This is NOT solvable by parameter optimization alone — the architecture must change.

**The 5 approaches above all share adaptation**:
- VAPS: Position sizing adapts to volatility regime
- RWMR: Entry parameters adapt to market conditions
- CASA: Pair selection adapts (triple vs double pair)
- Adaptive Session: Session definition adapts to actual volume
- CWE: Strategy weights adapt to correlation

**Parameter sweeps alone will NOT fix this.** Sweeps optimize within the same architecture. We need architectural changes.

---

*Research completed: 2026-04-07*
*Analyst: Research Manager (Agent 790e1a25-6d3e-47e8-a64f-1654bedb273e)*
*Parent: [AYUAA-489](/AYUAA/issues/AYUAA-489)*