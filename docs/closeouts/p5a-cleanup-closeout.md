# P5A Cleanup Sprint Closeout

Date: 2026-06-26
Sprint: P5A Cleanup Reconciliation
Branch: `senior-dev/p5a-cleanup-reconciliation`
Baseline: `recovery/ayumi-mvp-rebuild` at `183a996`

## Objective

Reconcile the two P5A branches (`recovery/ayumi-mvp-rebuild` at `183a996` and
`senior-dev/p5a-mvp-safety-shell` at `c4c8e3e`), modularize tests, document
order-path coverage, and prepare a merge-ready cleanup branch.

## What Was Done

### Builder 1: Modularize P5A Tests ✅
- Ported 3 modular test files from `c4c8e3e`:
  - `test_execution_permission.py` (unit, 67 lines)
  - `test_p5a_characterization.py` (characterization, 98 lines)
  - `test_p5a_integration.py` (integration, 50 lines)
- Removed monolithic `test_p5a_kill_switch_enforcement.py` (375 lines)
- Coverage: 12 tests (up from 11), equivalent or stricter
- Commit: `ce79e3d`

### Builder 2: Safety Test Compatibility ✅
- Verified all existing safety tests pass on cleanup branch
- 5 freeze activation tests remain xfail (Mika's condition)
- Kill switch state unchanged: `active=true`, `mode=kill`
- No commit (verification only)

### Builder 3: Static Order-Path Proof ✅
- Documented all new-order paths in cTrader adapter layer
- 3 active guarded paths (policy gate at engine + spot feed)
- 1 delegated path (OrderManager → covered via current wiring)
- 1 dead path (OrderGateway, uninstantiated)
- 3 Phase 6 scope-outs (close_position, cancel_order, amend_sl_tp)
- Commit: `3e64ea3`

### Builder 4: Recovery Dirty-Tree Triage ✅
- 15 untracked files classified and excluded from P5A
- `test_live_market_data_integration.py` already committed, not dirty
- Commit: `21fd1e9`

### Builder 5: Merge Readiness ✅
- Sprint-close targeted suite: 115 passed, 29 xfailed, 5 xpassed
- `.env` hash verified: `fd97f00920199646df05046d19753912`
- Kill switch: `active=true`, `mode=kill`
- Forward test service: inactive
- No production code changed during cleanup

## Validation Evidence

### Sprint-Close Targeted Suite

```bash
/home/TacoPants/projects/Ayumi/.venv/bin/python3 -m pytest \
  tests/adapters/ctrader/test_execution_permission.py \
  tests/adapters/ctrader/test_p5a_characterization.py \
  tests/adapters/ctrader/test_p5a_integration.py \
  tests/test_kill_switch_auto.py \
  tests/test_ctrader_execution_v2.py \
  tests/test_forward_test_engine_wiring.py \
  tests/test_forward_test_live_execution.py \
  tests/test_forward_test_live_execution_outcomes.py \
  tests/test_resilience_integration.py \
  -v --timeout=30
```

Result: **115 passed, 29 xfailed, 5 xpassed** in 3.72s

### Pre-Existing Full Suite Baseline

From `/tmp/full-suite.log` (pre-cleanup): `3849 passed, 37 failed, 91 skipped, 47 xfailed, 5 xpassed`

The 37 failures are existing suite debt (parquet, backtest, ML modules).
Not caused or worsened by P5A cleanup.

## Commits on Cleanup Branch

| Commit | Description |
|--------|-------------|
| `ce79e3d` | test(p5a): modularize safety-shell validation |
| `3e64ea3` | docs(p5a): static order-path proof |
| `21fd1e9` | docs(p5a): cleanup validation report |

## Constraints Honored

- ✅ No trades
- ✅ No `.env` mutation (hash verified)
- ✅ No kill-switch state change
- ✅ No gateway restart
- ✅ No freeze activation code un-commented
- ✅ No Tsukasa dispatch
- ✅ No production code changed

## Council Conditions Status (from original P5A review)

| Condition | Source | Status |
|-----------|--------|--------|
| Default deny on missing policy | Kaito | ✅ Verified in `test_policy_denies_when_kill_switch_none` |
| Use `is_active()` not global check | Rei | ✅ Verified in `test_policy_uses_is_active_not_globally_killed` |
| No monitor reactivation | Mika | ✅ 5 freeze xfails confirmed (plus 5 xpass: stale-tick tests, not freeze suppression) |
| Two-layer enforcement | Mika | ✅ Engine + spot feed gates documented. Dual-instance blind spot noted (see order-path proof) — Phase 6 fix |
| Document broker-mutating scope-outs | Rei | ✅ Phase 6 scope-outs in order-path proof — includes live OpenApiSpotFeed methods + dual-instance note |
| Document residual TOCTOU | Rei | ✅ Included in order-path proof |
| Static proof of guarded paths | Kaito | ✅ `p5a-order-path-proof.md` |

## Next Steps

1. **Council re-review** (Kaito, Mika, Rei) — review cleanup branch
2. **Craig approval** — merge to `main`
3. **Merge** — `git checkout main && git merge --no-ff senior-dev/p5a-cleanup-reconciliation`
4. **Post-merge validation** — re-run targeted suite on `main`
5. **Forward test restart** — separate explicit approval required
6. **Push** — after validation passes on `main`
