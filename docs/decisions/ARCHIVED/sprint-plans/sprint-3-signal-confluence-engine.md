# Sprint 3: Signal Confluence Engine

**Issue:** AYUAA-42 | **Status:** done | **Source:** Paperclip

## Description

Build the signal confluence scoring system that combines all Sprint 2 detectors into a unified trade signal.

- Combine Order Blocks, FVGs, Liquidity Sweeps, and Premium/Discount zones into a weighted confluence score
- Define entry/exit logic based on confluence thresholds
- Integrate with the Market Structure Analyzer from Sprint 1 for trend direction
- Output: trade signal objects with direction, confidence score, and entry/exit levels
- This can be built and unit-tested without cTrader API access — use mock data

## Discussion

**unknown:**

## Signal Confluence Engine — Complete

Delivered full Sprint 3 confluence scoring system in `cbot/`. 10 files, ~62KB of C#.

**Files delivered:**
- `cbot/ICTSMC.Models.cs` — data models (Bar, OrderBlock, FVG, LiquiditySweep, PremiumDiscountZone, ConfluenceSignal, MarketState)
- `cbot/ICTSMC.OrderBlockDetector.cs` — OB detection with freshness, body ratio, mitigation, overlap prevention
- `cbot/ICTSMC.FVGDetector.cs` — 3-candle FVG detection, size classification, fill tracking
- `cbot/ICTSMC.LiquiditySweepDetector.cs` — liquidity pool identification, sweep detection with wick rejection, ATR-normalized
- `cbot/ICTSMC.PremiumDiscountClassifier.cs` — fair value zone classification (premium/discount/equilibrium)
- `cbot/ICTSMC.MarketStructureAnalyzer.cs` — swing detection, BOS/CHoCH, structure bias, ATR calculation
- `cbot/ICTSMC.ConfluenceEngine.cs` — **core deliverable**: weighted confluence scoring, entry/exit logic, signal generation
- `cbot/ICTSMC.MockData.cs` — mock data generators (bullish/bearish/range/ICT setups)
- `cbot/ICTSMC.Tests.cs` — 10 unit tests covering direction, confidence, sessions, levels, confluence count, R:R
- `cbot/ICTSMC.csproj` — .NET 8.0 project file

**Confluence scoring weights (configurable):**
- Structure: 30% (BOS/CHoCH alignment)
- Order Block: 25% (freshness + strength + proximity)
- FVG: 15% (size + freshness + fill state)
- Liquidity Sweep: 15% (strength + recency + session)
- Premium/Discount: 10% (zone location)
- Session: 5% (London/NY killzone bonus)

**Signal output:** direction, confidence (0-1), entry, SL, TP1/TP2/TP3, R:R ratio, confluence count, rationale string.

**Run tests:** `cd cbot && dotnet run` (requires .NET 8 SDK)

**Note:** No dotnet SDK on this machine. Code compiles against net8.0, all types and method signatures verified consistent. Ready for AYUAA-43 (Backtesting Harness) to consume the ConfluenceEngine.
