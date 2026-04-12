# Sprint 2: Fair Value Gap (FVG) Detector

**Issue:** AYUAA-37 | **Status:** done | **Source:** Paperclip

## Description

Implement Fair Value Gap (FVG) / Imbalance detector. Detect bullish and bearish FVGs from 3-candle analysis (gap between high of candle 1 and low of candle 3). Requirements: track FVG age/freshness, size classification (mini, standard, massive), confluence with order blocks and liquidity sweeps, integrate with Risk Manager.

## Discussion

**unknown:**

## FVG Detector - Sprint 2 Complete

Implemented Fair Value Gap (FVG) detector for ICT/SMC trading bot.

### Files
- `cbot/FairValueGapDetector.cs` — new FVG detector module
- `cbot/ICT_SMC_Bot.cs` — integrated FVG into main bot
- `cbot/Tests/FVGDetectorTests.cs` — 20 unit tests

### What was built
- **3-candle FVG detection**: Bullish (gap between candle1 high and candle3 low) and bearish (gap between candle3 high and candle1 low)
- **Size classification**: Mini (<0.5x avg), Standard (0.5-2x avg), Massive (>2x avg) relative to historical FVG sizes
- **Age/freshness tracking**: Fresh (0-5 candles), Stale (>5 candles), with configurable thresholds
- **Fill tracking**: Partial (50-90% filled), Fully Filled (>90%), with remaining gap size tracking
- **Order block confluence**: `CheckOrderBlockConfluence()` checks for overlapping OBs of matching type, boosts strength 1.3x
- **Liquidity sweep confluence**: `MarkLiquiditySweepConfluence()` accepts sweep levels, boosts strength 1.2x
- **Higher TF trend confluence**: H4 bullish/bearish ratio multiplier on FVG strength
- **Signal integration**: `DetectEntrySignal()` now checks FVG confluence alongside OB entries; standalone FVG entries when confluence not required
- **Risk integration**: FVG signals flow through existing risk manager (drawdown limits, max positions, position sizing)
- **Configurable parameters**: 11 new bot parameters for FVG tuning

### Dependencies
- Builds on [AYUAA-36](/AYUAA/issues/AYUAA-36) (Order Block Detector) for confluence checks
- Ready for [AYUAA-38](/AYUAA/issues/AYUAA-38) (Liquidity Sweep Detector) to feed sweep levels
