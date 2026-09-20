# Strategy Factory Phase 0 — ATR Sensitivity Sweep

**Generated:** 2026-08-05T09:31:49.129034+00:00
**DuckDB:** `$AYUMI_ROOT/data/ayumi_market.duckdb`
**MTF mode:** `hard`
**⚠️ Diagnostic only** — this sweep does **not** modify the ≥70% validation gate.  Its purpose is to surface how combined conceptual accuracy moves with ``volatile_atr_pct`` so Rin / Ava can spot threshold sensitivities without re-running the factory dispatch.  Tuning on validation events is forbidden by AC 0.2 (overfitting).

**Thresholds swept:** 0.70, 0.75, 0.80, 0.85

## Combined Conceptual Accuracy vs. `volatile_atr_pct`

| `volatile_atr_pct` | 2020 COVID Crash | 2022 Fed Rate Shock | 2023 SVB Collapse | Mean |
|---:|:---:|:---:|:---:|---:|
| 0.70 | 71.2% | 64.0% | 64.8% | 66.6% |
| 0.75 | 71.2% | 63.8% | 64.3% | 66.4% |
| 0.80 | 70.9% | 63.7% | 64.1% | 66.2% |
| 0.85 | 70.6% | 63.7% | 64.4% | 66.2% |

## Per-Event Detail by Threshold

### Event 1: 2020 COVID Crash

**Window:** 2020-03-01 → 2020-04-15 UTC (EURUSD M15)

| `volatile_atr_pct` | Volatile acc | Trending acc | Combined | Pass |
|---:|---:|---:|---:|:---:|
| 0.70 | 74.3% | 68.0% | 71.2% | ✅ |
| 0.75 | 73.8% | 68.5% | 71.2% | ✅ |
| 0.80 | 73.2% | 68.6% | 70.9% | ✅ |
| 0.85 | 72.3% | 68.8% | 70.6% | ✅ |


### Event 2: 2022 Fed Rate Shock

**Window:** 2022-06-01 → 2022-09-30 UTC (XAUUSD M15)

| `volatile_atr_pct` | Volatile acc | Trending acc | Combined | Pass |
|---:|---:|---:|---:|:---:|
| 0.70 | 59.5% | 68.5% | 64.0% | ❌ |
| 0.75 | 59.1% | 68.5% | 63.8% | ❌ |
| 0.80 | 59.0% | 68.5% | 63.7% | ❌ |
| 0.85 | 59.2% | 68.3% | 63.7% | ❌ |


### Event 3: 2023 SVB Collapse

**Window:** 2023-03-08 → 2023-04-15 UTC (XAUUSD M15)

| `volatile_atr_pct` | Volatile acc | Trending acc | Combined | Pass |
|---:|---:|---:|---:|:---:|
| 0.70 | 60.8% | 68.7% | 64.8% | ❌ |
| 0.75 | 60.3% | 68.4% | 64.3% | ❌ |
| 0.80 | 59.4% | 68.8% | 64.1% | ❌ |
| 0.85 | 59.9% | 68.8% | 64.4% | ❌ |
