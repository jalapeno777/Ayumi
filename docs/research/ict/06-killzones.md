# Killzones and Session Analysis

## Definition

Killzones are specific time windows during the trading day when institutional order flow is concentrated, resulting in higher volatility, clearer directional moves, and more reliable trading setups. ICT methodology emphasizes that not all hours are created equal — the majority of high-probability setups occur within these defined windows.

## Session Overview (All times in UTC)

### Asian Session (Tokyo)
- **Killzone:** 00:00 - 03:00 UTC
- **Peak:** 00:00 - 02:00 UTC
- **Characteristics:**
  - Lower volume than London/NY
  - Often establishes the daily range boundaries
  - Asian high and Asian low are key liquidity levels for later sessions
  - "True" Asian range: 00:00 - 06:00 UTC
- **ICT note:** The Asian session creates the range that London and NY will manipulate. Asian high/low are key liquidity targets.

### London Session
- **Killzone:** 07:00 - 10:00 UTC
- **Peak:** 07:30 - 09:30 UTC
- **Characteristics:**
  - Highest volume session alongside NY overlap
  - Often sweeps Asian high or low as the first move
  - Sets the directional tone for the day
  - MSS/CHoCH during London killzone is high probability
- **ICT note:** The London killzone is where institutions place their directional orders. Most daily trend moves begin here.

### New York Session
- **Killzone:** 12:00 - 15:00 UTC
- **Peak:** 12:30 - 14:30 UTC
- **Characteristics:**
  - Overlaps with late London (12:00 - 16:00 UTC)
  - London-NY overlap (12:00 - 16:00) is the highest volume window of the day
  - Often reverses or continues the London move
  - Major economic data releases during this window (NFP, CPI, FOMC)
- **ICT note:** NY killzone often "reclaims" or confirms the London move. Reversals from NY killzone are significant.

### London Close
- **Window:** 15:00 - 17:00 UTC
- **Characteristics:**
  - Liquidity drops as London traders close positions
  - Can see sharp reversals as positions are unwound
  - Less reliable for new entries, better for managing existing positions

### ICT Macro Times

ICT identifies specific minute marks within killzones where institutional orders are most active:

| Macro Time (UTC) | Session | Significance |
|-----------------|---------|-------------|
| 02:00 | Asian | Late Asian manipulation |
| 03:00 | Asian/London | Pre-London positioning |
| 08:00 | London | London open (primary) |
| 08:30 | London | Major UK data releases |
| 08:50 | London | London macro (ICT-specific) |
| 09:00 | London | Post-open continuation |
| 09:50 | London | London secondary macro |
| 10:00 | London | Killzone boundary |
| 12:00 | NY | NY open |
| 12:30 | NY | Major US data releases |
| 13:00 | NY | NY secondary |
| 14:00 | NY | NY tertiary |
| 14:30 | NY | NY macro (ICT-specific) |
| 15:00 | NY | NY killzone boundary |
| 16:00 | London Close | London session close |

## Algorithmic Implementation

```python
from datetime import time, datetime

KILLZONES = {
    "asian": {
        "start": time(0, 0),
        "end": time(3, 0),
        "peak_start": time(0, 0),
        "peak_end": time(2, 0),
        "weight": 0.6,
    },
    "london": {
        "start": time(7, 0),
        "end": time(10, 0),
        "peak_start": time(7, 30),
        "peak_end": time(9, 30),
        "weight": 1.0,
    },
    "new_york": {
        "start": time(12, 0),
        "end": time(15, 0),
        "peak_start": time(12, 30),
        "peak_end": time(14, 30),
        "weight": 0.9,
    },
}

MACRO_TIMES_UTC = [
    time(2, 0), time(3, 0), time(8, 0), time(8, 30),
    time(8, 50), time(9, 0), time(9, 50), time(10, 0),
    time(12, 0), time(12, 30), time(13, 0), time(14, 0),
    time(14, 30), time(15, 0), time(16, 0),
]

def is_in_killzone(timestamp_utc):
    t = timestamp_utc.time()
    for name, kz in KILLZONES.items():
        if kz["start"] <= t <= kz["end"]:
            return {
                "active": True,
                "session": name,
                "is_peak": kz["peak_start"] <= t <= kz["peak_end"],
                "weight": kz["weight"],
            }
    return {"active": False}

def is_macro_time(timestamp_utc, tolerance_minutes=5):
    t = timestamp_utc.time()
    for mt in MACRO_TIMES_UTC:
        diff = abs(datetime.combine(datetime.today(), t) -
                   datetime.combine(datetime.today(), mt)).total_seconds() / 60
        if diff <= tolerance_minutes:
            return True
    return False

def get_asian_range(candles, day_start_utc):
    asian_candles = [c for c in candles
                     if day_start_utc <= c.timestamp < day_start_utc + timedelta(hours=6)]
    if not asian_candles:
        return None
    return {
        "high": max(c.high for c in asian_candles),
        "low": min(c.low for c in asian_candles),
        "candles": asian_candles,
    }
```

## Killzone Confluence Model

Killzone timing adds probability weight to other ICT concepts:

| Setup | Without KZ | With KZ | Weight Boost |
|-------|-----------|---------|-------------|
| Order Block entry | Baseline | +15-20% | High |
| FVG fill | Baseline | +10-15% | Medium |
| Liquidity sweep reversal | Baseline | +20-25% | High |
| MSS/CHoCH confirmation | Baseline | +15-20% | High |

**Rule:** ICT methodology strongly recommends only taking entries during killzones. Entries outside killzones have significantly lower win rates.

## Quantifiable Criteria

| Parameter | Value |
|-----------|-------|
| Asian killzone | 00:00-03:00 UTC |
| London killzone | 07:00-10:00 UTC |
| NY killzone | 12:00-15:00 UTC |
| London-NY overlap | 12:00-16:00 UTC (highest volume) |
| Macro time tolerance | +/- 5 minutes |
| Minimum killzone candle size | 1.0x ATR(14) for displacement |
| Asian range validity | Used for London/NY sweep targets |
| Daylight saving adjustment | US/UK DST shifts affect session times |

## DST Considerations

Session times shift with daylight saving time changes:
- **US DST:** Second Sunday in March to first Sunday in November
- **UK/EU DST:** Last Sunday in March to last Sunday in October
- During the mismatch period (March last Sunday to November first Sunday), London-NY overlap shifts by 1 hour
- Algorithm must track DST state or use exchange calendar data

## Historical Examples (Major Pairs)

### EUR/USD — London Killzone Sweep of Asian Low (April 2025)
- Asian range: 1.0830 - 1.0850
- London killzone opens at 07:00 UTC
- Price sweeps below Asian low to 1.0825 at 07:45
- Reverses at 08:10 (macro time)
- Continues to 1.0890 through NY session
- Killzone sweep + SSL sweep confluence

### GBP/USD — NY Killzone MSS (March 2025)
- London session established bearish bias
- NY killzone opens at 12:00 UTC
- Bearish MSS confirmed at 12:30 (macro time + NFP data)
- Sharp move down from 1.2720 to 1.2650
- Killzone + macro time + news release confluence

### USD/JPY — Failed Asian Killzone Trade (April 2025)
- Setup looked valid during Asian killzone (00:00-03:00)
- FVG + OB confluence present
- But outside London/NY killzones, volume was insufficient
- Price never continued in expected direction
- Demonstrates the importance of killzone filtering

## Feasibility Assessment for Algorithmic Implementation

**Difficulty: Low**

### Strengths
- Time-based — completely objective, no pattern recognition needed
- Simple to implement (datetime comparison)
- Clear filtering criterion (in killzone vs. outside)
- Asian range calculation is straightforward
- DST handling is well-documented
- Provides immediate filtering value even without other ICT concepts

### Challenges
- DST transitions require careful handling (especially the US/UK mismatch period)
- Weekend/holiday sessions have different characteristics
- Killzone effectiveness varies by pair (EUR/USD and GBP/USD respond more than exotic pairs)
- Macro times are somewhat arbitrary — the 5-minute tolerance is a rough heuristic
- Killzone timing alone is not a trading signal — it's a filter, not an entry trigger
- News events can override killzone patterns entirely

### Recommended Approach
1. Implement killzone detection as a time-based filter
2. Calculate Asian range daily (00:00-06:00 UTC)
3. Flag Asian high/low as liquidity targets
4. Use killzone as a mandatory filter for all ICT entries
5. Implement macro time detection with configurable tolerance
6. Track DST state programmatically (use pytz or zoneinfo)
7. Add news calendar awareness — skip trades around major data releases unless intentionally trading the news

### Implementation Priority: HIGH
Killzones are trivial to implement and provide immediate filtering value. They should be one of the first filters added to any ICT strategy. The Asian range calculation is also important for liquidity sweep targeting.

### Key Metric for Backtesting
- **Killzone vs. non-killzone win rate:** measure the win rate difference
- **Per-session effectiveness:** London vs. NY vs. Asian
- **Macro time edge:** do entries at macro times outperform random killzone entries?
- **Asian range sweep rate:** how often does London/NY sweep the Asian H/L?
