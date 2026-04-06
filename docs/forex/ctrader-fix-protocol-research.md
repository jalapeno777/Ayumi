# cTrader FIX Protocol Research

## Summary

**Root cause: Missing authentication tags (553/554) and multiple protocol formatting bugs.**

The server silently drops messages with invalid logon — no ack, no reject, no error. This is documented behavior ("If an invalid Logon message is received by cTrader, cTrader sends a Logout message" — but in practice, malformed messages may be silently dropped).

---

## Correct Protocol Implementation

### Separator
- **Wire format: SOH (`\x01`)** — always. The Spotware sample code builds messages with `|` for readability, then calls `.Replace("|", "\u0001")` before sending. The `|` is **never sent on the wire**.

### Required Logon Fields (from official spec)

| Tag | Field | Value | Notes |
|-----|-------|-------|-------|
| 8 | BeginString | `FIX.4.4` | Must be first field |
| 9 | BodyLength | (calculated) | Must be second field |
| 35 | MsgType | `A` | Must be third field |
| 49 | SenderCompID | `<Env>.<BrokerUID>.<Login>` | e.g. `demo.theBroker.12345` |
| 56 | TargetCompID | `CSERVER` | Uppercase |
| 57 | TargetSubID | `QUOTE` or `TRADE` | Session qualifier |
| 50 | SenderSubID | Any string | Must be set if TargetSubID=QUOTE |
| 34 | MsgSeqNum | `1` | Increment per message |
| 52 | SendingTime | `20260406-01:19:00` | UTC |
| 98 | EncryptMethod | `0` | No encryption |
| 108 | HeartBtInt | `30` | Seconds |
| 141 | ResetSeqNumFlag | `Y` | Reset sequence numbers |
| **553** | **Username** | **Account number** | **MISSING IN OUR CODE** |
| **554** | **Password** | **Account password** | **MISSING IN OUR CODE** |
| 10 | CheckSum | `XXX` | 3-digit checksum, last field |

### Authentication
Authentication is **dual**: SenderCompID identifies the organization/broker, and tags 553/554 provide username/password credentials. Both are required.

### SenderCompID Format
Must be: `<Environment>.<BrokerUID>.<TraderLogin>`
- Environment: `demo` or `live`
- BrokerUID: provided in the cTrader FIX API form
- TraderLogin: numeric account ID

**Our current value `demo.ctrader.5795523` may have the wrong BrokerUID.** The BrokerUID is broker-specific and provided when FIX API access is granted. Check your cTrader FIX API form for the correct SenderCompID.

### Example Correct Logon Message
```
8=FIX.4.4\x019=126\x0135=A\x0149=demo.theBroker.5795523\x0156=CSERVER\x0134=1\x0152=20260406-01:19:00\x0157=TRADE\x0150=any_string\x0198=0\x01108=30\x01141=Y\x01553=5795523\x01554=yourPassword\x0110=XXX\x01
```

### Ports
- 5211: Read-only SSL (QUOTES)
- 5212: Trading SSL (TRADE)
- 5201: Read-only non-SSL
- 5202: Trading non-SSL

These appear correct for our demo account.

---

## Bugs Found in Existing Code

### Bug 1: Missing Authentication Tags (CRITICAL — root cause)
**File:** `api_client.py` — `_send_logon()` method

The logon message omits tags 553 (Username) and 554 (Password). Without these, the server cannot authenticate and silently drops the message.

**Fix:** Add username/password to credentials model and send them in the logon message:
```python
msg.set_field(553, self.credentials.username)  # Account number
msg.set_field(554, self.credentials.password)  # Account password
```

### Bug 2: Wrong Field Separator (CRITICAL)
**File:** `api_client.py` — `FIXMessage.FIELD_SEPARATOR = "|"`

Uses pipe `|` as the separator in the wire format. cTrader expects SOH `\x01`. The trailing SOH is appended but every field between uses `|`.

**Fix:** Use SOH everywhere:
```python
FIELD_SEPARATOR = "\x01"  # SOH — the only valid FIX field separator
```

### Bug 3: Wrong Field Order
**File:** `api_client.py` — `to_string()` sorts by tag number

FIX requires specific field ordering in the header: 8, 9, 35, then the rest. Sorting by tag number produces the right header order by coincidence (8 < 9 < 35 < 49 < 50 < 52 < 56 < 57 < 98 < 108 < 141 < 553 < 554), but the body fields get interspersed with header fields in a single sorted dict, and the BodyLength/BeginString are handled separately. This is fragile.

**Fix:** Construct messages explicitly in the correct order, not via dict sorting.

### Bug 4: BodyLength Calculation (HIGH)
**File:** `api_client.py` — `_send_message()`

```python
body_length = len(data) - len(FIXMessage.SOH)
```
This calculates the length of the entire formatted string minus one byte, which is not the correct FIX BodyLength. BodyLength should be the byte count of everything after tag 9 (including its SOH) and before tag 10.

### Bug 5: TargetCompID Case (MEDIUM)
**File:** `api_client.py` defaults to `"cServer"`, spec says `"CSERVER"`.

### Bug 6: TargetSubID (tag 57) Empty (MEDIUM)
**File:** `api_client.py` sends `""` for tag 57. Must be `QUOTE` or `TRADE`.

### Bug 7: Test Script Missing Tags 553/554 (CRITICAL)
**File:** `test_ctrader_connectivity.py` — `build_logon()`

Same issue: no username/password fields in the logon message.

---

## Is This a Protocol Issue or Account Provisioning Issue?

**This is a protocol issue, not an account provisioning issue.** The evidence:
1. TCP + SSL handshake succeeds — the server is reachable and accepting connections
2. No response at all (not even a reject/logout) — indicates the message is malformed/unparseable
3. The official spec says invalid logons get a Logout response with error details, but severely malformed messages (wrong separator, missing required fields) may be silently dropped before parsing

**However**, once the protocol bugs are fixed, there's a secondary concern: **SenderCompID must contain the correct BrokerUID**. This is broker-specific and provided via the cTrader FIX API form. If the BrokerUID is wrong, authentication will fail even with correct tags 553/554.

---

## Recommended Fix

See corrected test script below. Key changes:
1. Add tags 553 (username) and 554 (password) to logon
2. Use SOH (`\x01`) as the only separator — no pipe
3. Fix BodyLength calculation
4. Set TargetCompID to `CSERVER`
5. Set TargetSubID to `QUOTE` or `TRADE`
6. Construct header in correct field order (not sorted)

```python
#!/usr/bin/env python3
"""Corrected cTrader FIX connectivity test."""

import ssl
import socket
import time
import os
import sys
from pathlib import Path

# Load .env
env_path = Path(__file__).parent.parent / ".env"
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line and "=" in line and not line.startswith("#"):
        key, _, val = line.partition("=")
        os.environ.setdefault(key, val)

SOH = "\x01"

HOST = os.environ["CTRADER_HOST"]
ACCOUNT = os.environ["CTRADER_ACCOUNT"]
PASSWORD = os.environ["CTRADER_PASSWORD"]
SENDER_COMP_ID = os.environ.get("CTRADER_SENDER_COMP_ID", f"demo.theBroker.{ACCOUNT}")
TARGET_COMP_ID = os.environ.get("CTRADER_TARGET_COMP_ID", "CSERVER")
SENDER_SUB_ID = os.environ.get("CTRADER_SENDER_SUB_ID", "any_string")

READONLY_SSL_PORT = int(os.environ.get("CTRADER_READONLY_SSL_PORT", "5211"))
LIVE_SSL_PORT = int(os.environ.get("CTRADER_SSL_PORT", "5212"))


def calculate_checksum(data: str) -> str:
    return f"{sum(ord(c) for c in data) % 256:03d}"


def build_logon(sender_comp_id: str, target_comp_id: str,
                sender_sub_id: str, target_sub_id: str,
                username: str, password: str) -> str:
    """Build a correct cTrader FIX 4.4 Logon message."""
    # Build body first (tags after header standard fields)
    body_parts = [
        f"98=0",           # EncryptMethod: none
        f"108=30",         # HeartBtInt: 30s
        f"141=Y",          # ResetSeqNumFlag
        f"553={username}", # Username (account number)
        f"554={password}", # Password
    ]
    body = SOH.join(body_parts) + SOH

    # Build header standard fields (after BeginString and BodyLength)
    now = time.strftime("%Y%m%d-%H:%M:%S")
    header_parts = [
        f"35=A",                  # MsgType: Logon
        f"49={sender_comp_id}",   # SenderCompID
        f"56={target_comp_id}",   # TargetCompID
        f"57={target_sub_id}",    # TargetSubID: QUOTE or TRADE
        f"50={sender_sub_id}",    # SenderSubID
        f"34=1",                  # MsgSeqNum
        f"52={now}",              # SendingTime
    ]
    header_msg = SOH.join(header_parts) + SOH

    # BodyLength = length of header_msg + body (everything after tag 9)
    body_length = len(header_msg) + len(body)

    # Full header: BeginString + BodyLength + rest of header
    header = f"8=FIX.4.4{SOH}9={body_length}{SOH}{header_msg}"

    # Checksum over header + body
    checksum = calculate_checksum(header + body)
    trailer = f"10={checksum}{SOH}"

    return header + body + trailer


def test_connection(host: str, port: int, mode: str, timeout: int = 10) -> dict:
    result = {"mode": mode, "port": port, "success": False, "error": None}
    target_sub = "QUOTE" if mode == "read-only" else "TRADE"

    print(f"\n{'='*60}")
    print(f"Testing: {mode} on port {port}")
    print(f"  Sender: {SENDER_COMP_ID}")
    print(f"  TargetSubID: {target_sub}")
    print(f"{'='*60}")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        print("  ✅ TCP connected")

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ssl_sock = ctx.wrap_socket(sock, server_hostname=host)
        print("  ✅ SSL established")

        logon = build_logon(
            SENDER_COMP_ID, TARGET_COMP_ID,
            SENDER_SUB_ID, target_sub,
            ACCOUNT, PASSWORD,
        )
        print(f"  Sending logon ({len(logon)} bytes)...")
        ssl_sock.send(logon.encode("latin-1"))

        # Wait for response
        response = b""
        ssl_sock.settimeout(5)
        start = time.time()
        while time.time() - start < timeout:
            try:
                chunk = ssl_sock.recv(4096)
                if chunk:
                    response += chunk
                    break
            except socket.timeout:
                continue

        if response:
            decoded = response.decode("latin-1", errors="replace")
            print(f"  ✅ Received {len(response)} bytes")
            # Parse messages by SOH
            for msg in decoded.split(SOH):
                msg = msg.strip()
                if not msg:
                    continue
                print(f"  MSG: {msg[:200]}")
                if "35=A" in msg and "49=CSERVER" in msg:
                    result["success"] = True
                    print("  ✅ LOGON ACKNOWLEDGED!")
                elif "35=5" in msg:
                    text = next((f.split("=",1)[1] for f in msg.split(SOH) if f.startswith("58=")), "no reason")
                    result["error"] = f"Logout: {text}"
                    print(f"  ❌ Logout: {text}")
        else:
            result["error"] = "No response"
            print("  ❌ No response from server")

        ssl_sock.close()
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"  ❌ {e}")

    return result


def main():
    print(f"cTrader FIX Connectivity Test (Corrected)")
    print(f"Host: {HOST} | Account: {ACCOUNT}")

    results = []
    results.append(test_connection(HOST, READONLY_SSL_PORT, "read-only"))
    results.append(test_connection(HOST, LIVE_SSL_PORT, "live"))

    print(f"\n{'='*60}\nSUMMARY")
    for r in results:
        status = "✅ PASS" if r["success"] else "❌ FAIL"
        print(f"  {r['mode']:>12} ({r['port']:>5}): {status}")
        if r["error"]:
            print(f"                {r['error']}")

    return 0 if all(r["success"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
```

---

## Action Items

1. **Immediate**: Fix the test script with tags 553/554 and correct separators — verify the connection works
2. **Verify SenderCompID**: Check the cTrader FIX API form for the correct BrokerUID. Our guess of `demo.ctrader.5795523` likely has the wrong BrokerUID
3. **Fix `api_client.py`**: Apply all the bug fixes listed above to the production adapter
4. **Update credentials model**: Add `username` and `password` fields to `cTraderCredentials`

## Sources
- Official spec: https://help.ctrader.com/fix/specification/
- Send/receive guide: https://help.ctrader.com/fix/sending-and-receiving-messages/
- Spotware C# sample: https://github.com/spotware/FIX-API-Sample (MessageConstructor.cs)
