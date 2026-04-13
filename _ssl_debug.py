"""Debug the SSL connection to readonly port."""
import socket, ssl, time, os, sys
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

host = os.environ["CTRADER_HOST"]
port = int(os.environ["CTRADER_READONLY_SSL_PORT"])
sender = os.environ["CTRADER_SENDER_COMP_ID"]
target = os.environ.get("CTRADER_TARGET_COMP_ID", "cServer")
sub = os.environ.get("CTRADER_SENDER_SUB_ID", "TRADE")
user = os.environ["CTRADER_ACCOUNT"]
pwd = os.environ["CTRADER_PASSWORD"]

SOH = "\x01"

# Build raw logon message
def make_fix(body_str):
    header = f"8=FIX.4.4{SOH}9={len(body_str)}{SOH}35={body_str.split(SOH)[0].split('=')[1]}{SOH}"
    # This is getting complicated, let me just use raw bytes

# Actually let's just test raw TCP + SSL
print(f"Connecting to {host}:{port}...")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(10)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
ssock = ctx.wrap_socket(sock, server_hostname=host)
ssock.connect((host, port))
print(f"SSL connected: {ssock.version()}")

# Try receiving without sending anything first
print("Listening for server-initiated message (5s)...")
try:
    data = ssock.recv(4096)
    print(f"Got {len(data)} bytes: {data[:200]}")
except socket.timeout:
    print("No data from server (expected - we haven't logged in)")

# Send a minimal logon
ts = time.strftime('%Y%m%d-%H:%M:%S')
body = f"98=0{SOH}108=30{SOH}141=Y{SOH}553={user}{SOH}554={pwd}{SOH}"
header = f"8=FIX.4.4{SOH}9={len(body)}{SOH}35=A{SOH}49={sender}{SOH}56={target}{SOH}50={sub}{SOH}34=1{SOH}52={ts}{SOH}"
raw = header + body
# Add checksum
chk = 0
for b in raw.encode('ascii'):
    chk = (chk + b) % 256
trailer = f"10={chk:03d}{SOH}"
wire = (raw + trailer).encode('ascii')
print(f"Sending logon ({len(wire)} bytes)...")
ssock.send(wire)

print("Waiting for response (10s)...")
try:
    data = ssock.recv(4096)
    print(f"Got {len(data)} bytes: {data}")
except socket.timeout:
    print("TIMEOUT - no response from server!")

ssock.close()
print("Done")
