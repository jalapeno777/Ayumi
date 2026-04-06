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
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set

from .api_client import FIXClient, FIXMessage, SOH
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


class MarketDataFeed:
    """Live market data feed from cTrader FIX QUOTE connection.

    Usage:
        feed = MarketDataFeed(quote_credentials)
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
    TAG_MD_ENTRY_ID = 278

    def __init__(
        self,
        credentials: cTraderCredentials,
        heartbeat_interval: int = 30,
    ):
        self._credentials = credentials
        self._heartbeat_interval = heartbeat_interval
        self._client: Optional[FIXClient] = None
        self._running = False
        self._ticks: Dict[int, Tick] = {}  # symbol_id -> latest tick
        self._symbols: Dict[int, SymbolInfo] = {
            sid: SymbolInfo(symbol_id=sid, name=name)
            for sid, name in DEFAULT_SYMBOLS.items()
        }
        self._name_to_id: Dict[str, int] = {v: k for k, v in DEFAULT_SYMBOLS.items()}
        self._subscriptions: Set[int] = set()
        self._lock = threading.Lock()
        self._tick_callbacks: List[Callable[[Tick], None]] = []
        self._error_callbacks: List[Callable[[str], None]] = []
        self._next_req_id = 1

    @property
    def symbols(self) -> Dict[int, SymbolInfo]:
        """Return all known symbols."""
        with self._lock:
            return dict(self._symbols)

    @property
    def name_to_id(self) -> Dict[str, int]:
        """Return mapping from symbol name to numeric ID."""
        with self._lock:
            return dict(self._name_to_id)

    def start(self) -> bool:
        """Connect to cTrader and start receiving market data."""
        if self._running:
            return True

        self._client = FIXClient(self._credentials)
        self._client.register_callback("on_logon", self._on_logon)
        self._client.register_callback("on_logout", self._on_logout)
        self._client.register_callback("on_heartbeat", self._on_heartbeat)

        # Register handlers for market data messages
        with self._client._lock:
            self._client._callbacks["_md_snapshot"] = self._handle_market_data_snapshot
            self._client._callbacks["_md_reject"] = self._handle_market_data_reject

        if not self._client.connect():
            logger.error("Failed to connect market data feed")
            return False

        self._running = True
        logger.info("Market data feed started")
        return True

    def stop(self):
        """Unsubscribe and disconnect."""
        if not self._running:
            return
        self._running = False
        if self._client:
            self._client.disconnect()
        logger.info("Market data feed stopped")

    def subscribe(self, symbol_name: str) -> bool:
        """Subscribe to market data for a symbol (e.g. 'EUR/USD')."""
        symbol_id = self._resolve_symbol_id(symbol_name)
        if symbol_id is None:
            logger.error(f"Unknown symbol: {symbol_name}")
            return False

        if symbol_id in self._subscriptions:
            return True  # already subscribed

        return self._send_subscription(symbol_id)

    def subscribe_many(self, symbol_names: List[str]) -> Dict[str, bool]:
        """Subscribe to multiple symbols. Returns {name: success}."""
        results = {}
        for name in symbol_names:
            results[name] = self.subscribe(name)
        return results

    def unsubscribe(self, symbol_name: str) -> bool:
        """Unsubscribe from market data for a symbol."""
        symbol_id = self._resolve_symbol_id(symbol_name)
        if symbol_id is None:
            return False

        return self._send_unsubscribe(symbol_id)

    def get_tick(self, symbol_name: str) -> Optional[Tick]:
        """Get the latest tick for a symbol."""
        symbol_id = self._resolve_symbol_id(symbol_name)
        if symbol_id is None:
            return None
        with self._lock:
            return self._ticks.get(symbol_id)

    def get_tick_by_id(self, symbol_id: int) -> Optional[Tick]:
        """Get the latest tick by numeric symbol ID."""
        with self._lock:
            return self._ticks.get(symbol_id)

    def get_all_ticks(self) -> Dict[str, Tick]:
        """Get latest ticks for all subscribed symbols."""
        with self._lock:
            return {
                self._symbols[sid].name: tick
                for sid, tick in self._ticks.items()
                if sid in self._symbols
            }

    def on_tick(self, callback: Callable[[Tick], None]):
        """Register a callback for new ticks."""
        self._tick_callbacks.append(callback)

    def on_error(self, callback: Callable[[str], None]):
        """Register a callback for errors."""
        self._error_callbacks.append(callback)

    def _resolve_symbol_id(self, symbol_name: str) -> Optional[int]:
        """Resolve symbol name to numeric ID."""
        with self._lock:
            return self._name_to_id.get(symbol_name)

    def _send_subscription(self, symbol_id: int) -> bool:
        """Send MarketDataRequest to subscribe."""
        if not self._client:
            return False

        req_id = f"SUB_{self._next_req_id:04d}"
        self._next_req_id += 1

        msg = FIXMessage(msg_type="V")
        msg.set_field(self.TAG_SYMBOL, str(symbol_id))
        # Body fields
        msg.set_body_field(self.TAG_MD_REQ_ID, req_id)
        msg.set_body_field(self.TAG_SUBSCRIPTION_TYPE, "1")  # Snapshot + Updates
        msg.set_body_field(self.TAG_MARKET_DEPTH, "1")  # Top of book
        msg.set_body_field(self.TAG_MD_UPDATE_TYPE, "1")  # Full refresh
        msg.set_body_field(self.TAG_NO_MD_ENTRY_TYPES, "2")
        msg.set_body_field(self.TAG_MD_ENTRY_TYPE, "0")  # Bid
        msg.set_body_field(self.TAG_MD_ENTRY_TYPE, "1")  # Ask
        msg.set_body_field(self.TAG_NO_RELATED_SYM, "1")

        success = self._client._send_message(msg)
        if success:
            with self._lock:
                self._subscriptions.add(symbol_id)
            logger.info(f"Subscribed to symbol {symbol_id} (req {req_id})")
        return success

    def _send_unsubscribe(self, symbol_id: int) -> bool:
        """Send MarketDataRequest to unsubscribe (SubscriptionRequestType=2)."""
        if not self._client:
            return False

        req_id = f"UNSUB_{self._next_req_id:04d}"
        self._next_req_id += 1

        msg = FIXMessage(msg_type="V")
        msg.set_field(self.TAG_SYMBOL, str(symbol_id))
        msg.set_body_field(self.TAG_MD_REQ_ID, req_id)
        msg.set_body_field(self.TAG_SUBSCRIPTION_TYPE, "2")  # Disable previous
        msg.set_body_field(self.TAG_MARKET_DEPTH, "1")

        success = self._client._send_message(msg)
        if success:
            with self._lock:
                self._subscriptions.discard(symbol_id)
            logger.info(f"Unsubscribed from symbol {symbol_id}")
        return success

    def _on_logon(self, msg):
        """Auto-subscribe to default forex pairs after logon."""
        logger.info("Market data feed logged in, subscribing to forex pairs")
        for name in FOREX_PAIRS:
            if name in self._name_to_id:
                self.subscribe(name)

    def _on_logout(self, msg):
        reason = msg.get_field(58) or "unknown"
        logger.warning(f"Market data feed logged out: {reason}")
        with self._lock:
            self._subscriptions.clear()
            self._ticks.clear()

    def _on_heartbeat(self, msg):
        pass  # Heartbeat is handled by FIXClient

    def _handle_market_data_snapshot(self, msg: FIXMessage):
        """Parse MarketDataSnapshot (35=W) and update tick cache."""
        try:
            symbol_id = int(msg.get_field(55) or 0)
            timestamp_str = msg.get_field(52)
            if timestamp_str:
                timestamp = datetime.strptime(timestamp_str, "%Y%m%d-%H:%M:%S.%f").replace(
                    tzinfo=timezone.utc
                )
            else:
                timestamp = datetime.now(timezone.utc)

            # Parse repeating group entries (269=MDEntryType, 270=MDEntryPx)
            bid = None
            ask = None

            # The raw fields from FIXClient contain all fields in a flat dict.
            # For repeating groups, we need to iterate by entry.
            # FIXClient stores all fields in msg.fields. We need the raw wire data.
            # Since our FIXMessage stores all fields flat, we extract from the raw response.
            # The response handler gets a parsed message where repeating groups are flattened.
            # We handle this by looking at the raw fields dict.

            # Collect all MDEntryType (269) and MDEntryPx (270) values
            # In the flat dict, repeated tags overwrite. We need raw wire data.
            # Let's use a different approach: extract from the message's raw data.
            # For now, use the get_all_fields method which returns lists for repeated tags.
            all_fields = self._extract_repeating_fields(msg)

            for entry_type, entry_px in all_fields.get(269, []), all_fields.get(270, []):
                pass  # This won't work well with flat dict

            # Simpler approach: parse the bid/ask from the raw response string
            # The FIXClient stores the raw message data - but we don't have it in msg.
            # We need to modify FIXClient to pass raw data or parse repeating groups properly.

            # For now, use a workaround: the FIXClient._process_buffer calls _handle_message
            # with a parsed FIXMessage. Since repeating groups have the same tag numbers,
            # the last value wins in the flat dict. We need raw wire data.

            # Temporary workaround: override _handle_message to pass raw data
            # This will be fixed in the proper implementation below.
            logger.debug(f"Market data snapshot for symbol {symbol_id}")

        except Exception as e:
            logger.error(f"Error parsing market data snapshot: {e}")

    def _extract_repeating_fields(self, msg: FIXMessage) -> Dict[int, list]:
        """Extract fields preserving repeats (not available with flat dict)."""
        # This is a limitation of the current FIXMessage design.
        # We'll fix this by enhancing the message handler.
        return {}

    # Override the message handling approach:
    # Instead of using FIXClient's _handle_message callback system,
    # we'll hook into _process_buffer directly via a subclass approach.
    # For now, we register a custom handler that receives raw wire data.


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
