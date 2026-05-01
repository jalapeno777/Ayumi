"""Symbol discovery module for cTrader via FIX protocol.

Discovers available trading symbols using SecurityListRequest (FIX msgType 'x')
with a subscription-probe fallback. Results are cached locally.
"""

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .api_client import FIXClient, FIXMessage

logger = logging.getLogger(__name__)

# --- Symbol categories ---

FOREX_MAJORS = {"EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD"}

MINOR_CURRENCIES = {"EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"}

EXOTIC_QUOTE = {"TRY", "ZAR", "MXN", "SGD", "HKD", "NOK", "SEK", "DKK", "CZK", "PLN", "HUF", "THB", "CNY"}

COMMODITY_PREFIXES = {"XAU", "XAG", "XPT", "XPD"}
COMMODITY_NAMES = {"UKOIL", "USOIL", "OIL", "COPPER"}

INDEX_NAMES = {"US30", "NAS100", "SPX500", "UK100", "DE30", "JP225", "AUS200",
               "US500", "US100", "FRA40", "ESP35", "EU50", "US2000"}

CRYPTO_PREFIXES = {"BTC", "ETH", "LTC", "XRP", "BCH", "EOS", "BNB", "ADA", "SOL", "DOGE"}


@dataclass
class SymbolInfo:
    """Metadata about a tradable symbol."""
    symbol_id: int
    name: str
    pip_size: float = 0.0001
    digits: int = 5
    description: str = ""
    currency: str = ""
    category: str = ""  # auto-detected
    contract_multiplier: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SymbolInfo":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def classify_symbol(name: str) -> str:
    """Classify a symbol name into a category."""
    stripped = name.replace("/", "").replace(" ", "").upper()

    # Check index first (no slash pattern)
    if stripped in INDEX_NAMES or any(stripped.startswith(idx) for idx in ["US30", "NAS100", "SPX500", "UK100", "DE30", "JP225", "AUS200"]):
        return "index"

    # Check commodity
    if stripped in COMMODITY_NAMES:
        return "commodity"
    for prefix in COMMODITY_PREFIXES:
        if stripped.startswith(prefix):
            return "commodity"

    # Check crypto
    for prefix in CRYPTO_PREFIXES:
        if stripped.startswith(prefix):
            return "crypto"

    # Must be forex-like — need a slash or recognized pair pattern
    if "/" in name:
        base, quote = name.split("/", 1)
        base = base.upper().strip()
        quote = quote.upper().strip()

        pair = f"{base}/{quote}"
        if pair in FOREX_MAJORS:
            return "forex_major"
        if base in MINOR_CURRENCIES and quote in MINOR_CURRENCIES:
            return "forex_minor"
        if quote in EXOTIC_QUOTE or base in EXOTIC_QUOTE:
            return "forex_exotic"

    return "other"


# --- Probe patterns ---

DEFAULT_PROBE_PATTERNS = [
    # Forex majors
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
    # Forex minors
    "EUR/GBP", "EUR/JPY", "GBP/JPY", "AUD/JPY", "EUR/AUD", "GBP/AUD", "EUR/CAD",
    "GBP/CAD", "AUD/NZD", "NZD/JPY", "CHF/JPY",
    # Forex exotics
    "USD/TRY", "USD/ZAR", "USD/MXN", "USD/SGD", "USD/HKD", "USD/NOK", "USD/SEK",
    "EUR/TRY", "EUR/NOK", "EUR/SEK",
    # Commodities
    "XAU/USD", "XAG/USD", "XPT/USD",
    # Indices
    "US30/USD", "NAS100/USD", "SPX500/USD",
    # Crypto
    "BTC/USD", "ETH/USD",
]


class _DiscoveryClient(FIXClient):
    """FIXClient subclass that captures SecurityList responses."""

    def __init__(self, credentials):
        super().__init__(credentials)
        self._security_list_response: dict[int, SymbolInfo] = {}
        self._security_list_event = threading.Event()
        self._reject_received = False
        self._probe_ticks: dict[int, tuple] = {}  # symbol_id -> (bid, ask)
        self._probe_event = threading.Event()

    def _handle_message(self, msg: FIXMessage):
        msg_type = msg.msg_type

        # Capture SecurityList response (msgType='y')
        if msg_type == "y":
            self._parse_security_list(msg)
            return

        # Capture MarketDataSnapshot for probe ticks
        if msg_type == "W":
            self._parse_probe_tick(msg)
            return

        # Track rejects
        if msg_type == "3":
            reject_code = int(msg.get_field(371) or 0)
            logger.warning(f"SecurityListRequest rejected: code={reject_code} text={msg.get_field(58)}")
            self._reject_received = True
            self._security_list_event.set()

        super()._handle_message(msg)

    def _parse_security_list(self, msg: FIXMessage):
        """Parse SecurityList (msgType='y') repeating group."""
        raw_fields = getattr(msg, "_raw_fields", [])
        if not raw_fields:
            self._security_list_event.set()
            return

        entries: list[dict] = []
        current: dict | None = None
        for tag, value in raw_fields:
            if tag == 55:  # Symbol — starts a new entry
                if current is not None:
                    entries.append(current)
                current = {"name": value}
            elif current is not None:
                if tag == 65:
                    current["symbol_sfx"] = value
                elif tag == 107:
                    current["description"] = value
                elif tag == 15:
                    current["currency"] = value
                elif tag == 462:
                    current["contract_multiplier"] = value

        if current is not None:
            entries.append(current)

        # Assign IDs — cTrader may send numeric IDs or string names in tag 55
        for i, entry in enumerate(entries):
            name = entry.get("name", f"UNKNOWN_{i}")
            symbol_id = i + 1  # default sequential ID
            try:
                # If tag 55 is numeric, use it as ID and look up the name
                maybe_id = int(name)
                symbol_id = maybe_id
                # The name might be in SecurityDesc (tag 107)
                if "description" in entry:
                    name = entry["description"]
            except ValueError:
                symbol_id = hash(name) % 100000  # deterministic hash-based ID

            category = classify_symbol(name)
            pip_size = 0.0001
            if "JPY" in name.upper():
                pip_size = 0.01
            elif "XAU" in name.upper():
                pip_size = 0.01
            elif any(idx in name.upper() for idx in INDEX_NAMES):
                pip_size = 0.1

            digits = 5
            if pip_size >= 0.01:
                digits = 3 if pip_size < 0.1 else 1

            info = SymbolInfo(
                symbol_id=symbol_id,
                name=name,
                pip_size=pip_size,
                digits=digits,
                description=entry.get("description", ""),
                currency=entry.get("currency", ""),
                category=category,
                contract_multiplier=float(entry.get("contract_multiplier", 1)),
            )
            self._security_list_response[symbol_id] = info

        self._security_list_event.set()

    def _parse_probe_tick(self, msg: FIXMessage):
        """Parse probe tick from MarketDataSnapshot."""
        symbol_id = int(msg.get_field(55) or 0)
        raw_fields = getattr(msg, "_raw_fields", [])
        if not raw_fields:
            return

        bid = None
        ask = None
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
                current_type = None

        if bid is not None and ask is not None:
            self._probe_ticks[symbol_id] = (bid, ask)
            self._probe_event.set()


class SymbolDiscovery:
    """Discovers available trading symbols from cTrader via FIX protocol.

    Two methods:
    1. SecurityListRequest (msgType='x') — request full symbol list
    2. Manual fallback — subscription probe of known patterns

    Results are cached locally for offline use.
    """

    TAG_SECURITY_REQ_ID = 320
    TAG_SECURITY_LIST_REQ_TYPE = 321
    TAG_SYMBOL = 55
    TAG_NO_RELATED_SYM = 146

    def __init__(self, credentials, cache_path: str = "data/ctrader_symbols.json"):
        self._credentials = credentials
        self._cache_path = Path(cache_path)
        self._symbols: dict[int, SymbolInfo] = {}
        # Load cache on init
        self._symbols = self.load_cache()

    def discover_via_security_list(self, timeout: float = 10.0) -> dict[int, SymbolInfo]:
        """Send SecurityListRequest to cTrader and parse response."""
        client = _DiscoveryClient(self._credentials)

        if not client.connect():
            logger.error("Failed to connect for SecurityListRequest")
            return {}

        try:
            req_id = f"SYM_DISC_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

            msg = FIXMessage(msg_type="x")  # SecurityListRequest
            msg.set_body_field(self.TAG_SECURITY_REQ_ID, req_id)
            msg.set_body_field(self.TAG_SECURITY_LIST_REQ_TYPE, "0")  # All symbols
            msg.set_body_field(self.TAG_NO_RELATED_SYM, "0")  # No symbol filter

            client._send_message(msg)
            logger.info("SecurityListRequest sent, waiting for response...")

            if client._security_list_event.wait(timeout=timeout):
                if client._security_list_response:
                    logger.info(f"Received {len(client._security_list_response)} symbols via SecurityList")
                    self._symbols.update(client._security_list_response)
                    self.save_cache()
                    return dict(client._security_list_response)
                elif client._reject_received:
                    logger.warning("SecurityListRequest was rejected by server")
                else:
                    logger.warning("SecurityList response was empty")
            else:
                logger.warning("Timeout waiting for SecurityList response")
        finally:
            client.disconnect()

        return {}

    def discover_via_subscription_probe(
        self,
        symbol_patterns: list[str] | None = None,
        timeout_per_symbol: float = 2.0,
    ) -> dict[int, SymbolInfo]:
        """Try subscribing to common symbol patterns to discover IDs.

        For each pattern, subscribe and wait briefly for a tick.
        If a tick arrives, the symbol exists.
        """
        if symbol_patterns is None:
            symbol_patterns = DEFAULT_PROBE_PATTERNS

        client = _DiscoveryClient(self._credentials)

        if not client.connect():
            logger.error("Failed to connect for subscription probe")
            return {}

        discovered: dict[int, SymbolInfo] = {}

        try:
            for name in symbol_patterns:
                # Try to subscribe using the name as symbol ID (string)
                req_id = f"PROBE_{datetime.now(timezone.utc).strftime('%H%M%S%f')}"

                msg = FIXMessage(msg_type="V")
                msg.set_body_field(262, req_id)
                msg.set_body_field(263, "1")  # snapshot + updates
                msg.set_body_field(264, "0")
                msg.set_body_field(265, "0")
                msg.set_body_field(267, "2")
                msg.set_body_field(269, "0")
                msg.set_body_field(269, "1")
                msg.set_body_field(146, "1")
                msg.set_body_field(55, name)

                client._probe_event.clear()
                client._send_message(msg)

                if client._probe_event.wait(timeout=timeout_per_symbol):
                    # We got ticks but they're keyed by numeric ID from tag 55
                    # The response will have the numeric ID, not the string we sent
                    for sid, (bid, ask) in client._probe_ticks.items():
                        if sid not in discovered:
                            category = classify_symbol(name)
                            pip_size = 0.0001
                            if "JPY" in name.upper():
                                pip_size = 0.01
                            elif "XAU" in name.upper():
                                pip_size = 0.01

                            info = SymbolInfo(
                                symbol_id=sid,
                                name=name,
                                pip_size=pip_size,
                                digits=5 if pip_size < 0.01 else 3,
                                category=category,
                            )
                            discovered[sid] = info
                            logger.info(f"Probe discovered: {name} (id={sid})")

                    # Unsubscribe
                    unsub = FIXMessage(msg_type="V")
                    unsub.set_body_field(262, f"UNSUB_{req_id}")
                    unsub.set_body_field(263, "2")
                    unsub.set_body_field(264, "1")
                    unsub.set_body_field(55, name)
                    client._send_message(unsub)
                else:
                    logger.debug(f"Probe: no response for {name}")

                time.sleep(0.5)  # Pause between probes

        finally:
            client.disconnect()

        if discovered:
            self._symbols.update(discovered)
            self.save_cache()
            logger.info(f"Probe discovered {len(discovered)} symbols")

        return discovered

    def discover_via_open_api(self, timeout: float = 15.0) -> dict[int, SymbolInfo]:
        """Discover symbols via cTrader Open API (protobuf).

        More reliable than FIX SecurityListRequest.
        """
        import os
        from .open_api_client import CTraderOpenApiClient

        client_id = os.environ.get("CTRADER_OPENAPI_CLIENT_ID", "")
        client_secret = os.environ.get("CTRADER_OPENAPI_CLIENT_SECRET", "")
        account_id = int(os.environ.get("CTRADER_ACCOUNT", "0"))
        access_token = os.environ.get("CTRADER_OPENAPI_ACCESS_TOKEN", "")

        if not client_id or not client_secret:
            logger.warning("Open API credentials not set, skipping")
            return {}

        client = CTraderOpenApiClient(
            client_id=client_id,
            client_secret=client_secret,
            account_id=account_id,
            access_token=access_token,
        )

        if not client.connect():
            logger.error("Failed to connect for Open API symbol discovery")
            return {}

        try:
            symbols = client.get_all_symbols()
        finally:
            client.disconnect()

        discovered = {}
        for s in symbols:
            category = classify_symbol(s["name"])
            info = SymbolInfo(
                symbol_id=s["symbol_id"],
                name=s["name"],
                pip_size=s["pip_size"],
                digits=s["digits"],
                description=s["description"],
                category=category,
            )
            discovered[s["symbol_id"]] = info

        if discovered:
            self._symbols.update(discovered)
            self.save_cache()
            logger.info(f"Open API discovered {len(discovered)} symbols")

        return discovered

    def load_cache(self) -> dict[int, SymbolInfo]:
        """Load previously discovered symbols from JSON cache."""
        if not self._cache_path.exists():
            return {}
        try:
            data = json.loads(self._cache_path.read_text())
            symbols = {}
            for sid_str, info_dict in data.items():
                info = SymbolInfo.from_dict(info_dict)
                symbols[int(sid_str)] = info
            logger.debug(f"Loaded {len(symbols)} symbols from cache")
            return symbols
        except Exception as e:
            logger.error(f"Failed to load symbol cache: {e}")
            return {}

    def save_cache(self):
        """Save discovered symbols to JSON cache."""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            data = {str(sid): info.to_dict() for sid, info in self._symbols.items()}
            self._cache_path.write_text(json.dumps(data, indent=2, default=str))
            logger.debug(f"Saved {len(self._symbols)} symbols to cache")
        except Exception as e:
            logger.error(f"Failed to save symbol cache: {e}")

    def get_all(self) -> dict[int, SymbolInfo]:
        """Get all known symbols (cache + discovered)."""
        return dict(self._symbols)

    def get_by_category(self, category: str) -> list[SymbolInfo]:
        """Filter symbols by category."""
        return [info for info in self._symbols.values() if info.category == category]

    def get_by_name(self, name: str) -> SymbolInfo | None:
        """Look up a symbol by name (case-insensitive, slash-agnostic)."""
        normalized = name.upper().replace(" ", "")
        for info in self._symbols.values():
            if info.name.upper().replace(" ", "").replace("/", "") == normalized:
                return info
        return None
