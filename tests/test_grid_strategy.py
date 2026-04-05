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
        self.assertEqual(
            eurusd_config.grid_spacing_pips, GRID_PRESETS["EURUSD"]["grid_spacing_pips"]
        )


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
            strategy.config.grid_spacing_pips,
            GRID_PRESETS["GBPJPY"]["grid_spacing_pips"],
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


class TestGridPositionSizing(unittest.TestCase):
    def test_equal_sizing_all_levels_same(self):
        config = GridConfig(num_levels=5, position_sizing_type="equal", base_lot_size=0.01, pair="EURUSD")
        state = GridState(config)
        state.initialize_grid(1.1000)
        for lvl in state.levels:
            self.assertEqual(lvl.size_percent, 0.01)

    def test_increasing_sizing_inner_levels_larger(self):
        config = GridConfig(num_levels=5, position_sizing_type="increasing", base_lot_size=0.01, pair="EURUSD")
        state = GridState(config)
        state.initialize_grid(1.1000)
        buy_levels = sorted([lvl for lvl in state.levels if lvl.is_buy], key=lambda x: x.level_index)
        self.assertGreater(buy_levels[1].size_percent, buy_levels[0].size_percent)
        self.assertGreater(buy_levels[2].size_percent, buy_levels[1].size_percent)
        self.assertGreater(buy_levels[3].size_percent, buy_levels[2].size_percent)
        self.assertGreater(buy_levels[4].size_percent, buy_levels[3].size_percent)

    def test_decreasing_sizing_outer_levels_larger(self):
        config = GridConfig(num_levels=5, position_sizing_type="decreasing", base_lot_size=0.01, pair="EURUSD")
        state = GridState(config)
        state.initialize_grid(1.1000)
        buy_levels = sorted([lvl for lvl in state.levels if lvl.is_buy], key=lambda x: x.level_index)
        self.assertGreater(buy_levels[0].size_percent, buy_levels[1].size_percent)
        self.assertGreater(buy_levels[1].size_percent, buy_levels[2].size_percent)


class TestGridLevelLifecycle(unittest.TestCase):
    def test_level_starts_unfilled(self):
        config = GridConfig(num_levels=5, pair="EURUSD")
        state = GridState(config)
        state.initialize_grid(1.1000)
        for lvl in state.levels:
            self.assertFalse(lvl.order_filled)
            self.assertEqual(lvl.filled_price, 0.0)
            self.assertIsNone(lvl.filled_time)

    def test_level_becomes_filled_on_trigger(self):
        config = GridConfig(num_levels=5, pair="EURUSD", grid_spacing_pips=10.0)
        state = GridState(config)
        state.initialize_grid(1.1000)
        buy_level = [lvl for lvl in state.levels if lvl.is_buy][0]
        buy_level.price = 1.0990
        bar = _bar(0, o=1.0995, h=1.1000, low=1.0989, c=1.0995)
        result = state.check_level_triggered(bar)
        self.assertIsNotNone(result)
        self.assertTrue(buy_level.order_filled)
        self.assertEqual(buy_level.filled_price, 1.0990)
        self.assertIsNotNone(buy_level.filled_time)

    def test_filled_level_not_retriggered(self):
        config = GridConfig(num_levels=5, pair="EURUSD", grid_spacing_pips=10.0)
        state = GridState(config)
        state.initialize_grid(1.1000)
        buy_level = [lvl for lvl in state.levels if lvl.is_buy][0]
        buy_level.price = 1.0990
        bar = _bar(0, o=1.0995, h=1.1000, low=1.0989, c=1.0995)
        state.check_level_triggered(bar)
        second_result = state.check_level_triggered(bar)
        self.assertIsNone(second_result)

    def test_multiple_levels_filled_sequentially(self):
        config = GridConfig(num_levels=5, pair="EURUSD", grid_spacing_pips=10.0)
        state = GridState(config)
        state.initialize_grid(1.1000)
        buy_levels = sorted([lvl for lvl in state.levels if lvl.is_buy], key=lambda x: x.level_index)
        bar1 = _bar(0, o=1.0995, h=1.1000, low=buy_levels[0].price - 0.0001, c=1.0990)
        state.check_level_triggered(bar1)
        bar2 = _bar(1, o=1.0990, h=1.1000, low=buy_levels[1].price - 0.0001, c=1.0985)
        state.check_level_triggered(bar2)
        self.assertEqual(state.filled_count, 2)
        self.assertTrue(buy_levels[0].order_filled)
        self.assertTrue(buy_levels[1].order_filled)


class TestGridTPSLXTriggers(unittest.TestCase):
    def test_tp_distance_for_buy_level(self):
        config = GridConfig(num_levels=5, pair="EURUSD")
        state = GridState(config)
        state.initialize_grid(1.1000)
        buy_level = [lvl for lvl in state.levels if lvl.is_buy][0]
        entry_price = buy_level.price
        tp = state.get_tp_for_level(buy_level, entry_price)
        self.assertGreater(tp, entry_price)

    def test_tp_distance_for_sell_level(self):
        config = GridConfig(num_levels=5, pair="EURUSD")
        state = GridState(config)
        state.initialize_grid(1.1000)
        sell_level = [lvl for lvl in state.levels if not lvl.is_buy][0]
        entry_price = sell_level.price
        tp = state.get_tp_for_level(sell_level, entry_price)
        self.assertLess(tp, entry_price)

    def test_sl_for_buy_level_below_entry(self):
        config = GridConfig(num_levels=5, pair="EURUSD")
        state = GridState(config)
        state.initialize_grid(1.1000)
        buy_level = [lvl for lvl in state.levels if lvl.is_buy][0]
        entry_price = buy_level.price
        sl = state.get_sl_for_level(buy_level, entry_price)
        self.assertLess(sl, entry_price)

    def test_sl_for_sell_level_above_entry(self):
        config = GridConfig(num_levels=5, pair="EURUSD")
        state = GridState(config)
        state.initialize_grid(1.1000)
        sell_level = [lvl for lvl in state.levels if not lvl.is_buy][0]
        entry_price = sell_level.price
        sl = state.get_sl_for_level(sell_level, entry_price)
        self.assertGreater(sl, entry_price)

    def test_signal_includes_all_take_profit_levels(self):
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
        self.assertIsNotNone(result.take_profit_1)
        self.assertIsNotNone(result.take_profit_2)
        self.assertIsNotNone(result.take_profit_3)


class TestGridRecoveryAfterAdverseMoves(unittest.TestCase):
    def test_grid_resets_after_max_positions(self):
        strategy = GridStrategy(num_levels=5, pair="EURUSD", max_concurrent_positions=2)
        state = _make_market_state(n=20)
        strategy.evaluate(state)
        strategy.state.filled_count = 2
        self.assertTrue(strategy.state.is_max_positions_reached())
        bar = _bar(0, o=1.1000, h=1.1005, low=1.0995, c=1.1000)
        state.bars.append(bar)
        strategy.evaluate(state)
        self.assertFalse(strategy.state.grid_active)

    def test_grid_resets_after_expiry(self):
        strategy = GridStrategy(num_levels=5, pair="EURUSD", grid_expiry_bars=5)
        state = _make_market_state(n=20)
        strategy.evaluate(state)
        strategy.state.grid_start_bar = 0
        strategy.state.bar_count = 10
        self.assertTrue(strategy.state.is_expired())
        bar = _bar(0, o=1.1000, h=1.1005, low=1.0995, c=1.1000)
        state.bars.append(bar)
        strategy.evaluate(state)
        self.assertFalse(strategy.state.grid_active)

    def test_reset_allows_new_grid_initialization(self):
        strategy = GridStrategy(num_levels=5, pair="EURUSD")
        state = _make_market_state(n=20)
        strategy.evaluate(state)
        self.assertTrue(strategy.state.grid_active)
        strategy.reset_grid()
        self.assertFalse(strategy.state.grid_active)
        state = _make_market_state(n=20)
        strategy.evaluate(state)
        self.assertTrue(strategy.state.grid_active)


class TestGridMultiPairSupport(unittest.TestCase):
    def test_eurusd_standard_pip_size(self):
        strategy = GridStrategy(pair="EURUSD")
        self.assertEqual(strategy._get_pip_size("EURUSD"), 0.0001)
        self.assertEqual(strategy._get_pip_size("GBPUSD"), 0.0001)

    def test_jpy_pair_pip_size(self):
        strategy = GridStrategy(pair="USDJPY")
        self.assertEqual(strategy._get_pip_size("USDJPY"), 0.01)
        self.assertEqual(strategy._get_pip_size("GBPJPY"), 0.01)

    def test_xauusd_pip_size(self):
        strategy = GridStrategy(pair="XAUUSD")
        self.assertEqual(strategy._get_pip_size("XAUUSD"), 0.0001)

    def test_xauusd_preset_applied(self):
        strategy = create_grid_strategy_from_preset("XAUUSD")
        self.assertEqual(strategy.config.pair, "XAUUSD")
        self.assertEqual(strategy.config.grid_spacing_pips, 150.0)
        self.assertEqual(strategy.config.num_levels, 6)
        self.assertEqual(strategy.config.max_concurrent_positions, 3)

    def test_xauusd_grid_with_different_spacing(self):
        strategy = GridStrategy(pair="XAUUSD", grid_spacing_pips=200.0, num_levels=8)
        state = _make_market_state(n=20)
        state.bars = [
            Bar(time=datetime(2025, 1, 1, 10, 0) + timedelta(hours=i), open=2000 + i, high=2005 + i, low=1995 + i, close=2000 + i, volume=1000)
            for i in range(20)
        ]
        strategy.evaluate(state)
        self.assertTrue(strategy.state.grid_active)

    def test_eurusd_preset_in_grid_config(self):
        config = GridConfig().to_preset("EURUSD")
        self.assertEqual(config.grid_spacing_pips, 15.0)
        self.assertEqual(config.num_levels, 10)
        self.assertEqual(config.pair, "EURUSD")

    def test_gbpjpy_preset_in_grid_config(self):
        config = GridConfig().to_preset("GBPJPY")
        self.assertEqual(config.grid_spacing_pips, 25.0)
        self.assertEqual(config.num_levels, 8)
        self.assertEqual(config.pair, "GBPJPY")

    def test_usdjpy_preset_in_grid_config(self):
        config = GridConfig().to_preset("USDJPY")
        self.assertEqual(config.grid_spacing_pips, 20.0)
        self.assertEqual(config.num_levels, 10)
        self.assertEqual(config.pair, "USDJPY")


if __name__ == "__main__":
    unittest.main()
