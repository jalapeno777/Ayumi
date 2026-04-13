"""Quick scan for XAU/USD symbol ID on cTrader."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "forex-bot"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
import time
from adapters.ctrader.market_data_feed import LiveMarketDataFeed, SymbolInfo
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

for sid in range(1, 200):
    feed._symbols[sid] = SymbolInfo(symbol_id=sid, name=f"SYM_{sid}", pip_size=0.0001, digits=5)
    feed._name_to_id[f"SYM_{sid}"] = sid
    feed._id_to_name[sid] = f"SYM_{sid}"

discovered = {}
def on_tick(tick):
    if tick.symbol_id not in discovered:
        discovered[tick.symbol_id] = (tick.bid, tick.ask)
feed.on_tick(on_tick)

names = [f"SYM_{i}" for i in range(1, 200)]
feed.start(auto_subscribe=names)
time.sleep(8)
feed.stop()

print(f"Active IDs: {sorted(discovered.keys())}")
for sid, (bid, ask) in sorted(discovered.items()):
    price = float(bid) if bid else 0
    tag = " <-- XAU candidate" if price > 500 else ""
    print(f"  ID={sid}: bid={bid} ask={ask}{tag}")
