# LBO + 5-Strategy Blend — Walk-Forward Validation
**Date:** 2026-07-25T01:59:23+0000
**Symbol:** XAUUSD (M15 primary, H1 for Donchian)
**Verdict:** **FAIL** — Both LBO and blend fail walk-forward stability. Do not proceed to FTMO.

## Methodology

- 5 rolling OOS windows, each 30 days test period
- Windows evenly spaced across full ~4.5 year data span
- Strategies have fixed parameters (no optimization in train period)
- Train period (90 days) used for indicator warmup only
- Pass criterion per window: PF > 1.0 with ≥1 trade
- Aggregate pass: ≥80% windows (4/5)
- Monte Carlo: 10,000 bootstrap paths, FTMO criteria (10% max DD, 10% profit target)

## Walk-Forward Windows

| Window | Test Period |
|---|---|
| W1 | 2022-05-17 → 2022-06-30 |
| W2 | 2023-05-16 → 2023-06-29 |
| W3 | 2024-05-14 → 2024-06-27 |
| W4 | 2025-05-14 → 2025-06-27 |
| W5 | 2026-05-19 → 2026-07-13 |

## LBO Walk-Forward Results

| Window | Trades | PF | Net $ | DD % | WR % | Pass |
|---|---:|---:|---:|---:|---:|---|
| W1 | 3 | 1.0 | $0.0 | 0.5% | 66.7% | ❌ |
| W2 | 5 | 2.308 | $65.41 | 0.0% | 80.0% | ✅ |
| W3 | 1 | 0.0 | $-50.0 | 0.0% | 0.0% | ❌ |
| W4 | 0 | 0.0 | $0.0 | 0.0% | 0.0% | ❌ |
| W5 | 0 | 0.0 | $0.0 | 0.0% | 0.0% | ❌ |
| **TOTAL** | **9** | **1.103** | **$15.41** | **1.0%** | **66.7%** | |

**OOS Pass Rate:** 1/5 (20%)
**Verdict:** ❌ FAIL (<80%)

## 5-Strategy Blend Walk-Forward Results

**Blend:** Killzone Momentum + DualTF Squeeze Pro + Donchian ATR Trend + SRMR+ + LBO

| Window | Trades | PF | Net $ | DD % | WR % | Pass |
|---|---:|---:|---:|---:|---:|---|
| W1 | 26 | 0.312 | $-550.0 | 6.17% | 38.5% | ❌ |
| W2 | 6 | 1.154 | $15.41 | 0.5% | 66.7% | ✅ |
| W3 | 25 | 0.933 | $-33.33 | 2.5% | 60.0% | ❌ |
| W4 | 10 | 0.389 | $-183.33 | 1.33% | 40.0% | ❌ |
| W5 | 23 | 0.508 | $-344.46 | 4.0% | 39.1% | ❌ |
| **TOTAL** | **90** | **0.543** | **$-1095.72** | **10.62%** | **46.7%** | |

**OOS Pass Rate:** 1/5 (20%)
**Verdict:** ❌ FAIL (<80%)

## Monte Carlo Analysis (10,000 Bootstrap Paths)

### LBO — Full Period
Full period: 76 trades, PF=0.916, Net=$-125.03, DD=6.37%

| Metric | Value |
|---|---|
| FTMO Pass Rate (DD<10% AND profit≥10%) | 0.1% |
| DD Survival Rate (DD<10% only) | 98.2% |
| Profit Target Hit Rate (≥10% profit) | 0.1% |
| Median Max DD | 4.34% |
| 95th Percentile Max DD | 8.68% |
| Median Final PnL | $-124.2 |
| 5th Percentile PnL | $-723.68 |
| 95th Percentile PnL | $492.07 |

### 5-Strategy Blend — Full Period
Full period: 581 trades, PF=0.801, Net=$-2536.67, DD=31.78%

| Metric | Value |
|---|---|
| FTMO Pass Rate (DD<10% AND profit≥10%) | 0.0% |
| DD Survival Rate (DD<10% only) | 0.9% |
| Profit Target Hit Rate (≥10% profit) | 0.0% |
| Median Max DD | 28.49% |
| 95th Percentile Max DD | 44.04% |
| Median Final PnL | $-2525.04 |
| 5th Percentile PnL | $-4203.73 |
| 95th Percentile PnL | $-836.9 |

## Interpretation

### LBO Stability
LBO fails walk-forward with only 20% OOS pass rate. The PF=3.98 from full-period backtest is likely overstated — the edge may be period-specific.

### Blend Stability
The 5-strategy blend fails walk-forward with 20% OOS pass rate. One or more strategies may be drag rather than diversifier.

### Monte Carlo Risk
LBO Monte Carlo FTMO pass rate: 0.1%. Median max DD: 4.34%.
Blend Monte Carlo FTMO pass rate: 0.0%. Median max DD: 28.49%.

### Statistical Caveats
- LBO has 76 trades over 4.5 years (~16.9/year). Confidence intervals are wide at this sample size.
- Walk-forward with 5 windows reduces but does not eliminate overfit risk.
- Monte Carlo bootstrap assumes trades are i.i.d. — serial correlation is not modeled.
- FTMO pass rate is a necessary but not sufficient condition for live trading.

## Overall Verdict

**FAIL**

Both LBO and blend fail walk-forward stability. Do not proceed to FTMO.

**Acceptance Criteria:**
- [ ] LBO walk-forward pass rate ≥80%: 20%
- [ ] Blend walk-forward pass rate ≥80%: 20%
- [x] Per-window PF, trade count, DD reported
- [x] Monte Carlo 10,000 paths with FTMO pass rate
- [x] Outcome documented: FAIL
