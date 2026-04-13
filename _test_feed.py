"""Test market data feed with default forex symbols."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "forex-bot"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
import time
from adapters.ctrader.market_data_feed import LiveMarketDataFeed
from adapters.ctrader.models import cTraderCredentials

creds = cTraderCredentials(
    host=os.environ["CTRADER_HOST"],
    port=int(os.environ["CTRADER_READONLY_SSL_PORT"]),
    use_ssl=True,
    sender_comp_id=os.environ["CTRADER_SENDER_COMP_ID"],
    target_comp_id=os.environ.get("CTRADER_TARGET_COMP_ID", "cServer"),
    sender_sub_id=os.environ.get("CTRADER_SENDER_SUB_ID", "TRADE"),
    username=os.environ["CTRADER_ACCOUNT"],
    password=os.environ["CTRADER_PASSWORD"],
)

feed = LiveMarketDataFeed(creds)
discovered = {}

def on_tick(tick):
    if tick.symbol_id not in discovered:
        discovered[tick.symbol_id] = (tick.bid, tick.ask)
        print(f"  ID={tick.symbol_id}: bid={tick.bid} ask={tick.ask}")
feed.on_tick(on_tick)

# Subscribe to known forex pairs
feed.start(auto_subscribe=["EUR/USD", "GBP/USD", "USD/JPY"])
print("Subscribed to 3 forex pairs, waiting 10s...")
time.sleep(10)
feed.stop()

print(f"\nTotal ticks received: {len(discovered)}")
if not discovered:
    print("NO DATA - market may be closed or connection issue")
