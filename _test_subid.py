"""Test readonly port with different SenderSubID values."""
import socket, ssl, time, os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

host = os.environ["CTRADER_HOST"]
sender = os.environ["CTRADER_SENDER_COMP_ID"]
target = os.environ.get("CTRADER_TARGET_COMP_ID", "cServer")
user = os.environ["CTRADER_ACCOUNT"]
pwd = os.environ["CTRADER_PASSWORD"]
SOH = "\x01"
port = 5211

for sub_id in ["TRADE", "QUOTE", "QUOTE2", "MD", "MARKET", "Q", "0", ""]:
    print(f"\n--- SenderSubID='{sub_id}' ---")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(8)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ssock = ctx.wrap_socket(sock, server_hostname=host)
        ssock.connect((host, port))

        ts = time.strftime('%Y%m%d-%H:%M:%S')
        body = f"98=0{SOH}108=30{SOH}141=Y{SOH}553={user}{SOH}554={pwd}{SOH}"
        header = f"8=FIX.4.4{SOH}9={len(body)}{SOH}35=A{SOH}49={sender}{SOH}56={target}{SOH}50={sub_id}{SOH}34=1{SOH}52={ts}{SOH}"
        raw = header + body
        chk = sum(b for b in raw.encode('ascii')) % 256
        trailer = f"10={chk:03d}{SOH}"
        ssock.send((raw + trailer).encode('ascii'))

        try:
            data = ssock.recv(4096)
            if len(data) == 0:
                print(f"  0 bytes (rejected)")
            else:
                print(f"  {len(data)} bytes: {data[:200]}")
        except socket.timeout:
            print(f"  TIMEOUT")
        ssock.close()
    except Exception as e:
        print(f"  Error: {e}")

# Also try plain text on 5211
print(f"\n--- Plain text on 5211 ---")
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(8)
    sock.connect((host, port))
    ts = time.strftime('%Y%m%d-%H:%M:%S')
    body = f"98=0{SOH}108=30{SOH}141=Y{SOH}553={user}{SOH}554={pwd}{SOH}"
    header = f"8=FIX.4.4{SOH}9={len(body)}{SOH}35=A{SOH}49={sender}{SOH}56={target}{SOH}50=TRADE{SOH}34=1{SOH}52={ts}{SOH}"
    raw = header + body
    chk = sum(b for b in raw.encode('ascii')) % 256
    trailer = f"10={chk:03d}{SOH}"
    sock.send((raw + trailer).encode('ascii'))
    try:
        data = sock.recv(4096)
        print(f"  {len(data)} bytes: {data[:200]}")
    except socket.timeout:
        print(f"  TIMEOUT")
    sock.close()
except Exception as e:
    print(f"  Error: {e}")
