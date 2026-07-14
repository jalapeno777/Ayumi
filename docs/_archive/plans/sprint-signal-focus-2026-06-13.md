# Ayumi Signal-Focus Sprint — 2026-06-13

**Goal:** Get the forward test producing signals. The pipeline is wired (ticks→bars→strategies→blend), bar building works, evaluation triggers on bar close. Zero signals means strategy parameters are too conservative or market conditions don't match strategy assumptions.

**Current state:** Forward test live, ~21k ticks, 30+ bars, 0 signals, 0 trades, $10k balance.

---

## Diagnosis: Why Zero Signals?

### What's Working
- ✅ Tick stream connected (21k ticks, 1.4 tps)
- ✅ Bar building on 15m + 60m TFs (preloaded 99/199 bars, 30 new bars)
- ✅ Evaluation triggers on bar completion events
- ✅ 8 strategies loaded: SRMR+, Killzone, Donchian, Session-Range MR, BB+RSI MR, 3x Session Breakout
- ✅ 2 symbols: GBPUSD, USDJPY

### Likely Causes (ranked)
1. **Strategy parameters not calibrated for live data** — strategies were likely tuned on backtest data with different bar counts/lookbacks. Live bars may not meet internal thresholds.
2. **Confidence gating** — min confidence 0.50. If strategies produce signals below this threshold, they're silently dropped.
3. **Insufficient bar history for indicators** — strategies may need 100+ bars for their indicator warmup. Preloaded 99/199 bars should cover this, but need to verify per-strategy.
4. **Market conditions** — it's Friday afternoon (low volatility), many strategies are session-specific (London/NY/Asian). If running outside those windows, no signals expected.

---

## Sprint Items

### BQ-S1: Signal Diagnostic Dashboard (~1 SP)
**Priority:** P0 — can't fix what we can't see

Add instrumentation to expose WHY signals aren't firing:
- Per-strategy evaluation counter (how many times each strategy ran)
- Per-strategy "near miss" counter (evaluated but no signal / signal below confidence)
- Per-strategy last evaluation timestamp
- Per-strategy indicator readiness flag (has enough bars for lookback?)
- Log at INFO level when evaluation runs (not just DEBUG)
- Expose as JSON endpoint or periodic log line (like B5 Health)

**Files:** `forward_test_engine.py`, `blend_runner.py`
**AC:** Can see per-strategy eval count + reason for no signal in logs

### BQ-S2: Strategy Parameter Audit (~1.5 SP)
**Priority:** P0 — the actual fix

Audit each strategy's `evaluate()` method:
1. What are the internal thresholds/gates?
2. What lookback periods do indicators need?
3. Are those lookbacks satisfied by the preloaded bar count?
4. What conditions produce a signal vs returning None?
5. Are there hardcoded assumptions about bar period or symbol that don't match live config?

For each strategy, document: min bars needed, typical signal frequency in backtest, any session/time filters.

**Output:** `docs/forex/strategy-audit-2026-06-13.md` — per-strategy findings + recommended parameter changes

**Files:** All 8 strategy files
**AC:** Clear understanding of why each strategy isn't firing + fix recommendations

### BQ-S3: Confidence Gate Tuning (~0.5 SP)
**Priority:** P1 — after audit reveals signal flow

- Lower min_confidence from 0.50 to 0.30 temporarily for diagnostic
- Add per-signal confidence logging to see what strategies ARE producing
- Once signals flow, tune back up based on observed distribution

**Files:** `launch_blend_forward_test.py`, `blend_runner.py`
**AC:** Can see raw strategy output before confidence gating

### BQ-S4: BQ-687 Deferred — Error Containment (~1 SP)
**Priority:** P2 — after signals flow

From BQ-687 council findings:
- Add try/except per strategy in `run_all_strategies()` and `run_combined_strategies()`
- Fix combined-run state leak (reset before each individual run after combined)
- 4 isolation tests

**Files:** `multi_strategy_engine.py`, `vaps_engine.py`, tests
**AC:** One strategy failure doesn't kill the run; combined results don't leak

### BQ-S5: Walk-Forward Smoke Test (~1 SP)
**Priority:** P2 — validates the full pipeline

Run walk-forward on all strategies with recent data:
- Verify Kelly sizing + regime labels work end-to-end (BQ-369 + BQ-508)
- Identify which strategies have actual edge vs noise
- Produce ranked strategy report

**Files:** `walk_forward_runner.py`, `multi_strategy_engine.py`
**AC:** Walk-forward produces per-strategy metrics with regime labels + Kelly sizing

### BQ-S6: Credential Logging Fix (~0.5 SP)
**Priority:** P0 — security

`open_api_spot_feed.py` logs OAuth credentials at CRITICAL level in plaintext. Remove or redact immediately.

**Files:** `open_api_spot_feed.py`
**AC:** No plaintext credentials in logs

---

## Execution Order

```
BQ-S6 (cred fix)     → immediate, 10 min fix
BQ-S1 (diagnostics)  → first, so we can see what's happening
BQ-S2 (strategy audit) → parallel with S1
BQ-S3 (confidence)    → after S2 findings
BQ-S4 (isolation)     → after signals flow
BQ-S5 (walk-forward)  → after signals flow
```

## Success Criteria

1. Forward test produces at least 1 signal in a 24-hour period
2. Per-strategy diagnostic data visible in logs
3. No plaintext credentials in logs
4. Clear ranking of which strategies have edge

---

## Open Questions for Craig
- What timeframes/symbols do you want to focus on? Currently GBPUSD + USDJPY.
- Any strategies you want to add or remove from the forward test?
- Walk-forward period — how far back? 6 months? 1 year?
