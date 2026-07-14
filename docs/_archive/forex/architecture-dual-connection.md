# Architecture: cTrader Dual-Connection Model

**Author:** Tsukasa (Builder)
**Date:** 2026-07-01
**Status:** Active
**Related:** BQ-682, BQ-1381, [architecture-v2.md](./architecture-v2.md)

---

## 1. Overview

Ayumi's cTrader adapter uses a **dual-connection model**: two independent TCP connections to cTrader Open API, each with its own state machine, health monitoring, and reconnection logic.

| Connection | Role | Purpose | Default Port |
|---|---|---|---|
| **Market Data** | `ConnectionRole.MARKET_DATA` | Spot price feed, tick streaming, symbol subscriptions | 5035 (SSL) |
| **Trade Execution** | `ConnectionRole.TRADE_EXECUTION` | Order submission, position management, account state | 5035 (SSL) |

Both connections target the same cTrader host (`openapi.ctrader.com`) on port 5035 over SSL/TLS. They are logically independent — each has its own `CTraderConnection` instance, `ConnectionStateManager`, and reconnection tracking.

The `ConnectionManager` owns both connections and provides a unified health gate (`SplitBrainGate`).

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    ConnectionManager                     │
│                                                         │
│  ┌─────────────────┐       ┌─────────────────┐         │
│  │  MARKET_DATA    │       │ TRADE_EXECUTION │         │
│  │  ConnectionRole │       │  ConnectionRole │         │
│  ├─────────────────┤       ├─────────────────┤         │
│  │                 │       │                 │         │
│  │ CTraderConnection      │ CTraderConnection         │
│  │  (TCP 5035 SSL) │       │  (TCP 5035 SSL) │         │
│  │                 │       │                 │         │
│  │ StateManager    │       │ StateManager    │         │
│  │ Metrics         │       │ Metrics         │         │
│  └────────┬────────┘       └────────┬────────┘         │
│           │                         │                   │
│           └────────┬────────────────┘                   │
│                    │                                    │
│           ┌────────▼────────┐                           │
│           │  SplitBrainGate │                           │
│           │  (health gate)  │                           │
│           └────────┬────────┘                           │
│                    │                                    │
│           ┌────────▼────────┐                           │
│           │ConnectionWatchdog│                          │
│           │ (heartbeat mon) │                           │
│           └─────────────────┘                           │
└─────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────────────────────────────────────────────┐
│              cTrader Open API (port 5035 SSL)            │
│              openapi.ctrader.com                         │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Connection Lifecycle

### 3.1 State Machine

Both connections share the same state machine (`ConnectionState` enum):

```
DISCONNECTED → CONNECTING → CONNECTED → APP_AUTHENTICATING → ACCT_AUTHENTICATING → AUTHENTICATED
                                                                                    │
                                          ┌─────────────────────────────────────────┤
                                          │                                         │
                                     DEGRADED                                  RECONNECTING
                                          │                                         │
                                          └──────────────► AUTHENTICATED            │
                                          │                                         │
                                          └─► FAILED ◄─────────────────────────────┘
                                                  │
                                                  └─► DISCONNECTED (manual reset)
```

**Key states:**
- **AUTHENTICATED** — Fully operational. Both app and account OAuth tokens validated.
- **DEGRADED** — Connection alive but heartbeat stale. Still usable for read operations.
- **RECONNECTING** — TCP connection lost, attempting reconnection with backoff.
- **FAILED** — Reconnection exhausted. Requires manual intervention.

All transitions are validated against a strict transition table (`_VALID_TRANSITIONS` in `connection_state.py`). Invalid transitions are rejected and logged.

### 3.2 Connection Establishment

```
1. TCP connect → host:5035 (SSL)
2. App authentication (client_id + secret → app token)
3. Account authentication (access token → session)
4. State → AUTHENTICATED
5. Start health monitor (heartbeat loop)
```

**Auth retry (BQ-1330a):** Authentication wraps in `authenticate_with_retry()` with 3 attempts and exponential backoff (1s, 2s, 4s). This prevents the engine FSM from permanently dying on transient auth failures.

---

## 4. Failover Triggers

### 4.1 Heartbeat Watchdog

The `ConnectionWatchdog` runs as a daemon thread, polling each connection's last successful ping timestamp every 5 seconds.

| Trigger | Threshold | State Transition | Action |
|---|---|---|---|
| Silence ≥ 30s | `DEGRADED_THRESHOLD_S` | AUTHENTICATED → DEGRADED | Log warning, mark suspect |
| Silence ≥ 90s | `FAILED_THRESHOLD_S` | Any operational → FAILED | Log error, trigger reconnect evaluation |
| Heartbeat recovered | Next ping received | DEGRADED → AUTHENTICATED | Reset silence timer, log recovery |

**Note:** `CTraderConnection` also has its own internal health check with configurable thresholds (`_HEARTBEAT_DEGRADED_SEC = 35.0`, `_HEARTBEAT_RECONNECT_SEC = 60.0`). These operate on the same principle but at the individual connection level rather than the manager level.

### 4.2 Market Hours Awareness

Both the watchdog and connection health checks respect forex market close (Fri 21:55 UTC – Sun 21:00 UTC). During market close:
- Heartbeat-based reconnects are **suppressed** (`is_forex_market_closed()` guard)
- This prevents false reconnect triggers from expected tick silence during weekend

### 4.3 Error-Driven Failover

Errors are classified into 4 tiers via `error_classifier.py`:

| Tier | Examples | Action | Reconnect? |
|---|---|---|---|
| **TIER_1** (Transient) | CONNECTION_LOST, HEARTBEAT_TIMEOUT, TCP_RESET, DNS_FAILURE | Fast retry | Yes, short backoff |
| **TIER_2** (Backoff) | SERVER_NOT_READY, REQUEST_TIMEOUT, TOO_MANY_REQUESTS | Retry with longer backoff | Yes, 2x multiplier |
| **TIER_3A** (Operation) | INVALID_VOLUME, MARKET_CLOSED, BAD_REQUEST | Reject request | No — reconnect won't help |
| **TIER_3B** (System) | AUTH_EXPIRED, TOKEN_INVALIDATED, ACCOUNT_DISABLED | Halt | No — system failure |

---

## 5. Reconnection Strategy

### 5.1 Exponential Backoff with Decorrelated Jitter

Uses the AWS-style decorrelated jitter algorithm (`reconnect_strategy.py`):

```
sleep = min(cap, random(base, prev * 3))
```

- **Base:** 1.0s minimum sleep
- **Cap:** 60.0s maximum sleep
- **Max attempts:** 10 (default)
- **TIER_2 multiplier:** 2x more aggressive backoff

### 5.2 Stuck Reconnect Detection

The forward test engine includes a **stuck reconnect detector** (`_stuck_reconnect_threshold_sec = 60.0s`). If a connection remains in RECONNECTING/FAILED state for more than 60 seconds, a forced reconnect is triggered regardless of backoff scheduling.

---

## 6. SplitBrainGate

The `ConnectionManager` provides two health gates for different operational contexts:

### `is_fully_operational`
```python
True only when ALL connections are AUTHENTICATED
```
Used for: Full trading operations, new position entry.

### `is_tradeable`
```python
True when trade execution is AUTHENTICATED
  AND market data is at least DEGRADED
```
Used for: Conservative trading — allows order management with slightly stale prices.

### `is_data_available`
```python
True when market data connection is operational (AUTHENTICATED or DEGRADED)
```
Used for: Read-only operations, monitoring, display.

### Decision Context

Every trading decision captures a `ConnectionStateSnapshot` via `get_decision_context()`, embedding both connection states into the decision record for post-hoc analysis.

---

## 7. Reconciliation on Reconnect

When a connection recovers after a disconnect, position reconciliation is performed:

### 7.1 Preflight Reconciliation

The forward test engine performs a preflight reconcile before the first strategy evaluation:
```python
positions = self._market_feed.reconcile()  # Fetches all open positions from cTrader
```

### 7.2 Position Tracker

`PositionTracker.reconcile_with_ctrader()` fetches current open positions and compares against local state. Mismatches are logged:

1. Build `ProtoOAGetAccountListByCTIDLogin` request
2. Send via authenticated session
3. Parse response positions
4. Compare with local `PositionTracker` state
5. Log discrepancies (missing, extra, or modified positions)

### 7.3 Order Resolution on Reconnect

After reconnect, the spot feed resolves orphaned orders:
```python
positions = self.reconcile()
# Orders matched against broker positions
# Unresolved orders tagged with reason="resolved_by_reconcile"
```

---

## 8. Monitoring & Metrics

### 8.1 Metrics Emission

`ConnectionManager` emits structured JSONL metrics at a configurable interval (default 60s):

```json
{
  "timestamp": "2026-07-01T12:00:00Z",
  "type": "connection_metrics",
  "market_data": {
    "state": "authenticated",
    "uptime_1h": 99.5,
    "reconnects_1h": 0,
    "degraded_time_1h": 12.3
  },
  "trade_execution": {
    "state": "authenticated",
    "uptime_1h": 100.0,
    "reconnects_1h": 0,
    "degraded_time_1h": 0.0
  },
  "fully_operational": true,
  "error_tiers": {
    "t1": 0, "t2": 0, "t3a": 0, "t3b": 0
  }
}
```

### 8.2 Health Snapshots

`DualConnectionHealth` provides a point-in-time view:
- Per-connection: state, uptime %, reconnect count, degraded time
- Overall: `fully_operational` flag

### 8.3 Error Tier Tracking

All errors are tracked by tier in `ConnectionManager._error_tier_counts`, included in each metrics emission.

---

## 9. Token Lifecycle Management

### OAuth Token Flow

```
CredentialStore (.env) → TokenLifecycle → CTraderConnection
```

- **App token:** Client ID + secret → `ProtoOAClientAppAuth`
- **Access token:** Refresh token → `ProtoOAAccountAuth` (per CTID account)
- **Refresh:** `TokenLifecycle.ensure_valid()` checks expiry with 5-day buffer

### Token Refresh

`ConnectionManager.refresh_oauth_if_needed()` is called before critical operations:
1. Load credentials from `.env` via `CredentialStore`
2. Check token expiry via `TokenLifecycle`
3. Refresh if within 5-day buffer
4. Update internal auth state

---

## 10. File Inventory

| File | Responsibility |
|---|---|
| `connection.py` | TCP connection lifecycle (connect/disconnect/send/receive/reconnect) |
| `connection_state.py` | Thread-safe state machine with transition validation |
| `connection_watchdog.py` | Heartbeat watchdog (30s DEGRADED, 90s FAILED) |
| `connection_manager.py` | Dual-connection orchestrator, SplitBrainGate, metrics |
| `reconnect_strategy.py` | AWS-style decorrelated jitter backoff |
| `error_classifier.py` | 4-tier error classification |
| `token_lifecycle.py` | OAuth token validity and refresh |
| `credential_store.py` | `.env` credential loading |
| `open_api_spot_feed.py` | Market data feed (subscriptions, ticks, bars) |
| `position_tracker.py` | Position tracking and reconciliation |
| `forward_test_engine.py` | Engine FSM with reconnect and kill switch integration |

---

## 11. Gap Analysis

> **Note:** The original research doc (`docs/research/ctrader-connection-reliability-research.md`) referenced by BQ-682 was not found in the repository. The gap analysis below is reconstructed from inline docstring references (connection_state.py §2, reconnect_strategy.py §5–§6) and standard cTrader reliability practices. **Filing a follow-up card to locate or recreate the research doc is recommended.**

| # | Recommendation | Status | Evidence |
|---|---|---|---|
| 1 | **Dual TCP connections with independent state machines** | ✅ IMPLEMENTED | `ConnectionRole` enum, per-role `ConnectionStateManager`, `ConnectionManager.register()` |
| 2 | **Exponential backoff with decorrelated jitter** | ✅ IMPLEMENTED | `ReconnectStrategy` in `reconnect_strategy.py`, AWS formula, configurable base/cap/max-attempts |
| 3 | **Error tier classification for reconnect routing** | ✅ IMPLEMENTED | `error_classifier.py` with 4 tiers (T1 transient → T3B system), `decide_reconnect()` in ConnectionManager |
| 4 | **Heartbeat watchdog with DEGRADED/FAILED thresholds** | ✅ IMPLEMENTED | `ConnectionWatchdog` with 30s/90s thresholds, per-role tracking, recovery detection |
| 5 | **SplitBrainGate — require both connections for trading** | ✅ IMPLEMENTED | `ConnectionManager.is_fully_operational` + `is_tradeable` with graduated strictness |
| 6 | **Position reconciliation on reconnect** | ⚠️ PARTIAL | `reconcile()` exists in spot feed and position tracker. Forward test engine does preflight reconcile. **Gap:** No automatic reconcile-on-reconnect hook — reconciliation is called manually/preflight only, not triggered by state transition AUTHENTICATED (after RECONNECTING). |
| 7 | **Structured metrics emission for monitoring** | ✅ IMPLEMENTED | JSONL metrics via `ConnectionManager._metrics_loop()`, 60s interval, includes uptime/reconnects/degraded/error tiers |
| 8 | **Auth retry on transient failures** | ✅ IMPLEMENTED | `authenticate_with_retry()` (BQ-1330a) with 3 attempts, exponential backoff (1s/2s/4s) |
| 9 | **Market hours awareness (suppress false reconnects)** | ✅ IMPLEMENTED | `is_forex_market_closed()` guard in both `CTraderConnection._check_heartbeat()` and forward test engine reconnect logic |
| 10 | **Stuck reconnect detector** | ✅ IMPLEMENTED | Forward test engine `_stuck_reconnect_threshold_sec = 60.0s` forces reconnect evaluation |

### Summary

- **8/10 recommendations:** ✅ IMPLEMENTED
- **1/10 recommendations:** ⚠️ PARTIAL (auto-reconcile on reconnect)
- **1/10 recommendations:** ✅ IMPLEMENTED (bonus — market hours awareness, not in original research)

### Gap: Auto-Reconcile on Reconnect

The current implementation performs reconciliation only during preflight (before first strategy evaluation). When a connection drops and recovers mid-session, there is **no automatic reconciliation hook** triggered by the `RECONNECTING → AUTHENTICATED` state transition.

**Risk:** If positions change at the broker during the disconnect window (stop-loss hit, margin call, etc.), local state will be out of sync until the next manual or preflight reconcile.

**Recommendation:** Register a state-change callback in `ConnectionManager` that triggers `position_tracker.reconcile_with_ctrader()` when either connection transitions back to AUTHENTICATED from RECONNECTING/DEGRADED. **Follow-up card recommended.**

---

## 12. Cross-References

- [architecture-v2.md](./architecture-v2.md) — Overall Ayumi v2 architecture spec
- [ctrader-live-data-feed-integration.md](./ctrader-live-data-feed-integration.md) — cTrader feed integration details
- [forward-test-protocol.md](./forward-test-protocol.md) — Forward testing protocol
- `docs/research/ctrader-connection-reliability-research.md` — **MISSING** (referenced by source code docstrings in `connection_state.py` §2, `reconnect_strategy.py` §5–§6, `connection_watchdog.py` header). Recommend recreation or recovery.
- `docs/runbooks/paper-mvp-runbook.md` — Paper MVP operational runbook
- **BQ-682** — This documentation card
- **BQ-1381** — Related (referenced in card)
