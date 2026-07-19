# Edge Hypothesis: killzone_momentum_tuned

## Strategy
Killzone momentum breakout with relaxed parameters for FX pairs.

## Edge Source
Same as killzone_momentum — London/NY killzone breakout. Tuned variant lowers session range threshold and ADX gate for FX pairs where default gold-oriented params are too restrictive.

## Tuning Rationale
- `min_session_range_pips`: 8.0 → 4.0 (FX pairs have tighter ranges than XAUUSD)
- `breakout_lookback_bars`: 12 → 8 (catch earlier breakouts)
- `retest_tolerance_atr`: 1.0 → 1.5 (wider retest zone = more entries)
- `atr_breakout_multiplier`: 0.3 → 0.2 (smaller breakouts qualify)
- `adx_threshold`: 15.0 → 12.0 (less restrictive trend gate)

## Risk
Over-relaxing parameters may increase false signals. If results are worse than defaults, the edge doesn't exist on FX at these thresholds.

## Pairs
EURUSD, GBPUSD H1.

## Expected Performance Targets
- Win rate: ≥40%
- Profit factor: ≥1.2
- Trades per window: ≥15
- Profitable windows: ≥2/5
