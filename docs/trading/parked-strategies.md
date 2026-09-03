# Parked Strategies

**Status:** All non-active strategies are PARKED — no parameter tuning, no new data
fetches, no deployment work until the active XAUUSD regime-gated blend cycle exits.
This list is the authoritative kill ledger for sprint planning.

**Active edge (do NOT touch):** XAUUSD regime-gated blend (PF 1.74 in current
walk-forward). See `active-blade.md` for the bounded tuning cycle.

## Parked — Kill Class (PF < 1.0, not viable under any parameter regime)

| Strategy ID | Symbols | Reason for Park |
|-------------|---------|-----------------|
| `commodity_xauusd_raw` | XAUUSD | PF 0.45; WR 33.3% < 45% floor. Raw commodity model — superseded by regime-gated blend. |
| `statistical_arbitrage` | EURUSD | PF 0.62; cointegration assumption breaks on 2024 regime shift. |
| `session_range_mr_gbpusd` | GBPUSD | PF 0.89; mean-reversion window too short for current vol. |

## Parked — Hold (not yet evaluated under current regime)

The following strategies are *not* killed — they simply have not been re-evaluated
under the post-2024 regime. They will only be evaluated IF and when a second
strategy earns its compute slot per the promotion rule in `active-blade.md`.

- `srmr_plus` (EURUSD/GBPUSD/USDJPY/AUDUSD/USDCAD, H1)
- `bb_rsi_reversion` (EURUSD/GBPUSD/USDJPY/AUDUSD, H1+M15)
- `killzone_momentum` (EURUSD/GBPUSD/USDJPY/AUDUSD/XAUUSD, M15+H1)
- `momentum` raw (EURUSD, M15)
- `mtf_filtered_momentum` (EURUSD/GBPUSD/USDJPY, M15+H1+H4)
- `session_range_mr_ict_filtered` (EURUSD/GBPUSD/USDJPY/AUDUSD/USDCAD, H1+H4)
- `usdjpy_d1_trend` (USDJPY, D1)
- `session_range_mean_reversion` (EURUSD/GBPUSD, H1)
- `volatility_squeeze` (EURUSD/GBPUSD/USDJPY/AUDUSD/XAUUSD, H1+M15)
- `session_breakout_london` (GBPUSD/EURUSD, M15)
- `session_breakout_ny` (GBPUSD/EURUSD, M15)
- `session_breakout_asian` (USDJPY, M15)
- `ttc_xauusd` (XAUUSD, M15) — *note: component of active blend, NOT a separate edge*
- `donchian_atr_trend_v2` (XAUUSD/GBPUSD/EURUSD, M15+H1)
- `dual_tf_squeeze_pro` (XAUUSD/GBPUSD, M15+H1)

## Pip Value Measurement Plumbing — Known Bug

**Critical:** All pip_value / measurement-plumbing numbers in backtest reports
predating the unit-test harness card are SUSPECT. Until that harness lands, no
parked strategy may be re-evaluated — re-evaluation would compound the bug.

## Enforcement

No parked strategy may be touched until the active cycle exits. Card dependency
ordering enforces this — see `active-blade.md` § Promotion Rule.

## Update Procedure

This file is updated by **Reina** when:
1. A parked strategy moves to Active (rare; requires promotion rule satisfaction).
2. A new strategy is filed (added to Hold or Kill class by Himari triage).
3. A pip_value measurement bug is fixed (may unlock Hold class for re-evaluation).
