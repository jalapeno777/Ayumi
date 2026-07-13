# Multiple Testing Correction — 2026-07-13

**Source:** SRF DuckDB: /home/TacoPants/projects/Ayumi/data/research/research.duckdb
**Trials analyzed:** 43
**Alpha (per-test):** 0.05
**BH-FDR target (q):** 0.1

## Summary

| Method | Rejected H0 (significant) | Notes |
|---|---|---|
| Uncorrected (p < 0.05) | 3/43 | Each trial judged in isolation. Expected false positives = 43 × 0.05 = 2.15. |
| Bonferroni (p < 0.05/43 = 0.00116) | 3/43 | Controls family-wise error rate. Conservative. |
| Benjamini-Hochberg FDR (q = 0.1) | 3/43 | Controls expected proportion of false discoveries among rejections. |

## Per-trial results

Sorted ascending by p-value. ✅ = rejected H0 (significant), ❌ = not rejected.
_Note: 40 trial(s) have a non-positive mean Sharpe and are reported as p = 1 (not candidates). They are omitted from the table below but counted in the summary above._

| # | Trial | Sharpe | Trades | p-value | Bonferroni | BH-FDR |
|---:|---|---:|---:|---:|:---:|:---:|
| 1 | `bb_rsi_reversion/GBPUSD/M60` | +79.646 | 21 | 0 | ✅ | ✅ |
| 2 | `ttc_xauusd/XAUUSD/M15` | +5.043 | 31 | 0 | ✅ | ✅ |
| 3 | `ttc_xauusd/XAUUSD/M5` | +1.679 | 61 | 0 | ✅ | ✅ |
| ... | _(40 non-candidate trials with non-positive Sharpe elided)_ | | | | | |

## Surviving candidates

**Bonferroni survivors** (FWER controlled):
- `bb_rsi_reversion/GBPUSD/M60`
- `ttc_xauusd/XAUUSD/M15`
- `ttc_xauusd/XAUUSD/M5`

**Benjamini-Hochberg survivors** (FDR controlled):
- `bb_rsi_reversion/GBPUSD/M60`
- `ttc_xauusd/XAUUSD/M15`
- `ttc_xauusd/XAUUSD/M5`

## Interpretation

3 of 43 trials survive BH-FDR at q = 0.1. These are the candidates whose apparent edges are most robust to the look-elsewhere effect. Promote these to walk-forward validation and live-paper stages; treat the rest as exploratory.

⚠️ **Caveat:** The top survivor (`bb_rsi_reversion/GBPUSD/M60`) has a mean Sharpe of +79.65 on only 21 trades. Sharpe ratios above ~3.0 on small samples are typically artifacts of variance estimation, not real edge. Treat the ranking as a screening tool, not a deployable signal. Bootstrap CIs and walk-forward OOS performance must confirm before any capital allocation.

## Method

Per-trial p-values come from a one-sample t-test on the Sharpe ratio with ``df = n_trades - 1`` and a unit-variance assumption on per-trade returns. This is the standard Lo (2002) approximation used in the SRF pipeline.

**Bonferroni** divides alpha by the number of trials. **Benjamini-Hochberg** controls the false discovery rate (expected proportion of false positives among rejected hypotheses) and is strictly more powerful than Bonferroni while still controlling FDR at level ``q`` under independence.
