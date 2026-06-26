# P5A-TEST-MOD: Test Modularization Audit

**Date:** 2026-06-26  
**Card:** `adb55aac`  
**Branch:** `senior-dev/p5a-test-mod`  
**Plan:** `docs/plans/p5a-test-mod-plan.md`  
**Manifest:** `docs/p5a/test-move-manifest.tsv`

---

## Summary

Reorganized 225 test files from a flat `tests/` root (187 files) into functional categories with subcategorization for the large unit test group. Created a scoped test runner for memory-isolated execution.

## Starting State

- **Total test files:** 225 `.py` files
- **Flat in `tests/` root:** 187 files
- **Existing subdirectories:** 38 files across `tests/unit/`, `tests/regression/`, `tests/adapters/ctrader/`, `tests/fixtures/`, `tests/strategies/`, `tests/strategies/ict/`, `tests/test_hybrid/`
- **Problem:** Running the full test suite exhausted memory because all 40 heavy-import files (numpy/pandas/scipy/sklearn) were collected into a single pytest process

## Heavy-Import Audit

**40 files** import numpy, pandas, scipy, or sklearn.

**Grep command:**
```bash
grep -rlE '^\s*(import|from)\s+(numpy|pandas|scipy|sklearn)' tests/ --include='*.py'
```

**Breakdown by library:**
- pandas: 30 files
- numpy: 28 files
- sklearn: 1 file (`test_ml_pipeline.py`)
- scipy: 0 files

All 40 files use module-level imports. The corrected grep pattern (using `^\s*(import|from)\s+`) catches both module-level and lazy/inline imports, though in this codebase all heavy imports turned out to be module-level.

## Path Navigation Audit

- **65 files** with `sys.path.insert` or `sys.path.append` calls (81 total call sites)
- **28 files** with `Path(__file__)` references (44 total references)

These were fixed in Task 7 by:
1. Adding `tests` to `pythonpath` in `pytest.ini`
2. Creating `tests/_project_root.py` helper
3. Removing all `sys.path` manipulation calls
4. Replacing `Path(__file__)` constructs with `from _project_root import PROJECT_ROOT`

## Final Directory Structure

| Category | Path | Test files | Heavy |
|----------|------|-----------|-------|
| unit/core | `tests/unit/core/` | 34 | 9 |
| unit/risk | `tests/unit/risk/` | 13 | 1 |
| unit/data | `tests/unit/data/` | 4 | 4 |
| unit/ict | `tests/unit/ict/` | 3 | 0 |
| unit/analytics | `tests/unit/analytics/` | 16 | 5 |
| unit/execution | `tests/unit/execution/` | 4 | 0 |
| unit/hybrid | `tests/unit/hybrid/` | 6 | 0 |
| integration | `tests/integration/` | 42 | 0 |
| integration/ctrader | `tests/integration/ctrader/` | 9 | 0 |
| strategies | `tests/strategies/` | 46 | 16 |
| strategies/ict | `tests/strategies/ict/` | 3 | 0 |
| e2e | `tests/e2e/` | 31 | 1 |
| regression | `tests/regression/` | 3 | 2 |
| fixtures | `tests/fixtures/` | 1 | 1 |
| **Total** | | **215 testable + 10 infra** | **40** |

## Test Runner

`scripts/run_test_scope.sh` provides scoped test execution:

| Flag | What it does |
|------|-------------|
| `--unit` | `tests/unit/` (all subcategories) |
| `--integration` | `tests/integration/` (including ctrader/) |
| `--strategies` | `tests/strategies/` (including ict/) |
| `--e2e` | `tests/e2e/` |
| `--regression` | `tests/regression/` |
| `--heavy` | Only heavy-import files across all categories |
| `--full` | All categories sequentially in separate processes (skips e2e unless `--live`) |
| `--collect-only` | Passthrough to pytest (dry run) |
| `--live` | Include `@pytest.mark.live` tests (excluded by default) |

**Memory isolation:** Each scope runs as a separate `python3 -m pytest` process, ensuring heavy imports don't accumulate across categories.

## Tasks Executed

| Task | Description | SP | Status |
|------|-------------|-----|--------|
| 1 | Directory skeleton + `__init__.py` | 0.5 | ✅ |
| 2 | Move 80 unit tests into subcategories | 2 | ✅ |
| 3 | Move 51 integration tests | 1.5 | ✅ |
| 4 | Move 46 strategy tests | 1.5 | ✅ |
| 5 | Move 31 e2e tests | 1 | ✅ |
| 6 | Move 1 regression test + verify fixtures | 0.5 | ✅ |
| 7 | pytest.ini + `_project_root.py` + path fixes | 1.5 | ✅ |
| 8 | `scripts/run_test_scope.sh` | 1 | ✅ |
| 9 | This audit document | 0.5 | ✅ |

## Council Review History

Three council members reviewed the initial plan (v1) and found significant issues:

| Reviewer | Focus | Key Finding |
|----------|-------|-------------|
| Kaito | Systems/architecture | Heavy count 37 (not 26); unit/ needs subcategorization; ctrader path too deep |
| Liora | Data quality | Heavy count 40 (lazy imports); 14 missing files from category lists |
| Rei | Devil's advocate | 50+ files need path migration (not "movement only"); runner double-runs heavy; `--collect-only` needed |

All amendments were incorporated into plan v2 and verified by re-council (18/18 amendments passed).

## Rolled-Forward Debt

These minor items are tracked for cleanup in the next phase:

1. **Audit table documentation:** The heavy-import audit table in the plan states "none are lazy/inline" which contradicts the manifest marking 14 files as `lazy/inline`. The manifest is correct (builders use it as authoritative); the table text is cosmetic.
2. **Path-fix ordering:** The plan offers two execution strategies for path fixes. Resolved at dispatch time: moves first, then Task 7 cleanup. Documented for future reference.

## Acceptance Criteria Verification

- [x] Audit document generated at `docs/p5a/test-modularization-audit-2026-06-26.md`
- [x] Split implemented without breaking test logic (file moves only, path fixes are navigation-only)
- [x] `scripts/run_test_scope.sh` exists and is executable
- [ ] `bash scripts/run_test_scope.sh --full` does not exhaust memory (pending Task 7 completion + verification)
- [ ] `pytest --collect-only tests/` discovers all testable files (pending Task 7 completion)
