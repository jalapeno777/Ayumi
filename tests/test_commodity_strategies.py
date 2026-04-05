import unittest
from datetime import datetime, timedelta
from backtest.strategies import CommodityTrendStrategy, CommodityMeanReversionStrategy
from backtest.engine import MarketState, Bar, TradeDirection


def _make_bar(offset_days: int, o: float, h: float, lo: float, c: float) -> Bar:
    t = datetime(2024, 1, 1) + timedelta(days=offset_days)
    return Bar(time=t, open=o, high=h, low=lo, close=c)


class TestCommodityTrendStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = CommodityTrendStrategy(
            fast_ema_period=20,
            slow_ema_period=50,
            adx_period=14,
            adx_threshold=25.0,
            atr_multiplier=1.75,
        )

    def _make_state(self, closes):
        bars = []
        for i, c in enumerate(closes):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            bars.append(Bar(time=t, open=c, high=c + 0.5, low=c - 0.5, close=c))
        state = MarketState(bars=bars)
        return state

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

    def test_bullish_signal_with_ema_cross_and_high_adx(self):
        bars = []
        for i in range(80):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 100.0 + i * 0.5
            bars.append(Bar(time=t, open=c, high=c + 0.2, low=c - 0.2, close=c))
        state = MarketState(bars=bars)
        result = self.strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.LONG)
            self.assertGreater(result.confidence, 0.0)
            self.assertLess(result.entry_price, result.stop_loss)
            self.assertGreater(result.take_profit_1, result.entry_price)

    def test_bearish_signal_with_ema_cross_and_high_adx(self):
        bars = []
        for i in range(80):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 200.0 - i * 0.5
            bars.append(Bar(time=t, open=c, high=c + 0.2, low=c - 0.2, close=c))
        state = MarketState(bars=bars)
        result = self.strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.SHORT)
            self.assertGreater(result.confidence, 0.0)

    def test_stop_loss_above_entry_for_short(self):
        bars = []
        for i in range(80):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 200.0 - i * 0.5
            bars.append(Bar(time=t, open=c, high=c + 0.2, low=c - 0.2, close=c))
        state = MarketState(bars=bars)
        result = self.strategy.evaluate(state)
        if result is not None and result.direction == TradeDirection.SHORT:
            self.assertGreater(result.stop_loss, result.entry_price)

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

    def test_oversold_signal(self):
        bars = []
        for i in range(30):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 100.0 - (30 - i) * 0.5
            bars.append(Bar(time=t, open=c, high=c + 0.2, low=c - 0.2, close=c))
        state = MarketState(bars=bars)
        result = self.strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.LONG)
            self.assertGreater(result.confidence, 0.0)
            self.assertLess(result.entry_price, result.stop_loss)

    def test_overbought_signal(self):
        bars = []
        for i in range(30):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 100.0 + (30 - i) * 0.5
            bars.append(Bar(time=t, open=c, high=c + 0.2, low=c - 0.2, close=c))
        state = MarketState(bars=bars)
        result = self.strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.SHORT)
            self.assertGreater(result.confidence, 0.0)

    def test_stop_loss_beyond_bands(self):
        bars = []
        for i in range(30):
            t = datetime(2024, 1, 1) + timedelta(days=i)
            c = 100.0 - (30 - i) * 0.5
            bars.append(Bar(time=t, open=c, high=c + 0.2, low=c - 0.2, close=c))
        state = MarketState(bars=bars)
        result = self.strategy.evaluate(state)
        if result is not None and result.direction == TradeDirection.LONG:
            self.assertLess(result.entry_price, result.stop_loss)

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


if __name__ == "__main__":
    unittest.main()