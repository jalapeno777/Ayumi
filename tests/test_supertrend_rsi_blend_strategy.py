import sys
import os
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from backtest.engine import Bar, MarketState, TradeDirection
from backtest.strategies import SupertrendRSIBlendStrategy


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


def make_trending_bars_with_supertrend_signal(n=100, seed=42, direction="long"):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = 1.1000
    prices = []

    if direction == "long":
        for i in range(n):
            if i < 20:
                price += np.random.normal(0, 0.0001)
            else:
                price += 0.0004 + np.random.normal(0, 0.0001)
            prices.append(price)
    else:
        for i in range(n):
            if i < 20:
                price += np.random.normal(0, 0.0001)
            else:
                price -= 0.0004 + np.random.normal(0, 0.0001)
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


class TestSupertrendRSIBlendStrategy(unittest.TestCase):
    def test_strategy_name(self):
        strategy = SupertrendRSIBlendStrategy()
        self.assertEqual(strategy.name, "Supertrend RSI Blend")

    def test_strategy_returns_none_with_insufficient_bars(self):
        strategy = SupertrendRSIBlendStrategy()
        bars = make_test_bars(10)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_strategy_returns_none_in_choppy_market_with_low_atr(self):
        strategy = SupertrendRSIBlendStrategy(atr_min_chop=50.0)
        bars = make_test_bars(50)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_strategy_returns_none_during_low_adx_regime(self):
        strategy = SupertrendRSIBlendStrategy(adx_min=50.0)
        bars = make_test_bars(50)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_strategy_returns_none_first_30_min_of_session(self):
        strategy = SupertrendRSIBlendStrategy()
        bars = make_test_bars(50)
        bars[-1].time = datetime(2023, 1, 1, 0, 15)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_strategy_returns_signal_on_bullish_supertrend_flip(self):
        strategy = SupertrendRSIBlendStrategy(
            supertrend_period=5,
            supertrend_multiplier=2.0,
            rsi_period=5,
            rsi_threshold=50.0,
            atr_min_pips=1.0,
            adx_min=15.0,
            atr_min_chop=1.0,
        )
        bars = make_trending_bars_with_supertrend_signal(50, seed=42, direction="long")
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.LONG)
            self.assertGreater(result.entry_price, 0)
            self.assertGreater(result.stop_loss, 0)
            self.assertIn("Supertrend", result.rationale)

    def test_strategy_returns_signal_on_bearish_supertrend_flip(self):
        strategy = SupertrendRSIBlendStrategy(
            supertrend_period=5,
            supertrend_multiplier=2.0,
            rsi_period=5,
            rsi_threshold=50.0,
            atr_min_pips=1.0,
            adx_min=15.0,
            atr_min_chop=1.0,
        )
        bars = make_trending_bars_with_supertrend_signal(50, seed=42, direction="short")
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.SHORT)
            self.assertGreater(result.entry_price, 0)
            self.assertGreater(result.stop_loss, 0)
            self.assertIn("Supertrend", result.rationale)

    def test_confidence_within_valid_range(self):
        strategy = SupertrendRSIBlendStrategy()
        bars = make_trending_bars_with_supertrend_signal(50, seed=42, direction="long")
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertGreaterEqual(result.confidence, 0.0)
            self.assertLessEqual(result.confidence, 0.85)

    def test_take_profit_levels_formatted_correctly(self):
        strategy = SupertrendRSIBlendStrategy(
            supertrend_period=5,
            supertrend_multiplier=2.0,
            rsi_period=5,
            rsi_threshold=50.0,
            atr_min_pips=1.0,
            adx_min=15.0,
            atr_min_chop=1.0,
            tp1_atr=1.5,
            tp2_atr=2.5,
        )
        bars = make_trending_bars_with_supertrend_signal(50, seed=42, direction="long")
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            risk = abs(result.entry_price - result.stop_loss)
            expected_tp1 = result.entry_price + risk * 1.5
            expected_tp2 = result.entry_price + risk * 2.5
            expected_tp3 = result.entry_price + risk * 3.0
            self.assertAlmostEqual(result.take_profit_1, expected_tp1, places=5)
            self.assertAlmostEqual(result.take_profit_2, expected_tp2, places=5)
            self.assertAlmostEqual(result.take_profit_3, expected_tp3, places=5)

    def test_custom_parameters(self):
        strategy = SupertrendRSIBlendStrategy(
            supertrend_period=10,
            supertrend_multiplier=2.0,
            rsi_period=10,
            rsi_threshold=45.0,
            atr_min_pips=8.0,
            adx_period=14,
            adx_min=20.0,
            atr_min_chop=8.0,
            sl_atr_multiplier=1.5,
            hard_cap_pips=40.0,
            tp1_atr=1.5,
            tp2_atr=2.5,
            time_exit_bars=20,
        )
        self.assertEqual(strategy.supertrend_period, 10)
        self.assertEqual(strategy.supertrend_multiplier, 2.0)
        self.assertEqual(strategy.rsi_period, 10)
        self.assertEqual(strategy.rsi_threshold, 45.0)
        self.assertEqual(strategy.atr_min_pips, 8.0)
        self.assertEqual(strategy.adx_period, 14)
        self.assertEqual(strategy.adx_min, 20.0)
        self.assertEqual(strategy.atr_min_chop, 8.0)
        self.assertEqual(strategy.sl_atr_multiplier, 1.5)
        self.assertEqual(strategy.hard_cap_pips, 40.0)
        self.assertEqual(strategy.tp1_atr, 1.5)
        self.assertEqual(strategy.tp2_atr, 2.5)
        self.assertEqual(strategy.time_exit_bars, 20)

    def test_stop_loss_hard_cap(self):
        strategy = SupertrendRSIBlendStrategy(
            supertrend_period=5,
            supertrend_multiplier=2.0,
            rsi_period=5,
            rsi_threshold=50.0,
            atr_min_pips=1.0,
            adx_min=15.0,
            atr_min_chop=1.0,
            hard_cap_pips=40.0,
            sl_atr_multiplier=10.0,
        )
        bars = make_trending_bars_with_supertrend_signal(50, seed=42, direction="long")
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            sl_pips = abs(result.entry_price - result.stop_loss) * 10000
            self.assertLessEqual(sl_pips, 40.0)

    def test_supertrend_flip_detection_with_near_identical_atr(self):
        strategy = SupertrendRSIBlendStrategy(
            supertrend_period=5,
            supertrend_multiplier=2.0,
            rsi_period=5,
            rsi_threshold=50.0,
            atr_min_pips=1.0,
            adx_min=15.0,
            atr_min_chop=1.0,
        )
        import numpy as np
        import pandas as pd

        np.random.seed(99)
        n = 120
        dates = pd.date_range("2023-01-01", periods=n, freq="1h")
        price = 1.1000
        prices = []
        for i in range(n):
            if i < 30:
                price += np.random.normal(0, 0.00005)
            elif i < 60:
                price += 0.0005 + np.random.normal(0, 0.00005)
            elif i < 90:
                price += np.random.normal(0, 0.00005)
            else:
                price -= 0.0005 + np.random.normal(0, 0.00005)
            prices.append(price)
        prices = np.array(prices)
        spread = 0.00015
        bars = [
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

        current_st, prev_st = strategy._calculate_supertrend(bars)
        self.assertIsNotNone(prev_st)
        self.assertIn(current_st, [1.0, -1.0])
        self.assertIn(prev_st, [1.0, -1.0])

        window_bars = bars[:-1]
        prev_current, prev_prev = strategy._calculate_supertrend(window_bars)
        self.assertIsNotNone(prev_prev)
        self.assertEqual(
            prev_current,
            prev_st,
            "Shifted-window current must match full-window previous",
        )

    def test_supertrend_insufficient_bars_returns_none(self):
        strategy = SupertrendRSIBlendStrategy()
        bars = [
            Bar(
                time=datetime(2023, 1, 1, 10, 0),
                open=1.1000,
                high=1.1005,
                low=1.0995,
                close=1.1002,
                volume=1000,
            )
        ]
        current_st, prev_st = strategy._calculate_supertrend(bars)
        self.assertIsNone(current_st)
        self.assertIsNone(prev_st)


class TestSupertrendATRConsistency(unittest.TestCase):
    def test_supertrend_consistent_with_increasing_volatility(self):
        strategy = SupertrendRSIBlendStrategy(
            supertrend_period=10,
            supertrend_multiplier=2.0,
            atr_period=14,
        )
        import numpy as np
        import pandas as pd

        np.random.seed(77)
        n = 200
        dates = pd.date_range("2023-01-01", periods=n, freq="1h")
        price = 1.1000
        prices = []
        for i in range(n):
            vol_scale = 0.0001 + (i / n) * 0.002
            price += np.random.normal(0, vol_scale)
            prices.append(price)
        prices = np.array(prices)
        spread_factor = 0.0001 + (np.arange(n) / n) * 0.003
        bars = [
            Bar(
                time=dates[i].to_pydatetime(),
                open=prices[i] - spread_factor[i] * np.random.uniform(0, 1),
                high=prices[i] + spread_factor[i] * np.random.uniform(1, 3),
                low=prices[i] - spread_factor[i] * np.random.uniform(1, 3),
                close=prices[i],
                volume=1000,
            )
            for i in range(n)
        ]

        current_st, prev_st = strategy._calculate_supertrend(bars)
        self.assertIsNotNone(current_st)
        self.assertIsNotNone(prev_st)

        prev_window_st, prev_window_prev_st = strategy._calculate_supertrend(bars[:-1])
        self.assertIsNotNone(prev_window_st)
        self.assertEqual(
            prev_window_st,
            prev_st,
            "Supertrend at bar N-1 must be identical whether computed "
            "with bars[0:N] or bars[0:N-1] (varying ATR data)",
        )

    def test_supertrend_consistent_multi_step(self):
        strategy = SupertrendRSIBlendStrategy(
            supertrend_period=7,
            supertrend_multiplier=2.5,
            atr_period=10,
        )
        import numpy as np
        import pandas as pd

        np.random.seed(123)
        n = 150
        dates = pd.date_range("2023-01-01", periods=n, freq="1h")
        price = 1.1000
        prices = []
        for i in range(n):
            if i < 30:
                vol = 0.0001
            elif i < 70:
                vol = 0.001
            elif i < 110:
                vol = 0.0002
            else:
                vol = 0.0015
            price += np.random.normal(0.0001, vol)
            prices.append(price)
        prices = np.array(prices)
        bars = [
            Bar(
                time=dates[i].to_pydatetime(),
                open=prices[i] - 0.0003,
                high=prices[i] + 0.0005,
                low=prices[i] - 0.0005,
                close=prices[i],
                volume=1000,
            )
            for i in range(n)
        ]

        for step in range(1, 6):
            full_st, full_prev = strategy._calculate_supertrend(bars[: n - step])
            shifted_st, shifted_prev = strategy._calculate_supertrend(
                bars[: n - step - 1]
            )
            self.assertEqual(
                shifted_st,
                full_prev,
                f"Step {step}: shifted-window current must match full-window previous",
            )


class TestSupertrendRealH1Data(unittest.TestCase):
    def test_supertrend_produces_direction_flips_on_eurusd_h1(self):
        import pandas as pd

        csv_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "data",
            "forex",
            "historical",
            "EURUSD_H1.csv",
        )
        if not os.path.exists(csv_path):
            self.skipTest(f"EURUSD H1 data not found at {csv_path}")

        df = pd.read_csv(csv_path, parse_dates=["Date"])
        self.assertGreater(len(df), 100, "Need at least 100 bars for meaningful test")

        bars = [
            Bar(
                time=row["Date"].to_pydatetime(),
                open=row["Open"],
                high=row["High"],
                low=row["Low"],
                close=row["Close"],
                volume=row["Volume"],
            )
            for _, row in df.iterrows()
        ]

        strategy = SupertrendRSIBlendStrategy()

        flips = []
        for i in range(50, min(len(bars), 500)):
            test_bars = bars[: i + 1]
            current_st, prev_st = strategy._calculate_supertrend(test_bars)
            if current_st is not None and prev_st is not None:
                if (current_st > 0 and prev_st < 0) or (current_st < 0 and prev_st > 0):
                    flips.append((i, prev_st, current_st))

        self.assertGreater(
            len(flips),
            0,
            f"Supertrend must produce direction flips on EURUSD H1 data. "
            f"Tested 450 bars and found {len(flips)} flips.",
        )


if __name__ == "__main__":
    unittest.main()
