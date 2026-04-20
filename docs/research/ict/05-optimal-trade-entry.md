# Optimal Trade Entry (OTE) — Fibonacci Retracement Zones

## Definition

OTE (Optimal Trade Entry) is ICT's framework for identifying the ideal price level to enter a trade using Fibonacci retracement levels. The core concept is that institutional traders use specific Fibonacci retracement zones — primarily the 0.62 to 0.79 range (62% to 79% retracement) — to place their orders during pullbacks in a trend.

## The OTE Zone

For a bullish trend (pullback in an uptrend):
- Measure the most recent significant swing low to swing high
- Apply Fibonacci retracement levels
- The OTE zone is between **0.62 (62%) and 0.79 (79%)** of the swing range
- This is where institutional buy orders are concentrated

For a bearish trend (pullback in a downtrend):
- Measure the most recent significant swing high to swing low
- Apply Fibonacci retracement levels
- The OTE zone is between **0.62 (62%) and 0.79 (79%)** of the swing range
- This is where institutional sell orders are concentrated

## Why 0.62-0.79?

The 0.62-0.79 range captures:
- **0.618 (Golden Ratio):** Classic Fibonacci retracement level
- **0.65-0.70:** Common institutional accumulation zone
- **0.786:** Deep Fibonacci retracement (square root of 0.618)
- **0.794:** ICT-specific "sweet spot" where maximum institutional interest occurs

This zone represents the "optimal" entry because:
- A shallower pullback (above 0.62) doesn't offer enough discount
- A deeper pullback (below 0.79) risks invalidating the trend structure
- The 0.62-0.79 range balances risk/reward optimally

## Identification Rules (Algorithmic)

```python
def calculate_ote(swing_low, swing_high, direction="bullish"):
    swing_range = swing_high - swing_low

    fib_levels = {
        0.0: swing_high if direction == "bullish" else swing_low,
        0.236: swing_high - 0.236 * swing_range if direction == "bullish" else swing_low + 0.236 * swing_range,
        0.382: swing_high - 0.382 * swing_range if direction == "bullish" else swing_low + 0.382 * swing_range,
        0.5: swing_high - 0.5 * swing_range if direction == "bullish" else swing_low + 0.5 * swing_range,
        0.618: swing_high - 0.618 * swing_range if direction == "bullish" else swing_low + 0.618 * swing_range,
        0.705: swing_high - 0.705 * swing_range if direction == "bullish" else swing_low + 0.705 * swing_range,
        0.786: swing_high - 0.786 * swing_range if direction == "bullish" else swing_low + 0.786 * swing_range,
        1.0: swing_low if direction == "bullish" else swing_high,
    }

    ote_zone = (fib_levels[0.786], fib_levels[0.618])  # (bottom, top) for bullish

    return {
        "fib_levels": fib_levels,
        "ote_zone": ote_zone,
        "ote_midpoint": (ote_zone[0] + ote_zone[1]) / 2,
        "swing_low": swing_low,
        "swing_high": swing_high,
    }

def check_ote_entry(current_price, ote, direction="bullish"):
    if direction == "bullish":
        return ote["ote_zone"][0] <= current_price <= ote["ote_zone"][1]
    else:
        return ote["ote_zone"][0] <= current_price <= ote["ote_zone"][1]
```

## OTE with Premium/Discount Arrays

OTE is most powerful when combined with premium/discount analysis:

- **Bullish OTE in Discount Zone:** Pullback into the lower 50% of the daily range AND into the 0.62-0.79 Fibonacci zone. This is the highest probability long setup.
- **Bearish OTE in Premium Zone:** Pullback into the upper 50% of the daily range AND into the 0.62-0.79 Fibonacci zone. This is the highest probability short setup.

## OTE with Order Blocks

The OTE zone often contains an order block. When they align:

1. Calculate OTE zone from recent swing
2. Identify order block within the OTE zone
3. If OB exists within OTE, the OB entry is preferred (more precise)
4. If no OB in OTE zone, use the 0.705 (OTE midpoint) as entry

## Quantifiable Criteria

| Parameter | Value |
|-----------|-------|
| OTE zone | 0.618 - 0.786 Fibonacci retracement |
| Optimal entry | 0.705 (midpoint of OTE zone) |
| Sweet spot | 0.794 (ICT premium entry) |
| Stop loss | Beyond 0.886 level (structure invalidation) |
| Minimum swing size | 50+ pips for majors on H1 |
| Maximum retracement | 0.886 before structure invalidated |
| Take profit | Previous swing extreme or 2:1 R:R |

## Fibonacci Level Reference

| Level | Name | Significance |
|-------|------|-------------|
| 0.0 | Swing extreme | Start of retracement |
| 0.236 | Shallow | Weak pullback zone |
| 0.382 | Moderate | Secondary institutional zone |
| 0.5 | Half | Psychological level |
| 0.618 | Golden Ratio | OTE boundary (shallow end) |
| 0.705 | OTE Midpoint | Optimal entry zone center |
| 0.786 | Deep Fib | OTE boundary (deep end) |
| 0.886 | Critical | Structure invalidation level |
| 1.0 | Full retracement | Trend invalidated |

## Historical Examples (Major Pairs)

### EUR/USD H1 — Bullish OTE (April 2025)
- Swing low: 1.0800, Swing high: 1.0890 (90 pip range)
- OTE zone: 1.0834 - 1.0848 (14 pip zone)
- Price retraced to 1.0838 (within OTE)
- Order block at 1.0835 provided additional confluence
- Entry at 1.0838, stop at 1.0825 (below 0.886 level)
- Target: 1.0890 (previous high) = 52 pip target, 13 pip risk
- R:R = 4.0:1

### GBP/USD H1 — Bearish OTE (March 2025)
- Swing high: 1.2760, Swing low: 1.2660 (100 pip range)
- Bearish OTE zone: 1.2722 - 1.2738 (16 pip zone)
- Price retraced to 1.2730 (within OTE)
- Entry at 1.2730, stop at 1.2750 (above 0.886 level)
- Target: 1.2660 = 70 pip target, 20 pip risk
- R:R = 3.5:1

### USD/JPY H1 — OTE Failure (April 2025)
- Swing low: 149.50, Swing high: 150.20 (70 pip range)
- OTE zone: 149.76 - 149.86
- Price entered OTE zone but broke below 0.886 (149.68)
- Structure invalidated — demonstrates why stop at 0.886 is critical

## Feasibility Assessment for Algorithmic Implementation

**Difficulty: Low**

### Strengths
- Fibonacci retracement is trivially easy to implement
- Objective, mathematical — no subjective interpretation
- Clear zone boundaries with defined entry/exit levels
- Combines well with other ICT concepts for confluence
- Stop loss and take profit levels are derived directly from the model
- Well-studied — extensive literature on Fibonacci in markets

### Challenges
- Which swing to use for the Fibonacci calculation is ambiguous
- Multiple swings at different degrees create overlapping Fibonacci zones
- Ranging markets produce frequent OTE "entries" that don't work
- The 0.62-0.79 zone is relatively wide — entry precision depends on other confluences
- OTE assumes a trend exists — in ranging markets, it generates false signals
- Requires accurate swing point identification (depends on market structure module)

### Recommended Approach
1. Use the most recent significant swing (swing that produced a structural break)
2. Calculate Fibonacci levels from that swing
3. Check if current price is within OTE zone
4. Require confluence: OTE + order block OR OTE + FVG for entry precision
5. Place stop at 0.886 Fibonacci level
6. Target the swing extreme (0.0 Fibonacci) for 2:1+ R:R
7. Add premium/discount zone filter for additional context

### Implementation Priority: HIGH
OTE is simple to implement and provides immediate value as an entry filter. It should be implemented alongside order blocks, as they naturally complement each other (OTE defines the zone, OB provides the precise entry).

### Key Metric for Backtesting
- **OTE zone hit rate:** how often price reaches the OTE zone during a trend pullback
- **OTE bounce rate:** of OTE zone touches, how many result in trend continuation
- **Optimal entry within OTE:** which sub-level (0.618, 0.705, 0.786) has the highest win rate
- **Confluence impact:** OTE+OB vs OTE alone win rate comparison
