import unittest
from datetime import datetime, timedelta
from backtest.strategies import CommodityTrendStrategy, CommodityMeanReversionStrategy
from backtest.engine import MarketState, Bar, TradeDirection


def _make_bar(offset_days: int, o: float, h: float, lo: float, c: float) -> Bar:
    t = datetime(2024, 1, 1) + timedelta(days=offset_days)
    return Bar(time=t, open=o, high=h, low=lo, close=c)


def _make_trending_bars_with_crossover() -> list:
    bars = []
    for i in range(60):
        t = datetime(2024, 1, 1) + timedelta(days=i)
        c = 150.0 - i * 2.0
        bars.append(Bar(time=t, open=c, high=c + 0.5, low=max(c - 0.5, 1), close=c))
    for i in range(60, 81):
        t = datetime(2024, 1, 1) + timedelta(days=i)
        c = 30.0 + (i - 60) * 4.0
        bars.append(Bar(time=t, open=c, high=c + 0.5, low=max(c - 0.5, 1), close=c))
    return bars


def _make_oversold_bb_reversion_bars() -> list:
    bars = []
    for i in range(25):
        t = datetime(2024, 1, 1) + timedelta(days=i)
        c = 100.0 - i * 1.5
        bars.append(Bar(time=t, open=c, high=c + 1, low=c - 1, close=c))
    sharp_drop = bars[-1].close - 50
    bars.append(
        Bar(
            time=datetime(2024, 1, 1) + timedelta(days=25),
            open=bars[-1].close,
            high=bars[-1].close + 1,
            low=sharp_drop,
            close=sharp_drop + 2,
        )
    )
    bars.append(
        Bar(
            time=datetime(2024, 1, 1) + timedelta(days=26),
            open=sharp_drop + 2,
            high=sharp_drop + 8,
            low=sharp_drop,
            close=sharp_drop + 6,
        )
    )
    return bars


class TestCommodityTrendStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = CommodityTrendStrategy(
            fast_ema_period=20,
            slow_ema_period=50,
            adx_period=14,
            adx_threshold=25.0,
            atr_multiplier=1.75,
        )

    def test_name(self):
        self.assertEqual(self.strategy.name, "Commodity Trend Following")

    def test_insufficient_bars_returns_none(self):
        bars = [_make_bar(i, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(10)]
        state = MarketState(bars=bars)
        self.assertIsNone(self.strategy.evaluate(state))

    def test_no_signal_without_adx_confirmation(self):
        bars = []
        for i in range(80):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 100.0 + i * 0.1
            bars.append(Bar(time=t, open=c, high=c + 0.1, low=c - 0.1, close=c))
        state = MarketState(bars=bars)
        result = self.strategy.evaluate(state)
        self.assertIsNone(result)

    def test_custom_parameters(self):
        strategy = CommodityTrendStrategy(
            fast_ema_period=10,
            slow_ema_period=30,
            adx_threshold=30.0,
            atr_multiplier=2.0,
        )
        self.assertEqual(strategy.fast_ema_period, 10)
        self.assertEqual(strategy.slow_ema_period, 30)
        self.assertEqual(strategy.adx_threshold, 30.0)
        self.assertEqual(strategy.atr_multiplier, 2.0)

    def test_ema_calculation_rising(self):
        bars = []
        for i in range(60):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 100.0 + i * 0.5
            bars.append(Bar(time=t, open=c, high=c + 0.3, low=c - 0.3, close=c))
        ema_fast = self.strategy._calculate_ema(bars, 20)
        ema_slow = self.strategy._calculate_ema(bars, 50)
        self.assertGreater(
            ema_fast, ema_slow, "Fast EMA should be above slow EMA for rising prices"
        )

    def test_ema_calculation_falling(self):
        bars = []
        for i in range(60):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 200.0 - i * 0.5
            bars.append(Bar(time=t, open=c, high=c + 0.3, low=c - 0.3, close=c))
        ema_fast = self.strategy._calculate_ema(bars, 20)
        ema_slow = self.strategy._calculate_ema(bars, 50)
        self.assertLess(
            ema_fast, ema_slow, "Fast EMA should be below slow EMA for falling prices"
        )

    def test_adx_calculation_requires_minimum_bars(self):
        bars = [_make_bar(i, 100, 101, 99, 100) for i in range(5)]
        adx = self.strategy._calculate_adx(bars)
        self.assertIsNone(adx, "ADX should be None with insufficient bars")

    def test_adx_calculation_with_strong_trending_data(self):
        bars = []
        for i in range(60):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 100.0 + i * 0.8
            h = c + 0.5
            l = c - 0.3
            bars.append(Bar(time=t, open=c, high=h, low=l, close=c))
        adx = self.strategy._calculate_adx(bars)
        self.assertIsNotNone(adx, "ADX should be computed with sufficient bars")
        self.assertGreater(adx, 0.0, "ADX should be positive for trending data")

    def test_signal_generation_bullish_ema_cross_high_adx(self):
        bars = _make_trending_bars_with_crossover()
        state = MarketState(bars=bars)
        result = self.strategy.evaluate(state)
        self.assertIsNotNone(
            result, "Signal should be generated on EMA crossover with high ADX"
        )
        self.assertEqual(result.direction, TradeDirection.LONG)
        self.assertGreater(result.confidence, 0.0)
        self.assertLess(result.confidence, 1.0)
        self.assertGreater(result.entry_price, 0.0)
        self.assertIsNotNone(result.stop_loss)
        self.assertIsNotNone(result.take_profit_1)
        self.assertIsNotNone(result.take_profit_2)
        self.assertIsNotNone(result.take_profit_3)
        self.assertLess(
            result.stop_loss, result.entry_price, "SL for LONG should be below entry"
        )
        self.assertGreater(
            result.take_profit_1,
            result.entry_price,
            "TP1 for LONG should be above entry",
        )
        self.assertLess(result.stop_loss, result.take_profit_1)


class TestCommodityMeanReversionStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = CommodityMeanReversionStrategy(
            bb_period=20,
            bb_std_dev=2.0,
            rsi_period=14,
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            atr_multiplier=2.0,
        )

    def test_name(self):
        self.assertEqual(self.strategy.name, "Commodity Mean Reversion")

    def test_insufficient_bars_returns_none(self):
        bars = [_make_bar(i, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(10)]
        state = MarketState(bars=bars)
        self.assertIsNone(self.strategy.evaluate(state))

    def test_no_signal_in_middle_band(self):
        bars = []
        for i in range(30):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 100.0
            bars.append(Bar(time=t, open=c, high=c + 0.1, low=c - 0.1, close=c))
        state = MarketState(bars=bars)
        result = self.strategy.evaluate(state)
        self.assertIsNone(result)

    def test_custom_parameters(self):
        strategy = CommodityMeanReversionStrategy(
            bb_period=30,
            bb_std_dev=2.5,
            rsi_oversold=25.0,
            rsi_overbought=75.0,
        )
        self.assertEqual(strategy.bb_period, 30)
        self.assertEqual(strategy.bb_std_dev, 2.5)
        self.assertEqual(strategy.rsi_oversold, 25.0)
        self.assertEqual(strategy.rsi_overbought, 75.0)

    def test_rsi_calculation_oversold(self):
        bars = []
        for i in range(30):
            if i < 14:
                c = 100.0 - (i + 1) * 1.5
            else:
                c = 79.0 - (i - 14) * 0.3
            bars.append(
                Bar(
                    time=datetime(2024, 1, 1) + timedelta(days=i),
                    open=c,
                    high=c + 0.3,
                    low=c - 0.3,
                    close=c,
                )
            )
        rsi = self.strategy._calculate_rsi(bars)
        self.assertIsNotNone(rsi)
        self.assertLess(
            rsi, 50.0, "RSI should be low after sustained decline with stabilization"
        )

    def test_rsi_calculation_overbought(self):
        bars = []
        for i in range(30):
            if i < 14:
                c = 100.0 + (i + 1) * 1.5
            else:
                c = 121.0 + (i - 14) * 0.3
            bars.append(
                Bar(
                    time=datetime(2024, 1, 1) + timedelta(days=i),
                    open=c,
                    high=c + 0.3,
                    low=c - 0.3,
                    close=c,
                )
            )
        rsi = self.strategy._calculate_rsi(bars)
        self.assertIsNotNone(rsi)
        self.assertGreater(
            rsi, 50.0, "RSI should be high after sustained advance with stabilization"
        )

    def test_rsi_calculation_neutral(self):
        bars = []
        for i in range(30):
            c = 100.0 + (i % 2) * 2.0 - 1.0
            bars.append(
                Bar(
                    time=datetime(2024, 1, 1) + timedelta(days=i),
                    open=c,
                    high=c + 0.3,
                    low=c - 0.3,
                    close=c,
                )
            )
        rsi = self.strategy._calculate_rsi(bars)
        self.assertIsNotNone(rsi)
        self.assertGreater(rsi, 30.0)
        self.assertLess(rsi, 70.0)

    def test_bollinger_bands_calculation(self):
        bars = []
        for i in range(30):
            c = 100.0 + (i % 5) * 0.5
            bars.append(
                Bar(
                    time=datetime(2024, 1, 1) + timedelta(days=i),
                    open=c,
                    high=c + 0.3,
                    low=c - 0.3,
                    close=c,
                )
            )
        sma = self.strategy._calculate_sma(bars)
        std = self.strategy._calculate_std(bars, sma)
        upper = sma + std * 2.0
        lower = sma - std * 2.0
        self.assertGreater(upper, sma)
        self.assertLess(lower, sma)

    def test_no_signal_without_reversal_candle(self):
        bars = []
        for i in range(30):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 100.0 - (30 - i) * 2.0
            bars.append(Bar(time=t, open=c, high=c + 0.5, low=c - 0.5, close=c))
        state = MarketState(bars=bars)
        result = self.strategy.evaluate(state)
        self.assertIsNone(result)

    def test_signal_generation_oversold_bb_rsi_reversal(self):
        bars = _make_oversold_bb_reversion_bars()
        state = MarketState(bars=bars)
        result = self.strategy.evaluate(state)
        self.assertIsNotNone(
            result, "Signal should be generated on BB oversold + RSI + reversal candle"
        )
        self.assertEqual(result.direction, TradeDirection.LONG)
        self.assertGreater(result.confidence, 0.0)
        self.assertLess(result.confidence, 1.0)
        self.assertGreater(result.entry_price, 0.0)
        self.assertIsNotNone(result.stop_loss)
        self.assertIsNotNone(result.take_profit_1)
        self.assertIsNotNone(result.take_profit_2)
        self.assertIsNotNone(result.take_profit_3)


class TestReversalCandleHelpers(unittest.TestCase):
    def setUp(self):
        self.strategy = CommodityMeanReversionStrategy()

    def test_bullish_reversal_candle_detected(self):
        bar = Bar(
            time=datetime(2024, 1, 1),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.7,
        )
        self.assertTrue(self.strategy._is_bullish_reversal(bar))

    def test_bullish_reversal_not_detected_when_close_near_low(self):
        bar = Bar(
            time=datetime(2024, 1, 1),
            open=100.3,
            high=101.0,
            low=99.0,
            close=99.3,
        )
        self.assertFalse(self.strategy._is_bullish_reversal(bar))

    def test_bearish_reversal_candle_detected(self):
        bar = Bar(
            time=datetime(2024, 1, 1),
            open=100.0,
            high=101.0,
            low=99.0,
            close=99.3,
        )
        self.assertTrue(self.strategy._is_bearish_reversal(bar))

    def test_bearish_reversal_not_detected_when_close_near_high(self):
        bar = Bar(
            time=datetime(2024, 1, 1),
            open=100.3,
            high=101.0,
            low=99.0,
            close=100.7,
        )
        self.assertFalse(self.strategy._is_bearish_reversal(bar))


if __name__ == "__main__":
    unittest.main()
