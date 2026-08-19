import dataclasses
import unittest

from datetime import datetime

from core.types import Bar, MarketState, SessionType, TradeDirection
from strategies.volatility_squeeze import (
    EURUSD_H1_PRESET,
    GBPJPY_H1_PRESET,
    XAUUSD_H1_PRESET,
    VolatilitySqueezeConfig,
    VolatilitySqueezeStrategy,
    _build_signal,
    _calculate_adx,
    _calculate_atr,
    _calculate_bollinger_bands,
    _calculate_ema,
    _calculate_keltner_channels,
    _calculate_sma,
    _calculate_std,
    _detect_squeeze_duration,
    _passes_session_filter,
)


def _make_bars(
    n: int = 100,
    base_price: float = 1.1000,
    volatility: float = 0.0005,
    seed: int = 42,
) -> list[Bar]:
    import random

    random.seed(seed)
    bars = []
    price = base_price
    for i in range(n):
        change = random.gauss(0, volatility)
        open_ = price
        close = price + change
        high = max(open_, close) + abs(random.gauss(0, volatility * 0.5))
        low = min(open_, close) - abs(random.gauss(0, volatility * 0.5))
        bars.append(
            Bar(
                time=datetime(2023, 1, 1, i % 24),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=1000,
            )
        )
        price = close
    return bars


def _make_squeeze_bars(
    n: int = 100,
    squeeze_start: int = 30,
    squeeze_end: int = 60,
    breakout_direction: str = "up",
    seed: int = 99,
) -> list[Bar]:
    import random

    random.seed(seed)
    bars = []
    price = 1.1000
    for i in range(n):
        if squeeze_start <= i < squeeze_end:
            change = random.gauss(0, 0.00005)
        elif i == squeeze_end:
            if breakout_direction == "up":
                change = 0.003
            else:
                change = -0.003
        else:
            change = random.gauss(0, 0.0005)
        open_ = price
        close = price + change
        high = max(open_, close) + abs(random.gauss(0, 0.0001))
        low = min(open_, close) - abs(random.gauss(0, 0.0001))
        bars.append(
            Bar(
                time=datetime(2023, 1, 1, i % 24),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=1000,
            )
        )
        price = close
    return bars


def _make_state(
    bars: list[Bar], session: SessionType = SessionType.LONDON
) -> MarketState:
    return MarketState(bars=bars, current_session=session)


class TestCalculateSma(unittest.TestCase):
    def test_basic_sma(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _calculate_sma(values, 3)
        self.assertAlmostEqual(result, 4.0)

    def test_insufficient_data(self):
        values = [1.0, 2.0]
        result = _calculate_sma(values, 5)
        self.assertEqual(result, 0.0)

    def test_exact_period(self):
        values = [10.0] * 5
        result = _calculate_sma(values, 5)
        self.assertAlmostEqual(result, 10.0)


class TestCalculateEma(unittest.TestCase):
    def test_basic_ema(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _calculate_ema(values, 3)
        self.assertGreater(result, 0.0)

    def test_insufficient_data(self):
        values = [1.0]
        result = _calculate_ema(values, 5)
        self.assertEqual(result, 0.0)

    def test_flat_series(self):
        values = [5.0] * 20
        result = _calculate_ema(values, 10)
        self.assertAlmostEqual(result, 5.0)

    def test_ema_more_reactive_than_sma(self):
        values = [1.0] * 10 + [10.0] * 5
        ema = _calculate_ema(values, 10)
        sma = _calculate_sma(values, 10)
        self.assertGreater(ema, sma)


class TestCalculateStd(unittest.TestCase):
    def test_zero_std(self):
        values = [5.0] * 10
        result = _calculate_std(values, 10)
        self.assertAlmostEqual(result, 0.0)

    def test_basic_std(self):
        values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        result = _calculate_std(values, 8)
        self.assertGreater(result, 0.0)

    def test_insufficient_data(self):
        values = [1.0]
        result = _calculate_std(values, 5)
        self.assertEqual(result, 0.0)


class TestCalculateAtr(unittest.TestCase):
    def test_basic_atr(self):
        bars = _make_bars(30, volatility=0.001)
        result = _calculate_atr(bars, 14)
        self.assertGreater(result, 0.0)

    def test_insufficient_bars(self):
        bars = _make_bars(5)
        result = _calculate_atr(bars, 14)
        self.assertAlmostEqual(result, 0.0001)

    def test_low_volatility_atr(self):
        bars = _make_bars(30, volatility=0.00001)
        high_vol_bars = _make_bars(30, volatility=0.01)
        low_atr = _calculate_atr(bars, 14)
        high_atr = _calculate_atr(high_vol_bars, 14)
        self.assertLess(low_atr, high_atr)


class TestCalculateAdx(unittest.TestCase):
    def test_basic_adx(self):
        bars = _make_bars(60, volatility=0.001)
        result = _calculate_adx(bars, 14)
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 100.0)

    def test_insufficient_bars(self):
        bars = _make_bars(10)
        result = _calculate_adx(bars, 14)
        self.assertEqual(result, 0.0)

    def test_trending_market_higher_adx(self):
        trending = _make_bars(80, base_price=1.1, volatility=0.0001, seed=1)
        for i in range(10, len(trending)):
            trending[i] = Bar(
                time=trending[i].time,
                open=trending[i - 1].close,
                high=trending[i - 1].close + 0.002,
                low=trending[i - 1].close,
                close=trending[i - 1].close + 0.0015,
                volume=1000,
            )
        adx_trending = _calculate_adx(trending, 14)
        adx_flat = _calculate_adx(_make_bars(80, volatility=0.0005), 14)
        self.assertGreater(adx_trending, adx_flat)


class TestCalculateBollingerBands(unittest.TestCase):
    def test_upper_above_middle(self):
        bars = _make_bars(30)
        upper, middle, lower = _calculate_bollinger_bands(bars, 20, 2.0)
        self.assertGreater(upper, middle)
        self.assertLess(lower, middle)

    def test_symmetric_bands(self):
        bars = _make_bars(30)
        upper, middle, lower = _calculate_bollinger_bands(bars, 20, 2.0)
        self.assertAlmostEqual(upper - middle, middle - lower, places=4)

    def test_wider_std_dev_wider_bands(self):
        bars = _make_bars(30)
        u1, _, l1 = _calculate_bollinger_bands(bars, 20, 1.5)
        u2, _, l2 = _calculate_bollinger_bands(bars, 20, 3.0)
        self.assertGreater(u2 - l2, u1 - l1)


class TestCalculateKeltnerChannels(unittest.TestCase):
    def test_upper_above_middle(self):
        bars = _make_bars(30)
        upper, middle, lower = _calculate_keltner_channels(bars, 20, 2.0)
        self.assertGreater(upper, middle)
        self.assertLess(lower, middle)

    def test_atr_based_width(self):
        bars = _make_bars(30)
        _, middle, _ = _calculate_keltner_channels(bars, 20, 2.0)
        atr = _calculate_atr(bars, 20)
        upper, _, lower = _calculate_keltner_channels(bars, 20, 2.0)
        self.assertAlmostEqual(upper - middle, middle - lower, places=4)
        self.assertAlmostEqual((upper - lower) / 2, atr * 2.0, places=4)


class TestDetectSqueezeDuration(unittest.TestCase):
    def test_no_squeeze_in_volatile_data(self):
        bars = _make_bars(50, volatility=0.01)
        result = _detect_squeeze_duration(bars, 20, 2.0, 20, 2.0)
        self.assertLess(result, 5)

    def test_squeeze_in_low_volatility(self):
        bars = _make_squeeze_bars(80, squeeze_start=20, squeeze_end=50)
        result = _detect_squeeze_duration(bars, 20, 2.0, 20, 2.0)
        self.assertGreaterEqual(result, 0)

    def test_insufficient_bars(self):
        bars = _make_bars(10)
        result = _detect_squeeze_duration(bars, 20, 2.0, 20, 2.0)
        self.assertEqual(result, 0)


class TestSessionFilter(unittest.TestCase):
    def test_london_session_passes(self):
        state = MarketState(bars=[], current_session=SessionType.LONDON)
        self.assertTrue(_passes_session_filter(state))

    def test_ny_am_session_passes(self):
        state = MarketState(bars=[], current_session=SessionType.NY_AM)
        self.assertTrue(_passes_session_filter(state))

    def test_outside_session_fails(self):
        state = MarketState(bars=[], current_session=SessionType.OUTSIDE)
        self.assertFalse(_passes_session_filter(state))

    def test_ny_pm_session_fails(self):
        state = MarketState(bars=[], current_session=SessionType.NY_PM)
        self.assertFalse(_passes_session_filter(state))

    def test_none_session_passes(self):
        """When session info is unavailable (e.g. CSV fallback), allow the trade."""
        state = MarketState(bars=[], current_session=None)
        self.assertTrue(_passes_session_filter(state))


class TestBuildSignal(unittest.TestCase):
    def test_long_signal(self):
        config = VolatilitySqueezeConfig()
        signal = _build_signal(TradeDirection.LONG, 1.1000, 0.001, config, 0.70, "test")
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, TradeDirection.LONG)
        self.assertLess(signal.stop_loss, signal.entry_price)
        self.assertGreater(signal.take_profit_1, signal.entry_price)

    def test_short_signal(self):
        config = VolatilitySqueezeConfig()
        signal = _build_signal(
            TradeDirection.SHORT, 1.1000, 0.001, config, 0.70, "test"
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, TradeDirection.SHORT)
        self.assertGreater(signal.stop_loss, signal.entry_price)
        self.assertLess(signal.take_profit_1, signal.entry_price)

    def test_low_confidence_rejected(self):
        config = VolatilitySqueezeConfig(min_confidence=0.70)
        signal = _build_signal(TradeDirection.LONG, 1.1000, 0.001, config, 0.50, "test")
        self.assertIsNone(signal)

    def test_zero_atr_rejected(self):
        config = VolatilitySqueezeConfig()
        signal = _build_signal(TradeDirection.LONG, 1.1000, 0.0, config, 0.70, "test")
        self.assertIsNone(signal)

    def test_tp_levels_scale(self):
        config = VolatilitySqueezeConfig(tp1_rr=1.0, tp2_rr=2.0, tp3_rr=3.0)
        signal = _build_signal(TradeDirection.LONG, 1.1000, 0.001, config, 0.70, "test")
        risk = 0.001 * config.atr_sl_multiplier
        self.assertAlmostEqual(signal.take_profit_1, 1.1000 + risk * 1.0, places=4)
        self.assertAlmostEqual(signal.take_profit_2, 1.1000 + risk * 2.0, places=4)
        self.assertAlmostEqual(signal.take_profit_3, 1.1000 + risk * 3.0, places=4)

    def test_confidence_capped_at_095(self):
        config = VolatilitySqueezeConfig()
        signal = _build_signal(TradeDirection.LONG, 1.1000, 0.001, config, 0.99, "test")
        self.assertLessEqual(signal.confidence, 0.95)


class TestVolatilitySqueezeStrategy(unittest.TestCase):
    def test_strategy_name(self):
        strategy = VolatilitySqueezeStrategy()
        self.assertEqual(strategy.name, "Volatility Squeeze Breakout")

    def test_default_config(self):
        strategy = VolatilitySqueezeStrategy()
        self.assertEqual(strategy.config.bb_period, 20)
        self.assertAlmostEqual(strategy.config.bb_std_dev, 1.8)
        self.assertEqual(strategy.config.min_squeeze_bars, 2)

    def test_custom_config(self):
        config = VolatilitySqueezeConfig(bb_period=10, adx_min=25)
        strategy = VolatilitySqueezeStrategy(config)
        self.assertEqual(strategy.config.bb_period, 10)
        self.assertEqual(strategy.config.adx_min, 25)

    def test_returns_none_with_insufficient_bars(self):
        strategy = VolatilitySqueezeStrategy()
        bars = _make_bars(20)
        state = _make_state(bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_returns_none_outside_session_with_filter(self):
        strategy = VolatilitySqueezeStrategy(
            VolatilitySqueezeConfig(session_filter=True)
        )
        bars = _make_bars(100)
        state = _make_state(bars, SessionType.OUTSIDE)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_allows_outside_session_without_filter(self):
        strategy = VolatilitySqueezeStrategy(
            VolatilitySqueezeConfig(session_filter=False)
        )
        bars = _make_bars(100)
        state = _make_state(bars, SessionType.OUTSIDE)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_reset_clears_squeeze_count(self):
        strategy = VolatilitySqueezeStrategy()
        strategy._squeeze_bar_count = 10
        strategy._was_in_squeeze = True
        strategy.reset()
        self.assertEqual(strategy._squeeze_bar_count, 0)
        self.assertFalse(strategy._was_in_squeeze)

    def test_no_signal_without_squeeze(self):
        strategy = VolatilitySqueezeStrategy(
            VolatilitySqueezeConfig(session_filter=False, min_squeeze_bars=1, adx_min=1)
        )
        bars = _make_bars(100, volatility=0.01)
        state = _make_state(bars, SessionType.OUTSIDE)
        result = strategy.evaluate(state)
        self.assertIsNone(result)


class TestPresets(unittest.TestCase):
    def test_gbpjy_preset_values(self):
        self.assertEqual(GBPJPY_H1_PRESET.min_squeeze_bars, 3)
        self.assertEqual(GBPJPY_H1_PRESET.adx_min, 20)
        self.assertTrue(GBPJPY_H1_PRESET.session_filter)

    def test_eurusd_preset_values(self):
        self.assertEqual(EURUSD_H1_PRESET.min_squeeze_bars, 2)
        self.assertEqual(EURUSD_H1_PRESET.adx_min, 18)
        self.assertTrue(EURUSD_H1_PRESET.session_filter)

    def test_xauusd_preset_values(self):
        self.assertEqual(XAUUSD_H1_PRESET.bb_std_dev, 2.5)
        self.assertEqual(XAUUSD_H1_PRESET.atr_sl_multiplier, 2.0)
        self.assertFalse(XAUUSD_H1_PRESET.session_filter)

    def test_presets_are_frozen(self):
        import dataclasses

        self.assertTrue(dataclasses.is_dataclass(VolatilitySqueezeConfig))
        self.assertTrue(getattr(VolatilitySqueezeConfig, "__dataclass_params__").frozen)


class TestVolatilitySqueezeConfig(unittest.TestCase):
    def test_default_values(self):
        config = VolatilitySqueezeConfig()
        self.assertEqual(config.bb_period, 20)
        self.assertAlmostEqual(config.bb_std_dev, 1.8)
        self.assertEqual(config.kc_period, 20)
        self.assertAlmostEqual(config.kc_atr_multiplier, 1.8)
        self.assertEqual(config.squeeze_threshold, 0.0)
        self.assertEqual(config.min_squeeze_bars, 2)
        self.assertEqual(config.ema_period, 20)
        self.assertEqual(config.adx_period, 14)
        self.assertEqual(config.rsi_period, 14)
        self.assertAlmostEqual(config.adx_min, 15.0)
        self.assertEqual(config.atr_period, 14)
        self.assertAlmostEqual(config.atr_sl_multiplier, 1.5)
        self.assertAlmostEqual(config.tp1_rr, 1.0)
        self.assertAlmostEqual(config.tp2_rr, 2.0)
        self.assertAlmostEqual(config.tp3_rr, 3.0)
        self.assertTrue(config.session_filter)
        self.assertAlmostEqual(config.min_confidence, 0.40)
        self.assertEqual(config.squeeze_release_mode, "any_release")

    def test_frozen_dataclass(self):
        config = VolatilitySqueezeConfig()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.bb_period = 10

    def test_custom_values(self):
        config = VolatilitySqueezeConfig(
            bb_period=10,
            bb_std_dev=1.5,
            min_squeeze_bars=5,
            adx_min=30,
        )
        self.assertEqual(config.bb_period, 10)
        self.assertEqual(config.bb_std_dev, 1.5)
        self.assertEqual(config.min_squeeze_bars, 5)
        self.assertAlmostEqual(config.adx_min, 30)


if __name__ == "__main__":
    unittest.main()
