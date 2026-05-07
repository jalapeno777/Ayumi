"""Shared market data types for cTrader adapters.

This module provides the core data types (Tick, SymbolInfo) used by both
OpenApiSpotFeed (Open API streaming) and LiveMarketDataFeed (FIX protocol).
The FIX-specific MarketDataClient/LiveMarketDataFeed are stubbed here to
avoid import errors when only OpenApiSpotFeed is used.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ─── Core shared types ────────────────────────────────────────────────────────

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
# Auto-populated from live data, but we seed common ones.
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


# ─── FIX-specific stubs ─────────────────────────────────────────────────────────
# These are only used when use_openapi_feed=False (FIX mode, deprecated).
# Importing them here would pull in api_client which is archived.
# Stub implementations to satisfy imports without pulling in FIX dependency.

class LiveMarketDataFeed:
    """DEPRECATED: FIX-mode live feed. Use OpenApiSpotFeed instead."""

    def __init__(self, credentials):
        raise NotImplementedError(
            "LiveMarketDataFeed (FIX mode) is deprecated. "
            "Set use_openapi_feed=True in ForwardTestConfig."
        )

    def on_tick(self, handler):
        pass

    def start(self, auto_subscribe=None):
        raise NotImplementedError("FIX mode is deprecated")

    def stop(self):
        pass
