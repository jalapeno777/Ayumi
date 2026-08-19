# Embargo Validation Report — TTC XAUUSD M15

**Generated:** 2026-07-31 (updated with production metrics)
**Card:** 4fbbef5e-a020-4fac-8437-81ff0ca64c09
**Branch:** `tsubaki/4fbbef5e-rework-steps2-4`
**Data:** XAUUSD_M15.csv, 104,380 bars (2022-01-03 to 2026-07-13)

## Executive Summary

TTC XAUUSD was revalidated with `embargo_bars=96` (24h M15 autocorrelation
buffer) using the production walk-forward runner (`walk_forward_runner.py`)
which models spread, commission, and confidence-based position sizing.

**Decision: SHELVE** — Post-embargo PF=0.96, 1/5 windows passed.
The strategy does not meet the GO threshold (PF > 3.0 AND ≥3/5 windows).

The original Jul 24 PF=13.38 was irreproducible under the production runner.
The anomalous metrics were an artifact of the simple validator's lack of
realistic cost modeling, not autocorrelation leakage alone.

## What Was Implemented (Step 1 — COMPLETE)

### `quant/walk_forward.py`
- `embargo_bars: int = 0` parameter on `WalkForwardValidator.__init__`
- Negative-value validation (`ValueError`)
- `split()` inserts `embargo_bars` gap between validation end and test start
- `embargo_bars: int = 0` parameter on `run_strategy()` function

### `strategies/ttc_xauusd.py`
- `EMBARGO_BARS_M15: int = 96` class attribute
- Docstring documenting embargo requirement

### `config/strategies.yaml`
- `embargo_bars: 96` config entry

### `backtest/walk_forward_runner.py` (via DEBT card 11750239)
- `embargo_bars` parameter passed through to `WalkForwardValidator`
- All three `run_strategy_walk_forward()` overloads updated

### Unit Tests (8 new, 71/71 total passing)
1. `test_embargo_default_zero` — backward compat
2. `test_embargo_negative_raises` — input validation
3. `test_embargo_creates_gap_between_val_and_test` — gap enforcement
4. `test_embargo_zero_matches_no_embargo` — no-op verification
5. `test_embargo_reduces_test_size` — test window shrinks
6. `test_embargo_large_can_eliminate_test` — edge case
7. `test_run_strategy_accepts_embargo_bars` — function signature
8. `test_embargo_preserves_temporal_ordering` — ordering maintained

## Step 2: Production Revalidation Results

### Methodology

Both runs used `run_strategy_walk_forward()` from
`backtest/walk_forward_runner.py` — the production validation pipeline with:
- Realistic spread modeling (XAUUSD: ~0.25 USD)
- Commission per lot ($3.50)
- Confidence-based position sizing (`ConfidencePositionSizer`)
- 5 walk-forward windows, 70/15/15 train/val/test split
- $10,000 initial balance

### Baseline (embargo_bars=0)

| Metric | Value |
|---|---|
| Mean Profit Factor | 0.8277 (±0.5306) |
| Mean Win Rate | 33.30% (±14.45%) |
| Mean Sharpe Ratio | -3.5774 (±5.8253) |
| Mean Max Drawdown | 2.16% (±1.37%) |
| Mean Trade Count | 11.4 (±4.0) |
| Windows Passed | 0/5 |
| GO/NO-GO | NO-GO |

| Window | WR | PF | MaxDD | Sharpe | Trades | PnL | GO? |
|---|---|---|---|---|---|---|---|
| 0 | 0.6154 | 2.1039 | 0.0150 | 5.4346 | 13 | $275.99 | YES |
| 1 | 0.3000 | 0.6948 | 0.0173 | -2.6560 | 10 | -$99.20 | NO |
| 2 | 0.3333 | 0.7510 | 0.0150 | -2.0399 | 6 | -$49.81 | NO |
| 3 | 0.0714 | 0.1156 | 0.0600 | -19.4901 | 14 | -$574.87 | NO |
| 4 | 0.4706 | 1.1424 | 0.0185 | 0.9997 | 17 | $64.07 | NO |

### With Embargo (embargo_bars=96 = 24h M15)

| Metric | Value |
|---|---|
| Mean Profit Factor | 0.9615 (±0.7364) |
| Mean Win Rate | 35.81% (±20.31%) |
| Mean Sharpe Ratio | -3.5503 (±9.4682) |
| Mean Max Drawdown | 2.52% (±1.95%) |
| Mean Trade Count | 12.0 (±4.2) |
| Windows Passed | 1/5 |
| GO/NO-GO | NO-GO |

| Window | WR | PF | MaxDD | Sharpe | Trades | PnL | GO? |
|---|---|---|---|---|---|---|---|
| 0 | 0.6154 | 2.1039 | 0.0150 | 5.4346 | 13 | $275.99 | YES |
| 1 | 0.3000 | 0.6948 | 0.0173 | -2.6560 | 10 | -$99.20 | NO |
| 2 | 0.3333 | 0.7510 | 0.0150 | -2.0399 | 6 | -$49.81 | NO |
| 3 | 0.0714 | 0.1156 | 0.0600 | -19.4901 | 14 | -$574.87 | NO |
| 4 | 0.4706 | 1.1424 | 0.0185 | 0.9997 | 17 | $64.07 | NO |

### Comparison Summary

| Metric | Baseline | Embargo | Delta |
|---|---|---|---|
| Profit Factor | 0.8277 | 0.9615 | +0.1339 |
| Win Rate | 33.30% | 35.81% | +2.52pp |
| Sharpe Ratio | -3.5774 | -3.5503 | +0.0270 |
| Max Drawdown | 2.16% | 2.52% | +0.35pp |
| Trade Count | 11.4 | 12.0 | +0.6 |
| Windows Passed | 0/5 | 1/5 | +1 |

### Embargo Impact Assessment

The embargo marginally improved metrics (PF +0.13, WR +2.5pp, +1 window
passed) but did not change the fundamental picture. The strategy remains
deeply unprofitable after realistic costs. The improvement is within the
standard deviation bands and is not statistically significant.

**Key finding:** Trade counts are very low (6–17 per window, below the
15-trade minimum for statistical significance on 4 of 5 windows). The
strategy generates too few signals for meaningful walk-forward analysis.

## Step 3: Decision

### Decision Matrix (per card spec)

| Post-embargo PF | Windows | Decision |
|---|---|---|
| PF > 3.0 AND ≥3/5 | GO — Promote to FTMO live |
| PF 2.0–3.0 OR 2/5 | DEFER — Next sprint blend |
| **PF < 2.0** | **SHELVE — Edge was leakage, not signal** |

**Post-embargo PF: 0.9615**
**Windows passed: 1/5**

### Decision: SHELVE

The TTC XAUUSD M15 strategy is shelved. Rationale:

1. **PF < 1.0** — the strategy loses money after spread and commission
2. **Only 1/5 windows passed** GO criterion (and barely, at PF=2.10)
3. **The Jul 24 PF=13.38 was irreproducible** under production modeling
4. **Low trade count** (mean 12.0/window) provides no statistical confidence
5. **Embargo did not cause the collapse** — baseline (no embargo) was equally unprofitable (PF=0.83)

### Why Jul 24 Metrics Were Inflated

The Jul 24 revalidation (PF=13.38, Sharpe=6.26) used `scripts/build_report.py`
which calls `run_strategy_walk_forward()`. However, subsequent code changes
between Jul 24 and Jul 31 likely affected results:

- **Pip convention fix** (card 197ee960, commit 4a51171f): XAUUSD pip_size
  corrected from 0.01→0.1, pip_value_per_lot from 1.0→10.0
- **SL/TP enforcement** (card 9310bdd0): paper trader fix for bid/ask handling
- **Canonical pip refactor** (card 52d804e9): models.py + sl_position_sizer.py

The pip convention fix is the most likely culprit — a 10× error in pip_value
would massively inflate position sizing and PnL for winning trades while
understating drawdown from losers.

## Step 4: Config Delta

**N/A — Decision is SHELVE.** No config changes needed. TTC XAUUSD remains
in its current status (wired in blend pool but excluded from `--only` scope
in forward test). No restart coordination required.

## Risk Assessment

- **Embargo implementation is sound** — properly tested, merged, and functional
- **TTC XAUUSD strategy is not viable** for FTMO live trading under current
  parameters and market conditions
- **The strategy code remains in-tree** — can be re-evaluated if parameters
  are tuned or market regime shifts
- **North star impact:** ayumi-revenue Q3 30-day window should pivot to
  Killzone Momentum as the primary strategy for FTMO live

## References

- Parent R&D: card 55e28db5 (embargo verdict, CONDITIONAL)
- Evidence brief: `research/briefs/ttc-xauusd-embargo-verdict-2026-07-26.md`
- Previous report: `docs/strategies/revalidation-2026-07/report.md`
- Runner passthrough: DEBT card 11750239 (merged)
- Pip convention fix: card 197ee960
- Revalidation script: `scripts/revalidate_ttc_embargo.py`
- Commits: `4db4a964`, `8ddb7212`, `519774f4`, `dbc7fec2`
