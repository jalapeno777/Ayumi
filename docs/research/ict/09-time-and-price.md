# Time and Price Theory (Judas Swing, Macro Times)

## Definition

Time and price theory is ICT's framework for understanding how institutional traders use specific times and price levels to manipulate markets and execute large orders. The core principle is that institutional moves are deliberate and occur at predictable times and prices, creating exploitable patterns for informed traders.

## The Judas Swing

### Definition

The Judas Swing is ICT's name for the false directional move that occurs at the open of a major session (London or New York). It is a deliberate manipulation move designed to:

1. Trigger retail stop losses (create liquidity)
2. Induce retail traders to enter in the wrong direction
3. Provide the liquidity institutions need to fill their real positions
4. Then reverse in the true institutional direction

The name "Judas" refers to the betrayal — the initial move betrays the true market direction.

### Judas Swing Characteristics

- Occurs within the first 30-60 minutes of London or NY open
- Moves in the opposite direction of the true session trend
- Often sweeps a key liquidity level (Asian H/L, previous session H/L)
- Followed by a sharp reversal (the "true" move)
- The reversal displacement is typically larger than the Judas swing itself

### Bullish Judas Swing (False Sell-Off)

1. London/NY opens
2. Price drops sharply — sweeps below Asian low or recent swing low
3. Retail traders go short (trapped)
4. Short stops are triggered above when price reverses
5. Price reverses sharply upward — the true direction was bullish all along
6. The initial drop was the Judas Swing

### Bearish Judas Swing (False Rally)

1. London/NY opens
2. Price rallies sharply — sweeps above Asian high or recent swing high
3. Retail traders go long (trapped)
4. Long stops are triggered below when price reverses
5. Price reverses sharply downward — the true direction was bearish all along
6. The initial rally was the Judas Swing

### Algorithmic Detection

```python
from datetime import time, timedelta

def detect_judas_swing(candles, session_open_utc, window_minutes=60):
    session_candles = [
        c for c in candles
        if session_open_utc <= c.timestamp < session_open_utc + timedelta(minutes=window_minutes)
    ]

    if len(session_candles) < 3:
        return None

    first_hour_high = max(c.high for c in session_candles)
    first_hour_low = min(c.low for c in session_candles)
    initial_move = session_candles[0]
    current = session_candles[-1]

    initial_direction = "bullish" if initial_move.close > initial_move.open else "bearish"
    current_direction = "bullish" if current.close > current.open else "bearish"

    if initial_direction != current_direction:
        swing_size = abs(first_hour_high - first_hour_low)
        return {
            "judas_detected": True,
            "initial_direction": initial_direction,
            "true_direction": current_direction,
            "swing_size": swing_size,
            "session_open": session_open_utc,
        }

    return {"judas_detected": False}
```

## ICT Macro Times

### Definition

Macro times are specific minute marks during trading sessions when ICT theory suggests institutional algorithmic orders are triggered. These are not based on news releases but on internal institutional scheduling.

### Key Macro Times (UTC)

| Time | Session | ICT Name | Description |
|------|---------|----------|-------------|
| 08:00 | London | London Open | Primary session open |
| 08:50 | London | London Macro | ICT-specific institutional time |
| 09:00 | London | London 9AM | Post-open continuation |
| 09:50 | London | London Secondary | Secondary institutional time |
| 10:00 | London | London KZ End | Killzone boundary |
| 12:00 | NY | NY Open | Primary session open |
| 12:30 | NY | NY 12:30 | Major US data time |
| 13:00 | NY | NY 1PM | Secondary time |
| 14:00 | NY | NY 2PM | Tertiary time |
| 14:30 | NY | NY Macro | ICT-specific institutional time |
| 15:00 | NY | NY KZ End | Killzone boundary |

### Macro Time Significance

ICT traders watch for:
- **Displacement candles** forming at macro times
- **Reversals** occurring at macro times (end of institutional program)
- **MSS/CHoCH** confirmation at macro times
- **FVG creation** at macro times

The theory is that institutional trading algorithms are programmed to execute at these specific times, creating observable patterns.

## Silver Bullet

### Definition

The Silver Bullet is an ICT trade setup that combines time and price theory:

1. Wait for the 10:00-11:00 UTC London killzone close window
2. Wait for the 14:00-15:00 UTC NY killzone close window
3. Identify a displacement candle at or near these times
4. Enter in the direction of the displacement
5. Target the previous session's high or low

**The Silver Bullet specifically targets the reversal or continuation that occurs as institutional programs complete at the killzone boundary.**

## Time Theory: Day Types

ICT classifies trading days into types based on the expected price action:

| Day Type | Description | Expected Behavior |
|----------|-------------|-------------------|
| Trend Day | Strong directional move | Continuous move, few pullbacks |
| Range Day | Consolidation | Bounded range, reversals at boundaries |
| Reversal Day | Trend change | Sweeps previous day's H/L then reverses |
| Expansion Day | Volatility expansion | Large range, breaks previous structure |

### Algorithmic Day Type Detection

```python
def classify_day_type(candles, day_start):
    day_candles = [c for c in candles if c.timestamp.date() == day_start.date()]
    if not day_candles:
        return "unknown"

    day_high = max(c.high for c in day_candles)
    day_low = min(c.low for c in day_candles)
    day_range = day_high - day_low
    body_sum = sum(abs(c.close - c.open) for c in day_candles)
    net_direction = day_candles[-1].close - day_candles[0].open

    range_ratio = day_range / atr_14  # normalize by volatility

    if range_ratio > 2.5:
        return "expansion"
    elif abs(net_direction) / day_range > 0.7:
        return "trend"
    elif range_ratio < 1.0:
        return "range"
    else:
        return "range"
```

## Quantifiable Criteria

| Parameter | Value |
|-----------|-------|
| Judas swing window | First 30-60 minutes of session open |
| Minimum Judas swing size | 0.75x ATR(14) |
| Judas reversal confirmation | Close beyond session open price |
| Macro time tolerance | +/- 5 minutes |
| Silver Bullet window 1 | 10:00-11:00 UTC (London close) |
| Silver Bullet window 2 | 14:00-15:00 UTC (NY close) |
| Trend day threshold | Range > 2.5x ATR, net direction > 70% of range |
| Range day threshold | Range < 1.0x ATR |

## Historical Examples (Major Pairs)

### EUR/USD — London Judas Swing (April 2025)
- London open at 07:00 UTC
- Asian range: 1.0830-1.0850
- Price dropped to 1.0820 at 07:30 (Judas Swing — swept Asian low)
- Retail shorts entered
- Price reversed at 08:00 (London macro time)
- Displacement candle up to 1.0860 at 08:50
- Continued to 1.0890 through NY session
- Judas Swing + Asian Low sweep + Killzone reversal

### GBP/USD — NY Judas Swing (March 2025)
- NY open at 12:00 UTC
- London session high at 1.2740
- Price rallied to 1.2755 at 12:20 (Judas Swing — swept London high)
- Retail longs entered
- Price reversed at 12:30 (macro time)
- Dropped to 1.2680 by 14:00
- Judas Swing + London High sweep + Premium zone

### USD/JPY — Failed Judas Swing (April 2025)
- London open: price dropped 30 pips
- Looked like a Judas Swing setup
- But price continued lower — no reversal
- Demonstrates that not all initial moves are Judas Swings
- Requires structural context to validate

## Feasibility Assessment for Algorithmic Implementation

**Difficulty: Medium-High**

### Strengths
- Time-based detection is objective for macro times
- Judas Swing pattern is conceptually clear and well-defined
- Silver Bullet windows are specific and actionable
- Combines naturally with killzone analysis
- Day type classification adds contextual awareness

### Challenges
- Judas Swing detection requires the reversal to confirm — entry is delayed
- The "initial move" vs "true move" distinction can only be confirmed in hindsight
- Not every session open produces a Judas Swing — false positives are common
- Macro times are somewhat arbitrary — the evidence for specific minute marks is weak
- Day type classification is ambiguous — a day can transition between types
- Requires multiple confirmation layers, reducing the number of tradeable setups
- Judas Swing + Silver Bullet combined may produce very few signals

### Recommended Approach
1. Implement session open tracking (London 07:00 UTC, NY 12:00 UTC)
2. Track first-hour price action to detect potential Judas Swings
3. Require reversal confirmation (close beyond session open price)
4. Use killzone timing as the primary filter
5. Implement macro time detection as a confluence booster
6. Implement day type classification for contextual awareness
7. Silver Bullet can be implemented as a specific strategy variant
8. Do NOT rely on Judas Swing or Silver Bullet as standalone signals

### Implementation Priority: MEDIUM
Time and price theory adds contextual value but is not foundational. The Judas Swing concept is useful for understanding session dynamics but is difficult to trade algorithmically due to the confirmation delay. Implement after core ICT concepts (structure, OB, FVG, P/D, killzones) are working.

### Key Metric for Backtesting
- **Judas Swing frequency:** how often does a session open produce a Judas Swing pattern?
- **Judas Swing reversal rate:** of detected Judas Swings, what % produce a profitable reversal?
- **Macro time displacement rate:** how often do displacement candles form at macro times?
- **Silver Bullet win rate:** specific win rate for the 10:00-11:00 and 14:00-15:00 setups
- **Day type prediction accuracy:** can the day type be predicted from the first 2 hours?
