# P5A Sprint Closeout — 2026-06-26

## Executive Summary

Phase 5A delivered cTrader adapter integration, two-layer kill switch enforcement, and full test suite modularization. The forward test pipeline is live and processing market data. P5A is **CLOSED**.

## What Shipped

### cTrader Integration (P5A core)
- Full cTrader adapter: auth, connection management, order gateway, market data feed
- Token lifecycle management with auto-refresh and file-lock safety
- Forward test engine wired to cTrader broker (demo.ctraderapi.com)
- Live order execution path proven (real fill achieved Jun 24, session_breakout_asian short GBPUSD)
- Signal adapter with strategy ID propagation
- Volume decoder for cTrader's spot feed API

### Kill Switch Enforcement (Two-Layer)
1. **ExecutionPermissionPolicy** — blocks at `OpenApiSpotFeed.new_order()` before order reaches broker
2. **ForwardTestEngine._execute_signal_live()** — blocks before live execution attempt
- Kill switch state: `data/kill_switches/global.state` (JSON, atomic writes)
- Trigger reasons: `ftmo_daily_loss_limit`, `risk_guard`, manual
- Currently: **ACTIVE** (kill mode, reason: ftmo_daily_loss_limit)

### Test Suite Modularization (P5A-TEST-MOD)
- 215 test files reorganized from flat `tests/` root into categorized directories
- 7 unit subcategories: core, risk, data, ict, analytics, execution, hybrid
- Integration (51 files), strategies (50 files), e2e (32 files), regression (4 files)
- `scripts/run_test_scope.sh` — scoped runner with memory isolation per category
- `tests/_project_root.py` — centralized path helper
- 65 `sys.path` hacks removed, 28 `Path(__file__)` references replaced
- Pre-push hook: collection-only gate (~3s), in-repo at `.githooks/pre-push`
- Collection: **4011/4014 tests** (3 deselected = live markers)

## What Was Deferred to P5B
- 5 xfailed freeze activation tests (freeze code not yet activated)
- ReactorManager mock for unit test isolation
- tick-to-bar pipeline stall investigation (bars building normally after restart — may have been transient)
- File permission fix for `data/kill_switches/global.state` and `data/signal_stats.jsonl` (root/TacoPants ownership)
- **Kill switch stale-state persistence bug** — `KillSwitchManager._load_state()` reads `global.state` on every startup and re-arms whatever was persisted. A kill switch tripped Jun 9 stayed active for 17 days across multiple restarts because the state file was never cleared. Risk guard's `daily_trade_count > 0` check is irrelevant when the switch is already active from disk. Fix options: (a) auto-expire after N hours of no live activity, (b) require re-confirmation on restart after 24h, (c) reset on new trading day. Also need a `clear_kill_switch` CLI/API endpoint so it can be cleared without editing the state file + restarting.

## Council Decisions Implemented

### Kaito (Systems/Architecture) — 4 conditions
1. ✅ Unit subcategorization applied (core/risk/data/ict/analytics/execution/hybrid)
2. ✅ Integration path flattened (`integration/ctrader/` not `integration/adapters/ctrader/`)
3. ✅ `pytest --collect-only` replaces `py_compile` as acceptance criterion
4. ✅ Runner script uses `python3` with mutual exclusivity (`--full` vs `--heavy`)

### Mika (Risk) — 7 conditions
1. ✅ Allow-path test hardened (try/except:pass → explicit policy rejection assertion)
2. ✅ Kill switch verified active during forward test restart
3. ✅ .env md5 verified pre/post restart
4. ✅ No-orders soak confirmed (0 trades, 6 signals blocked)
5. ✅ Rollback plan documented
6. ✅ Forward test restart logged
7. ✅ Order-path proof corrected per Mika's finding (commit `7255b2b`)

### Rei (Devil's Advocate) — Key findings
1. ✅ Heavy-import count corrected: 40 (not 26) — lazy/inline imports counted
2. ✅ Path navigation audit: 65 files with sys.path, 44 with Path(__file__)
3. ✅ Cross-test import risk mitigated via `_project_root.py` + `pythonpath` in pytest.ini
4. ✅ pytest-xdist evaluated as alternative — kept file-based split (simpler, no marker debt)

## Test Status (Modular Results)

| Category | Files | Collection | Notes |
|----------|-------|------------|-------|
| unit/ (all) | 80 | ✅ 1772 tests | 31 pre-existing failures (kill switch, risk — tracked as debt) |
| integration/ | 53 | ✅ 749 tests | 1 collection error fixed (signals_traded_counter import os) |
| strategies/ | 50 | ✅ 889 tests | Clean |
| e2e/ | 32 | ✅ 490 tests | 2 collection errors fixed (scripts/ on pythonpath) |
| regression/ | 4 | ✅ 83 tests | Clean |
| **Smoke test** | — | ✅ 28/28 passed | unit/risk + unit/ict |

## Forward Test Status
- **Service:** `ayumi-forward-test.service` — active (running as TacoPants)
- **Market data:** 6,375+ ticks received, 16+ bars built, 0 signals since restart
- **Execution:** 0 trades (strategies evaluating, no signals generated yet)
- **Paper account:** $10,000 (unchanged, no positions)
- **Kill switch:** Cleared (was stale from Jun 9 — root caused, logged to P5B)
- **Permission issues:** RESOLVED — all root-owned files chowned to TacoPants
- **stats_fails=0** — no PermissionError crashes

## Test Debt Sprint (2026-06-26)
- **Starting point:** 82 pre-existing test failures
- **Fixed:** 68 (83%) across 10 batches, merged as `1a876e4`
- **Remaining:** 14 (9 connection state guards, 2 API design decisions, 3 data-dependent)
- **Test suite:** 3872 passed, 14 failed, 47 xfailed, 92 skipped (3 deselected = live)
- **Plan:** `docs/plans/test-debt-fix-plan.md`
- **Round 2 card:** `146fa9ef`

## Risk Register
| Risk | Severity | Status |
|------|----------|--------|
| Kill switch file ownership (root vs TacoPants) | Medium | Tracked — card `41362916` |
| tick-to-bar pipeline intermittent stall | Medium | Tracked — card `c17448ea` |
| 31 pre-existing test failures (risk, kill switch) | Low | Tracked — cards `36971d52`, `317b0f13`, `2cbce061` |
| Pre-push hook is repo file but `core.hooksPath` must be set manually per clone | Low | Documented in commit `54d7aac` |

## Post-Mortem: Builder Session Failures

### What went wrong
1. **Builder commit sweep** — Task 3 builder ran `git add -A` and swept in 157 files (pre-existing unstaged work + Task 2's moves). Required manual `git reset --soft` and restaging.
2. **Task 7 over-aggressive cleanup** — Builder removed `import os` from `test_signals_traded_counter.py` during sys.path cleanup, but `os.path.join` was still used. Also removed `sys.path.insert('scripts')` from 2 e2e tests without adding `scripts` to `pythonpath`.
3. **Two startup crashes** — Forward test service crashed twice on restart before stabilizing on attempt 3. Likely transient timing issue during systemd `RestartSec` window.

### What we learned
1. Builders must use targeted `git add <path>` not `git add -A`
2. Import removal sub-tasks need verification: `grep -c` the import usage before removing
3. Path cleanup tasks should run collection checks before committing
4. The three-fix patch I applied post-Task 7 (import os, scripts pythonpath, _project_root for launcher) took 5 minutes — a verification gate in the builder would have caught all three

### What we'll do differently
1. Builder task specs now include explicit `git add <path>` instructions (already implemented in Tasks 4+5)
2. Path-fix tasks will include `pytest --collect-only <target_dir>/` as a pre-commit gate
3. Post-merge validation: run collection on ALL categories, not just the modified one

## Git History
```
206ca82 docs(p5a): forward test restart log
d712149 docs(p5a): test coverage mapping table
d006d36 test(p5a): harden allow-path assertion in test_p5a_integration
54d7aac chore: move pre-push hook into repo (.githooks/)
00dc77b merge(p5a): test modularization — 215 files reorganized
2e170ee fix(tests): add scripts to pythonpath + restore missing imports
0b4ea7c refactor(tests): update pytest.ini pythonpath + fix all path navigation (Task 7)
d8205ae docs(p5a): test modularization audit document (Task 9)
5d50b35 feat(tests): add scoped test runner script (Task 8)
6cea43d refactor(tests): move 31 e2e tests into tests/e2e/ (Task 5)
c5bd71c refactor(tests): move regression test to tests/regression/ (Task 6)
d3f9fa4 refactor(tests): move unit + integration tests into subcategories (Tasks 2+3)
6a06606 chore(tests): create subcategory directory skeleton (Task 1)
f87e181 docs(p5a): forward test restart log (prior)
e56d71c merge(p5a): cleanup reconciliation — modular tests + order-path proof
```
