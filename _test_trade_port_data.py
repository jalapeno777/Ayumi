"""Test if trade port (5202) also streams market data."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "forex-bot"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
import time
from adapters.ctrader.api_client import FIXClient, FIXMessage
from adapters.ctrader.market_data_feed import MarketDataClient, LiveMarketDataFeed, SymbolInfo
from adapters.ctrader.models import cTraderCredentials

creds = cTraderCredentials(
    host=os.environ["CTRADER_HOST"],
    port=int(os.environ.get("CTRADER_SSL_PORT", "5202")),
    use_ssl=False,
    sender_comp_id=os.environ["CTRADER_SENDER_COMP_ID"],
    target_comp_id=os.environ.get("CTRADER_TARGET_COMP_ID", "cServer"),
    sender_sub_id=os.environ.get("CTRADER_SENDER_SUB_ID", "TRADE"),
    username=os.environ["CTRADER_ACCOUNT"],
    password=os.environ["CTRADER_PASSWORD"],
)

# Use MarketDataClient (extends FIXClient) on the trade port
client = MarketDataClient(creds)
ok = client.connect()
print(f"Trade port connected: {ok}")
if not ok:
    sys.exit(1)

time.sleep(2)
print(f"Still connected: {client.is_connected}")

# Try subscribing to EUR/USD (id=1) using the market data request format
msg = FIXMessage(msg_type="V")
msg.set_body_field(262, "TEST_001")
msg.set_body_field(263, "1")  # snapshot + updates
msg.set_body_field(264, "1")  # top of book
msg.set_body_field(265, "1")  # full refresh
msg.set_body_field(267, "2")  # 2 entry types
msg.set_body_field(269, "0")  # bid
msg.set_body_field(269, "1")  # ask
msg.set_body_field(146, "1")  # NoRelatedSym
msg.set_body_field(55, "1")   # EUR/USD
client._send_message(msg)
print("Subscribed to EUR/USD on trade port, waiting 10s...")

# Also try GBP/USD, USD/JPY
for sid in [2, 3]:
    msg = FIXMessage(msg_type="V")
    msg.set_body_field(262, f"TEST_{sid:03d}")
    msg.set_body_field(263, "1")
    msg.set_body_field(264, "1")
    msg.set_body_field(265, "1")
    msg.set_body_field(267, "2")
    msg.set_body_field(269, "0")
    msg.set_body_field(269, "1")
    msg.set_body_field(146, "1")
    msg.set_body_field(55, str(sid))
    client._send_message(msg)

found = []
orig = client._handle_message
def capture(msg):
    mt = msg.msg_type
    if mt == "W":
        found.append(dict(msg.fields))
        print(f"  Snapshot: {dict(msg.fields)}")
    orig(msg)
client._handle_message = capture

time.sleep(10)
client.disconnect()
print(f"\nSnapshots received: {len(found)}")
