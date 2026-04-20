# Order Blocks

## Definition

An order block is the last opposing candle before a strong impulsive move that breaks market structure. It represents a zone where institutional orders were placed, and price tends to return to these zones to fill remaining orders before continuing in the direction of the original impulse.

## Types

### Bullish Order Block

- Last bearish candle (red) before a bullish impulse that breaks structure to the upside
- The body of the candle (not the wick) defines the zone
- Entry: limit order at the 50% mark of the order block body, or at the open of the OB candle
- Stop loss: below the wick of the OB candle

### Bearish Order Block

- Last bullish candle (green) before a bearish impulse that breaks structure to the downside
- The body of the candle defines the zone
- Entry: limit order at the 50% mark of the order block body, or at the open of the OB candle
- Stop loss: above the wick of the OB candle

### Breaker Blocks

A breaker block forms when an order block is mitigated (price sweeps through it) and then continues in the original direction. The failed order block becomes a breaker block:

- A mitigated bullish OB that price sweeps below and then rejects becomes a bearish breaker
- A mitigated bearish OB that price sweeps above and then rejects becomes a bullish breaker
- These are higher-probability setups because the failed zone now acts as resistance/support

**Identification rules:**
1. Identify an order block that has been fully mitigated (price traded through the entire body)
2. Wait for a displacement move away from that zone
3. The former OB zone now acts as a breaker in the opposite direction
4. Entry on retracement to the breaker zone

### Mitigation Blocks

A mitigation block is a weaker form of order block where price only partially fills the zone before reversing:

- Price enters the OB zone but does not fully sweep the body
- The partial fill indicates institutional interest was absorbed
- These are valid but lower probability than unmitigated order blocks

## Identification Rules (Algorithmic)

```
For bullish OB:
1. Scan for bearish candle (C[i].close < C[i].open)
2. Next N candles must be bullish with displacement (close > high of prior swing)
3. The displacement must break previous swing high (MSS/CHoCH confirmation)
4. Mark candle i's [open, close] range as the OB zone
5. OB is valid until fully mitigated or invalidated by structure break

For breaker blocks:
1. Track all identified OBs
2. When price closes fully beyond an OB zone (mitigation)
3. AND subsequent displacement occurs away from that zone
4. Mark mitigated OB as breaker in opposite direction
```

## Quantifiable Criteria

| Parameter | Value |
|-----------|-------|
| Minimum displacement | 1.5x ATR(14) from OB zone |
| OB validity window | Until mitigated or 50+ candles on H1 |
| Breaker confirmation | Requires displacement > 1.0x ATR(14) post-mitigation |
| Entry precision | 50% of OB body (optimal), full body (conservative) |
| Stop loss distance | 1.5x OB body height or below OB wick |
| Take profit | Next structural high/low or 2:1 R:R minimum |

## Historical Examples (Major Pairs)

### EUR/USD H1 — Bullish OB (April 2025)
- Bearish candle at 1.0820-1.0835 range
- Subsequent bullish displacement to 1.0880 (55 pips, ~2x ATR)
- Price retraced to 1.0828 (50% of OB body) before continuing to 1.0920
- R:R = 3.2:1

### GBP/USD H1 — Breaker Block (March 2025)
- Bearish OB at 1.2680-1.2695 was mitigated
- Price swept to 1.2670 then displaced up to 1.2740
- Breaker zone at 1.2680-1.2695 acted as support
- Retracement to 1.2688 produced a 60-pip move to 1.2748

### USD/JPY H1 — Mitigation Block (April 2025)
- Bullish OB at 149.80-149.95
- Price retraced to 149.85 (partial fill) then reversed down
- Move continued to 149.40 (55 pips from entry)

## Feasibility Assessment for Algorithmic Implementation

**Difficulty: Medium**

### Strengths
- Clear, rule-based identification (last opposing candle before displacement)
- Well-defined zone boundaries (candle body range)
- Objective entry/exit levels can be calculated
- Works across timeframes with parameter adjustment

### Challenges
- Requires concurrent identification of market structure shifts (MSS/CHoCH) for validation
- Displacement threshold is subjective and varies by pair/volatility
- False order blocks are common on lower timeframes (noise)
- Breaker block identification requires tracking OB lifecycle (mitigation state)
- Multiple overlapping OBs create ambiguity in zone selection

### Recommended Approach
1. Implement on H1 timeframe minimum (M15 too noisy)
2. Require MSS/CHoCH confirmation before validating any OB
3. Use ATR-normalized displacement thresholds
4. Track OB lifecycle state machine: active -> mitigated -> breaker/expired
5. Prioritize unmitigated OBs over breaker blocks for initial implementation
6. Limit to top 2-3 most recent valid OBs per direction to avoid zone clutter

### Implementation Priority: HIGH
Order blocks are the foundational concept in ICT methodology. Most other concepts (FVG, liquidity sweeps) are validated or enhanced when they occur at or near order block zones.
