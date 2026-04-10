# AYUAA-671: Parameter Sweep Aggregation Report

## Objective
Aggregate results from completed parameter sweeps into a ranked candidate list for walk-forward validation.

## Scope Status

| Task ID | Strategy | Status | Notes |
|---------|----------|--------|-------|
| AYUAA-491 | Keltner Channel Breakout | DONE | Walk-forward complete |
| AYUAA-495 | Momentum Breakout | PENDING | Walk-forward not yet run |
| AYUAA-592 | Optuna Optimization | IN_REVIEW | Not yet available |
| AYUAA-490 | Supertrend RSI | CANCELLED | Skipped |

## Source Data Files

| Strategy | Source File |
|----------|-------------|
| Keltner Channel Breakout | `reports/parameter_sweeps/combined_keltner_sweep.json` |
| Keltner Walk-Forward | `reports/walk_forward/keltner_sweep_walkforward_results.json` |
| Momentum Breakout | `reports/parameter_sweeps/combined_momentum_sweep.json` |
| Momentum Walk-Forward | `reports/walk_forward/momentum_sweep_walkforward_results.json` (NOT YET RUN) |
| Volatility Squeeze | `reports/parameter_sweeps/combined_volatility_squeeze_sweep.json` |
| Volatility Squeeze Walk-Forward | `reports/walk_forward/volatility_squeeze_sweep_walkforward_results.json` |

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

**Recommended Walk-Forward Window Config:** 5-window, 70% train / 30% test split (train_ratio=0.7)

---

### 2. Momentum Breakout — EURUSD (PENDING WALK-FORWARD)

**Note:** In-sample results show promise, but walk-forward validation has not been completed. The reported walk-forward NO-GO verdict is unverifiable without the results file.

**Top In-Sample Parameters:**
| Parameter | Value |
|-----------|-------|
| adx_threshold | 30.0 |
| atr_multiplier | 2.0 |
| fast_period | 5 |
| slow_period | 50 |

**In-Sample Metrics:**
| Metric | Value | Source |
|--------|-------|--------|
| Win Rate | 76.9% | combined_momentum_sweep.json (EURUSD, adx=30, atr_mult=2.0, fast=5, slow=50) |
| Profit Factor | 3.95 | combined_momentum_sweep.json |
| Max Drawdown | 1.07% | combined_momentum_sweep.json |
| Sharpe Ratio | +0.68 | combined_momentum_sweep.json |
| Trade Count | 13 | combined_momentum_sweep.json |

**Walk-Forward Status:** `reports/walk_forward/momentum_sweep_walkforward_results.json` does not exist. Walk-forward must be completed before GO/NO-GO determination.

**Recommendation:** Run momentum walk-forward before final evaluation.

---

### 3. Volatility Squeeze — Both Pairs (NO-GO)

**Note:** Walk-forward validation failed. All parameter combinations returned NO-GO for both GBPJPY and EURUSD.

**Recommendation:** Do not proceed to walk-forward validation.

---

## Summary

| Rank | Strategy | Pair | WF Verdict | Recommendation |
|------|----------|------|------------|----------------|
| 1 | Keltner Channel Breakout | EURUSD | GO (2/5 windows) | Proceed to WF validation |
| 2 | Momentum Breakout | EURUSD | PENDING | Walk-forward not yet run |
| 3 | Volatility Squeeze | GBPJPY/EURUSD | NO-GO | Do not proceed |

**AYUAA-592 (Optuna Optimization):** Results pending. Will update this report when available.

---

## Deliverable Status
- [x] Ranked table compiled
- [ ] Top candidates sent for walk-forward validation
- [ ] AYUAA-592 Optuna results to be added when available
- [ ] Momentum walk-forward must be run before final ranking

**Report Generated:** 2026-04-08
**Last Updated:** 2026-04-09
**Next Steps:**
1. Run momentum walk-forward (`scripts/run_momentum_sweep_walkforward.py`) and update report
2. Await AYUAA-592 Optuna results
3. Finalize ranked candidate list for walk-forward validation

---

## Revision Notes (2026-04-09)

This report has been revised to address engineering review feedback:
1. **Train/test split corrected:** 70% train / 30% test (was incorrectly stated as 20%/80%)
2. **Momentum metrics verified:** Corrected top in-sample parameters and metrics from `combined_momentum_sweep.json`
3. **Momentum walk-forward status:** Flagged as PENDING - no walk-forward results file exists
4. **Source data files added:** Table of source files added for auditability
5. **Q7 files note:** AYUAA-648 Q7 backtest files belong on `junior-dev-1/AYUAA-648-q7-multi-session-mw` branch
