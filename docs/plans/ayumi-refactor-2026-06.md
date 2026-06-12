# Ayumi Infrastructure Refactor — 2026-06

**Goal:** Modularize the forward test pipeline so subsystems can be developed, tested, and deployed independently without regressions.  
**Trigger:** Forward test has been broken more than functional over the past 2 weeks due to tight coupling between auth, connection, risk, and feed logic.

---

## Architecture Overview (Current vs Proposed)

### Current: Monolithic `open_api_spot_feed.py` (2100+ lines)

```
open_api_spot_feed.py
├── TCP connection management
├── ProtoBuf encoding/decoding
├── App authentication
├── Account authentication
├── Token validation + refresh
├── Bar building from ticks
├── Kill switch management
├── Spread tracking
├── Heartbeat / stale tick detection
├── State machine transitions
├── Symbol subscription management
└── Error recovery / self-healing
```

### Proposed: Modular Pipeline

```
ctrader/
├── auth.py                    # NEW — Authentication manager
│   ├── CTraderAuth
│   ├── app_authenticate()
│   ├── account_authenticate()
│   ├── validate_tokens()
│   ├── refresh_tokens()
│   └── Credentials management (load/save from data/.credentials)
│
├── connection.py              # NEW — TCP + reconnection
│   ├── CTraderConnection
│   ├── connect() / disconnect()
│   ├── reconnect_with_backoff()
│   ├── Health monitoring
│   └── Proto encode/decode wrapper
│
├── bar_builder.py             # NEW — Bar aggregation
│   ├── BarBuilder
│   ├── update_tick() → bar events
│   ├── finalize_bar()
│   ├── Multi-timeframe support
│   └── Bar integrity checks
│
├── token_manager.py           # EXISTS — keep, minor fixes
│
├── kill_switch.py             # EXISTS — keep, DI complete
│
├── risk_guard.py              # EXISTS — keep, DI complete
│
├── open_api_spot_feed.py      # SLIMMED — orchestrator only
│   ├── Composes: auth, connection, bar_builder
│   ├── Tick routing
│   └── Callback dispatch
│
├── forward_test_engine.py     # EXISTS — minimal changes
│
├── state_machine.py           # EXISTS — keep as-is
│
└── models.py                  # EXISTS — keep as-is
```

---

## Module Specs

### 1. `auth.py` — Authentication Manager

**Purpose:** Own ALL credential and authentication logic. Once working, nothing else touches auth.

**Responsibilities:**
- Load credentials from `data/.credentials` (NOT `.env`)
- App authentication (ProtoAuthRequest)
- Account authentication (ProtoAccountAuthRequest)
- Token validation (placeholder detection, expiry checking)
- Token refresh (via cTrader `/apps/token` endpoint)
- Credential persistence (atomic write to `data/.credentials`)
- Migration: on first load, migrate tokens from `.env` to `data/.credentials` with warning

**Interface:**
```python
class CTraderAuth:
    def __init__(self, credentials_path="data/.credentials"):
        """Load credentials from dedicated file, not .env."""
    
    @classmethod
    def from_env(cls) -> "CTraderAuth":
        """Migrate: load from .env, save to data/.credentials, warn about migration."""
    
    def app_authenticate(self, client) -> bool:
        """Perform app-level auth. Returns success."""
    
    def account_authenticate(self, client, account_id) -> bool:
        """Perform account-level auth. Returns success."""
    
    def validate_tokens(self) -> TokenValidationResult:
        """Check tokens are present, not placeholders, not expired."""
    
    def refresh_tokens(self) -> bool:
        """Refresh via cTrader API. Save new tokens to credentials file."""
    
    @property
    def access_token(self) -> str: ...
    @property
    def refresh_token(self) -> str: ...
```

**Credentials file format** (`data/.credentials`, gitignored, chmod 600):
```json
{
  "version": 1,
  "client_id": "...",
  "client_secret": "...",
  "access_token": "...",
  "refresh_token": "...",
  "account_id": "...",
  "trader_login": "...",
  "last_refreshed": "ISO-8601"
}
```

**Tests:**
- Test app auth with mock client
- Test account auth with mock client  
- Test token validation (placeholder, expired, valid)
- Test token refresh with mock HTTP
- Test credentials file read/write
- Test migration from .env
- **Test that no plaintext credentials appear in logs**

**Estimated SP:** 3

### 2. `connection.py` — Connection Manager

**Purpose:** Own TCP connection lifecycle, reconnection, and health.

**Responsibilities:**
- TCP connect/disconnect to cTrader API
- ProtoBuf message send/receive
- Reconnection with exponential backoff + jitter
- Connection health monitoring (heartbeat, stale detection)
- State machine integration (reporting transitions)

**Interface:**
```python
class CTraderConnection:
    def __init__(self, host: str, port: int): ...
    
    def connect(self) -> bool: ...
    def disconnect(self) -> None: ...
    def send(self, message: ProtoMessage) -> None: ...
    def set_message_callback(self, callback) -> None: ...
    
    @property
    def is_connected(self) -> bool: ...
    @property
    def uptime_seconds(self) -> float: ...
```

**Estimated SP:** 2

### 3. `bar_builder.py` — Bar Aggregation

**Purpose:** Extract bar building logic from the feed into its own testable unit.

**Responsibilities:**
- Aggregate ticks into OHLCV bars for multiple timeframes
- Bar completion detection and callbacks
- Forming bar management (current bar, not yet closed)
- Bar integrity validation
- Max bar history management

**Interface:**
```python
class BarBuilder:
    def __init__(self, timeframes: list[int], max_bars: int = 500): ...
    
    def update_tick(self, tick: Tick) -> list[Bar]:
        """Process tick. Returns any newly completed bars."""
    
    def get_bars(self, timeframe: int) -> list[Bar]: ...
    def get_current_bar(self, timeframe: int) -> Bar | None: ...
    def preload_bars(self, timeframe: int, bars: list[Bar]) -> None: ...
    
    @property
    def total_bars_built(self) -> int: ...
```

**Estimated SP:** 2

### 4. Slimmed `open_api_spot_feed.py`

After extraction, this becomes an orchestrator:
- Composes `CTraderAuth`, `CTraderConnection`, `BarBuilder`
- Routes ticks to bar builder
- Dispatches callbacks (on_tick, on_bar_close, on_disconnect)
- Manages subscription lifecycle
- Kill switch integration

**Target:** < 500 lines (down from 2100+)

**Estimated SP:** 2

---

## Development Workflow Changes

### Builder Safety Rules (Enforced)

1. **No `.env` modification** — Builders never read or write `.env`. Credentials live in `data/.credentials`.
2. **No `data/` writes** — Builders write only to `src/` and `tests/`. Runtime data files are created by production code.
3. **No `logs/` writes** — Obvious.
4. **File ownership** — All builder file writes must `chown TacoPants:TacoPants`. Enforced by wrapper script.
5. **Kill switch DI** — All tests that touch kill switch or risk guard must inject mocks. No default-path `KillSwitchManager()` in test code.

### Pre-Merge Checklist

Every PR/commit must pass:

```bash
# 1. Unit tests (existing)
python3 -m pytest tests/ -q

# 2. Import smoke test (new)
python3 -c "from adapters.ctrader.auth import CTraderAuth; print('OK')"

# 3. No plaintext credentials in source (new)
! grep -rn "client_secret.*=\|access_token.*=.*['\"][a-f0-9]" src/ --include="*.py"

# 4. File ownership check (new)
find src/ tests/ -user root | wc -l  # must be 0
```

### Smoke Test Script

`scripts/smoke_test.sh` — runs before every restart:
```bash
#!/bin/bash
# Validates forward test can start without crashing
# Tests: imports, config load, mock auth, no plaintext creds
```

**Estimated SP:** 0.5

---

## Migration Plan

### Phase 1: Credentials Boundary (Day 1)
- Create `data/.credentials` format
- Create `CTraderAuth` with migration from `.env`
- Update `open_api_spot_feed.py` to use `CTraderAuth`
- Smoke test script
- **SP: 3**

### Phase 2: Connection Extraction (Day 2)
- Extract TCP + reconnection into `CTraderConnection`
- Extract bar building into `BarBuilder`
- Slim `open_api_spot_feed.py`
- **SP: 4**

### Phase 3: Builder Safety (Day 2)
- Builder wrapper script with file ownership enforcement
- Pre-merge checklist integration
- Complete kill switch DI in all tests
- **SP: 1**

### Phase 4: Signal Focus (Day 3+)
- With stable infrastructure, return to signal sprint
- Strategy diagnostics, parameter audit, walk-forward validation

---

## Success Criteria

1. Forward test survives a full build sprint without regression
2. Auth works and tokens persist across restarts without `.env` modification
3. Builders can modify connection/risk/feed code without breaking auth
4. No plaintext credentials in any log file
5. No root-owned files in `src/` or `data/` after a build
6. Smoke test passes before every forward test restart

---

## BQ: Test Suite Refactor

**Problem:** Current e2e/integration tests run as monolithic one-shot methods that consume all server memory. Tests for the refactored modules need to be lightweight, modular, and memory-safe.

**Scope:**
- Replace one-shot e2e test methods with per-module unit + integration tests
- Each module (`auth`, `connection`, `bar_builder`, `feed`) gets its own test file
- Mock all external dependencies (TCP, Proto, cTrader API)
- Memory budget: no single test should exceed 100MB RSS
- Fixture-based setup instead of full engine bootstraps
- Kill switch / risk guard tests use DI mocks exclusively (no production state writes)
- Add memory profiling to CI: `pytest --memray` or similar

**Estimated SP:** 3

---

## Open Questions

- Should builders run as TacoPants instead of root? (Requires sudo config)
- Should `data/.credentials` be encrypted at rest? (Overkill for now?)
- Walk-forward period for signal validation — 6 months or 1 year?
