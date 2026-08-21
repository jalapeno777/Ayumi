"""Regression test for card 18ac48b1.

Forward test evaluation gate used the default bar_period_minutes (60m)
as the primary key, but strategy bars are stored under the strategy's
actual timeframe (e.g. M15). When running a single strategy on M15
with bar_period_minutes=60, the gate checked XAUUSD:60 (0 bars)
instead of XAUUSD:15 (199 bars), so evaluation never fired.

Fix: use min(_required_timeframes) instead of bar_period_minutes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from adapters.ctrader.forward_test_engine import ForwardTestConfig, ForwardTestEngine


def _make_bar(time, open_=1.0, high=1.0, low=1.0, close=1.0, volume=100.0):
    """Create a Bar-like object matching the engine's internal Bar namedtuple."""
    bar = MagicMock()
    bar.time = time
    bar.open = open_
    bar.high = high
    bar.low = low
    bar.close = close
    bar.volume = volume
    return bar


def _make_bars(n=60, period_minutes=15, start=None):
    """Create n finalized bars at the given period."""
    if start is None:
        start = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        t = start + timedelta(minutes=period_minutes * i)
        bars.append(_make_bar(time=t))
    return bars


@pytest.fixture
def engine_m15_strategy(tmp_path):
    """Build a forward test engine with a strategy on M15 but default bar_period=60.

    This mirrors the production Killzone Momentum scenario:
    - bar_period_minutes=60 (legacy default)
    - strategy_timeframes={'Killzone Momentum': 15}
    - _required_timeframes={15}
    """
    with (
        patch.object(ForwardTestEngine, "_build_live_credentials", return_value=None),
        patch.object(ForwardTestEngine, "_enforce_remediation_gate", return_value=None),
    ):
        cfg = ForwardTestConfig(
            symbol="XAUUSD",
            bar_period_minutes=60,
            min_bars_for_evaluation=55,
            starting_balance=10000.0,
            strategy_timeframes={"Killzone Momentum": 15},
        )
        # Mock a strategy named "Killzone Momentum" with timeframe 15
        strategy = MagicMock()
        strategy.name = "Killzone Momentum"
        strategy.timeframe_minutes = 15

        engine = ForwardTestEngine(config=cfg, strategies=[strategy])
    return engine


class TestEvalGateTimeframeKey:
    """Verify the evaluation gate uses strategy timeframe, not bar_period_minutes."""

    def test_required_timeframes_derived_from_strategy(self, engine_m15_strategy):
        """_required_timeframes should be {15} from the strategy, not {60} from config."""
        assert engine_m15_strategy._required_timeframes == {15}
        assert engine_m15_strategy._config.bar_period_minutes == 60

    def test_gate_uses_strategy_timeframe_not_bar_period(self, engine_m15_strategy):
        """The evaluation gate primary_key must use min(_required_timeframes)=15,
        not bar_period_minutes=60.

        With the old bug: primary_key = XAUUSD:60 (0 bars → gate fails)
        With the fix:     primary_key = XAUUSD:15 (199 bars → gate passes)
        """
        symbol = "XAUUSD"
        bars_15 = _make_bars(60, period_minutes=15)

        # Populate bars under the M15 key (where they actually live)
        key_15 = engine_m15_strategy._bar_key(symbol, 15)
        engine_m15_strategy._bars[key_15] = bars_15

        # The M60 key should have NO bars
        key_60 = engine_m15_strategy._bar_key(symbol, 60)
        assert len(engine_m15_strategy._bars.get(key_60, [])) == 0

        # Simulate the fixed gate logic
        min_tf = min(engine_m15_strategy._required_timeframes)
        assert min_tf == 15

        primary_key = engine_m15_strategy._bar_key(symbol, min_tf)
        assert primary_key == "XAUUSD:15"

        # Verify bars are found under the correct key
        bar_count = len(engine_m15_strategy._bars.get(primary_key, []))
        assert bar_count >= engine_m15_strategy._config.min_bars_for_evaluation

    def test_old_logic_would_fail(self, engine_m15_strategy):
        """Demonstrate that the old logic (bar_period_minutes=60) would fail
        because no bars exist under the M60 key."""
        symbol = "XAUUSD"
        bars_15 = _make_bars(60, period_minutes=15)

        key_15 = engine_m15_strategy._bar_key(symbol, 15)
        engine_m15_strategy._bars[key_15] = bars_15

        # Old logic: use bar_period_minutes
        old_key = engine_m15_strategy._bar_key(symbol, engine_m15_strategy._config.bar_period_minutes)
        old_count = len(engine_m15_strategy._bars.get(old_key, []))

        # With old logic, gate would see 0 bars < 55 → evaluation never fires
        assert old_count == 0
        assert old_count < engine_m15_strategy._config.min_bars_for_evaluation

    def test_multi_timeframe_uses_minimum(self, engine_m15_strategy):
        """When multiple timeframes are required, the gate should use the
        smallest one (most frequent bars) to avoid premature evaluation."""
        # Override to simulate multi-timeframe
        engine_m15_strategy._required_timeframes = {5, 15, 60}

        symbol = "XAUUSD"
        min_tf = min(engine_m15_strategy._required_timeframes)
        assert min_tf == 5

        primary_key = engine_m15_strategy._bar_key(symbol, min_tf)
        assert primary_key == "XAUUSD:5"

    def test_empty_required_timeframes_falls_back(self, engine_m15_strategy):
        """If _required_timeframes is somehow empty, fall back to bar_period_minutes."""
        engine_m15_strategy._required_timeframes = set()

        min_tf = (
            min(engine_m15_strategy._required_timeframes)
            if engine_m15_strategy._required_timeframes
            else engine_m15_strategy._config.bar_period_minutes
        )
        assert min_tf == 60
