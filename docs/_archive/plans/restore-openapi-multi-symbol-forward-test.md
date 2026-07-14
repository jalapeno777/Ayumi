# Plan: Restore OpenAPI Multi-Symbol Forward Test

**Date:** 2026-04-30
**Author:** Ava (Planner)
**SP Estimate:** 2 SP
**Status:** Draft

---

## Problem

The blend forward test launcher fetches bars for multiple symbols but only passes the primary symbol to the engine. Secondary symbols (e.g. USDJPY) never get their bars preloaded, and the engine's symbol list defaults to `[primary]` only, so the OpenAPI feed never subscribes to them.

**Current broken path:**
```
launcher: --symbols GBPUSD,USDJPY
  → fetches bars for BOTH symbols ✅
  → ForwardTestConfig(symbol="GBPUSD")  ← NO symbols=["GBPUSD","USDJPY"]
  → __post_init__: symbols = [symbol] = ["GBPUSD"] only
  → OpenAPI subscribes to ["GBPUSD"] only
  → engine.preload_bars() never called for any symbol
  → USDJPY is completely dead
```

## Scope

### In Scope
1. Pass `symbols` list to `ForwardTestConfig`
2. Call `engine.preload_bars()` for each symbol+timeframe before `engine.start()`
3. Verify OpenAPI feed subscribes to all configured symbols

### Out of Scope
- `test_flatten.py` BrokenPipeError (tangential, separate fix)
- New features or strategy changes
- FIX feed path (only OpenAPI path affected)

## Root Cause Analysis (Verified)

### Issue 1 — HIGH: `symbols` not passed to `ForwardTestConfig`
**File:** `scripts/launch_blend_forward_test.py` ~line 280
```python
config = ForwardTestConfig(
    symbol=symbols[0],          # ← only single symbol
    # symbols=symbols,          # ← MISSING
    ...
)
```
`ForwardTestConfig.__post_init__` (forward_test_engine.py ~line 100):
```python
if self.symbols is None:
    self.symbols = [self.symbol]
```
Since `symbols` is never passed, it defaults to `["GBPUSD"]`.

**Fix:** Add `symbols=symbols` to the ForwardTestConfig constructor call.

### Issue 2 — HIGH: Preloaded bars never injected into engine
The launcher fetches bars into `symbol_bars: dict[str, dict[int, list[Bar]]]` but **never calls** `engine.preload_bars()`. The engine has a working `preload_bars(symbol, period_minutes, bars)` method (forward_test_engine.py ~line 520) — it just needs to be called.

**Fix:** After creating the engine and before `engine.start()`, loop over `symbol_bars` and call `engine.preload_bars()` for each symbol+timeframe pair.

### Issue 3 — LOW: OpenAPI feed subscription (auto-fixed by Issue 1)
`_start_openapi_feed()` (forward_test_engine.py ~line 330) already iterates `self._config.symbols`:
```python
for sym in self._config.symbols:
    subscribe_names.append(sym.upper().replace("/", ""))
```
Once Issue 1 is fixed, both symbols will be subscribed. No code change needed.

### Issue 4 — MEDIUM: `test_flatten.py` BrokenPipeError
Observed during test collection. Tangential to multi-symbol fix. Flagged but out of scope.

## Acceptance Criteria

1. **AC1:** Launching with `--symbols GBPUSD,USDJPY` subscribes to both symbols in OpenAPI feed (confirmed in logs: "Open API spot feed connected for ['GBPUSD', 'USDJPY']")
2. **AC2:** Pre-fetched H1 and M15 bars for both symbols are loaded into engine before `start()` (confirmed in logs: "Preloaded N bars into key 'GBPUSD:60'", etc.)
3. **AC3:** Ticks for USDJPY produce bars in the engine (confirmed via health monitor or heartbeat showing bars_built incrementing for both symbols)
4. **AC4:** Strategies evaluate on both symbols when bars are available
5. **AC5:** Existing 81 tests still pass
6. **AC6:** Single-symbol mode (`--symbols GBPUSD`) still works unchanged

## File Changes

### Change 1: `scripts/launch_blend_forward_test.py` — Pass symbols to config
**Location:** ~line 280, ForwardTestConfig constructor
```python
# BEFORE:
config = ForwardTestConfig(
    symbol=symbols[0],
    starting_balance=10_000.0,
    ...
)

# AFTER:
config = ForwardTestConfig(
    symbol=symbols[0],
    symbols=symbols,
    starting_balance=10_000.0,
    ...
)
```

### Change 2: `scripts/launch_blend_forward_test.py` — Preload bars into engine
**Location:** After engine creation (~line 300), before `engine.start()` (~line 310)
```python
# NEW CODE — preload fetched bars into engine
for sym, tf_bars in symbol_bars.items():
    for tf_minutes, bars in tf_bars.items():
        if bars:
            engine.preload_bars(sym, tf_minutes, bars)
            logger.info("Preloaded %d bars for %s:%d", len(bars), sym, tf_minutes)
```

### Change 3: No changes to `forward_test_engine.py`
The engine already supports multi-symbol config and has `preload_bars()`. No modifications needed.

### Change 4: No changes to `signal_adapter.py`
`cTraderLiveAdapter` already creates per-symbol adapter instances. No modifications needed.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Strategy symbol filtering skips USDJPY if strategies don't declare it in `strategy.symbols` | Medium | High — no signals on secondary symbol | Verify strategy `.symbols` attribute; if None, adapter creation skips filtering (existing behavior) |
| Bar data gaps on secondary symbol causing premature evaluation | Low | Low — strategies have min_bars threshold | `min_bars_for_evaluation=50` provides buffer; evaluation simply skips until enough bars |
| OpenAPI subscription limit or rate limit on multi-symbol | Low | Medium — feed startup failure | OpenAPI supports multi-symbol subscriptions; test with actual connection |
| preload_bars called before engine._bars dict initialized | None | None — dict initialized in `__init__` | N/A — safe to call after engine construction |

## Test Plan

### Unit Tests (existing suite)
- Run `pytest tests/ -q` — expect 81 pass (no regressions)

### Integration Verification
1. Start forward test with `--symbols GBPUSD,USDJPY`
2. Check logs for:
   - `"Open API spot feed connected for ['GBPUSD', 'USDJPY']"`
   - `"Preloaded N bars for GBPUSD:60"`, `"Preloaded N bars for GBPUSD:15"`, `"Preloaded N bars for USDJPY:60"`, `"Preloaded N bars for USDJPY:15"`
   - Ticks arriving for both symbols (check tick rate in health)
   - Bar building for both symbols (bars_built incrementing)
3. Verify single-symbol `--symbols GBPUSD` still works identically

### Regression Check
- `--symbols GBPUSD` alone → only GBPUSD subscribed, only GBPUSD bars preloaded
- No `--symbols` flag → defaults to `["GBPUSD"]` (unchanged behavior)

## Implementation Order

1. Add `symbols=symbols` to ForwardTestConfig constructor (1 line)
2. Add preload loop after engine creation (~5 lines)
3. Run existing tests
4. Manual verification with dual-symbol launch
