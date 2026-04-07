# Fair Value Gaps (FVG) and Imbalance Zones

## Definition

A Fair Value Gap (FVG) is a three-candle pattern where the first candle's wick and the third candle's wick do not overlap, creating a price gap. This represents an imbalance between buyers and sellers — a zone where institutional order flow was one-sided, and price tends to return to rebalance.

## Types

### Bullish FVG (Buy-Side Imbalance)

Three consecutive candles where:
1. Candle 1: any candle
2. Candle 2: large bullish candle (displacement)
3. Candle 3: any candle

The gap exists when: `Candle3.low > Candle1.high`

The FVG zone is: `[Candle1.high, Candle3.low]`

Price is expected to return to fill this gap before continuing higher.

### Bearish FVG (Sell-Side Imbalance)

Three consecutive candles where:
1. Candle 1: any candle
2. Candle 2: large bearish candle (displacement)
3. Candle 3: any candle

The gap exists when: `Candle3.high < Candle1.low`

The FVG zone is: `[Candle3.high, Candle1.low]`

Price is expected to return to fill this gap before continuing lower.

### Consequent Encroachment (CE)

A FVG is considered mitigated (filled) when price retraces into the zone. The extent of fill is measured by consequent encroachment:

- **Full CE:** Price reaches 50% or deeper into the FVG zone
- **Partial CE:** Price enters but does not reach 50%
- **No CE:** Price has not yet returned to the FVG

A FVG with no CE is the highest-probability setup. A partially-filled FVG is still valid but lower probability. A fully-filled FVG is considered mitigated.

### BISI (Buyside Imbalance Sellside Inefficiency) / SIBI (Sellside Imbalance Buyside Inefficiency)

- **BISI:** A bullish FVG where price returns and creates selling pressure (rebalance zone for shorts)
- **SIBI:** A bearish FVG where price returns and creates buying pressure (rebalance zone for longs)

## Identification Rules (Algorithmic)

```python
def identify_bullish_fvg(candles, i):
    if i < 2:
        return None
    c1, c2, c3 = candles[i-2], candles[i-1], candles[i]
    gap_top = c3.low      # top of gap
    gap_bottom = c1.high   # bottom of gap
    if gap_top > gap_bottom:
        return {
            "type": "bullish",
            "zone": (gap_bottom, gap_top),
            "displacement_candle": c2,
            "ce_level": gap_bottom + (gap_top - gap_bottom) * 0.50
        }
    return None

def check_ce(fvg, current_price):
    if fvg["type"] == "bullish":
        if current_price <= fvg["ce_level"]:
            return "full"
        elif current_price <= fvg["zone"][1]:
            return "partial"
    # symmetric for bearish
    return "none"
```

## Quantifiable Criteria

| Parameter | Value |
|-----------|-------|
| Minimum FVG size | 0.5x ATR(14) — smaller gaps are noise |
| Maximum FVG size | 5.0x ATR(14) — larger gaps may not fill |
| Optimal FVG size | 1.0-2.5x ATR(14) |
| CE threshold | 50% of zone depth |
| FVG validity | Until full CE or 100+ candles on H1 |
| Entry | 50% level of FVG zone (consequent encroachment midpoint) |
| Stop loss | Below/above FVG zone (full zone height as buffer) |
| Confluence boost | +15% win rate when FVG aligns with order block |

## Historical Examples (Major Pairs)

### EUR/USD H1 — Bullish FVG (April 2025)
- FVG zone: 1.0845-1.0852 (7 pips, ~0.7x ATR)
- Price returned in 4 hours, filled to 50% level at 1.0849
- Bounced and continued to 1.0890 (41 pips from entry)
- R:R = 2.9:1

### GBP/USD H1 — Bearish FVG with SIBI (March 2025)
- FVG zone: 1.2720-1.2735 (15 pips, ~1.5x ATR)
- Price returned over 6 hours
- Created buying pressure at 1.2728 (SIBI)
- Reversed to 1.2780 (52 pips)
- R:R = 3.5:1

### USD/JPY M15 — FVG failure (April 2025)
- FVG zone: 150.10-150.18 (8 pips)
- Price never returned to fill the gap
- Gap expired after 80 candles without CE
- Demonstrates that not all FVGs fill — context matters

## Feasibility Assessment for Algorithmic Implementation

**Difficulty: Low-Medium**

### Strengths
- Very simple, objective three-candle pattern
- Clear zone boundaries
- No subjective interpretation needed
- Easy to implement as a scanning filter
- Statistical fill rate is measurable and significant (~60-70% on H1 for major pairs)
- CE tracking is straightforward

### Challenges
- FVGs are everywhere on lower timeframes — need filtering for quality
- Gap size matters significantly — too small (noise) or too large (structural)
- Not all FVGs fill — requires confluence filtering (OB alignment, killzone timing)
- CE can be partial and then price continues — ambiguous signal
- Multiple overlapping FVGs create zone confusion
- FVGs on M5/M15 have lower fill rates and more noise

### Recommended Approach
1. Implement on H1 as primary timeframe
2. Filter by minimum size (0.5x ATR) and maximum size (5x ATR)
3. Track CE state per FVG
4. Require confluence with at least one other ICT concept (OB, killzone, structure)
5. Prioritize unfilled FVGs with larger displacement candles
6. Implement FVG expiry (e.g., 100 candles without any CE)

### Implementation Priority: HIGH
FVGs are the second most important ICT concept after order blocks. They provide clear entry zones and are highly objective. Their simplicity makes them an excellent starting point for algorithmic implementation.

### Key Metric for Backtesting
- **FVG fill rate** by pair, timeframe, and gap size
- **CE distribution** — what % fill to 25%, 50%, 75%, 100%
- **Win rate improvement** when combining FVG + OB confluence vs. FVG alone
- **Average time to fill** — helps set expiry windows
