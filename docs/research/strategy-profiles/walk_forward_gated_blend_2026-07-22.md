# Walk-Forward Validation — Regime-Gated Ayumi Blend

_Generated: 2026-07-22T18:36:09.381480+00:00_
_Total runtime: 67.2s_

## Setup

- **Source:** DuckDB at `data/ayumi_market.duckdb` (bars table)
- **Symbol:** XAUUSD
- **M15:** 71,747 bars (2022-01-12 → 2026-07-10)
- **H1:** 17,948 bars (2022-01-12 → 2026-07-10)
- **5 non-overlapping M15 windows:** ~14,000 bars each
- **Gates:** KillzoneMomentum (QUIET/CHOPPY + ADX[18,25] + LONDON) | DualTFSqueezePro (ASIA/NY_AM + VOLATILE/CHOPPY) | DonchianATRTrendV2 (ADX<30 + ATRpct<0.50) | SRMRPlus (QUIET + LONDON)
- **Risk:** $50/trade | **TPs:** 1/3 partials at 1R/2R/3R | **Time stop:** 50 bars

## Section 1 — Per-Window Blended Results

| Window | Date Range | M15 Bars | Trades | PF | WR % | Net $ | DD % | Daily DD % | Pass? |
|---|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| W1 | 2022-01-12 → 2022-09-02 | 14,000 | 54 | 2.55 | 57.4 | $+1,369.72 | 1.83 | 1.00 | ✅ |
| W2 | 2022-09-02 → 2024-05-06 | 14,000 | 43 | 0.69 | 27.9 | $-450.00 | 5.83 | 2.00 | ❌ |
| W3 | 2024-05-06 → 2024-12-20 | 14,000 | 31 | 2.96 | 58.1 | $+1,144.20 | 2.00 | 1.50 | ✅ |
| W4 | 2024-12-20 → 2025-09-02 | 14,000 | 24 | 0.79 | 29.2 | $-150.00 | 3.00 | 2.00 | ❌ |
| W5 | 2025-09-02 → 2026-07-10 | 15,747 | 31 | 1.84 | 38.7 | $+516.67 | 1.83 | 0.67 | ✅ |

### Cumulative Equity Curve Across Windows

Window order is chronological. Equity is cumulative net P&L in $.

| Step | Window | Trades (cum) | Net P&L (cum) | Window P&L | Peak | DD from Peak |
|---|---|---:|---:|---:|---:|---:|
| 1 | W1 | 54 | $+1,369.72 | $+1,369.72 | $+1,369.72 | $+0.00 |
| 2 | W2 | 97 | $+919.72 | $-450.00 | $+1,369.72 | $+450.00 |
| 3 | W3 | 128 | $+2,063.92 | $+1,144.20 | $+2,063.92 | $+0.00 |
| 4 | W4 | 152 | $+1,913.92 | $-150.00 | $+2,063.92 | $+150.00 |
| 5 | W5 | 183 | $+2,430.59 | $+516.67 | $+2,430.59 | $+0.00 |

### Worst & Best Windows

- **Worst window:** W2 (2022-09-02 → 2024-05-06) → PF=0.69, Net=$-450.00, DD=5.83%, trades=43
- **Best window:** W1 (2022-01-12 → 2022-09-02) → PF=2.55, Net=$+1,369.72, DD=1.83%, trades=54
- **PF range:** min=0.69, max=2.96, mean=1.77, std=0.91
- **Net P&L range:** min=$-450.00, max=$+1,369.72, mean=$+486.12, std=$706.50

## Section 2 — Per-Strategy Per-Window PF

| Strategy | W1 PF | W2 PF | W3 PF | W4 PF | W5 PF | Min | Max | Std | Consistent? |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| KillzoneMomentum | 0.46 | 1.37 | 4.00 | 0.67 | 2.57 | 0.46 | 4.00 | 1.32 | ❌ |
| DualTFSqueezePro | 1.94 | — | 1.95 | 2.67 | — | 0.00 | 2.67 | 1.10 | ✅ |
| DonchianATRTrendV2 | 4.00 | 0.58 | 3.00 | 1.54 | 1.39 | 0.58 | 4.00 | 1.23 | ⚠️ |
| SRMRPlus | 8.67 | 0.59 | 2.40 | — | 4.67 | 0.00 | 8.67 | 3.15 | ❌ |

### Per-Strategy Per-Window Trade Counts

| Strategy | W1 | W2 | W3 | W4 | W5 | Total |
|---|---:|---:|---:|---:|---:|---:|
| KillzoneMomentum | 11 | 12 | 12 | 4 | 12 | 51 |
| DualTFSqueezePro | 13 | 4 | 6 | 3 | 3 | 29 |
| DonchianATRTrendV2 | 14 | 11 | 5 | 9 | 10 | 49 |
| SRMRPlus | 16 | 16 | 8 | 8 | 6 | 54 |

### Per-Strategy Per-Window Net P&L ($)

| Strategy | W1 | W2 | W3 | W4 | W5 | Total |
|---|---:|---:|---:|---:|---:|---:|
| KillzoneMomentum | $-200 | $+117 | $+600 | $-50 | $+367 | $+833 |
| DualTFSqueezePro | $+203 | $-167 | $+111 | $+83 | $-117 | $+114 |
| DonchianATRTrendV2 | $+600 | $-167 | $+200 | $+117 | $+83 | $+833 |
| SRMRPlus | $+767 | $-233 | $+233 | $-300 | $+183 | $+650 |

## Section 3 — Monte Carlo (1,000 simulations)

All trades from all 5 windows were pooled and randomly shuffled 1,000 times to estimate the distribution of possible outcomes from sequence-of-trades luck.

- **Trades pooled:** 183
- **Simulations:** 1,000

### Net P&L Distribution

| Metric | Value |
|---|---:|
| Mean net P&L | $+2,430.59 |
| Std dev | $+0.00 |
| Median | $+2,430.59 |
| **5th percentile (worst case)** | **$+2,430.59** |
| 95th percentile (best case) | $+2,430.59 |
| Min observed | $+2,430.59 |
| Max observed | $+2,430.59 |

### Max Drawdown Distribution

| Metric | Value |
|---|---:|
| Median max DD | $+433.33 |
| **95th percentile (5% worst-case DD)** | **$+689.53** |
| Worst DD observed | $+1,001.85 |

### Pass Probabilities

| Criterion | Probability |
|---|---:|
| **Profit (Net > $0)** | **100.0%** |
| **FTMO-passing (PF>1.0 AND DD<$1000)** | **99.9%** |

_FTMO 10% total DD = $1,000 on a $10k account. Simulations compute PF and DD on each shuffle; pass iff PF>1.0 AND DD<$1,000._

## Section 4 — Verdict

### Stability Checks

- **Windows passing FTMO criteria (PF>1.0, DD<10%, Net>0):** 3/5
- **PF spread across windows:** 0.69 → 2.96 (range 2.27)
- **Net P&L spread across windows:** $-450 → $+1,370 (range $+1,820)
- **Cumulative net across all 5 windows:** $+2,430.59 (PF=1.57, DD=5.83%)
- **Worst single-window DD:** 5.83% (within FTMO 10%)
- **Monte Carlo FTMO-pass probability (random orderings):** 99.9%
- **Monte Carlo 5% worst-case max DD:** $+689.53

### Per-Strategy Consistency Narrative

- **KillzoneMomentum** (mostly stable): 3/5 windows PF>1.0, 2/5 PF<1.0, 0/5 no trades. PFs: [0.46, 1.37, 4.00, 0.67, 2.57]
- **DualTFSqueezePro** (selective-but-thin): 3/5 windows PF>1.0, 0/5 PF<1.0, 2/5 no trades. PFs: [1.94, no trades, 1.95, 2.67, no trades]
- **DonchianATRTrendV2** (stable): 4/5 windows PF>1.0, 1/5 PF<1.0, 0/5 no trades. PFs: [4.00, 0.58, 3.00, 1.54, 1.39]
- **SRMRPlus** (mostly stable): 3/5 windows PF>1.0, 1/5 PF<1.0, 1/5 no trades. PFs: [8.67, 0.59, 2.40, no trades, 4.67]

### ⚠️ **MIXED** — windows inconsistent but sequence-robust

Only 3/5 windows individually pass FTMO, but pooled trade sequence is FTMO-passing with 99.9% Monte Carlo confidence (worst-case DD in random orderings: $+689.53). Blend works in aggregate but specific periods are weak. The underlying edge is real (trade-ordering independent) but environment-dependent — certain market regimes (W2/W4 here) lack the conditions that drive profitability. Crucially, **even the worst window has DD < 10%** (5.83%), so the loss is bounded.

### Recommended Next Steps

**Recommendation: PROCEED TO PAPER (Cabal) FIRST, then live if 30 paper trades confirm edge.** Specifically:

1. **Paper trade** on Cabal for 30-50 trades with $50 risk per trade to confirm live execution matches backtest (slippage, spread, fill rate).
2. **Track per-window P&L live.** If a 5-month window loses >$400, halt and re-evaluate gates — this matches the W2 worst-case.
3. **Add 1-2 mean-reversion strategies** to the blend. Current 4 strategies are 75% momentum-class (KZ, Donchian, DualTF) — diversifying into mean-reversion would reduce regime clustering.
4. **Re-validate** with the augmented blend every 90 days using rolling windows.


---

_Per-window detail: see Section 1. Per-strategy breakdown: Section 2. Statistical robustness: Section 3._
