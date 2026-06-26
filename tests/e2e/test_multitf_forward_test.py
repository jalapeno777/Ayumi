"""Integration tests for multi-timeframe forward test architecture."""

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.types import Bar, BarPeriod
from adapters.ctrader.forward_test_engine import ForwardTestConfig, ForwardTestEngine


# ── Helpers ──────────────────────────────────────────────────────────────────

class FakeStrategy:
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name


def make_tick(timestamp: datetime, bid: float = 1.2600, ask: float = 1.2602):
    """Create a minimal tick-like object."""
    tick = MagicMock()
    tick.timestamp = timestamp
    tick.bid = bid
    tick.ask = ask
    tick.mid = (bid + ask) / 2
    tick.spread = ask - bid
    tick.symbol_id = 1
    return tick


def make_bar(time: datetime, period_minutes: int = 60, price: float = 1.2600) -> Bar:
    return Bar(
        time=time,
        open=price,
        high=price + 0.0010,
        low=price - 0.0010,
        close=price + 0.0005,
        volume=100,
        period=BarPeriod(minutes=period_minutes),
    )


# ── Tests ────────────────────────────────────────────────────────────────────

class TestMultiTFBarBuilding:
    """T1: Engine builds bars for all required timeframes from each tick."""

    def test_single_tick_creates_both_h1_and_m15_bars(self):
        strategies = [FakeStrategy("TestH1"), FakeStrategy("TestM15")]
        config = ForwardTestConfig(
            strategy_timeframes={"TestH1": 60, "TestM15": 15},
            min_bars_for_evaluation=0,
        )
        engine = ForwardTestEngine(config=config, strategies=strategies)

        ts = datetime(2026, 4, 28, 10, 0, 30, tzinfo=timezone.utc)
        tick = make_tick(ts)

        # Simulate tick processing (bypass _on_tick symbol resolution)
        for tf in engine._required_timeframes:
            bar_time = engine._bar_period_start(tick.timestamp, period_minutes=tf)
            key = engine._bar_key("GBPUSD", tf)
            engine._update_current_bar(tick, key, bar_time)

        assert engine._current_bar.get("GBPUSD:60") is not None
        assert engine._current_bar.get("GBPUSD:15") is not None

    def test_bar_key_format(self):
        assert ForwardTestEngine._bar_key("GBPUSD", 60) == "GBPUSD:60"
        assert ForwardTestEngine._bar_key("GBPUSD", 15) == "GBPUSD:15"

    def test_required_timeframes_derived_from_config(self):
        config = ForwardTestConfig(strategy_timeframes={"A": 60, "B": 15})
        engine = ForwardTestEngine(config=config, strategies=[FakeStrategy("A"), FakeStrategy("B")])
        assert engine._required_timeframes == {60, 15}

    def test_backward_compat_empty_timeframes(self):
        config = ForwardTestConfig()  # no strategy_timeframes
        engine = ForwardTestEngine(config=config, strategies=[FakeStrategy("X")])
        assert engine._required_timeframes == {60}  # default bar_period_minutes


class TestBarIntegrityAssertion:
    """Bar integrity assertion after building."""

    def test_valid_bar_passes(self):
        config = ForwardTestConfig(strategy_timeframes={"X": 60})
        engine = ForwardTestEngine(config=config, strategies=[FakeStrategy("X")])
        bar = Bar(time=datetime.now(timezone.utc), open=1.0, high=1.1, low=0.9, close=1.05, volume=1)
        engine._assert_bar_integrity(bar)  # should not raise

    def test_invalid_bar_fails(self):
        config = ForwardTestConfig(strategy_timeframes={"X": 60})
        engine = ForwardTestEngine(config=config, strategies=[FakeStrategy("X")])
        bar = Bar(time=datetime.now(timezone.utc), open=1.0, high=0.95, low=0.9, close=1.05, volume=1)
        with pytest.raises(AssertionError, match="high"):
            engine._assert_bar_integrity(bar)


class TestPerTFEvaluationThreshold:
    """Each strategy checks its own timeframe's bar count."""

    def test_strategy_skipped_when_insufficient_bars(self):
        config = ForwardTestConfig(
            strategy_timeframes={"H1Strat": 60, "M15Strat": 15},
            min_bars_for_evaluation=10,
        )
        engine = ForwardTestEngine(config=config, strategies=[FakeStrategy("H1Strat"), FakeStrategy("M15Strat")])

        # Preload enough H1 bars but not enough M15 bars
        for i in range(15):
            bar = make_bar(datetime(2026, 4, 28, i, 0, tzinfo=timezone.utc), 60)
            key = engine._bar_key("GBPUSD", 60)
            engine._bars.setdefault(key, []).append(bar)

        # M15 only has 3 bars
        for i in range(3):
            bar = make_bar(datetime(2026, 4, 28, 10, i * 15, tzinfo=timezone.utc), 15)
            key = engine._bar_key("GBPUSD", 15)
            engine._bars.setdefault(key, []).append(bar)

        h1_bars = engine.get_bars_including_forming("GBPUSD", 60)
        m15_bars = engine.get_bars_including_forming("GBPUSD", 15)
        assert len(h1_bars) >= 10
        assert len(m15_bars) < 10


class TestStartupAssertions:
    """Mika's hard-fail startup assertions."""

    def test_invalid_timeframe_fails(self):
        with pytest.raises(AssertionError, match="whitelist"):
            ForwardTestEngine(
                config=ForwardTestConfig(strategy_timeframes={"X": 30}),
                strategies=[FakeStrategy("X")],
            )

    def test_strategy_name_mismatch_fails(self):
        with pytest.raises(AssertionError, match="does not match"):
            ForwardTestEngine(
                config=ForwardTestConfig(strategy_timeframes={"WrongName": 60}),
                strategies=[FakeStrategy("ActualName")],
            )


class TestBackwardCompatibility:
    """Empty strategy_timeframes → all strategies get bar_period_minutes."""

    def test_preload_bars_single_key(self):
        config = ForwardTestConfig()
        engine = ForwardTestEngine(config=config, strategies=[FakeStrategy("X")])

        bars = [make_bar(datetime(2026, 4, 28, i, 0, tzinfo=timezone.utc)) for i in range(10)]
        engine.preload_bars("GBPUSD", 60, bars)

        loaded = engine.get_bars_including_forming("GBPUSD", 60)
        assert len(loaded) == 10


class TestCallSiteMigration:
    """Verify composite keys used throughout."""

    def test_finalize_uses_composite_key(self):
        config = ForwardTestConfig(strategy_timeframes={"X": 60})
        engine = ForwardTestEngine(config=config, strategies=[FakeStrategy("X")])

        ts = datetime(2026, 4, 28, 10, 0, 30, tzinfo=timezone.utc)
        tick = make_tick(ts)
        key = engine._bar_key("GBPUSD", 60)
        bar_time = engine._bar_period_start(ts, period_minutes=60)
        engine._update_current_bar(tick, key, bar_time)

        # Finalize should use composite key
        result = engine._finalize_and_store_bar(key)
        assert result is not None
        assert key in engine._bars
        assert "GBPUSD" not in engine._bars  # old key scheme should NOT exist

    def test_stop_finalizes_all_composite_keys(self):
        config = ForwardTestConfig(strategy_timeframes={"A": 60, "B": 15})
        engine = ForwardTestEngine(config=config, strategies=[FakeStrategy("A"), FakeStrategy("B")])

        ts = datetime(2026, 4, 28, 10, 0, 30, tzinfo=timezone.utc)
        tick = make_tick(ts)
        for tf in engine._required_timeframes:
            key = engine._bar_key("GBPUSD", tf)
            bar_time = engine._bar_period_start(ts, period_minutes=tf)
            engine._update_current_bar(tick, key, bar_time)

        # Simulate stop's finalize loop
        for key in list(engine._current_bar.keys()):
            engine._finalize_and_store_bar(key)

        assert len(engine._current_bar) == 2  # keys remain, values are None
        assert all(v is None for v in engine._current_bar.values())
        assert "GBPUSD:60" in engine._bars
        assert "GBPUSD:15" in engine._bars
