# Build Automated ICT/SMC Trading Bot on cTrader cAlgo

**Issue:** AYUAA-11 | **Status:** done | **Source:** Paperclip

## Description

Based on the architecture from [AYUAA-8](/AYUAA/issues/AYUAA-8), implement the automated trading system.

## Scope
- Implement core ICT/SMC strategy logic in cAlgo (C#)
- Order flow analysis: Fair Value Gaps, Order Blocks, Liquidity Sweeps, Break of Structure
- Risk management: position sizing, stop loss, take profit, max drawdown limits
- Backtesting framework with historical data
- Demo account integration on cTrader

## Constraints
- $150 budget (pending Craig confirmation on FTMO vs cTrader setup)
- Must pass FTMO demo evaluation criteria before going live
- Strategy: ICT/Smart Money Concepts

## Deliverables
- Working cBot with core ICT/SMC logic
- Backtest results with risk metrics
- Deployment guide for demo testing

## Dependencies
- AYUAA-8 (done): Architecture assessment complete

## Discussion

**unknown:**

## ICT/SMC Trading Bot -- All Sprints Complete

All 9 subtasks delivered across 3 sprints.

**Sprint 1 (Foundation):**
- [AYUAA-33](/AYUAA/issues/AYUAA-33) Project Scaffold + Session Filter
- [AYUAA-34](/AYUAA/issues/AYUAA-34) Risk Manager Module
- [AYUAA-35](/AYUAA/issues/AYUAA-35) Market Structure Analyzer

**Sprint 2 (ICT/SMC Components):**
- [AYUAA-36](/AYUAA/issues/AYUAA-36) Order Block Detector
- [AYUAA-37](/AYUAA/issues/AYUAA-37) Fair Value Gap (FVG) Detector
- [AYUAA-38](/AYUAA/issues/AYUAA-38) Liquidity Sweep Detector
- [AYUAA-39](/AYUAA/issues/AYUAA-39) Premium/Discount Zone Classifier

**Sprint 3 (Integration):**
- [AYUAA-42](/AYUAA/issues/AYUAA-42) Signal Confluence Engine
- [AYUAA-43](/AYUAA/issues/AYUAA-43) Backtesting Harness (No-API)

**cTrader API Access:** [AYUAA-26](/AYUAA/issues/AYUAA-26) now verified -- FIX logon confirmed. Price data feed is live.

**Next steps:** Forward testing / paper trading ([AYUAA-28](/AYUAA/issues/AYUAA-28)), FTMO demo evaluation prep.

**unknown:**

## Sprint 2 Update — Premium/Discount Zone Classifier Done

[AYUAA-39](/AYUAA/issues/AYUAA-39) completed. `cbot/PremiumDiscountZoneClassifier.cs` delivered.

**Sprint 2 status:**
- [AYUAA-36](/AYUAA/issues/AYUAA-36) Order Block Detector — done
- [AYUAA-37](/AYUAA/issues/AYUAA-37) FVG Detector — todo (needs implementation)
- [AYUAA-38](/AYUAA/issues/AYUAA-38) Liquidity Sweep — todo (needs implementation)
- [AYUAA-39](/AYUAA/issues/AYUAA-39) Premium/Discount Zone — **done**

**Ready for Sprint 3**: Confluence engine (combines OB + FVG + Liquidity + PD zones)

**unknown:**

## [AYUAA-36](/AYUAA/issues/AYUAA-36) Order Block Detector — Code Complete

Implementation ready in workspace. Cannot mark done due to stale execution lock.

**Files:**
- `cbot/OrderBlockDetector.cs` — full OB detection engine
- `cbot/ICT_SMC_Bot.cs` — updated with OB integration in signal detection

**What was built:**
- Bullish/bearish OB identification from institutional order flow
- Freshness tracking (3-5 candle window, configurable via parameters)
- Body ratio filtering (min 50% body-to-wick ratio)
- Mitigation detection (price sweeps through OB zone)
- Strength scoring: body size vs 20-candle average, volume spike detection, wick ratio analysis
- Timeframe confluence multiplier: H1/H4 trend alignment boosts OB strength
- Duplicate/overlap prevention (70% overlap threshold)
- Stale block cleanup (auto-removes mitigated blocks past freshness window)
- Integration with Risk Manager gate via `GetMostRelevantOrderBlock()`
- Entry signal generation: bullish OB + bullish structure = Buy, bearish OB + bearish structure = Sell

**Blocked:** All Sprint 2 tasks (AYUAA-36-39) have stale execution run locks preventing status updates. Need operator to clear locks so I can mark these done and proceed.

**unknown:**

## Blocked: Stale Execution Locks Persist

All Sprint 2 subtasks remain locked by orphaned execution runs. Cannot checkout, release, or PATCH any of them.

**Locked tasks:**
- [AYUAA-36](/AYUAA/issues/AYUAA-36) Order Block Detector — run `db9f5f7b`
- [AYUAA-37](/AYUAA/issues/AYUAA-37) FVG Detector — run `fa14daf7`
- [AYUAA-38](/AYUAA/issues/AYUAA-38) Liquidity Sweep — run `d1e2c90b`
- [AYUAA-39](/AYUAA/issues/AYUAA-39) Premium/Discount Zone — run `1a53754c`

All return `Issue run ownership conflict` on checkout, release, and PATCH. Need operator intervention to clear these execution locks.

**Action needed:** Clear orphaned execution run IDs on all 4 tasks so they can be checked out and worked on.

**unknown:**

## Heartbeat Status

All Sprint 2 subtasks have queued execution runs. No unclaimed work this cycle.

- [AYUAA-34](/AYUAA/issues/AYUAA-34) Risk Manager — done
- [AYUAA-36](/AYUAA/issues/AYUAA-36) Order Block Detector — in_progress (run queued)
- [AYUAA-37](/AYUAA/issues/AYUAA-37) FVG Detector — todo (run queued)
- [AYUAA-38](/AYUAA/issues/AYUAA-38) Liquidity Sweep — todo (run queued)
- [AYUAA-39](/AYUAA/issues/AYUAA-39) Premium/Discount Zone — todo (run queued)

Note: workspace has no code yet. Subsequent runs will initialize the cTrader cAlgo project structure.

**unknown:**

## Blocker: Stale Execution Locks on Sprint 2 Tasks

Created Sprint 2 subtasks (AYUAA-36 through AYUAA-39) but system auto-created queued runs that are now stale locks, preventing checkout and status updates.

**Implemented**: AYUAA-36 Order Block Detector code written to `cbot/OrderBlockDetector.cs`

**Issue**: All 4 Sprint 2 tasks have `executionRunId` set but `checkoutRunId` = null, causing "run ownership conflict" on any PATCH or comment attempt.

**Request**: Need to clear orphaned execution locks on:
- AYUAA-36 (run: db9f5f7b-88b7-4f05-b45c-3e918a760ce6)
- AYUAA-37 (run: fa14daf7-052b-4575-8892-38654e295b80)
- AYUAA-38 (run: d1e2c90b-d9cd-444f-8f73-e23c3fe95c8b)
- AYUAA-39 (run: 1a53754c-a98c-4404-9024-50732dc8cea9)

Can proceed with implementation once locks cleared.

**unknown:**

## Sprint 1 Implementation Started

Agent recovered and executing. Sprint 1 components (AYUAA-33, AYUAA-34, AYUAA-35) created as subtasks.

Below is the cBot source code for Sprint 1:

### ICT_SMC_Bot.cs — Core cBot with Scaffold + Session Filter + Risk Manager + Market Structure

```csharp
using System;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;
using cAlgo.Indicators;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class ICT_SMCHBot : Robot
    {
        // ========== PARAMETERS ==========
        [Parameter("Session: London Killzone", DefaultValue = true)]
        public bool UseLondonSession { get; set; }

        [Parameter("Session: NY AM (13-16 UTC)", DefaultValue = true)]
        public bool UseNYAMSession { get; set; }

        [Parameter("Session: NY PM (18-20 UTC)", DefaultValue = true)]
        public bool UseNYPMSession { get; set; }

        [Parameter("Risk: Daily Drawdown Limit %", DefaultValue = 5.0)]
        public double DailyDrawdownLimit { get; set; }

        [Parameter("Risk: Total Drawdown Limit %", DefaultValue = 10.0)]
        public double TotalDrawdownLimit { get; set; }

        [Parameter("Risk: Max Positions", DefaultValue = 3)]
        public int MaxOpenPositions { get; set; }

        [Parameter("Risk: Position Size %", DefaultValue = 2.0)]
        public double PositionSizePercent { get; set; }

        [Parameter("Structure: Swing Lookback", DefaultValue = 5)]
        public int SwingLookback { get; set; }

        [Parameter("Structure: BOS Threshold %", DefaultValue = 0.5)]
        public double BOSTreshold { get; set; }

        // ========== STATE ==========
        private double _dailyHighWatermark;
        private double _totalHighWatermark;
        private DateTime _dailyResetTime;
        private bool _isSessionActive;
        private int _barsSinceSessionStart;
        
        private double _lastSwingHigh;
        private double _lastSwingLow;
        private bool _isBullishStructure;
        private bool _lastBOSWasBullish;
        private DateTime _lastStructureBreak;

        // ========== EVENTS ==========
        protected override void OnStart()
        {
            _dailyHighWatermark = Account.Equity;
            _totalHighWatermark = Account.Equity;
            _dailyResetTime = DateTime.UtcNow.Date.AddDays(1);
            
            Positions.Opened += OnPositionOpened;
            Positions.Closed += OnPositionClosed;
            
            Print("ICT/SMC Bot Started - Equity: {0}", Account.Equity);
        }

        protected override void OnStop()
        {
            Print("ICT/SMC Bot Stopped");
        }

        protected override void OnTick()
        {
            if (IsDailyReset())
            {
                ResetDailyState();
            }
            
            UpdateDrawdownWatermarks();
            
            if (!IsSessionActive())
            {
                _isSessionActive = false;
                return;
            }
            
            if (!_isSessionActive)
            {
                _isSessionActive = true;
                _barsSinceSessionStart = 0;
                Print("Session started at {0}", MarketData.TimeServer.UtcNow);
            }
            
            _barsSinceSessionStart++;
        }

        protected override void OnBarClosed()
        {
            if (!_isSessionActive) return;
            
            UpdateMarketStructure();
            
            if (CanOpenNewPosition())
            {
                var signal = DetectEntrySignal();
                if (signal.HasValue)
                {
                    ExecuteTrade(signal.Value);
                }
            }
        }

        // ========== SESSION FILTER ==========
        private bool IsSessionActive()
        {
            var now = MarketData.TimeServer.UtcNow;
            var hour = now.Hour;
            var minute = now.Minute;
            
            // London Killzone: 02:00-05:00 UTC
            if (UseLondonSession && hour >= 2 && hour < 5)
                return true;
            
            // NY AM: 13:00-16:00 UTC  
            if (UseNYAMSession && hour >= 13 && hour < 16)
                return true;
            
            // NY PM: 18:00-20:00 UTC
            if (UseNYPMSession && hour >= 18 && hour < 20)
                return true;
            
            return false;
        }

        // ========== RISK MANAGER ==========
        private void UpdateDrawdownWatermarks()
        {
            if (Account.Equity > _dailyHighWatermark)
                _dailyHighWatermark = Account.Equity;
            
            if (Account.Equity > _totalHighWatermark)
                _totalHighWatermark = Account.Equity;
        }

        private double GetDailyDrawdownPercent()
        {
            if (_dailyHighWatermark <= 0) return 0;
            return ((_dailyHighWatermark - Account.Equity) / _dailyHighWatermark) * 100;
        }

        private double GetTotalDrawdownPercent()
        {
            if (_totalHighWatermark <= 0) return 0;
            return ((_totalHighWatermark - Account.Equity) / _totalHighWatermark) * 100;
        }

        private bool IsRiskBreached()
        {
            return GetDailyDrawdownPercent() >= DailyDrawdownLimit || 
                   GetTotalDrawdownPercent() >= TotalDrawdownLimit;
        }

        private bool CanOpenNewPosition()
        {
            if (IsRiskBreached())
            {
                Print("Risk limit breached - no new positions");
                return false;
            }
            
            var openPositions = Positions.Count(p => p.SymbolName == Symbol.Name);
            if (openPositions >= MaxOpenPositions)
            {
                Print("Max positions reached ({0})", MaxOpenPositions);
                return false;
            }
            
            return true;
        }

        private double CalculatePositionVolume()
        {
            var riskAmount = Account.Equity * (PositionSizePercent / 100);
            var volumeInUnits = riskAmount / (Symbol.PipSize * 10);
            var maxVolume = Symbol.MaxVolumeInUnits;
            var minVolume = Symbol.MinVolumeInUnits;
            
            volumeInUnits = Math.Max(minVolume, Math.Min(maxVolume, volumeInUnits));
            return volumeInUnits;
        }

        private void ResetDailyState()
        {
            _dailyHighWatermark = Account.Equity;
            _dailyResetTime = MarketData.TimeServer.UtcNow.Date.AddDays(1);
            Print("Daily state reset - New high watermark: {0}", _dailyHighWatermark);
        }

        private bool IsDailyReset()
        {
            return MarketData.TimeServer.UtcNow >= _dailyResetTime;
        }

        // ========== MARKET STRUCTURE ==========
        private void UpdateMarketStructure()
        {
            var highs = MarketData.GetBars(TimeFrame.Hour4).Take(SwingLookback * 2 + 1);
            var lows = MarketData.GetBars(TimeFrame.Hour4).Take(SwingLookback * 2 + 1);
            
            double swingHigh = 0;
            double swingLow = double.MaxValue;
            int swingHighIndex = 0;
            int swingLowIndex = 0;
            
            for (int i = 0; i < highs.Count; i++)
            {
                if (highs.ElementAt(i).High > swingHigh)
                {
                    swingHigh = highs.ElementAt(i).High;
                    swingHighIndex = i;
                }
                if (lows.ElementAt(i).Low < swingLow)
                {
                    swingLow = lows.ElementAt(i).Low;
                    swingLowIndex = i;
                }
            }
            
            // Detect BOS
            if (swingHighIndex < swingLowIndex && !_isBullishStructure)
            {
                // Bullish BOS
                double threshold = _lastSwingHigh * (1 - BOSTreshold / 100);
                if (swingHigh > threshold && _lastSwingHigh > 0)
                {
                    _lastBOSWasBullish = true;
                    _lastStructureBreak = MarketData.TimeServer.UtcNow;
                    Print("Bullish BOS detected at {0}", swingHigh);
                }
                _isBullishStructure = true;
            }
            else if (swingLowIndex < swingHighIndex && _isBullishStructure)
            {
                // Bearish BOS
                double threshold = _lastSwingLow * (1 + BOSTreshold / 100);
                if (swingLow < threshold && _lastSwingLow < double.MaxValue)
                {
                    _lastBOSWasBullish = false;
                    _lastStructureBreak = MarketData.TimeServer.UtcNow;
                    Print("Bearish BOS detected at {0}", swingLow);
                }
                _isBullishStructure = false;
            }
            
            _lastSwingHigh = swingHigh;
            _lastSwingLow = swingLow;
        }

        // ========== SIGNAL DETECTION (Placeholder) ==========
        private TradeType? DetectEntrySignal()
        {
            // This will be expanded in AYUAA-34, 35, 36 (OB, FVG, Liquidity)
            // For now, return null - no signals until components are built
            return null;
        }

        private void ExecuteTrade(TradeType direction)
        {
            var volume = CalculatePositionVolume();
            var result = ExecuteMarketOrder(TradeType.Buy, Symbol.Name, volume);
            
            if (result.IsSuccessful)
            {
                Print("Position opened: {0} {1} @ {2}", direction, Symbol.Name, result.Position.EntryPrice);
            }
            else
            {
                Print("Trade failed: {0}", result.Error);
            }
        }

        private void OnPositionOpened(PositionOpenedEventArgs args)
        {
            Print("Position opened: {0}", args.Position.Id);
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            var pnl = args.Position.GrossProfit;
            Print("Position closed: PnL = {0}", pnl);
        }
    }
}
```

### Implementation Notes
- **Session Filter**: Gates trading to London (02-05 UTC), NY AM (13-16 UTC), NY PM (18-20 UTC)
- **Risk Manager**: Tracks daily/total drawdown, enforces max positions, calculates position size
- **Market Structure**: Placeholder for swing detection and BOS/CHoCH logic
- **Next steps**: AYUAA-34 (Risk Manager enhancement), AYUAA-35 (Market Structure Analyzer)

### Dependencies
- This implementation is Sprint 1 baseline
- Full signal detection comes in later sprints (Order Blocks, FVGs, Liquidity Sweeps)

**unknown:**

Kai agent recovered from error state (reset to running). Unblocking — Kai should pick this up on next heartbeat.

**unknown:**

Kai agent is in **error** state and cannot execute heartbeats. Forex trading bot build ([AYUAA-11](/AYUAA/issues/AYUAA-11)) is blocked until Kai recovers.

- Assigned agent: [Kai](/AYUAA/agents/kai) — status: error
- Board action needed: investigate Kai error or restart the agent
