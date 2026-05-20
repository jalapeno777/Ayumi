# Signal Threshold Analysis — GBPUSD & USDJPY Forward Test
**Date:** 2026-05-18
**Status:** Zero signals generated in 4+ days of forward testing
**Strategies:** SRMR+, Killzone Momentum, Session-Range Mean Reversion, BB+RSI Mean Reversion, Donchian Breakout, Session Breakouts (London/NY/Asian)

---

## Executive Summary

The zero-signal condition is NOT caused by a single bottleneck but by a **layered filter stack** where multiple conservative thresholds compound to block nearly all market opportunities. The most critical finding is a **bar-count shortage that prevents SRMR+ from ever evaluating**, followed by ADX and session-range thresholds that are too tight for trending/range-bound conditions respectively.

---

## 1. Current Threshold Settings vs. Market Conditions

### SRMR+ (H1) — Primary Engine for GBPUSD/USDJPY

| Parameter | Current Value | Typical Market Range | Assessment |
|-----------|--------------|---------------------|------------|
| `adx_max_threshold` | **20.0** | 15–45 | 🔴 TRENDING REGIMES excluded (ADX > 20 is common) |
| `session_range_min_pips` | **15.0** | 5–80+ | 🟡 Narrow ranges excluded |
| `entry_near_extreme_pips` | **15.0** | Must be within 15 pips of session hi/lo | 🟡 Tight entry zone |
| `rsi_long_level` | **35.0** | 30–50 (oversold) | 🟢 Standard |
| `rsi_short_level` | **65.0** | 50–70 (overbought) | 🟢 Standard |
| `ema_trend_period` | **50** | H1: 50 bars = ~2 days | 🟢 Standard |

**Signal confidence formula:** `0.55 + (0.15 × (1 - ADX/20))`, capped 0.40–0.80
- At ADX = 20 → conf = 0.55 (passes 0.50 filter ✓)
- At ADX = 15 → conf = 0.64 (passes ✓)
- At ADX = 25 → conf = 0.46 (BLOCKED by 0.50 adapter filter ✗)

### Killzone Momentum (M15)

| Parameter | Current Value | Assessment |
|-----------|--------------|------------|
| `adx_threshold` | **20.0** | 🔴 ADX must be > 20 to enter (same problem) |
| `min_session_range_pips` | **20.0** | 🔴 Higher than SRMR+ |
| `breakout_lookback_bars` | **6** | Must detect prior breakout in last 6 bars |
| `retest_tolerance_atr` | **0.5 × ATR** | Rejection bar must be within 0.5 ATR of range extreme |
| `min_bars_for_setup` | **80** | Need 80+ M15 bars |

**Killzone windows (UTC):** London Open 7–9, NY Open 12–14, Overlap 13–16

### Session-Range Mean Reversion (H1)

| Parameter | Current Value | Assessment |
|-----------|--------------|------------|
| `session_range_min_pips` | **25.0** | 🔴 STRICT — higher than SRMR+ |
| `adx_threshold` | **Not explicitly checked** | 🟢 Less restrictive |
| `rsi_long/short` | **30/70** | 🟢 More oversold/overbought tolerant |

---

## 2. Specific Bottleneck Analysis

### Bottleneck #1: SRMR+ Bar Count Shortage (CRITICAL — silent failure)

**Finding:** SRMR+ requires `min_required = max(ATR_period + RSI_period + 2, ADX_period × 2 + 1, EMA_period + 1)` = max(14+14+2, 14×2+1, 50+1) = **51 bars minimum**.

The forward test startup preloads only **49 H1 bars** (from API `min_bars_for_evaluation=50`, minus 1 for 0-indexing).

**Result:** `len(state.bars) < 51` → SRMR+ returns `None` immediately on every evaluation. **SRMR+ has produced zero signals since forward test inception.**

This is a silent failure — no error log is generated because the check at line 342 is a `logger.debug()` call, which is suppressed at INFO log level.

**Fix:** Increase `min_bars_for_evaluation` to at least **51** in `ForwardTestConfig`, or ensure the API returns 50+ bars.

---

### Bottleneck #2: ADX Threshold of 20 — Overly Conservative for GBPUSD

**Finding:** Both SRMR+ (max threshold 20) and Killzone Momentum (minimum threshold 20) use ADX=20 as a gating parameter.

In trending markets (which GBPUSD exhibits regularly, especially around news events and policy decisions), ADX routinely exceeds 25–35+. The ADX filter blocks entries in trending conditions — precisely when mean reversion strategies should be most cautious, but also when range-bound opportunities within sessions still exist.

SRMR+ confidence formula means ADX > 20 → confidence < 0.55 → rejected by 0.50 adapter threshold.

**Signal frequency impact:** If GBPUSD has ADX > 20 for 60% of the trading day, SRMR+ can only fire in the remaining 40% — and only if other conditions align.

---

### Bottleneck #3: Session Range Minimum of 15–25 Pips

**Finding:** The minimum session range filters out low-volatility days entirely.

GBPUSD average daily range is ~100–150 pips, but the session ranges (London, NY) within a day can be much narrower — especially during:
- Asian session carry rolls
- Early London (thin volume)
- End of NY PM session

If the prior day's London session range is < 15 pips (or < 25 pips for Session-Range MR), no signal can fire regardless of other conditions.

**Backtest evidence:** Session Range MR on GBPUSD (5-window walk-forward, 85 test days) showed **mean 14.8 trades per window** — approximately **1 signal per 5–6 trading days per symbol**. This is consistent with the forward test showing zero signals in 4 days across 2 symbols.

---

### Bottleneck #4: Killzone Timing and M15 Bar Shortage

**Finding:** Killzone Momentum needs:
1. Bars within a killzone window (7–9, 12–14, 13–16 UTC)
2. A prior session range with ≥ 20 pips
3. A detected breakout in the last 6 M15 bars
4. A bullish/bearish rejection bar at the retest

The forward test started at ~14:16 UTC on May 18. The first London Open killzone (7–9 UTC) had already passed. The NY Open killzone (12–14 UTC) was ending. The Overlap (13–16 UTC) overlaps with the tail of NY Open.

Additionally, M15 bar preloading was **only 49 bars** (same API limit issue as H1), but Killzone Momentum needs 80 bars minimum.

---

### Bottleneck #5: Eight Strategies on Two Symbols — Correlation Overlap

**Finding:** 8 strategies × 2 symbols means 16 possible signal sources, but the correlation gate limits to 1 position per (symbol, direction). With overlapping strategy logic (SRMR+, Session-Range MR, BB+RSI all use session-range logic), the effective independent signal sources are fewer than they appear.

---

## 3. Backtest Comparison

From `reports/walk_forward/GBPUSD_session_range_mr_5window.json`:

| Window | Trades | Win Rate | Profit Factor | Days in Window | Signals/Day |
|--------|--------|----------|---------------|----------------|-------------|
| 0 | 12 | 75% | 2.54 | ~17 | ~0.71 |
| 1 | 10 | 70% | 1.94 | ~17 | ~0.59 |
| 2 | 16 | 56% | 1.06 | ~17 | ~0.94 |
| 3 | 20 | 65% | 1.58 | ~17 | ~1.18 |
| 4 | 16 | 56% | 1.09 | ~17 | ~0.94 |
| **Mean** | **14.8** | **64.5%** | **1.64** | **~17** | **~0.87** |

**Implication:** Session Range MR (the most "generous" of the active strategies) historically produced ~1 signal per trading day per symbol in favorable windows. In weaker windows (windows 2, 4), it still produced ~1 signal per 2 days.

With 8 strategies active but overlapping logic and ADX/range filters, the combined signal rate should be higher — but the bar shortage, killzone timing, and strict session-range minimums are preventing any signals.

---

## 4. Recommendations

### Priority 1: Fix Bar Count Shortage (zero-cost, eliminates silent failure)

```python
# In launch_blend_forward_test.py line ~578
min_bars_for_evaluation=55,  # was 50; must exceed SRMR+ min_required=51
```

Also ensure the API bar fetch returns ≥ 55 bars. Current API call uses `count=self._config.min_bars_for_evaluation` (50) which returned 49.

### Priority 2: Relax ADX Thresholds (moderate risk)

| Strategy | Current ADX | Proposed |
|----------|-------------|----------|
| SRMR+ `adx_max_threshold` | 20.0 | **25.0** |
| Killzone Momentum `adx_threshold` | 20.0 | **25.0** |

This allows entries when ADX is 20–25 (mild trend) while still excluding strong trends. Confidence formula adjustment would be needed to ensure confidence ≥ 0.50 for this range.

### Priority 3: Reduce Session Range Minimum for Killzone Momentum (moderate risk)

Killzone Momentum `min_session_range_pips = 20.0` is very high. Reduce to **12.0 pips** to match SRMR+'s threshold.

### Priority 4: Log-Level Fix for SRMR+ Silent Failure (zero-cost debugging)

Change `logger.debug` at srmr_plus.py line 342 to `logger.info` so bar-shortage failures appear in logs:

```python
# srmr_plus.py line ~342
logger.info("SRMR+ %s: insufficient bars (have=%d, need=%d)...", ...)
```

### Priority 5: Add Killzone Awareness Logging

The killzone momentum strategy returns `None` silently on multiple conditions. Add `logger.info` on first failed condition per killzone window to identify which filter is blocking.

---

## 5. Risk Assessment of Proposed Changes

| Change | Risk | Rationale |
|--------|------|-----------|
| Increase min_bars to 55 | **Very Low** | Only enables evaluation that should already happen |
| Raise ADX max to 25 | **Low-Medium** | More signals in trending conditions; SRMR+ is still range-reversion so SL/TP handle trend edges |
| Reduce KZ min range to 12 | **Low** | Matches SRMR+; rejection bar still required for confirmation |
| SRMR+ debug → info | **Zero** | Debugging improvement only |

---

## 6. Root Cause Summary

```
[Zero signals]
├── SRMR+ never evaluates: 49 bars loaded < 51 required  ← CRITICAL (silent)
├── ADX > 20: SRMR+ confidence < 0.50, filtered by adapter  ← HIGH
├── Session range < 15 pips: SRMR+ exits before price check  ← MEDIUM
├── Killzone M15: 49 bars < 80 required  ← HIGH (silent)
├── Killzone ADX filter: ADX < 20 → no entry  ← MEDIUM
└── Session-Range MR: 25-pip minimum on range  ← MEDIUM
```

**Primary fix order:** bar count → SRMR+ debug logging → ADX relaxation → range minimum relaxation.

---

*Analysis by signal-threshold-analysis subagent | 2026-05-18*
