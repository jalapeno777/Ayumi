# Strategy Factory Phase 0 — Regime Detector Validation

**Generated:** 2026-08-05T09:31:04.277582+00:00
**DuckDB:** `/home/TacoPants/projects/Ayumi/data/ayumi_market.duckdb`
**MTF mode:** `none`
**Detector config:** adx_period=14, atr_period=14, atr_lookback=50, trending_adx=25.0, choppy_adx=20.0, volatile_atr_pct=0.8, quiet_atr_pct=0.2, mtf_confirmation=none, h1_adx_threshold=22.0, h4_adx_threshold=20.0
**Warm-up bars skipped:** 64 (ADX needs 29, ATR percentile needs 64)
**Conceptual ground truth thresholds:** VOLATILE = realised-vol pctl > 0.80, TRENDING = rolling R² (close vs bar index, 50-bar lookback) upper tercile (> 0.6667). Both metrics are computed on the warm-up-sliced slice and are independent of the detector's ADX/ATR internals.
**Accuracy gate:** ≥70% on combined conceptual accuracy (avg of VOLATILE + TRENDING).

## Per-Event Summary

| # | Event | Symbol | Window | Bars (scored) | Conceptual Acc (VOL) | Conceptual Acc (TREND) | Combined | Pass |
|---|-------|--------|--------|---------------:|----------------------:|-----------------------:|---------:|:----:|
| 1 | 2020 COVID Crash | EURUSD | 2020-03-01 → 2020-04-15 | 2468 | 73.2% | 67.3% | 70.3% | ✅ |
| 2 | 2022 Fed Rate Shock | XAUUSD | 2022-06-01 → 2022-09-30 | 7854 | 59.0% | 67.3% | 63.2% | ❌ |
| 3 | 2023 SVB Collapse | XAUUSD | 2023-03-08 → 2023-04-15 | 2376 | 59.4% | 67.4% | 63.4% | ❌ |

## Per-Event Detail

### Event 1: 2020 COVID Crash

**Window:** 2020-03-01 → 2020-04-15 UTC
**Instrument:** EURUSD M15
**Description:** March 2020 COVID crash on EURUSD M15. Markets froze mid-March with extreme two-sided volatility followed by central-bank intervention. Expected: dominant VOLATILE regime as realised volatility spiked.

**Bars in window:** 2532 (warm-up skipped: 64, scored: 2468)

**Detector label distribution:**

| Regime | Count | Percentage |
|--------|------:|-----------:|
| trending | 422 | 17.1% |
| choppy | 348 | 14.1% |
| volatile | 755 | 30.6% |
| quiet | 943 | 38.2% |

**Confusion matrix — Implementation Consistency (VOLATILE):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |        755 |           0 |
| Det: False   |          0 |        1713 |
Accuracy: 100.0%

**Confusion matrix — Implementation Consistency (TRENDING):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |        422 |           0 |
| Det: False   |          0 |        2046 |
Accuracy: 100.0%

**Confusion matrix — Conceptual Accuracy (VOLATILE):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |        475 |         280 |
| Det: False   |        382 |        1331 |
Accuracy: 73.2%

**Confusion matrix — Conceptual Accuracy (TRENDING):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |        211 |         211 |
| Det: False   |        595 |        1451 |
Accuracy: 67.3%

**Combined conceptual accuracy:** 70.3% (average of VOLATILE + TRENDING conceptual accuracy)

**Expectations check:**

- ✅ `volatile` ≥ 20% (actual: 30.6% — Top 20 % volatility window for forex pair)

**Verdict:** PASS


### Event 2: 2022 Fed Rate Shock

**Window:** 2022-06-01 → 2022-09-30 UTC
**Instrument:** XAUUSD M15
**Description:** Jun–Sep 2022 aggressive Fed tightening cycle on XAUUSD M15. Gold entered a sustained downtrend as real yields rose, with elevated volatility around CPI/FOMC releases. Expected: mix of VOLATILE and TRENDING bars.

**Bars in window:** 7918 (warm-up skipped: 64, scored: 7854)

**Detector label distribution:**

| Regime | Count | Percentage |
|--------|------:|-----------:|
| trending | 1534 | 19.5% |
| choppy | 1099 | 14.0% |
| volatile | 2086 | 26.6% |
| quiet | 3135 | 39.9% |

**Confusion matrix — Implementation Consistency (VOLATILE):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |       2086 |           0 |
| Det: False   |          0 |        5768 |
Accuracy: 100.0%

**Confusion matrix — Implementation Consistency (TRENDING):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |       1534 |           0 |
| Det: False   |          0 |        6320 |
Accuracy: 100.0%

**Confusion matrix — Conceptual Accuracy (VOLATILE):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |        945 |        1141 |
| Det: False   |       2080 |        3688 |
Accuracy: 59.0%

**Confusion matrix — Conceptual Accuracy (TRENDING):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |        785 |         749 |
| Det: False   |       1817 |        4503 |
Accuracy: 67.3%

**Combined conceptual accuracy:** 63.2% (average of VOLATILE + TRENDING conceptual accuracy)

**Expectations check:**

- ✅ `volatile` ≥ 10% (actual: 26.6% — Elevated intraday volatility around FOMC)
- ❌ `trending` ≥ 20% (actual: 19.5% — Sustained downtrend in gold through summer)

**Verdict:** FAIL


### Event 3: 2023 SVB Collapse

**Window:** 2023-03-08 → 2023-04-15 UTC
**Instrument:** XAUUSD M15
**Description:** Mar 2023 Silicon Valley Bank collapse and US regional banking crisis on XAUUSD M15. Gold spiked on safe-haven flows with elevated volatility early and persistent trend behaviour after central-bank backstops. Expected: VOLATILE spike transitioning to TRENDING.

**Bars in window:** 2440 (warm-up skipped: 64, scored: 2376)

**Detector label distribution:**

| Regime | Count | Percentage |
|--------|------:|-----------:|
| trending | 551 | 23.2% |
| choppy | 273 | 11.5% |
| volatile | 674 | 28.4% |
| quiet | 878 | 37.0% |

**Confusion matrix — Implementation Consistency (VOLATILE):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |        674 |           0 |
| Det: False   |          0 |        1702 |
Accuracy: 100.0%

**Confusion matrix — Implementation Consistency (TRENDING):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |        551 |           0 |
| Det: False   |          0 |        1825 |
Accuracy: 100.0%

**Confusion matrix — Conceptual Accuracy (VOLATILE):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |        340 |         334 |
| Det: False   |        630 |        1072 |
Accuracy: 59.4%

**Confusion matrix — Conceptual Accuracy (TRENDING):**

|              | Truth: True | Truth: False |
|--------------|------------:|-------------:|
| Det: True    |        276 |         275 |
| Det: False   |        500 |        1325 |
Accuracy: 67.4%

**Combined conceptual accuracy:** 63.4% (average of VOLATILE + TRENDING conceptual accuracy)

**Expectations check:**

- ✅ `volatile` ≥ 10% (actual: 28.4% — Initial banking panic volatility)
- ✅ `trending` ≥ 20% (actual: 23.2% — Sustained safe-haven rally after backstop)

**Verdict:** FAIL

## Label Distribution Audit (full data range)

Each regime must cover ≥ 15% of post-warm-up bars. Failure here means the regime taxonomy is degenerate on that data.

| Symbol | Timeframe | Total bars | Trending | Choppy | Volatile | Quiet | Pass |
|--------|-----------|-----------:|---------:|-------:|---------:|------:|:----:|
| XAUUSD | M15 | 104380 | 21.9% | 16.9% | 24.7% | 36.5% | ✅ |
| EURUSD | M15 | 100798 | 14.5% | 11.3% | 33.8% | 40.4% | ❌ |

## Overall Verdict

- Events pass: ❌
- Distribution audit: ❌

**Result: FAIL** — regime detector did not meet the ≥70% conceptual accuracy gate or label-distribution minimum. STOP and surface to Ava/Craig per AC 0.2 (do not auto-tune; tuning on validation events is overfitting).
