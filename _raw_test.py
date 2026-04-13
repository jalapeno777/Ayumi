"""Raw socket test - see what the readonly port actually returns."""
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

def build_msg(msg_type, body_fields=None):
    """Build a minimal FIX message."""
    header = f"8=FIX.4.4{SOH}9={0}{SOH}35={msg_type}{SOH}49={sender}{SOH}56={target}{SOH}50={sub}{SOH}34={1}{SOH}52={time.strftime('%Y%m%d-%H:%M:%S')}{SOH}"
    body = ""
    if body_fields:
        for tag, val in body_fields.items():
            body += f"{tag}={val}{SOH}"
    raw = header + body
    # Calculate body length (everything between 9= and 10=)
    body_start = raw.index("9=") + 2
    body_end = raw.index(SOH, body_start)
    # Actually need to recalculate properly
    # Body = everything after 8=...SOH up to 10=
    parts = raw.split(SOH)
    # Rebuild properly
    body_str = SOH.join([p for p in parts if not p.startswith("8=") and not p.startswith("9=")])
    # This is getting messy, let me use the library instead
    return None

# Just use the library for message building
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "forex-bot"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from adapters.ctrader.api_client import FIXClient, FIXMessage
from adapters.ctrader.market_data_feed import MarketDataClient

creds = type('Creds', (), {
    'host': host, 'port': port, 'use_ssl': True,
    'sender_comp_id': sender, 'target_comp_id': target,
    'sender_sub_id': sub, 'sender_sub_target': '',
    'username': user, 'password': pwd,
})()

client = MarketDataClient(creds)
ok = client.connect()
print(f"Connected: {ok}")
time.sleep(2)

# Subscribe to EUR/USD
msg = FIXMessage(msg_type="V")
msg.set_body_field(262, "RAW_TEST")
msg.set_body_field(263, "1")
msg.set_body_field(264, "1")
msg.set_body_field(265, "1")
msg.set_body_field(267, "2")
msg.set_body_field(269, "0")
msg.set_body_field(269, "1")
msg.set_body_field(146, "1")
msg.set_body_field(55, "1")
client._send_message(msg)
print("Subscribed. Waiting 15s...")

# Dump ALL incoming messages
messages = []
orig = client._handle_message
def dump(msg):
    mt = msg.msg_type
    raw = getattr(msg, '_raw_fields', None)
    messages.append((mt, dict(msg.fields)))
    if mt not in ("0", "1"):  # skip heartbeats
        print(f"  MSG type={mt}: {dict(msg.fields)}")
orig(msg)
client._handle_message = dump

time.sleep(15)
client.disconnect()
print(f"\nTotal messages: {len(messages)}")
non_hb = [m for m in messages if m[0] not in ("0", "1")]
print(f"Non-heartbeat messages: {len(non_hb)}")
