# Bootstrap Confidence Intervals — 2026-07-13

**Source:** metrics_summary JOIN runs (per-run aggregates; per-window fallback when windows table is non-empty)
**Database:** `/home/TacoPants/projects/Ayumi/data/research/research.duckdb`
**Iterations:** 10,000 (seed=42)
**Confidence level:** 95% (percentile method)
**Kill threshold:** lower PF CI < 1.0

## Summary

- **SURVIVE:** 0
- **WATCH:** 0
- **KILL:** 8

## Per-strategy 95% Confidence Intervals

Columns: `point` = observed mean across bootstrap samples; `lo` / `hi` = 2.5% / 97.5% percentile of the bootstrap distribution of the metric mean; `n` = number of underlying observations (runs when per-window data is empty, windows otherwise); `path` = which data the bootstrap drew from.

| Strategy | Metric | Point | 95% CI low | 95% CI high | n | Bootstrap path |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| ttc_xauusd | Profit Factor | 1.239 | 0.000 | 2.254 | 3 | run-level |
| ttc_xauusd | Sharpe | 2.242 | 0.000 | 5.043 | 3 | run-level |
| ttc_xauusd | Win Rate | 0.309 | 0.000 | 0.473 | 3 | run-level |
| ttc_xauusd | Max Drawdown | 0.010 | 0.002 | 0.020 | 3 | run-level |
| bb_rsi_reversion | Profit Factor | 0.956 | 0.099 | 2.193 | 9 | run-level |
| bb_rsi_reversion | Sharpe | -32.457 | -86.147 | 10.193 | 9 | run-level |
| bb_rsi_reversion | Win Rate | 0.179 | 0.082 | 0.290 | 9 | run-level |
| bb_rsi_reversion | Max Drawdown | 0.017 | 0.009 | 0.027 | 9 | run-level |
| killzone_momentum | Profit Factor | 0.750 | 0.306 | 1.269 | 9 | run-level |
| killzone_momentum | Sharpe | -17.450 | -34.766 | -5.823 | 9 | run-level |
| killzone_momentum | Win Rate | 0.254 | 0.176 | 0.322 | 9 | run-level |
| killzone_momentum | Max Drawdown | 0.032 | 0.020 | 0.045 | 9 | run-level |
| london_breakout_retest | Profit Factor | 0.496 | 0.034 | 1.387 | 9 | run-level |
| london_breakout_retest | Sharpe | -303.490 | -743.388 | -4.364 | 9 | run-level |
| london_breakout_retest | Win Rate | 0.110 | 0.039 | 0.199 | 9 | run-level |
| london_breakout_retest | Max Drawdown | 0.014 | 0.007 | 0.023 | 9 | run-level |
| srmr_plus | Profit Factor | 0.358 | 0.161 | 0.559 | 6 | run-level |
| srmr_plus | Sharpe | -111.123 | -266.148 | -12.264 | 6 | run-level |
| srmr_plus | Win Rate | 0.155 | 0.116 | 0.189 | 6 | run-level |
| srmr_plus | Max Drawdown | 0.064 | 0.056 | 0.075 | 6 | run-level |
| donchian_atr_trend | Profit Factor | 0.090 | 0.054 | 0.124 | 9 | run-level |
| donchian_atr_trend | Sharpe | -331.029 | -952.313 | -17.499 | 9 | run-level |
| donchian_atr_trend | Win Rate | 0.150 | 0.102 | 0.191 | 9 | run-level |
| donchian_atr_trend | Max Drawdown | 0.057 | 0.056 | 0.058 | 9 | run-level |
| volatility_regime_breakout | Profit Factor | 0.000 | 0.000 | 0.000 | 9 | run-level |
| volatility_regime_breakout | Sharpe | 0.000 | 0.000 | 0.000 | 9 | run-level |
| volatility_regime_breakout | Win Rate | 0.000 | 0.000 | 0.000 | 9 | run-level |
| volatility_regime_breakout | Max Drawdown | 0.000 | 0.000 | 0.000 | 9 | run-level |
| volatility_squeeze | Profit Factor | 0.000 | 0.000 | 0.000 | 9 | run-level |
| volatility_squeeze | Sharpe | 0.000 | 0.000 | 0.000 | 9 | run-level |
| volatility_squeeze | Win Rate | 0.000 | 0.000 | 0.000 | 9 | run-level |
| volatility_squeeze | Max Drawdown | 0.000 | 0.000 | 0.000 | 9 | run-level |

## Sample Size & Verdict

| Strategy | n_runs | n_runs_w_trades | total_trades | PF lower CI | Verdict | Reason |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| ttc_xauusd | 3 | 3 | 95 | 0.000 | **KILL** | PF lower CI 0.000 < 1.0 — edge not statistically distinguishable from break-even |
| bb_rsi_reversion | 9 | 9 | 158 | 0.099 | **KILL** | PF lower CI 0.099 < 1.0 — edge not statistically distinguishable from break-even |
| killzone_momentum | 9 | 9 | 196 | 0.306 | **KILL** | PF lower CI 0.306 < 1.0 — edge not statistically distinguishable from break-even |
| london_breakout_retest | 9 | 7 | 142 | 0.034 | **KILL** | PF lower CI 0.034 < 1.0 — edge not statistically distinguishable from break-even |
| srmr_plus | 6 | 6 | 314 | 0.161 | **KILL** | PF lower CI 0.161 < 1.0 — edge not statistically distinguishable from break-even |
| donchian_atr_trend | 9 | 9 | 347 | 0.054 | **KILL** | PF lower CI 0.054 < 1.0 — edge not statistically distinguishable from break-even |
| volatility_regime_breakout | 9 | 0 | 0 | 0.000 | **KILL** | no trades across any run — strategy is non-functional or not wired to a live data feed |
| volatility_squeeze | 9 | 0 | 0 | 0.000 | **KILL** | no trades across any run — strategy is non-functional or not wired to a live data feed |

## Detail

### ttc_xauusd — KILL

- **n_runs:** 3
- **n_runs_with_trades:** 3
- **total_trades:** 95
- **bootstrap path:** run-level

- **Profit Factor:** point = 1.239, 95% CI = [0.000, 2.254] (n=3) — run-level resample (per-window table empty — wider, coarser CI)
- **Sharpe:** point = 2.242, 95% CI = [0.000, 5.043] (n=3) — run-level resample (per-window table empty — wider, coarser CI)
- **Win Rate:** point = 0.309, 95% CI = [0.000, 0.473] (n=3) — run-level resample (per-window table empty — wider, coarser CI)
- **Max Drawdown:** point = 0.010, 95% CI = [0.002, 0.020] (n=3) — run-level resample (per-window table empty — wider, coarser CI)
- **Verdict reason:** PF lower CI 0.000 < 1.0 — edge not statistically distinguishable from break-even

### bb_rsi_reversion — KILL

- **n_runs:** 9
- **n_runs_with_trades:** 9
- **total_trades:** 158
- **bootstrap path:** run-level

- **Profit Factor:** point = 0.956, 95% CI = [0.099, 2.193] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Sharpe:** point = -32.457, 95% CI = [-86.147, 10.193] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Win Rate:** point = 0.179, 95% CI = [0.082, 0.290] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Max Drawdown:** point = 0.017, 95% CI = [0.009, 0.027] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Verdict reason:** PF lower CI 0.099 < 1.0 — edge not statistically distinguishable from break-even

### killzone_momentum — KILL

- **n_runs:** 9
- **n_runs_with_trades:** 9
- **total_trades:** 196
- **bootstrap path:** run-level

- **Profit Factor:** point = 0.750, 95% CI = [0.306, 1.269] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Sharpe:** point = -17.450, 95% CI = [-34.766, -5.823] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Win Rate:** point = 0.254, 95% CI = [0.176, 0.322] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Max Drawdown:** point = 0.032, 95% CI = [0.020, 0.045] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Verdict reason:** PF lower CI 0.306 < 1.0 — edge not statistically distinguishable from break-even

### london_breakout_retest — KILL

- **n_runs:** 9
- **n_runs_with_trades:** 7
- **total_trades:** 142
- **bootstrap path:** run-level

- **Profit Factor:** point = 0.496, 95% CI = [0.034, 1.387] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Sharpe:** point = -303.490, 95% CI = [-743.388, -4.364] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Win Rate:** point = 0.110, 95% CI = [0.039, 0.199] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Max Drawdown:** point = 0.014, 95% CI = [0.007, 0.023] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Verdict reason:** PF lower CI 0.034 < 1.0 — edge not statistically distinguishable from break-even

### srmr_plus — KILL

- **n_runs:** 6
- **n_runs_with_trades:** 6
- **total_trades:** 314
- **bootstrap path:** run-level

- **Profit Factor:** point = 0.358, 95% CI = [0.161, 0.559] (n=6) — run-level resample (per-window table empty — wider, coarser CI)
- **Sharpe:** point = -111.123, 95% CI = [-266.148, -12.264] (n=6) — run-level resample (per-window table empty — wider, coarser CI)
- **Win Rate:** point = 0.155, 95% CI = [0.116, 0.189] (n=6) — run-level resample (per-window table empty — wider, coarser CI)
- **Max Drawdown:** point = 0.064, 95% CI = [0.056, 0.075] (n=6) — run-level resample (per-window table empty — wider, coarser CI)
- **Verdict reason:** PF lower CI 0.161 < 1.0 — edge not statistically distinguishable from break-even

### donchian_atr_trend — KILL

- **n_runs:** 9
- **n_runs_with_trades:** 9
- **total_trades:** 347
- **bootstrap path:** run-level

- **Profit Factor:** point = 0.090, 95% CI = [0.054, 0.124] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Sharpe:** point = -331.029, 95% CI = [-952.313, -17.499] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Win Rate:** point = 0.150, 95% CI = [0.102, 0.191] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Max Drawdown:** point = 0.057, 95% CI = [0.056, 0.058] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Verdict reason:** PF lower CI 0.054 < 1.0 — edge not statistically distinguishable from break-even

### volatility_regime_breakout — KILL

- **n_runs:** 9
- **n_runs_with_trades:** 0
- **total_trades:** 0
- **bootstrap path:** run-level

- **Profit Factor:** point = 0.000, 95% CI = [0.000, 0.000] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Sharpe:** point = 0.000, 95% CI = [0.000, 0.000] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Win Rate:** point = 0.000, 95% CI = [0.000, 0.000] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Max Drawdown:** point = 0.000, 95% CI = [0.000, 0.000] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Verdict reason:** no trades across any run — strategy is non-functional or not wired to a live data feed

### volatility_squeeze — KILL

- **n_runs:** 9
- **n_runs_with_trades:** 0
- **total_trades:** 0
- **bootstrap path:** run-level

- **Profit Factor:** point = 0.000, 95% CI = [0.000, 0.000] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Sharpe:** point = 0.000, 95% CI = [0.000, 0.000] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Win Rate:** point = 0.000, 95% CI = [0.000, 0.000] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Max Drawdown:** point = 0.000, 95% CI = [0.000, 0.000] (n=9) — run-level resample (per-window table empty — wider, coarser CI)
- **Verdict reason:** no trades across any run — strategy is non-functional or not wired to a live data feed

## Methodology & Caveats

- When the `windows` table has rows for a strategy, the bootstrap resamples per-window scalars directly. This is the preferred path because the CI reflects the within-strategy window variability.
- When `windows` is empty (current production reality for the pre-SRF-fix runs in this database), the bootstrap resamples per-run `mean_*` scalars. The CI is wider and coarser because each run already collapsed many windows into one number; between-window variability is unrecoverable without the raw windows.
- All CIs use the percentile method on 10,000 bootstrap iterations with a fixed RNG seed for reproducibility.
- `total_trades = 0` strategies are kill-eligible on data grounds: there is no statistical evidence either way, but a strategy with zero executed trades cannot be promoted to production. Verdict is KILL regardless of any computed CI.
- The kill threshold (`lower PF CI < 1.0`) is the standard break-even test. It is intentionally one-sided — we only kill on evidence of no edge, not on evidence of large edge.

_Generated by `scripts/quant/bootstrap_ci.py` on 2026-07-13._
