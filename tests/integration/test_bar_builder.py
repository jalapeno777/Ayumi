"""Tests for BarBuilder — OHLCV bar aggregation."""

import threading
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

import pytest

from adapters.ctrader.bar_builder import BarBuilder


@dataclass
class FakeTick:
    symbol_id: int
    bid: float
    ask: float
    timestamp: datetime
    spread: float = 0.0

    @property
    def mid(self):
        return (self.bid + self.ask) / 2


def _tick(bid: float, ask: float, minutes_offset: int = 0) -> FakeTick:
    ts = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc) + timedelta(
        minutes=minutes_offset
    )
    return FakeTick(symbol_id=1, bid=bid, ask=ask, timestamp=ts)


class TestConfiguration:
    def test_add_timeframe(self):
        b = BarBuilder()
        b.add_timeframe("GBPUSD", 15)
        b.add_timeframe("GBPUSD", 60)
        assert b.timeframes == {15, 60}

    def test_burst_mode(self):
        b = BarBuilder(max_bars=100)
        assert b._effective_max_bars() == 100
        b.set_burst_mode(True)
        assert b._effective_max_bars() == 150


class TestBarBuilding:
    def test_single_tick_creates_forming_bar(self):
        b = BarBuilder()
        b.add_timeframe("GBPUSD", 60)
        b.process_tick(_tick(1.2600, 1.2601), "GBPUSD")
        assert b.bar_count("GBPUSD", 60) == 0
        forming = b.forming_bar("GBPUSD", 60)
        assert forming is not None
        assert forming["open"] == pytest.approx(1.26005)
        assert forming["volume"] == 1

    def test_two_ticks_same_bar_updates(self):
        b = BarBuilder()
        b.add_timeframe("GBPUSD", 60)
        b.process_tick(_tick(1.2600, 1.2601), "GBPUSD")
        b.process_tick(_tick(1.2610, 1.2611), "GBPUSD")
        forming = b.forming_bar("GBPUSD", 60)
        assert forming["high"] == 1.2611
        assert forming["low"] == 1.2600
        assert forming["volume"] == 2
        assert b.bar_count("GBPUSD", 60) == 0  # not finalized yet

    def test_tick_in_next_period_finalizes_bar(self):
        b = BarBuilder()
        b.add_timeframe("GBPUSD", 15)
        # Tick at 10:00
        b.process_tick(_tick(1.2600, 1.2601, minutes_offset=0), "GBPUSD")
        # Tick at 10:15 — new period
        completed = b.process_tick(_tick(1.2610, 1.2611, minutes_offset=15), "GBPUSD")
        assert b.bar_count("GBPUSD", 15) == 1
        bars = b.get_bars("GBPUSD", 15)
        assert bars[0]["open"] == pytest.approx(1.26005)
        assert bars[0]["close"] == pytest.approx(1.26005)
        assert completed == ["GBPUSD:15"]

    def test_ohlc_calculation(self):
        b = BarBuilder()
        b.add_timeframe("GBPUSD", 60)
        # 4 ticks in same bar
        b.process_tick(_tick(1.2600, 1.2601, 0), "GBPUSD")
        b.process_tick(_tick(1.2620, 1.2621, 5), "GBPUSD")  # high
        b.process_tick(_tick(1.2590, 1.2591, 10), "GBPUSD")  # low
        b.process_tick(_tick(1.2610, 1.2611, 15), "GBPUSD")

        # Force finalize by moving to next period
        b.process_tick(_tick(1.2610, 1.2611, 60), "GBPUSD")
        bars = b.get_bars("GBPUSD", 60)
        assert len(bars) == 1
        bar = bars[0]
        assert bar["open"] == pytest.approx(1.26005)  # first mid
        assert bar["high"] == pytest.approx(1.2621)
        assert bar["low"] == pytest.approx(1.2590)
        assert bar["close"] == pytest.approx(1.26105)  # last mid before finalize
        assert bar["volume"] == 4


class TestMaxBars:
    def test_max_bars_trim(self):
        b = BarBuilder(max_bars=3)
        b.add_timeframe("GBPUSD", 1)

        for i in range(10):
            b.process_tick(
                _tick(1.26 + i * 0.001, 1.26 + i * 0.001, minutes_offset=i), "GBPUSD"
            )

        assert b.bar_count("GBPUSD", 1) <= 3

    def test_burst_allocation(self):
        b = BarBuilder(max_bars=5)
        b.add_timeframe("GBPUSD", 1)
        b.set_burst_mode(True)

        for i in range(12):
            b.process_tick(
                _tick(1.26 + i * 0.001, 1.26 + i * 0.001, minutes_offset=i), "GBPUSD"
            )

        # max_bars * 1.5 = 7
        assert b.bar_count("GBPUSD", 1) <= 7


class TestMultiTimeframe:
    def test_multiple_timeframes(self):
        b = BarBuilder()
        b.add_timeframe("GBPUSD", 15)
        b.add_timeframe("GBPUSD", 60)

        # 4 ticks at 15-min boundaries
        for i in range(4):
            b.process_tick(
                _tick(1.26 + i * 0.001, 1.26 + i * 0.001, minutes_offset=i * 15),
                "GBPUSD",
            )

        assert b.bar_count("GBPUSD", 15) == 3  # 3 completed 15-min bars
        assert b.bar_count("GBPUSD", 60) == 0  # still forming 60-min bar


class TestPreload:
    def test_preload_historical_bars(self):
        b = BarBuilder(max_bars=100)
        bars = [
            {
                "time": datetime(2026, 1, 1, i % 24, i // 24 * 15, tzinfo=timezone.utc),
                "open": 1.26,
                "high": 1.27,
                "low": 1.25,
                "close": 1.26,
                "volume": 100,
            }
            for i in range(50)
        ]
        b.preload_bars("GBPUSD", 60, bars)
        assert b.bar_count("GBPUSD", 60) == 50

    def test_preload_trims_to_max(self):
        b = BarBuilder(max_bars=10)
        bars = [
            {"time": i, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}
            for i in range(50)
        ]
        b.preload_bars("GBPUSD", 60, bars)
        assert b.bar_count("GBPUSD", 60) == 10


class TestFinalize:
    def test_finalize_all(self):
        b = BarBuilder()
        b.add_timeframe("GBPUSD", 60)
        b.process_tick(_tick(1.26, 1.261, 0), "GBPUSD")
        assert b.forming_bar("GBPUSD", 60) is not None

        keys = b.finalize_all()
        assert "GBPUSD:60" in keys
        assert b.forming_bar("GBPUSD", 60) is None
        assert b.bar_count("GBPUSD", 60) == 1


class TestCallback:
    def test_bar_close_callback(self):
        b = BarBuilder()
        b.add_timeframe("GBPUSD", 15)
        received = []
        b.on_bar_close = lambda key, bar: received.append((key, bar))

        # Two ticks in different periods
        b.process_tick(_tick(1.26, 1.261, 0), "GBPUSD")
        b.process_tick(_tick(1.27, 1.271, 15), "GBPUSD")

        assert len(received) == 1
        assert received[0][0] == "GBPUSD:15"


class TestBarIntegrity:
    def test_integrity_assertion_passes(self):
        bar = {
            "time": 0,
            "open": 1.26,
            "high": 1.27,
            "low": 1.25,
            "close": 1.26,
            "volume": 1,
        }
        BarBuilder._assert_bar_integrity(bar)  # should not raise

    def test_integrity_assertion_fails_high(self):
        bar = {
            "time": 0,
            "open": 1.28,
            "high": 1.27,
            "low": 1.25,
            "close": 1.26,
            "volume": 1,
        }
        with pytest.raises(AssertionError):
            BarBuilder._assert_bar_integrity(bar)

    def test_integrity_assertion_fails_low(self):
        bar = {
            "time": 0,
            "open": 1.24,
            "high": 1.27,
            "low": 1.25,
            "close": 1.26,
            "volume": 1,
        }
        with pytest.raises(AssertionError):
            BarBuilder._assert_bar_integrity(bar)


class TestThreadSafety:
    def test_concurrent_ticks(self):
        b = BarBuilder()
        b.add_timeframe("GBPUSD", 60)

        errors = []

        def worker(offset):
            try:
                for i in range(100):
                    b.process_tick(
                        _tick(
                            1.26 + (offset + i) * 0.0001,
                            1.26 + (offset + i) * 0.0001,
                            minutes_offset=i,
                        ),
                        "GBPUSD",
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(j,)) for j in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
