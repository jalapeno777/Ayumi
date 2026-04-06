import unittest
from datetime import datetime

from backtest.engine import Bar, ExitReason, StrategySignal, TradeDirection
from backtest.trade_management.config import (
    TradeManagementConfig,
    TrailingStopConfig,
    TrailingStopMethod,
)
from backtest.trade_management.exit_refinement import ExitRefiner
from backtest.trade_management.partial_exit import (
    PartialExitAction,
    PartialExitManager,
)
from backtest.trade_management.session_filter import (
    NewsEvent,
    NewsEventSimulator,
    SessionFilter,
)
from backtest.trade_management.trailing_stop import (
    TrailingStopManager,
)
from backtest.trade_management.trade_manager import (
    TradeAction,
    TradeManager,
)


def _bar(time=None, o=1.0, h=1.01, low=0.99, c=1.005, v=1000):
    if time is None:
        time = datetime(2024, 1, 1, 10, 0)
    return Bar(time=time, open=o, high=h, low=low, close=c, volume=v)


def _signal(
    direction=TradeDirection.LONG, entry=1.0, sl=0.99, tp1=1.01, tp2=1.02, tp3=1.03
):
    return StrategySignal(
        direction=direction,
        confidence=0.8,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
        rationale="test",
    )


class TestPartialExitManager(unittest.TestCase):
    def setUp(self):
        self.mgr = PartialExitManager(
            enabled=True,
            tiers=[(0.5, 1.0, True), (0.75, 2.0, False)],
            final_trail=True,
        )
        self.state = self.mgr.create_state()
        self.entry = 1.0000
        self.sl = 0.9900

    def test_no_action_when_price_below_tp1(self):
        bar = _bar(o=1.0, h=1.005, low=0.995, c=1.002)
        result = self.mgr.evaluate(
            bar,
            self.state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.sl,
        )
        self.assertEqual(result.action, PartialExitAction.NO_ACTION)

    def test_partial_close_at_tp1(self):
        bar = _bar(o=1.0, h=1.015, low=0.995, c=1.01)
        result = self.mgr.evaluate(
            bar,
            self.state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.sl,
        )
        self.assertEqual(result.action, PartialExitAction.PARTIAL_CLOSE)
        self.assertAlmostEqual(result.close_pct, 0.5)
        self.assertEqual(result.reason, ExitReason.TAKE_PROFIT_1)
        self.assertIsNotNone(result.new_sl)
        self.assertAlmostEqual(result.new_sl, self.entry)

    def test_sl_moved_to_breakeven_only_once(self):
        bar1 = _bar(o=1.0, h=1.015, low=0.995, c=1.01)
        r1 = self.mgr.evaluate(
            bar1,
            self.state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.sl,
        )
        self.assertIsNotNone(r1.new_sl)

        bar2 = _bar(o=1.01, h=1.025, low=1.005, c=1.02)
        r2 = self.mgr.evaluate(
            bar2,
            self.state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.entry,
        )
        self.assertEqual(r2.action, PartialExitAction.PARTIAL_CLOSE)
        self.assertIsNone(r2.new_sl)

    def test_second_tier_partial_close(self):
        bar1 = _bar(o=1.0, h=1.015, low=0.995, c=1.01)
        self.mgr.evaluate(
            bar1,
            self.state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.sl,
        )

        bar2 = _bar(o=1.01, h=1.025, low=1.005, c=1.02)
        result = self.mgr.evaluate(
            bar2,
            self.state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.entry,
        )
        self.assertEqual(result.action, PartialExitAction.PARTIAL_CLOSE)
        self.assertAlmostEqual(result.close_pct, 0.25)
        self.assertEqual(result.reason, ExitReason.TAKE_PROFIT_2)

    def test_trail_enabled_after_last_tier(self):
        bar1 = _bar(o=1.0, h=1.015, low=0.995, c=1.01)
        self.mgr.evaluate(
            bar1,
            self.state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.sl,
        )
        bar2 = _bar(o=1.01, h=1.025, low=1.005, c=1.02)
        self.mgr.evaluate(
            bar2,
            self.state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.entry,
        )

        bar3 = _bar(o=1.02, h=1.03, low=1.015, c=1.025)
        result = self.mgr.evaluate(
            bar3,
            self.state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.entry,
        )
        self.assertEqual(result.action, PartialExitAction.ENABLE_TRAIL)

    def test_disabled_returns_no_action(self):
        mgr = PartialExitManager(enabled=False)
        state = mgr.create_state()
        bar = _bar(o=1.0, h=1.015, low=0.995, c=1.01)
        result = mgr.evaluate(
            bar,
            state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.sl,
        )
        self.assertEqual(result.action, PartialExitAction.NO_ACTION)

    def test_short_tp1_hit(self):
        bar = _bar(o=1.0, h=0.995, low=0.985, c=0.99)
        result = self.mgr.evaluate(
            bar,
            self.state,
            TradeDirection.SHORT,
            self.entry,
            1.01,
            0.99,
            0.98,
            0.97,
            1.01,
        )
        self.assertEqual(result.action, PartialExitAction.PARTIAL_CLOSE)
        self.assertEqual(result.reason, ExitReason.TAKE_PROFIT_1)

    def test_full_close_when_no_trail(self):
        mgr = PartialExitManager(
            enabled=True,
            tiers=[(0.5, 1.0, True), (0.75, 2.0, False)],
            final_trail=False,
        )
        state = mgr.create_state()
        bar1 = _bar(o=1.0, h=1.015, low=0.995, c=1.01)
        mgr.evaluate(
            bar1,
            state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.sl,
        )
        bar2 = _bar(o=1.01, h=1.025, low=1.005, c=1.02)
        result = mgr.evaluate(
            bar2,
            state,
            TradeDirection.LONG,
            self.entry,
            self.sl,
            1.01,
            1.02,
            1.03,
            self.entry,
        )
        self.assertEqual(result.action, PartialExitAction.FULL_CLOSE)
        self.assertAlmostEqual(result.close_pct, 1.0)


class TestTrailingStopManager(unittest.TestCase):
    def setUp(self):
        self.config = TrailingStopConfig(
            enabled=True,
            method=TrailingStopMethod.ATR,
            atr_multiplier=1.5,
        )
        self.mgr = TrailingStopManager(self.config)
        self.entry = 1.0000
        self.sl = 0.9900
        self.atr = 0.0050

    def test_create_state(self):
        state = self.mgr.create_state(TradeDirection.LONG, self.entry, self.sl)
        self.assertEqual(state.current_sl, self.sl)
        self.assertFalse(state.is_active)

    def test_inactive_returns_no_trigger(self):
        state = self.mgr.create_state(TradeDirection.LONG, self.entry, self.sl)
        bar = _bar(h=1.02, low=0.98)
        result = self.mgr.evaluate(
            bar, state, TradeDirection.LONG, self.atr, self.entry
        )
        self.assertFalse(result.triggered)

    def test_atr_trail_updates_sl(self):
        state = self.mgr.create_state(TradeDirection.LONG, self.entry, self.sl)
        state.is_active = True
        bar = _bar(h=1.02, low=1.0, c=1.015)
        result = self.mgr.evaluate(
            bar, state, TradeDirection.LONG, self.atr, self.entry
        )
        expected_sl = 1.02 - (self.atr * 1.5)
        self.assertTrue(result.sl_updated)
        self.assertAlmostEqual(result.new_sl, expected_sl, places=4)

    def test_atr_trail_triggers_stop(self):
        state = self.mgr.create_state(TradeDirection.LONG, self.entry, self.sl)
        state.is_active = True
        state.current_sl = 1.005
        bar = _bar(h=1.01, low=1.004, c=1.005)
        result = self.mgr.evaluate(
            bar, state, TradeDirection.LONG, self.atr, self.entry
        )
        self.assertTrue(result.triggered)
        self.assertAlmostEqual(result.exit_price, 1.005, places=4)

    def test_atr_trail_short(self):
        state = self.mgr.create_state(TradeDirection.SHORT, self.entry, 1.01)
        state.is_active = True
        bar = _bar(h=1.0, low=0.98, c=0.985)
        result = self.mgr.evaluate(
            bar, state, TradeDirection.SHORT, self.atr, self.entry
        )
        expected_sl = 0.98 + (self.atr * 1.5)
        self.assertTrue(result.sl_updated)
        self.assertAlmostEqual(result.new_sl, expected_sl, places=4)

    def test_step_trail(self):
        config = TrailingStopConfig(
            enabled=True,
            method=TrailingStopMethod.STEP,
            step_pips=10.0,
        )
        mgr = TrailingStopManager(config)
        state = mgr.create_state(TradeDirection.LONG, self.entry, self.sl)
        state.is_active = True
        bar = _bar(h=1.020, low=1.0, c=1.015)
        result = mgr.evaluate(bar, state, TradeDirection.LONG, self.atr, self.entry)
        self.assertTrue(result.sl_updated)
        expected_sl = 1.020 - (10.0 * 0.0001)
        self.assertAlmostEqual(result.new_sl, expected_sl, places=4)

    def test_time_trail_tightens_after_threshold(self):
        config = TrailingStopConfig(
            enabled=True,
            method=TrailingStopMethod.TIME,
            atr_multiplier=1.5,
            time_tighten_bars=3,
            time_tighten_pct=0.5,
        )
        mgr = TrailingStopManager(config)
        state = mgr.create_state(TradeDirection.LONG, self.entry, self.sl)
        state.is_active = True

        for i in range(3):
            bar = _bar(h=1.01 + i * 0.002, low=1.0, c=1.01)
            mgr.evaluate(bar, state, TradeDirection.LONG, self.atr, self.entry)

        bar = _bar(h=1.02, low=1.0, c=1.015)
        result = mgr.evaluate(bar, state, TradeDirection.LONG, self.atr, self.entry)
        self.assertTrue(result.sl_updated or state.bars_since_entry >= 4)

    def test_sl_only_moves_in_favorable_direction_long(self):
        state = self.mgr.create_state(TradeDirection.LONG, self.entry, self.sl)
        state.is_active = True

        bar_down = _bar(h=1.001, low=0.99, c=0.995)
        result = self.mgr.evaluate(
            bar_down, state, TradeDirection.LONG, self.atr, self.entry
        )
        self.assertFalse(result.sl_updated)
        self.assertEqual(state.current_sl, self.sl)


class TestSessionFilter(unittest.TestCase):
    def setUp(self):
        self.filter = SessionFilter(
            enabled=True,
            allow_entry_sessions=["london", "ny_am", "ny_pm"],
            weekend_close_hour_utc=21,
            weekend_close_minute_utc=55,
        )

    def test_allow_entry_in_london(self):
        bar = _bar(time=datetime(2024, 1, 1, 9, 0))
        result = self.filter.check_entry(bar)
        self.assertTrue(result.allow_entry)

    def test_allow_entry_in_ny_am(self):
        bar = _bar(time=datetime(2024, 1, 1, 15, 0))
        result = self.filter.check_entry(bar)
        self.assertTrue(result.allow_entry)

    def test_deny_entry_outside_hours(self):
        bar = _bar(time=datetime(2024, 1, 1, 5, 0))
        result = self.filter.check_entry(bar)
        self.assertFalse(result.allow_entry)
        self.assertIn("not in allowed", result.reason)

    def test_deny_entry_weekend_close(self):
        bar = _bar(time=datetime(2024, 1, 5, 22, 0))
        result = self.filter.check_entry(bar)
        self.assertFalse(result.allow_entry)
        self.assertIn("Weekend", result.reason)

    def test_deny_entry_saturday(self):
        bar = _bar(time=datetime(2024, 1, 6, 10, 0))
        result = self.filter.check_entry(bar)
        self.assertFalse(result.allow_entry)

    def test_force_close_weekend(self):
        bar = _bar(time=datetime(2024, 1, 5, 22, 0))
        entry_time = datetime(2024, 1, 5, 9, 0)
        result = self.filter.check_hold(bar, entry_time, TradeDirection.LONG)
        self.assertTrue(result.force_close)

    def test_no_force_close_during_week(self):
        bar = _bar(time=datetime(2024, 1, 3, 15, 0))
        entry_time = datetime(2024, 1, 3, 9, 0)
        result = self.filter.check_hold(bar, entry_time, TradeDirection.LONG)
        self.assertFalse(result.force_close)

    def test_kill_zone_london_open(self):
        self.assertTrue(self.filter.is_kill_zone(datetime(2024, 1, 1, 7, 30)))
        self.assertTrue(self.filter.is_kill_zone(datetime(2024, 1, 1, 8, 30)))

    def test_not_kill_zone_during_regular_session(self):
        self.assertFalse(self.filter.is_kill_zone(datetime(2024, 1, 1, 10, 0)))

    def test_disabled_allows_all(self):
        f = SessionFilter(enabled=False)
        bar = _bar(time=datetime(2024, 1, 1, 3, 0))
        self.assertTrue(f.check_entry(bar).allow_entry)

    def test_news_filter_blocks_entry(self):
        news_sim = NewsEventSimulator(
            [
                NewsEvent(
                    time=datetime(2024, 1, 1, 13, 30),
                    currency="USD",
                    impact="high",
                    description="NFP",
                ),
            ]
        )
        f = SessionFilter(
            enabled=True, news_buffer_on_entry=True, news_simulator=news_sim
        )
        bar = _bar(time=datetime(2024, 1, 1, 13, 15))
        result = f.check_entry(bar)
        self.assertFalse(result.allow_entry)
        self.assertIn("news", result.reason.lower())

    def test_news_filter_allows_far_from_event(self):
        news_sim = NewsEventSimulator(
            [
                NewsEvent(
                    time=datetime(2024, 1, 1, 13, 30),
                    currency="USD",
                    impact="high",
                    description="NFP",
                ),
            ]
        )
        f = SessionFilter(
            enabled=True, news_buffer_on_entry=True, news_simulator=news_sim
        )
        bar = _bar(time=datetime(2024, 1, 1, 10, 0))
        result = f.check_entry(bar)
        self.assertTrue(result.allow_entry)


class TestExitRefiner(unittest.TestCase):
    def setUp(self):
        self.refiner = ExitRefiner(
            enabled=True,
            max_bars_to_tp1=5,
            momentum_exit_enabled=True,
            momentum_lookback=3,
            momentum_reversal_threshold=0.5,
        )
        self.state = self.refiner.create_state()

    def test_time_stop_triggers(self):
        for i in range(6):
            bar = _bar(h=1.005, low=0.995, c=1.0)
            result = self.refiner.on_bar(bar, self.state, TradeDirection.LONG, 0.005)
        self.assertTrue(result.should_exit)
        self.assertEqual(result.reason, ExitReason.STOP_LOSS)
        self.assertIn("Time stop", result.message)

    def test_no_exit_within_time_limit(self):
        for i in range(4):
            bar = _bar(h=1.005, low=0.995, c=1.0)
            result = self.refiner.on_bar(bar, self.state, TradeDirection.LONG, 0.005)
        self.assertFalse(result.should_exit)

    def test_momentum_reversal_long(self):
        refiner = ExitRefiner(
            enabled=True,
            momentum_exit_enabled=True,
            momentum_lookback=3,
            momentum_reversal_threshold=0.002,
        )
        state = refiner.create_state()
        state.bars_since_entry = 3
        state.momentum_history = [-0.006, -0.008, -0.01]
        bar = _bar(c=0.99, o=1.0)
        result = refiner.on_bar(bar, state, TradeDirection.LONG, 0.005)
        self.assertTrue(result.should_exit)
        self.assertEqual(result.reason, ExitReason.SIGNAL_FLIP)

    def test_momentum_reversal_short(self):
        refiner = ExitRefiner(
            enabled=True,
            momentum_exit_enabled=True,
            momentum_lookback=3,
            momentum_reversal_threshold=0.002,
        )
        state = refiner.create_state()
        state.bars_since_entry = 3
        state.momentum_history = [0.006, 0.008, 0.01]
        bar = _bar(c=1.01, o=1.0)
        result = refiner.on_bar(bar, state, TradeDirection.SHORT, 0.005)
        self.assertTrue(result.should_exit)

    def test_spread_filter_allows_normal(self):
        self.assertTrue(self.refiner.check_entry_spread(_bar(), 0.005, 0.5))

    def test_spread_filter_blocks_wide(self):
        refiner = ExitRefiner(enabled=True, max_spread_atr_pct=0.1)
        bar = _bar(c=1.0)
        result = refiner.check_entry_spread(bar, 0.005, 20.0)
        self.assertFalse(result)

    def test_disabled_returns_no_action(self):
        refiner = ExitRefiner(enabled=False)
        state = refiner.create_state()
        for i in range(100):
            bar = _bar()
            result = refiner.on_bar(bar, state, TradeDirection.LONG, 0.005)
        self.assertFalse(result.should_exit)

    def test_tp1_hit_disables_time_stop(self):
        self.state.tp1_hit = True
        for i in range(100):
            bar = _bar(h=1.005, low=0.995, c=1.0)
            result = self.refiner.on_bar(bar, self.state, TradeDirection.LONG, 0.005)
        self.assertFalse(result.should_exit)


class TestTradeManager(unittest.TestCase):
    def setUp(self):
        self.config = TradeManagementConfig()
        self.tm = TradeManager(self.config)

    def test_check_entry_allowed(self):
        bar = _bar(time=datetime(2024, 1, 1, 10, 0))
        signal = _signal()
        result = self.tm.check_entry_allowed(bar, signal, 0.005, 0.5)
        self.assertTrue(result.allow_entry)

    def test_check_entry_blocked_outside_session(self):
        bar = _bar(time=datetime(2024, 1, 1, 6, 30))
        signal = _signal()
        result = self.tm.check_entry_allowed(bar, signal, 0.005, 0.5)
        self.assertFalse(result.allow_entry)

    def test_open_trade(self):
        bar = _bar()
        signal = _signal()
        trade = self.tm.open_trade(10, bar, signal, 0.1)
        self.assertEqual(trade.entry_price, 1.0)
        self.assertEqual(trade.direction, TradeDirection.LONG)
        self.assertEqual(trade.remaining_pct, 1.0)
        self.assertFalse(trade.is_closed)
        self.assertIsNotNone(trade.tier_state)
        self.assertIsNotNone(trade.trailing_state)

    def test_on_bar_stop_loss(self):
        bar = _bar()
        signal = _signal(entry=1.0, sl=0.99)
        trade = self.tm.open_trade(10, bar, signal, 0.1)
        sl_bar = _bar(h=1.0, low=0.989, c=0.992)
        result = self.tm.on_bar(trade, sl_bar, 11, 0.005)
        self.assertEqual(result.action, TradeAction.CLOSE_FULL)
        self.assertEqual(result.reason, ExitReason.STOP_LOSS)
        self.assertTrue(trade.is_closed)

    def test_on_bar_partial_tp1(self):
        bar = _bar()
        signal = _signal(entry=1.0, sl=0.99, tp1=1.01)
        trade = self.tm.open_trade(10, bar, signal, 0.1)
        tp_bar = _bar(h=1.015, low=0.995, c=1.01)
        result = self.tm.on_bar(trade, tp_bar, 11, 0.005)
        self.assertEqual(result.action, TradeAction.CLOSE_PARTIAL)
        self.assertAlmostEqual(result.close_pct, 0.5)
        self.assertAlmostEqual(trade.current_sl, 1.0)

    def test_on_bar_no_action(self):
        bar = _bar()
        signal = _signal()
        trade = self.tm.open_trade(10, bar, signal, 0.1)
        next_bar = _bar(h=1.005, low=0.995, c=1.002)
        result = self.tm.on_bar(trade, next_bar, 11, 0.005)
        self.assertEqual(result.action, TradeAction.NO_ACTION)

    def test_on_bar_force_close_weekend(self):
        bar = _bar(time=datetime(2024, 1, 3, 10, 0))
        signal = _signal()
        trade = self.tm.open_trade(10, bar, signal, 0.1)
        weekend_bar = _bar(time=datetime(2024, 1, 5, 22, 0), h=1.01, low=0.99, c=1.005)
        result = self.tm.on_bar(trade, weekend_bar, 11, 0.005)
        self.assertEqual(result.action, TradeAction.CLOSE_FULL)

    def test_closed_trade_returns_no_action(self):
        bar = _bar()
        signal = _signal()
        trade = self.tm.open_trade(10, bar, signal, 0.1)
        trade.is_closed = True
        result = self.tm.on_bar(trade, _bar(), 11, 0.005)
        self.assertEqual(result.action, TradeAction.NO_ACTION)


class TestTradeManagementConfig(unittest.TestCase):
    def test_default_config(self):
        config = TradeManagementConfig()
        self.assertTrue(config.partial_exit.enabled)
        self.assertTrue(config.trailing_stop.enabled)
        self.assertTrue(config.session_filter.enabled)
        self.assertTrue(config.exit_refinement.enabled)

    def test_conservative_preset(self):
        config = TradeManagementConfig.conservative()
        self.assertEqual(config.trailing_stop.atr_multiplier, 2.0)
        self.assertEqual(config.exit_refinement.max_spread_atr_pct, 0.1)
        self.assertEqual(config.session_filter.news_buffer_bars, 6)

    def test_aggressive_preset(self):
        config = TradeManagementConfig.aggressive()
        self.assertEqual(config.trailing_stop.atr_multiplier, 1.0)
        self.assertEqual(config.trailing_stop.step_pips, 5.0)
        self.assertEqual(config.exit_refinement.max_bars_to_tp1, 24)

    def test_ftmo_preset(self):
        config = TradeManagementConfig.ftmo()
        self.assertEqual(config.trailing_stop.only_after_tier, 1)
        self.assertTrue(config.session_filter.news_buffer_on_entry)
        self.assertEqual(config.partial_exit.tiers[0][1], 1.0)


class TestNewsEventSimulator(unittest.TestCase):
    def test_has_high_impact_near(self):
        sim = NewsEventSimulator(
            [
                NewsEvent(
                    time=datetime(2024, 1, 1, 13, 30), currency="USD", impact="high"
                ),
            ]
        )
        self.assertTrue(sim.has_high_impact_near(datetime(2024, 1, 1, 13, 0)))
        self.assertFalse(sim.has_high_impact_near(datetime(2024, 1, 1, 10, 0)))

    def test_low_impact_ignored(self):
        sim = NewsEventSimulator(
            [
                NewsEvent(
                    time=datetime(2024, 1, 1, 13, 30), currency="USD", impact="low"
                ),
            ]
        )
        self.assertFalse(sim.has_high_impact_near(datetime(2024, 1, 1, 13, 0)))

    def test_empty_simulator(self):
        sim = NewsEventSimulator()
        self.assertFalse(sim.has_high_impact_near(datetime(2024, 1, 1, 13, 0)))


if __name__ == "__main__":
    unittest.main()
