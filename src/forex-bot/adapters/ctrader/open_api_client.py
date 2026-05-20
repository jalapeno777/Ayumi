"""cTrader Open API client for fetching historical data.

Uses the ctrader_open_api package (Twisted-based protobuf client) to:
- Authenticate via OAuth (app auth + account auth)
- Fetch symbol lists
- Download historical trendbars (OHLCV)

The Twisted reactor runs in a background thread so all public methods
are synchronous from the caller's perspective.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from ctrader_open_api.client import Client
from ctrader_open_api.endpoints import EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAAccountAuthReq,
    ProtoOASymbolsListReq,
    ProtoOASymbolByIdReq,
    ProtoOAGetTrendbarsReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
from ctrader_open_api.protobuf import Protobuf
from ctrader_open_api.tcpProtocol import TcpProtocol
from twisted.internet import reactor
from .reactor_manager import ReactorManager

logger = logging.getLogger(__name__)

# Period string → ProtoOATrendbarPeriod enum value
PERIOD_MAP = {
    "M1":  ProtoOATrendbarPeriod.M1,
    "M5":  ProtoOATrendbarPeriod.M5,
    "M15": ProtoOATrendbarPeriod.M15,
    "M30": ProtoOATrendbarPeriod.M30,
    "H1":  ProtoOATrendbarPeriod.H1,
    "H4":  ProtoOATrendbarPeriod.H4,
    "D1":  ProtoOATrendbarPeriod.D1,
    "W1":  ProtoOATrendbarPeriod.W1,
}

# Period string → bar duration in seconds
PERIOD_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800,
}

# Max bars per single API request per period
MAX_BARS = {
    "M1": 5760, "M5": 5760, "M15": 5760,
    "H1": 5760, "H4": 5760, "D1": 5760,
}


class CTraderOpenApiClient:
    """Synchronous wrapper around cTrader's Twisted Open API client."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        account_id: int,
        access_token: str | None = None,
        host: str | None = None,
        port: int = 5035,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._account_id = account_id
        self._access_token = access_token
        self._host = host or EndPoints.PROTOBUF_DEMO_HOST
        self._port = port
        self._client: Client | None = None
        self._reactor_thread: threading.Thread | None = None
        self._connected = False
        self._symbol_digits_cache: dict[int, int] = {}

    # --- Connection lifecycle ---

    def connect(self) -> bool:
        """Connect to cTrader Open API, authenticate, and return True on success."""
        if self._connected:
            return True

        # Ensure shared reactor is running
        ReactorManager().ensure_running()
        time.sleep(0.3)  # brief pause for reactor readiness

        self._client = Client(self._host, self._port, TcpProtocol)

        # Wait for TCP connection
        connected_event = threading.Event()

        def on_connected(_):
            connected_event.set()

        self._client.setConnectedCallback(on_connected)
        self._client.startService()

        if not connected_event.wait(timeout=15):
            logger.error("Timeout waiting for TCP connection to cTrader")
            return False

        # Step 1: Application auth
        try:
            app_auth_res = self._send_and_wait(
                ProtoOAApplicationAuthReq(
                    clientId=self._client_id,
                    clientSecret=self._client_secret,
                ),
                timeout=10,
            )
            if app_auth_res is None:
                logger.error("Application auth failed — no response")
                return False
        except Exception as e:
            logger.error(f"Application auth failed: {e}")
            return False

        # Step 2: Account auth
        token = self._access_token or ""
        try:
            account_auth_res = self._send_and_wait(
                ProtoOAAccountAuthReq(
                    ctidTraderAccountId=self._account_id,
                    accessToken=token,
                ),
                timeout=10,
            )
            if account_auth_res is None:
                logger.error("Account auth failed — no response")
                return False
        except Exception as e:
            logger.error(f"Account auth failed: {e}")
            return False

        self._connected = True
        logger.info("cTrader Open API connected and authenticated")
        return True

    def disconnect(self):
        """Disconnect from the API. Stops the TCP client but NOT the reactor."""
        if self._client:
            try:
                self._client.stopService()
            except Exception:
                pass
        self._connected = False
        logger.info("cTrader Open API disconnected")

    def _send_and_wait(self, message, timeout: float = 10):
        """Send a protobuf message and wait for the response synchronously."""
        if not self._client or not self._client.isConnected:
            raise RuntimeError("Not connected")

        event = threading.Event()
        result_holder = [None]

        def on_response(client, msg):
            event.set()

        self._client.setMessageReceivedCallback(on_response)

        # Send via the Twisted thread
        client_msg_id = f"{id(message)}_{time.monotonic()}"
        deferred = self._client.send(message, clientMsgId=client_msg_id, responseTimeoutInSeconds=timeout)

        def capture_result(proto_res):
            result_holder[0] = proto_res
            event.set()

        def capture_error(failure):
            logger.error(f"API request failed: {failure}")
            event.set()

        from twisted.internet import threads
        reactor.callFromThread(
            lambda: deferred.addCallbacks(capture_result, capture_error)
        )

        if not event.wait(timeout=timeout + 5):
            return None

        return result_holder[0]

    # --- Public API ---

    def get_all_symbols(self) -> list[dict]:
        """Fetch all available symbols via ProtoOASymbolsListReq.

        Returns list of dicts with: symbol_id, name, description, digits,
        pip_size, category, enabled.
        """
        if not self._connected:
            raise RuntimeError("Not connected")

        response = self._send_and_wait(
            ProtoOASymbolsListReq(
                ctidTraderAccountId=self._account_id,
                includeArchivedSymbols=False,
            ),
            timeout=15,
        )

        if response is None:
            logger.error("No response for SymbolsListReq")
            return []

        # Extract payload
        payload = Protobuf.extract(response)
        symbols = []

        for s in payload.symbol:
            pip_position = getattr(s, "pipPosition", None) or getattr(s, "pipPositionSize", None) or 4
            pip_size = 10 ** (-pip_position)
            symbols.append({
                "symbol_id": s.symbolId,
                "name": s.symbolName,
                "description": getattr(s, "description", ""),
                "digits": getattr(s, "digits", None) or 5,
                "pip_size": pip_size,
                "enabled": getattr(s, "enabled", True),
                "base_asset_id": getattr(s, "baseAssetId", 0),
                "quote_asset_id": getattr(s, "quoteAssetId", 0),
                "category_id": s.symbolCategoryId,
            })

        logger.info(f"Fetched {len(symbols)} symbols")
        return symbols

    def get_symbol_details(self, symbol_id: int) -> dict | None:
        """Get details for a specific symbol via ProtoOASymbolByIdReq."""
        if not self._connected:
            raise RuntimeError("Not connected")

        response = self._send_and_wait(
            ProtoOASymbolByIdReq(
                ctidTraderAccountId=self._account_id,
                symbolId=[symbol_id],
            ),
            timeout=10,
        )

        if response is None:
            return None

        payload = Protobuf.extract(response)
        msg_type = getattr(payload, 'payloadType', None)
        if msg_type == 2142:  # ProtoOAErrorRes — symbol not found or auth error
            error_code = getattr(payload, 'errorCode', 'UNKNOWN')
            description = getattr(payload, 'description', '')
            logger.warning(
                "Symbol details error for symbol_id=%d: %s — %s",
                symbol_id, error_code, description,
            )
            return None
        if not hasattr(payload, 'symbol') or not payload.symbol:
            return None

        s = payload.symbol[0]
        return {
            "symbol_id": s.symbolId,
            "digits": s.digits,
            "pip_position": s.pipPosition,
            "pip_size": 10 ** (-s.pipPosition) if s.pipPosition else 0.0001,
            "enable_short_selling": s.enableShortSelling,
            "swap_long": s.swapLong,
            "swap_short": s.swapShort,
            "max_volume": s.maxVolume,
            "min_volume": s.minVolume,
            "step_volume": s.stepVolume,
            "lot_size": s.lotSize,
        }

    def get_trendbars(
        self,
        symbol_id: int,
        period: str,
        from_ts: int,
        to_ts: int,
        max_bars: int | None = None,
    ) -> list[dict]:
        """Fetch historical OHLCV bars via ProtoOAGetTrendbarsReq.

        Args:
            symbol_id: cTrader numeric symbol ID
            period: "M1", "M5", "M15", "M30", "H1", "H4", "D1"
            from_ts: Unix timestamp in milliseconds
            to_ts: Unix timestamp in milliseconds
            max_bars: Max bars to request (default: period-specific max)

        Returns list of dicts with: timestamp, open, high, low, close, volume
        """
        if not self._connected:
            raise RuntimeError("Not connected")

        if period not in PERIOD_MAP:
            raise ValueError(f"Invalid period '{period}'. Must be one of {list(PERIOD_MAP.keys())}")

        if max_bars is None:
            max_bars = MAX_BARS.get(period, 5760)

        period_enum = PERIOD_MAP[period]

        # Use cached symbol digits for rounding precision
        if symbol_id not in self._symbol_digits_cache:
            details = self.get_symbol_details(symbol_id)
            if details:
                self._symbol_digits_cache[symbol_id] = details["digits"]
            else:
                self._symbol_digits_cache[symbol_id] = 5  # default
        digits = self._symbol_digits_cache[symbol_id]

        # cTrader encodes all raw prices with 5 decimal places (int units of 1e-5)
        divisor = 100000.0

        response = self._send_and_wait(
            ProtoOAGetTrendbarsReq(
                ctidTraderAccountId=self._account_id,
                fromTimestamp=from_ts,
                toTimestamp=to_ts,
                period=period_enum,
                symbolId=symbol_id,
                count=max_bars,
            ),
            timeout=30,
        )

        if response is None:
            logger.warning(f"No trendbars response for symbol {symbol_id}")
            return []

        payload = Protobuf.extract(response)
        trendbars = getattr(payload, 'trendbar', None)
        if not trendbars:
            logger.warning(f"No trendbar data in response for symbol {symbol_id}")
            return []

        bars = []
        for tb in trendbars:
            # cTrader returns relative prices:
            # low is the base, divided by 100000
            # open/high/close are low + delta, also divided by 100000
            low_raw = tb.low
            open_raw = low_raw + tb.deltaOpen
            high_raw = low_raw + tb.deltaHigh
            close_raw = low_raw + tb.deltaClose

            # divisor is set above (always 100000.0 for cTrader raw encoding)

            bars.append({
                "timestamp": tb.utcTimestampInMinutes * 60 * 1000,  # to ms
                "open": round(open_raw / divisor, digits),
                "high": round(high_raw / divisor, digits),
                "low": round(low_raw / divisor, digits),
                "close": round(close_raw / divisor, digits),
                "volume": tb.volume,
            })

        return bars


def calculate_chunks(
    period: str,
    start_ms: int,
    end_ms: int,
) -> list[tuple[int, int]]:
    """Calculate chunk boundaries for a date range.

    Returns list of (from_ms, to_ms) tuples, each within the max bars
    constraint for the given period.
    """
    if period not in PERIOD_SECONDS:
        raise ValueError(f"Invalid period '{period}'")

    period_sec = PERIOD_SECONDS[period]
    max_bars = MAX_BARS.get(period, 5760)
    # Max timespan per chunk in milliseconds
    chunk_ms = max_bars * period_sec * 1000

    chunks = []
    current = start_ms
    while current < end_ms:
        chunk_end = min(current + chunk_ms, end_ms)
        chunks.append((current, chunk_end))
        current = chunk_end

    return chunks
