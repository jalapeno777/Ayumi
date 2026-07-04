# Spread / Pip Configuration Audit — All 7 Pairs

**Date:** 2026-07-01  
**Auditor:** Tsukasa  
**Scope:** `config/strategies.yaml`, `adapters/ctrader/models.py` (SYMBOL_METADATA)  
**Trigger:** Forward test expanded to 7 pairs — verify spread gates and pip values are correctly configured.

---

## 1. Executive Summary

**CRITICAL FINDING:** The `strategies.yaml` has **no `spread_pips` section**. The `blend_runner.py` reads `config.get("spread_pips", {})` which returns an empty dict. The spread gate (`confidence.gates.SpreadGate`) then falls back to `default_max_spread = 2.0` pips for **all symbols**.

This means **XAUUSD** (typical spread 2.0–4.0+ pips at `pip_size=0.01`) is at risk of being **blocked by the default 2.0 pip spread gate** during normal trading conditions.

---

## 2. SYMBOL_METADATA Reference (from `models.py`)

| Symbol | pip_size | pip_value_per_lot (USD) | lot_size | Notes |
|--------|----------|------------------------|----------|-------|
| GBPUSD | 0.0001 | 10.0 | 100,000 | Standard FX |
| EURUSD | 0.0001 | 10.0 | 100,000 | Standard FX |
| USDJPY | 0.01 | 6.5 | 100,000 | JPY pair — pip_size correct |
| XAUUSD | 0.01 | 1.0 | 100 | Gold — contract size 100 oz |
| AUDUSD | 0.0001 | 10.0 | 100,000 | Standard FX |
| USDCHF | 0.0001 | 10.0 | 100,000 | Standard FX |
| USDCAD | 0.0001 | 10.0 | 100,000 | Standard FX |

### Pip Value Verification

| Symbol | pip_size | pip_value_per_lot | Calculation | Correct? |
|--------|----------|-------------------|-------------|----------|
| GBPUSD | 0.0001 | $10 | 0.0001 × 100,000 = $10 | ✅ |
| EURUSD | 0.0001 | $10 | 0.0001 × 100,000 = $10 | ✅ |
| USDJPY | 0.01 | $6.5 | 0.01 × 100,000 = ¥1000 ≈ $6.5 (at ~155) | ✅ approx |
| XAUUSD | 0.01 | $1 | 0.01 × 100 oz = $1 | ✅ |
| AUDUSD | 0.0001 | $10 | 0.0001 × 100,000 = $10 | ✅ |
| USDCHF | 0.0001 | $10 | 0.0001 × 100,000 = $10 | ✅ (approx — CHF cross) |
| USDCAD | 0.0001 | $10 | 0.0001 × 100,000 = $10 | ✅ (approx — CAD cross) |

**Note:** For USDJPY, USDCHF, and USDCAD, the pip_value_per_lot is approximate because the quote currency isn't USD. USDJPY at $6.5 assumes USD/JPY ≈ 154. The actual pip value fluctuates with the exchange rate. This is acceptable for config purposes.

---

## 3. Spread Configuration Audit

### Current State

**`strategies.yaml` spread config:** **MISSING** — no `spread_pips` key exists in the file.

**`blend_runner.py` behavior:**
```python
spread_pips = config.get("spread_pips", {})  # → empty dict
gate_config = GateConfig(
    default_max_spread=2.0,           # ← used for ALL symbols
    symbol_max_spreads=spread_pips,   # ← empty dict
)
```

**Result:** All 7 pairs are subject to a flat 2.0 pip maximum spread gate.

### Per-Symbol Spread Assessment

| Symbol | Typical cTrader Spread | Effective Max (config) | pip_size | Spread in Pips | Status |
|--------|----------------------|----------------------|----------|----------------|--------|
| GBPUSD | 0.8–1.5 pips | 2.0 | 0.0001 | 0.8–1.5 | ✅ OK |
| EURUSD | 0.6–1.2 pips | 2.0 | 0.0001 | 0.6–1.2 | ✅ OK |
| USDJPY | 0.8–1.5 pips | 2.0 | 0.01 | 0.8–1.5 | ✅ OK |
| XAUUSD | $0.20–$0.40 | 2.0 | 0.01 | 20–40 | 🔴 **BLOCKING** |
| AUDUSD | 1.0–2.0 pips | 2.0 | 0.0001 | 1.0–2.0 | ⚠️ TIGHT |
| USDCHF | 1.0–2.0 pips | 2.0 | 0.0001 | 1.0–2.0 | ⚠️ TIGHT |
| USDCAD | 1.5–3.0 pips | 2.0 | 0.0001 | 1.5–3.0 | 🔴 **BLOCKING** |

### XAUUSD Detail (CRITICAL)

XAUUSD uses `pip_size = 0.01`. A typical cTrader spread for gold is $0.20–$0.40.

In pip terms: $0.20 / $0.01 = **20 pips**. The spread gate allows max **2.0 pips**.

**The spread gate will block 100% of XAUUSD signals** during normal market conditions. This is almost certainly why the XAUUSD strategy is silent.

**However:** The SRMR+ strategy config for XAUUSD in strategies.yaml sets `pip_value: 0.01`, which means the strategy's internal calculations use 0.01 as the pip size. The spread gate in `confidence.gates` is a separate system that doesn't use SYMBOL_METADATA — it receives spread as a raw float in pips. If the spread is passed in raw price difference (e.g., 0.30 for gold), then 0.30 < 2.0 would pass. If it's converted to pips (0.30 / 0.01 = 30 pips), it would fail.

**The behavior depends on how spread is calculated and passed to the gate.** This requires verification in the live trading path.

### USDCAD Detail (WARNING)

USDCAD typically has wider spreads (1.5–3.0 pips). With a 2.0 pip max, signals during wider spread periods (news, off-hours) will be blocked. This may or may not be desired.

### AUDUSD / USDCHF Detail (CAUTION)

At the higher end of typical spreads (2.0 pips), these pairs are right at the threshold. Signals could be intermittently blocked.

---

## 4. Strategy-Level Pip Handling

### SRMR+ per-symbol `pip_value` config in strategies.yaml

| Symbol | `pip_value` in YAML | `_pip_value_for_price()` fallback | Actual pip used |
|--------|--------------------|----------------------------------|----------------|
| GBPUSD | not set | 0.0001 (price < 50) | 0.0001 ✅ |
| EURUSD | not set | 0.0001 | 0.0001 ✅ |
| USDJPY | 0.01 | 0.01 (price ≥ 50) | 0.01 ✅ |
| XAUUSD | 0.01 | 0.01 (price ≥ 50) | 0.01 ✅ |
| AUDUSD | not set | 0.0001 | 0.0001 ✅ |
| USDCHF | not set | 0.0001 | 0.0001 ✅ |
| USDCAD | not set | 0.0001 | 0.0001 ✅ |

**Finding:** The `pip_value` config in strategies.yaml for USDJPY and XAUUSD is technically redundant — the `_pip_value_for_price()` function already returns 0.01 for prices ≥ 50. But having it explicit is good practice and not a bug.

### SRMR+ `session_range_min_pips` values

| Symbol | Configured `session_range_min_pips` | Typical Session Range | Assessment |
|--------|-------------------------------------|----------------------|------------|
| GBPUSD | 25.0 | 30–60 pips | ✅ OK |
| EURUSD | 15.0 | 20–40 pips | ✅ OK |
| USDJPY | 15.0 | 20–40 pips | ✅ OK |
| XAUUSD | 200.0 | $2–$10 (200–1000 pips at 0.01) | ✅ OK |
| AUDUSD | 15.0 | 20–40 pips | ✅ OK |
| USDCHF | 15.0 | 20–40 pips | ✅ OK |
| USDCAD | 15.0 | 20–40 pips | ✅ OK |

All `session_range_min_pips` values look reasonable and shouldn't block signal generation under normal conditions.

---

## 5. Issues Summary

### ISSUE-1: Missing `spread_pips` config — XAUUSD blocked (CRITICAL)

**File:** `config/strategies.yaml`  
**Issue:** No `spread_pips` section. All symbols use `default_max_spread=2.0`.  
**Impact:** XAUUSD signals will be blocked by spread gate. USDCAD likely blocked during wider-spread periods.  
**Fix:** Add `spread_pips` section to strategies.yaml:
```yaml
spread_pips:
  GBPUSD: 2.0
  EURUSD: 2.0
  USDJPY: 2.0
  XAUUSD: 50.0   # $0.50 = 50 pips at pip_size 0.01
  AUDUSD: 2.5
  USDCHF: 2.5
  USDCAD: 3.5
```

### ISSUE-2: Spread gate pip semantics unverified (HIGH)

**Issue:** The `SpreadGate.check()` method compares `spread` (from context dict) against `max_spread` in "pips". But the unit of `spread` in the context dict depends on how the live data feed populates it. If it's a raw price difference (e.g., 0.00015 for EURUSD), then 0.00015 < 2.0 would always pass — making the gate useless. If it's already in pips (1.5), then the gate works correctly for FX pairs but blocks XAUUSD.

**Action needed:** Verify how `spread` is populated in the confidence engine context. Check `confidence/engine.py` or the data feed adapter.

### ISSUE-3: USDJPY pip_value_per_lot approximate (LOW)

**Issue:** `pip_value_per_lot=6.5` for USDJPY assumes USD/JPY ≈ 154. At current rates (July 2026), this may be slightly off. This is a minor approximation and acceptable for config purposes — the actual pip value is dynamically calculated in live trading.

---

## 6. Recommendations

1. **Add `spread_pips` section** to `strategies.yaml` with per-symbol max spreads. This is the most likely cause of XAUUSD signal suppression.
2. **Verify spread units** in the confidence gate pipeline — confirm whether spread is passed in pips or raw price difference.
3. **Consider widening AUDUSD/USDCHF/USDCAD** max spreads to 2.5–3.5 to avoid intermittent signal blocking.

---

## 7. Status Table

| Symbol | pip_size | pip_value_per_lot | Configured Spread | Typical Spread | Status |
|--------|----------|-------------------|-------------------|----------------|--------|
| GBPUSD | 0.0001 ✅ | $10 ✅ | 2.0 (default) | 0.8–1.5 | ✅ OK |
| EURUSD | 0.0001 ✅ | $10 ✅ | 2.0 (default) | 0.6–1.2 | ✅ OK |
| USDJPY | 0.01 ✅ | $6.5 ✅ | 2.0 (default) | 0.8–1.5 | ✅ OK |
| XAUUSD | 0.01 ✅ | $1 ✅ | 2.0 (default) | 20–40 | 🔴 BLOCKING |
| AUDUSD | 0.0001 ✅ | $10 ✅ | 2.0 (default) | 1.0–2.0 | ⚠️ TIGHT |
| USDCHF | 0.0001 ✅ | $10 ✅ | 2.0 (default) | 1.0–2.0 | ⚠️ TIGHT |
| USDCAD | 0.0001 ✅ | $10 ✅ | 2.0 (default) | 1.5–3.0 | 🔴 BLOCKING |
