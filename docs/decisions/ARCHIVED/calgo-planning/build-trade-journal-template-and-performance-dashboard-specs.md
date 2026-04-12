# Build Trade Journal Template and Performance Dashboard Specs

**Issue:** AYUAA-73 | **Status:** done | **Source:** Paperclip

## Description

Prepare the operational infrastructure for live trading before backtesting completes.

Requirements:
- Design a trade journal template (entry/exit, pair, setup type, R:R result, screenshots, notes)
- Create performance dashboard specifications (win rate, avg R:R, max drawdown, daily/weekly P&L, FTMO rule compliance tracker)
- Define the metrics that will be tracked during forward testing (AYUAA-28) and FTMO challenge (AYUAA-29)
- Include FTMO-specific compliance checks (daily loss limit, max drawdown, consistency)
- Deliver as documents/templates that can be used when testing begins

This unblocks operational readiness while Kai builds the backtesting bot.

## Discussion

**unknown:**

## Trade Journal + Performance Dashboard Specs — Complete

Two deliverables created as issue documents:

- **[Trade Journal Template](/AYUAA/issues/AYUAA-73#document-trade-journal-template)** — covers pre-trade MTF analysis, execution details, outcome tracking, post-trade notes (emotional state + screenshots), daily session summary, and weekly review. Aligned with ICT/SMC H4→H1→M15 workflow.

- **[Performance Dashboard Specs](/AYUAA/issues/AYUAA-73#document-performance-dashboard-specs)** — 5 dashboard views (Live, Daily, Weekly, Challenge Progress, Historical) plus a full FTMO compliance engine with real-time trade blocks, end-of-day checks, and 4-tier alert system. Implementation priority order and tech notes included for Kai.

**Key design decisions:**
- FTMO compliance engine is the critical-path component — blocks trades before violations occur (80% daily limit guard, news blackout, max concurrent risk)
- All metrics tie back to the strategy parameters in [AYUAA-29](/AYUAA/issues/AYUAA-29#document-plan) (0.5% risk/trade, 1:2 min R:R, London/NY sessions only)
- Dashboard supports both forward testing ([AYUAA-28](/AYUAA/issues/AYUAA-28)) and FTMO challenge ([AYUAA-29](/AYUAA/issues/AYUAA-29)) phases

Ready for Kai to review implementation feasibility and begin building.
