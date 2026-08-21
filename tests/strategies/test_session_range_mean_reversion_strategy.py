import unittest
from datetime import datetime

from core.types import Bar, MarketState, SessionType, TradeDirection
from strategies.session_range_mean_reversion import (
    SessionRangeMeanReversionStrategy,
    SessionRangeMRConfig,
    _calculate_atr,
    _calculate_rsi,
    _calculate_session_range,
    _get_bar_session,
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


def make_session_range_bars(seed=42):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=100, freq="1h")
    price = 1.1000
    prices = []
    for i in range(100):
        if i < 20:
            price += np.random.normal(0, 0.0001)
        else:
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
        for i in range(100)
    ]


class TestSessionRangeMeanReversionStrategy(unittest.TestCase):
    def test_strategy_name(self):
        strategy = SessionRangeMeanReversionStrategy()
        self.assertEqual(strategy.name, "Session-Range Mean Reversion")

    def test_strategy_returns_none_with_insufficient_bars(self):
        strategy = SessionRangeMeanReversionStrategy()
        bars = make_test_bars(20)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_strategy_returns_none_outside_asian_early_london(self):
        strategy = SessionRangeMeanReversionStrategy()
        bars = make_test_bars(100, seed=42)
        bars[99] = Bar(
            time=datetime(2023, 1, 1, 14, 0),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_strategy_returns_none_during_london_ny_overlap(self):
        strategy = SessionRangeMeanReversionStrategy()
        bars = make_test_bars(100, seed=42)
        bars[99] = Bar(
            time=datetime(2023, 1, 1, 13, 0),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_config_parameters(self):
        config = SessionRangeMRConfig(
            atr_period=20,
            atr_sl_multiplier=2.0,
            rsi_long_level=35.0,
            rsi_short_level=65.0,
            session_range_min_pips=15.0,
        )
        strategy = SessionRangeMeanReversionStrategy(config)
        self.assertEqual(strategy.config.atr_period, 20)
        self.assertEqual(strategy.config.atr_sl_multiplier, 2.0)
        self.assertEqual(strategy.config.rsi_long_level, 35.0)
        self.assertEqual(strategy.config.rsi_short_level, 65.0)
        self.assertEqual(strategy.config.session_range_min_pips, 15.0)

    def test_config_tp_levels(self):
        config = SessionRangeMRConfig()
        self.assertEqual(config.tp1_rr, 1.0)
        self.assertEqual(config.tp2_rr, 1.5)

    def test_config_session_range_sl(self):
        config = SessionRangeMRConfig()
        self.assertTrue(config.use_session_range_sl)
        self.assertEqual(config.session_range_sl_fraction, 0.6)
        self.assertEqual(config.session_range_min_pips, 25.0)

    def test_no_z_score_threshold_in_config(self):
        config = SessionRangeMRConfig()
        self.assertFalse(hasattr(config, "z_score_threshold"))

    def test_signal_properties_on_long_entry(self):
        config = SessionRangeMRConfig(
            atr_period=14,
            atr_sl_multiplier=1.5,
            rsi_long_level=45.0,
            session_range_min_pips=10.0,
            entry_near_extreme_pips=5.0,
        )
        strategy = SessionRangeMeanReversionStrategy(config)
        bars = make_test_bars(100, seed=42)
        bars[99] = Bar(
            time=datetime(2023, 1, 1, 5, 0),
            open=1.0995,
            high=1.1000,
            low=1.0950,
            close=1.0952,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.LONG)
            self.assertGreater(result.entry_price, 0)
            self.assertGreater(result.stop_loss, 0)
            self.assertIn("Session range MR long", result.rationale)

    def test_signal_properties_on_short_entry(self):
        config = SessionRangeMRConfig(
            atr_period=14,
            atr_sl_multiplier=1.5,
            rsi_short_level=55.0,
            session_range_min_pips=10.0,
            entry_near_extreme_pips=5.0,
        )
        strategy = SessionRangeMeanReversionStrategy(config)
        bars = make_test_bars(100, seed=42)
        bars[99] = Bar(
            time=datetime(2023, 1, 1, 5, 0),
            open=1.0995,
            high=1.1050,
            low=1.0990,
            close=1.1048,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.SHORT)
            self.assertGreater(result.entry_price, 0)
            self.assertGreater(result.stop_loss, 0)
            self.assertIn("Session range MR short", result.rationale)


class TestSessionHelpers(unittest.TestCase):
    def test_get_bar_session_asian(self):
        bar = Bar(
            time=datetime(2023, 1, 1, 2, 0),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1000,
        )
        self.assertEqual(_get_bar_session(bar.time), SessionType.ASIAN)

    def test_get_bar_session_london(self):
        bar = Bar(
            time=datetime(2023, 1, 1, 8, 0),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1000,
        )
        self.assertEqual(_get_bar_session(bar.time), SessionType.LONDON)

    def test_get_bar_session_ny_am(self):
        bar = Bar(
            time=datetime(2023, 1, 1, 13, 0),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1000,
        )
        self.assertEqual(_get_bar_session(bar.time), SessionType.NY_AM)

    def test_get_bar_session_ny_pm(self):
        bar = Bar(
            time=datetime(2023, 1, 1, 17, 0),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1000,
        )
        self.assertEqual(_get_bar_session(bar.time), SessionType.NY_PM)

    def test_get_bar_session_outside(self):
        bar = Bar(
            time=datetime(2023, 1, 1, 21, 0),
            open=1.1000,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1000,
        )
        self.assertEqual(_get_bar_session(bar.time), SessionType.OUTSIDE)

    def test_calculate_atr(self):
        bars = make_test_bars(50, seed=42)
        atr = _calculate_atr(bars, 14)
        self.assertGreater(atr, 0)

    def test_calculate_rsi(self):
        bars = make_test_bars(50, seed=42)
        rsi = _calculate_rsi(bars, 14)
        self.assertIsNotNone(rsi)
        self.assertGreaterEqual(rsi, 0)
        self.assertLessEqual(rsi, 100)

    def test_calculate_session_range_filters_by_day(self):
        bars = make_session_range_bars(seed=42)
        high, low, mean = _calculate_session_range(bars, SessionType.LONDON, reference_day=datetime(2023, 1, 2).date())
        self.assertGreater(high, 0)
        self.assertLess(low, high)
        self.assertGreater(mean, 0)

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
            all_bars, SessionType.LONDON, reference_day=datetime(2023, 1, 2).date()
        )
        high_day2, _, _ = _calculate_session_range(
            all_bars, SessionType.LONDON, reference_day=datetime(2023, 1, 3).date()
        )

        self.assertNotAlmostEqual(high_day1, high_day2)
        self.assertGreater(high_day2, high_day1)

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
        high, low, mean = _calculate_session_range(bars, SessionType.LONDON, reference_day=datetime(2023, 1, 2).date())
        self.assertEqual(high, 0.0)
        self.assertEqual(low, 0.0)
        self.assertEqual(mean, 0.0)

    def test_calculate_session_range_default_reference_day(self):
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
                time=datetime(2023, 1, 2, 9, 0),
                open=1.1005,
                high=1.1015,
                low=1.1000,
                close=1.1010,
                volume=1000,
            ),
        ]
        high, low, mean = _calculate_session_range(bars, SessionType.LONDON)
        self.assertEqual(high, 1.1015)
        self.assertEqual(low, 1.0990)

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
        result = SessionRangeMeanReversionStrategy._find_previous_trading_day(bars, datetime(2023, 1, 3).date())
        self.assertEqual(result, datetime(2023, 1, 2).date())

    def test_find_previous_trading_day_skips_weekends(self):
        bars = [
            Bar(
                time=datetime(2023, 1, 6, 8, 0),
                open=1.10,
                high=1.1010,
                low=1.0990,
                close=1.1005,
                volume=1000,
            ),
            Bar(
                time=datetime(2023, 1, 9, 8, 0),
                open=1.11,
                high=1.1110,
                low=1.1090,
                close=1.1105,
                volume=1000,
            ),
        ]
        result = SessionRangeMeanReversionStrategy._find_previous_trading_day(bars, datetime(2023, 1, 9).date())
        self.assertEqual(result, datetime(2023, 1, 6).date())


if __name__ == "__main__":
    unittest.main()
