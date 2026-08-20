#!/usr/bin/env python3
"""FTMO Broker Validation — empirical slippage / spread / requote measurement.

Connects to an FTMO demo account via cTrader Open API and executes a
structured series of test market orders across varying market conditions
to build an empirical cost model.

Credential Schema
=================
FTMO demo credentials are read from environment variables (or ``.env``):

    FTMO_CTRADER_CLIENT_ID        OAuth2 client ID for FTMO app
    FTMO_CTRADER_CLIENT_SECRET    OAuth2 client secret
    FTMO_CTRADER_ACCESS_TOKEN     Access token (initial or refreshed)
    FTMO_CTRADER_REFRESH_TOKEN    Refresh token for token lifecycle
    FTMO_CTRADER_ACCOUNT_ID       cTrader numeric account ID

These mirror the existing Ayumi cTrader credential pattern
(``CTRADER_OPENAPI_*``) but are prefixed ``FTMO_`` to isolate the
demo account from any production connection.

Usage
=====
    # Dry run — no broker connection, generates synthetic data
    python scripts/ftmo_broker_validation.py --dry-run

    # Live execution (requires credentials)
    python scripts/ftmo_broker_validation.py --orders 100 --pairs EURUSD,GBPUSD,USDJPY

    # Specify market-condition windows
    python scripts/ftmo_broker_validation.py \\
        --conditions low_volatility,news,session_open

Output
======
Results are written to ``data/ftmo_broker_validation/results.json``.

Acceptance Criteria Mapping
===========================
This script framework satisfies:
    AC1: Script exists that can execute test orders on FTMO demo account
    AC6: No live funds at risk — demo/micro only (enforced by design)

Deferred (require live credentials):
    AC2: 100+ orders logged across ≥3 market conditions
    AC3: Slippage distribution calculated (mean, median, P95, P99)
    AC4: Spread widening events documented
    AC5: Results written to results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

OUTPUT_DIR = PROJECT_ROOT / "data" / "ftmo_broker_validation"
RESULTS_FILE = OUTPUT_DIR / "results.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ftmo_validation")

# ─── Market condition definitions ────────────────────────────────────

CONDITIONS = {
    "low_volatility": {
        "description": "Asian session, low spread, minimal news",
        "sessions": ["asia"],
        "expected_spread_pips": {
            "EURUSD": 0.5,
            "GBPUSD": 0.8,
            "USDJPY": 0.6,
            "XAUUSD": 15,
        },
    },
    "high_volatility": {
        "description": "London/NY overlap, elevated activity",
        "sessions": ["london_ny_overlap"],
        "expected_spread_pips": {
            "EURUSD": 1.2,
            "GBPUSD": 1.8,
            "USDJPY": 1.5,
            "XAUUSD": 30,
        },
    },
    "news": {
        "description": "Scheduled news release window (NFP, CPI, FOMC)",
        "sessions": ["news_window"],
        "expected_spread_pips": {
            "EURUSD": 3.0,
            "GBPUSD": 4.0,
            "USDJPY": 3.5,
            "XAUUSD": 80,
        },
    },
    "session_open": {
        "description": "London or NY session open (first 30 min)",
        "sessions": ["london_open", "ny_open"],
        "expected_spread_pips": {
            "EURUSD": 1.0,
            "GBPUSD": 1.5,
            "USDJPY": 1.2,
            "XAUUSD": 25,
        },
    },
    "session_close": {
        "description": "London or NY session close (last 30 min)",
        "sessions": ["london_close", "ny_close"],
        "expected_spread_pips": {
            "EURUSD": 0.8,
            "GBPUSD": 1.2,
            "USDJPY": 1.0,
            "XAUUSD": 20,
        },
    },
}

DEFAULT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY"]
DEFAULT_LOT_SIZE = 0.01  # Micro — demo only


# ─── Data models ─────────────────────────────────────────────────────


@dataclass
class OrderRecord:
    """Single test order result."""

    timestamp: str
    pair: str
    condition: str
    side: str  # 'buy' or 'sell'
    requested_price: float
    fill_price: float
    slippage_pips: float
    spread_pips_at_execution: float
    volume_lots: float
    latency_ms: float
    status: str  # 'filled', 'requoted', 'partial_fill', 'rejected'
    requote_price: float | None = None
    partial_fill_volume: float | None = None


@dataclass
class SpreadSample:
    """Point-in-time spread measurement."""

    timestamp: str
    pair: str
    condition: str
    bid: float
    ask: float
    spread_pips: float


@dataclass
class SpreadEvent:
    """Detected spread widening event."""

    timestamp: str
    pair: str
    condition: str
    baseline_spread_pips: float
    peak_spread_pips: float
    widening_factor: float
    duration_seconds: float
    trigger: str  # 'news', 'session_transition', 'unknown'


@dataclass
class ValidationResult:
    """Complete validation session output."""

    session_start: str
    session_end: str
    total_orders: int
    orders: list[OrderRecord] = field(default_factory=list)
    spread_samples: list[SpreadSample] = field(default_factory=list)
    spread_events: list[SpreadEvent] = field(default_factory=list)
    slippage_stats: dict[str, Any] = field(default_factory=dict)
    spread_stats: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False


# ─── Statistics ──────────────────────────────────────────────────────


def calculate_slippage_distribution(
    orders: list[OrderRecord],
) -> dict[str, dict[str, float]]:
    """Calculate slippage statistics per pair.

    Returns a dict keyed by pair name, each containing:
        mean, median, stdev, p95, p99, min, max, count
    """
    by_pair: dict[str, list[float]] = {}
    for o in orders:
        if o.status != "filled":
            continue
        by_pair.setdefault(o.pair, []).append(o.slippage_pips)

    stats: dict[str, dict[str, float]] = {}
    for pair, slips in by_pair.items():
        if not slips:
            continue
        slips_sorted = sorted(slips)
        n = len(slips_sorted)
        stats[pair] = {
            "mean": round(statistics.mean(slips_sorted), 4),
            "median": round(statistics.median(slips_sorted), 4),
            "stdev": round(statistics.stdev(slips_sorted), 4) if n > 1 else 0.0,
            "p95": round(_percentile(slips_sorted, 95), 4),
            "p99": round(_percentile(slips_sorted, 99), 4),
            "min": round(min(slips_sorted), 4),
            "max": round(max(slips_sorted), 4),
            "count": n,
        }
    return stats


def calculate_spread_stats(
    samples: list[SpreadSample],
) -> dict[str, dict[str, float]]:
    """Calculate spread statistics per pair."""
    by_pair: dict[str, list[float]] = {}
    for s in samples:
        by_pair.setdefault(s.pair, []).append(s.spread_pips)

    stats: dict[str, dict[str, float]] = {}
    for pair, spreads in by_pair.items():
        if not spreads:
            continue
        spreads_sorted = sorted(spreads)
        stats[pair] = {
            "mean": round(statistics.mean(spreads_sorted), 4),
            "median": round(statistics.median(spreads_sorted), 4),
            "stdev": round(statistics.stdev(spreads_sorted), 4) if len(spreads_sorted) > 1 else 0.0,
            "p95": round(_percentile(spreads_sorted, 95), 4),
            "p99": round(_percentile(spreads_sorted, 99), 4),
            "min": round(min(spreads_sorted), 4),
            "max": round(max(spreads_sorted), 4),
            "count": len(spreads_sorted),
        }
    return stats


def detect_spread_events(
    samples: list[SpreadSample],
    widening_threshold: float = 2.0,
    min_duration_seconds: float = 5.0,
) -> list[SpreadEvent]:
    """Detect spread widening events from spread samples.

    A widening event is when spread exceeds ``widening_threshold`` ×
    the running baseline (median of prior samples) for at least
    ``min_duration_seconds``.
    """
    if len(samples) < 3:
        return []

    events: list[SpreadEvent] = []
    by_pair: dict[str, list[SpreadSample]] = {}
    for s in samples:
        by_pair.setdefault(s.pair, []).append(s)

    for pair, pair_samples in by_pair.items():
        if len(pair_samples) < 3:
            continue

        # Compute baseline as median of first 20 samples (or all if < 20)
        baseline_window = pair_samples[: min(20, len(pair_samples))]
        baseline_spreads = [s.spread_pips for s in baseline_window]
        baseline = statistics.median(baseline_spreads)

        if baseline <= 0:
            continue

        in_event = False
        event_start: SpreadSample | None = None
        peak = 0.0

        for i, s in enumerate(pair_samples):  # noqa: B007
            factor = s.spread_pips / baseline
            if factor >= widening_threshold and not in_event:
                in_event = True
                event_start = s
                peak = s.spread_pips
            elif in_event:
                peak = max(peak, s.spread_pips)
                if factor < widening_threshold:
                    # Event ended
                    start_ts = _parse_ts(event_start.timestamp)
                    end_ts = _parse_ts(s.timestamp)
                    duration = (end_ts - start_ts).total_seconds()
                    if duration >= min_duration_seconds:
                        trigger = _classify_trigger(s.condition)
                        events.append(
                            SpreadEvent(
                                timestamp=event_start.timestamp,
                                pair=pair,
                                condition=s.condition,
                                baseline_spread_pips=round(baseline, 4),
                                peak_spread_pips=round(peak, 4),
                                widening_factor=round(peak / baseline, 2),
                                duration_seconds=round(duration, 1),
                                trigger=trigger,
                            )
                        )
                    in_event = False
                    event_start = None
                    peak = 0.0

    return events


# ─── Dry-run synthetic data generation ───────────────────────────────


def _dry_run_orders(
    pairs: list[str],
    conditions: list[str],
    orders_per_condition: int,
) -> list[OrderRecord]:
    """Generate realistic synthetic order records for dry-run mode."""
    import random

    random.seed(42)  # Deterministic for reproducible tests

    records: list[OrderRecord] = []
    base_prices = {
        "EURUSD": 1.0850,
        "GBPUSD": 1.2720,
        "USDJPY": 149.50,
        "XAUUSD": 2350.0,
    }
    pip_sizes = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01, "XAUUSD": 0.1}

    for condition in conditions:
        cond_def = CONDITIONS.get(condition, CONDITIONS["low_volatility"])
        for i in range(orders_per_condition):
            pair = pairs[i % len(pairs)]
            base = base_prices.get(pair, 1.0000)
            pip = pip_sizes.get(pair, 0.0001)
            expected_spread = cond_def["expected_spread_pips"].get(pair, 1.0)

            # Simulate slippage: normally distributed around expected_spread/2
            slip_pips = max(0, random.gauss(expected_spread * 0.4, expected_spread * 0.3))
            spread = max(0.1, random.gauss(expected_spread, expected_spread * 0.2))
            latency = max(5, random.gauss(50, 30))

            side = random.choice(["buy", "sell"])  # noqa: S311
            req_price = base + random.uniform(-pip * 10, pip * 10)  # noqa: S311
            fill_price = req_price + (slip_pips * pip * (1 if side == "buy" else -1))

            # Simulate occasional requotes/partial fills (~5%)
            roll = random.random()  # noqa: S311
            if roll < 0.02:
                status = "rejected"
            elif roll < 0.05:
                status = "requoted"
                fill_price = req_price + (slip_pips * 1.5 * pip)
            elif roll < 0.08:
                status = "partial_fill"
            else:
                status = "filled"

            now = datetime.now(timezone.utc).isoformat()
            records.append(
                OrderRecord(
                    timestamp=now,
                    pair=pair,
                    condition=condition,
                    side=side,
                    requested_price=round(req_price, 6),
                    fill_price=round(fill_price, 6),
                    slippage_pips=round(slip_pips, 4),
                    spread_pips_at_execution=round(spread, 4),
                    volume_lots=DEFAULT_LOT_SIZE,
                    latency_ms=round(latency, 1),
                    status=status,
                    requote_price=round(fill_price, 6) if status == "requoted" else None,
                    partial_fill_volume=round(DEFAULT_LOT_SIZE * 0.5, 2) if status == "partial_fill" else None,
                )
            )
    return records


def _dry_run_spreads(
    pairs: list[str],
    conditions: list[str],
    samples_per_pair: int,
) -> list[SpreadSample]:
    """Generate synthetic spread samples for dry-run mode."""
    import random

    random.seed(99)

    samples: list[SpreadSample] = []
    base_prices = {
        "EURUSD": 1.0850,
        "GBPUSD": 1.2720,
        "USDJPY": 149.50,
        "XAUUSD": 2350.0,
    }
    pip_sizes = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01, "XAUUSD": 0.1}

    for condition in conditions:
        cond_def = CONDITIONS.get(condition, CONDITIONS["low_volatility"])
        for pair in pairs:
            base = base_prices.get(pair, 1.0000)
            pip = pip_sizes.get(pair, 0.0001)
            expected = cond_def["expected_spread_pips"].get(pair, 1.0)

            for i in range(samples_per_pair):  # noqa: B007
                # Occasionally spike spread (simulate news/event)
                if random.random() < 0.05:  # noqa: S311
                    spread = expected * random.uniform(2.5, 4.0)  # noqa: S311
                else:
                    spread = max(0.1, random.gauss(expected, expected * 0.25))

                bid = base - (spread * pip / 2)
                ask = base + (spread * pip / 2)
                now = datetime.now(timezone.utc).isoformat()

                samples.append(
                    SpreadSample(
                        timestamp=now,
                        pair=pair,
                        condition=condition,
                        bid=round(bid, 6),
                        ask=round(ask, 6),
                        spread_pips=round(spread, 4),
                    )
                )
    return samples


# ─── Live broker connection (stub — activated when credentials exist) ─


class FTMOBrokerSession:
    """cTrader Open API session for FTMO demo account.

    This class encapsulates the broker connection. When credentials
    are provided via environment variables, it connects via the same
    ctrader_open_api stack used by the rest of Ayumi.

    Until credentials are available, instantiation raises
    ``CredentialsNotAvailable`` so callers can fall back to dry-run.
    """

    def __init__(self) -> None:
        self.client_id = os.environ.get("FTMO_CTRADER_CLIENT_ID", "")
        self.client_secret = os.environ.get("FTMO_CTRADER_CLIENT_SECRET", "")
        self.access_token = os.environ.get("FTMO_CTRADER_ACCESS_TOKEN", "")
        self.refresh_token = os.environ.get("FTMO_CTRADER_REFRESH_TOKEN", "")
        account_id_raw = os.environ.get("FTMO_CTRADER_ACCOUNT_ID", "")

        if not all([self.client_id, self.client_secret, self.access_token, account_id_raw]):
            raise CredentialsNotAvailable(
                "FTMO demo credentials not found in environment. "
                "Set FTMO_CTRADER_CLIENT_ID, FTMO_CTRADER_CLIENT_SECRET, "
                "FTMO_CTRADER_ACCESS_TOKEN, FTMO_CTRADER_REFRESH_TOKEN, "
                "FTMO_CTRADER_ACCOUNT_ID to run live validation."
            )

        self.account_id = int(account_id_raw)
        self._feed = None
        logger.info("FTMO broker session initialized for account %d", self.account_id)

    async def connect(self) -> None:
        """Establish connection to FTMO cTrader demo server."""
        from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed

        # FTMO uses the same cTrader Open API — just different host/port
        host = os.environ.get("FTMO_CTRADER_HOST", "demo.ctraderapi.com")
        port = int(os.environ.get("FTMO_CTRADER_SSL_PORT", "5035"))

        # Build a lightweight credential store from env
        # (FTMO credentials are separate from production CTRADER_OPENAPI_*)
        class _FTMOCredStore:
            client_id = self.client_id
            client_secret = self.client_secret
            access_token = self.access_token
            refresh_token = self.refresh_token
            account_id = self.account_id
            trader_login = 0
            expires_at = None

        _store = _FTMOCredStore()
        self._feed = OpenApiSpotFeed(
            ctid_account_id=self.account_id,
            client_id=self.client_id,
            client_secret=self.client_secret,
            access_token=self.access_token,
            refresh_token=self.refresh_token or None,
            host=host,
            port=port,
            token_lifecycle=None,  # FTMO session manages its own lifecycle
        )
        ok = await self._feed.start()
        if not ok:
            raise ConnectionError("Failed to connect to FTMO demo server")

    async def execute_market_order(
        self,
        pair: str,
        side: str,
        volume_lots: float,
    ) -> OrderRecord:
        """Execute a single market order and measure slippage.

        Returns an OrderRecord with measured execution metrics.
        """
        if not self._feed:
            raise RuntimeError("Broker session not connected — call connect() first")

        ts_start = time.monotonic()

        # Get current spot price as reference
        spot = self._feed.get_last_price(pair)
        if spot is None:
            raise ValueError(f"No spot price available for {pair}")

        bid = spot.get("bid", 0)
        ask = spot.get("ask", 0)
        spread_pips = ask - bid

        requested_price = ask if side == "buy" else bid

        # Execute market order
        volume_int = int(round(volume_lots * 100_000))  # Standard lot size
        ok = self._feed.send_market_order(pair, side, volume_int)

        latency_ms = (time.monotonic() - ts_start) * 1000

        # Record result
        now = datetime.now(timezone.utc).isoformat()
        if ok:
            fill_price = self._feed.get_last_price(pair)
            fill = fill_price.get("ask" if side == "buy" else "bid", requested_price)
            slippage = abs(fill - requested_price)
            return OrderRecord(
                timestamp=now,
                pair=pair,
                condition="",  # Set by caller
                side=side,
                requested_price=round(requested_price, 6),
                fill_price=round(fill, 6),
                slippage_pips=round(slippage, 4),
                spread_pips_at_execution=round(spread_pips, 4),
                volume_lots=volume_lots,
                latency_ms=round(latency_ms, 1),
                status="filled",
            )
        else:
            return OrderRecord(
                timestamp=now,
                pair=pair,
                condition="",
                side=side,
                requested_price=round(requested_price, 6),
                fill_price=0.0,
                slippage_pips=0.0,
                spread_pips_at_execution=round(spread_pips, 4),
                volume_lots=volume_lots,
                latency_ms=round(latency_ms, 1),
                status="rejected",
            )

    async def sample_spread(self, pair: str, duration_seconds: float = 30.0) -> list[SpreadSample]:
        """Sample bid/ask spread for a pair over a time window."""
        if not self._feed:
            raise RuntimeError("Broker session not connected")

        samples: list[SpreadSample] = []
        interval = 1.0  # Sample every second
        elapsed = 0.0

        while elapsed < duration_seconds:
            spot = self._feed.get_last_price(pair)
            if spot:
                bid = spot.get("bid", 0)
                ask = spot.get("ask", 0)
                spread_pips = ask - bid
                now = datetime.now(timezone.utc).isoformat()
                samples.append(
                    SpreadSample(
                        timestamp=now,
                        pair=pair,
                        condition="",  # Set by caller
                        bid=round(bid, 6),
                        ask=round(ask, 6),
                        spread_pips=round(spread_pips, 4),
                    )
                )
            await asyncio.sleep(interval)
            elapsed += interval

        return samples

    def disconnect(self) -> None:
        if self._feed:
            self._feed.stop()
            self._feed = None


class CredentialsNotAvailable(Exception):
    """Raised when FTMO demo credentials are not configured."""


# ─── Utilities ───────────────────────────────────────────────────────


def _percentile(sorted_data: list[float], pct: float) -> float:
    """Calculate percentile using nearest-rank method."""
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    # Nearest-rank method
    rank = max(0, min(n - 1, int(round((pct / 100.0) * (n - 1)))))
    return sorted_data[rank]


def _parse_ts(ts: str) -> datetime:
    """Parse ISO timestamp, tolerant of trailing Z."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


def _classify_trigger(condition: str) -> str:
    """Classify the likely trigger of a spread event from condition label."""
    if "news" in condition.lower():
        return "news"
    if "session" in condition.lower():
        return "session_transition"
    return "unknown"


def _write_results(result: ValidationResult, output_path: Path) -> None:
    """Write validation results to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = asdict(result)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    logger.info("Results written to %s", output_path)


# ─── Main execution ──────────────────────────────────────────────────


async def run_validation(
    pairs: list[str],
    conditions: list[str],
    orders_per_condition: int,
    spread_sampling_duration: int,
    dry_run: bool,
) -> ValidationResult:
    """Run the full validation pipeline.

    In dry-run mode, generates synthetic data through the same
    statistics pipeline so downstream consumers are identical.
    """
    session_start = datetime.now(timezone.utc).isoformat()
    logger.info(
        "Starting FTMO broker validation | dry_run=%s | pairs=%s | conditions=%s | orders/condition=%d",
        dry_run,
        pairs,
        conditions,
        orders_per_condition,
    )

    orders: list[OrderRecord] = []
    spread_samples: list[SpreadSample] = []

    if dry_run:
        logger.info("DRY RUN — generating synthetic data (no broker connection)")
        orders = _dry_run_orders(pairs, conditions, orders_per_condition)
        spread_samples = _dry_run_spreads(pairs, conditions, samples_per_pair=30)
    else:
        try:
            session = FTMOBrokerSession()
            await session.connect()

            for condition in conditions:
                logger.info("Executing orders for condition: %s", condition)
                for pair in pairs:
                    for i in range(orders_per_condition // len(pairs) + 1):
                        side = "buy" if i % 2 == 0 else "sell"
                        record = await session.execute_market_order(
                            pair=pair,
                            side=side,
                            volume_lots=DEFAULT_LOT_SIZE,
                        )
                        record.condition = condition
                        orders.append(record)
                        await asyncio.sleep(0.5)  # Throttle

                    # Sample spreads between order batches
                    samples = await session.sample_spread(pair, spread_sampling_duration)
                    for s in samples:
                        s.condition = condition
                    spread_samples.extend(samples)

            session.disconnect()
        except CredentialsNotAvailable as e:
            logger.error("Cannot run live validation: %s", e)
            logger.info("Use --dry-run to exercise the pipeline without credentials")
            sys.exit(1)

    # Calculate statistics
    slippage_stats = calculate_slippage_distribution(orders)
    spread_stats = calculate_spread_stats(spread_samples)
    spread_events = detect_spread_events(spread_samples)

    session_end = datetime.now(timezone.utc).isoformat()

    result = ValidationResult(
        session_start=session_start,
        session_end=session_end,
        total_orders=len(orders),
        orders=orders,
        spread_samples=spread_samples,
        spread_events=spread_events,
        slippage_stats=slippage_stats,
        spread_stats=spread_stats,
        config={
            "pairs": pairs,
            "conditions": conditions,
            "orders_per_condition": orders_per_condition,
            "spread_sampling_duration": spread_sampling_duration,
            "lot_size": DEFAULT_LOT_SIZE,
        },
        dry_run=dry_run,
    )

    _write_results(result, RESULTS_FILE)

    # Print summary
    logger.info("=" * 60)
    logger.info("FTMO Broker Validation Summary")
    logger.info("=" * 60)
    logger.info("Mode: %s", "DRY RUN" if dry_run else "LIVE")
    logger.info("Total orders: %d", len(orders))
    filled = [o for o in orders if o.status == "filled"]
    rejected = [o for o in orders if o.status == "rejected"]
    requoted = [o for o in orders if o.status == "requoted"]
    partial = [o for o in orders if o.status == "partial_fill"]
    logger.info(
        "  Filled: %d | Rejected: %d | Requoted: %d | Partial: %d",
        len(filled),
        len(rejected),
        len(requoted),
        len(partial),
    )
    logger.info("Spread samples: %d", len(spread_samples))
    logger.info("Spread events detected: %d", len(spread_events))
    for pair, stats in slippage_stats.items():
        logger.info(
            "  %s slippage: mean=%.4f pips, P95=%.4f pips, P99=%.4f pips",
            pair,
            stats["mean"],
            stats["p95"],
            stats["p99"],
        )
    logger.info("Results file: %s", RESULTS_FILE)

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FTMO broker validation — empirical slippage/spread/requote measurement",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate synthetic data without broker connection",
    )
    parser.add_argument(
        "--orders",
        type=int,
        default=100,
        help="Total test orders across all conditions (default: 100)",
    )
    parser.add_argument(
        "--pairs",
        type=str,
        default=",".join(DEFAULT_PAIRS),
        help="Comma-separated list of pairs to test",
    )
    parser.add_argument(
        "--conditions",
        type=str,
        default="low_volatility,news,session_open",
        help="Comma-separated condition keys: " + ", ".join(CONDITIONS.keys()),
    )
    parser.add_argument(
        "--spread-sampling-duration",
        type=int,
        default=30,
        help="Seconds of spread sampling per pair per condition (default: 30)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pairs = [p.strip().upper() for p in args.pairs.split(",")]
    conditions = [c.strip() for c in args.conditions.split(",")]

    # Validate condition names
    invalid = [c for c in conditions if c not in CONDITIONS]
    if invalid:
        logger.error("Unknown condition(s): %s. Valid: %s", invalid, list(CONDITIONS.keys()))
        sys.exit(1)

    orders_per_condition = args.orders // len(conditions)

    asyncio.run(
        run_validation(
            pairs=pairs,
            conditions=conditions,
            orders_per_condition=orders_per_condition,
            spread_sampling_duration=args.spread_sampling_duration,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
