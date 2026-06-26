# Test Coverage Mapping — Modular Test Split

**Generated:** 2026-06-26
**Source:** P5A-TEST-MOD categorization
**Total:** 216 test files, 40 heavy-import files

## Category Coverage Map

| Category | Files | Heavy | Covers |
|----------|-------|-------|--------|
| `unit/core` | 34 | 9 | Engine, indicators, types, calculators, mixins, trade mgmt |
| `unit/risk` | 13 | 1 | Position sizing, kill switch, risk guard, gate tuner |
| `unit/data` | 4 | 4 | Loaders, sources, parquet, backfill |
| `unit/ict` | 3 | 0 | ICT pure logic: H4 context, volume delta, M/W |
| `unit/analytics` | 16 | 5 | Session analyzers, regime, correlation, ML pipeline |
| `unit/execution` | 4 | 0 | Paper trader, position monitor/tracker |
| `unit/hybrid` | 6 | 0 | Hybrid strategy engine, CLI, signal |
| `integration` | 42 | 0 | Connection, execution, market data, token lifecycle |
| `integration/ctrader` | 9 | 0 | P5A adapter: auth, env, volume, permissions |
| `strategies` | 46 | 16 | Strategy implementations, signal engine, routing |
| `strategies/ict` | 3 | 0 | ICT pure logic: FVG, order block, confluence |
| `e2e` | 31 | 1 | Full backtest runs, forward test, live trading, portfolio |
| `regression` | 4 | 3 | Regression metrics, golden files, statistical validation |
| `fixtures` | 1 | 1 | Shared fixtures (historical strategy PnLs) |
| **Total** | **216** | **40** | |

## How to Run

```bash
# Single category
bash scripts/run_test_scope.sh --unit

# Heavy-import files only (memory isolation)
bash scripts/run_test_scope.sh --heavy

# All categories sequentially (separate processes)
bash scripts/run_test_scope.sh --full

# Include live/e2e tests
bash scripts/run_test_scope.sh --full --live

# Dry run (collection only)
bash scripts/run_test_scope.sh --unit --collect-only
```

## Memory Notes

- Heavy categories (`strategies`: 16, `unit/core`: 9, `unit/analytics`: 5) should be run in isolation during development
- The `--full` runner isolates each category in a separate pytest process, preventing memory accumulation
- Pre-push hook runs `--collect-only` on all categories (~3s) to catch import/path breaks without executing tests
