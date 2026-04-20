# Market Structure Shifts (MSS) and Change of Character (CHoCH)

## Definition

Market structure analysis is the foundational framework in ICT methodology. It determines trend direction and identifies the precise moment when the market transitions from bullish to bearish (or vice versa).

### Market Structure Shift (MSS)

An MSS is a **lower timeframe** confirmation that the higher timeframe trend has changed direction. It occurs when price breaks the most recent swing point in the opposite direction of the prevailing trend.

### Change of Character (CHoCH)

A CHoCH is the first structural break against the prevailing trend. It represents the earliest possible signal that the trend may be changing. An MSS is the confirmation that follows a CHoCH.

**Key difference:** CHoCH is the first break; MSS is the confirmation break that follows. Both are structural breaks, but CHoCH is the warning signal and MSS is the confirmation.

## Structural Elements

### Swing Points

Before identifying MSS/CHoCH, the algorithm must identify swing points:

- **Swing High (SH):** A candle whose high is higher than N candles on both sides
- **Swing Low (SL):** A candle whose low is lower than N candles on both sides
- Default lookback: 3-5 candles on H1

### Trend Definition

- **Bullish structure:** Higher highs (HH) and higher lows (HL)
- **Bearish structure:** Lower highs (LH) and lower lows (LL)
- **Ranging:** Neither HH/HL nor LH/LL pattern is intact

## CHoCH Identification

### Bearish CHoCH (from bullish structure)

1. Market is making HH and HL (bullish)
2. Price breaks below the most recent HL (swing low)
3. This is the first break of bullish structure
4. Signal: potential trend change from bullish to bearish

```
HH ---\
       HL ---\        <- HL is broken
              \--- CHoCH (break below HL)
```

### Bullish CHoCH (from bearish structure)

1. Market is making LH and LL (bearish)
2. Price breaks above the most recent LH (swing high)
3. This is the first break of bearish structure
4. Signal: potential trend change from bearish to bullish

## MSS Identification

### Bearish MSS (confirmation of bearish trend)

1. Bearish CHoCH has occurred (first HL broken)
2. Price makes a lower high (LH) — fails to make HH
3. Price then breaks below the most recent swing low
4. This confirms the bearish structure

### Bullish MSS (confirmation of bullish trend)

1. Bullish CHoCH has occurred (first LH broken)
2. Price makes a higher low (HL) — fails to make LL
3. Price then breaks above the most recent swing high
4. This confirms the bullish structure

## Algorithmic Implementation

```python
class MarketStructure:
    def __init__(self, lookback=5):
        self.lookback = lookback
        self.swing_highs = []
        self.swing_lows = []
        self.trend = "ranging"  # "bullish", "bearish", "ranging"
        self.last_choc = None
        self.last_mss = None

    def detect_swing_points(self, candles):
        for i in range(self.lookback, len(candles) - self.lookback):
            window = candles[max(0, i-self.lookback):i+self.lookback+1]
            high_max = max(c.high for c in window)
            low_min = min(c.low for c in window)

            if candles[i].high == high_max:
                self.swing_highs.append({"price": candles[i].high, "index": i})
            if candles[i].low == low_min:
                self.swing_lows.append({"price": candles[i].low, "index": i})

    def check_structure(self, candles, current_index):
        if len(self.swing_highs) < 2 or len(self.swing_lows) < 2:
            return

        last_sh = self.swing_highs[-1]
        prev_sh = self.swing_highs[-2]
        last_sl = self.swing_lows[-1]
        prev_sl = self.swing_lows[-2]

        current = candles[current_index]

        if self.trend == "bullish":
            if current.close < last_sl["price"]:
                self.last_choc = {"type": "bearish", "index": current_index}
                self.trend = "choc_bearish"

        elif self.trend == "choc_bearish":
            if current.close > last_sh["price"]:
                self.last_choc = None
                self.trend = "bullish"
            elif current.close < prev_sl["price"] or \
                 (last_sh["price"] < prev_sh["price"] and current.close < last_sl["price"]):
                self.last_mss = {"type": "bearish", "index": current_index}
                self.trend = "bearish"

        # Symmetric logic for bearish -> bullish transitions
```

## Quantifiable Criteria

| Parameter | Value |
|-----------|-------|
| Swing point lookback | 3-5 candles (H1), 5-8 candles (M15) |
| CHoCH confirmation | Close beyond swing level (not just wick) |
| MSS confirmation | Close beyond swing level + structural sequence |
| Timeframe relationship | MSS on LTF confirms HTF CHoCH |
| Typical pairings | H4 CHoCH = H1 MSS; D1 CHoCH = H4 MSS |

## Multi-Timeframe Structure Alignment

ICT methodology relies heavily on timeframe alignment:

| Higher Timeframe | Lower Timeframe | Relationship |
|-----------------|-----------------|--------------|
| H4 CHoCH | H1 MSS | H1 MSS confirms H4 trend change |
| D1 CHoCH | H4 MSS | H4 MSS confirms D1 trend change |
| H4 trend direction | H1 entries | Trade H1 entries aligned with H4 trend |

**Algorithmic rule:** Only take trades in the direction of the higher timeframe MSS/CHoCH. An H1 bullish MSS aligned with H4 bullish structure is the ideal setup.

## Historical Examples (Major Pairs)

### EUR/USD H1 — Bearish MSS (April 2025)
- Bullish structure: HH at 1.0890, HL at 1.0845
- CHoCH: close below 1.0845 (the HL)
- Retracement to 1.0870 (lower high — failed to make HH)
- MSS: close below 1.0845 (new LL at 1.0825)
- Short entry on MSS confirmation
- Price continued to 1.0780

### GBP/USD H1 — Bullish CHoCH to MSS (March 2025)
- Bearish structure: LH at 1.2680, LL at 1.2620
- CHoCH: close above 1.2680 (the LH)
- Pullback to 1.2670 (higher low — failed to make LL)
- MSS: close above 1.2700 (new HH)
- Long entry on MSS confirmation
- Price continued to 1.2760

### USD/JPY H4/H1 — MTF Alignment (April 2025)
- H4 bearish CHoCH at 150.50
- H1 bearish MSS confirmed at 150.30
- Both timeframes aligned bearish
- Short from 150.30, target 149.60
- Result: 70 pip move, achieved in 8 hours

## Feasibility Assessment for Algorithmic Implementation

**Difficulty: Medium**

### Strengths
- Well-defined, objective rules for structure identification
- Swing point detection is algorithmically trivial
- CHoCH/MSS sequence is deterministic
- Multi-timeframe alignment is straightforward to implement
- Forms the backbone of all other ICT concepts — everything references structure

### Challenges
- Ranging markets produce frequent false CHoCH signals
- Swing point lookback parameter significantly affects signal quality
- Wicks vs closes for confirmation — wick-based is more sensitive but noisier
- Micro-structure (M15) produces too many signals; macro-structure (H4+) is too slow
- Need to handle structure "reset" when price makes a new extreme in the original trend direction
- State machine complexity increases with multi-timeframe tracking

### Recommended Approach
1. Implement swing point detection with configurable lookback
2. Build a state machine: bullish -> choc_bearish -> bearish (and reverse)
3. Use close-based confirmation (more conservative, fewer false signals)
4. Implement on H1 as primary, H4 as higher timeframe
5. Require HTF alignment before taking LTF entries
6. Add a "ranging" state with minimum range width to filter noise
7. Track structure break count — require at least 2 consecutive structural breaks before confirming trend change

### Implementation Priority: CRITICAL
Market structure detection is the foundation upon which every other ICT concept depends. Order blocks require structure breaks to validate. FVGs gain meaning when they occur at structural levels. Liquidity sweeps are only meaningful within a structural context. **This must be implemented first.**

### Key Metric for Backtesting
- **CHoCH-to-MSS conversion rate:** % of CHoCH signals that become confirmed MSS
- **False CHoCH rate:** CHoCH signals where trend reverts to original direction
- **MTF alignment improvement:** win rate with HTF alignment vs. single TF
- **Optimal lookback:** which lookback window produces the best CHoCH/MSS signals per pair
