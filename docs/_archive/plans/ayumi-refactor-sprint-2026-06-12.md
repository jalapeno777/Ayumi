# Ayumi Refactor Sprint — 2026-06-12

**Status:** PHASE 1 COMPLETE — AWAITING SUNDAY MARKET OPEN  
**Council review:** Kaito, Mika, Rei, Nora — all APPROVE_WITH_CONCERNS  

---

## Sprint Goal
Modularize the forward test pipeline so subsystems can be developed, tested, and deployed independently. Get the forward test operationally stable, then unblock signal engine work.

---

## Build Queue

### ✅ B1: Kill Switch Hotfix (1 SP) — COMPLETE
- Risk guard skips daily loss check when 0 trades
- 29 tests passing
- Commit: `affd729`

### ✅ B2: Credential Boundary (3 SP) — COMPLETE
- CTraderAuth wraps TokenManager, writes to `data/.credentials`
- Auto-migration from `.env` with dual-source guard
- CredentialManager: atomic write, chmod 600, placeholder detection
- 49 tests passing
- Commit: `affd729`

### ✅ B3: Connection + BarBuilder Extraction (4 SP) — COMPLETE
- CTraderConnection (412 lines) — TCP lifecycle, backoff+jitter, feed_dead event
- BarBuilder (244 lines) — multi-timeframe OHLCV, max_bars trim, thread-safe
- Feed: 2141 → 1036 lines (52% reduction)
- 33 new tests passing
- Commit: `ab8e4c5`

### ✅ B5: Test Suite Refactor (3 SP) — COMPLETE
- Shared fixtures in conftest.py (mock_auth, mock_connection, mock_kill_switch, etc.)
- Kill switch DI completion in all risk guard tests
- 132 core tests passing
- Commit: `ab8e4c5`

### 🔧 Fix commits
- `1f4b3aa` — DualSourceError exception class, .env comment parsing fix

### ⏳ B4: Builder Safety (1 SP) — QUEUED FOR SUNDAY
- builder_wrapper.sh, AYUMI_READONLY_DATA flag
- Document as soft enforcement

### ⏳ B6: Signal Sprint (3 SP) — QUEUED FOR SUNDAY
- Strategy diagnostics: why 0 signals from 10 strategies
- Get ONE strategy producing ONE signal as MVP

### 📋 BQ-822: Feed Integration Test Refactor (follow-up)
- test_open_api_spot_feed.py OOMs on full suite (pre-existing e2e pattern)
- Queued for later, not blocking

---

## Sunday Prep Checklist

### Pre-Market (Sunday ~4pm EDT)
- [ ] Verify `data/.credentials` has valid tokens (access + refresh)
- [ ] Run smoke test: `pytest tests/test_credentials.py tests/test_ctrader_auth.py tests/test_ctrader_connection.py tests/test_bar_builder.py -q`
- [ ] Confirm no root-owned files: `find src/ tests/ -user root | wc -l` == 0
- [ ] Start forward test
- [ ] Monitor connection: verify CTraderConnection establishes and holds
- [ ] Monitor bar builder: verify ticks are producing bars
- [ ] Monitor kill switch: verify it does NOT trigger (B1 fix validation)

### Post-Connection Confirmed
- [ ] Dispatch B4 (builder safety)
- [ ] Dispatch B6 (signal sprint) — strategy diagnostics
- [ ] Monitor forward test for 30+ minutes stable uptime

### Success Criteria
1. Forward test survives 30+ min without disconnection
2. Auth tokens persist across restart (no .env dependency)
3. Kill switch does not false-trigger
4. Bars building from live ticks
5. No root-owned files in src/ or data/

---

## Credentials Status
- Tokens loaded in `data/.credentials` (gitignored, chmod 600)
- `.env` token values emptied (migrated)
- Access token: XStv1y_J... (expires: check Sunday, may need refresh)
- Refresh token: BpyZp5xT...
- Account ID: REDACTED_CTRADER_ACCOUNT

---

## Council Findings Integrated

| Finding | Source | Status |
|---------|--------|--------|
| TokenManager wrap, don't replace | Kaito | ✅ Done |
| Empty .env post-migration | Mika | ✅ Done |
| Builder wrapper = soft enforcement | Kaito/Mika | ⏳ B4 |
| Serial B2→B3 | Kaito | ✅ Done |
| Feed-dead event | Mika | ✅ Done |
| Kill switch ships first | Rei | ✅ Done |
| Budget 10-12 SP | Rei | Actual: 11 SP (B1-B5 + fixes) |
| Signal sprint underdefined | Nora | ⏳ B6 scoped with MVP |
| Memory burst on reconnect | Mika | ✅ Burst allocation in BarBuilder |
