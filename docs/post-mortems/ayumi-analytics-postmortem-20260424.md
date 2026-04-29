# Post-Mortem: Historical Signal Provider, Score Formula, & Daily Analytics

**Date:** 2026-04-24
**Reviewer:** Mika (Risk Advisor)
**Scope:** `signal_provider.py`, `blend_optimizer.py`, `daily_report.py`, associated tests

---

## Confidence Score: 7.5 / 10

Solid foundation, a few issues worth flagging before production wiring.

---

## 1. P0/P1 Fixes — Are They Correct?

### P0: Historical signal determinism ✅
- `HistoricalSignalProvider` uses `hashlib.md5(strategy_id)` as seed → deterministic per strategy.
- JSONL disk caching means regenerate returns identical results.
- Test `test_deterministic_generation` confirms cross-instance consistency.
- **Verdict:** Correct.

### P1: Score formula gaming vector ✅ (partially)
- `profit_factor` added to score (was missing — pure win_rate × sqrt(trades) was gameable).
- `strategy_penalty = 1/(1 + 0.1*(n-1))` penalizes activating all strategies.
- **Issue:** `gross_profit` / `gross_loss` calculation in `objective()` is broken:
  ```python
  gross_profit=result.profit_factor * max(result.total_pnl, 0),
  gross_loss=max(-result.total_pnl, 0) if result.total_pnl < 0 else 1.0,
  ```
  This derives gross_profit from `profit_factor * total_pnl` — a circular reference. If `total_pnl < 0`, `gross_profit = 0` (correct) but `gross_loss = 1.0` (should be absolute loss). If `total_pnl > 0`, `gross_loss = 1.0` (hardcoded floor). This means `profit_factor` in the score is effectively just `gross_profit`, which is `profit_factor * total_pnl` — the profit_factor appears twice in the formula.
- **Severity:** Medium. The optimizer still *ranks* correctly (more profit = higher score), but the profit_factor term doesn't do what it says. It's `profit_factor² * total_pnl * ...` effectively.
- **Fix:** The backtest runner (`BlendBacktest`) needs to expose actual `gross_profit` and `gross_loss` fields, not derive them from `profit_factor * total_pnl`.

---

## 2. Historical Signal Determinism

**Yes, truly deterministic.** Seed = MD5 of strategy_id. Same strategy_id → same Random instance → same signals. Disk caching adds a second layer. Cross-instance test passes.

**Edge case flagged:** `start_date` and `end_date` parameters are accepted but **never used** in `_deterministic_signals()`. The date range is hardcoded to 60 days starting 2025-01-06. This means `generate_signals("EURUSD", "2024-01-01", "2024-12-31")` silently returns 2025 data. Not a correctness bug (optimizer doesn't care about real dates), but a footgun if anyone assumes date filtering works.

---

## 3. Score Formula — Gaming Vector Fix

The original formula (`win_rate * sqrt(trades) * dd_factor`) was gameable by:
- High-frequency low-confidence strategies inflating trade count
- Activating all strategies (no penalty for complexity)

The new formula (`profit_factor * win_rate * sqrt(trades) * dd_factor * strategy_penalty`) addresses both:
- **profit_factor** penalizes strategies with large losses even if win rate is decent
- **strategy_penalty** makes adding marginal strategies costly

**Remaining gaming vector:** A strategy that wins many tiny trades and loses rarely but big still scores well because `sqrt(trades)` rewards volume. The profit_factor helps but doesn't fully eliminate this. Consider capping `sqrt(trades)` contribution or using `log(trades)` instead.

---

## 4. Daily Analytics — Ready for Morning Briefing?

**Yes, structurally ready.** The `DailyAnalytics` class:
- Reads from `logs/trades.jsonl` (date-filtered)
- Produces `DailyPerformance` dataclass with all needed fields
- `format_report()` outputs human-readable text
- `generate_summary(days=7)` supports multi-day lookback
- Handles empty trade logs gracefully (returns zeros)

**Gaps before wiring to cron:**
- No timezone handling — `datetime.now()` uses server local time, not EDT. Craig's in EDT.
- Hardcoded 10k base balance for `daily_risk_used_pct` — should read from config.
- No alerting thresholds (e.g., "win rate below X" → flag).
- Missing: weekly/monthly aggregation for trend analysis.

---

## 5. Dead Code

`_generate_synthetic_signals()` in `blend_optimizer.py` (lines ~130-185) is dead code. The optimizer now uses `HistoricalSignalProvider` exclusively. This method references the old synthetic approach and should be removed.

---

## Issues Summary

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 1 | **Medium** | Circular profit_factor calculation in `objective()` | `blend_optimizer.py` ~L95 |
| 2 | **Low** | `start_date`/`end_date` params ignored in signal generation | `signal_provider.py` ~L97 |
| 3 | **Low** | Dead code: `_generate_synthetic_signals()` | `blend_optimizer.py` ~L130 |
| 4 | **Low** | No timezone awareness in daily analytics | `daily_report.py` ~L45 |
| 5 | **Info** | Hardcoded 10k balance for risk % | `daily_report.py` ~L130 |

---

## Remaining Roadmap

| Item | Priority | Est. Effort | Notes |
|------|----------|-------------|-------|
| Fix gross_profit/gross_loss in objective() | P1 | 1h | Needs BlendBacktest to expose raw gross figures |
| Confidence gate tuning with historical data | P1 | 2-3h | Run optimizer on real backtest data, calibrate thresholds |
| ML feature pipeline enhancement | P2 | 4-6h | Confluence features from new pipeline data |
| Wire daily analytics into morning briefing cron | P2 | 1-2h | Add timezone fix, config-driven balance, alert thresholds |
| Clean up dead code (synthetic generator) | P3 | 15min | Delete `_generate_synthetic_signals()` |
| Consider log() vs sqrt() for trade count term | P3 | 1h | A/B on gaming vector effectiveness |
| Date parameter support in signal generation | P3 | 30min | Actually use start/end_date or remove params |

---

## Test Coverage Assessment

- **signal_provider.py:** 6 tests, good coverage of cache, determinism, filtering, empty states ✅
- **daily_report.py:** 6 tests, covers report generation, empty logs, win rate, per-strategy, confidence bucketing, formatting ✅
- **blend_optimizer.py:** No direct tests for `_compute_score()` — the circular profit_factor bug would have been caught by a unit test here.
- **Recommendation:** Add a `test_compute_score()` unit test with known inputs/outputs to the blend_optimizer test file.

---

*Mika — Risk Advisor, Ayumi*
