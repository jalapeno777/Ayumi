# AYUAA-671: Parameter Sweep Aggregation Report

## Objective
Aggregate results from completed parameter sweeps into a ranked candidate list for walk-forward validation.

## Scope Status

| Task ID | Strategy | Status | Notes |
|---------|----------|--------|-------|
| AYUAA-491 | Keltner Channel Breakout | DONE | Walk-forward complete |
| AYUAA-495 | Momentum Breakout | DONE | Walk-forward complete |
| AYUAA-592 | Optuna Optimization | IN_REVIEW | Not yet available |
| AYUAA-490 | Supertrend RSI | CANCELLED | Skipped |

---

## Ranked Candidates for Walk-Forward Validation

### 1. Keltner Channel Breakout — EURUSD (GO)

**Parameters:**
| Parameter | Value |
|-----------|-------|
| adx_threshold | 30.0 |
| atr_multiplier | 2.0 |
| atr_period | 10 |
| ema_period | 10 |
| sl_atr_multiplier | 1.5 |
| volume_ma_period | 20 |

**In-Sample Metrics (5-Window Walk-Forward Aggregated):**
| Metric | Value |
|--------|-------|
| Mean Win Rate | 42.0% |
| Mean Profit Factor | 1.06 |
| Mean Max Drawdown | 1.37% |
| Mean Sharpe Ratio | -104.15 (high variance) |
| Trade Count (avg) | 3.0 |
| Windows Passed | 2/5 |

**Walk-Forward Window Details:**
| Window | Win Rate | Profit Factor | Max DD | Sharpe | Passed |
|--------|----------|---------------|--------|--------|--------|
| 0 | 33.3% | 0.50 | 1.17% | -4.52 | NO |
| 1 | 66.7% | 2.00 | 1.20% | +4.58 | YES |
| 2 | 0.0% | 0.00 | 2.31% | -525.26 | NO |
| 3 | 60.0% | 1.68 | 1.09% | +3.74 | YES |
| 4 | 50.0% | 1.14 | 1.08% | +0.71 | NO |

**Recommended Walk-Forward Window Config:** 5-window, 20% train/80% test split

---

### 2. Momentum Breakout — EURUSD (NO-GO)

**Note:** Walk-forward validation failed. Both GBPJPY and EURUSD returned NO-GO verdicts with very low win rates (10-20%) and poor profit factors (<0.2).

**Top In-Sample Parameters (Not Recommended for WF):**
| Parameter | Value |
|-----------|-------|
| adx_threshold | 20.0 |
| atr_multiplier | 2.0 |
| fast_period | 5 |
| slow_period | 18 |

**In-Sample Metrics:**
| Metric | Value |
|--------|-------|
| Win Rate | 51.6% |
| Profit Factor | 0.97 |
| Max Drawdown | 5.39% |
| Sharpe Ratio | +0.55 |
| Trade Count | 62 |

**Recommendation:** Do not proceed to walk-forward validation until strategy logic is reviewed.

---

### 3. Volatility Squeeze — Both Pairs (NO-GO)

**Note:** Walk-forward validation failed. All parameter combinations returned NO-GO for both GBPJPY and EURUSD.

**Recommendation:** Do not proceed to walk-forward validation.

---

## Summary

| Rank | Strategy | Pair | WF Verdict | Recommendation |
|------|----------|------|------------|----------------|
| 1 | Keltner Channel Breakout | EURUSD | GO (2/5 windows) | Proceed to WF validation |
| 2 | Momentum Breakout | EURUSD | NO-GO | Review strategy logic first |
| 3 | Volatility Squeeze | GBPJPY/EURUSD | NO-GO | Do not proceed |

**AYUAA-592 (Optuna Optimization):** Results pending. Will update this report when available.

---

## Deliverable Status
- [x] Ranked table compiled
- [ ] Top candidates sent for walk-forward validation
- [ ] AYUAA-592 Optuna results to be added when available

**Report Generated:** 2026-04-08
**Next Step:** Move top candidate (Keltner/EURUSD) to walk-forward validation phase
