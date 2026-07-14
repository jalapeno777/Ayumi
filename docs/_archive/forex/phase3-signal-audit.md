# Phase 3 Signal Capability Audit

## Executive Summary

**Can signals fire?** Yes — the signal path from strategy evaluation through to execution is architecturally sound. There is no go/no-go filter in the forward test engine (it exists only in backtest/walk-forward evaluation). However, **zero signals across 8+ evaluations is entirely expected** given current conditions: the forward test is running on **Sunday evening** when the forex market is closed (opens 21:00 UTC Sunday), and even when the market is open, **every active strategy has session filters that restrict firing to specific weekday windows** (London 07:00–11:00 UTC, NY 12:00–17:00 UTC, etc.). Additionally, one **critical bug** was found: `MarketState` is constructed without setting `current_session`, causing it to default to `OUTSIDE`, which silently blocks all session-filtered strategies.

**Verdict: Market conditions (expected) + one code bug (critical)**

---

## Signal Path Trace

The signal path differs depending on which engine class is active. The production launcher (`scripts/launch_blend_forward_test.py`) uses `BlendForwardTestEngine`, which overrides `_evaluate_strategies()`.

### Step-by-step (BlendForwardTestEngine)

1. **Tick arrives** → `_on_tick()` in base `ForwardTestEngine`
2. **Bar building** → Tick updates `_current_bar` for each required timeframe; on bar boundary, completed bar is pushed to `_bars[key]` and `_bar_completed[key] = True`
3. **Evaluation gate** → `_on_tick()` checks:
   - `total_bars >= min_bars_for_evaluation` (55) — if not enough bars, return silently
   - `has_new_bar` — at least one timeframe has a completed bar
   - Consume `_bar_completed` flags
4. **`_evaluate_strategies(symbol)` called** (the BLEND override):
   - **NOT checked**: kill switch (base class checks it, blend override skips it)
   - **NOT checked**: rejection cooldown (base class checks it, blend override skips it)
   - Acquires `_eval_semaphore` (prevents concurrent evaluations)
   - Builds per-timeframe bar snapshots — **includes forming bar** (`_current_bar`) appended to completed bars
   - For each strategy:
     - Resolves strategy's timeframe (15m or 60m per `STRATEGY_TIMEFRAMES`)
     - Checks `len(bars) >= min_bars_for_evaluation` (55)
     - Constructs `MarketState(bars=bars)` ← **BUG: `current_session` not set**
     - Calls `adapter.evaluate_and_trade(state, spread)`
5. **Inside `cTraderSignalAdapter.evaluate_and_trade()`**:
   - Calls `strategy.evaluate(state)` → returns `StrategySignal | None`
   - If signal returned, checks `confidence >= 0.50` (min_confidence)
   - If passed, wraps as `TradeSignal` and returns it
6. **Back in `_evaluate_strategies()` (blend)**:
   - Signal routed to `_route_signal()`
   - **Correlation Gate**: max 1 position per (symbol, direction)
   - **BlendForwardTestRunner**: risk sizing, daily cap check
   - **Execution**: paper → `PaperTrader.process_signal()`, live → `_execute_signal_live()`

### Key difference: Base vs Blend engine

| Check | Base `_evaluate_strategies` | Blend override |
|-------|---------------------------|----------------|
| Kill switch | ✅ Checked | ❌ **Skipped** |
| Rejection cooldown | ✅ Checked | ❌ **Skipped** |
| Forming bar leaked | ✅ Explicitly removed | ❌ **Appended** (`_current_bar` included) |
| Signal routing | Direct to paper/live | Through correlation gate → blend runner |

---

## Per-Strategy Analysis

The blend launcher registers **9 strategies**. Here is each one:

### 1. SRMR+ (H1)
- **File**: `strategies/srmr_plus.py`
- **Class**: `SRMRPlusStrategy`
- **Timeframe**: 60m
- **Entry conditions**:
  - Must be in a trading session: London (07:00–11:00 UTC), NY (12:00–15:00 UTC), Overlap (12:00–16:00 UTC), or NY Close (16:00–20:00 UTC) — checked via `_is_trading_session()`
  - ≥115 bars required (max of ATR+RSI+2, ADX*2+1, EMA+1)
  - Previous session range must be ≥15 pips wide
  - ADX ≤ 25 (low trend strength)
  - Price near session low + RSI < 35 → LONG, or price near session high + RSI > 65 → SHORT
- **Would fire now (Sunday open)**: **NO** — `_is_trading_session()` requires UTC hours 7–20. Market opens at 21:00 UTC Sunday, which is outside all defined trading sessions. Would need to wait until Monday 07:00 UTC (London open).

### 2. Killzone Momentum (M15)
- **File**: `strategies/killzone_momentum.py`
- **Class**: `KillzoneMomentumStrategy`
- **Timeframe**: 15m
- **Entry conditions**:
  - Must be in a killzone: London Open (07:00–09:00 UTC), NY Open (12:00–14:00 UTC), or Overlap (13:00–16:00 UTC)
  - ≥80 bars required
  - Prior session range ≥12 pips
  - ADX ≥ 20 (momentum required)
  - Prior breakout detected in lookback window
  - Breakout direction aligned with 50-EMA trend
  - Price retesting breakout level
  - Bullish/bearish rejection bar pattern on latest bar
- **Would fire now**: **NO** — All killzones are weekday daytime windows (07:00–16:00 UTC). Sunday 21:00 UTC is outside all killzones.

### 3. Donchian Channel Breakout (M15)
- **File**: `strategies/momentum.py`
- **Class**: `DonchianBreakoutStrategy`
- **Timeframe**: 15m
- **Entry conditions**:
  - `_passes_session_filter()` → requires `state.current_session in {LONDON, NY_AM}` ← **AFFECTED BY BUG**
  - ≥22 bars required
  - Close breaks above 20-period Donchian channel high → LONG
  - Close breaks below 20-period Donchian channel low → SHORT
  - ADX ≥ 20, RSI in valid range (not >70 for longs, not <30 for shorts)
  - Confidence ≥ 0.50
- **Would fire now**: **NO** — Two blockers: (1) `current_session` bug means session filter always returns `OUTSIDE`, so `_passes_session_filter()` always fails. (2) Even without the bug, Sunday 21:00 UTC is outside London/NY sessions.

### 4. Session-Range Mean Reversion (H1)
- **File**: `strategies/session_range_mean_reversion.py`
- **Class**: `SessionRangeMeanReversionStrategy`
- **Timeframe**: 60m
- **Entry conditions**:
  - Must be in Asian session (00:00–07:00 UTC) or Early London (07:00–09:00 UTC)
  - Must NOT be in London/NY overlap (12:00–16:00 UTC)
  - ≥66 bars required
  - Previous day's London or NY session range ≥25 pips
  - Price near session extreme + RSI < 30 (LONG) or RSI > 70 (SHORT)
- **Would fire now**: **NO** — Sunday 21:00 UTC is outside Asian (00:00–07:00) and Early London (07:00–09:00) windows.

### 5. BB+RSI Mean Reversion (H1)
- **File**: `strategies/bb_rsi_reversion.py`
- **Class**: `BBRSIMeanReversion`
- **Timeframe**: 60m
- **Entry conditions**:
  - Must be in trading hours: 07:00–21:00 UTC (`_is_trading_session()`)
  - ≥55 bars required
  - Bollinger Band penetration + RSI extreme (RSI < 30 for longs, RSI > 70 for shorts)
  - ADX ≤ 25
  - Low volatility confirmed (ATR below its 20-period SMA)
- **Would fire now**: **NO** — At 21:00 UTC, `_is_trading_session()` check is `7 <= 21 < 21` → **FALSE**. The trading window ends at exactly 21:00 UTC. This is a boundary condition that excludes the Sunday open at 21:00.

### 6. Session Breakout London (M15)
- **File**: `strategies/session_breakout.py`
- **Class**: `SessionBreakoutStrategy` (configured as "Session Breakout London")
- **Timeframe**: 15m
- **Entry conditions**:
  - Range window: 00:00–08:00 UTC (Asian session)
  - Trade window: 08:00–12:00 UTC (London morning)
  - ≥30 bars required
  - Range width between 30–80 pips
  - Close breaks 3 pips above/below range high/low
  - One signal per direction per day
- **Would fire now**: **NO** — Trade window is 08:00–12:00 UTC only. Sunday 21:00 is far outside.

### 7. Session Breakout NY (M15)
- **File**: `strategies/session_breakout.py`
- **Class**: `SessionBreakoutStrategy` (configured as "Session Breakout NY")
- **Timeframe**: 15m
- **Entry conditions**:
  - Range window: 08:00–13:00 UTC (London session)
  - Trade window: 13:00–17:00 UTC (NY afternoon)
  - ≥30 bars required
  - Range width between 25–70 pips
  - Close breaks 3 pips above/below range high/low
- **Would fire now**: **NO** — Trade window is 13:00–17:00 UTC. Sunday 21:00 is outside.

### 8. Session Breakout Asian (M15)
- **File**: `strategies/session_breakout.py`
- **Class**: `SessionBreakoutStrategy` (configured as "Session Breakout Asian")
- **Timeframe**: 15m
- **Entry conditions**:
  - Range window: 21:00–00:00 UTC (NY evening, wraps midnight)
  - Trade window: 00:00–06:00 UTC (Asian session)
  - ≥30 bars required
  - Range width between 20–60 pips
  - Close breaks 3 pips above/below range high/low
- **Would fire now**: **NO** — Trade window starts at 00:00 UTC Monday. At Sunday 21:00 UTC we're in the range definition window, not the trade window. Signals would only be possible after 00:00 UTC Monday.

### 9. Simple RSI Threshold (M15)
- **File**: `strategies/rsi_threshold.py`
- **Class**: `SimpleRSIThresholdStrategy`
- **Timeframe**: 15m
- **Entry conditions**:
  - ≥16 bars required
  - **No session filter** — this strategy has no time-of-day restriction
  - RSI crosses below oversold (20) → LONG
  - RSI crosses above overbought (80) → SHORT
  - Cross detection (not zone occupancy) required
- **Would fire now**: **THEORETICALLY YES** — No session filter. However, RSI must cross the extreme thresholds of 20/80, which are very rare events requiring significant price movement. On a Sunday evening open with low volatility, RSI is unlikely to reach these extremes immediately. This is the **only strategy that could potentially fire** during the Sunday open, but only with unusual volatility.

---

## go_nogo Filter Status

**Not applicable to forward testing.** The `GoNoGoCriteria` and go/no-go evaluation exist exclusively in:
- `backtest/statistical_study.py` — for backtest study evaluation
- `backtest/walk_forward_runner.py` — for walk-forward analysis
- `backtest/phase2d_eval.py` — for phase 2D strategy validation

The forward test engine has **no go/no-go filter** in its evaluation path. The only gates between strategy evaluation and execution are:
1. **Min confidence** (0.50) — in `cTraderSignalAdapter`
2. **Correlation Gate** — max 1 position per (symbol, direction)
3. **BlendForwardTestRunner** — risk budget, daily cap, sizing
4. **FTMOConfig** — `min_risk_reward=0.0` (effectively disabled in the launcher)

---

## Bugs Found

### BUG 1: `MarketState.current_session` never set — **CRITICAL**

**Location**: 
- `forward_test_engine.py:1468` — `state = MarketState(bars=bars)`
- `launch_blend_forward_test.py:240` — `state = MarketState(bars=bars)`

**Impact**: `MarketState.current_session` defaults to `SessionType.OUTSIDE`. It is never set to the actual session based on the current bar time. This means:
- `DonchianBreakoutStrategy` with `session_filter=True` → **permanently blocked** (`_passes_session_filter()` always returns `False`)
- `ATRVolatilityBreakoutStrategy` (if used) → same
- `MATrendFollowingStrategy` (if used) → same
- `VolatilitySqueezeStrategy` with `session_filter=True` → **permanently blocked**
- `VolatilityRegimeBreakoutStrategy` → **permanently blocked**

**Affected active strategies**: Donchian Channel Breakout (#3) is directly affected. The Volatility Squeeze and VRB strategies are in the registry but NOT loaded by the blend launcher, so only Donchian is affected in practice.

**Fix**: Before constructing `MarketState`, derive the session type from the latest bar time:
```python
from backtest.types import SessionType
def _derive_session(bar_time: datetime) -> SessionType:
    h = bar_time.hour
    if 0 <= h < 7: return SessionType.ASIAN
    if 7 <= h < 11: return SessionType.LONDON
    if 12 <= h < 16: return SessionType.NY_AM
    if 16 <= h < 20: return SessionType.NY_PM
    return SessionType.OUTSIDE

state = MarketState(bars=bars, current_session=_derive_session(bars[-1].time))
```

### BUG 2: BlendForwardTestEngine skips kill switch and rejection cooldown — **MODERATE**

**Location**: `launch_blend_forward_test.py:206-292` (`_evaluate_strategies` override)

**Impact**: The base class `_evaluate_strategies` checks the kill switch and rejection circuit breaker before evaluating strategies. The blend override skips both checks entirely. This means:
- If the kill switch is activated (global freeze), strategies will still be evaluated and signals generated
- If the rejection circuit breaker has tripped (too many risk-guard rejections), strategies continue to be evaluated

**Risk level**: Moderate. The blend runner has its own risk checks, and execution-side checks still apply, but the diagnostic/cooldown intent is bypassed.

### BUG 3: BlendForwardTestEngine includes forming bar in evaluation — **LOW-MODERATE**

**Location**: `launch_blend_forward_test.py:225-226`

```python
current = self._current_bar.get(key)
if current is not None:
    bars.append(current)
```

The base class explicitly removes the forming bar to prevent evaluating incomplete candle data (it even has an invariant check for this). The blend override deliberately includes the forming bar. This means strategies evaluate on the in-progress bar, not just completed bars. While this provides faster signal detection, it can produce flickering signals as the bar forms.

---

## Conclusion

**Zero signals from 8+ evaluations is EXPECTED behavior, not a bug.** Here's why:

1. **Market timing**: The forward test has been running during or just after the weekend market close. The forex market opens at 21:00 UTC Sunday, but **no strategy is configured to trade at that hour**. The earliest any strategy can fire is Monday 00:00 UTC (Session Breakout Asian trade window).

2. **Session filters are doing their job**: 8 of 9 strategies have explicit session filters that restrict trading to specific weekday windows. These windows are all between 00:00–20:00 UTC on weekdays. The only strategy without a session filter (Simple RSI Threshold) requires extreme RSI levels (20/80) that are very rare.

3. **One critical bug found**: `MarketState.current_session` is never populated, permanently blocking strategies that rely on it (primarily Donchian Channel Breakout). This would suppress signals **even during active trading sessions** on weekdays. This must be fixed before the strategies can produce their full expected signal rate.

4. **Blends override skips safety checks**: The blend engine's override of `_evaluate_strategies` bypasses the kill switch and rejection cooldown. While not causing the zero-signal issue, it's a safety concern.

### Recommendations

1. **Fix `current_session` bug** — highest priority. Without this, Donchian Breakout and any future session-filtered strategy will never fire.
2. **Add kill switch check to blend override** — match the base class safety pattern.
3. **Wait for London open (07:00 UTC Monday)** to evaluate signal generation in production conditions.
4. **Consider adding a "warm-up" indicator** to the health dashboard showing how many strategies passed/failed each gate (bars insufficient, session filter, confidence threshold, etc.).
