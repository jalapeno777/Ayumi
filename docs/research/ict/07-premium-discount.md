# Premium and Discount Arrays

## Definition

Premium and Discount zones divide the price range of a given period into two halves, identifying whether price is at a premium (expensive, favorable for sellers) or discount (cheap, favorable for buyers). ICT methodology uses this to determine trade direction — buy in discount zones, sell in premium zones.

## Core Concept

For any given time period, calculate the range (high - low):

- **Equilibrium:** 50% of the range — the fair value midpoint
- **Premium Zone:** Above equilibrium (upper 50%) — price is expensive
- **Discount Zone:** Below equilibrium (lower 50%) — price is cheap

**Rule:** Buy in discount zones, sell in premium zones. Never buy in premium or sell in discount.

## Timeframe Applications

### Daily Premium/Discount

Most commonly used timeframe:
- Previous day's high and low define the range
- Equilibrium = (PDH + PDL) / 2
- Premium: above equilibrium toward PDH
- Discount: below equilibrium toward PDL

```python
def daily_premium_discount(pd_high, pd_low, current_price):
    equilibrium = (pd_high + pd_low) / 2
    range_size = pd_high - pd_low

    if current_price > equilibrium:
        premium_pct = (current_price - equilibrium) / range_size * 100
        return {
            "zone": "premium",
            "equilibrium": equilibrium,
            "premium_pct": premium_pct,
        }
    else:
        discount_pct = (equilibrium - current_price) / range_size * 100
        return {
            "zone": "discount",
            "equilibrium": equilibrium,
            "discount_pct": discount_pct,
        }
```

### Weekly Premium/Discount

- Previous week's high and low define the range
- Equilibrium = (PWH + PWL) / 2
- Used for swing trades and higher-timeframe bias

### Session Premium/Discount

- Killzone session high and low define the range
- Used for intraday precision
- Most useful during London and NY sessions

### Swing Premium/Discount

- Most recent significant swing high and low define the range
- More dynamic than daily/weekly — adapts to current market structure

## Advanced: Premium/Discount Arrays

ICT extends the basic premium/discount concept into arrays — multiple tiers of premium and discount zones:

### Three-Zone Array

```
PDH ───────────────────── Premium Zone (Top)
         │
EQ1 (75%) ─────────────── High Premium / Low Discount
         │
EQ (50%) ─────────────── Equilibrium
         │
EQ2 (25%) ─────────────── High Discount / Low Premium
         │
PDL ───────────────────── Discount Zone (Bottom)
```

| Zone | Range | Bias |
|------|-------|------|
| Deep Premium | 75% - 100% | Strong sell bias |
| Premium | 50% - 75% | Sell bias |
| Equilibrium | 45% - 55% | Neutral (avoid) |
| Discount | 25% - 50% | Buy bias |
| Deep Discount | 0% - 25% | Strong buy bias |

## Confluence Model

Premium/Discount analysis is a directional filter, not an entry signal. It combines with:

1. **Order Block in Discount:** OB + Discount = high probability long
2. **OTE in Discount:** OTE + Discount = optimal long entry
3. **Liquidity Sweep in Discount:** SSL sweep + Discount = strongest long signal
4. **FVG in Discount:** FVG fill + Discount = precision long entry
5. **MSS aligned with P/D zone:** Structural confirmation + P/D = highest probability

## Rejection Zones

ICT identifies specific areas within premium/discount where reversals are most likely:

### Buyside Rejection (in Premium)

When price is in premium and reaches an area of buying interest (e.g., equal highs, order block), the premium zone context suggests selling is higher probability. A "buyside rejection" occurs when buyers fail to push price higher from premium — a bearish signal.

### Sellside Rejection (in Discount)

When price is in discount and reaches an area of selling interest (e.g., equal lows, order block), the discount zone context suggests buying is higher probability. A "sellside rejection" occurs when sellers fail to push price lower from discount — a bullish signal.

## Quantifiable Criteria

| Parameter | Value |
|-----------|-------|
| Equilibrium | 50% of period range |
| Deep discount | 0-25% of period range |
| Deep premium | 75-100% of period range |
| Avoid zone | 45-55% (equilibrium +/- 5%) |
| Daily P/D calculation | Previous day's H/L |
| Weekly P/D calculation | Previous week's H/L |
| Minimum range | 50 pips for majors (smaller ranges = unreliable) |

## Algorithmic Implementation

```python
class PremiumDiscount:
    def __init__(self):
        self.daily_range = None
        self.weekly_range = None

    def update_daily(self, pd_high, pd_low):
        self.daily_range = {
            "high": pd_high,
            "low": pd_low,
            "equilibrium": (pd_high + pd_low) / 2,
            "size": pd_high - pd_low,
        }

    def get_zone(self, price, timeframe="daily"):
        r = self.daily_range if timeframe == "daily" else self.weekly_range
        if r is None or r["size"] < 50:  # minimum range filter
            return {"zone": "unknown", "confidence": 0}

        pct = (price - r["low"]) / r["size"] * 100

        if pct >= 75:
            return {"zone": "deep_premium", "pct": pct, "bias": "sell"}
        elif pct >= 55:
            return {"zone": "premium", "pct": pct, "bias": "sell"}
        elif pct >= 45:
            return {"zone": "equilibrium", "pct": pct, "bias": "neutral"}
        elif pct >= 25:
            return {"zone": "discount", "pct": pct, "bias": "buy"}
        else:
            return {"zone": "deep_discount", "pct": pct, "bias": "buy"}

    def is_valid_trade_direction(self, price, trade_direction, timeframe="daily"):
        zone = self.get_zone(price, timeframe)
        if trade_direction == "long":
            return zone["zone"] in ("discount", "deep_discount")
        elif trade_direction == "short":
            return zone["zone"] in ("premium", "deep_premium")
        return False
```

## Historical Examples (Major Pairs)

### EUR/USD — Long in Deep Discount (April 2025)
- PDH: 1.0870, PDL: 1.0800
- Equilibrium: 1.0835
- Price at 1.0812 (deep discount — 24% of range)
- Order block at 1.0810 provided entry
- Result: 78 pip move to 1.0890
- Premium/discount + OB confluence

### GBP/USD — Short in Deep Premium (March 2025)
- PDH: 1.2750, PDL: 1.2680
- Equilibrium: 1.2715
- Price at 1.2742 (deep premium — 89% of range)
- FVG at 1.2738 provided entry
- Result: 62 pip move to 1.2680
- Premium/discount + FVG confluence

### USD/JPY — Equilibrium Avoidance (April 2025)
- PDH: 150.20, PDL: 149.50
- Equilibrium: 149.85
- Price hovering at 149.82-149.88 (equilibrium zone)
- Multiple setups triggered but all failed
- Demonstrates why the 45-55% zone should be avoided

## Feasibility Assessment for Algorithmic Implementation

**Difficulty: Very Low**

### Strengths
- Extremely simple to implement — basic arithmetic
- Completely objective — no pattern recognition
- Provides immediate directional filtering
- Works on any timeframe
- No parameters to optimize beyond the timeframe selection
- Complements every other ICT concept

### Challenges
- Daily range resets at midnight — must handle rollover correctly
- Small daily ranges (< 50 pips) make premium/discount unreliable
- Ranging days can flip between premium/discount rapidly
- Equilibrium zone avoidance can filter out valid trades in strong trends
- Premium/discount from daily range may conflict with higher-timeframe structure

### Recommended Approach
1. Calculate daily premium/discount at the start of each trading day
2. Use as a mandatory directional filter for all entries
3. Avoid entries in the 45-55% equilibrium zone
4. Combine with weekly P/D for higher-timeframe confirmation
5. Require deep discount/premium for highest-conviction trades
6. Skip P/D filter entirely if daily range is below minimum threshold (50 pips)

### Implementation Priority: HIGH
Premium/Discount is the simplest ICT concept to implement and provides immediate filtering value. It should be one of the first modules built and applied as a universal directional filter.

### Key Metric for Backtesting
- **Directional accuracy:** does P/D zone correctly predict trade direction?
- **Deep zone edge:** deep discount/premium vs. regular discount/premium win rates
- **Equilibrium zone avoidance:** what is the failure rate in the 45-55% zone?
- **Minimum range threshold:** what is the optimal minimum daily range for reliable P/D?
