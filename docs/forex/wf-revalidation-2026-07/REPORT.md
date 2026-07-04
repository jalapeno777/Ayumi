# SRMR+ Walk-Forward Revalidation — 2026-07-03

Walk-forward revalidation of `SRMR+` on the four target pairs using the clean
WF runner (`backtest.walk_forward_runner.run_strategy_walk_forward`,
`n_windows=5`, `train_ratio=0.7`, `val_ratio=0.15`, `overlap_ratio=0.2`).

## Exit Gate

> "≥1 strategy passes 3/5 WF windows per pair" — repeated across ≥2 pairs.

**Result: FAIL.** Only **XAUUSD** passes 3/5 (passes 5/5). The other three
pairs each pass at most 1/5.

## Data Sources

| Pair    | Source                    | Bars    | Range                           | Spread (pips) |
| ------- | ------------------------- | ------- | ------------------------------- | ------------- |
| GBPUSD  | `data/forex/parquet/GBPUSD_1h.parquet` | 17,225 | 2023-06-22 → 2026-04-08 | 1.5 |
| EURUSD  | `data/forex/parquet/EURUSD_1h.parquet` | 17,223 | 2023-06-22 → 2026-04-08 | 1.5 |
| USDJPY  | `data/forex/parquet/USDJPY_1h.parquet` | 17,126 | 2023-06-22 → 2026-04-08 | 1.5 |
| XAUUSD  | `data/forex/historical/XAUUSD_M15.csv` | 74,324 | 2023-01-02 → 2026-04-10 | 2.5 |

Note: parquet files store the timestamp as the dataframe index; the in-tree
`CsvDataLoader.load_parquet` does not `reset_index()` so it raises
`KeyError: 'timestamp'`. The runner reads the parquet directly and constructs
`Bar` objects. This is a pre-existing loader bug and is logged as a finding.

## Per-Pair Summary

| Pair    | Windows Passed | PF mean | WR mean | Sharpe | Max DD  | Trades/window | PnL mean (10k acct) |
| ------- | -------------- | ------- | ------- | ------ | ------- | ------------- | ------------------- |
| GBPUSD  | 0 / 5          | 0.807   | 37.7 %  | −2.40  | 2.40 %  | 14.4          | −126.63             |
| EURUSD  | 1 / 5          | 0.944   | 36.0 %  | −3.56  | 3.09 %  | 13.0          | −144.72             |
| USDJPY  | 1 / 5          | 1.271   | 42.8 %  | −0.01  | 2.19 %  | 13.6          | −31.67              |
| XAUUSD  | 5 / 5          | 8.020   | 86.3 %  | 13.68  | 0.60 %  | 48.4          | +2,020.31           |

## Interpretation

- **XAUUSD** dominates: passes 5/5 windows, mean PF ≈ 8, very low DD, mean
  PnL ≈ +20 % per walk-forward window. The strategy is robust on gold at
  M15 resolution (74k bars ≈ 2.3 years of data).
- **USDJPY** is borderline: passes 1/5, mean PF 1.27 but negative Sharpe and
  negative PnL. Trade counts are too low for statistical confidence (window 4
  has only 8 trades). USDJPY at 1h is borderline viable — needs more data or
  a smaller timeframe to confirm.
- **EURUSD** and **GBPUSD** fail: mean PF < 1, negative PnL, and Sharpe strongly
  negative. The SRMR+ configuration is not viable on these pairs at 1h
  resolution with the supplied data window.
- Trade-count guardrail flags every 1h-pair window as below the 15-trade
  minimum for statistical significance — these results are exploratory, not
  statistically conclusive.

## Recommendation

The exit gate as written is **not met**. Two paths forward:

1. **Scope down to XAUUSD-only** for the MVP forward-test shortlist. SRMR+ on
   XAUUSD is the only configuration with credible walk-forward evidence. Drop
   GBPUSD/EURUSD/USDJPY from the SRMR+ universe until retuned or retested on
   smaller timeframes.
2. **Re-spec the exit gate or the data window.** The 1h parquet slice
   (2023-06 → 2026-04) only generates 8–19 trades per WF window for the FX
   majors. Either lower the trade-count guardrail for these pairs, expand
   the data history, or move to M15 (matches XAUUSD).

## Artifacts

- `summary.json` — machine-readable per-pair summary + exit gate verdict
- `srmrplus_wf_GBPUSD.json` — full per-window metrics, regime breakdown
- `srmrplus_wf_EURUSD.json`
- `srmrplus_wf_USDJPY.json`
- `srmrplus_wf_XAUUSD.json`