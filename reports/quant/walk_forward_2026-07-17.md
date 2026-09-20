# Walk-Forward Haircut-Ratio Analysis (Proxy)

**Date:** 2026-07-17
**Data source:** `$AYUMI_ROOT/data/research/research.duckdb`
**Method:** Proxy haircut from `metrics_summary.mean_sharpe` and `oos_sharpe_decay`

---

## Data State Assessment

### Critical Limitations

- **Window date columns ALL NULL:** `windows.train_start/end`, `test_start/end` = 0/323 populated. True IS/OOS haircut impossible.
- **7 of 8 candidates have 0 windows** in the `windows` table (only `killzone_momentum` has 3).
- **`oos_sharpe_decay` is a within-test-period proxy** (first-half vs second-half PnL split), NOT true out-of-sample decay.
- **Naming variants:** SRF DB has duplicate runs under both `killzone_momentum` and `killzonemomentum`. Analysis merges both, preferring backfilled (non-underscore) variant with more complete metrics.
- **Most strategies are no-go** with 0/5 windows passed and deeply negative Sharpe ratios.

### Windows Table Summary

| Candidate | Windows Count | Date Columns Populated |
|-----------|--------------|----------------------|
| srmr_plus | 30 | 0% (all NULL) |
| ttc_xauusd | 0 | 0% (all NULL) |
| donchian_atr_trend | 45 | 0% (all NULL) |
| killzone_momentum | 93 | 0% (all NULL) |
| volatility_squeeze | 65 | 0% (all NULL) |
| london_breakout_retest | 45 | 0% (all NULL) |
| volatility_regime_breakout | 45 | 0% (all NULL) |
| bb_rsi_reversion | 0 | 0% (all NULL) |

## Proxy Haircut Results

### Per-Candidate Summary

| Candidate | Runs | Avg Mean Sharpe | Avg OOS Decay | Haircut Ratio | Verdict |
|-----------|------|----------------|---------------|---------------|---------|
| srmr_plus | 12 | -20.9627 | 0.0000 | -20.9627 | **kill** |
| ttc_xauusd | 3 | 2.2406 | N/A | 1.0000 | **healthy** |
| donchian_atr_trend | 18 | -352.4085 | 0.0000 | -352.4085 | **kill** |
| killzone_momentum | 28 | -41.0947 | 0.0126 | -40.5820 | **kill** |
| volatility_squeeze | 22 | 0.0000 | N/A | 0.0000 | **kill** |
| london_breakout_retest | 18 | -13.9828 | 0.0000 | -13.9828 | **kill** |
| volatility_regime_breakout | 18 | 0.0000 | N/A | 0.0000 | **kill** |
| bb_rsi_reversion | 9 | -32.2649 | N/A | -32.2649 | **kill** |

### Kill List (haircut < 0.5 or negative Sharpe)

- **srmr_plus** — haircut=-20.9627, avg_sharpe=-20.9627
  - 6/12 runs lack oos_sharpe_decay
  - All runs are no-go
- **donchian_atr_trend** — haircut=-352.4085, avg_sharpe=-352.4085
  - 9/18 runs lack oos_sharpe_decay
  - All runs are no-go
- **killzone_momentum** — haircut=-40.5820, avg_sharpe=-41.0947
  - 10/28 runs lack oos_sharpe_decay
  - All runs are no-go
- **volatility_squeeze** — haircut=0.0000, avg_sharpe=0.0000
  - All runs are no-go
- **london_breakout_retest** — haircut=-13.9828, avg_sharpe=-13.9828
  - 15/18 runs lack oos_sharpe_decay
  - All runs are no-go
- **volatility_regime_breakout** — haircut=0.0000, avg_sharpe=0.0000
  - All runs are no-go
- **bb_rsi_reversion** — haircut=-32.2649, avg_sharpe=-32.2649
  - All runs are no-go

### Marginal (0.5 ≤ haircut < 0.7)

- (none)

### Healthy (haircut ≥ 0.7)

- **ttc_xauusd** — haircut=1.0000

### No Data

- (none)

## Best Run Per Candidate

| Candidate | Best Pair | Best TF | Best Sharpe | Worst Sharpe |
|-----------|-----------|---------|-------------|-------------|
| srmr_plus | GBPUSD | 5m | -7.9172 | -56.1544 |
| ttc_xauusd | XAUUSD | 15m | 5.0430 | 0.0000 |
| donchian_atr_trend | GBPUSD | 60m | -12.8681 | -2812.1527 |
| killzone_momentum | XAUUSD | 60m | 3.3059 | -249.9255 |
| volatility_squeeze | EURUSD | 5m | 0.0000 | 0.0000 |
| london_breakout_retest | XAUUSD | 5m | -3.6372 | -21.3837 |
| volatility_regime_breakout | EURUSD | 5m | 0.0000 | 0.0000 |
| bb_rsi_reversion | GBPUSD | 60m | 79.6456 | -212.6082 |

## Killzone Momentum Window Detail (only candidate with windows)

| Run ID | Pair | TF | Window | PnL | Trades | Passed |
|--------|------|----|--------|-----|--------|--------|
| killzone_momentum_GBPUSD_15m_2... | GBPUSD | 15m | 0 | -636.80 | 4 | False |
| killzone_momentum_GBPUSD_15m_2... | GBPUSD | 15m | 1 | -524.79 | 4 | False |
| killzone_momentum_GBPUSD_15m_2... | GBPUSD | 15m | 2 | -643.38 | 5 | False |
| killzonemomentum_EURUSD_5m_202... | EURUSD | 5m | 0 | -727.62 | 2 | False |
| killzonemomentum_EURUSD_5m_202... | EURUSD | 5m | 0 | -727.62 | 2 | False |
| killzonemomentum_EURUSD_5m_202... | EURUSD | 5m | 1 | -430.02 | 9 | False |
| killzonemomentum_EURUSD_5m_202... | EURUSD | 5m | 1 | -430.02 | 9 | False |
| killzonemomentum_EURUSD_5m_202... | EURUSD | 5m | 2 | -1039.63 | 4 | False |
| killzonemomentum_EURUSD_5m_202... | EURUSD | 5m | 2 | -1039.63 | 4 | False |
| killzonemomentum_EURUSD_5m_202... | EURUSD | 5m | 3 | -562.24 | 2 | False |
| killzonemomentum_EURUSD_5m_202... | EURUSD | 5m | 3 | -562.24 | 2 | False |
| killzonemomentum_EURUSD_5m_202... | EURUSD | 5m | 4 | -538.16 | 11 | False |
| killzonemomentum_EURUSD_5m_202... | EURUSD | 5m | 4 | -538.16 | 11 | False |
| killzonemomentum_EURUSD_15m_20... | EURUSD | 15m | 0 | -559.18 | 10 | False |
| killzonemomentum_EURUSD_15m_20... | EURUSD | 15m | 0 | -559.18 | 10 | False |
| killzonemomentum_EURUSD_15m_20... | EURUSD | 15m | 1 | -658.18 | 4 | False |
| killzonemomentum_EURUSD_15m_20... | EURUSD | 15m | 1 | -658.18 | 4 | False |
| killzonemomentum_EURUSD_15m_20... | EURUSD | 15m | 2 | -655.23 | 4 | False |
| killzonemomentum_EURUSD_15m_20... | EURUSD | 15m | 2 | -655.23 | 4 | False |
| killzonemomentum_EURUSD_15m_20... | EURUSD | 15m | 3 | -648.17 | 6 | False |
| killzonemomentum_EURUSD_15m_20... | EURUSD | 15m | 3 | -648.17 | 6 | False |
| killzonemomentum_EURUSD_15m_20... | EURUSD | 15m | 4 | -725.73 | 7 | False |
| killzonemomentum_EURUSD_15m_20... | EURUSD | 15m | 4 | -725.73 | 7 | False |
| killzonemomentum_EURUSD_60m_20... | EURUSD | 60m | 0 | -515.30 | 4 | False |
| killzonemomentum_EURUSD_60m_20... | EURUSD | 60m | 0 | -515.30 | 4 | False |
| killzonemomentum_EURUSD_60m_20... | EURUSD | 60m | 1 | -629.83 | 4 | False |
| killzonemomentum_EURUSD_60m_20... | EURUSD | 60m | 1 | -629.83 | 4 | False |
| killzonemomentum_EURUSD_60m_20... | EURUSD | 60m | 2 | -171.84 | 5 | False |
| killzonemomentum_EURUSD_60m_20... | EURUSD | 60m | 2 | -171.84 | 5 | False |
| killzonemomentum_EURUSD_60m_20... | EURUSD | 60m | 3 | -297.35 | 4 | False |
| killzonemomentum_EURUSD_60m_20... | EURUSD | 60m | 3 | -297.35 | 4 | False |
| killzonemomentum_EURUSD_60m_20... | EURUSD | 60m | 4 | -515.14 | 4 | False |
| killzonemomentum_EURUSD_60m_20... | EURUSD | 60m | 4 | -515.14 | 4 | False |
| killzonemomentum_GBPUSD_5m_202... | GBPUSD | 5m | 0 | -638.34 | 2 | False |
| killzonemomentum_GBPUSD_5m_202... | GBPUSD | 5m | 0 | -638.34 | 2 | False |
| killzonemomentum_GBPUSD_5m_202... | GBPUSD | 5m | 1 | -567.62 | 4 | False |
| killzonemomentum_GBPUSD_5m_202... | GBPUSD | 5m | 1 | -567.62 | 4 | False |
| killzonemomentum_GBPUSD_5m_202... | GBPUSD | 5m | 2 | -715.33 | 4 | False |
| killzonemomentum_GBPUSD_5m_202... | GBPUSD | 5m | 2 | -715.33 | 4 | False |
| killzonemomentum_GBPUSD_5m_202... | GBPUSD | 5m | 3 | -539.01 | 6 | False |
| killzonemomentum_GBPUSD_5m_202... | GBPUSD | 5m | 3 | -539.01 | 6 | False |
| killzonemomentum_GBPUSD_5m_202... | GBPUSD | 5m | 4 | -550.39 | 4 | False |
| killzonemomentum_GBPUSD_5m_202... | GBPUSD | 5m | 4 | -550.39 | 4 | False |
| killzonemomentum_GBPUSD_15m_20... | GBPUSD | 15m | 0 | -636.32 | 8 | False |
| killzonemomentum_GBPUSD_15m_20... | GBPUSD | 15m | 0 | -636.32 | 8 | False |
| killzonemomentum_GBPUSD_15m_20... | GBPUSD | 15m | 1 | -543.47 | 7 | False |
| killzonemomentum_GBPUSD_15m_20... | GBPUSD | 15m | 1 | -543.47 | 7 | False |
| killzonemomentum_GBPUSD_15m_20... | GBPUSD | 15m | 2 | -481.16 | 3 | False |
| killzonemomentum_GBPUSD_15m_20... | GBPUSD | 15m | 2 | -481.16 | 3 | False |
| killzonemomentum_GBPUSD_15m_20... | GBPUSD | 15m | 3 | -519.89 | 4 | False |
| killzonemomentum_GBPUSD_15m_20... | GBPUSD | 15m | 3 | -519.89 | 4 | False |
| killzonemomentum_GBPUSD_15m_20... | GBPUSD | 15m | 4 | -564.61 | 5 | False |
| killzonemomentum_GBPUSD_15m_20... | GBPUSD | 15m | 4 | -564.61 | 5 | False |
| killzonemomentum_GBPUSD_60m_20... | GBPUSD | 60m | 0 | -358.30 | 13 | False |
| killzonemomentum_GBPUSD_60m_20... | GBPUSD | 60m | 0 | -358.30 | 13 | False |
| killzonemomentum_GBPUSD_60m_20... | GBPUSD | 60m | 1 | -514.54 | 5 | False |
| killzonemomentum_GBPUSD_60m_20... | GBPUSD | 60m | 1 | -514.54 | 5 | False |
| killzonemomentum_GBPUSD_60m_20... | GBPUSD | 60m | 2 | -632.55 | 9 | False |
| killzonemomentum_GBPUSD_60m_20... | GBPUSD | 60m | 2 | -632.55 | 9 | False |
| killzonemomentum_GBPUSD_60m_20... | GBPUSD | 60m | 3 | -497.91 | 7 | False |
| killzonemomentum_GBPUSD_60m_20... | GBPUSD | 60m | 3 | -497.91 | 7 | False |
| killzonemomentum_GBPUSD_60m_20... | GBPUSD | 60m | 4 | -596.24 | 4 | False |
| killzonemomentum_GBPUSD_60m_20... | GBPUSD | 60m | 4 | -596.24 | 4 | False |
| killzonemomentum_XAUUSD_5m_202... | XAUUSD | 5m | 0 | 13.28 | 30 | False |
| killzonemomentum_XAUUSD_5m_202... | XAUUSD | 5m | 0 | 13.28 | 30 | False |
| killzonemomentum_XAUUSD_5m_202... | XAUUSD | 5m | 1 | -219.52 | 17 | False |
| killzonemomentum_XAUUSD_5m_202... | XAUUSD | 5m | 1 | -219.52 | 17 | False |
| killzonemomentum_XAUUSD_5m_202... | XAUUSD | 5m | 2 | 372.61 | 24 | False |
| killzonemomentum_XAUUSD_5m_202... | XAUUSD | 5m | 2 | 372.61 | 24 | False |
| killzonemomentum_XAUUSD_5m_202... | XAUUSD | 5m | 3 | 12699.78 | 12 | False |
| killzonemomentum_XAUUSD_5m_202... | XAUUSD | 5m | 3 | 12699.78 | 12 | False |
| killzonemomentum_XAUUSD_5m_202... | XAUUSD | 5m | 4 | 154.85 | 45 | False |
| killzonemomentum_XAUUSD_5m_202... | XAUUSD | 5m | 4 | 154.85 | 45 | False |
| killzonemomentum_XAUUSD_15m_20... | XAUUSD | 15m | 0 | -494.49 | 11 | False |
| killzonemomentum_XAUUSD_15m_20... | XAUUSD | 15m | 0 | -494.49 | 11 | False |
| killzonemomentum_XAUUSD_15m_20... | XAUUSD | 15m | 1 | -542.38 | 2 | False |
| killzonemomentum_XAUUSD_15m_20... | XAUUSD | 15m | 1 | -542.38 | 2 | False |
| killzonemomentum_XAUUSD_15m_20... | XAUUSD | 15m | 2 | -332.01 | 15 | False |
| killzonemomentum_XAUUSD_15m_20... | XAUUSD | 15m | 2 | -332.01 | 15 | False |
| killzonemomentum_XAUUSD_15m_20... | XAUUSD | 15m | 3 | 130.48 | 15 | True |
| killzonemomentum_XAUUSD_15m_20... | XAUUSD | 15m | 3 | 130.48 | 15 | True |
| killzonemomentum_XAUUSD_15m_20... | XAUUSD | 15m | 4 | -511.69 | 8 | False |
| killzonemomentum_XAUUSD_15m_20... | XAUUSD | 15m | 4 | -511.69 | 8 | False |
| killzonemomentum_XAUUSD_60m_20... | XAUUSD | 60m | 0 | 251.32 | 6 | True |
| killzonemomentum_XAUUSD_60m_20... | XAUUSD | 60m | 0 | 251.32 | 6 | True |
| killzonemomentum_XAUUSD_60m_20... | XAUUSD | 60m | 1 | -196.24 | 5 | False |
| killzonemomentum_XAUUSD_60m_20... | XAUUSD | 60m | 1 | -196.24 | 5 | False |
| killzonemomentum_XAUUSD_60m_20... | XAUUSD | 60m | 2 | 76.83 | 6 | True |
| killzonemomentum_XAUUSD_60m_20... | XAUUSD | 60m | 2 | 76.83 | 6 | True |
| killzonemomentum_XAUUSD_60m_20... | XAUUSD | 60m | 3 | -115.45 | 4 | False |
| killzonemomentum_XAUUSD_60m_20... | XAUUSD | 60m | 3 | -115.45 | 4 | False |
| killzonemomentum_XAUUSD_60m_20... | XAUUSD | 60m | 4 | 30.59 | 11 | False |
| killzonemomentum_XAUUSD_60m_20... | XAUUSD | 60m | 4 | 30.59 | 11 | False |

## Caveats

1. **This is a proxy analysis, not a true walk-forward haircut.** The formula
   `haircut = avg_sharpe / max(avg_sharpe, |decay| + 1)` approximates OOS
   degradation using the within-period first-half/second-half PnL split.
2. **True IS/OOS haircut requires** populated window date columns + window-level
   Sharpe ratios. Both are absent from the current SRF data pipeline.
3. **Negative Sharpe ratios dominate.** 7/8 candidates have deeply negative
   average Sharpe, suggesting either unprofitable strategies or parameter
   misconfiguration. The haircut ratio is moot when the strategy itself is
   unprofitable.
4. **`ttc_xauusd` is the only candidate with any positive Sharpe runs**
   (XAUUSD 5m=1.68, 15m=5.04), but still rated no-go (0/5 and 2/5 windows passed).

## [DEBT] Cards Recommended

1. **Fix `srf/runner.py` `_insert_windows` to populate date columns** — 
   `train_start/end`, `test_start/end` must be written per window for true
   walk-forward analysis.
2. **Re-run SRF sweep for 7 candidates missing from `windows` table** — 
   only `killzone_momentum` has window-level data.
3. **Investigate deeply negative Sharpe ratios** — values like -2812 (donchian
   XAUUSD 15m) suggest data quality or parameter search issues.

---
*Generated by `scripts/quant/walk_forward_analysis.py`*