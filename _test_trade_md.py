"""Test MarketDataRequest on the trade port (5202) with proper FIX format."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "forex-bot"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
import time
from adapters.ctrader.market_data_feed import MarketDataClient, LiveMarketDataFeed, SymbolInfo
from adapters.ctrader.models import cTraderCredentials

# Use MarketDataClient on the TRADE port
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

client = MarketDataClient(creds)
ok = client.connect()
print(f"Connected: {ok}")
if not ok:
    sys.exit(1)
time.sleep(2)
print(f"Logged in: {client.is_connected}")

# Register raw message handler to see everything
all_msgs = []
orig = client._handle_message
def capture(msg):
    mt = msg.msg_type
    raw = dict(msg.fields)
    all_msgs.append((mt, raw))
    if mt not in ("0",):
        print(f"  [{mt}] {raw}")
    orig(msg)
client._handle_message = capture

# Use LiveMarketDataFeed's exact subscribe format but on this client
feed = LiveMarketDataFeed(creds)
feed._client = client  # inject the trade port client

# Subscribe to EUR/USD using feed's own method
print("\nSubscribing to EUR/USD, GBP/USD, USD/JPY...")
result = feed.subscribe("EUR/USD")
print(f"EUR/USD subscribe: {result}")
result = feed.subscribe("GBP/USD")
print(f"GBP/USD subscribe: {result}")
result = feed.subscribe("USD/JPY")
print(f"USD/JPY subscribe: {result}")

# Also try XAU with various IDs
print("\nTrying XAU symbol IDs...")
for xau_id in [4, 5, 6, 7, 8, 10, 15, 20, 25, 30, 31, 35, 40, 50, 64, 70, 80, 8819]:
    feed._symbols[xau_id] = SymbolInfo(symbol_id=xau_id, name=f"XAU_{xau_id}", pip_size=0.01, digits=2)
    feed._name_to_id[f"XAU_{xau_id}"] = xau_id
    feed._id_to_name[xau_id] = f"XAU_{xau_id}"
    r = feed.subscribe(f"XAU_{xau_id}")
    if r:
        print(f"  ID {xau_id}: subscribed OK")

print("\nWaiting 15s for data...")
time.sleep(15)

# Summary
non_hb = [(mt, f) for mt, f in all_msgs if mt != "0"]
print(f"\nTotal messages: {len(all_msgs)}")
print(f"Non-heartbeat: {len(non_hb)}")
for mt, f in non_hb:
    print(f"  {mt}: {f}")

client.disconnect()
