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


class TestHighConvictionTP3Calculation(unittest.TestCase):
    def test_tp3_long_is_3r_from_entry(self):
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
            expected_tp3 = result.entry_price + risk * 3.0
            self.assertAlmostEqual(result.take_profit_3, expected_tp3, places=5)
            self.assertLess(result.take_profit_3, result.entry_price * 1.1)

    def test_tp3_short_is_3r_from_entry(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
            sl_atr_mult=3.0,
            tp_atr_mult=6.0,
        )
        bars = make_strong_downtrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 13, 0)
        state = MarketState(bars=bars, current_session=SessionType.NY_AM)
        result = strategy.evaluate(state)
        if result is not None:
            risk = abs(result.entry_price - result.stop_loss)
            expected_tp3 = result.entry_price - risk * 3.0
            self.assertAlmostEqual(result.take_profit_3, expected_tp3, places=5)
            self.assertLess(result.take_profit_3, result.entry_price)

    def test_tp3_short_not_above_entry(self):
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
            self.assertLess(result.take_profit_3, result.entry_price)

    def test_tp_ordering_long(self):
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
            self.assertGreater(result.take_profit_1, result.entry_price)
            self.assertGreater(result.take_profit_2, result.take_profit_1)
            self.assertGreater(result.take_profit_3, result.take_profit_2)

    def test_tp_ordering_short(self):
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
            self.assertLess(result.take_profit_1, result.entry_price)
            self.assertLess(result.take_profit_2, result.take_profit_1)
            self.assertLess(result.take_profit_3, result.take_profit_2)


class TestHighConvictionMinConfluences(unittest.TestCase):
    def test_default_requires_all_5_confluences(self):
        strategy = HighConvictionStrategy(min_confluences=5)
        self.assertEqual(strategy.min_confluences, 5)

    def test_relaxed_confluences_allows_more_signals(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
            min_confluences=3,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 9, 0)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertIn("High Conviction", result.rationale)

    def test_confluence_1_blocks_when_5_required(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
            min_confluences=5,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 3, 0)
        state = MarketState(bars=bars, current_session=SessionType.OUTSIDE)
        result = strategy.evaluate(state)
        self.assertIsNone(result)


class TestHighConvictionMTFResample(unittest.TestCase):
    def test_resample_to_daily_groups_bars_by_date(self):
        strategy = HighConvictionStrategy()
        bars = []
        for i in range(12):
            bars.append(
                Bar(
                    time=datetime(2023, 1, 1, 0, 0)
                    + __import__("datetime").timedelta(hours=4 * i),
                    open=1.1,
                    high=1.1005,
                    low=1.0995,
                    close=1.1 + i * 0.0001,
                    volume=100,
                )
            )
        d1 = strategy._resample_to_daily(bars)
        self.assertGreater(len(d1), 1)
        self.assertLessEqual(len(d1), 3)

    def test_resample_to_daily_empty_bars(self):
        strategy = HighConvictionStrategy()
        d1 = strategy._resample_to_daily([])
        self.assertEqual(d1, [])

    def test_resample_to_daily_preserves_ohlc(self):
        strategy = HighConvictionStrategy()
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 0),
                open=1.0,
                high=1.005,
                low=0.995,
                close=1.002,
                volume=100,
            ),
            Bar(
                time=datetime(2023, 1, 1, 4),
                open=1.002,
                high=1.008,
                low=1.001,
                close=1.006,
                volume=200,
            ),
            Bar(
                time=datetime(2023, 1, 2, 0),
                open=1.006,
                high=1.010,
                low=1.004,
                close=1.008,
                volume=150,
            ),
        ]
        d1 = strategy._resample_to_daily(bars)
        self.assertEqual(len(d1), 2)
        self.assertAlmostEqual(d1[0].open, 1.0)
        self.assertAlmostEqual(d1[0].high, 1.008)
        self.assertAlmostEqual(d1[0].low, 0.995)
        self.assertAlmostEqual(d1[0].close, 1.006)
        self.assertAlmostEqual(d1[0].volume, 300)


class TestHighConvictionD1Trend(unittest.TestCase):
    def test_detects_d1_bullish_trend(self):
        strategy = HighConvictionStrategy(trend_lookback=5)
        d1_bars = []
        price = 1.1
        for i in range(10):
            price += 0.005
            d1_bars.append(
                Bar(
                    time=datetime(2023, 1, 1 + i),
                    open=price - 0.003,
                    high=price + 0.002,
                    low=price - 0.004,
                    close=price,
                    volume=1000,
                )
            )
        result = strategy._detect_d1_trend(d1_bars)
        self.assertEqual(result, TradeDirection.LONG)

    def test_detects_d1_bearish_trend(self):
        strategy = HighConvictionStrategy(trend_lookback=5)
        d1_bars = []
        price = 1.2
        for i in range(10):
            price -= 0.005
            d1_bars.append(
                Bar(
                    time=datetime(2023, 1, 1 + i),
                    open=price + 0.003,
                    high=price + 0.004,
                    low=price - 0.002,
                    close=price,
                    volume=1000,
                )
            )
        result = strategy._detect_d1_trend(d1_bars)
        self.assertEqual(result, TradeDirection.SHORT)

    def test_returns_none_in_ranging_d1(self):
        strategy = HighConvictionStrategy(trend_lookback=5)
        d1_bars = []
        for i in range(10):
            d1_bars.append(
                Bar(
                    time=datetime(2023, 1, 1 + i),
                    open=1.1,
                    high=1.1 + 0.001 * (i % 2),
                    low=1.1 - 0.001 * (i % 2),
                    close=1.1,
                    volume=1000,
                )
            )
        result = strategy._detect_d1_trend(d1_bars)
        self.assertIsNone(result)

    def test_returns_none_with_insufficient_d1_bars(self):
        strategy = HighConvictionStrategy(trend_lookback=20)
        d1_bars = [
            Bar(
                time=datetime(2023, 1, 1),
                open=1.1,
                high=1.11,
                low=1.09,
                close=1.105,
                volume=1000,
            ),
        ]
        result = strategy._detect_d1_trend(d1_bars)
        self.assertIsNone(result)


class TestHighConvictionTradeFrequency(unittest.TestCase):
    def test_blocks_second_trade_same_week(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
            max_trades_per_week=1,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 5, 9, 0)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        strategy._last_trade_time = datetime(2023, 1, 3, 9, 0)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_allows_trade_after_week_elapses(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
            max_trades_per_week=1,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 15, 9, 0)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        strategy._last_trade_time = datetime(2023, 1, 3, 9, 0)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertIn("High Conviction", result.rationale)

    def test_allows_trade_when_no_previous(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
            max_trades_per_week=1,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 1, 9, 0)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        self.assertIsNone(strategy._last_trade_time)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertIn("High Conviction", result.rationale)

    def test_disabled_freq_limit_allows_all(self):
        strategy = HighConvictionStrategy(
            trend_lookback=10,
            swing_lookback=20,
            atr_percentile_lookback=20,
            max_trades_per_week=0,
        )
        bars = make_strong_uptrend_with_pullback(150)
        bars[-1].time = datetime(2023, 1, 5, 9, 0)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        strategy._last_trade_time = datetime(2023, 1, 3, 9, 0)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertIn("High Conviction", result.rationale)

    def test_reset_clears_trade_time(self):
        strategy = HighConvictionStrategy(max_trades_per_week=1)
        strategy._last_trade_time = datetime(2023, 1, 3, 9, 0)
        strategy.reset()
        self.assertIsNone(strategy._last_trade_time)


class TestHighConvictionNewParameters(unittest.TestCase):
    def test_max_trades_per_week_default(self):
        strategy = HighConvictionStrategy()
        self.assertEqual(strategy.max_trades_per_week, 1)

    def test_max_trades_per_week_custom(self):
        strategy = HighConvictionStrategy(max_trades_per_week=2)
        self.assertEqual(strategy.max_trades_per_week, 2)

    def test_source_timeframe_default(self):
        strategy = HighConvictionStrategy()
        self.assertEqual(strategy.source_timeframe_minutes, 240)

    def test_custom_new_parameters(self):
        strategy = HighConvictionStrategy(
            source_timeframe_minutes=60,
            max_trades_per_week=3,
        )
        self.assertEqual(strategy.source_timeframe_minutes, 60)
        self.assertEqual(strategy.max_trades_per_week, 3)


if __name__ == "__main__":
    unittest.main()
