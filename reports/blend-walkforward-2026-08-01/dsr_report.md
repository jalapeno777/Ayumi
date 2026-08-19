# Deflated Sharpe Ratio Analysis — 2026-08-01

**Source:** JSONL: reports/blend-walkforward-2026-08-01/killzone_momentum_focused_results.jsonl, reports/blend-walkforward-2026-08-01/dual_tf_squeeze_pro_focused_results.jsonl, reports/blend-walkforward-2026-08-01/donchian_atr_trend_v2_focused_results.jsonl, reports/blend-walkforward-2026-08-01/srmr_plus_focused_results.jsonl, reports/blend-walkforward-2026-08-01/london_breakout_retest_focused_results.jsonl, reports/blend-walkforward-2026-08-01/ttc_xauusd_focused_results.jsonl
**Candidates analyzed:** 6
**Independent trials (multiple-testing correction):** 48
**Significance level (α):** 0.05
**Expected max Sharpe under null:** 2.2606

## Summary

| Category | Count | Criteria |
|---|---:|---|
| Promote (significant edge) | 0 | DSR p-value < 0.05 |
| Watch (uncertain) | 0 | Edge prob ∈ [50%, 95%) |
| Kill (insufficient evidence) | 6 | Edge prob < 50% |

## Promote List

Candidates with DSR p-value < 0.05 (statistically significant edge after multiple-testing correction).

_No candidates meet the promotion threshold._

## Kill List

Candidates with edge probability < 50% (insufficient evidence of genuine edge).

| # | Candidate | Sharpe | Trades | DSR p-value | Edge Prob |
|---:|---|---:|---:|---:|---:|
| 1 | `XAUUSD/M15` | +1.693 | 21 | 0.9481 | 5.2% |
| 2 | `XAUUSD/H1` | +0.185 | 13 | 1.0000 | 0.0% |
| 3 | `XAUUSD/M15` | -7.790 | 20 | 1.0000 | 0.0% |
| 4 | `XAUUSD/M15` | -0.571 | 34 | 1.0000 | 0.0% |
| 5 | `XAUUSD/M15` | -0.674 | 15 | 1.0000 | 0.0% |
| 6 | `XAUUSD/M15` | -3.577 | 11 | 1.0000 | 0.0% |

## Full Ranking

All candidates sorted by edge probability (descending).

| # | Candidate | Sharpe | Trades | DSR p-value | Edge Prob | MinTRL | TRL Met | Tier |
|---:|---|---:|---:|---:|---:|---:|:---:|:---:|
| 1 | `XAUUSD/M15` | +1.693 | 21 | 0.9481 | 5.2% | -1 | — | 🔴 Kill |
| 2 | `XAUUSD/H1` | +0.185 | 13 | 1.0000 | 0.0% | -1 | — | 🔴 Kill |
| 3 | `XAUUSD/M15` | -7.790 | 20 | 1.0000 | 0.0% | -1 | — | 🔴 Kill |
| 4 | `XAUUSD/M15` | -0.571 | 34 | 1.0000 | 0.0% | -1 | — | 🔴 Kill |
| 5 | `XAUUSD/M15` | -0.674 | 15 | 1.0000 | 0.0% | -1 | — | 🔴 Kill |
| 6 | `XAUUSD/M15` | -3.577 | 11 | 1.0000 | 0.0% | -1 | — | 🔴 Kill |

## Method

**Deflated Sharpe Ratio (DSR):** Bailey & López de Prado (2014) Eq. 5. Adjusts the observed Sharpe ratio for selection bias (multiple testing) and non-normality (skewness and kurtosis). The DSR p-value tests H0: true SR ≤ E[max SR | null], where E[max SR] is the expected maximum Sharpe under the null across 48 independent trials.

**Edge Probability:** `1 - DSR p-value`. Represents the probability that the observed Sharpe ratio is genuine (not due to selection bias or multiple testing). Higher is better.

**Minimum Track Record Length (MinTRL):** Bailey & López de Prado (2014). The minimum number of observations (trades) needed to reject H0 at α = 0.05. If `Trades < MinTRL`, the candidate has insufficient track record for the DSR verdict to be trustworthy, even if the p-value is significant. Marked with ⚠️ in the TRL Met column.

**Kill List:** Edge probability < 50% — the observed Sharpe is more likely than not due to selection bias. Do not deploy or paper-trade.

**Promote List:** DSR p-value < α — the observed edge is statistically significant after multiple-testing correction. Candidates with ⚠️ on TRL Met should accumulate more trades before live deployment.
