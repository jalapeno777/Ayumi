#!/usr/bin/env python3
"""Test: run main() logic but with a fake orchestrator that just logs ticks."""
import sys
import os
import time
import logging
import argparse
import signal
import threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "forex-bot"))

# Load env
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

# Use the same logging setup as MVP
fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.DEBUG, format=fmt)

log = logging.getLogger("test_mvp_minimal")

# Build real orchestrator
from engine.trading_orchestrator import build_mvp_orchestrator
from storage.trade_store import TradeStore
trade_store = TradeStore(db_path="data/trading.db")
orch = build_mvp_orchestrator(starting_balance=10000.0, trade_store=trade_store)
log.info("Orchestrator built: %s", orch.registered_strategies)

# Load historical bars
from run_paper_mvp import load_historical_bars
load_historical_bars(orch, symbol="XAUUSD", max_bars=300)

# Create feed directly
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

tick_count = 0
def on_tick(tick):
    global tick_count
    tick_count += 1
    if tick_count % 500 == 0:
        log.info("Tick #%d: bid=%.5f ask=%.5f", tick_count, tick.bid, tick.ask)
    orch.on_tick("XAUUSD", tick.bid, tick.ask)

feed.on_tick(on_tick)
result = feed.start(auto_subscribe=["XAU/USD"])
log.info("Feed started: %s", result)

# Simulate MVP main loop
shutdown_event = threading.Event()

def _shutdown(signum, frame):
    log.info("Shutting down...")
    shutdown_event.set()

signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

# Wait 30 seconds then exit
log.info("Waiting 30 seconds for ticks...")
shutdown_event.wait(timeout=30)

log.info("Total ticks: %d", tick_count)
feed.stop()
trade_store.close()
