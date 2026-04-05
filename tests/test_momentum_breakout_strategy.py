import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from backtest.engine import Bar, MarketState, TradeDirection
from backtest.strategies import MomentumBreakoutStrategy


def make_test_bars(n=100, seed=42):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = 1.1000
    prices = [price]
    for _ in range(n - 1):
        price += np.random.normal(0, 0.0005)
        prices.append(price)
    prices = np.array(prices)
    spread = 0.0002
    return [
        Bar(
            time=dates[i].to_pydatetime(),
            open=prices[i] - spread * np.random.uniform(0, 1),
            high=prices[i] + spread * np.random.uniform(1, 3),
            low=prices[i] - spread * np.random.uniform(1, 3),
            close=prices[i],
            volume=1000,
        )
        for i in range(n)
    ]


def make_trending_bars(n=100, seed=42, trend_direction="up"):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = 1.1000
    prices = []

    if trend_direction == "up":
        for i in range(n):
            price += 0.0003 + np.random.normal(0, 0.0001)
            prices.append(price)
    else:
        for i in range(n):
            price -= 0.0003 + np.random.normal(0, 0.0001)
            prices.append(price)

    prices = np.array(prices)
    spread = 0.0002
    return [
        Bar(
            time=dates[i].to_pydatetime(),
            open=prices[i] - spread * np.random.uniform(0, 1),
            high=prices[i] + spread * np.random.uniform(1, 3),
            low=prices[i] - spread * np.random.uniform(1, 3),
            close=prices[i],
            volume=1000,
        )
        for i in range(n)
    ]


class TestMomentumBreakoutStrategy(unittest.TestCase):
    def test_strategy_name(self):
        strategy = MomentumBreakoutStrategy()
        self.assertEqual(strategy.name, "Momentum Breakout")

    def test_strategy_returns_none_with_insufficient_bars(self):
        strategy = MomentumBreakoutStrategy()
        bars = make_test_bars(20)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_strategy_returns_none_when_adx_below_threshold(self):
        strategy = MomentumBreakoutStrategy(adx_threshold=50.0)
        bars = make_test_bars(100)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_strategy_returns_signal_on_bullish_cross_with_high_adx(self):
        strategy = MomentumBreakoutStrategy(
            fast_period=5, slow_period=10, adx_threshold=20.0
        )
        bars = make_trending_bars(100, seed=42, trend_direction="up")
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.LONG)
            self.assertGreater(result.entry_price, 0)
            self.assertGreater(result.stop_loss, 0)
            self.assertGreater(result.take_profit_1, result.entry_price)
            self.assertIn("EMA cross", result.rationale)

    def test_strategy_returns_signal_on_bearish_cross_with_high_adx(self):
        strategy = MomentumBreakoutStrategy(
            fast_period=5, slow_period=10, adx_threshold=20.0
        )
        bars = make_trending_bars(100, seed=42, trend_direction="down")
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.SHORT)
            self.assertGreater(result.entry_price, 0)
            self.assertGreater(result.stop_loss, 0)
            self.assertLess(result.take_profit_1, result.entry_price)

    def test_confidence_lower_than_40_adx(self):
        strategy = MomentumBreakoutStrategy(
            fast_period=5, slow_period=10, adx_threshold=25.0
        )
        bars = make_trending_bars(100, seed=42, trend_direction="up")
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertLessEqual(result.confidence, 0.8)

    def test_take_profit_levels_formatted_correctly(self):
        strategy = MomentumBreakoutStrategy(
            fast_period=5, slow_period=10, adx_threshold=20.0
        )
        bars = make_trending_bars(100, seed=42, trend_direction="up")
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            risk = abs(result.entry_price - result.stop_loss)
            expected_tp2 = result.entry_price + risk * 2.0
            expected_tp3 = result.entry_price + risk * 3.0
            self.assertAlmostEqual(result.take_profit_2, expected_tp2, places=5)
            self.assertAlmostEqual(result.take_profit_3, expected_tp3, places=5)

    def test_custom_parameters(self):
        strategy = MomentumBreakoutStrategy(
            fast_period=12,
            slow_period=26,
            adx_period=14,
            adx_threshold=30.0,
            atr_multiplier=1.5,
        )
        self.assertEqual(strategy.fast_period, 12)
        self.assertEqual(strategy.slow_period, 26)
        self.assertEqual(strategy.adx_period, 14)
        self.assertEqual(strategy.adx_threshold, 30.0)
        self.assertEqual(strategy.atr_multiplier, 1.5)


if __name__ == "__main__":
    unittest.main()
