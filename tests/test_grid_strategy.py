import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar, MarketState, TradeDirection
from backtest.grid_strategy import (
    GridConfig,
    GridDirection,
    GridState,
    GridStrategy,
    create_grid_strategy_from_preset,
    GRID_PRESETS,
)


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005):
    base = datetime(2024, 1, 1, 10, 0)
    return Bar(time=base + timedelta(hours=i), open=o, high=h, low=low, close=c)


def _make_bars(n=50, start_price=1.0, price_step=0.0001):
    bars = []
    for i in range(n):
        p = start_price + i * price_step
        bars.append(_bar(i, o=p, h=p + 0.0005, low=p - 0.0005, c=p + 0.0002))
    return bars


def _make_market_state(n=50, price=1.0, price_step=0.0001):
    bars = _make_bars(n, start_price=price, price_step=price_step)
    state = MarketState(bars)
    return state


class TestGridConfig(unittest.TestCase):
    def test_defaults(self):
        config = GridConfig()
        self.assertEqual(config.grid_spacing_pips, 20.0)
        self.assertEqual(config.num_levels, 10)
        self.assertEqual(config.max_concurrent_positions, 5)
        self.assertEqual(config.pair, "EURUSD")
        self.assertEqual(config.direction, GridDirection.BOTH)

    def test_preset_lookup(self):
        self.assertIn("EURUSD", GRID_PRESETS)
        self.assertIn("GBPJPY", GRID_PRESETS)
        self.assertIn("USDJPY", GRID_PRESETS)
        self.assertIn("XAUUSD", GRID_PRESETS)

    def test_to_preset(self):
        config = GridConfig(pair="EURUSD")
        eurusd_config = config.to_preset("EURUSD")
        self.assertEqual(eurusd_config.pair, "EURUSD")
        self.assertEqual(eurusd_config.grid_spacing_pips, GRID_PRESETS["EURUSD"]["grid_spacing_pips"])


class TestGridState(unittest.TestCase):
    def test_initialization(self):
        config = GridConfig(num_levels=5, pair="EURUSD")
        state = GridState(config)
        self.assertFalse(state.grid_active)
        self.assertEqual(state.filled_count, 0)

    def test_initialize_grid(self):
        config = GridConfig(num_levels=5, pair="EURUSD", grid_spacing_pips=10.0)
        state = GridState(config)
        state.initialize_grid(1.1000)

        self.assertTrue(state.grid_active)
        self.assertEqual(len(state.levels), 10)
        self.assertEqual(state.base_price, 1.1000)

        buy_levels = [lvl for lvl in state.levels if lvl.is_buy]
        sell_levels = [lvl for lvl in state.levels if not lvl.is_buy]
        self.assertEqual(len(buy_levels), 5)
        self.assertEqual(len(sell_levels), 5)

    def test_check_level_triggered_buy(self):
        config = GridConfig(num_levels=5, pair="EURUSD", grid_spacing_pips=10.0)
        state = GridState(config)
        state.initialize_grid(1.1000)
        state._get_pip_size = lambda p: 0.0001

        level = state.levels[0]
        level.price = 1.0990
        level.is_buy = True

        bar = _bar(0, o=1.0995, h=1.1000, low=1.0989, c=1.0995)
        result = state.check_level_triggered(bar)

        self.assertIsNotNone(result)
        self.assertEqual(result[0], level)
        self.assertTrue(level.order_filled)

    def test_check_level_triggered_sell(self):
        config = GridConfig(num_levels=5, pair="EURUSD", grid_spacing_pips=10.0)
        state = GridState(config)
        state.initialize_grid(1.1000)
        state._get_pip_size = lambda p: 0.0001

        sell_levels = [lvl for lvl in state.levels if not lvl.is_buy]
        level = sell_levels[0]
        level.price = 1.1010

        bar = _bar(0, o=1.1005, h=1.1012, low=1.1000, c=1.1005)
        result = state.check_level_triggered(bar)

        self.assertIsNotNone(result)
        self.assertEqual(result[0].level_index, level.level_index)
        self.assertTrue(level.order_filled)

    def test_max_positions_reached(self):
        config = GridConfig(num_levels=5, max_concurrent_positions=3)
        state = GridState(config)
        state.filled_count = 3
        self.assertTrue(state.is_max_positions_reached())

    def test_grid_expiry(self):
        config = GridConfig(grid_expiry_bars=10)
        state = GridState(config)
        state.grid_start_bar = 0
        state.bar_count = 15
        self.assertTrue(state.is_expired())

    def test_reset(self):
        config = GridConfig(num_levels=5)
        state = GridState(config)
        state.initialize_grid(1.1000)
        state.filled_count = 3
        state.reset()

        self.assertFalse(state.grid_active)
        self.assertEqual(state.filled_count, 0)
        self.assertEqual(len(state.levels), 0)


class TestGridStrategy(unittest.TestCase):
    def test_name(self):
        strategy = GridStrategy(pair="EURUSD")
        self.assertEqual(strategy.name, "Grid (EURUSD)")

    def test_initial_evaluation_returns_none(self):
        strategy = GridStrategy(num_levels=5)
        state = _make_market_state(n=20)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_grid_activates_on_second_evaluation(self):
        strategy = GridStrategy(num_levels=5, pair="EURUSD")
        state = _make_market_state(n=20)
        result = strategy.evaluate(state)

        self.assertIsNone(result)
        self.assertTrue(strategy.state.grid_active)

    def test_signal_generated_on_level_trigger(self):
        strategy = GridStrategy(num_levels=5, pair="EURUSD", grid_spacing_pips=10.0)
        state = _make_market_state(n=20)
        strategy.evaluate(state)

        level = strategy.state.levels[0]
        level.price = 1.0990
        level.is_buy = True

        bar = _bar(0, o=1.0995, h=1.1000, low=1.0989, c=1.0995)
        state.bars.append(bar)

        result = strategy.evaluate(state)

        self.assertIsNotNone(result)
        self.assertEqual(result.direction, TradeDirection.LONG)
        self.assertGreater(result.confidence, 0.0)

    def test_long_only_direction(self):
        strategy = GridStrategy(
            num_levels=5, direction=GridDirection.LONG, pair="EURUSD"
        )
        state = _make_market_state(n=20)
        strategy.evaluate(state)

        for level in strategy.state.levels:
            if not level.is_buy:
                level.price = 1.1000
            else:
                level.price = 0.9000

        bar = _bar(0, o=1.1000, h=1.1000, low=0.9000, c=1.0000)
        state.bars.append(bar)

        result = strategy.evaluate(state)
        self.assertIsNotNone(result)
        self.assertEqual(result.direction, TradeDirection.LONG)

    def test_short_only_direction(self):
        strategy = GridStrategy(
            num_levels=5, direction=GridDirection.SHORT, pair="EURUSD"
        )
        state = _make_market_state(n=20)
        strategy.evaluate(state)

        for level in strategy.state.levels:
            if level.is_buy:
                level.price = 1.2000
            else:
                level.price = 1.0000

        bar = _bar(0, o=1.1000, h=1.1000, low=0.9999, c=1.1000)
        state.bars.append(bar)

        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_reset_grid(self):
        strategy = GridStrategy(num_levels=5)
        state = _make_market_state(n=20)
        strategy.evaluate(state)
        self.assertTrue(strategy.state.grid_active)

        strategy.reset_grid()
        self.assertFalse(strategy.state.grid_active)

    def test_grid_status(self):
        strategy = GridStrategy(num_levels=5, pair="EURUSD")
        state = _make_market_state(n=20)
        strategy.evaluate(state)

        status = strategy.get_grid_status()
        self.assertTrue(status["active"])
        self.assertEqual(status["filled_count"], 0)
        self.assertEqual(len(status["levels"]), 10)

    def test_create_from_preset(self):
        strategy = create_grid_strategy_from_preset("GBPJPY")
        self.assertEqual(strategy.config.pair, "GBPJPY")
        self.assertEqual(
            strategy.config.grid_spacing_pips, GRID_PRESETS["GBPJPY"]["grid_spacing_pips"]
        )

    def test_create_from_preset_with_overrides(self):
        strategy = create_grid_strategy_from_preset(
            "EURUSD", grid_spacing_pips=50.0, num_levels=15
        )
        self.assertEqual(strategy.config.grid_spacing_pips, 50.0)
        self.assertEqual(strategy.config.num_levels, 15)


class TestGridPresets(unittest.TestCase):
    def test_eurusd_preset(self):
        preset = GRID_PRESETS["EURUSD"]
        self.assertEqual(preset["grid_spacing_pips"], 15.0)
        self.assertEqual(preset["num_levels"], 10)
        self.assertIn("atr_multiplier", preset)

    def test_gbpjpy_preset(self):
        preset = GRID_PRESETS["GBPJPY"]
        self.assertEqual(preset["grid_spacing_pips"], 25.0)
        self.assertEqual(preset["num_levels"], 8)

    def test_usdjpy_preset(self):
        preset = GRID_PRESETS["USDJPY"]
        self.assertEqual(preset["grid_spacing_pips"], 20.0)
        self.assertEqual(preset["num_levels"], 10)

    def test_xauusd_preset(self):
        preset = GRID_PRESETS["XAUUSD"]
        self.assertEqual(preset["grid_spacing_pips"], 150.0)
        self.assertEqual(preset["num_levels"], 6)
        self.assertLess(preset["max_concurrent_positions"], 5)


if __name__ == "__main__":
    unittest.main()