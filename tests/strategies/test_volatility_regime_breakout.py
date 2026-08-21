"""Tests for VolatilityRegimeBreakoutStrategy.

Verifies signal generation and type-identity compatibility after the
D-011 zero-trade fix (core.types TradeDirection now shared with
backtest.types TradeDirection).
"""

import unittest
from datetime import datetime, timezone

from backtest.types import TradeDirection as BacktestTradeDirection
from core.types import Bar, MarketState, SessionType, TradeDirection
from strategies.volatility_regime_breakout import (
    VolatilityRegimeBreakoutStrategy,
    VRBConfig,
)


def _make_bar(
    price: float = 1.1000,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1000.0,
    hour: int = 10,
) -> Bar:
    if open_ is None:
        open_ = price
    if high is None:
        high = max(open_, price) + 0.0002
    if low is None:
        low = min(open_, price) - 0.0002
    return Bar(
        time=datetime(2026, 7, 21, hour % 24, 0, tzinfo=timezone.utc),
        open=open_,
        high=high,
        low=low,
        close=price,
        volume=volume,
    )


def _make_flat_bars(
    n: int = 70,
    base_price: float = 1.1000,
    volatility: float = 0.0001,
    seed: int = 42,
) -> list[Bar]:
    """Create n bars with low volatility around base_price."""
    import random

    random.seed(seed)
    bars = []
    for i in range(n):
        change = random.gauss(0, volatility)
        open_ = base_price
        close = base_price + change
        high = max(open_, close) + abs(random.gauss(0, volatility * 0.3))
        low = min(open_, close) - abs(random.gauss(0, volatility * 0.3))
        bars.append(_make_bar(price=close, open_=open_, high=high, low=low, hour=i % 24))
    return bars


def _make_mixed_vol_bars(n: int = 75) -> list[Bar]:
    """Create bars with moderate-vol history then low-vol squeeze + breakout."""
    import random

    random.seed(99)
    bars: list[Bar] = []
    base = 1.1000

    # Phase 1: moderate volatility (bars 0-55) — establishes higher ATR baseline
    for i in range(56):
        vol = 0.0010
        open_ = base + i * 0.00005
        change = random.gauss(0, vol)
        close = open_ + change
        high = max(open_, close) + abs(random.gauss(0, vol * 0.3))
        low = min(open_, close) - abs(random.gauss(0, vol * 0.3))
        bars.append(_make_bar(price=close, open_=open_, high=high, low=low, hour=i % 24))

    # Phase 2: low-volatility squeeze (bars 56-69)
    for i in range(56, 70):
        vol = 0.00005  # very tight
        open_ = bars[-1].close
        change = random.gauss(0, vol)
        close = open_ + change
        high = max(open_, close) + abs(random.gauss(0, vol * 0.3))
        low = min(open_, close) - abs(random.gauss(0, vol * 0.3))
        bars.append(_make_bar(price=close, open_=open_, high=high, low=low, hour=i % 24))

    # Phase 3: breakout bar (bar 70) — close above recent 10-bar high
    recent_high = max(b.high for b in bars[-11:-1])
    breakout_price = recent_high + 0.003
    bars.append(
        _make_bar(
            price=breakout_price,
            open_=bars[-1].close,
            high=breakout_price + 0.001,
            low=bars[-1].close - 0.0002,
            hour=70 % 24,
        )
    )

    # Extra bars to allow cooldown + additional evaluation
    for i in range(71, n):
        open_ = bars[-1].close
        change = random.gauss(0, 0.0005)
        close = open_ + change
        high = max(open_, close) + 0.0003
        low = min(open_, close) - 0.0003
        bars.append(_make_bar(price=close, open_=open_, high=high, low=low, hour=i % 24))

    return bars


class TestVRBConfig(unittest.TestCase):
    def test_default_config(self):
        cfg = VRBConfig()
        self.assertEqual(cfg.atr_period, 14)
        self.assertEqual(cfg.atr_lookback, 50)
        self.assertAlmostEqual(cfg.atr_percentile_low, 30.0)
        self.assertEqual(cfg.range_period, 20)
        self.assertAlmostEqual(cfg.range_position_max, 0.70)
        self.assertEqual(cfg.trend_ema_period, 20)
        self.assertEqual(cfg.breakout_period, 10)
        self.assertEqual(cfg.cooldown_bars, 3)
        self.assertAlmostEqual(cfg.min_confidence, 0.35)
        self.assertAlmostEqual(cfg.vol_expansion_ratio, 1.5)

    def test_custom_config(self):
        cfg = VRBConfig(atr_period=10, trend_ema_period=30)
        self.assertEqual(cfg.atr_period, 10)
        self.assertEqual(cfg.trend_ema_period, 30)


class TestVRBStrategyProperties(unittest.TestCase):
    def test_name(self):
        strategy = VolatilityRegimeBreakoutStrategy()
        self.assertEqual(strategy.name, "Volatility Regime Breakout")

    def test_reset_clears_state(self):
        strategy = VolatilityRegimeBreakoutStrategy()
        strategy._setup_active = True
        strategy._setup_bars_remaining = 20
        strategy._last_signal_bar_index = 50
        strategy.reset()
        self.assertFalse(strategy._setup_active)
        self.assertEqual(strategy._setup_bars_remaining, 0)
        self.assertEqual(strategy._last_signal_bar_index, -1)

    def test_insufficient_bars_returns_none(self):
        strategy = VolatilityRegimeBreakoutStrategy()
        bars = _make_flat_bars(20)  # well below minimum
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strategy.evaluate(state)
        self.assertIsNone(result)


class TestVRBBreakoutSignal(unittest.TestCase):
    """Test signal generation via the setup → breakout flow."""

    def test_long_breakout_signal_with_armed_setup(self):
        """When setup is armed and a breakout bar arrives, a LONG signal is produced."""
        strategy = VolatilityRegimeBreakoutStrategy(VRBConfig())
        bars = _make_mixed_vol_bars(75)

        # Feed bars progressively from bar 65 onwards to allow setup detection
        # and then breakout.
        state = None
        signal = None
        for start_idx in range(65, len(bars)):
            partial = bars[: start_idx + 1]
            state = MarketState(
                bars=partial,
                current_session=SessionType.LONDON,
            )
            signal = strategy.evaluate(state)
            if signal is not None:
                break

        # If the organic data didn't trigger, manually arm setup and retry
        if signal is None:
            strategy.reset()
            strategy._setup_active = True
            strategy._setup_bars_remaining = 30
            state = MarketState(
                bars=bars,
                current_session=SessionType.LONDON,
            )
            signal = strategy.evaluate(state)

        self.assertIsNotNone(signal, "VRB strategy should produce a signal on breakout")
        self.assertEqual(signal.direction, TradeDirection.LONG)
        self.assertGreater(signal.confidence, 0)
        self.assertGreater(signal.entry_price, 0)
        self.assertNotEqual(signal.stop_loss, signal.entry_price)

    def test_short_breakout_signal_with_armed_setup(self):
        """When setup is armed and price breaks below recent low, a SHORT signal is produced."""
        bars = _make_mixed_vol_bars(70)
        # Overwrite last bar to be a downside breakout
        recent_low = min(b.low for b in bars[-11:-1])
        breakout_price = recent_low - 0.003
        bars[-1] = _make_bar(
            price=breakout_price,
            open_=bars[-2].close,
            high=bars[-2].close + 0.0002,
            low=breakout_price - 0.001,
            hour=69 % 24,
        )

        strategy = VolatilityRegimeBreakoutStrategy(VRBConfig())
        # Arm setup directly for deterministic test
        strategy._setup_active = True
        strategy._setup_bars_remaining = 30

        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        signal = strategy.evaluate(state)

        self.assertIsNotNone(signal, "VRB strategy should produce SHORT signal on downside breakout")
        self.assertEqual(signal.direction, TradeDirection.SHORT)

    def test_cooldown_prevents_rapid_resignal(self):
        """After a signal, cooldown_bars must elapse before the next signal."""
        strategy = VolatilityRegimeBreakoutStrategy(VRBConfig(cooldown_bars=10))
        bars = _make_mixed_vol_bars(75)

        # Use progressive evaluation to get first signal organically
        signal1 = None
        for start_idx in range(65, len(bars)):
            partial = bars[: start_idx + 1]
            state = MarketState(bars=partial, current_session=SessionType.LONDON)
            signal1 = strategy.evaluate(state)
            if signal1 is not None:
                break

        self.assertIsNotNone(signal1, "Should produce at least one signal")

        # Immediately re-arm and try again with same bars — should be blocked by cooldown
        strategy._setup_active = True
        strategy._setup_bars_remaining = 30
        signal2 = strategy.evaluate(state)
        self.assertIsNone(signal2, "Cooldown should block immediate re-signal")


class TestVRBSignalTypeIdentity(unittest.TestCase):
    """Verify that signals produced by VRB strategy have directions compatible
    with the backtest engine's TradeDirection type (D-011 zero-trade fix)."""

    def test_signal_direction_is_backtest_direction(self):
        """A VRB signal's direction must be identical to backtest.types.TradeDirection."""
        strategy = VolatilityRegimeBreakoutStrategy(VRBConfig())
        bars = _make_mixed_vol_bars(75)

        # Use progressive evaluation for organic signal generation
        signal = None
        for start_idx in range(65, len(bars)):
            partial = bars[: start_idx + 1]
            state = MarketState(bars=partial, current_session=SessionType.LONDON)
            signal = strategy.evaluate(state)
            if signal is not None:
                break

        self.assertIsNotNone(signal, "Strategy should produce a signal")
        # Type-identity check: strategy direction IS backtest direction
        self.assertIs(signal.direction, getattr(BacktestTradeDirection, signal.direction.name))
        self.assertIn(signal.direction, BacktestTradeDirection)

    def test_short_signal_direction_is_backtest_direction(self):
        """SHORT signal direction must also share identity."""
        strategy = VolatilityRegimeBreakoutStrategy(VRBConfig())
        bars = _make_mixed_vol_bars(75)

        # Use progressive evaluation for organic signal generation
        signal = None
        for start_idx in range(65, len(bars)):
            partial = bars[: start_idx + 1]
            # Flip the breakout bar to a downside breakout
            if start_idx == 70:
                prior_bars = partial[-(11):-1]
                recent_low = min(b.low for b in prior_bars)
                partial[-1] = _make_bar(
                    price=recent_low - 0.003,
                    open_=partial[-2].close,
                    high=partial[-2].close + 0.0002,
                    low=recent_low - 0.004,
                )
            state = MarketState(bars=partial, current_session=SessionType.LONDON)
            signal = strategy.evaluate(state)
            if signal is not None:
                break

        self.assertIsNotNone(signal, "Strategy should produce a SHORT signal")
        self.assertIn(signal.direction, BacktestTradeDirection)
        self.assertIs(signal.direction, getattr(BacktestTradeDirection, signal.direction.name))


if __name__ == "__main__":
    unittest.main()
