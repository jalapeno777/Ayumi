# Ayumi Filter Chain Backtest Report — July 2026

## BQ-1042: ORB Filter Prioritization

**Date:** 2026-07-03
**Branch:** `autodev/orb-filter-chain-wiring`

## Overview

This report compares signal generation **with** vs **without** the FilterChain (ORB filter stage enabled at `min_score_threshold: 0.3`).

## Configuration

```yaml
filters:
  trend:
    enabled: true
    ema_fast_period: 9
    ema_slow_period: 21
    tolerance_pips: 0.0
  atr:
    enabled: true
  fvg:
    enabled: true
  orb:
    enabled: true
    min_score_threshold: 0.3
    breakout_min_fraction: 0.10
```

Filter priority order: trend (10) → ATR (20) → FVG (30) → ORB (40)

## Sample Data

10 simulated GBPUSD signals during London session with opening range:
- Range high: 1.2650
- Range low: 1.2600
- Average volume: 1500
- Test volume: 1200

## Results

| # | Direction | Entry   | ORB Score | Breakout Type | Chain Result |
|---|-----------|---------|-----------|---------------|--------------|
| 1 | long      | 1.2700  | 0.825     | breakout      | PASS         |
| 2 | long      | 1.2660  | 0.735     | breakout      | PASS         |
| 3 | long      | 1.2625  | 0.075     | inside        | REJECT       |
| 4 | short     | 1.2580  | 0.795     | breakout      | PASS         |
| 5 | short     | 1.2595  | 0.675     | pseudo        | PASS         |
| 6 | long      | 1.2640  | 0.075     | inside        | REJECT       |
| 7 | long      | 1.2750  | 0.825     | breakout      | PASS         |
| 8 | short     | 1.2550  | 0.825     | breakout      | PASS         |
| 9 | long      | 1.2651  | 0.555     | pseudo        | PASS         |
| 10| long      | 1.2600  | 0.075     | inside        | REJECT       |

## Summary

- **Signals without ORB filter:** 10
- **Signals with ORB filter (≥0.3):** 7
- **Filtered out:** 3 (30%)
- **Filter characteristics:** Removes inside-range signals (no breakout confirmation). Strong breakouts and pseudo-breakouts near edges pass through.

## Key Findings

1. **ORB filter adds meaningful selectivity** — 30% of low-quality signals removed
2. **Inside-range signals correctly rejected** — These have no directional conviction relative to the session range
3. **Pseudo-breakouts preserved** — Signals near the edge (but not beyond min fraction) still pass with moderate scores
4. **Direction alignment works** — Short signals below range low and long signals above range high score highest
5. **ORB filter fails open** — When no opening range is available (e.g., pre-session), signals pass through unchecked

## Integration Notes

- `build_chain_from_config()` in `filter_chain.py` reads the `filters:` section from `strategies.yaml`
- ORBFilter implements the IFilter interface: `priority`, `name`, `evaluate(**kwargs)`
- The orchestrator (`trading_orchestrator.py`) needs a one-line addition to call `chain.evaluate()` after confluence scoring — this file is NOT in the current card's allowed_files and requires a follow-up card for the actual call site wiring

## Limitations

- Sample size is small (10 synthetic signals) — production validation with live data recommended
- No historical win-rate comparison (requires live backtest runner execution)
- Volume data simulated at fixed 1200/bar — live volume varies
