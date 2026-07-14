# Forex Trading Infrastructure Assessment

**Issue:** AYUAA-6 | **Status:** done | **Source:** Paperclip

## Description

Review the current state of the Forex trading infrastructure. Identify the top 3 gaps between where we are and a functional ICT/SMC trading operation. Post your assessment to #board-updates.

Focus areas:
- Market data pipelines and feeds
- Trade execution infrastructure
- Risk management and position sizing systems
- Prop firm compliance tooling

## Discussion

**unknown:**

## Forex Trading Infrastructure Assessment

**Current state:** Greenfield. No code, no pipelines, no execution systems exist. The workspace is empty.

**Board direction (from Craig):** cTrader + FTMO stack, ICT/SMC strategy, $150 starting capital, Discord community.

---

### Top 3 Gaps to Functional ICT/SMC Trading

**1. Market Data Pipeline**
- No market data feeds exist. ICT/SMC requires: real-time OHLCV (M1–W1), tick data, order flow, and session timing (London, NY, Asia killzones).
- cTrader Open API provides WebSocket and REST endpoints for this. Needs integration layer.
- Deliverable: `market_data/` module — cTrader symbol subscription, candle aggregation, session clock, data persistence.

**2. ICT/SMC Signal Engine + Trade Execution**
- No signal detection or execution logic. Core ICT/SMC concepts to automate: daily bias (BOS/CHoCH), killzone entry timing, liquidity sweep detection, fair value gaps, order blocks, breaker blocks, displacement.
- Execution must route through cTrader Open API (v2 or v3).
- Deliverable: `signals/` module (bias engine, pattern detector) + `execution/` module (order management, cTrader API client).

**3. Risk Management + Prop Firm Compliance Engine**
- No risk controls or FTMO compliance tooling. Critical given $150 capital and prop firm rules.
- Must enforce: max 1-2% risk per trade, daily loss cap (5% FTMO), total drawdown cap (10% FTMO), minimum 5 trading days before payout, news trading restrictions.
- Deliverable: `risk/` module — position sizing calculator, drawdown tracker, pre-trade compliance checks, violation alerts.

---

### Recommended Build Order

1. Market data pipeline (signals and execution depend on it)
2. Risk/compliance engine (must be in place before any live trading)
3. Signal engine + execution (last, after guardrails exist)

### Infrastructure Needs

- Python environment (pandas, numpy, websockets)
- cTrader demo account credentials for API access
- FTMO demo account for compliance testing
- Logging and alerting (Discord webhook integration)

All dependent on board go/no-go on execution. Parent issue: [AYUAA-3](/AYUAA/issues/AYUAA-3).
