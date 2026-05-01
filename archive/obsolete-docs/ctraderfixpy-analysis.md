# cTraderFixPy Analysis — Spotware's Official Python FIX Library

## Source
https://github.com/spotware/cTraderFixPy (MIT license)

## Architecture
- Uses Twisted (async) with `ClientService` for reconnection
- 4 source files: `messages.py`, `fixProtocol.py`, `client.py`, `factory.py`
- Delimiter default: SOH (`\x01`) — passed through `Client.__init__`

---

## CRITICAL FINDING: TargetCompID = "cServer" (mixed case)

The README config sample shows:
```json
"TargetCompID": "cServer"
```

**Our research doc says "CSERVER" (uppercase). Our v2 script also uses "CSERVER".** This is Spotware's own Python library using mixed-case `"cServer"`. This is almost certainly the cause of "Can't route request" — the server can't match "CSERVER" to any registered session.

## Other Key Differences from Our v2 Script

### 1. BodyLength Calculation
The official library's approach:
```python
# In _getHeader:
fieldsJoined = delimiter.join(fields)  # NO trailing delimiter
# BodyLength = len(body) + len(fieldsJoined) + 2
# +2 accounts for the 2 delimiters added in getMessage():
#   f"{header}{delimiter}{body}{delimiter}"
```

Our v2 approach:
```python
message_str = f"35=A{SOH}49=...{SOH}...{body_str}"
body_length = len(message_str.encode("ascii"))
```

**Both are equivalent** — our v2 is correct.

### 2. Field Order
Official: `35, 49, 56, 57, 50, 34, 52` — exact same as our v2. ✓

### 3. Logon Body Fields
Official: `98, 108, 141(optional), 553, 554` — exact same as our v2. ✓

### 4. ResetSeqNumFlag (141)
Official: Only sends `141=Y` if `ResetSeqNum` attribute is explicitly set. Our v2 always sends it. This is unlikely to cause issues.

### 5. SenderSubID (tag 50)
Official README config: `"SenderSubID": "QUOTE"` — but it's configurable, just a placeholder. Our v2 uses the account number. The spec says "any string" for QUOTE sessions.

### 6. SenderCompID Format
Official README: empty string (user must fill in). No specific format enforced. Our `demo.c-trader.{ACCOUNT}` should be fine IF the broker UID is correct.

---

## Wire Format Comparison

### Official library produces (example):
```
8=FIX.4.4\x019=XXX\x0135=A\x0149=demo.c-trader.5795523\x0156=cServer\x0157=TRADE\x0150=QUOTE\x0134=1\x0152=20260406-01:30:00\x0198=0\x01108=30\x01553=5795523\x01554=xxx\x0110=XXX\x01
```

### Our v2 produces:
```
8=FIX.4.4\x019=XXX\x0135=A\x0149=demo.c-trader.5795523\x0156=CSERVER\x0157=TRADE\x0150=5795523\x0134=1\x0152=20260406-01:30:00\x0198=0\x01108=30\x01141=Y\x01553=5795523\x01554=xxx\x0110=XXX\x01
```

### Differences:
| Field | Official | Our v2 | Impact |
|-------|----------|--------|--------|
| 56 (TargetCompID) | `cServer` | `CSERVER` | **HIGH — likely cause of routing failure** |
| 50 (SenderSubID) | `QUOTE` | `5795523` | LOW — spec says any string |
| 141 (ResetSeqNum) | omitted unless set | `Y` always | LOW |

---

## Live Test Results

Tested with `TargetCompID="cServer"` (matching official library) — still got "Can't route request".

The server DID parse the FIX message correctly and returned a proper Logout (35=5). This means:
- ✅ SOH separator is correct
- ✅ BodyLength calculation is correct
- ✅ Checksum is correct
- ✅ Field ordering is correct
- ✅ Tags 553/554 are present

### Actual Root Cause: Wrong SenderCompID (BrokerUID)

"Can't route request" means the server received a valid FIX message but **cannot find a registered session** matching the SenderCompID. The SenderCompID `demo.c-trader.5795523` contains `c-trader` as the BrokerUID — this is a **placeholder** from the Spotware documentation.

The correct BrokerUID is broker-specific and provided when FIX API access is granted. Without the correct one, the server cannot route the message to any broker session.

### Interesting: Server Swapped SubIDs
In the response, the server swapped TargetSubID/SenderSubID:
- We sent: `57=TRADE`, `50=QUOTE`
- Server responded: `57=QUOTE`, `50=TRADE`

This suggests the server has a session registered on port 5212 with TargetSubID=QUOTE, not TRADE. Or it could be that the QUOTE session is the one configured for this account.

### Recommended Fix
1. **Get the correct BrokerUID** from the cTrader FIX API access form
2. Update SenderCompID to `demo.<correct-uid>.5795523`
3. Also change TargetCompID to `cServer` (matching official library, though both `cServer` and `CSERVER` produce the same error)

### Message Construction
Our v2 script's FIX message construction is **correct and equivalent** to the official library. The only difference that matters is the BrokerUID in SenderCompID.
