# Revalidation Report — July 2026

**Generated:** 2026-07-24 06:12 UTC
**Sweep date:** 2026-07-24T01:39:11.059084+00:00
**Strategies evaluated:** 6
**Walk-forward windows:** 5

## Canonical Parameters (Corrected)

| Parameter | Value |
|---|---|
| Initial Balance | $100,000 |
| Risk per Trade | 0.5% |
| Daily DD Limit | 3.0% |
| Max Open Trades | 3 |

> **⚠ PROVISIONAL:** All strategy decisions based on historical sweeps prior to
> this revalidation are marked **PROVISIONAL** throughout this report. The
> corrected FTMO parameters (0.5% risk, 3% daily DD, $100k balance) reflect
> actual FTMO challenge conditions. Prior sweeps used incorrect parameters
> (1% risk, 5% daily DD) that inflated trade counts and drawdown tolerance.

## Per-Strategy Comparison (Old Sweep vs Re-Sweep)

| Strategy | Pair | TF | Metric | Old Sweep | New Re-Sweep | Delta |
|---|---|---|---|---|---|---|
| srmr_plus | XAUUSD | M15 | **PF** | N/A → 0.966 | | |
| | | | **Win Rate** | N/A → 0.526 | | |
| | | | **Sharpe** | N/A → 0.663 | | |
| | | | **Max DD** | N/A → 0.014 | | |
| | | | **Trades** | 0 → 35 (+35) | | |
| | | | **GO/NO-GO** | N/A → NO-GO  | | |
| | | | | | | |
| london_breakout_retest | XAUUSD | M15 | **PF** | 0.078 → 0.251 (+0.173) | | |
| | | | **Win Rate** | 0.138 → 0.547 (+0.409) | | |
| | | | **Sharpe** | -16.928 → -1.146 (+15.782) | | |
| | | | **Max DD** | 0.046 → 0.012 (-0.033) | | |
| | | | **Trades** | 53 → 73 (+20) | | |
| | | | **GO/NO-GO** | NO-GO → NO-GO  | | |
| | | | | | | |
| ttc_xauusd | XAUUSD | M15 | **PF** | 2.254 → 13.383 (+11.129) | | |
| | | | **Win Rate** | 0.473 → 0.511 (+0.038) | | |
| | | | **Sharpe** | 5.043 → 6.256 (+1.213) | | |
| | | | **Max DD** | 0.007 → 0.009 (+0.001) | | |
| | | | **Trades** | 31 → 49 (+18) | | |
| | | | **GO/NO-GO** | NO-GO → GO 🔥 **STATUS CHANGE** | | |
| | | | | | | |
| killzone_momentum | XAUUSD | H1 | **PF** | 2.777 → 2.610 (-0.167) | | |
| | | | **Win Rate** | 0.572 → 0.639 (+0.066) | | |
| | | | **Sharpe** | 4.377 → 1.904 (-2.473) | | |
| | | | **Max DD** | 0.014 → 0.008 (-0.006) | | |
| | | | **Trades** | 32 → 30 (-2) | | |
| | | | **GO/NO-GO** | NO-GO → GO 🔥 **STATUS CHANGE** | | |
| | | | | | | |
| volatility_squeeze | XAUUSD | H1 | **PF** | N/A → 0.326 | | |
| | | | **Win Rate** | N/A → 0.544 | | |
| | | | **Sharpe** | N/A → -1.425 | | |
| | | | **Max DD** | N/A → 0.023 | | |
| | | | **Trades** | 0 → 82 (+82) | | |
| | | | **GO/NO-GO** | NO-GO → GO 🔥 **STATUS CHANGE** | | |
| | | | | | | |
| volatility_regime_breakout | XAUUSD | M15 | **PF** | N/A → 0.044 | | |
| | | | **Win Rate** | N/A → 0.375 | | |
| | | | **Sharpe** | N/A → -5.003 | | |
| | | | **Max DD** | N/A → 0.033 | | |
| | | | **Trades** | 0 → 83 (+83) | | |
| | | | **GO/NO-GO** | NO-GO → NO-GO  | | |
| | | | | | | |
## Detailed Analysis

### srmr_plus (XAUUSD M15)

- **Status: NO-GO** (no prior sweep data for this strategy/TF combination)
- Profit Factor: 0.966 (95% CI: [0.310, 2.385])
- Win Rate: 52.6%
- Sharpe Ratio: 0.663
- Max Drawdown: 1.44%
- Windows Passed: 0/5
- Total Trades: 35
- ⚠ **Old sweep had 0 trades** — comparison may not be meaningful

### london_breakout_retest (XAUUSD M15)

- **Status: NO-GO** (unchanged from prior sweep)
- Profit Factor: 0.251 (95% CI: [0.100, 0.464])
- Win Rate: 54.7%
- Sharpe Ratio: -1.146
- Max Drawdown: 1.25%
- Windows Passed: 2/5
- Total Trades: 73

### ttc_xauusd (XAUUSD M15)

- **Status: ↑ Newly passing** (was NO-GO, now GO)
- PF improved: 2.254 → 13.383
- Profit Factor: 13.383 (95% CI: [5.553, 53.972])
- Win Rate: 51.1%
- Sharpe Ratio: 6.256
- Max Drawdown: 0.89%
- Windows Passed: 3/5
- Total Trades: 49

### killzone_momentum (XAUUSD H1)

- **Status: ↑ Newly passing** (was NO-GO, now GO)
- PF improved: 2.777 → 2.610
- Profit Factor: 2.610 (95% CI: [1.091, 9.273])
- Win Rate: 63.9%
- Sharpe Ratio: 1.904
- Max Drawdown: 0.80%
- Windows Passed: 3/5
- Total Trades: 30

### volatility_squeeze (XAUUSD H1)

- **Status: ↑ Newly passing** (was NO-GO, now GO)
- PF: 0.326
- **Critical:** Old sweep generated 0 trades — strategy was untestable with prior params
- Profit Factor: 0.326 (95% CI: [0.196, 0.533])
- Win Rate: 54.4%
- Sharpe Ratio: -1.425
- Max Drawdown: 2.29%
- Windows Passed: 3/5
- Total Trades: 82
- ⚠ **CI concern:** Lower bound (0.196) < 1.0 — profitability not statistically certain
- ⚠ **Old sweep had 0 trades** — comparison may not be meaningful

### volatility_regime_breakout (XAUUSD M15)

- **Status: NO-GO** (unchanged from prior sweep)
- Profit Factor: 0.044 (95% CI: [0.024, 0.074])
- Win Rate: 37.5%
- Sharpe Ratio: -5.003
- Max Drawdown: 3.31%
- Windows Passed: 0/5
- Total Trades: 83
- ⚠ **Old sweep had 0 trades** — comparison may not be meaningful

## Go/No-Go Summary

### ✅ GO (2)

1. **ttc_xauusd** — PF=13.38, Sharpe=6.26, WR=51.1%
1. **killzone_momentum** — PF=2.61, Sharpe=1.90, WR=63.9%

### ⚠ ANOMALOUS — Criteria Conflict (1)

These strategies have GO=true (passed ≥3/5 windows) but PF < 1.0 (net losses).
**DO NOT DEPLOY until criteria conflict is resolved.**

1. **volatility_squeeze** — PF=0.33, Sharpe=-1.43, WR=54.4% (GO by window count 3/5, but PF indicates losses)

### ❌ NO-GO (3)

1. **srmr_plus** — PF=0.97, Sharpe=0.66, WR=52.6%
1. **london_breakout_retest** — PF=0.25, Sharpe=-1.15, WR=54.7%
1. **volatility_regime_breakout** — PF=0.04, Sharpe=-5.00, WR=37.5%

## Status Changes (Old → New)

### ↑ Newly Passing
- **ttc_xauusd** — was NO-GO, now GO. Prior decisions to shelve this strategy are **PROVISIONAL**.
- **killzone_momentum** — was NO-GO, now GO. Prior decisions to shelve this strategy are **PROVISIONAL**.
- **volatility_squeeze** — ↑ Newly passing BY WINDOW COUNT (3/5) but PF=0.33 indicates losses — criteria conflict, see anomaly section. Prior decisions are **PROVISIONAL**.
### ↓ Newly Failing: None

## ⚠ Anomaly: GO Flag vs Metrics Conflict

### volatility_squeeze

- **GO flag:** True (passed 3/5 walk-forward windows)
- **Profit Factor:** 0.326 — below 1.0, indicating net losses
- **Sharpe Ratio:** -1.425 — negative
- **CI lower bound:** 0.196 — well below 1.0 profitability threshold

**Root cause:** The GO/NO-GO gate uses window-count (≥3/5 passed) as its criterion,
but PF=0.33 means the strategy loses money on average. These two
criteria conflict for this strategy.

**Recommendation:** Resolve the criterion conflict BEFORE any FTMO deployment decision.
Either:(a) add a PF ≥ 1.0 floor to the GO gate, or (b) accept window-count as sole
criterion and document the risk. This is the issue parent card d8c5aead flagged
for this report to address.

**Status: DO NOT DEPLOY volatility_squeeze until this conflict is resolved.**

## ⚠ PROVISIONAL Decisions Flag

All strategy deployment, shelving, or parameter decisions made between the original
sweep (Jul 13–19, 2026) and this revalidation (Jul 24, 2026) are **PROVISIONAL**.
They were based on sweeps with incorrect FTMO parameters and must be re-evaluated
against the corrected results in this report.

**Affected decisions:**
- Any strategy promoted to forward testing based on old sweep GO status
- Any strategy archived based on old sweep NO-GO status
- Any parameter optimization performed against old sweep metrics
- The multiple testing correction (Jul 12) results — p-values were computed from
  old sweep data and may change with corrected params

## Craig Recommendation

Based on the corrected re-sweep results:

**Proceed to FTMO live capital:**
- ttc_xauusd (PF=13.38, Sharpe=6.26)
- killzone_momentum (PF=2.61, Sharpe=1.90)

**Do not deploy:**
- srmr_plus (PF=0.97)
- volatility_squeeze (PF=0.33) (⚠ ANOMALOUS: GO by window count but PF=0.33 — criteria conflict, see anomaly section)
- london_breakout_retest (PF=0.25)
- volatility_regime_breakout (PF=0.04)

---
*Generated by `scripts/build_report.py`*