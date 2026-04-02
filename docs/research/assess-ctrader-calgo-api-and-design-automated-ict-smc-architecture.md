# Assess cTrader cAlgo API and Design Automated ICT/SMC Architecture

**Issue:** AYUAA-8 | **Status:** done | **Source:** Paperclip

## Description

## Objective
Assess cTrader cAlgo API capabilities and design the architecture for a fully automated ICT/SMC trading system.

## Context
This is the first execution task under the board-approved execution plan. See [AYUAA-1 plan document](/AYUAA/issues/AYUAA-1#document-plan) v3 for full strategic context.

Board direction: Fully automated from day one. No manual trading as primary. cAlgo API for execution. FTMO prop firm challenge is the target.

## Tasks
1. **cAlgo API Assessment** — Evaluate cTrader cAlgo API: data feed access (tick/bar), order execution (market/limit/stop), historical data for backtesting, event hooks, error handling
2. **Architecture Design** — Propose system architecture:
   - Signal detection module (order blocks, FVGs, liquidity sweeps, premium/discount zones, market structure shifts)
   - Order management module (entry, SL, TP, partial closes, trailing stops)
   - Risk management module (2% daily drawdown hard stop, position sizing, max position limits per FTMO rules)
   - Data/logging module (trade journal, performance metrics, equity curve)
3. **Build Sequence** — Propose ordered build sequence: what to build first, dependencies, estimated complexity per component
4. **Language/Platform Decision** — Recommend: cAlgo (C#) vs Python bridge vs other approach. Consider maintainability, API compatibility, backtesting capabilities.

## Deliverables
- Document your assessment and architecture proposal as an issue comment on this task
- Include a clear build sequence with dependencies
- Flag any API limitations or risks

## Constraints
- $0 budget for tooling (cTrader is free)
- Must be compatible with FTMO prop firm rules
- Target: system must be ready for FTMO demo deployment within 2-3 weeks

## Discussion

**unknown:**

Assessment and architecture complete. C# native cAlgo recommended. 12-component build sequence proposed (~13 days). Awaiting approval to begin Sprint 1 (scaffold, risk manager, market structure analyzer).

**unknown:**

## cTrader cAlgo API Assessment & ICT/SMC Architecture Proposal

### 1. cAlgo API Assessment

**Data Feeds**
- Real-time ticks via `OnTick()` — every bid/ask change
- Historical OHLC via `Bars` object and `MarketData.GetBars(TimeFrame, symbol)`
- Multi-timeframe: M1, M2–M30, H1–H12, Daily, Weekly, Monthly + custom timeframes via `TimeFrameManager.Custom.Add()`
- Depth: years of M1 data available from broker server; custom tick data via CSV upload
- Key for ICT: custom timeframes for London Killzone (02:00–05:00 UTC), NY AM Session (13:00–16:00 UTC)

**Order Execution**
- Market, Limit, Stop, Stop-Limit orders via `ExecuteMarketOrder()`, `PlaceLimitOrder()`, `PlaceStopOrder()`
- SL/TP on all order types; partial closes via `ModifyPosition()` with reduced volume
- No built-in trailing stop — implement in `OnTick()` (straightforward)
- Async variants available for non-blocking execution
- `TradeResult` pattern: check `.IsSuccessful`, `.Error` for every trade call

**Backtesting**
- Built-in engine with date range, starting capital, commission, spread config
- Custom data source API (`BacktestingDataSources`) for tick-level backtesting
- Parameter optimization with genetic algorithm
- Visual replay mode
- Results: net profit, equity curve, win rate, max drawdown, trade stats

**Event Hooks**
- `OnStart()`, `OnStop()`, `OnTick()`, `OnBar()`, `OnBarClosed()`, `OnException()`
- Position events: `Positions.Opened`, `Positions.Modified`, `Positions.Closed`
- Pending order events: `Created`, `Modified`, `Filled`, `Cancelled`
- `MarketSessionsChanged` — session transitions (London, NY, Tokyo, Sydney)
- Single-threaded — no concurrency concerns

**Account Access**
- `Account.Balance`, `Account.Equity`, `Account.Margin`, `Account.FreeMargin`, `Account.UnrealizedPnL`
- Critical for FTMO: monitor `Account.Equity` every tick for drawdown enforcement

**Indicators**
- 50+ built-in (RSI, MACD, ATR, Bollinger Bands, Ichimoku, Fractals, etc.)
- Custom indicators via `Indicator` subclass — `[Output]` and `[Parameter]` attributes
- Essential for ICT: ATR for volatility, Fractals for swing detection

**Limitations & Risks**
- Rate limits: 500 orders/min (demo), exceeding bans ALL trading for 1 min
- No native trailing stop — custom implementation required
- No OCO/bracket orders — manual logic
- No direct order history query — use `History` collection
- Backtesting uses M1 by default (tick data requires custom source)
- HTTP/WebSocket available for external data (news feeds)

**FTMO Compatibility**
- cTrader supported by FTMO for some challenge types — verify specific challenge
- cBots allowed on prop firm accounts
- Risk rules NOT enforced by platform — MUST code internally
- Hedging supported — verify prop firm rules
- News trading restrictions must be implemented via external news API

---

### 2. Architecture Design

```
┌─────────────────────────────────────────────────────┐
│                   cBot Entry Point                   │
│              (OnStart / OnTick / OnBar)              │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │   Session     │  │  Market      │  │   Risk      │ │
│  │   Filter      │  │  Structure   │  │   Manager   │ │
│  │              │  │  Analyzer    │  │             │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬──────┘ │
│         │                 │                 │        │
│         └────────┬────────┘                 │        │
│                  ▼                          │        │
│  ┌──────────────────────┐                   │        │
│  │   Signal Detector     │                   │        │
│  │  (ICT/SMC Logic)      │                   │        │
│  │  - Order Blocks       │                   │        │
│  │  - Fair Value Gaps    │                   │        │
│  │  - Liquidity Sweeps   │                   │        │
│  │  - Premium/Discount   │                   │        │
│  │  - Structure Shifts   │                   │        │
│  └──────────┬───────────┘                   │        │
│             │                               │        │
│             ▼                               │        │
│  ┌──────────────────────┐                   │        │
│  │   Order Manager       │◄──────────────────┘        │
│  │  - Entry execution    │                            │
│  │  - SL/TP placement    │                            │
│  │  - Partial closes     │                            │
│  │  - Trailing stops     │                            │
│  │  - Position tracking  │                            │
│  └──────────┬───────────┘                            │
│             │                                         │
│             ▼                                         │
│  ┌──────────────────────┐                            │
│  │   Trade Logger        │                            │
│  │  - Trade journal      │                            │
│  │  - Performance metrics │                            │
│  │  - Equity curve       │                            │
│  └──────────────────────┘                            │
└─────────────────────────────────────────────────────┘
```

**Module Details:**

**Session Filter** — Gates all trading to high-probability ICT sessions
- London Killzone (02:00–05:00 UTC), NY AM (13:00–16:00 UTC), NY PM (18:00–20:00 UTC)
- Uses `MarketSessionsChanged` event + custom time checks
- Outside sessions: no signal generation, only monitoring

**Market Structure Analyzer** — Tracks swing highs/lows and trend direction
- Custom indicator using Fractals or swing detection algorithm
- Identifies: Higher Highs/Lower Lows, Break of Structure (BOS), Change of Character (CHoCH)
- Multi-timeframe: M15 for entry, H1/H4 for structure context
- Outputs: current trend, recent BOS/CHoCH levels, key swing points

**Signal Detector** — Core ICT/SMC logic
- **Order Blocks**: Last bullish/bearish candle before impulsive move; zone = high–low of that candle
- **Fair Value Gaps (FVG)**: Three-candle pattern where candle 1 wick and candle 3 wick don't overlap
- **Liquidity Sweeps**: Price sweeps above/below swing H/L then reverses (wick rejection)
- **Premium/Discount**: Equilibrium at 50% of swing range; above = premium (sell zone), below = discount (buy zone)
- **Confluence scoring**: Multiple signals aligned = higher probability entry

**Order Manager** — Execution layer
- Entry: Limit orders at OB/FVG zones, stop orders for breakout entries
- SL: Below/above OB or recent swing; TP at next liquidity level or fixed R:R
- Partial closes: At 1:1 R:R, move SL to breakeven, trail remainder
- Trailing stop: ATR-based trailing in `OnTick()` — `ModifyPosition()` on distance threshold
- Position tracking: label-based (`Positions.Find(label)`) for multiple concurrent setups

**Risk Manager** — Hard enforcement of FTMO rules
- **Daily drawdown**: Track `Account.Equity` vs daily start equity; hard stop all trading at -5% (FTMO rule)
- **Max drawdown**: Track `Account.Equity` vs account high-water mark; hard stop at -10%
- **Position sizing**: `Symbol.QuantityToVolumeInUnits()` capped at max lot per FTMO tier
- **Max open positions**: Configurable limit (recommend 2-3 concurrent)
- **Daily loss cap**: Additional -2% hard stop (stricter than FTMO for safety margin)
- **Pre-trade check**: Every `ExecuteMarketOrder()` call goes through risk check first
- **Cooldown**: No new entries for N minutes after a loss (configurable)

**Trade Logger** — Performance tracking
- Log every trade to file: entry time, symbol, direction, size, entry price, SL, TP, exit price, result, screenshot trigger
- Running metrics: win rate, avg R:R, profit factor, max drawdown, Sharpe ratio
- Equity curve tracking for review

---

### 3. Language/Platform Decision

**Recommendation: C# natively in cAlgo**

| Factor | C# (cAlgo native) | Python (Open API bridge) |
|--------|-------------------|------------------------|
| API access | Full, direct | Full, but via TCP/Protobuf bridge |
| Latency | Minimal — runs in-process | Higher — network hop + serialization |
| Backtesting | Built-in, visual, optimizer | None — must build custom |
| Indicators | Native integration + custom | Must reimplement |
| Multi-timeframe | Direct `MarketData.GetBars()` | Available via API |
| Debugging | cTrader IDE with breakpoints | Standard Python tooling |
| Deployment | One-click from cTrader | Separate process, manage yourself |
| Maintainability | C# is verbose but well-structured | Python is faster to iterate |
| Community/Docs | cTrader docs + community | Smaller community, older SDK |

**Why C#:**
- Zero-latency execution — runs inside cTrader process
- Built-in backtesting with visual replay and optimization — critical for the 2-3 week timeline
- Custom indicator framework — build OB/FVG detectors as reusable indicators
- One-click deploy to demo/live from cTrader UI
- $0 budget constraint — everything runs in cTrader, no external infrastructure

**Python use case (later):** External analytics, ML-based signal enhancement, performance dashboarding. Not for v1 execution.

---

### 4. Build Sequence

| # | Component | Depends On | Complexity | Est. Time |
|---|-----------|------------|------------|-----------|
| 1 | **Project scaffold + session filter** | — | Low | 0.5 day |
| 2 | **Risk Manager** | #1 | Medium | 1 day |
| 3 | **Market Structure Analyzer** (swing detection, BOS/CHoCH) | #1 | High | 2 days |
| 4 | **Order Block detector** | #3 | Medium | 1 day |
| 5 | **FVG detector** | #3 | Medium | 1 day |
| 6 | **Liquidity Sweep detector** | #3 | Medium | 1 day |
| 7 | **Premium/Discount zones** | #3 | Low | 0.5 day |
| 8 | **Confluence engine** (signal scoring + entry logic) | #4, #5, #6, #7 | High | 1.5 days |
| 9 | **Order Manager** (entry, SL, TP, partial close, trail) | #2, #8 | Medium | 1.5 days |
| 10 | **Trade Logger** (journal, metrics, equity curve) | #9 | Low | 0.5 day |
| 11 | **Backtesting + optimization** | All | Medium | 2 days |
| 12 | **Demo deployment + monitoring** | #11 | Low | 1 day |

**Total: ~13 days** — fits within the 2-3 week target with buffer.

**Critical path:** #1 → #3 → #4/#5/#6 → #8 → #9 → #11

**Parallelizable:** #4, #5, #6, #7 can be built in parallel after #3. #10 can start alongside #9.

---

### 5. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| FTMO may not offer cTrader for all challenge types | Blocks deployment | Verify FTMO cTrader availability before starting. Fallback: adapt to MetaTrader if needed |
| Backtesting on M1 data (not tick) | Signal accuracy | Use M15+ timeframes for ICT signals (M1 granularity not needed). Validate with forward demo testing |
| Rate limit ban shuts down all trading | Missed trades | Implement order queue with rate limiting. Never exceed 300 orders/min (60% of limit) |
| ICT signal false positives | Drawdown | Confluence scoring (require 2+ signals), strict R:R minimum (1:2), daily loss cap |
| No external news API integration in v1 | News trading violations | Gate trades to pre-session only. No entries within 30 min of high-impact news (time-based filter using known news schedule) |

---

### 6. Next Step

With this assessment approved, I'll start building. **Sprint 1** covers items #1-#3 (scaffold, risk manager, market structure analyzer) — approximately 3.5 days. I'll create subtasks for each component and begin execution.

Parent issue: [AYUAA-1](/AYUAA/issues/AYUAA-1) | Plan: [AYUAA-1#document-plan](/AYUAA/issues/AYUAA-1#document-plan)

