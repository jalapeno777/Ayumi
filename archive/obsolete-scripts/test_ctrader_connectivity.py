#!/usr/bin/env python3
"""Direct cTrader FIX connectivity test — read-only (5211) and live (5212)."""

import os
import socket
import ssl
import sys
import time
from pathlib import Path

# Load .env
env_path = Path(__file__).parent.parent / ".env"
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line and "=" in line and not line.startswith("#"):
        key, _, val = line.partition("=")
        os.environ.setdefault(key, val)

HOST = os.environ["CTRADER_HOST"]
ACCOUNT = os.environ["CTRADER_ACCOUNT"]
PASSWORD = os.environ["CTRADER_PASSWORD"]
SENDER_COMP_ID = os.environ.get("CTRADER_SENDER_COMP_ID", f"demo.ctrader.{ACCOUNT}")
TARGET_COMP_ID = os.environ.get("CTRADER_TARGET_COMP_ID", "cServer")
SENDER_SUB_ID = os.environ.get("CTRADER_SENDER_SUB_ID", "TRADE")

READONLY_SSL_PORT = int(os.environ.get("CTRADER_READONLY_SSL_PORT", "5211"))
LIVE_SSL_PORT = int(os.environ.get("CTRADER_SSL_PORT", "5212"))

SOH = "\x01"


def build_fix_string(fields: dict, use_soh: bool = True) -> str:
    """Build a FIX message string. Tag 8 (BeginString) and 9 (BodyLength) are auto-set.
    If use_soh=False, uses pipe separators (matching existing adapter behavior)."""
    sep = SOH if use_soh else "|"
    term = SOH  # trailing terminator is always SOH
    # Body = all fields except 8, 9, 10
    body = sep.join(f"{tag}={val}" for tag, val in sorted(fields.items()) if tag not in (8, 9, 10)) + term
    body_str = f"8=FIX.4.4{sep}9={len(body)}{sep}{body}"
    # Checksum over everything before it
    checksum = sum(ord(c) for c in body_str) % 256
    return body_str + f"10={checksum:03d}{term}"


def build_logon(
    sender_comp_id: str,
    sender_sub_id: str = "",
    target_comp_id: str = TARGET_COMP_ID,
    use_soh: bool = True,
) -> str:
    fields = {
        35: "A",  # Logon
        49: sender_comp_id,
        56: target_comp_id,
        34: "1",  # SeqNum
        52: time.strftime("%Y%m%d-%H:%M:%S"),
        98: "0",  # EncryptMethod = None
        108: "30",  # Heartbeat interval
        141: "Y",  # ResetSeqNumFlag
    }
    return build_fix_string(fields, use_soh=use_soh)


def test_connection(host: str, port: int, mode: str, timeout: int = 10, use_soh: bool = True) -> dict:
    """Try to connect, send logon, and read the response."""
    result = {
        "mode": mode,
        "host": host,
        "port": port,
        "success": False,
        "error": None,
        "response": None,
    }

    # Use SENDER_SUB_ID=QUOTE for read-only, TRADE for live
    sub_id = "QUOTE" if mode == "read-only" else SENDER_SUB_ID
    sender_id = SENDER_COMP_ID
    sep_label = "SOH" if use_soh else "pipe"

    print(f"\n{'=' * 60}")
    print(f"Testing: {mode.upper()} connection (separator: {sep_label})")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Sender: {sender_id}")
    print(f"  Sub: {sub_id}")
    print(f"{'=' * 60}")

    try:
        # DNS resolution
        try:
            ip = socket.gethostbyname(host)
            print(f"  DNS resolved: {host} -> {ip}")
        except socket.gaierror as e:
            result["error"] = f"DNS resolution failed: {e}"
            print(f"  ❌ DNS failed: {e}")
            return result

        # TCP connect
        print("  Connecting TCP...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        print("  ✅ TCP connected")

        # SSL handshake
        print("  SSL handshake...")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False  # demo cert
        ctx.verify_mode = ssl.CERT_NONE
        ssl_sock = ctx.wrap_socket(sock, server_hostname=host)
        print("  ✅ SSL established")

        # Build and send logon
        logon_msg = build_logon(sender_id, sub_id, use_soh=use_soh)
        print("  Sending logon...")
        ssl_sock.send(logon_msg.encode("latin-1"))
        print(f"  ✅ Logon sent ({len(logon_msg)} bytes)")

        # Read response — loop for up to timeout seconds
        print(f"  Waiting for response (up to {timeout}s)...")
        response = b""
        ssl_sock.settimeout(3)  # shorter per-read timeout
        start = time.time()
        while time.time() - start < timeout:
            try:
                chunk = ssl_sock.recv(4096)
                if chunk:
                    response += chunk
                    break  # got something, process it
            except socket.timeout:
                continue
            except ssl.SSLError:
                break
        if response:
            decoded = response.decode("latin-1", errors="replace")
            result["response"] = decoded
            print(f"  ✅ Received {len(response)} bytes")

            # Parse response
            messages = decoded.split(SOH)
            for msg_part in messages:
                if not msg_part.strip():
                    continue
                print(f"  Message: {msg_part[:200]}")

                # Check for logon ack (msg type 35=A)
                if "35=A" in msg_part:
                    result["success"] = True
                    print("  ✅ LOGON ACKNOWLEDGED — Authentication successful!")
                elif "35=5" in msg_part or "35=3" in msg_part:
                    # Logout or Reject
                    text_tag = None
                    for field in msg_part.split(SOH):
                        if field.startswith("58="):
                            text_tag = field[3:]
                    result["error"] = f"Rejected/Logged out: {text_tag or 'no reason'}"
                    print(f"  ❌ Rejected: {text_tag or 'no reason provided'}")
                elif "35=0" in msg_part:
                    print("  ℹ️ Heartbeat received (server alive)")
        else:
            result["error"] = "No response received (empty)"
            print("  ❌ No response from server")

        # Clean disconnect
        logout = build_fix_string(
            {
                35: "5",
                49: sender_id,
                56: TARGET_COMP_ID,
                34: "2",
                52: time.strftime("%Y%m%d-%H:%M:%S"),
            }
        )
        try:
            ssl_sock.send(logout.encode("latin-1"))
            time.sleep(0.5)
        except Exception:  # noqa: S110
            pass

        ssl_sock.close()

    except socket.timeout:
        result["error"] = f"Connection timed out after {timeout}s"
        print(f"  ❌ Timeout after {timeout}s")
    except ConnectionRefusedError:
        result["error"] = "Connection refused"
        print("  ❌ Connection refused (port closed or firewall)")
    except ssl.SSLError as e:
        result["error"] = f"SSL error: {e}"
        print(f"  ❌ SSL error: {e}")
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"  ❌ {type(e).__name__}: {e}")

    return result


def main():
    print("cTrader FIX Connectivity Test")
    print(f"Host: {HOST}")
    print(f"Account: {ACCOUNT}")

    results = []

    # Test with SOH separators (correct FIX)
    results.append(test_connection(HOST, READONLY_SSL_PORT, "read-only (SOH)", use_soh=True))
    results.append(test_connection(HOST, LIVE_SSL_PORT, "live (SOH)", use_soh=True))

    # Test with pipe separators (matching existing adapter)
    results.append(test_connection(HOST, READONLY_SSL_PORT, "read-only (pipe)", use_soh=False))
    results.append(test_connection(HOST, LIVE_SSL_PORT, "live (pipe)", use_soh=False))

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    for r in results:
        status = "✅ PASS" if r["success"] else "❌ FAIL"
        print(f"  {r['mode']:>12} ({r['port']:>5}): {status}")
        if r["error"]:
            print(f"                Error: {r['error']}")

    all_pass = all(r["success"] for r in results)
    print(f"\n  Overall: {'✅ BOTH CONNECTIONS WORK' if all_pass else '❌ SOME CONNECTIONS FAILED'}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
