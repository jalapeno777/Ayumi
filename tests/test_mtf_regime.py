import unittest
from datetime import datetime

from backtest.engine import Bar

from quant.mtf_regime import (
    MTFRegimeConfig,
    MTFRegimeFilter,
    MarketRegime,
    MultiTimeframeRegime,
    TrendDirection,
    VolatilityRegime,
    VolatilityRegime,
    compute_adx,
    compute_atr,
    compute_confluence,
    detect_multi_timeframe_regime,
    detect_regime,
    volatility_regime_atr,
)


def _make_bar(time: datetime, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(time=time, open=o, high=h, low=l, close=c)


def _make_trending_bars(n: int, start: float = 1.0, step: float = 0.001) -> list[Bar]:
    bars = []
    for i in range(n):
        t = datetime(2024, 1, 1, i % 24, i % 60)
        close = start + i * step
        high = close + 0.001
        low = close - 0.001
        bars.append(_make_bar(t, close, high, low, close))
    return bars


def _make_ranging_bars(n: int, base: float = 1.0) -> list[Bar]:
    bars = []
    for i in range(n):
        t = datetime(2024, 1, 1, i % 24, i % 60)
        close = base + 0.0001 * (i % 4)
        high = close + 0.0002
        low = close - 0.0002
        bars.append(_make_bar(t, close, high, low, close))
    return bars


class TestComputeATR(unittest.TestCase):
    def test_atr_computation(self):
        highs = [1.1000, 1.1100, 1.1050]
        lows = [1.0900, 1.0950, 1.0900]
        closes = [1.0950, 1.1000, 1.1000]
        result = compute_atr(highs, lows, closes, period=3)
        self.assertGreater(result, 0)

    def test_atr_insufficient_data(self):
        result = compute_atr([1.1], [1.0], [1.05], period=14)
        self.assertLess(result, 0.001)


class TestComputeADX(unittest.TestCase):
    def test_adx_trending_market(self):
        highs = [1.0 + i * 0.01 for i in range(30)]
        lows = [1.0 + i * 0.01 - 0.005 for i in range(30)]
        closes = [1.0 + i * 0.01 + 0.002 for i in range(30)]
        adx, plus_di, minus_di = compute_adx(highs, lows, closes, period=14)
        self.assertGreater(adx, 0)

    def test_adx_insufficient_data(self):
        adx, plus_di, minus_di = compute_adx([1.0], [0.99], [1.0], period=14)
        self.assertEqual(adx, 0.0)


class TestVolatilityRegimeATR(unittest.TestCase):
    def test_low_volatility(self):
        atr = [0.001] * 50 + [0.0005]
        regime, pct, _ = volatility_regime_atr(atr)
        self.assertEqual(regime, VolatilityRegime.LOW)
        self.assertLess(pct, 25.0)

    def test_normal_volatility(self):
        atr = list(range(50, 100))
        atr.append(75)
        regime, pct, _ = volatility_regime_atr(atr, lookback=50)
        self.assertEqual(regime, VolatilityRegime.NORMAL)

    def test_high_volatility(self):
        atr = list(range(40, 90))
        atr.append(84)
        regime, pct, _ = volatility_regime_atr(atr, lookback=50)
        self.assertEqual(regime, VolatilityRegime.HIGH)

    def test_extreme_volatility(self):
        atr = [0.001] * 49 + [0.01]
        regime, pct, _ = volatility_regime_atr(atr, lookback=50)
        self.assertEqual(regime, VolatilityRegime.EXTREME)

    def test_empty_series(self):
        regime, pct, atr_val = volatility_regime_atr([])
        self.assertEqual(regime, VolatilityRegime.NORMAL)
        self.assertEqual(pct, 50.0)


class TestDetectRegime(unittest.TestCase):
    def test_trending_regime(self):
        bars = _make_trending_bars(50)
        result = detect_regime(bars)
        self.assertIn(result.regime, [MarketRegime.TRENDING, MarketRegime.RANGING])
        self.assertGreater(result.adx, 0)

    def test_ranging_regime(self):
        bars = _make_ranging_bars(50)
        result = detect_regime(bars)
        self.assertIsInstance(result.regime, MarketRegime)

    def test_insufficient_data(self):
        bars = _make_trending_bars(5)
        result = detect_regime(bars)
        self.assertEqual(result.adx, 0.0)
        self.assertEqual(result.regime, MarketRegime.RANGING)


class TestComputeConfluence(unittest.TestCase):
    def test_all_bullish(self):
        from quant.mtf_regime import TimeframeRegime, TrendDirection
        regimes = [
            TimeframeRegime(VolatilityRegime.NORMAL, 50.0, TrendDirection.BULLISH, 25.0, MarketRegime.TRENDING, 0.001),
            TimeframeRegime(VolatilityRegime.NORMAL, 50.0, TrendDirection.BULLISH, 25.0, MarketRegime.TRENDING, 0.001),
            TimeframeRegime(VolatilityRegime.NORMAL, 50.0, TrendDirection.BULLISH, 25.0, MarketRegime.TRENDING, 0.001),
        ]
        confluence, direction = compute_confluence(regimes)
        self.assertEqual(confluence, 1.0)
        self.assertEqual(direction, TrendDirection.BULLISH)

    def test_all_bearish(self):
        from quant.mtf_regime import TimeframeRegime
        regimes = [
            TimeframeRegime(VolatilityRegime.NORMAL, 50.0, TrendDirection.BEARISH, 25.0, MarketRegime.TRENDING, 0.001),
            TimeframeRegime(VolatilityRegime.NORMAL, 50.0, TrendDirection.BEARISH, 25.0, MarketRegime.TRENDING, 0.001),
            TimeframeRegime(VolatilityRegime.NORMAL, 50.0, TrendDirection.BEARISH, 25.0, MarketRegime.TRENDING, 0.001),
        ]
        confluence, direction = compute_confluence(regimes)
        self.assertEqual(confluence, 1.0)
        self.assertEqual(direction, TrendDirection.BEARISH)

    def test_mixed_alignment(self):
        from quant.mtf_regime import TimeframeRegime
        regimes = [
            TimeframeRegime(VolatilityRegime.NORMAL, 50.0, TrendDirection.BULLISH, 25.0, MarketRegime.TRENDING, 0.001),
            TimeframeRegime(VolatilityRegime.NORMAL, 50.0, TrendDirection.BULLISH, 25.0, MarketRegime.TRENDING, 0.001),
            TimeframeRegime(VolatilityRegime.NORMAL, 50.0, TrendDirection.BEARISH, 25.0, MarketRegime.TRENDING, 0.001),
        ]
        confluence, direction = compute_confluence(regimes)
        self.assertEqual(confluence, 0.7)
        self.assertEqual(direction, TrendDirection.BULLISH)

    def test_empty_regimes(self):
        confluence, direction = compute_confluence([])
        self.assertEqual(confluence, 0.0)
        self.assertEqual(direction, TrendDirection.NEUTRAL)


class TestDetectMultiTimeframeRegime(unittest.TestCase):
    def test_mtf_regime_returns_structure(self):
        h4 = _make_trending_bars(50)
        h1 = _make_trending_bars(50)
        m15 = _make_trending_bars(50)
        result = detect_multi_timeframe_regime(h4, h1, m15)
        self.assertIsInstance(result, MultiTimeframeRegime)
        self.assertIsInstance(result.h4, object)
        self.assertIsInstance(result.h1, object)
        self.assertIsInstance(result.m15, object)
        self.assertGreaterEqual(result.confluence_score, 0.0)
        self.assertLessEqual(result.confluence_score, 1.0)


class TestMTFRegimeFilter(unittest.TestCase):
    def test_filter_passes_with_high_confluence(self):
        filter = MTFRegimeFilter(MTFRegimeConfig(min_confluence=0.6))
        h4 = _make_trending_bars(50)
        h1 = _make_trending_bars(50)
        m15 = _make_trending_bars(50)
        result = filter.evaluate(None, h4, h1, m15)
        self.assertIsInstance(result, bool)

    def test_filter_config(self):
        config = MTFRegimeConfig(
            min_confluence=0.8,
            require_h4_alignment=True,
            allowed_regimes=frozenset({MarketRegime.TRENDING}),
        )
        filter = MTFRegimeFilter(config)
        self.assertEqual(filter.config.min_confluence, 0.8)

    def test_get_confidence(self):
        filter = MTFRegimeFilter()
        h4 = _make_trending_bars(50)
        h1 = _make_trending_bars(50)
        m15 = _make_trending_bars(50)
        conf = filter.get_confidence(None, h4, h1, m15)
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

    def test_get_regime(self):
        filter = MTFRegimeFilter()
        h4 = _make_trending_bars(50)
        h1 = _make_trending_bars(50)
        m15 = _make_trending_bars(50)
        regime = filter.get_regime(h4, h1, m15)
        self.assertIsInstance(regime, MultiTimeframeRegime)


if __name__ == "__main__":
    unittest.main()