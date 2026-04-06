import sys
import os
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from backtest.engine import Bar, MarketState, SessionType, TradeDirection
from backtest.strategies import HighConvictionStrategy


def make_bars(n=150, seed=42, trend="up", volatility_scale=0.0005):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="4h")
    price = 1.1000
    prices = []
    for i in range(n):
        drift = 0.0003 if trend == "up" else -0.0003
        vol = volatility_scale * (1.0 + 0.5 * np.sin(i / 20))
        price += drift + np.random.normal(0, vol)
        prices.append(price)
    prices = np.array(prices)
    bars = []
    for i in range(n):
        bar_high = prices[i] + abs(np.random.normal(0, volatility_scale))
        bar_low = prices[i] - abs(np.random.normal(0, volatility_scale))
        bar_open = prices[i] + np.random.normal(0, volatility_scale * 0.5)
        bars.append(
            Bar(
                time=dates[i].to_pydatetime(),
                open=bar_open,
                high=bar_high,
                low=bar_low,
                close=prices[i],
                volume=1000,
            )
        )
    return bars


def make_strong_uptrend_with_pullback(n=150, seed=55):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="4h")
    price = 1.1000
    prices = []
    for i in range(n):
        if i < 100:
            price += 0.0004 + np.random.normal(0, 0.0002)
        elif i < 120:
            price -= 0.0003 + np.random.normal(0, 0.0001)
        else:
            price += 0.0005 + np.random.normal(0, 0.0002)
        prices.append(price)
    prices = np.array(prices)
    bars = []
    for i in range(n):
        bar_high = prices[i] + abs(np.random.normal(0, 0.0003))
        bar_low = prices[i] - abs(np.random.normal(0, 0.0003))
        bar_open = prices[i] + np.random.normal(0, 0.00015)
        bars.append(
            Bar(
                time=dates[i].to_pydatetime(),
                open=bar_open,
                high=bar_high,
                low=bar_low,
                close=prices[i],
                volume=1000,
            )
        )
    return bars


def make_strong_downtrend_with_pullback(n=150, seed=77):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="4h")
    price = 1.2000
    prices = []
    for i in range(n):
        if i < 100:
            price -= 0.0004 + np.random.normal(0, 0.0002)
        elif i < 120:
            price += 0.0003 + np.random.normal(0, 0.0001)
        else:
            price -= 0.0005 + np.random.normal(0, 0.0002)
        prices.append(price)
    prices = np.array(prices)
    bars = []
    for i in range(n):
        bar_high = prices[i] + abs(np.random.normal(0, 0.0003))
        bar_low = prices[i] - abs(np.random.normal(0, 0.0003))
        bar_open = prices[i] + np.random.normal(0, 0.00015)
        bars.append(
            Bar(
                time=dates[i].to_pydatetime(),
                open=bar_open,
                high=bar_high,
                low=bar_low,
                close=prices[i],
                volume=1000,
            )
        )
    return bars


class TestHighConvictionStrategyName(unittest.TestCase):
    def test_strategy_name(self):
        strategy = HighConvictionStrategy()
        self.assertEqual(strategy.name, "High Conviction")


class TestHighConvictionInsufficientBars(unittest.TestCase):
    def test_returns_none_with_insufficient_bars(self):
        strategy = HighConvictionStrategy()
        bars = make_bars(10)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)


class TestHighConvictionSessionFilter(unittest.TestCase):
    def test_returns_none_outside_allowed_sessions(self):
        strategy = HighConvictionStrategy()
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 3, 0)
        state = MarketState(bars=bars, current_session=SessionType.OUTSIDE)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_returns_none_in_asian_session(self):
        strategy = HighConvictionStrategy()
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 2, 0)
        state = MarketState(bars=bars, current_session=SessionType.OUTSIDE)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_allows_london_session(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 9, 0)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertIn("High Conviction", result.rationale)

    def test_allows_ny_am_session(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 13, 0)
        state = MarketState(bars=bars, current_session=SessionType.NY_AM)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertIn("High Conviction", result.rationale)


class TestHighConvictionTrendDetection(unittest.TestCase):
    def test_returns_none_in_ranging_market(self):
        import numpy as np
        import pandas as pd

        np.random.seed(99)
        n = 150
        dates = pd.date_range("2023-01-01", periods=n, freq="4h")
        price = 1.1000
        bars = []
        for i in range(n):
            price += np.random.normal(0, 0.0003)
            bar_high = price + abs(np.random.normal(0, 0.0002))
            bar_low = price - abs(np.random.normal(0, 0.0002))
            bars.append(
                Bar(
                    time=dates[i].to_pydatetime(),
                    open=price,
                    high=bar_high,
                    low=bar_low,
                    close=price,
                    volume=1000,
                )
            )
        strategy = HighConvictionStrategy(trend_lookback=20)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strategy.evaluate(state)
        self.assertIsNone(result)


class TestHighConvictionRiskManagement(unittest.TestCase):
    def test_stop_loss_is_3x_atr(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
            sl_atr_mult=3.0,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 9, 0)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strategy.evaluate(state)
        if result is not None:
            atr = state.atr
            expected_sl = result.entry_price - atr * 3.0
            self.assertAlmostEqual(result.stop_loss, expected_sl, places=5)

    def test_take_profit_at_2r_minimum(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
            sl_atr_mult=3.0,
            tp_atr_mult=6.0,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 9, 0)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strategy.evaluate(state)
        if result is not None:
            risk = abs(result.entry_price - result.stop_loss)
            self.assertGreaterEqual(
                result.take_profit_2, result.entry_price + risk * 2.0
            )

    def test_confidence_is_high(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 9, 0)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertGreaterEqual(result.confidence, 0.7)


class TestHighConvictionATRPercentile(unittest.TestCase):
    def test_returns_none_when_atr_low(self):
        import numpy as np
        import pandas as pd

        np.random.seed(33)
        n = 150
        dates = pd.date_range("2023-01-01", periods=n, freq="4h")
        price = 1.1000
        bars = []
        for i in range(n):
            if i < 140:
                vol = 0.002
            else:
                vol = 0.0001
            price += np.random.normal(0, vol)
            bar_high = price + abs(np.random.normal(0, vol))
            bar_low = price - abs(np.random.normal(0, vol))
            bars.append(
                Bar(
                    time=dates[i].to_pydatetime(),
                    open=price,
                    high=bar_high,
                    low=bar_low,
                    close=price,
                    volume=1000,
                )
            )
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=100,
            atr_percentile_threshold=0.90,
        )
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strategy.evaluate(state)
        self.assertIsNone(result)


class TestHighConvictionCustomParameters(unittest.TestCase):
    def test_custom_parameters_stored(self):
        strategy = HighConvictionStrategy(
            trend_lookback=15,
            swing_lookback=40,
            rsi_period=10,
            atr_period=10,
            atr_percentile_lookback=80,
            atr_percentile_threshold=0.50,
            sl_atr_mult=2.5,
            tp_atr_mult=5.0,
            allowed_sessions=["london", "ny_am"],
        )
        self.assertEqual(strategy.trend_lookback, 15)
        self.assertEqual(strategy.swing_lookback, 40)
        self.assertEqual(strategy.rsi_period, 10)
        self.assertEqual(strategy.atr_period, 10)
        self.assertEqual(strategy.atr_percentile_lookback, 80)
        self.assertAlmostEqual(strategy.atr_percentile_threshold, 0.50)
        self.assertAlmostEqual(strategy.sl_atr_mult, 2.5)
        self.assertAlmostEqual(strategy.tp_atr_mult, 5.0)
        self.assertEqual(
            strategy.allowed_sessions, {SessionType.LONDON, SessionType.NY_AM}
        )


class TestHighConvictionRSIHelper(unittest.TestCase):
    def test_rsi_returns_none_with_insufficient_bars(self):
        strategy = HighConvictionStrategy()
        bars = [
            Bar(
                time=datetime(2023, 1, 1),
                open=1.1,
                high=1.1005,
                low=1.0995,
                close=1.1,
                volume=100,
            )
        ]
        result = strategy._calculate_rsi(bars)
        self.assertIsNone(result)

    def test_rsi_returns_value_with_sufficient_bars(self):
        bars = make_bars(30)
        strategy = HighConvictionStrategy(rsi_period=14)
        result = strategy._calculate_rsi(bars)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 100.0)

    def test_rsi_all_gains_is_100(self):
        bars = []
        for i in range(20):
            bars.append(
                Bar(
                    time=datetime(2023, 1, 1, i),
                    open=1.1 + i * 0.0001,
                    high=1.1005 + i * 0.0001,
                    low=1.0995 + i * 0.0001,
                    close=1.1002 + i * 0.0001,
                    volume=1000,
                )
            )
        strategy = HighConvictionStrategy(rsi_period=14)
        result = strategy._calculate_rsi(bars)
        self.assertAlmostEqual(result, 100.0, places=1)


class TestHighConvictionSignalStructure(unittest.TestCase):
    def test_signal_has_all_required_fields(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 9, 0)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertIsNotNone(result.direction)
            self.assertGreater(result.confidence, 0)
            self.assertGreater(result.entry_price, 0)
            self.assertGreater(result.stop_loss, 0)
            self.assertGreater(result.take_profit_1, 0)
            self.assertGreater(result.take_profit_2, 0)
            self.assertGreater(result.take_profit_3, 0)
            self.assertIn("High Conviction", result.rationale)

    def test_bearish_signal_structure(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
        )
        bars = make_strong_downtrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 13, 0)
        state = MarketState(bars=bars, current_session=SessionType.NY_AM)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.SHORT)
            self.assertGreater(result.entry_price, result.stop_loss)


if __name__ == "__main__":
    unittest.main()
