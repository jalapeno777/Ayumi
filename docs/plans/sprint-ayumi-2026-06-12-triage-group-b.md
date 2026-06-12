# BQ Triage Report — Group B (Signal/Strategy/Backtest)
**Date:** 2026-06-12  
**Triage Agent:** Subagent (Group B)  
**Context:** Forward test LIVE (1948 ticks, 0 errors), 8 strategies active, blend pipeline with correlation gate running.

---

## Item-by-Item Triage

### BQ-687: Strategy Pipeline Standardization (2 SP, draft)
**Verdict: RESPEC**  
**Evidence:** The strategy registry (`engine/strategy_registry.py`, 131 lines) already exists with `StrategySlot`, factory registration, YAML loading, and `StrategyFactory` type alias. The spec asks to "design strategy registry and lifecycle management" — this is partially built. The remaining work (standardized signal/risk/TP-SL interface, lifecycle management) is still needed but scope is narrower than original spec.  
**New SP:** 3 → 1.5 (registry exists, only interface standardization remains)  
**New scope:** Standardize the ISignalStrategy interface to enforce signal generation, risk params, position sizing, and TP/SL contracts. Add lifecycle hooks (init/warmup/active/shutdown). Skip registry design — it's done.

---

### BQ-133: Spread Regime Classifier Feature for Signal Engine (3 SP, drafts)
**Verdict: DEFER**  
**Evidence:** `core/spread.py` already has `RealisticSpreadModel` with per-bar spread from bid/ask data. The signal engine does not currently consume spread regime signals. This is a nice-to-have enhancement (classify thin/normal/wide spread regimes and gate signals) but not critical — the forward test runs fine without it. The spread model is already realistic.  
**Reason:** No forward-test pain driving this. Spread handling works. Deprioritize behind items that unblock production readiness.

---

### BQ-345: Signal Engine Bar-Close Audit (2 SP, ready)
**Verdict: READY**  
**Evidence:** Confirmed the signal engine has no `on_bar_close` / `bar_complete` handlers. Searched all files in `signal_engine/` — no bar-close gating logic exists. The spec's concern (signals generated on forming bars rather than closed bars) is a real risk affecting win rate. This is a concrete, bounded audit + fix.  
**Confirmed SP:** 1.5 (audit + add bar-close gate to signal evaluation pipeline)

---

### BQ-369: Wire Kelly Criterion into MultiStrategyBacktestEngine (2 SP, ready)
**Verdict: READY**  
**Evidence:** `kelly_criterion()` exists in `quant/position_sizing.py` (Half-Kelly, 50% cap). `MultiStrategyBacktestEngine` uses fixed `ConfidencePositionSizer` with no Kelly integration. No Kelly references found in `multi_strategy_engine.py` or `engine.py`. Clear, scoped wiring task.  
**Confirmed SP:** 1 (function exists, just needs to be called from MultiStrategyBacktestEngine with trade history stats)

---

### BQ-545: Validate trend+ATR filter combination against backtest data (2 SP, drafts)
**Verdict: RESPEC**  
**Evidence:** `session_breakout.py` already has `h4_trend_filter` (H4 50 EMA) and `_calculate_atr()`. The filter exists but hasn't been validated across all strategies. Scope should narrow to: validate the trend+ATR filter on the 8 active strategies using walk-forward data, produce a validation report.  
**New SP:** 1.5  
**New scope:** Run trend+ATR filter validation against backtest data for all 8 active strategies. Output: per-strategy metrics with/without filter. No new code needed — the filter already exists in `session_breakout.py`.

---

### BQ-504: London Breakout ORB Strategy Module (5 SP, drafts)
**Verdict: RESPEC**  
**Evidence:** `session_breakout.py` already implements London/NY/Asian session breakouts with ATR calculation, range detection, and breakout logic. The "London Breakout ORB" is largely already implemented as `SessionBreakoutStrategy` with `session="london"`. The remaining gap is Opening Range Breakout (ORB) specific logic — defined range window (e.g., first 30min of London), then trade breakout of that range. This is a subset of what exists.  
**New SP:** 2  
**New scope:** Add ORB sub-mode to `SessionBreakoutStrategy`: configurable opening range window (default 30min), ORB high/low levels, breakout entry with ORB-specific TP/SL. Don't build a separate strategy — extend the existing one.

---

### BQ-508: Regime-labeling module for walk-forward backtest windows (3 SP, drafts)
**Verdict: READY** (with minor scope clarification)  
**Evidence:** `quant/regime.py` has full regime detection (volatility, trend, session, combined). `backtest/walk_forward_runner.py` and `quant/walk_forward.py` have walk-forward infrastructure with `WindowMetrics`. No regime labeling per window exists — `WindowMetrics` doesn't include regime fields. Clear integration task.  
**Confirmed SP:** 2 (add regime labels to `WindowMetrics`, run regime detection on each training window's data, include regime in walk-forward output)

---

### BQ-117: Fix forward_test_engine logging namespace (0.5 SP, drafts)
**Verdict: CLOSE**  
**Evidence:** The spec body says "This draft is superseded by BQ-122 (same root-cause fix with stronger evidence trail)." Confirmed the logger is `logging.getLogger("ayumi.forward_test")` which is functional. The superseding BQ-122 should be tracked instead.  
**Action:** Close as superseded by BQ-122.

---

### BQ-118: Fix forward test logging namespace - ayumi.* vs adapters.ctrader.* (0.5 SP, drafts)
**Verdict: CLOSE**  
**Evidence:** Same as BQ-117 — spec body explicitly says "This draft is superseded by BQ-122." Both are duplicates pointing to the same root cause. The actual logger namespace is `ayumi.forward_test` which is working in production (1948 ticks, 0 errors).  
**Action:** Close as superseded by BQ-122.

---

### BQ-102: Preference Authenticity & Specificity Pipeline (3 SP, drafts)
**Verdict: NOT_AYUMI**  
**Evidence:** Title and spec relate to Ava's learning/personality system (preference authenticity scoring). Category is not `ayumi`. This is Ava learning pipeline work, not trading system work.  
**Action:** Recategorize to Ava learning/personality domain.

---

### BQ-592: Mode-aware authenticity thresholds in learning pipeline (3 SP, drafts)
**Verdict: NOT_AYUMI**  
**Evidence:** Explicitly about "learning pipeline" authenticity thresholds tied to Ava's behavioral modes. Not trading system work.  
**Action:** Recategorize to Ava learning/personality domain.

---

### BQ-234: Second-order generalization criteria (4 SP, draft)
**Verdict: NOT_AYUMI**  
**Evidence:** Category is `ava-learning`. Spec body says "BLOCKED on BQ-137 + BQ-667. Plan written. Min 2-week wait after BQ-137 ships for data." This is Ava's learning system generalization work, not trading.  
**Action:** Recategorize to Ava learning/personality domain.

---

## Summary Table

| ID | Verdict | SP | Notes |
|----|---------|-----|-------|
| BQ-687 | RESPEC | 1.5 | Registry exists; narrow to interface standardization |
| BQ-133 | DEFER | 3 | Spread model already realistic; no production pain |
| BQ-345 | READY | 1.5 | Real risk — no bar-close gating in signal engine |
| BQ-369 | READY | 1 | Kelly exists, just needs wiring |
| BQ-545 | RESPEC | 1.5 | Filter exists; narrow to validation report |
| BQ-504 | RESPEC | 2 | Session breakout exists; add ORB sub-mode |
| BQ-508 | READY | 2 | Clear integration: regime labels on walk-forward windows |
| BQ-117 | CLOSE | — | Superseded by BQ-122 |
| BQ-118 | CLOSE | — | Superseded by BQ-122 |
| BQ-102 | NOT_AYUMI | — | Ava learning/personality |
| BQ-592 | NOT_AYUMI | — | Ava learning/personality |
| BQ-234 | NOT_AYUMI | — | Ava learning/personality, blocked on BQ-137+667 |

**Autobuild-ready items (today's sprint candidates):** BQ-345 (1.5 SP), BQ-369 (1 SP), BQ-508 (2 SP) = **4.5 SP total**

**RESPEC items (need spec update before scheduling):** BQ-687, BQ-545, BQ-504 = **5.5 SP after respec**

---

## JSON Verdicts

```json
[
  {"id": "BQ-687", "verdict": "RESPEC", "evidence": "Strategy registry (strategy_registry.py, 131 lines) already exists with StrategySlot, factory registration, YAML loading. Spec scope overlaps existing work. Narrow to ISignalStrategy interface standardization + lifecycle hooks only.", "new_sp": 1.5, "new_scope": "Standardize ISignalStrategy interface (signal, risk, sizing, TP/SL contracts). Add lifecycle hooks. Skip registry design — already built."},
  {"id": "BQ-133", "verdict": "DEFER", "evidence": "RealisticSpreadModel in core/spread.py already handles per-bar spread from bid/ask data. Signal engine runs fine without regime classification. No production pain driving this.", "new_sp": null, "new_scope": null},
  {"id": "BQ-345", "verdict": "READY", "evidence": "Confirmed no bar-close/on_bar_complete handlers exist in signal_engine/. Signals may fire on forming bars, affecting win rate (30% cited in spec). Concrete audit + fix task.", "new_sp": 1.5, "new_scope": null},
  {"id": "BQ-369", "verdict": "READY", "evidence": "kelly_criterion() exists in quant/position_sizing.py with Half-Kelly/50% cap. MultiStrategyBacktestEngine uses fixed ConfidencePositionSizer with zero Kelly references. Clean wiring task.", "new_sp": 1.0, "new_scope": null},
  {"id": "BQ-545", "verdict": "RESPEC", "evidence": "session_breakout.py already has h4_trend_filter and _calculate_atr(). No new filter code needed. Scope should narrow to validation report across 8 active strategies.", "new_sp": 1.5, "new_scope": "Run trend+ATR filter validation against backtest data for all 8 active strategies. Output per-strategy metrics with/without filter."},
  {"id": "BQ-504", "verdict": "RESPEC", "evidence": "SessionBreakoutStrategy already implements London/NY/Asian breakouts. ORB is a subset — add configurable opening range window (30min) and ORB-specific entry logic as a sub-mode.", "new_sp": 2.0, "new_scope": "Add ORB sub-mode to SessionBreakoutStrategy: opening range window, ORB high/low levels, breakout entry. Extend existing strategy, don't create new one."},
  {"id": "BQ-508", "verdict": "READY", "evidence": "quant/regime.py has full regime detection. walk_forward.py has WindowMetrics without regime fields. Clear integration: add regime labels to each walk-forward window.", "new_sp": 2.0, "new_scope": null},
  {"id": "BQ-117", "verdict": "CLOSE", "evidence": "Spec body explicitly states 'superseded by BQ-122'. Logger namespace (ayumi.forward_test) is functional in production.", "new_sp": null, "new_scope": null},
  {"id": "BQ-118", "verdict": "CLOSE", "evidence": "Spec body explicitly states 'superseded by BQ-122'. Duplicate of BQ-117, same root cause. Production logging works.", "new_sp": null, "new_scope": null},
  {"id": "BQ-102", "verdict": "NOT_AYUMI", "evidence": "Preference authenticity pipeline for Ava's learning/personality system. Not trading system work.", "new_sp": null, "new_scope": null},
  {"id": "BQ-592", "verdict": "NOT_AYUMI", "evidence": "Mode-aware authenticity thresholds in Ava's learning pipeline. Not trading system work.", "new_sp": null, "new_scope": null},
  {"id": "BQ-234", "verdict": "NOT_AYUMI", "evidence": "Category: ava-learning. Second-order generalization for Ava's learning system. Blocked on BQ-137+667. Not trading work.", "new_sp": null, "new_scope": null}
]
```
