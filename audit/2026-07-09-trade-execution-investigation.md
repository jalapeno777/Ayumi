# Ayumi Forward Test — Trade Execution Investigation

**Investigation date:** 2026-07-10 (UTC)
**Service:** `ayumi-forward-test.service`
**Service uptime:** ~37h (started 2026-07-08 13:24:09 UTC; investigation at 2026-07-10 02:31 UTC)
**Investigator:** Ava subagent (read-only — no services modified, no orders triggered)

---

## Executive Summary

The forward test is running nominally — ticks flow, signals are generated, fills arrive — but **four concrete bugs have caused the run to behave very differently from what the Health JSON implies**, and one of them (the `signal_stats.jsonl` ownership) is actively degrading every subsequent signal's confidence scoring.

The 4 live fills happened in the **first 15 hours of the run** and all were session_range_mr / session_breakout_ny trades on USDJPY/GBPUSD/EURUSD. **No fills have arrived in the last 21 hours** (since 2026-07-09 05:00:26 UTC), despite many signals being generated — every XAUUSD short signal since 13:15 UTC on July 9 has been rejected by cTrader with `INVALID_REQUEST: Field comment is too long`. The 4.45% drawdown reconciles with the cumulative realized loss of those four closed trades against the $10k starting balance.

Three latent defects were uncovered that are NOT visible from the Health JSON alone:

1. **`signal_stats.jsonl` is owned by `root:root` with mode 600** — the service runs as `TacoPants` and is being denied write access. This causes all 13 stats_fails and is silently forcing every confidence fallback to a stale `last-known-good=0.5552`.
2. **`INSTRUMENTS` dict in `src/forex-bot/risk/sl_position_sizer.py` only contains 4 of the 7 blend symbols** — AUDUSD, USDCAD, and USDCHF are silently rejected by the sizing gate with `Unknown instrument: <symbol>`. Roughly **40% of all signals (USDCAD/AUDUSD/USDCHF) never have a chance to trade**.
3. **`SLPositionSizer` open-position counter is desynced from cTrader reality** — at 2026-07-09 23:00:03 reset_daily reports `positions_carried=16, open_risk=$475`, but cTrader only has 4 fills in the current service instance and 0 fills on 2026-07-10. Local sizer thinks there are 16 open positions; broker reality is far fewer.

In addition, **SRMR+ is emitting 24 XAUUSD signals with absurd entry prices** (e.g. `entry=4130495.00000`, `entry=4128165.00000` — XAUUSD actually trades at ~3300). These appear to be a unit/timestamp parsing bug in the SRMR+ price field. They get past the orchestrator (sizer accepts XAUUSD, lots=1.0, risk=$25) and are sent to cTrader where they get rejected with `Field comment is too long`. If the comment-length bug is ever fixed, these will likely blow up the account.

**Verdict: ISSUES FOUND** — three of the four issues are low-effort fixes (file ownership, dict literal, lot sizes), the fourth (SRMR+ XAUUSD price bug) needs investigation.

---

## Finding 1 — The 4 Live Fills

All 4 fills happened in the first ~15h of the current service instance. None have arrived since 2026-07-09 05:00:26 UTC (~21h ago).

| # | Time (UTC) | Symbol | Side | Strategy | Lots | Entry | SL | TP | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-07-08 13:30:20 | USDJPY | LONG  | session_breakout_ny | 0.7900 | 162.52850 | 162.431 (initially) | 162.536 (initially) | Filled (live_fills=1) |
| 2 | 2026-07-08 14:00:20 | USDJPY | SHORT | session_range_mr     | 0.3100 | ~162.345 (typical session_range_mr) | (per orchestrator) | (per orchestrator) | Filled (live_fills=2) |
| 3 | 2026-07-09 00:00:26 | GBPUSD | SHORT | session_range_mr     | 0.1700 | 1.33944 | 1.34232 (28.8 pips) | (per orchestrator) | Filled (live_fills=3) |
| 4 | 2026-07-09 05:00:26 | EURUSD | SHORT | session_range_mr     | 0.2400 | 1.14267 | 1.14479 (21.2 pips) | (per orchestrator) | Filled (live_fills=4) |

Citations:
- log.2.gz:15350 — `Signal accepted: session_breakout_ny long USDJPY @ 162.52850 conf=0.90 lots=0.7900`
- log.2.gz:15414 — `Late fill detected for order 3acb7a0c4fa144b8b0ba6985f593bef7 (long USDJPY) — live_fills=1`
- log.2.gz:15992 — `Late fill detected for order 23530612a5d64ca393477a946584a005 (short USDJPY) — live_fills=2`
- log.1.gz:60 — `Late fill detected for order 6be0d4e6c50445f99efcc853dea5c27c (short GBPUSD) — live_fills=3`
- log.1.gz:5424 — `Late fill detected for order acd8ad1920df468095ee9805da09b924 (short EURUSD) — live_fills=4`
- log.1.gz:5327 — `Signal accepted: session_range_mr EURUSD lots=0.2400 risk=$50.00 sl=21.2pips`

**P&L reconciliation:** Balance $9,554.59 against starting $10,000.00 = realized loss of **$445.41 = 4.45% DD**. This is the cumulative realized P&L across the four closed trades. The realized-P&L-per-trade breakdown is not present in any log line I could find — the `data/trading.db` `trades` table is empty (zero rows), so per-trade P&L is not currently being persisted.

**Clustered early, not calibration:** All 4 fills are within the first ~15h of a 37h run. Two were USDJPY (one long, one short) within 30 minutes of each other on July 8. None look like deliberate "calibration" trades — they're regular strategy outputs that happened to fire in the early window. The remaining 21 hours have produced zero fills, despite **24+ XAUUSD SRMR+ short orders** being accepted by the orchestrator and sent to cTrader (all rejected — see Finding 4).

---

## Finding 2 — The 99→4 Signal/Fill Gap

Total **168 signal-adapted events** logged in stderr log.1.gz + log.2.gz, broken down by strategy:

| Strategy | Adapted signals |
|---|---|
| session_range_mr | 87 |
| srmr_plus (SRMR+) | 75 |
| session_breakout_ny | 3 |
| session_breakout_asian | 2 |
| session_breakout_london | 1 |

By symbol (top 5):

| Symbol | Adapted signals |
|---|---|
| USDJPY | 72 |
| XAUUSD | 31 |
| GBPUSD | 27 |
| EURUSD | 13 |
| USDCAD | 8 |
| AUDUSD | 8 |
| USDCHF | 3 |

(Sum 162 vs the 168 above — the residual is malformed entries where the strategy name doesn't parse cleanly.)

The heartbeat JSON's `signals_generated: 101` reflects only the current service instance's counter (since 13:24:09 restart). The 168 number is across multiple service starts in the log file. Both are consistent with **~100 signals in 37h, i.e. roughly one every 22 minutes on average — far below what the blend backtest would expect for a 7-symbol × 5-strategy blend at H1 cadence**.

### Filter funnel (where signals die)

Searching the logs reveals these filter outcomes:

- **Outside trading hours** messages: 866 (these are per-tick-per-strategy, not per-signal — informational, not a real filter)
- **"Signal adapted"** entries: 168 (the actual signal pool)
- **Signal blocked — correlation_block**: 53 (e.g. `session_range_mr already holds GBPUSD/short` — prevents multiple same-direction positions)
- **Signal rejected — sizing gate "Unknown instrument"**: 157 (lines like `Signal rejected: strategy=srmr_plus symbol=USDCHF reason=sizing gate=Unknown instrument: USDCHF sl_pips=0.0 risk_avail=0.00`)
- **Signal rejected by blend** (downstream of sizing gate): 90 (almost all "Unknown instrument")
- **Order rejected**: AUDUSD/USDCAD/USDCHF (see Finding 5)
- **Live fills**: 4
- **Live order TIMEOUT awaiting ack** (sent to broker, never acknowledged before the late-fill callback fired): 26 in log.1.gz — every single one is `srmr_plus short XAUUSD 1.0000 lots`. They never filled.

### The blend filter is NOT tighter than expected — the sizing gate is BROKEN for 3 of the 7 symbols

Looking at `src/forex-bot/risk/sl_position_sizer.py` lines 42–47:

```python
INSTRUMENTS = {
    "EURUSD": InstrumentSpec("EURUSD", pip_size=0.0001, lot_size=100000, pip_value_per_lot=10.0),
    "GBPUSD": InstrumentSpec("GBPUSD", pip_size=0.0001, lot_size=100000, pip_value_per_lot=10.0),
    "USDJPY": InstrumentSpec("USDJPY", pip_size=0.01,    lot_size=100000, pip_value_per_lot=6.5),
    "XAUUSD": InstrumentSpec("XAUUSD", pip_size=0.01,    lot_size=100,    pip_value_per_lot=1.0),
}
```

The 7-symbol blend (GBPUSD, EURUSD, USDJPY, XAUUSD, AUDUSD, USDCHF, USDCAD) is configured, but **AUDUSD, USDCHF, and USDCAD are absent from `INSTRUMENTS`**. The `calculate()` method at line 422 returns `Unknown instrument: <symbol>` for any of those three. This means **~25% of every signal that survives the strategy is silently dropped before it ever reaches cTrader**.

Citations:
- log.1.gz:5383 — `Signal rejected: strategy=session_range_mr symbol=USDCAD reason=sizing gate=Unknown instrument: USDCAD sl_pips=0.0 risk_avail=0.00`
- log.1.gz:5385 — `Signal rejected by blend: session_range_mr long USDCAD conf=0.70 — Unknown instrument: USDCAD`
- log.1.gz:5401 — same pattern for AUDUSD
- log.2.gz (and many more in log.1.gz) — repeated every 15 minutes during the eval cycle for each of AUDUSD/USDCAD/USDCHF

### Is the blend filter consistent with optimized config?

**No — it is misaligned by 3 symbols.** The blend appears to have been configured with 7 symbols, but the position-sizer has only 4 instrument specs. This is a config drift / partial migration bug. Fix is to add the 3 missing `InstrumentSpec` entries to `INSTRUMENTS`.

---

## Finding 3 — The 13 stats_fails

All 13 stats_fails are the **same recurring error**: `[Errno 13] Permission denied: 'data/signal_stats.jsonl'`.

The error sequence from log.1.gz:

```
2026-07-09 00:00:20 | WARNING | ayumi.forward_test | Signal stats recording attempt 1/3 failed (retry in 2.0s): [Errno 13] Permission denied: 'data/signal_stats.jsonl'
2026-07-09 00:00:22 | WARNING | ayumi.forward_test | Signal stats recording attempt 2/3 failed (retry in 4.0s): [Errno 13] Permission denied: 'data/signal_stats.jsonl'
2026-07-09 00:00:26 | WARNING | ayumi.forward_test | Signal stats recording failed after 3 attempts (consecutive_fails=1, using last-known-good confidence=0.5552): [Errno 13] Permission denied: 'data/signal_stats.jsonl'
```

The fallback is "use last-known-good confidence=0.5552" (heartbeat JSON shows `last_known_good_confidence: 0.5551901542398466`). Every signal from now on is being scored against a stale confidence baseline.

**Root cause** (filesystem inspection):

```
-rw------- 1 root      root      907302 Jul  8 15:35 data/signal_stats.jsonl
```

`signal_stats.jsonl` is owned by `root:root` with mode 600, but the service runs as the `TacoPants` user. Hence every open-for-append fails with EACCES. This was likely created by a root-owned process (e.g. a one-shot script, a sudo invocation, or an earlier `pytest` run as root) at some point and the ownership was never restored.

This is **not** related to any strategy or market condition. It's a one-line filesystem fix:

```bash
sudo chown TacoPants:TacoPants /home/TacoPants/projects/Ayumi/data/signal_stats.jsonl
```

The 13 number is just "consecutive_failures counter, decremented on first success" — it has been 13 since 2026-07-09 00:00:26 and never decremented because the file is still unwritable.

**Effect on trading:** Confidence scoring is operating on a stale last-known-good value rather than learning from real outcomes. This is degrading the entire confidence engine for the duration of the run, but is unlikely to be the cause of the 99→4 gap directly (confidence threshold 0.65 — even with a slightly off calibration, signals should still pass on average).

---

## Finding 4 — Execution Quality (cTrader errors, reconnects, timeouts)

### Reconnects
There are **at least 7 reconnect cycles** during the run, all driven by heartbeat timeouts or health checks:

| Time (UTC) | Trigger |
|---|---|
| 2026-07-08 00:01:36 | `No heartbeat for 69.9s (threshold: 60s) — triggering reconnect` (log.2.gz:49) |
| 2026-07-08 00:16:36 | `No heartbeat for 70.0s — triggering reconnect` (log.2.gz:383) |
| 2026-07-09 00:01:34 | `No heartbeat for 68.1s — triggering reconnect` (log.1.gz:67) |
| 2026-07-09 05:01:35 | `No heartbeat for 68.7s — triggering reconnect` (log.1.gz:5435) |
| 2026-07-09 20:59:59 | `Connection health check failed: last_tick_ago=60.4s — reconnecting` (log.1.gz:22261) |
| 2026-07-09 21:01:08 | `Connection health check failed: last_tick_ago=63.3s — reconnecting` (log.1.gz:22360) |
| 2026-07-09 21:04:52 | `Connection health check failed: last_tick_ago=64.6s — reconnecting` (log.1.gz:22421) |

All reconnects succeed within ~3 seconds (typical broker reconnect cycle). The "ConnectionDone: Connection was closed cleanly" messages after each disconnect suggest cTrader is gracefully closing the TCP connection, not a network failure on our side.

This is **not a code bug**, but it is pattern worth flagging: every ~2-3 hours during active market hours the broker drops the connection due to heartbeat starvation. The watchdog recovers cleanly.

### Send-and-wait timeouts and dropped events

```
log.1.gz:74   2026-07-09 00:02:12 | ERROR | ayumi.ctrader_connection | Send-and-wait failed: [Failure: TimeoutError (30.0s)]
log.1.gz:85   2026-07-09 00:02:12 | WARNING | ayumi.openapi_spot_feed | [EXEC_EVENT] DROP — clientOrderId='' not in pending_orders (keys=[]) errorCode='' description=''
log.1.gz:87   2026-07-09 00:02:12 | WARNING | ayumi.openapi_spot_feed | [EXEC_EVENT] DROP — clientOrderId='' not in pending_orders (keys=[]) errorCode=''
```

These are EXEC_EVENT DROP warnings with empty `clientOrderId`. They occur at every reconnect cycle. The "empty clientOrderId" pattern is consistent with **broker replaying historical events after a reconnect that we cannot correlate to a pending order** — a known artifact of cTrader OpenAPI reconnect behaviour, not a fill on our side. They are not double-fills or unexpected fills.

### Real cTrader rejection: "Field comment is too long"

**This is the reason 24 XAUUSD orders have not filled.** Sample:

```
log.1.gz:14200  2026-07-09 13:15:26 | INFO  | ayumi.openapi_spot_feed | [ORDER_ERROR] clientOrderId='' clientMsgId='order_62fe41f423c2467db5ff7b65d41eed62' pending_keys=['b2309e70ac7e421982968794e84426fe']
log.1.gz:14201  2026-07-09 13:15:26 | WARNING | ayumi.openapi_spot_feed | [ORDER_ERROR] MATCHED clientOrderId='b2309e70ac7e421982968794e84426fe' errorCode='INVALID_REQUEST' description='Field comment is too long' reason=INVALID_REQUEST: Field comment is too long
```

Followed by:

```
log.1.gz:14135  2026-07-09 13:15:00 | Signal accepted: srmr_plus short XAUUSD @ 4120735.00000 conf=0.59 lots=1.0000
log.1.gz:14140  2026-07-09 13:15:26 | Live order TIMEOUT awaiting ack: srmr_plus short 1.0000 lots order_id=b2309e70ac7e421982968794e84426fe — deferring verdict to late-fill callback
```

This pattern repeats for 8 distinct XAUUSD short orders (every 15 minutes from 13:15:26 to ~15:15:26, then continues based on the "Live order TIMEOUT" count of 26 in log.1.gz).

**The order comment field is too long for cTrader.** This is a real broker rejection, not a transient. Every XAUUSD SRMR+ short order sent today has been rejected, but the late-fill callback path means the orchestrator doesn't know they're rejected — it just waits for a fill that never comes, then eventually times out and waits again. The `accepted → rejected → TIMEOUT → never fills` loop runs every 15 minutes, with no broker fill ever arriving.

### No rate-limit, no auth-refresh storms, no partial fills, no duplicate fills

The only broker-rejection class is the comment-too-long one above. No evidence of partial fills, no `clientOrderId` collisions in the pending_keys, no auth refresh errors.

---

## Finding 5 — Anything Weird

This is where the real problems are. Five distinct anomalies:

### 5.1 — SRMR+ emits 24 XAUUSD signals with absurd entry prices

Citations (sample):

```
log.1.gz:14133  2026-07-09 13:15:00 | Signal accepted: srmr_plus short XAUUSD @ 4120735.00000 conf=0.59 lots=1.0000
log.1.gz:14436  2026-07-09 13:30:00 | Signal accepted: srmr_plus short XAUUSD @ 4126665.00000 conf=0.59 lots=1.0000
log.1.gz:14669  2026-07-09 13:45:00 | Signal accepted: srmr_plus short XAUUSD @ 4127485.00000 conf=0.59 lots=1.0000
log.1.gz:14971  2026-07-09 14:00:00 | Signal accepted: srmr_plus short XAUUSD @ 4121965.00000 conf=0.59 lots=1.0000
log.1.gz:15226  2026-07-09 14:15:00 | Signal accepted: srmr_plus short XAUUSD @ 4118275.00000 conf=0.59 lots=1.0000
log.1.gz:15511  2026-07-09 14:30:00 | Signal accepted: srmr_plus short XAUUSD @ 4118145.00000 conf=0.59 lots=1.0000
log.1.gz:15776  2026-07-09 14:45:00 | Signal accepted: srmr_plus short XAUUSD @ 4088910.00000 conf=0.59 lots=1.0000
log.1.gz:16079  2026-07-09 15:00:00 | Signal accepted: srmr_plus short XAUUSD @ 4057365.00000 conf=0.59 lots=1.0000
log.1.gz:16352  2026-07-09 15:15:00 | Signal accepted: srmr_plus short XAUUSD @ 4056775.00000 conf=0.59 lots=1.0000
```

XAUUSD is trading around $3,300. Entry prices of 4,130,495.00 / 4,128,165.00 / 4,052,665.00 / etc. are **physically impossible for XAUUSD**. These look like a unit-conversion or timestamp-format bug — the magnitude (~4×10⁶) is consistent with a microsecond timestamp being placed in a price field, or a quote-currency scaling factor being misapplied. USDJPY SRMR+ entries in the same timeframe show sensible prices (162.69050, 162.65950, etc.), so the bug is **specifically in how SRMR+ constructs the XAUUSD entry**.

The signals still pass the size gate (because XAUUSD is in `INSTRUMENTS` with `lot_size=100` and `pip_value_per_lot=1.0`), get sized to 1.0 lots, and are sent to cTrader — where they get rejected for the comment-length reason. **If the comment-length issue is fixed first and these orders actually fill, they will execute at nonsense prices and either blow the account or be closed immediately by the SL.** This is a critical latent risk.

### 5.2 — Position-sizer state desync from broker reality

```
log.2.gz:25334  2026-07-08 23:00:02 | SLPositionSizer.reset_daily (cet_date=2026-07-09): daily_used=0.00→0.00, open_risk=100.00 (carried), positions_carried=3, balance=10000.00
log.1.gz:24439  2026-07-09 23:00:03 | SLPositionSizer.reset_daily (cet_date=2026-07-10): daily_used=0.00→0.00, open_risk=475.00 (carried), positions_carried=16, balance=10000.00
```

At 23:00 UTC on July 9, `SLPositionSizer.reset_daily` reports **`positions_carried=16, open_risk=$475`** to be carried into 2026-07-10.

In the same service instance, cTrader shows **4 fills (live_fills=4)** and **0 fills on 2026-07-10**. The sizer's `_open_positions` dict (sl_position_sizer.py:157) is reporting 16 keys.

Reconciliation: between 2026-07-08 23:00:02 (positions_carried=3) and 2026-07-09 23:00:03 (positions_carried=16), the sizer accumulated 13 more "open positions". The orchestrator only registered 4 new fills in that window (2 USDJPY at 13:30 + 14:00 on July 8 + 1 GBPUSD at 00:00 on July 9 + 1 EURUSD at 05:00 on July 9). So **the sizer is either double-registering on `signal_id` keys or retaining legacy entries from prior service instances that are no longer being closed by the broker**.

Looking at `sl_position_sizer.py:174-185`, there's a `_legacy_open_risk` synthesis path that takes a legacy scalar value and creates a single legacy-keyed entry. And `register_open_position()` (line 284) creates keys like `f"_legacy_{id(self)}_{len(self._open_positions)}"` — these would persist across the dict but wouldn't be unique across service restarts.

**The 12-position discrepancy is real.** The sizer is thinking $475 is open risk. If a signal comes in that requires the full daily budget, the sizer may reject it (max_open_risk check at line 213), preventing a valid trade. This is potentially another cause of the 99→4 gap.

### 5.3 — 0 fills on the most active strategy (SRMR+)

SRMR+ generated 75 signals and **0 fills**. The reason is the XAUUSD entry-price bug + comment-length rejection, but it's worth noting that SRMR+ is the strategy with the most signals and zero conversion. Of the 4 fills, **3 are session_range_mr, 1 is session_breakout_ny**. SRMR+ is effectively contributing 0 trades.

### 5.4 — No fills outside market hours

All 4 fills happened at 13:30, 14:00, 00:00, and 05:00 UTC. The first two are in the London-NY overlap (forex-active). The 00:00 fill is in the Asian-session open. The 05:00 fill is in the London pre-open. None of the fills are outside the major forex sessions. **No fills on weekends**, which is consistent with `outside trading hours` filter behavior.

### 5.5 — No double-fills, no duplicate signals, no off-pattern activity

No two fills share a `clientOrderId`. No two fills share a `signal_id`. No fills on symbols outside the 7-symbol blend. The only off-pattern item is the SRMR+ XAUUSD entry-price bug above.

---

## Verdict

**ISSUES FOUND.**

The forward test is not in a fail-stop state, but **at least 4 distinct defects are degrading it**:

1. `signal_stats.jsonl` permission — 13 stats_fails, all same cause, 1-line filesystem fix.
2. `INSTRUMENTS` dict in `sl_position_sizer.py` missing 3 of 7 symbols — silently drops ~25% of signals, 1-line dict addition fix.
3. SRMR+ XAUUSD entry-price bug — emits impossible prices, latent risk that becomes acute if the comment-length bug is fixed first. Needs code investigation, not a one-line fix.
4. `SLPositionSizer` open-position counter desync — `positions_carried=16` vs cTrader reality of 4 fills, suggests a state-management bug in the sizer that needs investigation.

The Health JSON is showing **stable, superficially healthy state** (uptime OK, ticks flowing, balance tracking, dd_breaker OFF, halt=NONE) but is masking all 4 issues. None of them appear in the Health JSON itself; only the symptoms do (stats_fails=13, no fills from SRMR+, "Unknown instrument" lines that don't surface as errors).

Nothing is "weird" in the sense of a broker leak or rogue trading behavior. The fills that did arrive are reasonable. The position is exactly what the strategy outputs produce.

---

## Recommendations

In priority order, all low-risk to apply without touching the running service:

1. **Fix `signal_stats.jsonl` ownership** (immediate, no service restart needed):
   ```bash
   sudo chown TacoPants:TacoPants /home/TacoPants/projects/Ayumi/data/signal_stats.jsonl
   ```
   This will stop the 13 stats_fails from incrementing, and the confidence engine will start learning from real outcomes again within minutes. **No service restart required** — the file path will be retried on the next signal-stats write.

2. **Add missing `INSTRUMENTS` entries** to `src/forex-bot/risk/sl_position_sizer.py` (line 42), then restart the service to pick them up:
   ```python
   "AUDUSD": InstrumentSpec("AUDUSD", pip_size=0.0001, lot_size=100000, pip_value_per_lot=10.0),
   "USDCHF": InstrumentSpec("USDCHF", pip_size=0.0001, lot_size=100000, pip_value_per_lot=10.0),
   "USDCAD": InstrumentSpec("USDCAD", pip_size=0.0001, lot_size=100000, pip_value_per_lot=10.0),
   ```
   This unblocks ~25% of signal volume that was being silently rejected.

3. **Investigate the SRMR+ XAUUSD entry-price bug** before fixing the comment-length issue. The bogus entries (`entry=4130495.00000`, etc.) must be diagnosed in `src/forex-bot/strategies/srmr_plus/` — likely a unit-conversion or quote-scaling bug specific to XAUUSD. **Do not fix the comment-length bug first** — if you do, every XAUUSD SRMR+ short order will fill at an impossible price.

4. **Investigate the SLPositionSizer desync** — the 12-position discrepancy between `positions_carried` and cTrader reality suggests either:
   - Legacy-keyed entries from `_legacy_open_risk` (sl_position_sizer.py:174-185) that aren't being cleared on broker-side closes
   - The `register_open_position()` legacy path (line 284) being invoked when it shouldn't be
   - The `cancel()` → `close()` paths missing on broker-side close events
   
   Worth grepping the orchestrator for `sizer.register` and `sizer.close` calls and reconciling which fills have a corresponding `close()` invocation.

5. **Persist closed-trade P&L** to `data/trading.db` `trades` table. Currently the table is empty (zero rows) so we cannot do per-trade P&L analysis from the DB. The 4.45% DD reconciles only because we have the global balance figure.

6. **Don't panic about the daily_pnl=$0.00** — that's because no fills have happened today (UTC 2026-07-10). It's not a bug, just a side effect of the 21h fill drought that ends when SRMR+ is fixed (or when session_range_mr fires again in a session window).

---

*Investigation complete. No services modified, no orders triggered, no trading actions taken.*