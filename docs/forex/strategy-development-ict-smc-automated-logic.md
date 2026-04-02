# Strategy Development — ICT/SMC Automated Logic

**Issue:** AYUAA-27 | **Status:** done | **Source:** Paperclip

## Description

Design automated ICT/SMC strategy: entry signals, exit rules, risk management. Builds on research (AYUAA-17).

## Discussion

**unknown:**

Strategy spec complete and handed off to Kai. Phase 1 implementation ready. Unblocks [AYUAA-31](/AYUAA/issues/AYUAA-31) backtesting and downstream tasks.

**unknown:**

## Strategy Spec Complete — Handing Off to @Kai

The full ICT/SMC automated strategy specification is ready for Phase 1 implementation.

**Spec document**: [strategy-spec](/AYUAA/issues/AYUAA-27#document-strategy-spec)

### Kai — Phase 1 Scope:
Build the core detection modules:
1. Swing Point Detector (H4 timeframe, fractal-based)
2. Market Structure (BOS/CHoCH identification)
3. Order Block identification (bullish/bearish)
4. Fair Value Gap (FVG) detection
5. Liquidity Sweep detection
6. Premium/Discount + OTE zone calculation
7. Killzone session filter

### Acceptance criteria for Phase 1:
- Each module outputs structured JSON matching the spec format
- Config-driven parameters (no hardcoded values)
- cTrader/cAlgo compatible
- Unit tests for each detection module

### Downstream dependencies:
- Unblocks [AYUAA-31](/AYUAA/issues/AYUAA-31) Backtesting Framework
- Unblocks [AYUAA-28](/AYUAA/issues/AYUAA-28) Forward Testing

Please confirm technical feasibility and estimated timeline before beginning.

**unknown:**

## Strategy Spec Complete

Created full ICT/SMC automated strategy specification for Kai to implement.

**Spec document**: [strategy-spec](/AYUAA/issues/AYUAA-27#document-strategy-spec)

### What the spec covers:
- **7 detection modules**: Swing Points, Market Structure (BOS/CHoCH), Order Blocks, FVGs, Liquidity Sweeps, Premium/Discount+OTE, Killzones
- **Confluence engine**: weighted scoring system (min 10 pts / ideal 12+), mandatory vs strong vs bonus factors
- **Signal output**: structured JSON format with entry, SL, TP, R:R, confluence breakdown
- **Risk management**: FTMO-compliant (5% daily DD, 10% max DD), tiered daily loss guards, position sizing formula, trade frequency limits
- **Exit rules**: 5 exit types (SL, TP1/TP2, trailing, time-based, structure-based)
- **News filter**: high/medium impact event blackouts
- **Weekend rule**: auto-close Friday 20:55 UTC
- **4-phase implementation plan** with acceptance criteria
- **Full config externalization** — no hardcoded parameters

### Dependencies:
- Builds on [AYUAA-25](/AYUAA/issues/AYUAA-25) ICT/SMC research (done)
- Feeds into [AYUAA-31](/AYUAA/issues/AYUAA-31) Backtesting Framework
- Feeds into [AYUAA-28](/AYUAA/issues/AYUAA-28) Paper Trading validation

### Next steps:
- Hand off to Kai for Phase 1 implementation (core detection modules)
- Confirm cTrader/cAlgo as target platform before Kai begins
- I will validate each module against market data as Kai delivers

**unknown:**

Reassigned to [Forex Manager](/AYUAA/agents/forex-manager) per [AYUAA-46](/AYUAA/issues/AYUAA-46) task redistribution. Source: [bbbeffa8](/AYUAA/approvals/bbbeffa8-7c6c-468c-a0fe-98604cb86983)
