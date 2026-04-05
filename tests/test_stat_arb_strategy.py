import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

import numpy as np
import pandas as pd

from backtest.engine import Bar, MarketState, TradeDirection
from backtest.stat_arb import StatArbStrategy, StatArbBacktestResult


def make_test_bars(n=100, seed=42):
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


def make_cointegrated_pair_bars(n=100, seed=42):
    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = 0.8500
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


class TestStatArbStrategy(unittest.TestCase):
    def test_strategy_name(self):
        strategy = StatArbStrategy()
        self.assertEqual(strategy.name, "Statistical Arbitrage")

    def test_strategy_with_insufficient_bars(self):
        strategy = StatArbStrategy(lookback=60)
        bars_a = make_test_bars(20)
        state = MarketState(bars=bars_a)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_strategy_without_pair_b_bars(self):
        strategy = StatArbStrategy(lookback=60)
        bars_a = make_test_bars(100)
        state = MarketState(bars=bars_a)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_set_pair_b_bars(self):
        strategy = StatArbStrategy(lookback=60)
        bars_b = make_cointegrated_pair_bars(100)
        strategy.set_pair_b_bars(bars_b)
        self.assertEqual(len(strategy._pair_b_bars), 100)

    def test_reset(self):
        strategy = StatArbStrategy(lookback=60)
        strategy._position_open = True
        strategy._last_signal = "entry_long"
        strategy.reset()
        self.assertFalse(strategy._position_open)
        self.assertIsNone(strategy._last_signal)

    def test_custom_parameters(self):
        strategy = StatArbStrategy(
            lookback=80,
            entry_threshold=1.5,
            exit_threshold=0.1,
            stop_loss_threshold=2.5,
            atr_multiplier=1.5,
        )
        self.assertEqual(strategy.lookback, 80)
        self.assertEqual(strategy.entry_threshold, 1.5)
        self.assertEqual(strategy.exit_threshold, 0.1)
        self.assertEqual(strategy.stop_loss_threshold, 2.5)
        self.assertEqual(strategy.atr_multiplier, 1.5)


class TestStatArbBacktestResult(unittest.TestCase):
    def test_initialization(self):
        result = StatArbBacktestResult()
        self.assertEqual(result.total_trades, 0)
        self.assertEqual(result.winning_trades, 0)
        self.assertEqual(result.losing_trades, 0)
        self.assertEqual(result.total_pnl, 0.0)
        self.assertEqual(result.max_drawdown, 0.0)
        self.assertEqual(result.z_scores, [])
        self.assertEqual(result.signals, [])

    def test_add_signal(self):
        result = StatArbBacktestResult()
        result.add_signal("entry_long", 2.5)
        self.assertEqual(len(result.signals), 1)
        self.assertEqual(len(result.z_scores), 1)
        self.assertEqual(result.signals[0], "entry_long")
        self.assertEqual(result.z_scores[0], 2.5)

    def test_add_signal_with_none_z_score(self):
        result = StatArbBacktestResult()
        result.add_signal("entry_long", None)
        self.assertEqual(len(result.signals), 1)
        self.assertEqual(len(result.z_scores), 0)


class TestStatArbStrategyIntegration(unittest.TestCase):
    def test_full_evaluation_cycle(self):
        strategy = StatArbStrategy(
            lookback=60,
            entry_threshold=2.0,
            exit_threshold=0.0,
            stop_loss_threshold=3.0,
        )

        bars_a = make_test_bars(100)
        bars_b = make_cointegrated_pair_bars(100)
        strategy.set_pair_b_bars(bars_b)

        state = MarketState(bars=bars_a)
        result = strategy.evaluate(state)

        if result is not None:
            self.assertIn(result.direction, [TradeDirection.LONG, TradeDirection.SHORT])
            self.assertGreater(result.entry_price, 0)
            self.assertGreater(result.stop_loss, 0)
            self.assertIn("StatArb", result.rationale)


if __name__ == "__main__":
    unittest.main()
