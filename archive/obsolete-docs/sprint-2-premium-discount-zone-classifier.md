# Sprint 2: Premium/Discount Zone Classifier

**Issue:** AYUAA-39 | **Status:** done | **Source:** Paperclip

## Description

Implement Premium/Discount zone classifier per ICT methodology. Classify price location relative to fair value: Premium (above 50% fib, bearish), Discount (below 50% fib, bullish). Requirements: calculate fair value area, track zone quality (strong/weak), time-in-zone metrics, confluence scoring with other ICT elements.

## Discussion

**unknown:**

## Premium/Discount Zone Classifier — Code Complete

Implementation in `cbot/PremiumDiscountZoneClassifier.cs`.

**What was built:**
- Fair value calculation via 50% retracement of swing high/low range
- Zone classification: Premium (above equilibrium), Discount (below), Equilibrium (within tolerance)
- Swing detection with strict left/right confirmation
- Zone quality scoring (Strong/Moderate/Weak) based on:
  - Range-to-body ratio (wider ranges = stronger zones)
  - Volume at swing points vs average
  - Rejection counting (wick-based, 50%+ body ratio threshold)
  - Timeframe multiplier (H1/H4 boost)
  - Wick ratio analysis
 - Time-in-zone tracking (bars spent in premium/discount/equilibrium)
- Confluence scoring combining quality + rejection count + time-in-zone + swing edge proximity
- Optimal entry price calculation: Fibonacci-based (0.382 for buys in discount, 0.618 for sells in premium)
- Zone depth percentage: how deep price sits within premium/discount
- Multi-timeframe alignment via `GetMultiTimeframeZones()` and `HasMultiTfAlignment()`
- `IsOptimalEntry()` gate: only returns true when zone + confluence meet threshold

**Key design decisions:**
- Equilibrium tolerance: 0.3% configurable (avoids zone flip noise)
- Rejection detection: requires 50%+ wick-to-range ratio (filters noise)
- Multi-TF: M15/H1/H4 zone comparison for alignment confirmation
- Zone depth: percentage-based so it normalizes across instruments
