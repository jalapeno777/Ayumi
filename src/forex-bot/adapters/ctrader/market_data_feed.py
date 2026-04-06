"""cTrader FIX Market Data Feed.

Provides live price streaming from cTrader via the QUOTE connection (port 5211/SSL).

Protocol notes:
- MarketDataRequest (35=V) requires SubscriptionRequestType=1 (snapshot + updates)
- cTrader does NOT support snapshot-only (263=0)
- Symbols are identified by numeric ID (tag 55), not string (e.g. 1 = EUR/USD)
- MDEntryType 269=0 (bid), 269=1 (ask)
- MDEntryPx (270) contains the price
- Responses are MarketDataSnapshot (35=W) with repeating group entries
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set

from .api_client import FIXClient, FIXMessage
from .models import cTraderCredentials

logger = logging.getLogger(__name__)


@dataclass
class Tick:
    """A single price update from the market."""
    symbol_id: int
    bid: float
    ask: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass
class SymbolInfo:
    """Metadata about a tradable symbol."""
    symbol_id: int
    name: str  # e.g. "EUR/USD"
    pip_size: float = 0.0001  # default, will be calibrated from live data
    digits: int = 5


# Known cTrader symbol IDs (FTMO demo account).
# This will be auto-populated from live data, but we seed common ones.
DEFAULT_SYMBOLS: Dict[int, str] = {
    1: "EUR/USD",
    2: "GBP/USD",
    3: "USD/JPY",
    4: "USD/CHF",
    5: "AUD/USD",
    6: "USD/CAD",
    7: "NZD/USD",
}

# Common forex symbols we care about for trading
FOREX_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD"]


class MarketDataClient(FIXClient):
    """Extended FIXClient that properly handles MarketDataSnapshot repeating groups."""

    def __init__(self, credentials):
        super().__init__(credentials)
        self._md_handlers: List[Callable] = []

    def register_md_handler(self, handler: Callable):
        self._md_handlers.append(handler)

    def _handle_message(self, msg: FIXMessage):
        msg_type = msg.msg_type

        if msg_type == "W":  # MarketDataSnapshot
            for handler in self._md_handlers:
                try:
                    handler(msg)
                except Exception as e:
                    logger.error(f"MD handler error: {e}")
            return  # Don't pass to parent — we handle it ourselves

        super()._handle_message(msg)


class LiveMarketDataFeed:
    """Live market data feed using MarketDataClient for proper repeating group handling.

    Usage:
        feed = LiveMarketDataFeed(quote_credentials)
        feed.start()
        tick = feed.get_tick("EUR/USD")
        feed.stop()
    """

    TAG_MD_REQ_ID = 262
    TAG_SUBSCRIPTION_TYPE = 263
    TAG_MARKET_DEPTH = 264
    TAG_MD_UPDATE_TYPE = 265
    TAG_NO_MD_ENTRY_TYPES = 267
    TAG_MD_ENTRY_TYPE = 269
    TAG_MD_ENTRY_PX = 270
    TAG_NO_RELATED_SYM = 146
    TAG_SYMBOL = 55
    TAG_NO_MD_ENTRIES = 268

    def __init__(self, credentials: cTraderCredentials):
        self._credentials = credentials
        self._client: Optional[MarketDataClient] = None
        self._running = False
        self._ticks: Dict[int, Tick] = {}
        self._symbols: Dict[int, SymbolInfo] = {
            sid: SymbolInfo(symbol_id=sid, name=name)
            for sid, name in DEFAULT_SYMBOLS.items()
        }
        self._name_to_id: Dict[str, int] = {v: k for k, v in DEFAULT_SYMBOLS.items()}
        self._id_to_name: Dict[int, str] = {k: v for k, v in DEFAULT_SYMBOLS.items()}
        self._subscriptions: Set[int] = set()
        self._lock = threading.Lock()
        self._tick_callbacks: List[Callable[[Tick], None]] = []
        self._next_req_id = 1

    @property
    def symbols(self) -> Dict[int, SymbolInfo]:
        with self._lock:
            return dict(self._symbols)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def name_to_id(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._name_to_id)

    def start(self, auto_subscribe: Optional[List[str]] = None) -> bool:
        """Connect and optionally auto-subscribe to symbols."""
        if self._running:
            return True

        self._client = MarketDataClient(self._credentials)
        self._client.register_md_handler(self._on_snapshot)
        self._client.register_callback("on_logon", lambda m: logger.info("MD feed logged in"))

        if not self._client.connect():
            logger.error("Failed to connect MD feed")
            return False

        self._running = True

        if auto_subscribe is None:
            auto_subscribe = FOREX_PAIRS

        for name in auto_subscribe:
            self.subscribe(name)

        logger.info(f"Market data feed started (auto-subscribed to {len(auto_subscribe)} pairs)")
        return True

    def stop(self):
        self._running = False
        if self._client:
            self._client.disconnect()
        with self._lock:
            self._subscriptions.clear()
            self._ticks.clear()

    def subscribe(self, symbol_name: str) -> bool:
        symbol_id = self._resolve_id(symbol_name)
        if symbol_id is None:
            logger.error(f"Unknown symbol: {symbol_name}")
            return False
        if symbol_id in self._subscriptions:
            return True

        req_id = f"SUB_{self._next_req_id:04d}"
        self._next_req_id += 1

        msg = FIXMessage(msg_type="V")
        # Body fields in correct FIX order with repeating groups
        msg.set_body_field(self.TAG_MD_REQ_ID, req_id)
        msg.set_body_field(self.TAG_SUBSCRIPTION_TYPE, "1")
        msg.set_body_field(self.TAG_MARKET_DEPTH, "1")
        msg.set_body_field(self.TAG_MD_UPDATE_TYPE, "1")
        msg.set_body_field(self.TAG_NO_MD_ENTRY_TYPES, "2")
        msg.set_body_field(self.TAG_MD_ENTRY_TYPE, "0")
        msg.set_body_field(self.TAG_MD_ENTRY_TYPE, "1")
        msg.set_body_field(self.TAG_NO_RELATED_SYM, "1")
        msg.set_body_field(self.TAG_SYMBOL, str(symbol_id))  # Inside repeating group

        if self._client._send_message(msg):
            with self._lock:
                self._subscriptions.add(symbol_id)
            logger.info(f"Subscribed to {symbol_name} (id={symbol_id})")
            return True
        return False

    def unsubscribe(self, symbol_name: str) -> bool:
        symbol_id = self._resolve_id(symbol_name)
        if symbol_id is None:
            return False

        req_id = f"UNSUB_{self._next_req_id:04d}"
        self._next_req_id += 1

        msg = FIXMessage(msg_type="V")
        msg.set_field(self.TAG_SYMBOL, str(symbol_id))
        msg.set_body_field(self.TAG_MD_REQ_ID, req_id)
        msg.set_body_field(self.TAG_SUBSCRIPTION_TYPE, "2")
        msg.set_body_field(self.TAG_MARKET_DEPTH, "1")

        if self._client._send_message(msg):
            with self._lock:
                self._subscriptions.discard(symbol_id)
            return True
        return False

    def get_tick(self, symbol_name: str) -> Optional[Tick]:
        symbol_id = self._resolve_id(symbol_name)
        if symbol_id is None:
            return None
        with self._lock:
            return self._ticks.get(symbol_id)

    def get_tick_by_id(self, symbol_id: int) -> Optional[Tick]:
        with self._lock:
            return self._ticks.get(symbol_id)

    def get_all_ticks(self) -> Dict[str, Tick]:
        with self._lock:
            return {
                self._symbols[sid].name: tick
                for sid, tick in self._ticks.items()
                if sid in self._symbols
            }

    def get_spread(self, symbol_name: str) -> Optional[float]:
        tick = self.get_tick(symbol_name)
        return tick.spread if tick else None

    def on_tick(self, callback: Callable[[Tick], None]):
        self._tick_callbacks.append(callback)

    def _resolve_id(self, symbol_name: str) -> Optional[int]:
        with self._lock:
            return self._name_to_id.get(symbol_name)

    def _on_snapshot(self, msg: FIXMessage):
        """Handle MarketDataSnapshot (35=W).

        cTrader sends repeating group entries in the flat fields dict.
        Since FIXMessage uses a flat dict, repeated tags (269, 270) get overwritten.
        We need raw wire data to properly parse repeating groups.

        Solution: We store raw wire data on the message during parsing.
        For now, we work around this by using the raw fields from the
        buffer processing. The FIXClient._process_buffer calls _handle_message
        with a parsed message. We enhance this by storing raw field lists.
        """
        # Parse from raw data stored during buffer processing
        symbol_id = int(msg.get_field(55) or 0)

        # Use the _raw_fields attribute if available (set during parsing)
        raw_fields = getattr(msg, '_raw_fields', None)
        if raw_fields is None:
            # Fallback: parse from the flat dict (last value wins)
            entry_type = msg.get_field(269)
            entry_px = msg.get_field(270)
            if entry_type is None or entry_px is None:
                return

            bid = float(entry_px) if entry_type == "0" else None
            ask = float(entry_px) if entry_type == "1" else None
        else:
            bid = None
            ask = None
            # Group fields by their position in the repeating group
            current_type = None
            for tag, value in raw_fields:
                if tag == 269:
                    current_type = value
                elif tag == 270 and current_type is not None:
                    px = float(value)
                    if current_type == "0":
                        bid = px
                    elif current_type == "1":
                        ask = px
                    current_type = None  # reset for next entry

        if bid is None or ask is None:
            logger.debug(f"Incomplete tick for symbol {symbol_id}: bid={bid}, ask={ask}")
            return

        timestamp_str = msg.get_field(52)
        if timestamp_str:
            try:
                timestamp = datetime.strptime(
                    timestamp_str, "%Y%m%d-%H:%M:%S.%f"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                timestamp = datetime.strptime(
                    timestamp_str, "%Y%m%d-%H:%M:%S"
                ).replace(tzinfo=timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        tick = Tick(symbol_id=symbol_id, bid=bid, ask=ask, timestamp=timestamp)

        with self._lock:
            self._ticks[symbol_id] = tick

        for cb in self._tick_callbacks:
            try:
                cb(tick)
            except Exception as e:
                logger.error(f"Tick callback error: {e}")
