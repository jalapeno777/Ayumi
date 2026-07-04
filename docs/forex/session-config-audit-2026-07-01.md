# Session / Kill-Zone Configuration Audit

**Date:** 2026-07-01  
**Auditor:** Tsukasa  
**Scope:** `config/sessions.py`, `strategies/session_range_mean_reversion.py`, `strategies/srmr_plus.py`  
**Trigger:** Forward test started at 14:55 UTC (NY session) — strategies appear silent.

---

## 1. Session Definitions (from `config/sessions.py`)

All times are **UTC**.

### KillzoneHours

| Session | Start (UTC) | End (UTC) |
|---------|-------------|-----------|
| London Open | 07:00 | 09:00 |
| NY Open | 12:00 | 14:00 |
| Overlap | 13:00 | 16:00 |

### SessionRangeHours

| Session | Start (UTC) | End (UTC) |
|---------|-------------|-----------|
| Asian | 00:00 | 07:00 |
| Early London End | — | 09:00 |
| London | 07:00 | 11:00 |
| NY AM | 12:00 | 15:00 |
| London/NY Overlap | 12:00 | 16:00 |
| NY Close | 16:00 | 20:00 |

### DEFAULT_KILLZONES

Tuples derived from `KillzoneHours`:
- London Open: 07:00–09:00
- NY Open: 12:00–14:00
- Overlap: 13:00–16:00

### DEFAULT_PREFERRED_SESSIONS

`{"london", "ny_am"}`

---

## 2. Per-Strategy Session Filtering

### SRMR+ (`srmr_plus.py`)

**Function:** `_is_trading_session(bar_time)` — checks `utc_hour`

**Active windows:**

| Window | Hours (UTC) | Session Reference |
|--------|-------------|-------------------|
| London | 07:00–11:00 | `_LONDON_START` to `_LONDON_END` |
| NY AM | 12:00–15:00 | `_NY_OPEN_START` to `_NY_OPEN_END` |
| Overlap | 12:00–16:00 | `_LONDON_NY_OVERLAP_START` to `_LONDON_NY_OVERLAP_END` |

**Effective active window:** 07:00–16:00 UTC (London + NY AM + Overlap)

**Session classification** (`_get_bar_session_type`):
- 07:00–11:00 → `LONDON`
- 12:00–16:00 → `NY_AM` (NY AM and Overlap both map here)
- 16:00–20:00 → `NY_PM`
- Everything else → `OUTSIDE`

**Additional filters before signal generation:**
1. Minimum bar count (ATR + RSI + ADX + EMA periods)
2. Session range from previous day must exist and be ≥ `session_range_min_pips`
3. ADX must be ≤ `adx_max_threshold` (default 25.0)
4. ATR must be > 0
5. RSI must cross long/short thresholds
6. Price must be near session extremes (within `entry_near_extreme_pips`)

**Verdict:** SRMR+ **IS active at 14:55 UTC** (within NY AM / Overlap window). The strategy should be evaluating signals. If no signals are produced, one of the additional filters (ADX, RSI, range width, price-at-extreme) is the likely cause — NOT a session window issue.

### SessionRangeMeanReversion (`session_range_mean_reversion.py`)

**Function:** `_is_in_asian_or_early_london(state)` + `_is_in_london_ny_overlap(state)` exclusion

**Active window:** 00:00–09:00 UTC (Asian 00–07 + London 07–09)

**Exclusion:** London/NY Overlap (12:00–16:00) is explicitly excluded.

**Additional filters:**
1. Minimum bar count
2. Previous day session range ≥ `session_range_min_pips` (default 25.0)
3. RSI thresholds
4. Price near session extremes
5. Session range width check

**Verdict:** SessionRangeMeanReversion is **NOT active at 14:55 UTC**. It only operates during Asian/Early London (00:00–09:00). This is by design — it's a mean-reversion strategy targeting the Asian/early-London consolidation.

---

## 3. Kill-Zone Penalties Per Symbol

**Finding: No per-symbol kill-zone penalty values exist in `strategies.yaml`.**

The concept of "kill-zone penalties" does not appear in the forward test configuration. The `strategies.yaml` file contains strategy definitions with parameters like `session_range_min_pips`, `hard_cap_sl_pips`, and `tp1_rr` — but no kill-zone penalty section.

The kill-zone concept appears in two other code paths:

### `signal_validator.py` (legacy validator)

- `ValidatorConfig.require_killzone = True` (default)
- `_KILLZONE_SESSIONS = {Session.LONDON, Session.NY_AM, Session.NY_PM}`
- If `require_killzone=True` and the signal's session is NOT in the killzone set, the signal is **rejected**.
- `confluence_score()` gives a `killzone_bonus = 0.2` boost for killzone sessions.

**Usage in forward test pipeline:** Unknown — the forward test uses `blend_runner.py` → `confidence.gates`, not `signal_validator.py` directly. The validator appears to be a legacy path.

### `confidence/gates.py` — SessionGate

The `GateConfig` has its own session hour definitions that **do not match** `sessions.py`:

| Session | GateConfig Hours | sessions.py Hours |
|---------|------------------|-------------------|
| London | 08:00–17:00 | 07:00–11:00 |
| NY | 13:00–22:00 | 12:00–16:00 |
| Asia | 00:00–08:00 | 00:00–07:00 |

**This is a discrepancy** — the gate uses wider session windows than the strategy definitions.

---

## 4. Cross-Reference: Why Strategies May Be Silent

Given the forward test started at 14:55 UTC:

| Check | Result |
|-------|--------|
| Session window | ✅ SRMR+ is active (07:00–16:00 UTC) |
| Killzone filter | ⚠️ See below |
| ADX filter | Possible suppression if ADX > 25.0 |
| RSI thresholds | Possible — needs price near extremes with RSI confirmation |
| Session range min pips | Possible — if previous session was narrow |
| Spread gate | See spread-pip audit (separate report) |

**Killzone filter risk:** The `blend_runner.py` pipeline uses `confidence.gates.GateConfig` with a `SessionGate`. If the gate's session hours (london 8-17, ny 13-22) are used to filter signals, then 14:55 UTC falls within the NY window (13-22) and should pass. However, the mismatch between GateConfig hours and sessions.py hours is a configuration smell.

**Most likely cause of silence:** The SRMR+ strategy has six conditional filters beyond the session window. Any single one rejecting will produce no signal. The forward test should check the strategy logs (INFO level) for specific rejection reasons. The SRMR+ code has `logger.info()` and `logger.debug()` calls for each rejection path.

---

## 5. Anomalies Found

### ANOMALY-1: GateConfig session hours mismatch (MEDIUM)

**Location:** `confidence/gates.py` → `GateConfig`  
**Issue:** London 08:00–17:00 vs sessions.py 07:00–11:00. NY 13:00–22:00 vs sessions.py 12:00–16:00. These definitions serve different purposes (gate = broad session filter, sessions.py = strategy-specific windows) but the naming overlap is confusing and could cause misconfiguration.  
**Risk:** If a signal is generated at 10:30 UTC (London per sessions.py), the gate's London window (08-17) would pass it — wider than the strategy's own window (07-11). Not a bug per se, but a maintenance hazard.

### ANOMALY-2: `require_killzone=True` default in SignalValidator (LOW)

**Location:** `signal_validator.py` → `ValidatorConfig`  
**Issue:** If this validator is ever used in the pipeline with default config, it will reject any signal not tagged as LONDON, NY_AM, or NY_PM.  
**Risk:** Low — the forward test uses `confidence.gates`, not `signal_validator.py`. But if someone wires the validator into the pipeline, signals from the Asian session would be silently dropped.

### ANOMALY-3: No per-symbol session configuration (LOW)

**Issue:** All 7 pairs use the same session windows. XAUUSD (gold) has different liquidity profiles than FX pairs — it tends to be most active during NY/Overlap, less so during London open. There's no per-symbol session customization.

### ANOMALY-4: SessionRangeMeanReversion references EARLY_LONDON_END but London session ends at 11:00 (INFO)

**Location:** `session_range_mean_reversion.py` line ~39  
**Issue:** `_EARLY_LONDON_END = SessionRangeHours.EARLY_LONDON_END` = 09:00. The function `_is_in_asian_or_early_london` accepts hours 00:00–09:00 (Asian 0-7, London 7-9). But the full London session runs 07:00–11:00. The strategy only uses "early London" (07-09), not the full session. This is intentional but worth documenting.

---

## 6. Recommendations

1. **Add logging diagnostics:** The SRMR+ strategy already has INFO/DEBUG logging for each rejection path. Verify the forward test captures these logs to diagnose why no signals are produced.
2. **Reconcile session definitions:** Consider unifying GateConfig and sessions.py hour definitions, or add documentation explaining why they differ.
3. **No kill-zone penalty fix needed:** The concept doesn't exist as "penalties per symbol" in the config. The actual filtering is via ADX, RSI, range-width, and spread gates.

---

## 7. Summary

| Question | Answer |
|----------|--------|
| Are strategies evaluating during correct session windows? | ✅ Yes — SRMR+ active 07:00–16:00 UTC, SessionRangeMR active 00:00–09:00 UTC |
| Are kill-zone penalties suppressing all signals? | ❌ No — no per-symbol kill-zone penalties exist in config |
| Why might the forward test be silent at 14:55 UTC? | SRMR+ is active but one of: ADX too high, RSI not at extreme, range too narrow, or price not near session extreme. Check strategy logs. |
| Any blocking issues? | No blocking session/kill-zone config issues found |
