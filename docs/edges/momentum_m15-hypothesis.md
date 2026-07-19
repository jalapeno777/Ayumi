# Edge Hypothesis: momentum_m15

## Strategy
N-bar range breakout on M15 with EMA50 trend filter and ADX≥20 gate.

## Edge Source
London/NY session range expansion — price breaks out of consolidated ranges with momentum confirmation. The EMA50 filter ensures we only trade in the direction of the prevailing trend, and ADX≥20 ensures sufficient directional movement.

## Why It Should Work
- M15 timeframe captures intraday momentum without M1/M5 noise
- Range breakouts are one of the oldest validated edges in FX
- EMA50 + ADX combo filters out choppy/ranging conditions where breakouts fail
- FTMO-compliant: 0.5% risk per trade, daily DD circuit breaker

## Why It Might Fail
- Breakout strategies can whipsaw in low-ADX environments
- EMA50 is lagging — may enter late on fast moves
- EURUSD M15 has tight ranges that may not produce enough ATR for clean stops

## Pairs
EURUSD, GBPUSD — major pairs with sufficient liquidity and range formation.

## Timeframe
M15 — balances signal frequency with noise reduction.

## Expected Performance Targets
- Win rate: ≥45%
- Profit factor: ≥1.3
- Max DD: ≤8%
- Profitable windows: ≥3/5
