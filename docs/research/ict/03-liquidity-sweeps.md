# Liquidity Sweeps and Inducement

## Definition

Liquidity in ICT terminology refers to resting orders (stop losses, buy stops, sell stops, limit orders) clustered above swing highs and below swing lows. A liquidity sweep occurs when price intentionally moves beyond these levels to trigger these orders, providing the liquidity institutional traders need to fill their large positions — before reversing in the opposite direction.

Inducement is a related concept: a small move beyond a key level designed to lure retail traders into positioning in the wrong direction before the real move occurs.

## Types of Liquidity

### Buy-Side Liquidity (BSL)

- Resting orders above swing highs
- Stop losses from short positions clustered above recent highs
- Buy stop orders from breakout traders
- When swept, these become sell pressure (stops triggered = market sell orders)

### Sell-Side Liquidity (SSL)

- Resting orders below swing lows
- Stop losses from long positions clustered below recent lows
- Sell stop orders from breakdown traders
- When swept, these become buy pressure (stops triggered = market buy orders)

### Equal Highs / Equal Lows

- When two or more swing points form at approximately the same price level
- This creates an even larger pool of resting orders
- Sweeps of equal highs/lows are higher probability because more liquidity exists

### Internal / External Liquidity

- **Internal liquidity:** Swing points within the current range (smaller sweeps)
- **External liquidity:** Swing points beyond the current range / previous day/week highs and lows (larger sweeps, higher probability)
- ICT traders prefer targeting external liquidity for higher probability setups

## Sweep Identification Rules (Algorithmic)

```python
def identify_swing_highs(candles, lookback=5):
    highs = []
    for i in range(lookback, len(candles) - lookback):
        if candles[i].high >= max(c.high for c in candles[i-lookback:i+1]):
            if candles[i].high >= max(c.high for c in candles[i+1:i+1+lookback]):
                highs.append({"price": candles[i].high, "index": i})
    return highs

def detect_bsl_sweep(candles, swing_highs, sweep_threshold_pips=2):
    for sh in swing_highs:
        # Check if recent candle swept above the swing high
        for c in candles[sh["index"]+1:]:
            if c.high > sh["price"] + sweep_threshold_pips:
                # Check for reversal (sweep, not breakout)
                if c.close < sh["price"]:
                    return {
                        "type": "BSL_sweep",
                        "level": sh["price"],
                        "sweep_high": c.high,
                        "index": candles.index(c)
                    }
                break
    return None
```

## Inducement Patterns

### Equal Highs Inducement

1. Price forms two or more similar highs within a range
2. Retail traders see "resistance" and short
3. Price sweeps slightly above the equal highs
4. Short stops are triggered, creating buy-side liquidity
5. Price reverses lower — the retail shorts were the liquidity

### Internal Range Liquidity

1. Price is in a clear range with defined highs and lows
2. A move toward one side of the range but not beyond creates internal liquidity
3. Institutions use this as a stop hunt before the real directional move
4. The sweep of internal liquidity often precedes the break of the opposite side

### Stop Hunt Before Trend Continuation

1. Trend is established (e.g., bullish)
2. Price pulls back and sweeps below the most recent swing low
3. Long stops are triggered (SSL sweep)
4. This creates the buying pressure for trend continuation
5. Price reverses and makes new highs

## Quantifiable Criteria

| Parameter | Value |
|-----------|-------|
| Sweep threshold (H1) | 2-5 pips beyond level for majors |
| Sweep threshold (M15) | 1-3 pips beyond level for majors |
| Reversal confirmation | Close back below/above the swept level |
| Equal highs/lows tolerance | Within 3 pips for majors |
| External vs internal | External = previous day/week H/L |
| Entry after sweep | 50% of sweep candle body back toward the level |
| Stop loss | Beyond the sweep extreme (new high/low) |
| Minimum sweep candle size | 0.5x ATR(14) |

## Confluence Model

Liquidity sweeps gain significant probability when combined with:

1. **Order Block at the sweep level** — highest confluence
2. **FVG near the sweep zone** — entry precision
3. **Killzone timing** — sweeps during London/NY open are more reliable
4. **Premium/Discount array** — sweeping SSL in discount zone for longs
5. **Higher timeframe structure** — sweep aligned with HTF trend direction

## Historical Examples (Major Pairs)

### EUR/USD H1 — BSL Sweep (April 2025)
- Previous swing high at 1.0870
- Price swept to 1.0874 (4 pips above)
- Reversed and closed at 1.0862
- Entry at 1.0868 (50% of sweep candle)
- Continued down to 1.0825 (43 pips)
- R:R = 3.6:1

### GBP/USD H1 — Equal Highs Sweep (March 2025)
- Two swing highs at 1.2750 and 1.2752 (equal highs)
- Price swept to 1.2758
- Reversed and closed below 1.2750
- Entry at 1.2754
- Dropped to 1.2690 (64 pips)
- R:R = 5.3:1

### USD/JPY H1 — SSL Sweep in Discount (April 2025)
- In daily discount zone (below 50% of previous day's range)
- Swept below swing low at 149.60 to 149.55
- Reversed from discount + SSL sweep confluence
- Entry at 149.58
- Continued to 150.15 (57 pips)
- R:R = 4.8:1

## Feasibility Assessment for Algorithmic Implementation

**Difficulty: Medium-High**

### Strengths
- Swing high/low detection is algorithmically straightforward
- Reversal after sweep is a well-documented market microstructure phenomenon
- Equal highs/lows detection is objective
- Clear entry/exit framework
- High R:R potential (sweep targets are often the start of large moves)

### Challenges
- Distinguishing a sweep from a genuine breakout is the core difficulty
- "Sweep" vs "breakout" can only be confirmed in hindsight (close back beyond level)
- False sweeps are common — price sweeps, reverses briefly, then continues through
- Sweep threshold varies significantly by pair, volatility, and session
- Multiple swing levels create competing liquidity pools — which one gets swept?
- Requires real-time structure tracking to identify current swing highs/lows
- The "reversal confirmation" requirement means entries are delayed

### Recommended Approach
1. Implement swing point detection with configurable lookback (5-10 candles)
2. Track equal highs/lows with tolerance bands
3. Use close-based confirmation (not just wick-based) for sweep validation
4. Require confluence: sweep + OB/FVG at the level, or sweep + killzone timing
5. Implement sweep invalidation: if price closes beyond the level and continues, it was a breakout, not a sweep
6. Focus on H1+ timeframes; M15 sweeps are too noisy for initial implementation
7. Prioritize external liquidity sweeps (daily/weekly levels) over internal

### Implementation Priority: MEDIUM-HIGH
Liquidity sweeps are conceptually critical but algorithmically challenging due to the sweep/breakout disambiguation problem. Implement after order blocks and FVGs are working, then layer sweep detection as a confluence filter.

### Key Metric for Backtesting
- **True sweep rate:** % of level breaches that reverse vs. continue
- **Confluence impact:** win rate with sweep+OB vs. sweep alone
- **Sweep threshold optimization:** optimal pip distance beyond level by pair/timeframe
- **Session distribution:** do sweeps during killzones have higher reversal rates?
