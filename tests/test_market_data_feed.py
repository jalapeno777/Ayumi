"""Tests for MarketDataFeed — spot events → bars → ticks (BQ-1043 Phase 2b).

These tests call ``on_spot_event`` directly with synthetic data — no
protobuf or network required.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from adapters.ctrader.market_data_feed import MarketDataFeed
from adapters.ctrader.protocols import Bar, Tick


# ── Helpers ─────────────────────────────────────────────────────────────────

def ts(minute: int, second: int = 0) -> datetime:
    """Create a UTC timestamp on 2026-06-16 at the given minute/second."""
    return datetime(2026, 6, 16, 14, minute, second, tzinfo=timezone.utc)


def ts_at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    """Create a UTC timestamp on 2026-06-16 at the given hour:minute:second."""
    return datetime(2026, 6, 16, hour, minute, second, tzinfo=timezone.utc)


SYM_ID = 1
SYM_NAME = "GBPUSD"


def make_feed(bar_period_seconds: int = 3600) -> MarketDataFeed:
    """Create a feed with a single symbol and matching id map."""
    return MarketDataFeed(
        symbols=[SYM_NAME],
        bar_period_seconds=bar_period_seconds,
        symbol_id_map={SYM_ID: SYM_NAME},
    )


# ── Tests ───────────────────────────────────────────────────────────────────


class TestMarketDataFeed:
    # ── 1. Spot event updates latest tick ──────────────────────────────────

    def test_spot_event_updates_latest_tick(self):
        """Send a spot event, verify get_tick returns it."""
        feed = make_feed()
        feed.on_spot_event(SYM_ID, 1.26500, 1.26510, ts(0))

        tick = feed.get_tick(SYM_NAME)
        assert tick is not None
        assert tick.symbol == SYM_NAME
        assert tick.bid == 1.26500
        assert tick.ask == 1.26510
        assert tick.mid == pytest.approx(1.26505)

    # ── 2. Tick listener fires ─────────────────────────────────────────────

    def test_tick_listener_called(self):
        """Register a listener, send event, verify it fires."""
        feed = make_feed()
        received: list[Tick] = []
        feed.add_tick_listener(received.append)

        feed.on_spot_event(SYM_ID, 1.26500, 1.26510, ts(0))

        assert len(received) == 1
        assert received[0].symbol == SYM_NAME
        assert received[0].bid == 1.26500

    # ── 3. Bar builds over period ──────────────────────────────────────────

    def test_bar_builds_over_period(self):
        """Send ticks spanning 1 hour, verify bar closes and listener fires."""
        feed = make_feed(bar_period_seconds=3600)
        closed_bars: list[Bar] = []
        feed.add_bar_listener(closed_bars.append)

        # Ticks within the 14:00 hour
        for m in range(0, 60, 5):
            feed.on_spot_event(SYM_ID, 1.26500 + m * 0.00010,
                               1.26510 + m * 0.00010, ts(m))

        # No bar should have closed yet — all within same period
        assert len(closed_bars) == 0
        assert feed.bars_built == 0

        # First tick of the next hour (15:00) closes the 14:00 bar
        feed.on_spot_event(SYM_ID, 1.27000, 1.27010, ts_at(15, 0))

        assert len(closed_bars) == 1
        assert feed.bars_built == 1
        assert closed_bars[0].is_closed is True
        assert closed_bars[0].symbol == SYM_NAME

    # ── 4. Bar OHLC correctness ────────────────────────────────────────────

    def test_bar_high_low_close_correct(self):
        """Send ticks with known prices, verify OHLC values."""
        feed = make_feed(bar_period_seconds=3600)

        # Tick 1: open
        feed.on_spot_event(SYM_ID, 1.26500, 1.26510, ts(0))
        # Tick 2: higher high
        feed.on_spot_event(SYM_ID, 1.26600, 1.26620, ts(15))
        # Tick 3: lower low
        feed.on_spot_event(SYM_ID, 1.26400, 1.26410, ts(30))
        # Tick 4: close (mid)
        feed.on_spot_event(SYM_ID, 1.26550, 1.26560, ts(45))

        # Close the bar with a tick in the next period
        feed.on_spot_event(SYM_ID, 1.27000, 1.27010, ts_at(15, 0))

        bars = feed.get_closed_bars(SYM_NAME)
        assert len(bars) == 1
        bar = bars[0]

        # Open = mid of first tick = (1.26500 + 1.26510) / 2
        assert bar.open == pytest.approx(1.26505)
        # High = highest ask = 1.26620
        assert bar.high == pytest.approx(1.26620)
        # Low = lowest bid = 1.26400
        assert bar.low == pytest.approx(1.26400)
        # Close = mid of last tick in period = (1.26550 + 1.26560) / 2
        assert bar.close == pytest.approx(1.26555)
        # Volume = 4 ticks
        assert bar.volume == 4

    # ── 5. Tick count increments ───────────────────────────────────────────

    def test_tick_count_increments(self):
        """Send 100 events, verify ticks_received == 100."""
        feed = make_feed()
        base = ts_at(14, 0)

        for i in range(100):
            feed.on_spot_event(SYM_ID, 1.26500, 1.26510,
                               base + timedelta(seconds=i))

        assert feed.ticks_received == 100

    # ── 6. get_latest_bar returns most recent ──────────────────────────────

    def test_get_latest_bar_returns_most_recent(self):
        """Build 3 bars, verify get_latest_bar returns the 3rd."""
        feed = make_feed(bar_period_seconds=3600)

        # Build bar in hour 14
        feed.on_spot_event(SYM_ID, 1.26000, 1.26010, ts_at(14, 0))
        feed.on_spot_event(SYM_ID, 1.27000, 1.27010, ts_at(15, 0))  # closes H14

        # Build bar in hour 15
        feed.on_spot_event(SYM_ID, 1.27500, 1.27510, ts_at(16, 0))  # closes H15

        # Build bar in hour 16
        feed.on_spot_event(SYM_ID, 1.28000, 1.28010, ts_at(17, 0))  # closes H16

        bars = feed.get_closed_bars(SYM_NAME)
        assert len(bars) == 3
        assert feed.bars_built == 3

        latest = feed.get_latest_bar(SYM_NAME)
        assert latest is not None
        # Latest closed bar should be the hour 16 bar (open=1.27505)
        assert latest.open == pytest.approx((1.27500 + 1.27510) / 2)

    # ── 7. Thread safety ───────────────────────────────────────────────────

    def test_thread_safety(self):
        """10 threads sending spot events concurrently, no corruption."""
        feed = make_feed()
        errors: list[Exception] = []

        def worker(thread_id: int):
            try:
                for i in range(100):
                    bid = 1.26000 + (thread_id * 0.001) + (i * 0.00001)
                    ask = bid + 0.00010
                    feed.on_spot_event(
                        SYM_ID, bid, ask,
                        ts_at(14, 0, (thread_id * 100 + i) % 60),
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert feed.ticks_received == 1000

        # Tick state should be internally consistent
        tick = feed.get_tick(SYM_NAME)
        assert tick is not None
        assert tick.bid < tick.ask
