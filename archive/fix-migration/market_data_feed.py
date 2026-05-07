"""cTrader FIX Market Data Feed.

Provides live price streaming from cTrader via the QUOTE connection (port 5211/SSL).

Protocol notes:
- MarketDataRequest (35=V) requires SubscriptionRequestType=1 (snapshot + updates)
- cTrader does NOT support snapshot-only (263=0)
- MarketDepth=0 (full book), MDUpdateType=0 (full refresh per tick)
- Symbols are identified by numeric ID (tag 55), not string (e.g. 1 = EUR/USD)
- MDEntryType 269=0 (bid), 269=1 (ask)
- MDEntryPx (270) contains the price
- Responses are MarketDataSnapshot (35=W) with repeating group entries
- Incremental updates arrive as MarketDataIncrementalRefresh (35=X)
  with MDUpdateAction (tag 279): 0=new, 1=change, 2=delete
- SenderSubID must be "QUOTE" for quote-only connections (port 5211)
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
DEFAULT_SYMBOLS: dict[int, str] = {
    1: "EUR/USD",
    2: "GBP/USD",
    3: "USD/JPY",
    4: "USD/CHF",
    5: "AUD/USD",
    6: "USD/CAD",
    7: "NZD/USD",
    31: "XAU/USD",
}

# Common forex symbols we care about for trading
FOREX_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD"]


class MarketDataClient(FIXClient):
    """Extended FIXClient that properly handles MarketDataSnapshot repeating groups."""

    def __init__(self, credentials):
        super().__init__(credentials)
        self._md_handlers: list[Callable] = []

    def register_md_handler(self, handler: Callable):
        self._md_handlers.append(handler)

    def _handle_message(self, msg: FIXMessage):
        msg_type = msg.msg_type

        if msg_type in ("W", "X"):  # MarketDataSnapshot or MarketDataIncrementalRefresh
            for handler in self._md_handlers:
                try:
                    handler(msg)
                except Exception as e:
                    logger.error(f"MD handler error: {e}")
            return

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
        self._client: MarketDataClient | None = None
        self._running = False
        self._ticks: dict[int, Tick] = {}
        self._symbols: dict[int, SymbolInfo] = {
            sid: SymbolInfo(symbol_id=sid, name=name)
            for sid, name in DEFAULT_SYMBOLS.items()
        }
        self._name_to_id: dict[str, int] = {v: k for k, v in DEFAULT_SYMBOLS.items()}
        self._id_to_name: dict[int, str] = {k: v for k, v in DEFAULT_SYMBOLS.items()}
        self._subscriptions: set[int] = set()
        self._lock = threading.Lock()
        self._tick_callbacks: list[Callable[[Tick], None]] = []
        self._order_book: dict[int, dict[str, dict[str, float]]] = {}
        self._next_req_id = 1

    @property
    def symbols(self) -> dict[int, SymbolInfo]:
        with self._lock:
            return dict(self._symbols)

    @property
    def is_running(self) -> bool:
        """True only if the feed was started AND the underlying FIX session is alive."""
        if self._client is None:
            return False
        return self._running and self._client.is_connected

    @property
    def name_to_id(self) -> dict[str, int]:
        with self._lock:
            return dict(self._name_to_id)

    def start(self, auto_subscribe: list[str] | None = None) -> bool:
        """Connect and optionally auto-subscribe to symbols."""
        if self._running:
            return True

        self._client = MarketDataClient(self._credentials)
        self._client.register_md_handler(self._on_snapshot)
        self._client.register_md_handler(self._on_incremental)
        self._client.register_callback(
            "on_logon", lambda m: logger.info("MD feed logged in")
        )

        if not self._client.connect():
            logger.error("Failed to connect MD feed")
            return False


        self._running = True

        if auto_subscribe is None:
            auto_subscribe = FOREX_PAIRS

        for name in auto_subscribe:
            self.subscribe(name)

        logger.info(
            f"Market data feed started (auto-subscribed to {len(auto_subscribe)} pairs)"
        )
        return True

    def stop(self):
        self._running = False
        if self._client:
            self._client.disconnect()
        with self._lock:
            self._subscriptions.clear()
            self._ticks.clear()
            self._order_book.clear()

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
        msg.set_body_field(self.TAG_MD_REQ_ID, req_id)
        msg.set_body_field(self.TAG_SUBSCRIPTION_TYPE, "1")
        msg.set_body_field(self.TAG_MARKET_DEPTH, "0")
        msg.set_body_field(self.TAG_MD_UPDATE_TYPE, "0")
        msg.set_body_field(self.TAG_NO_MD_ENTRY_TYPES, "2")
        msg.set_body_field(self.TAG_MD_ENTRY_TYPE, "0")
        msg.set_body_field(self.TAG_MD_ENTRY_TYPE, "1")
        msg.set_body_field(self.TAG_NO_RELATED_SYM, "1")
        msg.set_body_field(self.TAG_SYMBOL, str(symbol_id))

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

    def get_tick(self, symbol_name: str) -> Tick | None:
        symbol_id = self._resolve_id(symbol_name)
        if symbol_id is None:
            return None
        with self._lock:
            return self._ticks.get(symbol_id)

    def get_tick_by_id(self, symbol_id: int) -> Tick | None:
        with self._lock:
            return self._ticks.get(symbol_id)

    def get_all_ticks(self) -> dict[str, Tick]:
        with self._lock:
            return {
                self._symbols[sid].name: tick
                for sid, tick in self._ticks.items()
                if sid in self._symbols
            }

    def get_spread(self, symbol_name: str) -> float | None:
        tick = self.get_tick(symbol_name)
        return tick.spread if tick else None

    def on_tick(self, callback: Callable[[Tick], None]):
        self._tick_callbacks.append(callback)

    def _resolve_id(self, symbol_name: str) -> int | None:
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
        if msg.msg_type != "W":
            return

        # Parse from raw data stored during buffer processing
        symbol_id = int(msg.get_field(55) or 0)

        # Use the _raw_fields attribute if available (set during parsing)
        raw_fields = getattr(msg, "_raw_fields", None)
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
            last_269_value: str | None = None  # Track last seen MDEntryType
            for tag, value in raw_fields:
                if tag == 269:
                    last_269_value = value
                elif tag == 270 and last_269_value is not None:
                    px = float(value)
                    if last_269_value == "0":
                        bid = px
                    elif last_269_value == "1":
                        ask = px
                    last_269_value = None  # reset for next entry

        if bid is None or ask is None:
            logger.debug(
                f"Incomplete tick for symbol {symbol_id}: bid={bid}, ask={ask}"
            )
            return

        timestamp_str = msg.get_field(52)
        if timestamp_str:
            try:
                timestamp = datetime.strptime(
                    timestamp_str, "%Y%m%d-%H:%M:%S.%f"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                timestamp = datetime.strptime(timestamp_str, "%Y%m%d-%H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
        else:
            timestamp = datetime.now(timezone.utc)

        tick = Tick(symbol_id=symbol_id, bid=bid, ask=ask, timestamp=timestamp)

        with self._lock:
            self._ticks[symbol_id] = tick
            # Reset order book on snapshot — snapshot IS the authoritative state.
            # Incremental entries will rebuild the book from here.
            # Use sentinel keys to avoid collision with order_id keys from incrementals.
            self._order_book[symbol_id] = {
                "bids": {"__snapshot__": bid},
                "asks": {"__snapshot__": ask},
            }

        for cb in self._tick_callbacks:
            try:
                cb(tick)
            except Exception as e:
                logger.error(f"Tick callback error: {e}")

    def _on_incremental(self, msg: FIXMessage):
        """Handle MarketDataIncrementalRefresh (35=X).

        Maintains a local order book keyed by OrderID (tag 278) to support
        top-of-book extraction across new, change, and delete actions.

        MDUpdateAction (tag 279): 0=new, 1=change, 2=delete
        MDEntryType (tag 269): 0=bid, 1=ask
        OrderID (tag 278): identifies the order
        MDEntryPx (tag 270): price (absent for delete)
        Symbol (tag 55): repeated per entry in incremental messages

        cTrader incremental messages can contain entries for multiple symbols.
        Each entry carries its own tag 55. We route each entry to the correct
        per-symbol order book to prevent cross-symbol contamination.
        """
        if msg.msg_type != "X":
            return

        raw_fields = getattr(msg, "_raw_fields", None)
        if raw_fields is None:
            return

        msg_level_symbol_id = int(msg.get_field(55) or 0)

        entries: list[dict] = []
        current_entry: dict | None = None
        last_269_value: str | None = None  # Track last seen MDEntryType
        for tag, value in raw_fields:
            if tag == 279:
                if current_entry is not None:
                    entries.append(current_entry)
                current_entry = {"action": value}
                last_269_value = None  # Reset for new entry
            elif current_entry is not None:
                if tag == 269:
                    current_entry["entry_type"] = value
                    last_269_value = value
                elif tag == 270:
                    try:
                        price = float(value)
                        # Use the last seen entry_type (269)
                        if last_269_value is not None:
                            current_entry["entry_type"] = last_269_value
                            current_entry["price"] = price
                    except ValueError:
                        pass
                elif tag == 278:
                    current_entry["order_id"] = value
                elif tag == 55:
                    try:
                        current_entry["symbol_id"] = int(value)
                    except ValueError:
                        pass
        if current_entry is not None:
            entries.append(current_entry)

        if not entries:
            return


        timestamp_str = msg.get_field(52)
        if timestamp_str:
            try:
                timestamp = datetime.strptime(
                    timestamp_str, "%Y%m%d-%H:%M:%S.%f"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                timestamp = datetime.strptime(timestamp_str, "%Y%m%d-%H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
        else:
            timestamp = datetime.now(timezone.utc)

        updated_symbols: set[int] = set()

        with self._lock:
            for entry in entries:
                action = entry.get("action")
                entry_type = entry.get("entry_type")
                order_id = entry.get("order_id")
                price = entry.get("price")

                if not order_id or not entry_type:
                    logger.debug(
                        "Skipping order book entry missing order_id or entry_type"
                    )
                    continue

                entry_symbol = entry.get("symbol_id", 0)
                if entry_symbol == 0:
                    entry_symbol = msg_level_symbol_id
                if entry_symbol == 0:
                    continue

                if entry_symbol not in self._order_book:
                    self._order_book[entry_symbol] = {"bids": {}, "asks": {}}
                book = self._order_book[entry_symbol]

                side = (
                    "bids"
                    if entry_type == "0"
                    else "asks"
                    if entry_type == "1"
                    else None
                )
                if side is None:
                    continue

                if action in ("0", "1"):
                    if price is not None:
                        book[side][order_id] = price
                        # Clear snapshot sentinel once real entries arrive
                        book[side].pop("__snapshot__", None)
                elif action == "2":
                    book[side].pop(order_id, None)
                    book[side].pop("__snapshot__", None)

                updated_symbols.add(entry_symbol)

        for sym_id in updated_symbols:
            with self._lock:
                book = self._order_book.get(sym_id)
                if not book:
                    continue

                bids = book["bids"]
                asks = book["asks"]
                if not bids or not asks:
                    continue

                best_bid = max(bids.values())
                best_ask = min(asks.values())


                if best_bid > best_ask + 1e-7:
                    logger.debug(
                        f"Inverted spread for symbol {sym_id}: "
                        f"bid={best_bid} >= ask={best_ask}, skipping tick"
                    )
                    continue

                tick = Tick(
                    symbol_id=sym_id,
                    bid=best_bid,
                    ask=best_ask,
                    timestamp=timestamp,
                )
                self._ticks[sym_id] = tick

            for cb in self._tick_callbacks:
                try:
                    cb(tick)
                except Exception as e:
                    logger.error(f"Tick callback error: {e}")
