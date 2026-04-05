from __future__ import annotations

import sys
import os
import unittest
from datetime import datetime, timedelta
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from backtest.engine import Bar, MarketState
from quant.bar_resample import resample_bars
from quant.mtf_regime import (
    MTFRegimeConfig,
    MTFRegimeFilter,
    TrendDirection,
    VolatilityRegime,
    MarketRegime,
    TimeframeRegime,
    MultiTimeframeRegime,
    compute_confluence,
    detect_regime,
    volatility_regime_atr,
)
from strategies.momentum import (
    DonchianBreakoutStrategy,
    ATRVolatilityBreakoutStrategy,
    MATrendFollowingStrategy,
)
from strategies.mtf_filtered_momentum import MTFFilteredMomentumStrategy
from backtest.strategies import MomentumBreakoutStrategy


def _make_bars(
    n: int = 200,
    seed: int = 42,
    start: datetime | None = None,
    minutes: int = 15,
    trend: str = "up",
) -> List[Bar]:
    import random

    random.seed(seed)
    if start is None:
        start = datetime(2023, 1, 1, 0, 0)
    interval = timedelta(minutes=minutes)

    price = 1.1000
    bars = []
    for i in range(n):
        drift = 0.0002 if trend == "up" else -0.0002
        if trend == "flat":
            drift = 0.0
        noise = random.uniform(-0.0003, 0.0003)
        change = drift + noise
        price += change

        bar_open = price - random.uniform(0, 0.0001)
        bar_high = price + random.uniform(0.0001, 0.0003)
        bar_low = price - random.uniform(0.0001, 0.0003)
        bar_close = price

        bars.append(
            Bar(
                time=start + i * interval,
                open=bar_open,
                high=bar_high,
                low=bar_low,
                close=bar_close,
                volume=1000,
            )
        )
    return bars


class TestBarResample(unittest.TestCase):
    def test_resample_empty(self):
        self.assertEqual(resample_bars([], 60), [])

    def test_resample_single_bar(self):
        bars = _make_bars(1, seed=1, minutes=15)
        result = resample_bars(bars, 60)
        self.assertEqual(len(result), 1)

    def test_resample_15_to_60(self):
        bars = _make_bars(16, minutes=15)
        result = resample_bars(bars, 60)
        self.assertEqual(len(result), 4)

    def test_resample_preserves_time_order(self):
        bars = _make_bars(100, minutes=15)
        result = resample_bars(bars, 60)
        for i in range(1, len(result)):
            self.assertGreater(result[i].time, result[i - 1].time)

    def test_resample_high_is_max(self):
        bars = _make_bars(4, minutes=15)
        result = resample_bars(bars, 60)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].high, max(b.high for b in bars))

    def test_resample_low_is_min(self):
        bars = _make_bars(4, minutes=15)
        result = resample_bars(bars, 60)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].low, min(b.low for b in bars))

    def test_resample_15_to_240(self):
        bars = _make_bars(100, minutes=15)
        h4 = resample_bars(bars, 240)
        self.assertTrue(len(h4) > 0)
        self.assertTrue(len(h4) < len(bars))


class TestMTFRegimeFilter(unittest.TestCase):
    def test_filter_with_insufficient_bars(self):
        config = MTFRegimeConfig()
        filt = MTFRegimeFilter(config)
        bars = _make_bars(5, minutes=15)
        state = MarketState(bars=bars)
        result = filt.evaluate(state, bars, bars, bars)
        self.assertFalse(result)

    def test_filter_with_trending_data(self):
        bars = _make_bars(300, minutes=15, trend="up")
        state = MarketState(bars=bars)
        filt = MTFRegimeFilter(
            MTFRegimeConfig(
                min_confluence=0.3,
                require_h4_alignment=False,
            )
        )
        result = filt.evaluate(state, bars, bars, bars)
        self.assertIsInstance(result, bool)

    def test_get_confidence_range(self):
        bars = _make_bars(300, minutes=15, trend="up")
        state = MarketState(bars=bars)
        filt = MTFRegimeFilter()
        confidence = filt.get_confidence(state, bars, bars, bars)
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)

    def test_get_regime_returns_valid_structure(self):
        bars = _make_bars(300, minutes=15, trend="up")
        filt = MTFRegimeFilter()
        regime = filt.get_regime(bars, bars, bars)
        self.assertIsInstance(regime, MultiTimeframeRegime)
        self.assertIsInstance(regime.h4, TimeframeRegime)
        self.assertIsInstance(regime.h1, TimeframeRegime)
        self.assertIsInstance(regime.m15, TimeframeRegime)
        self.assertIsInstance(regime.aligned_direction, TrendDirection)
        self.assertGreaterEqual(regime.confluence_score, 0.0)
        self.assertLessEqual(regime.confluence_score, 1.0)


class TestComputeConfluence(unittest.TestCase):
    def test_all_bullish(self):
        from quant.mtf_regime import TimeframeRegime as TR
        from quant.mtf_regime import TrendDirection as TD

        regimes = [
            TR(
                VolatilityRegime.NORMAL,
                50.0,
                TD.BULLISH,
                30.0,
                MarketRegime.TRENDING,
                0.001,
            ),
            TR(
                VolatilityRegime.NORMAL,
                50.0,
                TD.BULLISH,
                30.0,
                MarketRegime.TRENDING,
                0.001,
            ),
            TR(
                VolatilityRegime.NORMAL,
                50.0,
                TD.BULLISH,
                30.0,
                MarketRegime.TRENDING,
                0.001,
            ),
        ]
        conf, aligned = compute_confluence(regimes)
        self.assertEqual(conf, 1.0)
        self.assertEqual(aligned, TrendDirection.BULLISH)

    def test_all_bearish(self):
        from quant.mtf_regime import TimeframeRegime as TR
        from quant.mtf_regime import TrendDirection as TD

        regimes = [
            TR(
                VolatilityRegime.NORMAL,
                50.0,
                TD.BEARISH,
                30.0,
                MarketRegime.TRENDING,
                0.001,
            ),
            TR(
                VolatilityRegime.NORMAL,
                50.0,
                TD.BEARISH,
                30.0,
                MarketRegime.TRENDING,
                0.001,
            ),
        ]
        conf, aligned = compute_confluence(regimes)
        self.assertEqual(conf, 1.0)
        self.assertEqual(aligned, TrendDirection.BEARISH)

    def test_mixed(self):
        from quant.mtf_regime import TimeframeRegime as TR
        from quant.mtf_regime import TrendDirection as TD

        regimes = [
            TR(
                VolatilityRegime.NORMAL,
                50.0,
                TD.BULLISH,
                30.0,
                MarketRegime.TRENDING,
                0.001,
            ),
            TR(
                VolatilityRegime.NORMAL,
                50.0,
                TD.BEARISH,
                30.0,
                MarketRegime.TRENDING,
                0.001,
            ),
        ]
        conf, aligned = compute_confluence(regimes)
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

    def test_empty(self):
        conf, aligned = compute_confluence([])
        self.assertEqual(conf, 0.0)
        self.assertEqual(aligned, TrendDirection.NEUTRAL)


class TestVolatilityRegime(unittest.TestCase):
    def test_empty_atr_series(self):
        regime, pct, atr = volatility_regime_atr([])
        self.assertEqual(regime, VolatilityRegime.NORMAL)
        self.assertEqual(pct, 50.0)

    def test_low_volatility(self):
        series = [0.001] * 49 + [0.0005]
        regime, pct, atr = volatility_regime_atr(series)
        self.assertEqual(regime, VolatilityRegime.LOW)

    def test_extreme_volatility(self):
        series = [0.0005] * 49 + [0.002]
        regime, pct, atr = volatility_regime_atr(series)
        self.assertEqual(regime, VolatilityRegime.EXTREME)


class TestDetectRegime(unittest.TestCase):
    def test_insufficient_bars(self):
        bars = _make_bars(5, minutes=15)
        regime = detect_regime(bars)
        self.assertEqual(regime.trend, TrendDirection.NEUTRAL)
        self.assertEqual(regime.regime, MarketRegime.RANGING)
        self.assertEqual(regime.adx, 0.0)

    def test_trending_up(self):
        bars = _make_bars(300, minutes=15, trend="up")
        regime = detect_regime(bars)
        self.assertIsInstance(regime, TimeframeRegime)
        self.assertIn(
            regime.trend,
            [TrendDirection.BULLISH, TrendDirection.BEARISH, TrendDirection.NEUTRAL],
        )


class TestMTFFilteredMomentumStrategy(unittest.TestCase):
    def _make_trending_bars(self, n=500, trend="up"):
        return _make_bars(n, minutes=15, trend=trend)

    def test_name_includes_inner_strategy(self):
        inner = DonchianBreakoutStrategy()
        wrapper = MTFFilteredMomentumStrategy(inner)
        self.assertIn("MTF-Filtered", wrapper.name)
        self.assertIn(inner.name, wrapper.name)

    def test_returns_none_with_insufficient_bars(self):
        inner = DonchianBreakoutStrategy(channel_period=20)
        wrapper = MTFFilteredMomentumStrategy(
            inner,
            regime_config=MTFRegimeConfig(
                min_confluence=0.3,
                require_h4_alignment=False,
            ),
        )
        bars = self._make_trending_bars(10)
        state = MarketState(bars=bars)
        result = wrapper.evaluate(state)
        self.assertIsNone(result)

    def test_filter_rejects_non_aligned_signals(self):
        inner = DonchianBreakoutStrategy(channel_period=20)
        wrapper = MTFFilteredMomentumStrategy(
            inner,
            regime_config=MTFRegimeConfig(
                min_confluence=1.0,
                require_h4_alignment=True,
            ),
            direction_filter=True,
        )
        bars = self._make_trending_bars(500, trend="up")
        state = MarketState(bars=bars)
        result = wrapper.evaluate(state)
        if result is not None:
            self.assertIn("[MTF]", result.rationale)

    def test_direction_filter_disabled(self):
        inner = DonchianBreakoutStrategy(channel_period=20)
        wrapper = MTFFilteredMomentumStrategy(
            inner,
            regime_config=MTFRegimeConfig(
                min_confluence=0.3,
                require_h4_alignment=False,
            ),
            direction_filter=False,
        )
        bars = self._make_trending_bars(500, trend="up")
        state = MarketState(bars=bars)
        result = wrapper.evaluate(state)
        if result is not None:
            self.assertIn("[MTF]", result.rationale)

    def test_confidence_boost_applied(self):
        inner = DonchianBreakoutStrategy(channel_period=20)
        wrapper = MTFFilteredMomentumStrategy(
            inner,
            regime_config=MTFRegimeConfig(
                min_confluence=0.3,
                require_h4_alignment=False,
            ),
            confidence_boost=0.10,
            direction_filter=False,
        )
        bars = self._make_trending_bars(500, trend="up")
        state = MarketState(bars=bars)
        inner_signal = inner.evaluate(state)
        result = wrapper.evaluate(state)
        if inner_signal is not None and result is not None:
            self.assertGreaterEqual(result.confidence, inner_signal.confidence)

    def test_wraps_all_momentum_strategies(self):
        strategies = [
            DonchianBreakoutStrategy(channel_period=20),
            ATRVolatilityBreakoutStrategy(atr_period=14),
            MATrendFollowingStrategy(fast_period=8, slow_period=21),
        ]
        bars = self._make_trending_bars(500, trend="up")
        state = MarketState(bars=bars)
        for strat in strategies:
            wrapper = MTFFilteredMomentumStrategy(
                strat,
                regime_config=MTFRegimeConfig(
                    min_confluence=0.3,
                    require_h4_alignment=False,
                ),
                direction_filter=False,
            )
            result = wrapper.evaluate(state)
            if result is not None:
                self.assertIn("[MTF]", result.rationale)
                self.assertIsInstance(result.confidence, float)

    def test_momentum_breakout_wrapper(self):
        inner = MomentumBreakoutStrategy(
            fast_period=5, slow_period=10, adx_threshold=20.0
        )
        wrapper = MTFFilteredMomentumStrategy(
            inner,
            regime_config=MTFRegimeConfig(
                min_confluence=0.3,
                require_h4_alignment=False,
            ),
            direction_filter=False,
        )
        bars = self._make_trending_bars(500, trend="up")
        state = MarketState(bars=bars)
        result = wrapper.evaluate(state)
        if result is not None:
            self.assertIn("[MTF]", result.rationale)


class TestMTFRegimeConfig(unittest.TestCase):
    def test_defaults(self):
        config = MTFRegimeConfig()
        self.assertEqual(config.min_confluence, 0.6)
        self.assertTrue(config.require_h4_alignment)
        self.assertIn(MarketRegime.TRENDING, config.allowed_regimes)
        self.assertIn(MarketRegime.RANGING, config.allowed_regimes)
        self.assertNotIn(MarketRegime.VOLATILE, config.allowed_regimes)

    def test_custom_config(self):
        config = MTFRegimeConfig(
            min_confluence=0.4,
            require_h4_alignment=False,
        )
        self.assertEqual(config.min_confluence, 0.4)
        self.assertFalse(config.require_h4_alignment)

    def test_frozen(self):
        config = MTFRegimeConfig()
        with self.assertRaises(AttributeError):
            config.min_confluence = 0.99


if __name__ == "__main__":
    unittest.main()
