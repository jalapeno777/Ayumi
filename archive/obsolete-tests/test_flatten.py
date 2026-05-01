"""Flatten account: send BUY orders to close net short."""
import os
import time
import socket

from dotenv import load_dotenv
load_dotenv("/home/TacoPants/projects/Ayumi/.env")

SOH = "\x01"

def build_fix(msg_type, config, seq, body_fields):
    body = SOH.join(body_fields)
    hdr = SOH.join([
        f"35={msg_type}", f"49={config['sid']}", f"56={config['tid']}",
        f"57={config['tsub']}", f"50={config['ssub']}", f"34={seq}",
        f"52={time.strftime('%Y%m%d-%H:%M:%S', time.gmtime())}",
    ])
    bl = len(hdr.encode()) + 1 + len(body.encode()) + 1
    msg = f"8=FIX.4.4{SOH}9={bl}{SOH}{hdr}{SOH}{body}{SOH}"
    cs = sum(msg.encode()) % 256
    return f"{msg}10={cs:03d}{SOH}"

def recv_all(sock, timeout=5):
    data = b""
    sock.settimeout(timeout)
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk: break
            data += chunk
    except: pass
    return data

config = {
    "host": os.environ["CTRADER_HOST"],
    "port": int(os.environ.get("CTRADER_SSL_PORT", "5202")),
    "sid": os.environ["CTRADER_SENDER_COMP_ID"],
    "tid": os.environ["CTRADER_TARGET_COMP_ID"],
    "ssub": os.environ.get("CTRADER_SENDER_SUB_ID", "TRADE"),
    "tsub": "TRADE",
    "user": os.environ["CTRADER_ACCOUNT"],
    "pass": os.environ["CTRADER_PASSWORD"],
}

sock = socket.socket()
sock.settimeout(10)
sock.connect((config["host"], config["port"]))
sock.send(build_fix("A", config, 1, ["98=0", "108=30", "141=Y", f"553={config['user']}", f"554={config['pass']}"]).encode())
recv_all(sock, 2)

# Send 10 BUY orders to flatten
seq = 2
for i in range(10):
    body = [f"11=flatten_{i}_{int(time.time()*1000)}", "55=1", "54=1", f"60={time.strftime('%Y%m%d-%H:%M:%S', time.gmtime())}", "38=1000", "40=1"]
    sock.send(build_fix("D", config, seq, body).encode())
    seq += 1
    time.sleep(0.5)
    data = recv_all(sock, 3)
    if data:
        for seg in data.decode("latin-1").split(SOH):
            if seg.startswith("150="):
                print(f"  BUY #{i}: execType={seg[3:]}")
            elif seg.startswith("39="):
                print(f"  BUY #{i}: ordStatus={seg[3:]}")
    time.sleep(0.3)

# Now send 10 SELL to close those buys
for i in range(10):
    body = [f"11=flatten_sell_{i}_{int(time.time()*1000)}", "55=1", "54=2", f"60={time.strftime('%Y%m%d-%H:%M:%S', time.gmtime())}", "38=1000", "40=1"]
    sock.send(build_fix("D", config, seq, body).encode())
    seq += 1
    time.sleep(0.5)
    data = recv_all(sock, 3)
    if data:
        for seg in data.decode("latin-1").split(SOH):
            if seg.startswith("150="):
                print(f"  SELL #{i}: execType={seg[3:]}")
            elif seg.startswith("39="):
                print(f"  SELL #{i}: ordStatus={seg[3:]}")
    time.sleep(0.3)

sock.close()
print("Flatten done")
