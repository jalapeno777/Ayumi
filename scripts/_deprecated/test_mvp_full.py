#!/usr/bin/env python3
"""Test feed with full MVP bootstrap (orchestrator + bars + feed)."""
import sys
import os
import time
import logging
import csv as csv_mod
from pathlib import Path
from datetime import datetime, timezone

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "forex-bot"))

try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

# Build orchestrator
from engine.trading_orchestrator import build_mvp_orchestrator, Bar
from storage.trade_store import TradeStore

trade_store = TradeStore(db_path="data/trading.db")
orch = build_mvp_orchestrator(starting_balance=10000.0, trade_store=trade_store)
print(f"Orchestrator built: {orch.registered_strategies}", flush=True)

# Load historical bars
data_dir = _PROJECT_ROOT / "data" / "forex" / "historical"
csv_path = data_dir / "XAUUSD_M5.csv"
bars = []
with open(csv_path) as f:
    reader = csv_mod.DictReader(f)
    rows = list(reader)[-300:]
    for row in rows:
        try:
            dt = datetime.strptime(row["Date"].strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            dt = datetime.strptime(row["Date"].strip(), "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=timezone.utc)
        bars.append(Bar(time=dt, open=float(row["Open"]), high=float(row["High"]),
                       low=float(row["Low"]), close=float(row["Close"]),
                       volume=float(row.get("Volume", 0))))
print(f"Loaded {len(bars)} M5 bars", flush=True)
orch.load_historical_bars("XAUUSD", "M5", bars)

# Now test feed
from adapters.ctrader.market_data_feed import LiveMarketDataFeed, SymbolInfo
from adapters.ctrader.models import cTraderCredentials

creds = cTraderCredentials(
    host=os.getenv("CTRADER_HOST"),
    port=int(os.getenv("CTRADER_READONLY_SSL_PORT", "5211")),
    use_ssl=True,
    sender_comp_id=os.getenv("CTRADER_SENDER_COMP_ID", ""),
    target_comp_id=os.getenv("CTRADER_TARGET_COMP_ID", "cServer"),
    sender_sub_id="QUOTE",
    target_sub_id="QUOTE",
    username=os.getenv("CTRADER_ACCOUNT", ""),
    password=os.getenv("CTRADER_PASSWORD", ""),
)

feed = LiveMarketDataFeed(creds)
feed._symbols[31] = SymbolInfo(symbol_id=31, name="XAU/USD")
feed._name_to_id["XAU/USD"] = 31

count = 0
def on_tick(tick):
    global count
    count += 1
    if count <= 3:
        print(f"TICK #{count}: bid={tick.bid}", flush=True)
    orch.on_tick("XAUUSD", tick.bid, tick.ask)

feed.on_tick(on_tick)
result = feed.start(auto_subscribe=["XAU/USD"])
print(f"start() returned: {result}", flush=True)
time.sleep(15)
print(f"Total in 15s: {count}", flush=True)
feed.stop()
trade_store.close()
