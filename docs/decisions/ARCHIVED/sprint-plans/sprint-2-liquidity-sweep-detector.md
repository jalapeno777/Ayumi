# Sprint 2: Liquidity Sweep Detector

**Issue:** AYUAA-38 | **Status:** done | **Source:** Paperclip

## Description

Implement Liquidity Sweep detector. Detect stops above/below key levels (swing highs/lows, day highs/lows, Fibonacci). Requirements: identify liquidity pools, detect sweep patterns (quick spike/rejection), track time-of-sweep relative to session (prefer London/NY killzones), confluence with other signals.

## Discussion

**unknown:**

## [AYUAA-38](/AYUAA/issues/AYUAA-38) Liquidity Sweep Detector — Code Complete

Implementation ready in workspace.

**Files:**
- `cbot/LiquiditySweepDetector.cs` — full liquidity sweep detection engine
- `cbot/ICT_SMC_Bot.cs` — updated with LS integration (parameters, OnBarClosed, signal detection)
- `cbot/Tests/LiquiditySweepDetectorTests.cs` — 37 test cases

**What was built:**
- **Liquidity Pool Identification**: Swing highs/lows on H1/H4, day highs/lows, Fibonacci retracement levels
- **Sweep Detection**: Buy-side and sell-side sweep patterns with wick ratio validation, rejection close confirmation, configurable tolerance
- **Session Tracking**: London KZ, NY AM/PM, Asian. Killzone sweeps get 1.5x strength multiplier
- **Confirmation Logic**: 2-candle confirmation window after level pierce
- **Strength Scoring**: Pool strength, wick ratio, session timing, volume spike, rejection body ratio
- **Confluence Integration**: Feeds sweep levels into FVG detector confluence, signals logged with FVG + LiquiditySweep tags
- **Cleanup**: Auto-removes swept pools, stale sweeps, caps at 20 pools and 10 sweeps

**Parent:** [AYUAA-11](/AYUAA/issues/AYUAA-11)
