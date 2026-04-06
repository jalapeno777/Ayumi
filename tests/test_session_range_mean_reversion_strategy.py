import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from datetime import datetime
from backtest.engine import Bar, MarketState, TradeDirection, SessionType
from strategies.session_range_mean_reversion import (
    SessionRangeMeanReversionStrategy,
    SessionRangeMRConfig,
    _get_bar_session,
    _calculate_atr,
    _calculate_rsi,
    _calculate_session_range,
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
            z_score_threshold=2.0,
            rsi_long_level=35.0,
            rsi_short_level=65.0,
            session_range_min_pips=15.0,
        )
        strategy = SessionRangeMeanReversionStrategy(config)
        self.assertEqual(strategy.config.atr_period, 20)
        self.assertEqual(strategy.config.atr_sl_multiplier, 2.0)
        self.assertEqual(strategy.config.z_score_threshold, 2.0)
        self.assertEqual(strategy.config.rsi_long_level, 35.0)
        self.assertEqual(strategy.config.rsi_short_level, 65.0)
        self.assertEqual(strategy.config.session_range_min_pips, 15.0)

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
        self.assertEqual(_get_bar_session(bar.time), SessionType.LONDON)

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

    def test_calculate_session_range(self):
        bars = make_session_range_bars(seed=42)
        latest_bar_time = datetime(2023, 1, 5, 8, 0)
        high, low, mean = _calculate_session_range(bars, SessionType.LONDON, latest_bar_time)
        self.assertGreater(high, 0)
        self.assertLess(low, high)
        self.assertGreater(mean, 0)

    def test_calculate_session_range_excludes_current_session(self):
        import numpy as np
        import pandas as pd

        np.random.seed(42)
        dates = pd.date_range("2023-01-01", periods=200, freq="1h")
        price = 1.1000
        prices = []
        for i in range(200):
            if 48 <= i < 72:
                price += np.random.normal(0, 0.0001)
            else:
                price += np.random.normal(0, 0.0005)
            prices.append(price)
        prices = np.array(prices)
        bars = [
            Bar(
                time=dates[i].to_pydatetime(),
                open=prices[i] - 0.0001,
                high=prices[i] + 0.0001,
                low=prices[i] - 0.0001,
                close=prices[i],
                volume=1000,
            )
            for i in range(200)
        ]
        latest_bar_time = datetime(2023, 1, 3, 8, 0)
        high, low, mean = _calculate_session_range(bars, SessionType.LONDON, latest_bar_time)
        bar_8am_day3 = next(b for b in bars if b.time == datetime(2023, 1, 3, 8, 0))
        self.assertLess(bar_8am_day3.high, high)
        self.assertGreater(bar_8am_day3.low, low)


if __name__ == "__main__":
    unittest.main()
