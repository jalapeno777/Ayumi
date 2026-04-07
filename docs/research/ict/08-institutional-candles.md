# Institutional Candle Analysis

## Definition

Institutional candle analysis focuses on identifying specific candlestick patterns that indicate institutional participation — large market participants executing significant orders. Unlike traditional Japanese candlestick patterns, ICT institutional candles are characterized by their relationship to surrounding price action, their displacement magnitude, and their position within market structure.

## Key Candle Types

### Displacement / Propulsion Candle

A large-bodied candle that represents a strong institutional move:

**Identification rules:**
- Body size >= 1.5x ATR(14) for the timeframe
- Body-to-wick ratio >= 60% (body dominates the candle)
- Closes near the extreme of the candle (bullish: close near high; bearish: close near low)
- Usually follows a period of consolidation or a displacement in the opposite direction

**Significance:** Displacement candles indicate that a large institutional participant has entered the market aggressively. They are the "footprints" of smart money and often mark the beginning of a new directional move.

```python
def is_displacement_candle(candle, atr_14):
    body = abs(candle.close - candle.open)
    total_range = candle.high - candle.low

    return (
        body >= 1.5 * atr_14 and
        total_range > 0 and
        (body / total_range) >= 0.60 and
        abs(candle.close - (candle.high if candle.close > candle.open else candle.low)) < total_range * 0.25
    )
```

### Institutional Candle

A candle that closes above/below the previous candle's high/low AND the previous candle's close:

**Bullish institutional candle:**
- Close > previous high AND close > previous close
- Body size >= 0.75x ATR(14)
- Indicates institutional buying

**Bearish institutional candle:**
- Close < previous low AND close < previous close
- Body size >= 0.75x ATR(14)
- Indicates institutional selling

### Rejection Candle

A candle that tests a level and is rejected:

**Identification rules:**
- Long upper wick >= 2x body size (bearish rejection)
- Long lower wick >= 2x body size (bullish rejection)
- Occurs at a key level (OB, FVG, swing point, P/D zone boundary)
- Body size is relatively small compared to wick

**Significance:** Rejection candles at key levels indicate that institutional limit orders are resting at that level and absorbing market orders. A rejection at an order block in the discount zone is a high-probability setup.

### Momentum Shift Candle

A candle that changes the momentum of the market:

**Identification rules:**
- Opens in the direction of the trend but closes against it
- Body size >= 0.5x ATR(14)
- Occurs at a structural level (swing point, order block, FVG)
- First candle to break the sequence of trend-aligned candles

**Significance:** Indicates that institutional participants are changing their positioning. Often the first visible sign of a CHoCH or MSS before structural confirmation.

### Consolidation Break Candle

A candle that breaks out of a consolidation/range:

**Identification rules:**
- Range of the candle >= 1.2x the average range of the preceding N candles
- Body >= 1.0x ATR(14)
- Closes beyond the consolidation range
- N = typically 10-20 candles

## Candle Sequences

### Institutional Sequence (Bullish)

1. Consolidation (low volatility, ranging)
2. Displacement candle (bullish, large body)
3. Optional: small pullback (1-3 candles)
4. Continuation displacement
5. This sequence = institutional accumulation followed by distribution to the upside

### Institutional Sequence (Bearish)

1. Consolidation
2. Displacement candle (bearish, large body)
3. Optional: small pullback
4. Continuation displacement
5. This sequence = institutional distribution followed by selling pressure

### Manipulation Sequence

1. Small candles moving toward a key level
2. Displacement beyond the level (sweep)
3. Rejection candle or reversal displacement
4. This sequence = inducement followed by institutional reversal

## Quantifiable Criteria

| Parameter | Value |
|-----------|-------|
| Displacement minimum body | 1.5x ATR(14) |
| Displacement body-to-wick ratio | >= 60% |
| Institutional candle minimum body | 0.75x ATR(14) |
| Rejection wick-to-body ratio | >= 2:1 |
| Momentum shift minimum body | 0.5x ATR(14) |
| Consolidation break minimum range | 1.2x avg range of N candles |
| Consolidation window | 10-20 candles |

## Confluence with Other ICT Concepts

| Candle Type | Best Confluence |
|------------|-----------------|
| Displacement | Order block origin, MSS/CHoCH confirmation |
| Institutional candle | Killzone timing, premium/discount zone |
| Rejection candle | Order block level, FVG zone, equilibrium |
| Momentum shift | Structural level, OTE zone |
| Consolidation break | Killzone open, macro time |

## Historical Examples (Major Pairs)

### EUR/USD H1 — Displacement Candle Sequence (April 2025)
- 15-candle consolidation range (1.0820-1.0840)
- Bullish displacement candle: open 1.0830, close 1.0860 (30 pips = 2.0x ATR)
- Body-to-wick ratio: 85% (close near high)
- 2-candle pullback to 1.0848 (filled FVG)
- Continuation displacement to 1.0890
- Classic institutional sequence

### GBP/USD H1 — Rejection at Order Block (March 2025)
- Bearish order block at 1.2740-1.2755
- Price in premium zone (85% of daily range)
- Bearish rejection candle: wick to 1.2758, body 1.2740-1.2748
- Wick-to-body ratio: 2.25:1
- Price reversed to 1.2690
- Rejection + OB + Premium confluence

### USD/JPY H1 — Momentum Shift at Swing High (April 2025)
- Bullish trend with HH and HL
- Price reached swing high at 150.40
- Momentum shift candle: opened at 150.38 (bullish), closed at 150.10 (bearish)
- Body = 28 pips (0.7x ATR)
- This was the first sign of bearish CHoCH
- Followed by MSS confirmation 3 candles later

## Feasibility Assessment for Algorithmic Implementation

**Difficulty: Low-Medium**

### Strengths
- Candle analysis is based on OHLC data — universally available
- Displacement detection is straightforward (ATR-normalized threshold)
- Rejection candle identification is objective (wick-to-body ratio)
- Candle sequences provide temporal context beyond single candles
- Complements all other ICT concepts (OB, FVG, structure, etc.)
- No external data required

### Challenges
- ATR normalization required — displacement threshold varies by volatility
- Candle patterns are context-dependent — a rejection candle only matters at key levels
- Sequences require state tracking (consolidation detection, momentum direction)
- Lower timeframes (M5, M15) produce too many false displacement signals
- Wick data can be noisy on some data feeds
- Body-to-wick ratio thresholds need per-pair optimization

### Recommended Approach
1. Implement displacement detection with ATR normalization
2. Implement rejection candle detection with wick-to-body ratio
3. Implement institutional candle detection (close beyond previous H/L)
4. Track candle sequences: consolidation -> displacement -> continuation
5. Require level confluence: displacement from OB zone, rejection at FVG, etc.
6. Use H1+ timeframes for reliable detection
7. Combine with killzone timing — displacement during killzones is more significant

### Implementation Priority: MEDIUM
Institutional candle analysis is a useful addition but not foundational. It provides confirmation and context for other ICT concepts. Implement after market structure, order blocks, and FVGs are working. Use as a confluence booster rather than a primary signal.

### Key Metric for Backtesting
- **Displacement follow-through rate:** what % of displacement candles are followed by continuation?
- **Rejection candle accuracy:** what % of rejections at key levels produce reversals?
- **Sequence completion rate:** how often does consolidation -> displacement -> continuation complete?
- **Killzone displacement advantage:** displacement during killzone vs. outside
