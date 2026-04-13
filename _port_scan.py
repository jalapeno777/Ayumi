"""Test readonly port with plain text (no SSL)."""
import socket, time, os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

host = os.environ["CTRADER_HOST"]
sender = os.environ["CTRADER_SENDER_COMP_ID"]
target = os.environ.get("CTRADER_TARGET_COMP_ID", "cServer")
sub = os.environ.get("CTRADER_SENDER_SUB_ID", "TRADE")
user = os.environ["CTRADER_ACCOUNT"]
pwd = os.environ["CTRADER_PASSWORD"]
SOH = "\x01"

# Test multiple ports
for port in [5211, 5212, 5213, 5214, 5215]:
    print(f"\n--- Testing port {port} (plain text) ---")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(8)
        sock.connect((host, port))
        print(f"  Connected!")

        ts = time.strftime('%Y%m%d-%H:%M:%S')
        body = f"98=0{SOH}108=30{SOH}141=Y{SOH}553={user}{SOH}554={pwd}{SOH}"
        header = f"8=FIX.4.4{SOH}9={len(body)}{SOH}35=A{SOH}49={sender}{SOH}56={target}{SOH}50={sub}{SOH}34=1{SOH}52={ts}{SOH}"
        raw = header + body
        chk = sum(b for b in raw.encode('ascii')) % 256
        trailer = f"10={chk:03d}{SOH}"
        sock.send((raw + trailer).encode('ascii'))
        print(f"  Sent logon, waiting...")

        try:
            data = sock.recv(4096)
            print(f"  Got {len(data)} bytes: {data[:150]}")
        except socket.timeout:
            print(f"  TIMEOUT - no response")
        sock.close()
    except Exception as e:
        print(f"  Error: {e}")
