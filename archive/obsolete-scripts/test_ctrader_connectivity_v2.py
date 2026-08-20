#!/usr/bin/env python3
"""
cTrader FIX API Connectivity Test v2
=====================================
Based on the official Spotware C# sample: https://github.com/spotware/FIX-API-Sample

Key protocol details extracted from the reference implementation:
- FIX version: 4.4
- Field separator: SOH (0x01)
- TargetCompID: "CSERVER" (uppercase, per official sample)
- Logon MUST include: Username (553) and Password (554)
- SenderSubID (50): account number
- TargetSubID (57): "QUOTE" for read-only (port 5211), "TRADE" for live (port 5212)
- BodyLength: bytes from after tag-9 SOH to before tag-10 (checksum itself excluded)
- Checksum: sum of all bytes before tag-10, mod 256, zero-padded to 3 digits
"""

import os  # noqa: I001
import ssl
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env (non-destructive — won't override already-set env vars)
# ---------------------------------------------------------------------------
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            os.environ.setdefault(key, val.strip('"').strip("'"))

# ---------------------------------------------------------------------------
# Credentials — override to match FIX API form values
# ---------------------------------------------------------------------------
HOST = os.environ.get("CTRADER_FIX_HOST", "demo-uk-eqpx-01.p.c-trader.com")
ACCOUNT = os.environ.get("CTRADER_ACCOUNT", "5795519")
PASSWORD = os.environ.get("CTRADER_PASSWORD", "D92ooLbNvZ$2%%rF")

# SenderCompID format: <environment>.c-trader.<account_id>
# Per Spotware sample: <BrokerUID>.<TraderLogin> where BrokerUID is from cTrader
SENDER_COMP_ID = os.environ.get("CTRADER_FIX_SENDER_COMP_ID", f"demo.c-trader.{ACCOUNT}")
# Official C# sample uses "CSERVER" (uppercase)
TARGET_COMP_ID = os.environ.get("CTRADER_FIX_TARGET_COMP_ID", "CSERVER")

READONLY_PORT = int(os.environ.get("CTRADER_READONLY_SSL_PORT", "5211"))
LIVE_PORT = int(os.environ.get("CTRADER_SSL_PORT", "5212"))

SOH = "\x01"


# ---------------------------------------------------------------------------
# FIX message construction — mirrors Spotware's MessageConstructor.cs
# ---------------------------------------------------------------------------


def calculate_checksum(data: str) -> str:
    """Calculate FIX checksum over a string (with SOH separators)."""
    return f"{sum(data.encode('ascii')) % 256:03d}"


def build_fix_message(
    msg_type: str,
    sender_comp_id: str,
    target_comp_id: str,
    sender_sub_id: str,
    target_sub_id: str,
    seq_num: int,
    body_fields: dict | None = None,
) -> str:
    """
    Build a well-formed FIX 4.4 message.

    Structure (all separators are SOH):
        8=FIX.4.4 | 9=<BodyLength> | 35=<MsgType> | 49=<SenderCompID> |
        56=<TargetCompID> | 57=<TargetSubID> | 50=<SenderSubID> |
        34=<SeqNum> | 52=<SendingTime> | <body fields...> | 10=<Checksum>

    BodyLength = byte count from after tag-9 SOH to before tag-10.
    """
    sending_time = datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S")

    # Build body fields string (each field terminated by SOH)
    body_parts = []
    if body_fields:
        for tag, value in body_fields.items():
            body_parts.append(f"{int(tag)}={value}{SOH}")
    body_str = "".join(body_parts)

    # Build the "message" portion (everything after tag-9's SOH)
    # Order follows Spotware sample: 35, 49, 56, 57, 50, 34, 52, then body
    message_str = (
        f"35={msg_type}{SOH}"
        f"49={sender_comp_id}{SOH}"
        f"56={target_comp_id}{SOH}"
        f"57={target_sub_id}{SOH}"
        f"50={sender_sub_id}{SOH}"
        f"34={seq_num}{SOH}"
        f"52={sending_time}{SOH}"
        f"{body_str}"
    )

    # BodyLength = length of message_str in bytes
    body_length = len(message_str.encode("ascii"))

    # Build header
    header_str = f"8=FIX.4.4{SOH}9={body_length}{SOH}"

    # Full message without checksum (everything 10= will be calculated over)
    msg_without_checksum = header_str + message_str

    # Calculate checksum
    checksum = calculate_checksum(msg_without_checksum)

    # Complete message
    return f"{msg_without_checksum}10={checksum}{SOH}"


def build_logon(
    sender_comp_id: str,
    sender_sub_id: str,
    target_comp_id: str,
    target_sub_id: str,
    username: str,
    password: str,
    seq_num: int = 1,
    heartbeat_seconds: int = 30,
    reset_seq_num: bool = True,
) -> str:
    """Build a FIX Logon (35=A) message with credentials.

    Mirrors Spotware's MessageConstructor.LogonMessage exactly.
    """
    body_fields = {
        98: "0",  # EncryptMethod = NONE_OTHER
        108: str(heartbeat_seconds),
    }
    if reset_seq_num:
        body_fields[141] = "Y"
    body_fields[553] = username  # Username — CRITICAL, was missing in v1
    body_fields[554] = password  # Password — CRITICAL, was missing in v1

    return build_fix_message(
        msg_type="A",
        sender_comp_id=sender_comp_id,
        target_comp_id=target_comp_id,
        sender_sub_id=sender_sub_id,
        target_sub_id=target_sub_id,
        seq_num=seq_num,
        body_fields=body_fields,
    )


def build_logout(
    sender_comp_id: str,
    sender_sub_id: str,
    target_comp_id: str,
    target_sub_id: str,
    seq_num: int,
) -> str:
    """Build a FIX Logout (35=5) message."""
    return build_fix_message(
        msg_type="5",
        sender_comp_id=sender_comp_id,
        target_comp_id=target_comp_id,
        sender_sub_id=sender_sub_id,
        target_sub_id=target_sub_id,
        seq_num=seq_num,
    )


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------


def parse_fix_messages(data: str) -> list[str]:
    """Split raw FIX data into individual messages (SOH-delimited)."""
    messages = []
    current = []
    for char in data:
        if char == SOH:
            current.append(char)
            messages.append("".join(current))
            current = []
        else:
            current.append(char)
    # Handle any trailing content
    if current:
        messages.append("".join(current))
    return [m for m in messages if m.strip()]


def format_fix_for_display(msg: str) -> str:
    """Replace SOH with | for human-readable output."""
    return msg.replace(SOH, "|")


def test_connection(
    host: str,
    port: int,
    mode: str,  # "QUOTE" or "TRADE"
    timeout: int = 10,
) -> dict:
    """Connect, send logon, read response. Returns result dict."""
    result = {
        "mode": mode,
        "host": host,
        "port": port,
        "success": False,
        "error": None,
        "response_raw": None,
    }

    sender_sub_id = ACCOUNT  # Per Spotware sample: SenderSubID = trader login
    target_sub_id = mode  # QUOTE or TRADE

    print(f"\n{'=' * 64}")
    print(f"  Testing: {mode} connection")
    print(f"  Host:      {host}")
    print(f"  Port:      {port}")
    print(f"  SenderID:  {SENDER_COMP_ID}")
    print(f"  TargetID:  {TARGET_COMP_ID}")
    print(f"  SenderSub: {sender_sub_id}")
    print(f"  TargetSub: {target_sub_id}")
    print(f"  Account:   {ACCOUNT}")
    print(f"{'=' * 64}")

    try:
        # DNS resolution
        try:
            ip = socket.gethostbyname(host)
            print(f"  DNS: {host} -> {ip}")
        except socket.gaierror as e:
            result["error"] = f"DNS resolution failed: {e}"
            print(f"  ❌ DNS failed: {e}")
            return result

        # TCP + SSL
        print("  Connecting TCP+SSL...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ssl_sock = ctx.wrap_socket(sock, server_hostname=host)
        print("  ✅ Connected (SSL)")

        # Build and send logon
        logon_msg = build_logon(
            sender_comp_id=SENDER_COMP_ID,
            sender_sub_id=sender_sub_id,
            target_comp_id=TARGET_COMP_ID,
            target_sub_id=target_sub_id,
            username=ACCOUNT,
            password=PASSWORD,
            seq_num=1,
            heartbeat_seconds=30,
            reset_seq_num=True,
        )

        print(f"\n  >> SENDING LOGON ({len(logon_msg.encode('ascii'))} bytes):")
        print(f"     {format_fix_for_display(logon_msg)}")

        ssl_sock.send(logon_msg.encode("ascii"))

        # Read response
        print(f"\n  Waiting for response (up to {timeout}s)...")
        response = b""
        ssl_sock.settimeout(3)
        start = time.time()
        while time.time() - start < timeout:
            try:
                chunk = ssl_sock.recv(4096)
                if chunk:
                    response += chunk
                    # Keep reading briefly for more data
                    ssl_sock.settimeout(1)
                else:
                    break
            except socket.timeout:
                if response:
                    break
                continue
            except ssl.SSLError:
                break

        if response:
            decoded = response.decode("ascii", errors="replace")
            result["response_raw"] = decoded
            print(f"  ✅ Received {len(response)} bytes:")
            print("\n  << RAW RESPONSE:")
            for line in format_fix_for_display(decoded).split("|"):
                line = line.strip()
                if line:
                    print(f"     {line}")

            # Parse for status
            if "35=A" in decoded:
                result["success"] = True
                print("\n  ✅✅✅ LOGON ACKNOWLEDGED — Authentication successful!")
            elif "35=5" in decoded:
                result["error"] = "Server sent Logout"
                print("\n  ❌ Server sent Logout (35=5)")
            elif "35=3" in decoded:
                for field in decoded.split(SOH):
                    if field.startswith("58="):
                        result["error"] = f"Rejected: {field[3:]}"
                print(f"\n  ❌ Rejected: {result['error']}")
            elif "35=0" in decoded:
                print("\n  ℹ️  Heartbeat received (server alive but no logon ack)")
                result["error"] = "Only heartbeat received, no logon ack"
        else:
            result["error"] = "No response received"
            print("  ❌ No response from server")

        # Send logout
        try:
            logout_msg = build_logout(SENDER_COMP_ID, sender_sub_id, TARGET_COMP_ID, target_sub_id, seq_num=2)
            print("\n  >> SENDING LOGOUT:")
            print(f"     {format_fix_for_display(logout_msg)}")
            ssl_sock.send(logout_msg.encode("ascii"))
            time.sleep(0.5)
        except Exception:  # noqa: S110
            pass

        ssl_sock.close()

    except ConnectionRefusedError:
        result["error"] = "Connection refused (port closed/firewall)"
        print("  ❌ Connection refused")
    except socket.timeout:
        result["error"] = f"Timeout after {timeout}s"
        print("  ❌ Timeout")
    except ssl.SSLError as e:
        result["error"] = f"SSL error: {e}"
        print(f"  ❌ SSL error: {e}")
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"  ❌ {type(e).__name__}: {e}")

    return result


def main():
    print("=" * 64)
    print("  cTrader FIX API Connectivity Test v2")
    print("  Based on Spotware official C# sample")
    print("=" * 64)
    print(f"  Host:         {HOST}")
    print(f"  Account:      {ACCOUNT}")
    print(f"  SenderCompID: {SENDER_COMP_ID}")
    print(f"  TargetCompID: {TARGET_COMP_ID}")

    results = []

    # Test read-only (QUOTE) connection on port 5211
    results.append(test_connection(HOST, READONLY_PORT, "QUOTE"))

    # Test live (TRADE) connection on port 5212
    results.append(test_connection(HOST, LIVE_PORT, "TRADE"))

    # Summary
    print(f"\n{'=' * 64}")
    print("  SUMMARY")
    print(f"{'=' * 64}")
    for r in results:
        status = "✅ PASS" if r["success"] else "❌ FAIL"
        print(f"  {r['mode']:>6} ({r['port']:>5}): {status}")
        if r["error"]:
            print(f"         Error: {r['error']}")

    all_pass = all(r["success"] for r in results)
    print(f"\n  Overall: {'✅ ALL PASSED' if all_pass else '❌ SOME FAILED'}")

    # Key differences from v1 for debugging
    print(f"\n{'=' * 64}")
    print("  CHANGES FROM v1 (why this should work):")
    print("  1. Added Username (553) and Password (554) to logon")
    print("  2. Added SenderSubID (50) = account number")
    print("  3. Added TargetSubID (57) = QUOTE/TRADE")
    print("  4. TargetCompID = 'CSERVER' (uppercase, per Spotware)")
    print("  5. Correct host with '.p.' subdomain")
    print("  6. SenderCompID = 'demo.c-trader.<account>' (with hyphen)")
    print("  7. BodyLength = bytes from after tag-9 SOH to before tag-10")
    print(f"{'=' * 64}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
