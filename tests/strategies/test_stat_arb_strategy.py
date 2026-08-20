import unittest

import numpy as np
import pandas as pd
from backtest.engine import Bar, MarketState, TradeDirection
from backtest.stat_arb import StatArbBacktestResult, StatArbStrategy


def make_cointegrated_pair_bars(n=300, base_price=1.1000, seed=42):
    """Generate cointegrated bar pairs using common-factor model."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")

    common = np.cumsum(rng.normal(0, 0.001, n))
    prices_a = base_price + 0.5 * common + rng.normal(0, 0.01, n)
    prices_b = base_price * 0.77 + 0.4 * common + rng.normal(0, 0.01, n)

    spread = 0.0002
    bars_a = [
        Bar(
            time=dates[i].to_pydatetime(),
            open=prices_a[i] - spread * rng.uniform(0, 1),
            high=prices_a[i] + spread * rng.uniform(1, 3),
            low=prices_a[i] - spread * rng.uniform(1, 3),
            close=prices_a[i],
            volume=1000,
        )
        for i in range(n)
    ]
    bars_b = [
        Bar(
            time=dates[i].to_pydatetime(),
            open=prices_b[i] - spread * rng.uniform(0, 1),
            high=prices_b[i] + spread * rng.uniform(1, 3),
            low=prices_b[i] - spread * rng.uniform(1, 3),
            close=prices_b[i],
            volume=1000,
        )
        for i in range(n)
    ]
    return bars_a, bars_b


def make_non_cointegrated_bars(n=200, seed=42):
    """Generate independent random walk bars (not cointegrated)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")

    price_a = 1.1000
    prices_a = [price_a]
    for _ in range(n - 1):
        price_a += rng.normal(0, 0.002)
        prices_a.append(price_a)
    prices_a = np.array(prices_a)

    price_b = 0.8500
    prices_b = [price_b]
    for _ in range(n - 1):
        price_b += rng.normal(0, 0.003)
        prices_b.append(price_b)
    prices_b = np.array(prices_b)

    spread = 0.0002
    bars_a = [
        Bar(
            time=dates[i].to_pydatetime(),
            open=prices_a[i] - spread * rng.uniform(0, 1),
            high=prices_a[i] + spread * rng.uniform(1, 3),
            low=prices_a[i] - spread * rng.uniform(1, 3),
            close=prices_a[i],
            volume=1000,
        )
        for i in range(n)
    ]
    bars_b = [
        Bar(
            time=dates[i].to_pydatetime(),
            open=prices_b[i] - spread * rng.uniform(0, 1),
            high=prices_b[i] + spread * rng.uniform(1, 3),
            low=prices_b[i] - spread * rng.uniform(1, 3),
            close=prices_b[i],
            volume=1000,
        )
        for i in range(n)
    ]
    return bars_a, bars_b


class TestStatArbStrategy(unittest.TestCase):
    def test_strategy_name(self):
        strategy = StatArbStrategy()
        self.assertEqual(strategy.name, "Statistical Arbitrage")

    def test_strategy_with_insufficient_bars(self):
        strategy = StatArbStrategy(lookback=60)
        bars_a, bars_b = make_cointegrated_pair_bars(20)
        strategy.set_pair_b_bars(bars_b)
        state = MarketState(bars=bars_a)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_strategy_without_pair_b_bars(self):
        strategy = StatArbStrategy(lookback=60)
        bars_a, _ = make_cointegrated_pair_bars(100)
        state = MarketState(bars=bars_a)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_set_pair_b_bars(self):
        strategy = StatArbStrategy(lookback=60)
        bars_b = make_cointegrated_pair_bars(100)[1]
        strategy.set_pair_b_bars(bars_b)
        self.assertEqual(len(strategy._pair_b_bars), 100)

    def test_reset_clears_state(self):
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

    def test_cointegration_gate_filters_most_bars(self):
        strategy = StatArbStrategy(
            lookback=60,
            entry_threshold=2.0,
            exit_threshold=0.0,
            stop_loss_threshold=3.0,
        )
        bars_a, bars_b = make_cointegrated_pair_bars(300, seed=42)
        strategy.set_pair_b_bars(bars_b)

        evaluated = 0
        passed_coint = 0
        for i in range(61, len(bars_a)):
            state = MarketState(bars=bars_a[:i])
            result = strategy.evaluate(state)
            evaluated += 1
            if result is not None:
                passed_coint += 1

        self.assertGreater(evaluated, 0)
        rate = passed_coint / evaluated
        self.assertLess(
            rate,
            0.95,
            "Cointegration gate should filter some bars (not all pass)",
        )

    def test_cointegrated_data_produces_entry_signal(self):
        strategy = StatArbStrategy(
            lookback=60,
            entry_threshold=1.5,
            exit_threshold=0.0,
            stop_loss_threshold=5.0,
        )
        bars_a, bars_b = make_cointegrated_pair_bars(500, seed=42)
        strategy.set_pair_b_bars(bars_b)

        found_entry = False
        for i in range(61, len(bars_a)):
            state = MarketState(bars=bars_a[:i])
            result = strategy.evaluate(state)
            if result is not None:
                found_entry = True
                self.assertIn(result.direction, [TradeDirection.LONG, TradeDirection.SHORT])
                self.assertGreater(result.entry_price, 0)
                self.assertGreater(result.confidence, 0)
                self.assertGreater(result.stop_loss, 0)
                self.assertIn("StatArb", result.rationale)
                self.assertIn("spread", result.rationale)
                break

        self.assertTrue(found_entry, "Should produce at least one entry signal")

    def test_signal_has_valid_sl_tp_relationship(self):
        strategy = StatArbStrategy(
            lookback=60,
            entry_threshold=1.5,
            exit_threshold=0.0,
            stop_loss_threshold=5.0,
        )
        bars_a, bars_b = make_cointegrated_pair_bars(500, seed=42)
        strategy.set_pair_b_bars(bars_b)

        for i in range(61, len(bars_a)):
            state = MarketState(bars=bars_a[:i])
            result = strategy.evaluate(state)
            if result is not None and "entry" in result.rationale:
                entry = result.entry_price
                sl = result.stop_loss
                if result.direction == TradeDirection.LONG:
                    self.assertLess(sl, entry, "Long SL should be below entry")
                    self.assertGreater(result.take_profit_1, entry)
                else:
                    self.assertGreater(sl, entry, "Short SL should be above entry")
                    self.assertLess(result.take_profit_1, entry)
                break

    def test_get_current_z_score(self):
        strategy = StatArbStrategy(lookback=60)
        bars_a, bars_b = make_cointegrated_pair_bars(200)
        strategy.set_pair_b_bars(bars_b)
        state = MarketState(bars=bars_a)

        z = strategy.get_current_z_score(state)
        if z is not None:
            self.assertIsInstance(z, float)


class TestStatArbBacktestResult(unittest.TestCase):
    def test_initialization_defaults(self):
        result = StatArbBacktestResult()
        self.assertEqual(result.total_trades, 0)
        self.assertEqual(result.winning_trades, 0)
        self.assertEqual(result.losing_trades, 0)
        self.assertEqual(result.total_pnl, 0.0)
        self.assertEqual(result.max_drawdown, 0.0)
        self.assertEqual(result.z_scores, [])
        self.assertEqual(result.signals, [])

    def test_add_signal_with_z_score(self):
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

    def test_multiple_signals(self):
        result = StatArbBacktestResult()
        result.add_signal("entry_long", 2.1)
        result.add_signal("hold_long", 1.5)
        result.add_signal("exit", 0.1)
        result.add_signal("entry_short", -2.3)
        self.assertEqual(len(result.signals), 4)
        self.assertEqual(len(result.z_scores), 4)

    def test_is_dataclass(self):
        result = StatArbBacktestResult(total_trades=5, total_pnl=100.0)
        self.assertEqual(result.total_trades, 5)
        self.assertEqual(result.total_pnl, 100.0)


class TestStatArbStrategyIntegration(unittest.TestCase):
    def test_full_evaluation_cycle_produces_signals(self):
        strategy = StatArbStrategy(
            lookback=60,
            entry_threshold=1.5,
            exit_threshold=0.0,
            stop_loss_threshold=5.0,
        )

        bars_a, bars_b = make_cointegrated_pair_bars(500, seed=42)
        strategy.set_pair_b_bars(bars_b)

        signals_found = []
        for i in range(61, len(bars_a)):
            state = MarketState(bars=bars_a[:i])
            result = strategy.evaluate(state)
            if result is not None:
                signals_found.append((i, result.direction, result.confidence))

        self.assertGreater(len(signals_found), 0, "Cointegrated pairs should produce signals")

    def test_strategy_state_tracks_position(self):
        strategy = StatArbStrategy(
            lookback=60,
            entry_threshold=1.5,
            exit_threshold=0.0,
            stop_loss_threshold=5.0,
        )

        bars_a, bars_b = make_cointegrated_pair_bars(500, seed=42)
        strategy.set_pair_b_bars(bars_b)

        entered = False
        for i in range(61, len(bars_a)):
            state = MarketState(bars=bars_a[:i])
            result = strategy.evaluate(state)
            if result is not None and not entered:
                entered = True
                self.assertTrue(strategy._position_open)
                self.assertIsNotNone(strategy._last_signal)
                break

    def test_strategy_implements_interface(self):
        from backtest.strategies import ISignalStrategy

        strategy = StatArbStrategy()
        self.assertIsInstance(strategy, ISignalStrategy)
        self.assertIsNotNone(strategy.name)
        self.assertIsInstance(strategy.name, str)


if __name__ == "__main__":
    unittest.main()
