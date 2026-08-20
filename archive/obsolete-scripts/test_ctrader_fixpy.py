#!/usr/bin/env python3
"""
Test cTrader FIX connection using Spotware's official cTraderFixPy library format.
Falls back to manual connection if ctrader-fix not installed.
"""

import os  # noqa: I001
import ssl
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            os.environ.setdefault(key, val.strip('"').strip("'"))

HOST = os.environ.get("CTRADER_FIX_HOST", "demo-uk-eqx-01.p.c-trader.com")
ACCOUNT = os.environ.get("CTRADER_ACCOUNT", "5795523")
PASSWORD = os.environ.get("CTRADER_PASSWORD", "44J*aldC3Req9osKd")
SENDER_COMP_ID = os.environ.get("CTRADER_FIX_SENDER_COMP_ID", f"demo.c-trader.{ACCOUNT}")

config = {
    "Host": HOST,
    "Port": 5212,
    "SSL": True,
    "Username": ACCOUNT,
    "Password": PASSWORD,
    "BeginString": "FIX.4.4",
    "SenderCompID": SENDER_COMP_ID,
    "SenderSubID": "QUOTE",
    "TargetCompID": "cServer",  # Mixed case — per official Spotware library
    "TargetSubID": "TRADE",
    "HeartBeat": "30",
}

SOH = "\x01"


def build_message_official(msg_type, cfg, body_fields=None, seq_num=1):
    """Replicate the official cTraderFixPy library's exact message construction."""
    fields = [
        f"35={msg_type}",
        f"49={cfg['SenderCompID']}",
        f"56={cfg['TargetCompID']}",
        f"57={cfg['TargetSubID']}",
        f"50={cfg['SenderSubID']}",
        f"34={seq_num}",
        f"52={datetime.now(timezone.utc).strftime('%Y%m%d-%H:%M:%S')}",
    ]
    fields_joined = SOH.join(fields)

    if body_fields:
        body = SOH.join(body_fields)
        header = f"8={cfg['BeginString']}{SOH}9={len(body) + len(fields_joined) + 2}{SOH}{fields_joined}"
        header_and_body = f"{header}{SOH}{body}{SOH}"
    else:
        header = f"8={cfg['BeginString']}{SOH}9={0 + len(fields_joined) + 2}{SOH}{fields_joined}"
        header_and_body = f"{header}{SOH}"

    checksum = sum(header_and_body.encode("ascii")) % 256
    return f"{header_and_body}10={str(checksum).zfill(3)}{SOH}"


def main():
    print("=" * 60)
    print("  cTrader FIX Test — Official cTraderFixPy Format")
    print("=" * 60)
    print(f"  Host:          {config['Host']}")
    print(f"  Port:          {config['Port']}")
    print(f"  TargetCompID:  {config['TargetCompID']}")
    print(f"  SenderCompID:  {config['SenderCompID']}")
    print(f"  Account:       {ACCOUNT}")
    print("=" * 60)

    # Try official library first
    try:
        from ctrader_fix.messages import LogonRequest  # noqa: I001
        from ctrader_fix import Client
        from twisted.internet import reactor

        state = {"logon": False, "reason": None}

        def on_msg(client, response):
            mt = response.getFieldValue(35)
            txt = response.getFieldValue(58)
            print(f"  << {response.getMessage()[:300]}")
            if mt == "A":
                state["logon"] = True
                print("  ✅ LOGON ACK!")
            elif mt == "5":
                state["reason"] = txt
                print(f"  ❌ Logout: {txt}")
            reactor.callLater(0.5, reactor.stop)

        def on_connect(client):
            print("  ✅ Connected, sending logon...")
            logon = LogonRequest(config)
            logon.ResetSeqNum = True
            client.send(logon)

        def on_disconnect(client, reason):
            if not state["logon"] and not state["reason"]:
                state["reason"] = f"disconnected: {reason}"
            reactor.callLater(0, reactor.stop)

        client = Client(config["Host"], config["Port"], ssl=config["SSL"])
        client.setConnectedCallback(on_connect)
        client.setDisconnectedCallback(on_disconnect)
        client.setMessageReceivedCallback(on_msg)
        client.startService()
        reactor.callLater(15, lambda: (print("  ❌ Timeout"), reactor.stop()))
        reactor.run()

        if state["logon"]:
            print("\n  ✅✅✅ SUCCESS!")
            return 0
        print(f"\n  ❌ FAILED: {state['reason'] or 'no response'}")
        return 1

    except ImportError:
        print("  ctrader-fix not installed, using manual fallback...\n")

    # Manual fallback — same wire format as official library
    logon_body = [
        "98=0",
        f"108={config['HeartBeat']}",
        "141=Y",
        f"553={config['Username']}",
        f"554={config['Password']}",
    ]
    msg = build_message_official("A", config, logon_body)
    print(f"  >> LOGON ({len(msg.encode('ascii'))} bytes):")
    print(f"     {msg.replace(SOH, '|')}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((config["Host"], config["Port"]))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ssl_sock = ctx.wrap_socket(sock, server_hostname=config["Host"])
    print("  ✅ Connected")

    ssl_sock.send(msg.encode("ascii"))

    response = b""
    ssl_sock.settimeout(3)
    start = time.time()
    while time.time() - start < 10:
        try:
            chunk = ssl_sock.recv(4096)
            if chunk:
                response += chunk
                ssl_sock.settimeout(1)
            else:
                break
        except (socket.timeout, ssl.SSLError):
            if response:
                break
            continue
    ssl_sock.close()

    if response:
        decoded = response.decode("ascii", errors="replace")
        print(f"  << Received ({len(response)} bytes):")
        for field in decoded.split(SOH):
            if field.strip():
                print(f"     {field}")
        if "35=A" in decoded:
            print("\n  ✅✅✅ LOGON ACKNOWLEDGED!")
            return 0
        elif "35=5" in decoded:
            reason = next(
                (f.split("=", 1)[1] for f in decoded.split(SOH) if f.startswith("58=")),
                "?",
            )
            print(f"\n  ❌ Logout: {reason}")
            return 1
    else:
        print("  ❌ No response")
        return 1


if __name__ == "__main__":
    sys.exit(main())
