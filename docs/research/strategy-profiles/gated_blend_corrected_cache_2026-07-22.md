# Gated Blend Re-Validation: Corrected Cache + Current Code

_Generated: 2026-07-25T04:40:00+0000_
_Methodology: v7 gate-first evaluation, rolling 300/100-bar window, corrected 100-bar regime cache_
_Script: `scripts/run_blend_5strat.py` + walk-forward/Monte Carlo analysis_

## Executive Summary

The original gated blend result (PF=1.742, +$2,820, DD=5.67%) **cannot be reproduced** with the corrected regime cache and current strategy code. The re-validated blend shows:

| Metric | Original (buggy cache) | Re-validated | Δ |
|---|---:|---:|---:|
| PF | 1.742 | 0.832 | **-0.910** |
| Net | +$2,820 | -$1,962 | **-$4,782** |
| DD% | 5.67% | 25.83% | **+20.16pp** |
| Trades | 170 | 440 | +270 |
| WR% | 45.9% | 43.6% | -2.3pp |
| Daily DD% | 2.00% | 1.50% | -0.50pp |
| Walk-forward | Unknown | 2/5 pass | FAIL |
| MC FTMO rate | Unknown | 0.2% | FAIL |
| **FTMO verdict** | **PASS** | **FAIL** | — |

**Conclusion: All PF/DD numbers from the original gated_blend_results are suspect and should not be used for viability claims.**

---

## Data

- **Source:** DuckDB `data/ayumi_market.duckdb` (bars table)
- **Symbol:** XAUUSD
- **M15:** 71,747 bars (2022-01-03 → 2025-01-31, truncated from 104K tick-aggregated bars)
- **H1:** 17,948 bars (same period)
- **Cache:** `data/cache/labels_XAUUSD_M15_18ec1e70d282.pkl` (corrected 100-bar precompute)

## Strategy Gates

| Strategy | TF | Gate |
|---|---|---|
| KillzoneMomentum | M15 | regime ∈ {QUIET, CHOPPY} AND ADX ∈ [18, 25] AND session ∈ {LONDON} |
| DualTFSqueezePro | M15 | session ∈ {ASIA, NY_AM} AND regime ∈ {VOLATILE, CHOPPY} |
| DonchianATRTrendV2 | H1 | ADX < 30 AND ATR_percentile < 0.50 |
| SRMRPlus | M15 | regime ∈ {QUIET} AND session ∈ {LONDON} |

**Risk:** $50/trade. **TPs:** 1/3 partials at 1R/2R/3R. **Time stop:** 50 bars.

## Per-Strategy Contribution (Corrected Cache)

| Strategy | TF | Trades | PF | Net $ | WR % | Outcome |
|---|---|---:|---:|---:|---:|---|
| KillzoneMomentum | M15 | 22 | 0.917 | -$50.00 | 45.5% | Near-breakeven, low signal count |
| DualTFSqueezePro | M15 | 406 | 0.852 | -$1,562.04 | 44.3% | **Dominates blend (92% of trades), negative PF** |
| DonchianATRTrendV2 | H1 | 0 | — | $0.00 | — | **Zero signals on current code** |
| SRMRPlus | M15 | 12 | 0.300 | -$350.00 | 16.7% | Severe degradation (was 57 trades, PF=1.80) |
| **Blend** | | **440** | **0.832** | **-$1,962** | **43.6%** | |

### Delta vs Original Per-Strategy

| Strategy | Original Trades | Re-validated Trades | Original PF | Re-val PF | Root Cause |
|---|---:|---:|---:|---:|---|
| KillzoneMomentum | 51 | 22 | 1.658 | 0.917 | Code drift: DST-aware hours, per-preset ADX gate, H4 filter, pip_value migration |
| DualTFSqueezePro | 13 | 406 | 1.937 | 0.852 | Stateful evaluate() diverges with on_bar() every bar; 31× more signals, mostly losing |
| DonchianATRTrendV2 | 49 | 0 | 1.735 | — | Strategy code produces zero signals on current implementation; `_bars_since_signal` counter never triggers |
| SRMRPlus | 57 | 12 | 1.803 | 0.300 | Code drift + corrected cache drastically reduces gate-accepted bars where signals fire |

---

## Walk-Forward Validation (5 OOS Windows)

Methodology: Split 71,747 M15 bars into 5 equal windows (~14,349 bars each). Run full 4-strategy blend on each window. Pass criteria: PF > 1.0 AND DD < 10%.

| Window | Period | Trades | PF | Net $ | DD % | Daily DD % | WR % | Pass |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| W1 | 2022-01-03 → 2022-08-15 | 91 | 0.642 | -$950 | 12.17% | 1.50% | 37.4% | ❌ |
| W2 | 2022-08-15 → 2023-03-27 | 73 | 1.206 | +$333 | 3.00% | 1.50% | 54.8% | ✅ |
| W3 | 2023-03-27 → 2023-11-06 | 82 | 0.479 | -$1,417 | 13.67% | 1.00% | 30.5% | ❌ |
| W4 | 2023-11-06 → 2024-06-19 | 101 | 1.037 | +$88 | 5.17% | 1.00% | 50.5% | ✅ |
| W5 | 2024-06-19 → 2025-01-31 | 93 | 0.993 | -$17 | 5.08% | 1.00% | 45.2% | ❌ |

**Result: 2/5 windows pass. Target: ≥4/5. ❌ WALK-FORWARD FAIL**

Only W2 and W4 show PF > 1.0. W3 is catastrophic (PF=0.479, DD=13.67%). The blend lacks temporal stability.

---

## Monte Carlo FTMO Simulation

**Method:** Bootstrap resampling (10,000 iterations) of 440 trades with replacement. Each simulation rebuilds the equity curve and checks FTMO criteria.

| Criterion | Required | Result |
|---|---|---|
| Profit ≥ $1,000 (10%) | Required | Median: -$1,969 |
| Total DD < 10% | Required | Almost always exceeded |
| Daily DD < 5% | Required | Usually passes (daily DD is low) |
| **Overall FTMO pass rate** | ≥ 90% | **0.2%** |

**Result: 0.2% pass rate. Target: ≥90%. ❌ MONTE CARLO FAIL**

---

## Root Cause Analysis

### Why the Original Result Changed

Two factors combined to invalidate the original PF=1.74:

### 1. Corrected Regime Cache (Bug #4)
The original cache used 60-bar windows for RegimeDetector, which needs ≥100 bars for full warmup. This caused QUIET/VOLATILE bars to be silently misclassified as TRENDING/CHOPPY. The corrected cache (100-bar precompute) changes which bars pass each strategy's gate:

| Strategy | Original Accepted Bars | Corrected Accepted Bars | Impact |
|---|---:|---:|---|
| KillzoneMomentum | 2,802 | 2,809 | ~Same |
| DualTFSqueezePro | 14,260 | 16,588 | +16% more bars |
| DonchianATRTrendV2 | 7,810 | 5,745 | -26% fewer bars |
| SRMRPlus | 3,780 | 3,776 | ~Same |

### 2. Strategy Code Drift
Multiple commits modified strategy code after the original study:

| Commit | Strategy | Change |
|---|---|---|
| f06bdf1 | KZ Momentum | DST-aware hours + per-preset ADX gate + H4 filter |
| 8840815 | KZ Momentum | pip_value migration |
| b514b0a | DualTF Squeeze Pro | Initial add + subsequent modifications |
| 0a89e37 | Donchian ATR v2 | Initial add + subsequent modifications |

**Impact on signal generation:**

| Strategy | Original Trades | Current Code Trades | Ratio |
|---|---:|---:|---:|
| KZ | 51 | 22 | 0.43× |
| DualTF | 13 | 406 | **31×** |
| Donchian | 49 | 0 | **0** |
| SRMR+ | 57 | 12 | 0.21× |

DualTFSqueezePro is the primary destroyer of value: it generates 31× more signals than the original study, and those signals have PF=0.852 (losing). This is likely because the stateful `evaluate()` behavior diverges when `on_bar()` is called every bar vs only on gate-accepted bars.

DonchianATRTrendV2 produces zero signals because the `_bars_since_signal` counter in its `evaluate()` method never reaches the trigger threshold under the current gate-first evaluation model.

### 3. Original Study Script Lost
The original gated blend study script is not in git history. The v7 script (`scripts/run_blend_5strat.py`) reproduces the methodology as documented but cannot match the original's exact signal counts due to strategy code drift.

---

## Recommendations

1. **Do not use original PF=1.74 for any viability claims.** The corrected result is PF=0.832, net negative.

2. **DualTFSqueezePro needs investigation.** It generates 406 signals (92% of blend trades) with PF=0.852. The stateful evaluate() divergence is the likely cause. Investigate whether the original 13-trade result was correct (gate-accepted only) or an artifact of the old buggy evaluate-on-all-bars model.

3. **DonchianATRTrendV2 needs debugging.** Zero signals on current code is a regression. The `_bars_since_signal` counter doesn't work correctly under gate-first evaluation.

4. **SRMRPlus signal count dropped 79%.** Only 12 trades vs original 57. Investigate whether the corrected cache or code drift is the primary cause.

5. **Strategy code needs freeze + re-baseline.** Before any new blend study, strategy code should be frozen and a clean baseline established with the corrected cache.

---

## Reproduction

```bash
# Full 4-strategy + 5-strategy blend backtest
cd $AYUMI_ROOT
python3 scripts/run_blend_5strat.py

# Walk-forward + Monte Carlo analysis
python3 scripts/run_blend_5strat.py  # provides baseline metrics
# Walk-forward and MC scripts written as ad-hoc analysis (see card 7318d89c)
```

Data files:
- Cache: `data/cache/labels_XAUUSD_M15_18ec1e70d282.pkl`
- Bars: DuckDB `data/ayumi_market.duckdb`, table `bars`, symbol XAUUSD
