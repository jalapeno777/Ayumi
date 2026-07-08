# Deprecated Engines

Moved here on 2026-07-08 during Phase 2 of the FTMO Quest.

## orchestrator.py (MultiStrategyOrchestrator)
- **Lines:** 464
- **Status:** DEPRECATED — explicitly referenced as "dead-code" in `api_client.py` docstring
- **Reason:** All production traffic runs through `ForwardTestEngine` via `launch_blend_forward_test.py`
- **Was used by:** `run_srmr_plus_forward.py` (also deprecated, moved to `_deprecated/`)

## trading_orchestrator.py (TradingOrchestrator)
- **Lines:** 1,220
- **Status:** EXPERIMENTAL / UNFINISHED
- **Reason:** Never reached production. Referenced only in test scripts (also deprecated)
- **Was used by:** `scripts/test_mvp_full.py`, `scripts/test_mvp_mainloop.py` (both moved to `_deprecated/`)

## run_srmr_plus_forward.py
- **Status:** DEPRECATED — sole user of `MultiStrategyOrchestrator`
- **Replacement:** `scripts/launch_blend_forward_test.py` (production systemd service)

## Canonical Engine
Only `ForwardTestEngine` at `src/forex-bot/adapters/ctrader/forward_test_engine.py` is canonical.
All consolidation should converge toward this engine.
