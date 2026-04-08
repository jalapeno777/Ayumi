import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from datetime import datetime
from backtest.engine import Bar, MarketState, TradeDirection, SessionType
from strategies.killzone_momentum import (
    KillzoneMomentumStrategy,
    KillzoneMomentumConfig,
    _get_bar_session,
    _is_killzone,
    _get_killzone_name,
    _calculate_atr,
    _calculate_rsi,
    _calculate_adx,
    _calculate_session_range,
    _calculate_ema,
    _get_trend_direction,
    _find_previous_trading_day,
    _is_bullish_rejection_bar,
    _is_bearish_rejection_bar,
    _detect_prior_breakout,
)


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


def make_breakout_retest_bars(direction: str = "long", seed=42):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-02", periods=120, freq="1h")
    price = 1.1000
    prices = []
    for i in range(120):
        hour = dates[i].hour
        if hour < 7:
            price += np.random.normal(0, 0.00005)
        elif hour < 9:
            if direction == "long":
                if i == 84:
                    price += 0.0008
                elif i == 85:
                    price -= 0.0003
                else:
                    price += np.random.normal(0, 0.0001)
            else:
                if i == 84:
                    price -= 0.0008
                elif i == 85:
                    price += 0.0003
                else:
                    price += np.random.normal(0, 0.0001)
        else:
            price += np.random.normal(0, 0.0002)
        prices.append(price)
    spread = 0.0002
    bars = []
    for i in range(120):
        close = prices[i]
        op = (
            close - spread * np.random.uniform(0, 0.5)
            if direction == "long"
            else close + spread * np.random.uniform(0, 0.5)
        )
        hi = close + spread * np.random.uniform(0.5, 1.5)
        lo = close - spread * np.random.uniform(0.5, 1.5)
        bars.append(
            Bar(
                time=dates[i].to_pydatetime(),
                open=op,
                high=hi,
                low=lo,
                close=close,
                volume=1000,
            )
        )
    return bars


class TestKillzoneMomentumStrategy(unittest.TestCase):
    def test_strategy_name(self):
        strategy = KillzoneMomentumStrategy()
        self.assertEqual(strategy.name, "Killzone Momentum")

    def test_returns_none_with_insufficient_bars(self):
        strategy = KillzoneMomentumStrategy()
        bars = make_test_bars(20)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_returns_none_outside_killzone(self):
        strategy = KillzoneMomentumStrategy()
        bars = make_test_bars(100)
        bars[99] = Bar(
            time=datetime(2023, 1, 5, 20, 0),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_returns_none_during_outside_hours(self):
        strategy = KillzoneMomentumStrategy()
        bars = make_test_bars(100)
        bars[99] = Bar(
            time=datetime(2023, 1, 5, 22, 0),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_config_defaults(self):
        config = KillzoneMomentumConfig()
        self.assertEqual(config.atr_period, 14)
        self.assertEqual(config.atr_breakout_multiplier, 0.5)
        self.assertEqual(config.ema_trend_period, 50)
        self.assertEqual(config.rsi_period, 14)
        self.assertEqual(config.min_session_range_pips, 20.0)
        self.assertEqual(config.hard_cap_sl_pips, 35.0)
        self.assertEqual(config.atr_sl_multiplier, 1.5)
        self.assertEqual(config.tp1_rr, 1.0)
        self.assertEqual(config.tp2_rr, 2.0)
        self.assertEqual(config.adx_threshold, 20.0)

    def test_config_custom_values(self):
        config = KillzoneMomentumConfig(
            atr_period=20,
            hard_cap_sl_pips=50.0,
            tp1_rr=1.5,
            adx_threshold=25.0,
        )
        strategy = KillzoneMomentumStrategy(config)
        self.assertEqual(strategy.config.atr_period, 20)
        self.assertEqual(strategy.config.hard_cap_sl_pips, 50.0)
        self.assertEqual(strategy.config.tp1_rr, 1.5)
        self.assertEqual(strategy.config.adx_threshold, 25.0)

    def test_no_signal_without_prior_session_range(self):
        config = KillzoneMomentumConfig()
        strategy = KillzoneMomentumStrategy(config)
        bars = [
            Bar(
                time=datetime(2023, 1, 5, 7, 30),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
                volume=1000,
            )
            for _ in range(80)
        ]
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_no_signal_without_prior_breakout(self):
        strategy = KillzoneMomentumStrategy()
        bars = make_test_bars(100, seed=42)
        bars[99] = Bar(
            time=datetime(2023, 1, 5, 7, 30),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_signal_structure_on_retest_long(self):
        bars = make_breakout_retest_bars("long", seed=42)
        config = KillzoneMomentumConfig(
            min_session_range_pips=5.0,
            adx_threshold=10.0,
            retest_tolerance_atr=1.0,
        )
        strategy = KillzoneMomentumStrategy(config)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.LONG)
            self.assertGreater(result.entry_price, 0)
            self.assertGreater(result.stop_loss, 0)
            self.assertIn("retest long", result.rationale)

    def test_sl_below_entry_for_long(self):
        bars = make_breakout_retest_bars("long", seed=42)
        config = KillzoneMomentumConfig(
            min_session_range_pips=5.0,
            adx_threshold=10.0,
            retest_tolerance_atr=1.0,
        )
        strategy = KillzoneMomentumStrategy(config)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertGreater(result.entry_price, result.stop_loss)

    def test_tp_levels_are_correct_ratio(self):
        config = KillzoneMomentumConfig(
            min_session_range_pips=5.0,
            adx_threshold=10.0,
            retest_tolerance_atr=1.0,
        )
        strategy = KillzoneMomentumStrategy(config)
        bars = make_breakout_retest_bars("long", seed=42)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            risk = abs(result.entry_price - result.stop_loss)
            tp1_dist = abs(result.take_profit_1 - result.entry_price)
            tp2_dist = abs(result.take_profit_2 - result.entry_price)
            tp3_dist = abs(result.take_profit_3 - result.entry_price)
            self.assertAlmostEqual(tp1_dist / risk, 1.0, places=1)
            self.assertAlmostEqual(tp2_dist / risk, 2.0, places=1)
            self.assertAlmostEqual(tp3_dist / risk, 3.0, places=1)

    def test_trend_mismatch_returns_none(self):
        bars = make_breakout_retest_bars("long", seed=42)
        config = KillzoneMomentumConfig(
            min_session_range_pips=5.0,
            adx_threshold=10.0,
            retest_tolerance_atr=1.0,
            ema_trend_period=10,
        )
        strategy = KillzoneMomentumStrategy(config)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)


class TestKillzoneHelpers(unittest.TestCase):
    def test_get_bar_session_asian(self):
        self.assertEqual(
            _get_bar_session(datetime(2023, 1, 1, 2, 0)), SessionType.ASIAN
        )

    def test_get_bar_session_london(self):
        self.assertEqual(
            _get_bar_session(datetime(2023, 1, 1, 8, 0)), SessionType.LONDON
        )

    def test_get_bar_session_ny_am(self):
        self.assertEqual(
            _get_bar_session(datetime(2023, 1, 1, 13, 0)), SessionType.NY_AM
        )

    def test_get_bar_session_ny_pm(self):
        self.assertEqual(
            _get_bar_session(datetime(2023, 1, 1, 17, 0)), SessionType.NY_PM
        )

    def test_get_bar_session_outside(self):
        self.assertEqual(
            _get_bar_session(datetime(2023, 1, 1, 21, 0)), SessionType.OUTSIDE
        )

    def test_is_killzone_london_open(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 7, 30),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertTrue(_is_killzone(state))

    def test_is_killzone_ny_open(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 12, 30),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertTrue(_is_killzone(state))

    def test_is_killzone_overlap(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 14, 0),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertTrue(_is_killzone(state))

    def test_is_not_killzone_outside(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 22, 0),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertFalse(_is_killzone(state))

    def test_get_killzone_name_london_open(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 7, 30),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertEqual(_get_killzone_name(state), "london_open")

    def test_get_killzone_name_ny_open(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 12, 30),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertEqual(_get_killzone_name(state), "ny_open")

    def test_get_killzone_name_overlap(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 14, 0),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertEqual(_get_killzone_name(state), "overlap")

    def test_get_killzone_name_none_outside(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 22, 0),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertIsNone(_get_killzone_name(state))

    def test_calculate_atr_positive(self):
        bars = make_test_bars(50)
        atr = _calculate_atr(bars, 14)
        self.assertGreater(atr, 0)

    def test_calculate_atr_insufficient_bars(self):
        bars = make_test_bars(5)
        atr = _calculate_atr(bars, 14)
        self.assertEqual(atr, 0.0001)

    def test_calculate_rsi_range(self):
        bars = make_test_bars(50)
        rsi = _calculate_rsi(bars, 14)
        self.assertIsNotNone(rsi)
        self.assertGreaterEqual(rsi, 0)
        self.assertLessEqual(rsi, 100)

    def test_calculate_rsi_insufficient_bars(self):
        bars = make_test_bars(5)
        rsi = _calculate_rsi(bars, 14)
        self.assertIsNone(rsi)

    def test_calculate_adx_insufficient_bars(self):
        bars = make_test_bars(5)
        adx = _calculate_adx(bars, 14)
        self.assertIsNone(adx)

    def test_calculate_adx_returns_value(self):
        bars = make_test_bars(100)
        adx = _calculate_adx(bars, 14)
        self.assertIsNotNone(adx)
        self.assertGreaterEqual(adx, 0)

    def test_calculate_session_range_filters_by_day(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 2, 8 + i, 0),
                open=1.10 + i * 0.001,
                high=1.10 + i * 0.001 + 0.0005,
                low=1.10 + i * 0.001 - 0.0003,
                close=1.10 + i * 0.001 + 0.0002,
                volume=1000,
            )
            for i in range(4)
        ]
        high, low, mean = _calculate_session_range(
            bars, SessionType.LONDON, datetime(2023, 1, 2).date()
        )
        self.assertGreater(high, 0)
        self.assertLess(low, high)

    def test_calculate_session_range_returns_zero_for_missing_session(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 2, 2, 0),
                open=1.10,
                high=1.1005,
                low=1.0995,
                close=1.1002,
                volume=1000,
            )
        ]
        high, low, mean = _calculate_session_range(
            bars, SessionType.LONDON, datetime(2023, 1, 2).date()
        )
        self.assertEqual(high, 0.0)
        self.assertEqual(low, 0.0)
        self.assertEqual(mean, 0.0)

    def test_calculate_session_range_no_future_leak(self):
        day1_bars = [
            Bar(
                time=datetime(2023, 1, 2, 8 + i, 0),
                open=1.10 + i * 0.001,
                high=1.10 + i * 0.001 + 0.0005,
                low=1.10 + i * 0.001 - 0.0003,
                close=1.10 + i * 0.001 + 0.0002,
                volume=1000,
            )
            for i in range(4)
        ]
        day2_bars = [
            Bar(
                time=datetime(2023, 1, 3, 8 + i, 0),
                open=1.15 + i * 0.001,
                high=1.15 + i * 0.001 + 0.0005,
                low=1.15 + i * 0.001 - 0.0003,
                close=1.15 + i * 0.001 + 0.0002,
                volume=1000,
            )
            for i in range(4)
        ]
        all_bars = day1_bars + day2_bars
        high_day1, _, _ = _calculate_session_range(
            all_bars, SessionType.LONDON, datetime(2023, 1, 2).date()
        )
        high_day2, _, _ = _calculate_session_range(
            all_bars, SessionType.LONDON, datetime(2023, 1, 3).date()
        )
        self.assertNotAlmostEqual(high_day1, high_day2)
        self.assertGreater(high_day2, high_day1)

    def test_find_previous_trading_day(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 2, 8, 0),
                open=1.10,
                high=1.1010,
                low=1.0990,
                close=1.1005,
                volume=1000,
            ),
            Bar(
                time=datetime(2023, 1, 3, 8, 0),
                open=1.11,
                high=1.1110,
                low=1.1090,
                close=1.1105,
                volume=1000,
            ),
        ]
        result = _find_previous_trading_day(bars, datetime(2023, 1, 3).date())
        self.assertEqual(result, datetime(2023, 1, 2).date())

    def test_find_previous_trading_day_returns_none_when_no_prior(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 3, 8, 0),
                open=1.11,
                high=1.1110,
                low=1.1090,
                close=1.1105,
                volume=1000,
            )
        ]
        result = _find_previous_trading_day(bars, datetime(2023, 1, 3).date())
        self.assertIsNone(result)

    def test_calculate_ema(self):
        values = [1.0, 1.1, 1.2, 1.3, 1.4]
        ema = _calculate_ema(values, 3)
        self.assertIsNotNone(ema)
        self.assertGreater(ema, 1.0)

    def test_calculate_ema_insufficient_data(self):
        values = [1.0, 1.1]
        ema = _calculate_ema(values, 3)
        self.assertIsNone(ema)

    def test_get_trend_direction(self):
        bars = make_test_bars(100, seed=42)
        trend = _get_trend_direction(bars, 50)
        self.assertIsNotNone(trend)
        self.assertIn(trend, ["long", "short"])

    def test_get_trend_direction_insufficient_bars(self):
        bars = make_test_bars(20)
        trend = _get_trend_direction(bars, 50)
        self.assertIsNone(trend)

    def test_is_bullish_rejection_bar(self):
        bar = Bar(
            time=datetime(2023, 1, 1, 8, 0),
            open=1.1000,
            high=1.1005,
            low=1.0998,
            close=1.1004,
            volume=1000,
        )
        self.assertTrue(_is_bullish_rejection_bar(bar))

    def test_is_not_bullish_rejection_bearish_bar(self):
        bar = Bar(
            time=datetime(2023, 1, 1, 8, 0),
            open=1.1005,
            high=1.1006,
            low=1.0998,
            close=1.1000,
            volume=1000,
        )
        self.assertFalse(_is_bullish_rejection_bar(bar))

    def test_is_bearish_rejection_bar(self):
        bar = Bar(
            time=datetime(2023, 1, 1, 8, 0),
            open=1.1005,
            high=1.1006,
            low=1.0998,
            close=1.1000,
            volume=1000,
        )
        self.assertTrue(_is_bearish_rejection_bar(bar))

    def test_detect_prior_breakout_long(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 8 + i, 0),
                open=1.10,
                high=1.10,
                low=1.10,
                close=1.10,
                volume=100,
            )
            for i in range(4)
        ]
        bars.append(
            Bar(
                time=datetime(2023, 1, 1, 12, 0),
                open=1.10,
                high=1.105,
                low=1.10,
                close=1.104,
                volume=100,
            )
        )
        bars.append(
            Bar(
                time=datetime(2023, 1, 1, 13, 0),
                open=1.10,
                high=1.10,
                low=1.10,
                close=1.10,
                volume=100,
            )
        )
        result = _detect_prior_breakout(bars, 1.10, 1.10, 3, 0.001, 0.5)
        self.assertEqual(result, "long")

    def test_detect_prior_breakout_none(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 8 + i, 0),
                open=1.10,
                high=1.10,
                low=1.10,
                close=1.10,
                volume=100,
            )
            for i in range(4)
        ]
        result = _detect_prior_breakout(bars, 1.10, 1.10, 3, 0.001, 0.5)
        self.assertIsNone(result)


class TestKillzoneTimeWindows(unittest.TestCase):
    def test_london_open_7am_is_killzone(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 7, 0),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertTrue(_is_killzone(state))

    def test_london_open_859_is_killzone(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 8, 59),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertTrue(_is_killzone(state))

    def test_9am_is_not_london_open_killzone(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 9, 0),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertFalse(_is_killzone(state))

    def test_ny_open_12pm_is_killzone(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 12, 0),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertTrue(_is_killzone(state))

    def test_overlap_1pm_is_killzone(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 13, 0),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertTrue(_is_killzone(state))

    def test_overlap_1559_is_killzone(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 15, 59),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertTrue(_is_killzone(state))

    def test_4pm_is_not_overlap(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 16, 0),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertFalse(_is_killzone(state))

    def test_6am_is_not_killzone(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 6, 0),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertFalse(_is_killzone(state))

    def test_11am_is_not_killzone(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 11, 0),
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=100,
            )
        ]
        state = MarketState(bars=bars)
        self.assertFalse(_is_killzone(state))


if __name__ == "__main__":
    unittest.main()
