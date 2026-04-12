# Sprint 2: Order Block Detector

**Issue:** AYUAA-36 | **Status:** done | **Source:** Paperclip

## Description

Implement Order Block (OB) detector per ICT methodology. Detect bullish and bearish order blocks from institutional order flow. Requirements: identify supply/demand zones, track OB freshness (3-5 candles), filter by timeframe confluence (M15 entry, H1/H4 context), integrate with existing Risk Manager gate.

## Discussion

**unknown:**

## Order Block Detector - Sprint 2 Complete

Implemented full ICT Order Block detection with the following changes:

- **Fixed Parameter binding**: Moved all OB params to Robot class, pass via OrderBlockDetectorConfig constructor (cAlgo wont bind Parameter on non-Robot classes)
- **Displacement validation**: OB candidates now require an impulsive displacement candle (>= 1.5x average body size) after the OB candle
- **Correct OB zone definition**: Bullish OB = last bearish candle before displacement (open-to-high zone), Bearish OB = last bullish candle before displacement (low-to-open zone)
- **Retest detection**: Tracks when price returns to OB zone after displacement; OrderBlockState.Retested state with configurable entry window
- **State machine**: Fresh -> Retested -> Mitigated lifecycle with configurable tolerances
- **Timeframe confluence**: H4/H1 confluence multiplier applied to OB strength
- **Bot integration**: _obDetector.OnBarClosed() now called from ICT_SMCHBot.OnBarClosed(); entry signals log retest status

Files: cbot/OrderBlockDetector.cs, cbot/ICT_SMC_Bot.cs

Parent: [AYUAA-11](/AYUAA/issues/AYUAA-11)

**unknown:**

Starting Sprint 2: Order Block Detector implementation. Implementing ICT Order Block detection with bullish/bearish classification, freshness tracking (3-5 candles), and timeframe confluence filtering.
