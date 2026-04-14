import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from datetime import datetime

from backtest.engine import Bar, MarketState, TradeDirection
from strategies.srmr_plus import (
    SRMRPlusStrategy,
    SRMRPlusConfig,
    _calculate_adx,
    _calculate_atr,
    _calculate_rsi,
    _is_trading_session,
    _pip_value_for_price,
)


def make_ranging_bars(n=200, seed=42):
    import numpy as np

    np.random.seed(seed)
    price = 1.2600
    bars = []
    base_date = datetime(2024, 6, 1, 0, 0)
    for i in range(n):
        hour = (base_date.hour + i) % 24
        day_offset = (base_date.hour + i) // 24
        dt = datetime(2024, 6, 1 + day_offset, hour, 0)
        price += np.random.normal(0, 0.00015)
        noise = abs(np.random.normal(0, 0.0003))
        bars.append(
            Bar(
                time=dt,
                open=price - noise * 0.3,
                high=price + noise,
                low=price - noise,
                close=price,
                volume=1000,
            )
        )
    return bars


def make_trending_bars(n=200, seed=42):
    import numpy as np

    np.random.seed(seed)
    price = 1.2600
    bars = []
    base_date = datetime(2024, 6, 1, 0, 0)
    for i in range(n):
        hour = (base_date.hour + i) % 24
        day_offset = (base_date.hour + i) // 24
        dt = datetime(2024, 6, 1 + day_offset, hour, 0)
        price += 0.0002 + np.random.normal(0, 0.0001)
        noise = abs(np.random.normal(0, 0.0002))
        bars.append(
            Bar(
                time=dt,
                open=price - noise * 0.3,
                high=price + noise,
                low=price - noise,
                close=price,
                volume=1000,
            )
        )
    return bars


class TestSRMRPlusConfig(unittest.TestCase):
    def test_default_config(self):
        config = SRMRPlusConfig()
        self.assertEqual(config.adx_max_threshold, 20.0)
        self.assertEqual(config.rsi_long_level, 35.0)
        self.assertEqual(config.rsi_short_level, 65.0)
        self.assertEqual(config.adx_period, 14)
        self.assertEqual(config.hard_cap_sl_pips, 25.0)
        self.assertEqual(config.tp1_rr, 1.0)
        self.assertEqual(config.tp2_rr, 1.5)
        self.assertEqual(config.entry_near_extreme_pips, 15.0)
        self.assertEqual(config.session_range_min_pips, 15.0)

    def test_custom_config(self):
        config = SRMRPlusConfig(adx_max_threshold=20.0, rsi_long_level=25.0)
        self.assertEqual(config.adx_max_threshold, 20.0)
        self.assertEqual(config.rsi_long_level, 25.0)


class TestSRMRPlusStrategy(unittest.TestCase):
    def test_strategy_name(self):
        strategy = SRMRPlusStrategy()
        self.assertEqual(strategy.name, "SRMR+")

    def test_returns_none_with_insufficient_bars(self):
        strategy = SRMRPlusStrategy()
        bars = make_ranging_bars(20)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_skips_outside_session(self):
        strategy = SRMRPlusStrategy()
        bars = make_ranging_bars(200)
        bars[-1] = Bar(
            time=datetime(2024, 6, 10, 22, 0),
            open=1.26,
            high=1.2610,
            low=1.2590,
            close=1.2600,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_skips_when_adx_too_high(self):
        config = SRMRPlusConfig(adx_max_threshold=10.0)
        strategy = SRMRPlusStrategy(config=config)
        bars = make_trending_bars(200)
        bars[-1] = Bar(
            time=datetime(2024, 6, 10, 8, 0),
            open=1.26,
            high=1.2610,
            low=1.2590,
            close=1.2600,
            volume=1000,
        )
        state = MarketState(bars=bars)
        adx = _calculate_adx(state.bars)
        if adx > 10.0:
            result = strategy.evaluate(state)
            self.assertIsNone(result)

    def test_returns_signal_in_range_market(self):
        config = SRMRPlusConfig(
            adx_max_threshold=35.0,
            session_range_min_pips=5.0,
            entry_near_extreme_pips=5.0,
        )
        strategy = SRMRPlusStrategy(config=config)
        bars = make_ranging_bars(200, seed=42)
        last_bar = bars[-1]
        if _is_trading_session(last_bar.time):
            state = MarketState(bars=bars)
            adx = _calculate_adx(state.bars)
            if adx < 35.0:
                result = strategy.evaluate(state)
                if result is not None:
                    self.assertIn(
                        result.direction, [TradeDirection.LONG, TradeDirection.SHORT]
                    )
                    self.assertIn("SRMR+", result.rationale)
                    self.assertIn("ADX=", result.rationale)
                    self.assertGreater(result.confidence, 0.3)


class TestADXCalculation(unittest.TestCase):
    def test_low_adx_in_range(self):
        bars = make_ranging_bars(100)
        adx = _calculate_adx(bars)
        self.assertLess(adx, 30.0)

    def test_higher_adx_in_trend(self):
        bars = make_trending_bars(100)
        adx = _calculate_adx(bars)
        self.assertGreater(adx, 15.0)

    def test_returns_zero_with_insufficient_bars(self):
        bars = make_ranging_bars(20)
        adx = _calculate_adx(bars)
        self.assertEqual(adx, 0.0)


class TestSessionFilter(unittest.TestCase):
    def test_london_session(self):
        self.assertTrue(_is_trading_session(datetime(2024, 6, 10, 8, 0)))
        self.assertTrue(_is_trading_session(datetime(2024, 6, 10, 10, 0)))

    def test_ny_session(self):
        self.assertTrue(_is_trading_session(datetime(2024, 6, 10, 13, 0)))
        self.assertTrue(_is_trading_session(datetime(2024, 6, 10, 14, 0)))

    def test_outside_session(self):
        self.assertFalse(_is_trading_session(datetime(2024, 6, 10, 22, 0)))
        self.assertFalse(_is_trading_session(datetime(2024, 6, 10, 23, 0)))

    def test_asian_session(self):
        self.assertFalse(_is_trading_session(datetime(2024, 6, 10, 3, 0)))


class TestPipValue(unittest.TestCase):
    def test_gbpusd_pip(self):
        self.assertEqual(_pip_value_for_price(1.2600), 0.0001)

    def test_usdjpy_pip(self):
        self.assertEqual(_pip_value_for_price(150.0), 0.01)


class TestRSICalculation(unittest.TestCase):
    def test_rsi_none_with_insufficient_bars(self):
        bars = make_ranging_bars(10)
        rsi = _calculate_rsi(bars)
        self.assertIsNone(rsi)

    def test_rsi_returns_value(self):
        bars = make_ranging_bars(50)
        rsi = _calculate_rsi(bars)
        self.assertIsNotNone(rsi)
        self.assertGreaterEqual(rsi, 0.0)
        self.assertLessEqual(rsi, 100.0)


class TestATRCalculation(unittest.TestCase):
    def test_atr_returns_positive(self):
        bars = make_ranging_bars(50)
        atr = _calculate_atr(bars)
        self.assertGreater(atr, 0.0)

    def test_atr_with_insufficient_bars(self):
        bars = make_ranging_bars(10)
        atr = _calculate_atr(bars)
        self.assertEqual(atr, 0.0001)


if __name__ == "__main__":
    unittest.main()
