# Hybrid ICT/SMC + Quantitative Overlay Strategy — Walk-Forward Evaluation

**Paperclip:** AYUAA-221  
**Date:** 2026-04-04  
**Result:** **NO-GO**  
**Commit:** c0032df (walk-forward results), d476fa6 + f78481d (runner.py fixes)

## Executive Summary

The hybrid ICT/SMC + quantitative overlay strategy was evaluated against FTMO acceptance criteria using 5-window walk-forward validation on EURUSD and GBPUSD. **Both pairs FAIL** the evaluation — only 1/5 windows pass per pair against the required 3/5+ windows.

## FTMO Acceptance Criteria

| Criterion | Threshold |
|-----------|-----------|
| Win Rate | >55% |
| Profit Factor | >1.5 |
| Max Drawdown | <5% (FTMO 1-Step rule) |
| Sharpe Ratio | >0.5 |
| OOS Trades | 100+ |
| Profitable Windows | 3+ (out of 5) |

## Per-Window OOS Metrics

### EURUSD (139 total OOS trades)

| Window | OOS Period | Trades | WR% | PF | MaxDD% | Sharpe | Rejected |
|--------|------------|--------|------|-----|--------|--------|----------|
| 0 | Aug-Sep 2023 | 27 | 59.26 | 1.90 | 1.53 | 5.18 | 430 |
| 1 | Mar-Apr 2024 | 31 | 38.71 | 0.70 | 4.49 | -3.16 | 436 |
| 2 | Oct-Nov 2024 | 33 | 54.55 | 1.20 | 5.92 | 1.81 | 393 |
| 3 | May-Jun 2025 | 32 | 40.62 | 0.78 | 4.61 | -2.22 | 388 |
| 4 | Nov-Dec 2025 | 16 | 18.75 | 0.28 | 4.95 | -6.88 | 465 |

**Aggregates:** Mean WR=42.4%, Mean PF=0.97, Mean MaxDD=4.3%, Mean Sharpe=-1.05  
**Windows Passed:** 1/5 (Window 0 only)

### GBPUSD (107 total OOS trades)

| Window | OOS Period | Trades | WR% | PF | MaxDD% | Sharpe | Rejected |
|--------|------------|--------|------|-----|--------|--------|----------|
| 0 | Aug-Sep 2023 | 16 | 68.75 | 5.20 | 0.52 | 8.46 | 452 |
| 1 | Mar-Apr 2024 | 24 | 54.17 | 1.55 | 1.61 | 3.37 | 437 |
| 2 | Oct-Nov 2024 | 31 | 38.71 | 0.68 | 5.55 | -3.58 | 379 |
| 3 | May-Jun 2025 | 17 | 29.41 | 0.44 | 5.42 | -6.89 | 253 |
| 4 | Nov-Dec 2025 | 19 | 21.05 | 0.27 | 5.04 | -9.87 | 313 |

**Aggregates:** Mean WR=42.4%, Mean PF=1.63, Mean MaxDD=3.63%, Mean Sharpe=-1.70  
**Windows Passed:** 1/5 (Windows 0-1 only)

## FTMO Criteria vs Actual Results

| Criterion | Required | EURUSD | GBPUSD |
|-----------|----------|--------|--------|
| Win Rate | >55% | 42.4% ❌ | 42.4% ❌ |
| Profit Factor | >1.5 | 0.97 ❌ | 1.63 ✅ |
| Max Drawdown | <5% | 4.3% ✅ | 3.63% ✅ |
| Sharpe Ratio | >0.5 | -1.05 ❌ | -1.70 ❌ |
| OOS Trades | >100 | 139 ✅ | 107 ✅ |
| Profitable Windows | >3 | 1 ❌ | 1 ❌ |

**Result: 2/12 criteria passed (EURUSD: 1/6, GBPUSD: 3/6)**

## Filter Rejection Analysis

The quantitative filters rejected ~94% of signals:

| Pair | Total Evaluated | Passed | Rejected | Rejection Rate |
|------|-----------------|--------|----------|----------------|
| EURUSD | 1,612 | 139 | 1,473 | 94.2% |
| GBPUSD | 1,554 | 107 | 1,447 | 93.3% |

High rejection rates indicate the quant filters (ADX > 20, H4 alignment, ATR percentile > 30th) are very conservative. The strategy only generates signals when all confluence conditions are met.

## Critical Findings

1. **Win Rate Insufficient:** Both pairs average ~42% WR vs 55% required. The strategy wins less than half its trades.

2. **Sharpe Ratio Negative:** Mean Sharpe is deeply negative (-1.05 EURUSD, -1.70 GBPUSD), indicating returns are not compensating for volatility.

3. **Profitable Windows Below Threshold:** Only 1/5 windows profitable per pair vs 3+ required. Strategy performance is inconsistent across market conditions.

4. **High Variability:** Windows 2-4 show significant degradation compared to Windows 0-1, suggesting the strategy may be overfitting to specific market regimes.

## Recommendation

**NO-GO** — The hybrid strategy does not meet FTMO acceptance criteria for either EURUSD or GBPUSD.

### Required for Next Iteration

- Win rate must improve from ~42% to >55%
- Sharpe ratio must become positive and exceed 0.5
- At least 3 out of 5 windows must be profitable

### Potential Improvements

1. **Relax quant filters:** Current 94% rejection rate may be too conservative. Consider loosening ADX/ATR thresholds.

2. **ICT/SMC parameter tuning:** Order block and FVG detection parameters may need adjustment.

3. **H4 context weighting:** The H4 alignment filter may be misaligned with the H1 signal generation.

4. **Consider regime-adaptive approach:** Strategy performs well in specific market conditions (Windows 0-1) but poorly in others (Windows 2-4).

## Files

- Walk-forward results: `junior-dev-2/ayuua-220-walk-forward-results` branch, commit c0032df
- Runner.py fixes: `kai/main`, commits d476fa6 + f78481d

## Previous Evaluation Context

| Date | Commit | Result | Issue |
|------|--------|--------|-------|
| 2026-04-04 12:33 | 0d67592 | NO-GO | Buggy engine (MaxDD>5000%) |
| 2026-04-04 15:36 | c0032df | NO-GO | Valid results, strategy fails criteria |
