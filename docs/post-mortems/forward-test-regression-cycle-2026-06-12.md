# Post-Mortem: Ayumi Forward Test Regression Cycle

**Date:** 2026-06-12  
**Severity:** High — forward test has been non-functional more than functional  
**Author:** Ava

---

## What Happened

Over the past 2 weeks, the Ayumi forward test has been in a persistent cycle of **break → fix → break differently → fix again**. Today alone (June 12), the forward test was restarted at least 8 times. Each restart failed for a different reason:

| Time | Failure | Root Cause |
|------|---------|------------|
| ~12:00 | Auth failure | ProtoMessage double-wrap (fixed yesterday) |
| ~14:07 | Auth failure | DEBUG AUTH logging plaintext creds |
| ~14:09 | Working | Tokens valid, preloaded bars, evaluation running |
| ~16:03 | Kill switch activated | **Tests** wrote to production kill switch state file |
| ~17:46 | Permission denied (.env) | BQ-681 builder atomic write as root |
| ~17:49 | Permission denied (kill switch) | Same root ownership issue |
| ~17:55 | Token placeholder abort | BQ-681 startup validation too strict |
| ~18:18 | Invalid access token | **Tokens were overwritten by BQ-681 builder** |

The forward test was working at 14:09 with real tokens. By 18:18 the tokens were gone — replaced with placeholders by the BQ-681 builder's atomic .env write.

## Root Causes (Ranked by Impact)

### 1. Builders Run as Root, Production Runs as $USER
Every autobuild subagent runs as root. Every file it creates or modifies becomes root-owned. The production forward test service runs as $USER and can't read its own config files.

**Fix:** Builders must `chown $USER:$USER` after any file write, or run as $USER.

### 2. Tests Write to Production State
`RiskGuard._trigger_circuit_breaker()` creates a `KillSwitchManager()` with the default path (`data/kill_switches/`). When tests trigger the circuit breaker, they write to the same `global.state` file the production forward test reads on startup.

**Fix:** Dependency injection — tests inject mocks, production injects real instance. Partially fixed today but tests still fall through.

### 3. Atomic .env Writes Destroy Working Tokens
The BQ-681 token manager builder performed atomic writes to `.env` (temp file + rename). This is correct in principle but clobbered the real tokens that were set during the earlier auth debugging session. The builder had no awareness that `.env` contained live credentials.

**Fix:** Never touch `.env` from builders. Tokens live in a separate file (`data/token_state.json` or `data/.credentials`) that is gitignored and never modified by build agents.

### 4. No Separation Between Auth and Business Logic
`open_api_spot_feed.py` is a 2100-line file that handles:
- TCP connection management
- ProtoBuf message parsing
- Authentication (app + account)
- Token validation and refresh
- Bar building from ticks
- Kill switch management
- Spread tracking
- Heartbeat/stale tick detection

Any change to any of these concerns requires touching this file, which means any builder working on connection, auth, or kill switch logic risks breaking the feed.

### 5. No Integration Test Safety Net
The forward test itself is the integration test. There's no lightweight "can the system start and authenticate" test that catches regressions before they hit production. The 314 unit tests all pass — they just don't test the integration path.

## Pattern: Why This Keeps Happening

The core pattern is **tight coupling + build agents with no production awareness**:

1. A builder modifies a shared file (e.g., `.env`, `open_api_spot_feed.py`)
2. The modification doesn't account for runtime state (tokens, file ownership, kill switch state)
3. The forward test crashes on restart
4. We debug, fix the crash, restart
5. Another builder or change introduces a different crash
6. Repeat

Each individual fix is correct. The problem is that each fix exists in isolation — there's no boundary that prevents one subsystem from breaking another.

## Development Workflow Failures

| Failure | What Happened | Prevention |
|---------|---------------|------------|
| No pre-commit integration test | Commits landed that broke the forward test | Add a `scripts/smoke_test.sh` that runs before merge |
| Builders modify production files | `.env` clobbered by token manager builder | Builders forbidden from touching `.env`, `data/`, `logs/` |
| File ownership drift | Root-owned files break $USER service | `chown` as part of every builder write, or run builders as $USER |
| Kill switch state leak | Tests write to production state file | Dependency injection + test-specific state dirs |
| No token persistence boundary | Tokens stored in `.env` alongside config | Separate credentials file, gitignored, never touched by builders |

---

## Action Items

1. **Auth refactor** — Extract auth into `ctrader_auth.py` (own class, own tests, own state file)
2. **Credentials boundary** — Tokens in `data/.credentials` (gitignored), never in `.env`
3. **Builder sandbox rules** — Builders cannot write to `.env`, `data/`, or `logs/`
4. **Smoke test** — `scripts/smoke_test.sh` that validates: imports, config load, mock auth, no plaintext creds
5. **File ownership guard** — Post-build `chown` or builder runs as $USER
6. **Kill switch DI** — Complete the dependency injection fix so tests never touch production state

---

*This post-mortem will inform the Ayumi refactor spec (docs/plans/ayumi-refactor-2026-06.md).*
