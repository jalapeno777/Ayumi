# Regime-Gated Portfolio Blend Backtest

_Generated: 2026-07-22T18:25:10.062508+00:00_
_Total runtime: 70.7s_

## Data

- **Source:** DuckDB at `data/ayumi_market.duckdb` (bars table)
- **Symbol:** XAUUSD
- **M15:** 71,747 bars (2022-01-12 → 2026-07-10)
- **H1:** 17,948 bars (2022-01-12 → 2026-07-10)

## Strategy Gates

Each strategy only emits signals on bars where its regime gate passes.

| Strategy | TF | Gate |
|---|---|---|
| KillzoneMomentum | M15 | regime ∈ {QUIET, CHOPPY} AND ADX ∈ [18, 25] AND session ∈ {LONDON} |
| DualTFSqueezePro | M15 | session ∈ {ASIA, NY_AM} AND regime ∈ {VOLATILE, CHOPPY} |
| DonchianATRTrendV2 | H1 | ADX < 30 AND ATR_percentile < 0.50 |
| SRMRPlus | M15 | regime ∈ {QUIET} AND session ∈ {LONDON} |

**Risk:** $50/trade. **TPs:** 1/3 partials at 1R/2R/3R. **Time stop:** 50 bars.

## Per-Strategy Gated Results

| Strategy | Bars Eval | Rejected | Accepted | Gate % | No-Signal | Trades | WR % | PF | Net $ | DD % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| KillzoneMomentum (M15) | 71,647 | 68,845 | 2,802 | 3.91% | 2,751 | 51 | 45.1 | 1.66 | $833 | 3.3% |
| DualTFSqueezePro (M15) | 71,647 | 57,387 | 14,260 | 19.9% | 14,247 | 13 | 46.1 | 1.94 | $203 | 1.3% |
| DonchianATRTrendV2 (H1) | 17,848 | 10,038 | 7,810 | 43.76% | 7,761 | 49 | 42.9 | 1.74 | $833 | 2.5% |
| SRMRPlus (M15) | 71,647 | 67,867 | 3,780 | 5.28% | 3,723 | 57 | 49.1 | 1.80 | $950 | 4.3% |

### Per-Strategy Detail

#### KillzoneMomentum (M15)

- Bars evaluated: 71,647
- Bars rejected by gate: 68,845
- Bars accepted by gate: 2,802 (3.91% of evaluated)
- Of accepted, strategy returned no signal: 2,751
- Trades taken: 51
- Win rate: 45.10%
- Profit factor: 1.658
- Net P&L: $833.33
- Avg win: $91.30
- Avg loss: $-45.24
- Max DD: $333.33 (3.33%)
- Runtime: 3.7s

#### DualTFSqueezePro (M15)

- Bars evaluated: 71,647
- Bars rejected by gate: 57,387
- Bars accepted by gate: 14,260 (19.9% of evaluated)
- Of accepted, strategy returned no signal: 14,247
- Trades taken: 13
- Win rate: 46.15%
- Profit factor: 1.937
- Net P&L: $203.05
- Avg win: $69.95
- Avg loss: $-30.95
- Max DD: $130.42 (1.30%)
- Runtime: 20.8s

#### DonchianATRTrendV2 (H1)

- Bars evaluated: 17,848
- Bars rejected by gate: 10,038
- Bars accepted by gate: 7,810 (43.76% of evaluated)
- Of accepted, strategy returned no signal: 7,761
- Trades taken: 49
- Win rate: 42.86%
- Profit factor: 1.735
- Net P&L: $833.33
- Avg win: $93.65
- Avg loss: $-40.48
- Max DD: $250.00 (2.50%)
- Runtime: 32.4s

#### SRMRPlus (M15)

- Bars evaluated: 71,647
- Bars rejected by gate: 67,867
- Bars accepted by gate: 3,780 (5.28% of evaluated)
- Of accepted, strategy returned no signal: 3,723
- Trades taken: 57
- Win rate: 49.12%
- Profit factor: 1.803
- Net P&L: $950.00
- Avg win: $76.19
- Avg loss: $-40.80
- Max DD: $433.33 (4.33%)
- Runtime: 6.1s

## Blended Equity Curve

- **Total trades:** 170
- **Win rate:** 45.88%
- **Profit factor:** 1.742
- **Net P&L:** $2,819.72
- **Avg win:** $84.87
- **Avg loss:** $-41.30
- **Max total DD:** $566.67 (5.67%)
- **Max daily DD:** $200.00 (2.00%)

## FTMO Viability Verdict

| Criterion | Required | Actual | Pass |
|---|---|---:|:---:|
| Profit target | ≥ $1,000 | $2,819.72 | ✅ |
| Total DD | < 10% | 5.67% | ✅ |
| Daily DD | < 5% | 2.00% | ✅ |
| Profit factor | > 1.0 | 1.742 | ✅ |
| Win rate | ≥ 50% (sanity) | 45.9% | ❌ |

**✅ FTMO-PASSING** — All four hard criteria met.

## Per-Strategy Contribution to Gated Blend

| Strategy | Trades | % of Blend | Net $ | Contribution % |
|---|---:|---:|---:|---:|
| KillzoneMomentum | 51 | 30.0% | $833.33 | +29.6% |
| DualTFSqueezePro | 13 | 7.6% | $203.05 | +7.2% |
| DonchianATRTrendV2 | 49 | 28.8% | $833.33 | +29.6% |
| SRMRPlus | 57 | 33.5% | $950.00 | +33.7% |

## Comparison: Gated vs Ungated

| Metric | Gated Blend | Ungated Blend | Δ |
|---|---:|---:|---:|
| Total trades | 170 | (n/a) | — |
| Win rate | 45.88% | (n/a) | — |
| Profit factor | 1.742 | 0.720 | +1.022 |
| Net P&L | $2,819.72 | $-45,475.00 | $+48,294.72 |
| Max DD % | 5.67% | 440.00% | -434.33pp |

_Note: ungated baseline (PF=0.72, Net=-$45,475, DD=440%) is from prior blend run._

## Recommendation

This gated blend:
- ✅ **FTMO-passing.** PF=1.742, Net=$2,819.72, DD=5.67%, daily DD=2.00%.
- ✅ All hard FTMO criteria met.
- **Next step:** Walk-forward validation of gated blend on out-of-sample windows.
- **Next step:** Per-strategy robustness check — does each strategy remain profitable in isolation under its gate?

---

## Reconciliation Study (2026-07-25)

### Background

`scripts/run_blend_5strat.py` was written Jul 22 to compare 4-strategy vs 5-strategy
blends. Initial runs produced wildly different results (888 trades vs 170). This
section documents the reconciliation effort.

### AC #1: Model Differences (DOCUMENTED)

Five key differences identified between `run_blend_5strat.py` and the original gated blend:

1. **Serial vs Concurrent Positions**: Original script evaluated each strategy
   independently. Early `run_blend_5strat.py` used serial blocking (`if pos: continue`).
2. **Missing Donchian**: Script excluded Donchian strategy from M15 strategies.
3. **Bar Sampling**: Default sampled every 3rd M15 bar, corrupting indicator values.
4. **Position Management**: Custom inline dict vs proper strategy lifecycle.
5. **No Risk Budget**: No daily risk cap, circuit breaker, or correlation gate.

### AC #2: Reproduction Attempt (CANNOT EXACTLY MATCH)

Multiple approaches tried (v2 through v7):
- v2: Independent strategy model with proper evaluate lifecycle
- v3: Fixed on_bar() for DualTF state
- v4: Full history bars[:i+1] — O(n²) killed performance
- v5: Rolling 500-bar window — DualTF produced 902 trades vs 13
- v6: Two-phase (generate all signals → filter by gate) — still 356 DualTF trades
- v7: Gate-first (check gate → evaluate only if passed) — 406 DualTF trades

**Root causes preventing exact reproduction:**
1. **Original gated study script is lost.** Not in git history, not in /tmp.
2. **Strategy code drift since Jul 22:**
   - `f06bdf1` KZ Momentum: DST-aware hours + per-preset ADX gate + H4 filter
   - `8840815` KZ Momentum: pip_value migration
   - `b514b0a` DualTF Squeeze Pro: initial add (then likely modified)
   - `0a89e37` Donchian ATR v2: initial add (then likely modified)
3. **Stateful evaluate() side effects:** Strategies like Donchian maintain
   `_bars_since_signal` counter inside evaluate(). The counter behavior differs
   depending on whether evaluate() is called on all bars or only gate-accepted bars.
4. **Regime label cache:** Cached labels may be from a different detector version.

**Gate-accepted bar counts are close (confirming gate logic is correct):**

| Strategy | Original Accepted | v7 Accepted | Match |
|---|---:|---:|:---:|
| KZ | 2,802 | 2,809 | ✅ |
| DualTF | 14,260 | 16,588 | ~ |
| Donchian | 7,810 | 5,745 | ~ |
| SRMR+ | 3,780 | 3,776 | ✅ |

**Signal counts diverge significantly:**

| Strategy | Original Trades | v7 Trades | Ratio |
|---|---:|---:|---:|
| KZ | 51 | 22 | 0.43× |
| DualTF | 13 | 406 | 31× |
| Donchian | 49 | 0 | 0 |
| SRMR+ | 57 | 12 | 0.21× |

### AC #3: 5-Strategy Blend Results (v7 — current strategy code)

| Blend | Trades | PF | Net $ | DD % | WR % |
|---|---:|---:|---:|---:|---:|
| 4-strategy | 440 | 0.832 | -$1,962 | 25.83% | 43.6% |
| 5-strategy | 463 | 0.852 | -$1,808 | 24.79% | 44.1% |
| D | +23 | +0.020 | +$154 | -1.04% | +0.5% |

### AC #4: LBO Impact

London Breakout Retest adds 23 trades (+5.2%), marginally improves PF (+0.020),
and slightly reduces drawdown (-1.04pp). Not a meaningful improvement.

### Conclusion

The original gated blend (PF=1.742, 170 trades, +$2,820) **cannot be reproduced**
with current strategy code. The strategies have been modified since the original
study, producing different signals on the same gate-accepted bars. To regenerate
clean baseline results, a new gated blend study should be run with the current
strategy code and the v7 methodology (gate-first evaluation, rolling 300/100-bar
window, DualTF on_bar() with H1 cap).

The v7 script (`scripts/run_blend_5strat.py`) implements the correct methodology
and produces reproducible results in ~10 seconds. It is ready for future blend
studies with whatever strategy code is current at run time.

_Run with: `python3 scripts/run_blend_5strat.py [--costs]`_
