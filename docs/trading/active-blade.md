# Active Blade — XAUUSD Regime-Gated Blend

**Single active edge.** All sprint compute budget goes here until the cycle exits.

## What It Is

XAUUSD regime-gated blend (current walk-forward PF 1.74). Composite of regime
detector + component signals (ttc_xauusd M15, donchian_atr_trend_v2, dual_tf_squeeze_pro)
weighted by detected regime (trending / ranging / volatile).

## Tuning Budget

**Bounded, deadline-free cycle. No "ship by Friday" pressure.**

- **N parameter-sets:** 24 candidates per cycle (3 regimes × 2 Sizing profiles × 4
  signal-weight ratios). Anything larger is overfit on 4 years of M15 data.
- **M walk-forward windows:** 4 windows per candidate. Window length 6 months,
  step 1 month, anchored at 2022-01. Total in-sample + out-of-sample coverage
  per candidate: 24 months.
- **Compute per candidate:** ≤12 hours wall on the dedicated runner. If it
  exceeds 12h, the candidate is dropped (timeout, not a parameter tweak).
- **Cycles per year:** ≤4 cycles. No more. Re-tuning more often is noise.

## Noise Guards

**No metric may be quoted until 30 live/paper trades have closed under the
candidate. Anything earlier is structural noise.**

- **30-trade minimum** applies to: PF, Sharpe, win-rate, max drawdown.
- **Pre-30-trade metrics are forbidden** in any card comment, slack message,
  or report. Even directional ("looking promising") is forbidden pre-30.
- **PF confidence interval** must be reported alongside PF point estimate.
  5-trade PF of 2.4 is meaningless — surface that.
- **Drawdown is a hard gate, not a metric.** If a candidate breaches -8% max DD
  on any walk-forward window, it is killed regardless of PF.

## Promotion Rule

**A second strategy earns its compute slot only after the active edge has
accumulated 1 live/paper quarter of clean receipts.**

Clean receipts means:
1. Order fills match signal intent (no orphan orders, no missed exits).
2. Slippage distribution matches backtest assumption (median within 0.5 pip of
   backtest, p95 within 1.5 pip).
3. Regime detector hit rate ≥70% on the live tape (matches backtest regime
   labels within tolerance).
4. No sev-2 or sev-1 incidents traceable to the active edge during the quarter.

If the quarter closes clean, ONE second strategy may enter evaluation under the
same 30-trade noise guard. The selection of which one is decided by Himari
triage + Craig approval — not by which has the prettiest backtest.

## Exit Criteria

The active cycle EXITS when any of:
1. A candidate passes all 4 walk-forward windows with PF ≥1.5, max DD ≤-5%,
   and 30+ live/paper trades clean. → Lock parameters. Cycle complete.
2. Six cycles (24 candidates × 4 windows) yield no passing candidate. → Kill
   the active edge. Pivot to next-best Hold-class strategy from `parked-strategies.md`.
3. The pip_value measurement bug is fixed AND a parked Hold-class strategy
   shows a backtest PF that beats the active edge by ≥0.3 in walk-forward. →
   Trigger Promotion Rule evaluation early.
4. Craig pulls the edge for any reason (strategic shift, capital allocation,
   FTMO rule change). → Document reason, archive to `docs/trading/ARCHIVED/`.

## What This Doc Does NOT Cover

- The pip_value/measurement plumbing unit-test harness (separate child card).
- The walk-forward validation runner implementation (separate child card).
- The parameter tuning cycle automation (separate child card).
- Promotion-rule scoring rubric (separate child card).

These four child cards are created under parent card 5aeb2d40 and remain
blocked behind this file + `parked-strategies.md` landing.
