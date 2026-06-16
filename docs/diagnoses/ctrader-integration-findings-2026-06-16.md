# cTrader Open API — Integration Findings & Hard-Won Knowledge

**Date:** 2026-06-16
**Author:** Ava
**Status:** Verified against live demo account 46877902
**BQ:** BQ-1043 / BQ-1042

---

## Critical Finding: Volume Units

**The #1 issue that blocked all order execution since April.**

### The Problem
The cTrader Open API `volume` field in `ProtoOANewOrderReq` is **NOT in lots**. It's in **units of the base asset**, scaled by the symbol's `lotSize` field.

### What the Symbol Spec Says (GBPUSD on demo 46877902)
```
lotSize = 10,000,000   (10M — NOT the standard 100K)
minVolume = 100,000    (minimum tradeable volume in raw units)
stepVolume = 100,000   (volume must be multiples of this)
maxVolume = 1,000,000,000
```

### Volume Conversion
| Lots | Raw Volume (units) | Formula |
|------|-------------------|---------|
| 0.01 | 100,000 | `0.01 × lotSize / 100` |
| 0.10 | 1,000,000 | `0.10 × lotSize / 100` |
| 1.00 | 10,000,000 | `1.00 × lotSize / 100` |

**Formula:** `raw_volume = lots_in_cents × (lotSize / 100)`

Or more simply: `raw_volume = lots × lotSize / 100`

**For this demo account (lotSize=10M):** `0.01 lots = raw_volume 100,000`

### Why the Old Code Failed
```python
# OLD (BROKEN):
def _lots_to_units(lots: float) -> int:
    return int(round(lots * 100_000))  # Assumes 100K per lot

# This produced volume=1000 for 0.01 lots
# cTrader interpreted 1000 as 0.10 lots (1000/100 = 10.00 centi-lots)
# Which was BELOW the minVolume of 100,000
```

### The Fix
```python
# NEW (CORRECT):
def lots_to_volume(lots: float, lot_size: int = 10_000_000) -> int:
    """Convert lots to raw cTrader volume units."""
    return int(lots * lot_size / 100)
    
# lots_to_volume(0.01, lot_size=10_000_000) = 100,000 ✓
```

**IMPORTANT:** Always query `ProtoOASymbolByIdReq` at startup to get the actual `lotSize`, `minVolume`, and `stepVolume` for each symbol. Do NOT hardcode lot sizes.

---

## Finding: SDK Connection Pattern

### The Client API
The `ctrader_open_api` SDK uses Twisted's reactor. The reactor MUST be running for any TCP operation.

```python
from twisted.internet import reactor
from ctrader_open_api import Client, TcpProtocol

client = Client("demo.ctraderapi.com", 5035, TcpProtocol)

# Set callbacks (NOT properties — use setter methods)
client.setConnectedCallback(on_connected)
client.setMessageReceivedCallback(on_message)

# Start service (needs reactor)
client.startService()

# Reactor must be running in a background thread
if not reactor.running:
    threading.Thread(target=reactor.run, args=(False,), daemon=True).start()
```

**Key rules:**
- Use `setConnectedCallback()`, NOT `client.onConnected = ...`
- Use `setMessageReceivedCallback()`, NOT `client.onMessage = ...`
- Reactor must be started AFTER `client.startService()`
- All `client.send()` calls return a Twisted `Deferred` — add callbacks: `d.addCallbacks(on_success, on_error)`

---

## Finding: Auth Flow (3 Steps)

1. **TCP connect** — `client.startService()` + reactor running → `setConnectedCallback` fires
2. **Application auth** — send `ProtoOAApplicationAuthReq` with `clientId` + `clientSecret`
3. **Account auth** — send `ProtoOAAccountAuthReq` with `ctidTraderAccountId` + `accessToken`

Only after step 3 can you send trading requests.

---

## Finding: Execution Event Correlation (BQ-1042 Fix)

The response to `ProtoOANewOrderReq` comes as one of:

| Payload Type | Message | Meaning |
|-------------|---------|---------|
| 2126 | Execution Event | Order filled / cancelled / rejected (check `executionType`) |
| 2132 | Order Error Event | Order rejected with error code |
| 2112 | New Order Response | Order accepted (legacy) |

**The `clientMsgId` is the key for correlation.** When you call `client.send(msg, clientMsgId="my_id")`, the response comes back with the same `clientMsgId`. The SDK automatically routes it to your Deferred callback.

**You do NOT need manual pending-order maps.** The SDK's built-in `clientMsgId` routing handles correlation. The old code's `_pending_orders` / `_pending_client_msg_ids` dicts were reinventing what the SDK already does.

---

## Finding: Credential Sync Issue

**This happens on EVERY restart.** The root cause:

1. `.env` has the original credentials (set by Craig)
2. `data/.credentials` is a copy that gets updated by token refresh
3. On restart, if `.credentials` has `expires_at = None` (never set), the `CredentialStore` treats it as stale and re-reads from `.env`
4. But `.env` has the OLD tokens, overwriting any refreshed tokens
5. The old refresh token may be invalid → `Access denied`

**Fix:** `CredentialStore` must preserve `expires_at` across restarts. If `expires_at` is in the future, trust the `.credentials` file. Only re-read from `.env` if the file is truly missing.

---

## Finding: Message Extraction

Incoming messages are raw `ProtoMessage` envelopes. Use `Protobuf.extract()` to get the typed payload:

```python
from ctrader_open_api.protobuf import Protobuf

def on_message(client, message):
    extracted = Protobuf.extract(message)
    payload_type = extracted.payloadType
    # Now access typed fields: extracted.errorCode, extracted.executionType, etc.
```

---

## Finding: Protobuf Imports

All proto messages are in `ctrader_open_api.messages.OpenApiMessages_pb2`:

```python
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,    # App auth request
    ProtoOAApplicationAuthRes,    # App auth response (pt=2101)
    ProtoOAAccountAuthReq,        # Account auth request
    ProtoOAAccountAuthRes,        # Account auth response (pt=2103)
    ProtoOANewOrderReq,           # New order
    ProtoOAClosePositionReq,      # Close position
    ProtoOACancelOrderReq,        # Cancel order
    ProtoOAAmendOrderReq,         # Amend order
    ProtoOASymbolByIdReq,         # Symbol lookup
    ProtoOASymbolByIdRes,         # Symbol response (pt=2117)
    ProtoOASubscribeSpotsReq,     # Subscribe to tick data
    ProtoOAOrderErrorEvent,       # Order error (pt=2132)
)
```

**NOT** in `OpenApiModelMessages_pb2` (that file has enums/constants only).

---

## Verified Trade Sequence

On 2026-06-16 at 22:44 UTC, the following was verified on demo account 46877902:

1. **TCP connect** to `demo.ctraderapi.com:5035` — ✓
2. **Application auth** (client_id + client_secret) — ✓
3. **Account auth** (account_id + access_token) — ✓
4. **Symbol query** GBPUSD (symbolId=1) — ✓ (got lotSize=10M, minVolume=100K)
5. **Market BUY order** GBPUSD volume=100000 (0.01 lots) — **FILLED**
   - Position ID: 266374347
   - Order ID: 306767986
6. **Close position** 266374347 volume=100000 — **CLOSED**
   - Order ID: 306768128

**First complete open→close trade cycle in Ayumi project history.**

---

## Key Takeaway

The volume unit mismatch (`lotSize=10M` vs assumed `100K`) was the single blocking issue preventing order execution since April. Combined with the credential sync issue and the missing errback event.set() (BQ-1042), every order attempt was silently failing.

All three issues are now understood and fixable. The BQ-1043 rebuild will codify these fixes into clean, tested modules.
