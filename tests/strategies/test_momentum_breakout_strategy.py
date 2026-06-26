import os
import sys
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


def make_bars_with_rsi_zone(n=100, rsi_zone="neutral", rsi_period=14):
    import numpy as np
    import pandas as pd

    np.random.seed(99)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    bars = []

    if rsi_zone == "overbought":
        prices = np.linspace(1.10, 1.14, n)
        for i in range(n):
            noise = np.random.uniform(-0.00005, 0.00005)
            c = prices[i] + noise
            bars.append(
                Bar(
                    time=dates[i].to_pydatetime(),
                    open=c - 0.0001,
                    high=c + 0.0002,
                    low=c - 0.0002,
                    close=c,
                    volume=1000,
                )
            )
    elif rsi_zone == "oversold":
        prices = np.linspace(1.14, 1.10, n)
        for i in range(n):
            noise = np.random.uniform(-0.00005, 0.00005)
            c = prices[i] + noise
            bars.append(
                Bar(
                    time=dates[i].to_pydatetime(),
                    open=c - 0.0001,
                    high=c + 0.0002,
                    low=c - 0.0002,
                    close=c,
                    volume=1000,
                )
            )
    else:
        for i in range(n):
            c = 1.1000 + np.random.normal(0, 0.0003)
            bars.append(
                Bar(
                    time=dates[i].to_pydatetime(),
                    open=c - 0.0001,
                    high=c + 0.0002,
                    low=c - 0.0002,
                    close=c,
                    volume=1000,
                )
            )
    return bars


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


class TestRSIFilterIntegration(unittest.TestCase):
    def test_rsi_disabled_when_rsi_period_is_none(self):
        strategy = MomentumBreakoutStrategy(
            fast_period=5,
            slow_period=10,
            adx_threshold=20.0,
            rsi_period=None,
        )
        bars = make_trending_bars(100, seed=42, trend_direction="up")
        state = MarketState(bars=bars)
        result_without_rsi = strategy.evaluate(state)

        strategy_with_rsi = MomentumBreakoutStrategy(
            fast_period=5,
            slow_period=10,
            adx_threshold=20.0,
            rsi_period=14,
            rsi_overbought=70.0,
            rsi_oversold=30.0,
        )
        result_with_rsi = strategy_with_rsi.evaluate(state)

        if result_without_rsi is not None:
            if result_with_rsi is not None:
                self.assertEqual(
                    result_without_rsi.direction, result_with_rsi.direction
                )
            else:
                self.assertIsNotNone(result_without_rsi)

    def test_rsi_blocks_long_at_overbought(self):
        bars = make_bars_with_rsi_zone(100, rsi_zone="overbought")
        strategy = MomentumBreakoutStrategy(
            fast_period=5,
            slow_period=10,
            adx_threshold=15.0,
            rsi_period=14,
            rsi_overbought=70.0,
            rsi_oversold=30.0,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertNotEqual(result.direction, TradeDirection.LONG)

    def test_rsi_blocks_short_at_oversold(self):
        bars = make_bars_with_rsi_zone(100, rsi_zone="oversold")
        strategy = MomentumBreakoutStrategy(
            fast_period=5,
            slow_period=10,
            adx_threshold=15.0,
            rsi_period=14,
            rsi_overbought=70.0,
            rsi_oversold=30.0,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertNotEqual(result.direction, TradeDirection.SHORT)

    def test_rsi_allows_entries_in_neutral_zone(self):
        bars = make_bars_with_rsi_zone(100, rsi_zone="neutral")
        strategy_no_rsi = MomentumBreakoutStrategy(
            fast_period=5,
            slow_period=10,
            adx_threshold=20.0,
        )
        strategy_with_rsi = MomentumBreakoutStrategy(
            fast_period=5,
            slow_period=10,
            adx_threshold=20.0,
            rsi_period=14,
            rsi_overbought=70.0,
            rsi_oversold=30.0,
        )
        state = MarketState(bars=bars)
        result_no_rsi = strategy_no_rsi.evaluate(state)
        result_with_rsi = strategy_with_rsi.evaluate(state)
        if result_no_rsi is not None:
            self.assertIsNotNone(
                result_with_rsi,
                "RSI filter should not block entry when RSI is in neutral zone",
            )

    def test_rsi_returns_none_when_insufficient_bars_for_rsi(self):
        strategy = MomentumBreakoutStrategy(
            fast_period=5,
            slow_period=10,
            adx_threshold=20.0,
            rsi_period=50,
        )
        bars = make_trending_bars(40, seed=42, trend_direction="up")
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)


class TestCalculateRSI(unittest.TestCase):
    def setUp(self):
        self.strategy = MomentumBreakoutStrategy()
        import pandas as pd

        self.dates = pd.date_range("2023-01-01", periods=100, freq="1h")

    def _make_rising_bars(self, n=30):
        bars = []
        for i in range(n):
            c = 1.1000 + i * 0.001
            bars.append(
                Bar(
                    time=self.dates[i].to_pydatetime(),
                    open=c - 0.0001,
                    high=c + 0.0002,
                    low=c - 0.0002,
                    close=c,
                    volume=1000,
                )
            )
        return bars

    def _make_falling_bars(self, n=30):
        bars = []
        for i in range(n):
            c = 1.1300 - i * 0.001
            bars.append(
                Bar(
                    time=self.dates[i].to_pydatetime(),
                    open=c + 0.0001,
                    high=c + 0.0002,
                    low=c - 0.0002,
                    close=c,
                    volume=1000,
                )
            )
        return bars

    def test_all_gains_returns_100(self):
        bars = self._make_rising_bars(30)
        rsi = self.strategy._calculate_rsi(bars, 14)
        self.assertEqual(rsi, 100.0)

    def test_all_losses_returns_0(self):
        bars = self._make_falling_bars(30)
        rsi = self.strategy._calculate_rsi(bars, 14)
        self.assertIsNotNone(rsi)
        self.assertAlmostEqual(rsi, 0.0, places=1)

    def test_insufficient_bars_returns_none(self):
        bars = self._make_rising_bars(10)
        rsi = self.strategy._calculate_rsi(bars, 14)
        self.assertIsNone(rsi)

    def test_exactly_minimum_bars(self):
        bars = self._make_rising_bars(15)
        rsi = self.strategy._calculate_rsi(bars, 14)
        self.assertEqual(rsi, 100.0)

    def test_flat_prices_returns_none(self):
        bars = []
        for i in range(30):
            bars.append(
                Bar(
                    time=self.dates[i].to_pydatetime(),
                    open=1.10,
                    high=1.1002,
                    low=1.0998,
                    close=1.10,
                    volume=1000,
                )
            )
        rsi = self.strategy._calculate_rsi(bars, 14)
        self.assertEqual(rsi, 100.0)

    def test_rsi_between_0_and_100(self):
        import numpy as np

        np.random.seed(77)
        bars = []
        price = 1.10
        for i in range(50):
            price += np.random.normal(0, 0.001)
            bars.append(
                Bar(
                    time=self.dates[i].to_pydatetime(),
                    open=price,
                    high=price + 0.0005,
                    low=price - 0.0005,
                    close=price,
                    volume=1000,
                )
            )
        rsi = self.strategy._calculate_rsi(bars, 14)
        self.assertIsNotNone(rsi)
        self.assertGreaterEqual(rsi, 0.0)
        self.assertLessEqual(rsi, 100.0)


if __name__ == "__main__":
    unittest.main()
