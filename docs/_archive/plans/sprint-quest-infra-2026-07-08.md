# Sprint: Quest Infrastructure — Phases 8-10 + Quick Wins

**Date:** 2026-07-08
**Constraint:** Max 1 builder at a time. No strategy testing.

## Task Sequence (11 tasks, ~12 SP total)

### Quick Wins (≤1 SP each, auto-proceed)
1. `a717939c` — Fix min_windows_passed discrepancy (30 min)
2. `ada055b8` — Fix 5 DSR gate defects → create `oos_gate.py` (2 hours)
3. NEW — Add calibration + Brier score to WF evaluation (1 SP)

### Phase 8: DuckDB Analytics (3 SP, council-reviewed)
4. 8a — DuckDB install + spike benchmark: import M1 CSV, validate parity (1 SP)
5. 8b — Schema design + CSV migration with parity tests (1 SP)
6. 8c — DbDataLoader class with list[Bar] interface (1 SP)

### Phase 9: Dukascopy Data (2 SP)
7. 9a — Download script: M1 bars 2015-2023, 4 pairs (1 SP)
8. 9b — Data QA + timeframe synthesis pipeline (1 SP)

### Phase 10: Testing Pipeline Upgrade (3 SP)
9. 10a — data_loader.py: DB-backed with CSV fallback (1 SP)
10. 10b — DSR gate integration into Optuna+WF pipeline (1 SP)
11. 10c — ICIR computation + live monitor + cohort dashboard (1 SP)

## Execution Order
Strict sequential. Builder N+1 starts after builder N validated.

## Council Status
Phases 8-10 already council-reviewed (Kaito/Rei/Sora, 2026-07-08). Craig approved pivot. Quick wins are ≤1 SP auto-proceed.
