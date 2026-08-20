import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar, MarketState, TradeDirection
from backtest.strategies import KeltnerChannelBreakoutStrategy


def _make_bars(n=100, seed=42, base_price=1.1000, trend="flat", vol=0.0005, volume=1000):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = base_price
    prices = []
    for i in range(n):  # noqa: B007
        drift = 0
        if trend == "up":
            drift = 0.0003
        elif trend == "down":
            drift = -0.0003
        price += drift + np.random.normal(0, vol)
        prices.append(price)
    spread = 0.0002
    return [
        Bar(
            time=dates[i].to_pydatetime(),
            open=prices[i] - spread * np.random.uniform(0, 1),
            high=prices[i] + spread * np.random.uniform(1, 3),
            low=prices[i] - spread * np.random.uniform(1, 3),
            close=prices[i],
            volume=volume + np.random.randint(-100, 100),
        )
        for i in range(n)
    ]


def _make_deterministic_breakout_bars(direction="long", n=50):
    """Construct bars that deterministically produce a breakout signal.

    Phase 1 (bars 0 to n-2): Steady trend with small increments that build
    ADX above threshold while keeping price within the Keltner Channel.
    Phase 2 (last bar): Single strong breakout that exceeds channel band.
    """
    bars = []
    dt = datetime(2023, 1, 1, 0, 0)
    base = 1.1000
    price = base

    for i in range(n - 1):  # noqa: B007
        if direction == "long":
            price += 0.0001
        else:
            price -= 0.0001

        bars.append(
            Bar(
                time=dt,
                open=price - 0.00005,
                high=price + 0.0004,
                low=price - 0.0001,
                close=price,
                volume=1500.0,
            )
        )
        dt += timedelta(hours=1)

    if direction == "long":
        price += 0.003
    else:
        price -= 0.003

    bars.append(
        Bar(
            time=dt,
            open=price - 0.001,
            high=price + 0.0005,
            low=price - 0.0002,
            close=price,
            volume=2000.0,
        )
    )

    return bars


class TestKeltnerChannelBreakoutStrategy(unittest.TestCase):
    def test_strategy_name(self):
        s = KeltnerChannelBreakoutStrategy()
        self.assertEqual(s.name, "Keltner Channel Breakout")

    def test_returns_none_with_insufficient_bars(self):
        s = KeltnerChannelBreakoutStrategy()
        state = MarketState(bars=_make_bars(20))
        self.assertIsNone(s.evaluate(state))

    def test_returns_none_without_volume(self):
        s = KeltnerChannelBreakoutStrategy()
        bars = _make_bars(100)
        for b in bars:
            b.volume = 0
        state = MarketState(bars=bars)
        self.assertIsNone(s.evaluate(state))

    def test_returns_none_when_volume_below_ma(self):
        s = KeltnerChannelBreakoutStrategy(volume_ma_period=20)
        bars = _make_bars(100, volume=1000)
        bars[-1].volume = 10
        state = MarketState(bars=bars)
        self.assertIsNone(s.evaluate(state))

    def test_returns_none_when_adx_below_threshold(self):
        s = KeltnerChannelBreakoutStrategy(adx_threshold=90.0)
        state = MarketState(bars=_make_bars(100))
        self.assertIsNone(s.evaluate(state))

    def test_custom_parameters_stored(self):
        s = KeltnerChannelBreakoutStrategy(
            ema_period=15,
            atr_period=10,
            atr_multiplier=2.0,
            atr_min_pips=10.0,
            adx_period=12,
            adx_threshold=30.0,
            volume_ma_period=25,
            sl_atr_multiplier=2.0,
            sl_max_pips=50.0,
            tp1_atr_multiplier=1.5,
            tp2_atr_multiplier=2.5,
        )
        self.assertEqual(s.ema_period, 15)
        self.assertEqual(s.atr_period, 10)
        self.assertEqual(s.atr_multiplier, 2.0)
        self.assertEqual(s.atr_min_pips, 10.0)
        self.assertEqual(s.adx_period, 12)
        self.assertEqual(s.adx_threshold, 30.0)
        self.assertEqual(s.volume_ma_period, 25)
        self.assertEqual(s.sl_atr_multiplier, 2.0)
        self.assertEqual(s.sl_max_pips, 50.0)
        self.assertEqual(s.tp1_atr_multiplier, 1.5)
        self.assertEqual(s.tp2_atr_multiplier, 2.5)

    def test_ema_calculation(self):
        s = KeltnerChannelBreakoutStrategy()
        bars = _make_bars(30)
        ema = s._calculate_ema(bars, 20)
        self.assertGreater(ema, 0)
        sma = sum(b.close for b in bars[:20]) / 20
        self.assertAlmostEqual(ema, sma, delta=0.01)

    def test_atr_calculation(self):
        s = KeltnerChannelBreakoutStrategy()
        bars = _make_bars(30)
        atr = s._calculate_atr(bars, 14)
        self.assertGreater(atr, 0)

    def test_atr_returns_zero_for_insufficient_bars(self):
        s = KeltnerChannelBreakoutStrategy()
        bars = _make_bars(10)
        atr = s._calculate_atr(bars, 14)
        self.assertEqual(atr, 0.0)

    def test_volume_ma_calculation(self):
        s = KeltnerChannelBreakoutStrategy(volume_ma_period=10)
        bars = _make_bars(30, volume=500)
        vol_ma = s._calculate_volume_ma(bars)
        self.assertGreater(vol_ma, 0)
        self.assertAlmostEqual(vol_ma, 500, delta=20)

    def test_pip_value_calculation(self):
        self.assertEqual(KeltnerChannelBreakoutStrategy._get_pip_value(150.0), 0.01)
        self.assertEqual(KeltnerChannelBreakoutStrategy._get_pip_value(1.1000), 0.0001)
        self.assertEqual(KeltnerChannelBreakoutStrategy._get_pip_value(0.00001), 0.00000001)

    def test_signal_structure_on_strong_trend(self):
        s = KeltnerChannelBreakoutStrategy(
            ema_period=10,
            atr_period=10,
            adx_threshold=20.0,
            atr_min_pips=1.0,
            volume_ma_period=10,
        )
        bars = _make_deterministic_breakout_bars("long", n=50)
        state = MarketState(bars=bars)
        result = s.evaluate(state)
        self.assertIsNotNone(result)
        self.assertIn(result.direction, [TradeDirection.LONG, TradeDirection.SHORT])
        self.assertGreater(result.entry_price, 0)
        self.assertGreater(result.confidence, 0)
        self.assertGreater(result.stop_loss, 0)
        self.assertNotEqual(result.rationale, "")

    def test_long_signal_tp_levels_correct(self):
        s = KeltnerChannelBreakoutStrategy(
            ema_period=10,
            atr_period=10,
            adx_threshold=20.0,
            atr_min_pips=1.0,
            volume_ma_period=10,
            sl_atr_multiplier=1.5,
            tp1_atr_multiplier=2.0,
            tp2_atr_multiplier=3.0,
        )
        bars = _make_deterministic_breakout_bars("long", n=50)
        state = MarketState(bars=bars)
        result = s.evaluate(state)
        self.assertIsNotNone(result)
        self.assertEqual(result.direction, TradeDirection.LONG)
        self.assertGreater(result.take_profit_1, result.entry_price)
        self.assertGreater(result.take_profit_2, result.take_profit_1)
        self.assertGreater(result.take_profit_3, result.take_profit_2)
        self.assertLess(result.stop_loss, result.entry_price)

    def test_short_signal_tp_levels_correct(self):
        s = KeltnerChannelBreakoutStrategy(
            ema_period=10,
            atr_period=10,
            adx_threshold=20.0,
            atr_min_pips=1.0,
            volume_ma_period=10,
        )
        bars = _make_deterministic_breakout_bars("short", n=50)
        state = MarketState(bars=bars)
        result = s.evaluate(state)
        self.assertIsNotNone(result)
        self.assertEqual(result.direction, TradeDirection.SHORT)
        self.assertLess(result.take_profit_1, result.entry_price)
        self.assertLess(result.take_profit_2, result.take_profit_1)
        self.assertLess(result.take_profit_3, result.take_profit_2)
        self.assertGreater(result.stop_loss, result.entry_price)

    def test_confidence_scaling(self):
        s = KeltnerChannelBreakoutStrategy(
            ema_period=10,
            atr_period=10,
            adx_threshold=20.0,
            atr_min_pips=1.0,
            volume_ma_period=10,
        )
        bars = _make_deterministic_breakout_bars("long", n=50)
        state = MarketState(bars=bars)
        result = s.evaluate(state)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.confidence, 0.6)
        self.assertLessEqual(result.confidence, 0.8)

    def test_rationale_contains_key_info(self):
        s = KeltnerChannelBreakoutStrategy(
            ema_period=10,
            atr_period=10,
            adx_threshold=20.0,
            atr_min_pips=1.0,
            volume_ma_period=10,
        )
        bars = _make_deterministic_breakout_bars("long", n=50)
        state = MarketState(bars=bars)
        result = s.evaluate(state)
        self.assertIsNotNone(result)
        self.assertIn("KC breakout", result.rationale)
        self.assertIn("ADX", result.rationale)

    def test_gbpjpy_pip_value(self):
        price = 185.50
        pip_value = KeltnerChannelBreakoutStrategy._get_pip_value(price)
        self.assertEqual(pip_value, 0.01)

    def test_adx_returns_none_for_insufficient_bars(self):
        s = KeltnerChannelBreakoutStrategy(adx_period=14)
        bars = _make_bars(20)
        result = s._calculate_adx(bars)
        self.assertIsNone(result)

    def test_no_signal_in_flat_market(self):
        s = KeltnerChannelBreakoutStrategy(
            ema_period=20,
            atr_period=14,
            adx_threshold=25.0,
            atr_min_pips=1.0,
            volume_ma_period=20,
        )
        bars = _make_bars(100, trend="flat", vol=0.00005, volume=1500)
        state = MarketState(bars=bars)
        result = s.evaluate(state)
        self.assertIsNone(result)

    def test_sl_max_pips_cap(self):
        s = KeltnerChannelBreakoutStrategy(
            ema_period=10,
            atr_period=10,
            adx_threshold=20.0,
            atr_min_pips=1.0,
            volume_ma_period=10,
            sl_max_pips=5.0,
            sl_atr_multiplier=10.0,
            lod_hod_stop_buffer_pips=0.0,
        )
        bars = _make_deterministic_breakout_bars("long", n=50)
        state = MarketState(bars=bars)
        result = s.evaluate(state)
        self.assertIsNotNone(result)
        pip_value = s._get_pip_value(result.entry_price)
        sl_pips = abs(result.entry_price - result.stop_loss) / pip_value
        self.assertLessEqual(sl_pips, 5.0)

    def test_returns_none_when_ema_is_zero(self):
        s = KeltnerChannelBreakoutStrategy()
        bars = []
        dt = datetime(2023, 1, 1, 0, 0)
        for i in range(100):  # noqa: B007
            bars.append(
                Bar(
                    time=dt,
                    open=0.0,
                    high=0.0,
                    low=0.0,
                    close=0.0,
                    volume=1000.0,
                )
            )
            dt += timedelta(hours=1)
        state = MarketState(bars=bars)
        self.assertIsNone(s.evaluate(state))

    def test_returns_none_when_atr_is_zero(self):
        s = KeltnerChannelBreakoutStrategy()
        bars = []
        dt = datetime(2023, 1, 1, 0, 0)
        for i in range(100):  # noqa: B007
            bars.append(
                Bar(
                    time=dt,
                    open=1.1000,
                    high=1.1000,
                    low=1.1000,
                    close=1.1000,
                    volume=1000.0,
                )
            )
            dt += timedelta(hours=1)
        state = MarketState(bars=bars)
        self.assertIsNone(s.evaluate(state))

    def test_returns_none_when_atr_pips_below_min(self):
        s = KeltnerChannelBreakoutStrategy(atr_min_pips=100000.0)
        bars = _make_deterministic_breakout_bars("long", n=50)
        state = MarketState(bars=bars)
        self.assertIsNone(s.evaluate(state))

    def test_adx_returns_none_when_tr_sum_is_zero(self):
        s = KeltnerChannelBreakoutStrategy(adx_period=14)
        bars = []
        dt = datetime(2023, 1, 1, 0, 0)
        for i in range(50):  # noqa: B007
            bars.append(
                Bar(
                    time=dt,
                    open=1.1000,
                    high=1.1000,
                    low=1.1000,
                    close=1.1000,
                    volume=1000.0,
                )
            )
            dt += timedelta(hours=1)
        self.assertIsNone(s._calculate_adx(bars))

    def test_adx_returns_zero_when_di_sum_is_zero(self):
        s = KeltnerChannelBreakoutStrategy(adx_period=14)
        bars = []
        dt = datetime(2023, 1, 1, 0, 0)
        for i in range(50):
            close = 1.1000 + 0.0001 * ((i % 3) - 1)
            bars.append(
                Bar(
                    time=dt,
                    open=close,
                    high=1.1002,
                    low=1.0998,
                    close=close,
                    volume=1000.0,
                )
            )
            dt += timedelta(hours=1)
        result = s._calculate_adx(bars)
        self.assertEqual(result, 0.0)

    def test_adx_smoothing_handles_zero_di_sum(self):
        s = KeltnerChannelBreakoutStrategy(adx_period=5)
        bars = []
        dt = datetime(2023, 1, 1, 0, 0)
        for i in range(30):
            if i < 15:
                high = 1.1000 + i * 0.0002
                low = 1.1000 + i * 0.0002 - 0.0001
                close = high
            else:
                high = 1.1030
                low = 1.1029
                close = 1.10295 + 0.0001 * ((i % 3) - 1)
            bars.append(
                Bar(
                    time=dt,
                    open=close,
                    high=high,
                    low=low,
                    close=close,
                    volume=1000.0,
                )
            )
            dt += timedelta(hours=1)
        result = s._calculate_adx(bars)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result, 0.0)

    def test_volume_ma_returns_zero_for_insufficient_bars(self):
        s = KeltnerChannelBreakoutStrategy(volume_ma_period=20)
        bars = _make_bars(10, volume=1000)
        self.assertEqual(s._calculate_volume_ma(bars), 0.0)

    def test_long_breakout_rejected_when_ema_not_rising(self):
        s = KeltnerChannelBreakoutStrategy(
            ema_period=10,
            atr_period=10,
            adx_threshold=20.0,
            atr_min_pips=1.0,
            volume_ma_period=10,
        )
        bars = []
        dt = datetime(2023, 1, 1, 0, 0)
        base = 1.1000
        for i in range(48):  # noqa: B007
            base -= 0.0001
            bars.append(
                Bar(
                    time=dt,
                    open=base + 0.00005,
                    high=base + 0.0003,
                    low=base - 0.0001,
                    close=base,
                    volume=1500.0,
                )
            )
            dt += timedelta(hours=1)
        spike_close = base + 0.0001
        bars.append(
            Bar(
                time=dt,
                open=base,
                high=spike_close + 0.0005,
                low=base - 0.0001,
                close=spike_close,
                volume=2000.0,
            )
        )
        state = MarketState(bars=bars)
        result = s.evaluate(state)
        self.assertIsNone(result)

    def test_short_breakout_rejected_when_ema_not_falling(self):
        s = KeltnerChannelBreakoutStrategy(
            ema_period=10,
            atr_period=10,
            adx_threshold=20.0,
            atr_min_pips=1.0,
            volume_ma_period=10,
        )
        bars = []
        dt = datetime(2023, 1, 1, 0, 0)
        base = 1.1000
        for i in range(48):  # noqa: B007
            base += 0.0001
            bars.append(
                Bar(
                    time=dt,
                    open=base - 0.00005,
                    high=base + 0.0001,
                    low=base - 0.0003,
                    close=base,
                    volume=1500.0,
                )
            )
            dt += timedelta(hours=1)
        spike_close = base - 0.0001
        bars.append(
            Bar(
                time=dt,
                open=base,
                high=base + 0.0001,
                low=spike_close - 0.0005,
                close=spike_close,
                volume=2000.0,
            )
        )
        state = MarketState(bars=bars)
        result = s.evaluate(state)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
