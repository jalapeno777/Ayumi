# BQ-774: Forward Test Resilience Integration Tests

**Status:** Plan | **SP:** 1 | **Type:** Test-only | **Date:** 2026-06-12

## Context

The forward test resilience code is live and stable. The following features were implemented and are running in production but have **zero integration test coverage**:

| Feature | Location | What it does |
|---------|----------|--------------|
| State machine | `connection_state.py` | Thread-safe `ConnectionStateManager` with validated transitions |
| Startup token validation | `open_api_spot_feed.py:293-304` | Rejects placeholder/empty tokens before connecting |
| Kill switch auto-clear | `open_api_spot_feed.py:775-784` | Clears stale FREEZE on successful auth |
| Stale tick → FREEZE | `open_api_spot_feed.py:1990-2020` | No ticks for 120s → `activate_global_freeze` |
| Health monitor loop | `forward_test_engine.py` `_health_monitor_loop` | 5s loop: heartbeat, feed health, error rate |
| Feed disconnect → FREEZE | `forward_test_engine.py` `_check_feed_health_kill_switch` | Feed disconnected → freeze, manual recovery |

### Existing Test Coverage

- `tests/test_open_api_spot_feed.py` — Unit tests for tick callbacks, token refresh, multi-symbol subscriptions, state transitions. **No resilience tests.**
- `tests/test_forward_test_live_execution.py` — Property checks (`is_paper_mode`, `is_connected`, `resolve_symbol_id`). **No integration tests.**

## Test Plan

### Test Suite 1: Startup Token Validation

**File:** `tests/test_resilience_integration.py` (or split into `test_startup_validation.py`)

**Tests:**

| # | Test | Validates |
|---|------|-----------|
| 1.1 | `test_start_rejects_placeholder_access_token` | `start()` returns `False` when access token is `"***"`, `"changeme"`, `"todo"`, `"none"`, `"null"`, `""` |
| 1.2 | `test_start_rejects_placeholder_refresh_token` | `start()` returns `False` when refresh token is a placeholder |
| 1.3 | `test_start_rejects_empty_access_token` | `start()` returns `False` when access token is empty string |
| 1.4 | `test_start_rejects_case_insensitive_placeholders` | `"CHANGE_ME"`, `"None"`, `"NULL"` are all rejected |
| 1.5 | `test_start_succeeds_with_valid_tokens` | `start()` proceeds (past validation) with real-looking tokens |

**Approach:** Construct `OpenApiSpotFeed` with placeholder tokens, mock `ReactorManager`, call `start()`, assert `False`. No network needed.

**Acceptance criteria:**
- All placeholder values in the `_PLACEHOLDER_VALUES` set are rejected
- Valid tokens pass validation (may fail later at network, but not at validation)

---

### Test Suite 2: Kill Switch Auto-Clear on Successful Auth

**File:** `tests/test_resilience_integration.py`

**Tests:**

| # | Test | Validates |
|---|------|-----------|
| 2.1 | `test_auto_clear_on_first_auth` | Kill switch active (FREEZE) → simulate successful auth flow → kill switch deactivated |
| 2.2 | `test_no_clear_when_kill_switch_inactive` | Kill switch not active → auth succeeds → `deactivate()` never called |
| 2.3 | `test_auto_clear_exception_does_not_break_auth` | Kill switch `is_active` throws → logged but auth continues |

**Approach:** Mock `KillSwitchManager` on the feed. Set kill switch to active (FREEZE). Trigger the auth completion path (call the method that sets state to AUTHENTICATED and runs auto-clear logic). Assert `deactivate(reason="auto_cleared_on_successful_auth")` was called.

**Key detail:** The auto-clear lives at line ~775-784, inside the initial auth completion flow. The builder needs to identify the exact method entry point (likely `_on_app_auth_completed` or similar after acct auth) and call it directly or simulate the auth callback chain.

**Acceptance criteria:**
- `kill_switch.deactivate()` called with reason `"auto_cleared_on_successful_auth"` when kill switch was active
- No call to `deactivate()` when kill switch was already inactive
- Exception in kill switch does not prevent auth completion

---

### Test Suite 3: Stale Tick → FREEZE

**File:** `tests/test_resilience_integration.py`

**Tests:**

| # | Test | Validates |
|---|------|-----------|
| 3.1 | `test_stale_ticks_60s_warn` | No ticks for 61s → WARNING logged (no freeze) |
| 3.2 | `test_stale_ticks_120s_freeze` | No ticks for 121s → `kill_switch.activate_global_freeze()` called |
| 3.3 | `test_stale_ticks_skipped_on_weekend` | Weekend (mock weekday=5) → no freeze even after 200s |
| 3.4 | `test_stale_ticks_skipped_when_not_authenticated` | State is `CONNECTING` → no freeze check |
| 3.5 | `test_stale_ticks_freeze_exact_threshold` | Exactly 120.0s → freeze activated (boundary test) |

**Approach:** 
1. Create feed, set state to AUTHENTICATED, set `_last_tick_recv_monotonic` to a known past value
2. Mock `time.monotonic()` to control elapsed time
3. Mock `datetime.now()` to control weekday
4. Call `_check_stale_ticks()` directly
5. Assert on kill switch mock calls

**Acceptance criteria:**
- 120s threshold triggers FREEZE with reason starting with `"stale_ticks:"`
- Weekend skip works (Saturday/Sunday)
- States other than AUTHENTICATED/DEGRADED skip the check

---

### Test Suite 4: Feed Disconnect → FREEZE (ForwardTestEngine)

**File:** `tests/test_resilience_integration.py` or `tests/test_forward_test_resilience.py`

**Tests:**

| # | Test | Validates |
|---|------|-----------|
| 4.1 | `test_feed_disconnect_activates_freeze` | `feed.is_running = False` + `_check_feed_health_kill_switch()` → FREEZE activated |
| 4.2 | `test_feed_reconnect_does_not_auto_recover` | Feed reconnects after freeze → kill switch stays active |
| 4.3 | `test_no_freeze_when_feed_connected` | `feed.is_running = True` → no freeze |
| 4.4 | `test_no_freeze_when_already_frozen` | Already frozen → no duplicate activation |

**Approach:** Construct `ForwardTestEngine` with mock feed and mock kill switch. Set `feed.is_running` to False. Call `_check_feed_health_kill_switch()`. Assert kill switch state.

**Acceptance criteria:**
- Feed disconnect triggers exactly one FREEZE activation
- Reconnect does NOT auto-clear (manual recovery required)
- No false positives when feed is healthy

---

### Test Suite 5: Connection State Machine Transitions

**File:** `tests/test_connection_state_resilience.py`

**Tests:**

| # | Test | Validates |
|---|------|-----------|
| 5.1 | `test_reconnect_transition_from_authenticated` | AUTHENTICATED → RECONNECTING → CONNECTING → CONNECTED → APP_AUTHENTICATING → ACCT_AUTHENTICATING → AUTHENTICATED (full reconnect cycle) |
| 5.2 | `test_invalid_transition_rejected` | DISCONNECTED → AUTHENTICATED rejected |
| 5.3 | `test_degraded_to_reconnecting` | AUTHENTICATED → DEGRADED → RECONNECTING → ... → AUTHENTICATED |
| 5.4 | `test_failed_to_disconnected_only` | FAILED → DISCONNECTED works; FAILED → AUTHENTICATED rejected |
| 5.5 | `test_callbacks_fire_on_state_change` | Callback receives (old_state, new_state, reason, metadata) |
| 5.6 | `test_self_transition_no_callback` | AUTHENTICATED → AUTHENTICATED is valid but no callback fired |

**Approach:** Direct unit tests on `ConnectionStateManager`. No mocking needed beyond the class itself.

**Acceptance criteria:**
- All valid transitions succeed, all invalid transitions return `False`
- Callbacks fire exactly on state changes (not self-transitions)
- Thread safety: two threads transitioning simultaneously don't corrupt state

---

### Test Suite 6: Disconnect Recovery Integration

**File:** `tests/test_resilience_integration.py`

**Tests:**

| # | Test | Validates |
|---|------|-----------|
| 6.1 | `test_disconnect_triggers_reconnecting_state` | Mid-session disconnect → state transitions to RECONNECTING |
| 6.2 | `test_reconnect_restores_authenticated` | Reconnect cycle completes → AUTHENTICATED + kill switch auto-cleared |
| 6.3 | `test_max_reconnect_attempts_circuit_breaker` | Exceed max attempts → engine stops gracefully |
| 6.4 | `test_reconnect_backoff_increases` | Each failed attempt doubles delay up to max |

**Approach:** 
1. Construct `ForwardTestEngine` with mock feed
2. Simulate ticks flowing (healthy state)
3. Set `feed.is_running = False`, simulate stale ticks
4. Call `_check_connection_health()` to trigger reconnect path
5. Verify state transitions and backoff behavior

**Acceptance criteria:**
- Disconnect → RECONNECTING state transition
- Successful reconnect → AUTHENTICATED + kill switch cleared
- Max attempts → engine stops (not crashes)
- Backoff follows exponential pattern capped at `max_reconnect_delay_sec`

---

## Test Infrastructure Notes

### Mock Strategy (Builder Decides)

The builder should choose between:
1. **Direct method testing** — Call `_check_stale_ticks()`, `_check_feed_health_kill_switch()` etc. directly with controlled state. Simplest and recommended for most tests.
2. **Callback simulation** — Trigger the protobuf message callbacks that lead to state transitions. More realistic but requires more setup.

### Shared Fixtures

```python
@pytest.fixture
def mock_kill_switch():
    """KillSwitchManager with temp state dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield KillSwitchManager(state_dir=tmpdir)

@pytest.fixture  
def feed_with_kill_switch(mock_kill_switch):
    """OpenApiSpotFeed with mock reactor and real kill switch."""
    # ... construct feed, set_kill_switch ...
```

### Key Mocking Points

| What to mock | Why |
|-------------|-----|
| `ReactorManager` | Prevent real network |
| `time.monotonic()` | Control stale tick elapsed time |
| `datetime.now(timezone.utc)` | Control weekday for weekend skip tests |
| `feed.is_running` | Control connected state |
| `KillSwitchManager` (or use real with temp dir) | Verify activate/deactivate calls |

## Acceptance Criteria Summary

| Criterion | Verification |
|-----------|-------------|
| All 6 test suites pass | `pytest tests/test_resilience_integration.py tests/test_connection_state_resilience.py -v` |
| No real network calls | All tests run without cTrader connection |
| Startup validation blocks placeholders | Suite 1 |
| Kill switch auto-clears on auth | Suite 2 |
| Stale ticks trigger FREEZE at 120s | Suite 3 |
| Feed disconnect triggers FREEZE | Suite 4 |
| State machine transitions are valid | Suite 5 |
| Disconnect recovery restores AUTHENTICATED | Suite 6 |
| Weekend skip works | Test 3.3 |
| No auto-recovery on reconnect | Test 4.2 |

## Out of Scope

- Performance/load testing
- Real network integration tests (those are forward test validation, not unit tests)
- Kill switch file persistence tests (already implicitly tested by `KillSwitchManager` internals)
- Error rate monitor tests (separate concern, can be added later)
