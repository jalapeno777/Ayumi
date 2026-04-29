# Post-Mortem: Strategy Registry + Confluence Detector Wiring

**Date:** 2026-04-24  
**Reviewer:** Mika (Risk Advisor)  
**Scope:** `registry.py`, `confluence.py`, `engine.py` (confluence wiring), tests  
**Overall Confidence Score: 7.5/10** — Solid foundation, a few gaps to close before live

---

## Test Results

**20/20 passed** (11 registry, 9 confluence). Clean run, no warnings from test code.

---

## 1. Code Quality & Scoring Logic

### Registry (`registry.py`)
- **Clean, minimal design.** Dataclass config + dict-backed registry. Simple and correct.
- **Case-insensitive symbol matching** — good defensive coding.
- **No thread safety** — fine for single-threaded backtesting, will need attention if the orchestrator goes async.
- **`default_registry()` hardcodes 8 strategies** — works now, but if strategies get added frequently this becomes a maintenance burden. Consider auto-discovery later (low priority).

### Confluence Detector (`confluence.py`)
- **Signal pruning on insert** — correct and efficient. No stale data accumulation.
- **Scoring logic is sound:**
  - 1 strategy → 0.0 (no confluence)
  - 2 same-type → 0.3, 2 cross-type → 0.5
  - 3+ same-type → 0.7, 3+ cross-type → 0.9
- **No partial credit for confidence values** — a low-confidence signal counts the same as a high-confidence one. This is a design choice, not a bug, but worth flagging: a 0.3 confidence signal shouldn't carry the same confluence weight as a 0.8.

### Confidence Engine Wiring (`engine.py`)
- **Dual-path confluence:** explicit `confluences` list param AND detector integration. Good — supports both manual and automatic flows.
- **Boost cap at 0.30** (0.15 explicit + 0.15 detector). Reasonable ceiling.
- **Gate hard-block on failure** — any gate failure returns score 0.0 immediately. Correct for safety-first design.
- **Minor issue:** detector uses `datetime.now(timezone.utc)` instead of receiving the signal's timestamp. In backtesting, this will always return "now" rather than the bar time. **Bug if backtesting confluence is intended.**

---

## 2. Registry Metadata Accuracy

**8 strategies registered. 10 strategy files exist.**

Missing from registry:
| File | Status |
|------|--------|
| `session_range_mean_reversion.py` | **Actively imported** by backtest, orchestrator, portfolio, ICT filter. This is the original SRMR — still in production use but NOT in the registry. |
| `gbpusd_bb_reversion.py` | Appears to be a pair-specific variant of BB RSI. Likely legacy or specialized. Low concern. |

**Risk:** The confluence detector can't detect signals from unregistered strategies. If `session_range_mean_reversion` fires, it won't contribute to confluence scoring even though it's active in the codebase.

**Recommendation:** Register `session_range_mean_reversion` as a strategy (or confirm it's been superseded by `srmr_plus` and `session_range_mr_ict_filtered` and flag the imports for cleanup).

---

## 3. Confluence Scoring Thresholds

| Threshold | Assessment |
|-----------|------------|
| 2 strategies, same type → 0.3 | Reasonable. Mild boost for agreement within a category. |
| 2 strategies, cross-type → 0.5 | Good. Cross-type agreement is significantly more meaningful. |
| 3+ strategies, cross-type → 0.9 | **Potentially aggressive.** This nearly maxes out confluence. Three strategies agreeing (e.g., two MR + one momentum) doesn't guarantee the trade is good — it could mean correlated noise. |
| Window: 60 minutes | Reasonable for intraday. For D1 strategies, 60 min is too tight — signals could be hours apart and still represent the same thesis. |
| Detector boost: score × 0.15, cap 0.30 | Conservative. Good. |

**Recommendation:** 
- Cap 3+ cross-type at 0.8 instead of 0.9, or add a confidence-weighted component.
- Consider per-strategy-type window configs (D1 strategies get wider windows).

---

## 4. Integration with Confidence Engine

- **Wiring is clean.** Engine accepts optional `confluence_detector`, falls back gracefully to explicit confluences.
- **No circular imports** — `TYPE_CHECKING` guard used correctly.
- **The backtesting timestamp bug** (section 1) is the main integration concern. The detector should accept a `timestamp` parameter rather than calling `datetime.now()`.

---

## 5. What's Next on the Roadmap

| Module | Priority | Dependency on This Build |
|--------|----------|------------------------|
| **Optuna blend optimizer** | HIGH | Registry is the foundation — needs strategy metadata + confluence scoring to define search space. Ready to start. |
| **Confidence gate tuning with historical data** | HIGH | Needs the gate pipeline (done) + confluence boost (done) + historical trade outcomes to optimize thresholds. Ready to start. |
| **ML feature pipeline enhancement** | MEDIUM | Can consume confluence scores as features. No blocker. |
| **Daily performance analytics** | MEDIUM | Needs trade outcome data flowing through confidence engine. Start after gate tuning. |

---

## Issues Summary

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | **Medium** | `session_range_mean_reversion` not in registry but actively used | Register it or confirm superseded and clean up imports |
| 2 | **Medium** | Detector uses `datetime.now()` — breaks backtesting confluence | Pass timestamp through `score()` method |
| 3 | **Low** | No confidence weighting in confluence scoring | Consider weighting signals by confidence in future iteration |
| 4 | **Low** | Single window size (60 min) for all strategy types | Per-type window config for D1 strategies |
| 5 | **Info** | `gbpusd_bb_reversion.py` not in registry | Investigate — likely legacy, document or register |
| 6 | **Info** | No thread safety on registry | Fine for now, track for async orchestrator |

---

## Verdict

The registry + confluence wiring is a **solid Phase 1 deliverable**. Clean code, good test coverage, sensible scoring. The two medium-severity issues (missing strategy registration, backtesting timestamp) should be fixed before the Optuna optimizer consumes this — bad data in, bad optimization out. Everything else is low-priority polish.

**Ready for next build.** Fix issues #1 and #2, then proceed to Optuna blend optimizer.
