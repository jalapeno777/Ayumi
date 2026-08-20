import unittest

from quant.regime import (
    CombinedRegime,
    RegimeWeights,
    SessionName,
    SessionRegimeResult,
    TrendDirection,
    TrendRegimeResult,
    VolatilityRegime,
    VolatilityRegimeResult,
    VolatilityThresholds,
    combined_regime,
    session_regime,
    trend_regime,
    volatility_regime,
)


class TestVolatilityRegime(unittest.TestCase):
    def test_low_volatility(self):
        atr = [0.001] * 50 + [0.0005]
        result = volatility_regime(atr, lookback=50)
        self.assertEqual(result.regime, VolatilityRegime.LOW)
        self.assertLess(result.percentile, 25.0)
        self.assertAlmostEqual(result.atr_value, 0.0005)

    def test_normal_volatility(self):
        atr = list(range(50, 100))
        atr.append(75)
        result = volatility_regime(atr, lookback=50)
        self.assertEqual(result.regime, VolatilityRegime.NORMAL)

    def test_high_volatility(self):
        atr = list(range(40, 90))
        atr.append(84)
        result = volatility_regime(atr, lookback=50)
        self.assertEqual(result.regime, VolatilityRegime.HIGH)
        self.assertGreaterEqual(result.percentile, 75.0)
        self.assertLess(result.percentile, 90.0)

    def test_extreme_volatility(self):
        atr = [0.001] * 49 + [0.01]
        result = volatility_regime(atr, lookback=50)
        self.assertEqual(result.regime, VolatilityRegime.EXTREME)
        self.assertGreaterEqual(result.percentile, 90.0)

    def test_custom_lookback(self):
        atr = [0.001] * 20 + [0.005]
        result = volatility_regime(atr, lookback=20)
        self.assertEqual(result.regime, VolatilityRegime.EXTREME)

    def test_empty_series(self):
        result = volatility_regime([])
        self.assertEqual(result.regime, VolatilityRegime.NORMAL)
        self.assertEqual(result.percentile, 50.0)
        self.assertEqual(result.atr_value, 0.0)

    def test_single_value(self):
        result = volatility_regime([0.001])
        self.assertEqual(result.regime, VolatilityRegime.LOW)
        self.assertAlmostEqual(result.percentile, 0.0)

    def test_returns_current_atr(self):
        atr = [0.001, 0.002, 0.003]
        result = volatility_regime(atr)
        self.assertAlmostEqual(result.atr_value, 0.003)

    def test_custom_thresholds(self):
        atr = list(range(40, 90))
        atr.append(84)
        thresholds = VolatilityThresholds(low=10.0, normal=50.0, high=80.0)
        result = volatility_regime(atr, lookback=50, thresholds=thresholds)
        self.assertEqual(result.regime, VolatilityRegime.EXTREME)

    def test_custom_thresholds_all_normal(self):
        atr = list(range(50, 100))
        atr.append(75)
        thresholds = VolatilityThresholds(low=5.0, normal=99.0, high=99.5)
        result = volatility_regime(atr, lookback=50, thresholds=thresholds)
        self.assertEqual(result.regime, VolatilityRegime.NORMAL)

    def test_all_identical_values(self):
        atr = [0.001] * 50
        result = volatility_regime(atr)
        self.assertAlmostEqual(result.percentile, 50.0)

    def test_negative_atr_values(self):
        atr = [-0.003] * 49 + [-0.001]
        result = volatility_regime(atr)
        self.assertEqual(result.regime, VolatilityRegime.EXTREME)
        self.assertAlmostEqual(result.atr_value, -0.001)


class TestTrendRegime(unittest.TestCase):
    def _make_trending_data(self, periods: int = 30) -> tuple[list[float], list[float], list[float]]:
        close = [1.0 + i * 0.001 for i in range(periods)]
        high = [c + 0.001 for c in close]
        low = [c - 0.001 for c in close]
        return high, low, close

    def _make_ranging_data(self, periods: int = 30) -> tuple[list[float], list[float], list[float]]:
        close = [1.0 + 0.0001 * (i % 4) for i in range(periods)]
        high = [c + 0.0002 for c in close]
        low = [c - 0.0002 for c in close]
        return high, low, close

    def test_insufficient_data_returns_neutral(self):
        result = trend_regime([1.0], [0.99], [1.0], adx_period=14)
        self.assertEqual(result.direction, TrendDirection.NEUTRAL)
        self.assertEqual(result.adx_value, 0.0)

    def test_trending_detection(self):
        high, low, close = self._make_trending_data(50)
        result = trend_regime(high, low, close, adx_period=14)
        self.assertEqual(result.direction, TrendDirection.TRENDING)
        self.assertGreater(result.adx_value, 25.0)
        self.assertGreater(result.ma_slope, 0.0)

    def test_ranging_detection(self):
        high, low, close = self._make_ranging_data(50)
        result = trend_regime(high, low, close, adx_period=14)
        self.assertEqual(result.direction, TrendDirection.RANGING)
        self.assertLess(result.adx_value, 20.0)

    def test_ma_slope_negative_for_downtrend(self):
        close = [2.0 - i * 0.001 for i in range(50)]
        high = [c + 0.001 for c in close]
        low = [c - 0.001 for c in close]
        result = trend_regime(high, low, close, adx_period=14)
        self.assertLess(result.ma_slope, 0.0)

    def test_custom_adx_period(self):
        high, low, close = self._make_trending_data(30)
        result = trend_regime(high, low, close, adx_period=10)
        self.assertIsInstance(result.adx_value, float)

    def test_result_is_dataclass(self):
        high, low, close = self._make_trending_data(30)
        result = trend_regime(high, low, close)
        self.assertIsInstance(result, TrendRegimeResult)
        self.assertTrue(hasattr(result, "adx_value"))
        self.assertTrue(hasattr(result, "direction"))
        self.assertTrue(hasattr(result, "ma_slope"))

    def test_flat_close_ma_slope_zero(self):
        close = [1.0] * 50
        high = [1.001] * 50
        low = [0.999] * 50
        result = trend_regime(high, low, close, adx_period=14)
        self.assertAlmostEqual(result.ma_slope, 0.0)

    def test_empty_inputs(self):
        result = trend_regime([], [], [], adx_period=14)
        self.assertEqual(result.direction, TrendDirection.NEUTRAL)
        self.assertEqual(result.adx_value, 0.0)


class TestSessionRegime(unittest.TestCase):
    def test_asia_session(self):
        result = session_regime(3, 0)
        self.assertEqual(result.session, SessionName.ASIA)
        self.assertAlmostEqual(result.vol_multiplier, 0.7)

    def test_london_session(self):
        result = session_regime(9, 1)
        self.assertEqual(result.session, SessionName.LONDON)
        self.assertAlmostEqual(result.vol_multiplier, 1.0)

    def test_new_york_session(self):
        result = session_regime(14, 2)
        self.assertEqual(result.session, SessionName.NEW_YORK)
        self.assertAlmostEqual(result.vol_multiplier, 1.1)

    def test_close_session(self):
        result = session_regime(20, 3)
        self.assertEqual(result.session, SessionName.CLOSE)
        self.assertAlmostEqual(result.vol_multiplier, 0.5)

    def test_weekend_reduces_volatility(self):
        result = session_regime(9, 5)
        self.assertEqual(result.session, SessionName.LONDON)
        self.assertAlmostEqual(result.vol_multiplier, 0.5)

    def test_saturday_asia(self):
        result = session_regime(3, 6)
        self.assertEqual(result.session, SessionName.ASIA)
        self.assertAlmostEqual(result.vol_multiplier, 0.35)

    def test_hour_24_wraps(self):
        result = session_regime(24, 0)
        self.assertEqual(result.session, SessionName.CLOSE)

    def test_session_boundaries(self):
        self.assertEqual(session_regime(0, 0).session, SessionName.ASIA)
        self.assertEqual(session_regime(6, 0).session, SessionName.ASIA)
        self.assertEqual(session_regime(7, 0).session, SessionName.LONDON)
        self.assertEqual(session_regime(11, 0).session, SessionName.LONDON)
        self.assertEqual(session_regime(12, 0).session, SessionName.NEW_YORK)
        self.assertEqual(session_regime(16, 0).session, SessionName.NEW_YORK)
        self.assertEqual(session_regime(17, 0).session, SessionName.CLOSE)
        self.assertEqual(session_regime(23, 0).session, SessionName.CLOSE)

    def test_negative_hour(self):
        result = session_regime(-1, 0)
        self.assertEqual(result.session, SessionName.CLOSE)


class TestCombinedRegime(unittest.TestCase):
    def _make_normal_vol(self) -> VolatilityRegimeResult:
        return VolatilityRegimeResult(
            regime=VolatilityRegime.NORMAL,
            percentile=50.0,
            atr_value=0.001,
        )

    def _make_trending(self) -> TrendRegimeResult:
        return TrendRegimeResult(
            adx_value=30.0,
            direction=TrendDirection.TRENDING,
            ma_slope=0.001,
        )

    def _make_london_session(self) -> SessionRegimeResult:
        return SessionRegimeResult(
            session=SessionName.LONDON,
            vol_multiplier=1.0,
        )

    def test_returns_combined_regime(self):
        vol = self._make_normal_vol()
        trend = self._make_trending()
        session = self._make_london_session()
        result = combined_regime(vol, trend, session)
        self.assertIsInstance(result, CombinedRegime)
        self.assertEqual(result.volatility, vol)
        self.assertEqual(result.trend, trend)
        self.assertEqual(result.session, session)

    def test_confidence_high_for_favorable(self):
        vol = self._make_normal_vol()
        trend = self._make_trending()
        session = self._make_london_session()
        result = combined_regime(vol, trend, session)
        self.assertGreater(result.confidence, 0.7)

    def test_confidence_low_for_extreme(self):
        vol = VolatilityRegimeResult(
            regime=VolatilityRegime.EXTREME,
            percentile=95.0,
            atr_value=0.01,
        )
        trend = TrendRegimeResult(
            adx_value=15.0,
            direction=TrendDirection.RANGING,
            ma_slope=0.0,
        )
        session = SessionRegimeResult(
            session=SessionName.CLOSE,
            vol_multiplier=0.5,
        )
        result = combined_regime(vol, trend, session)
        self.assertLess(result.confidence, 0.5)

    def test_confidence_between_zero_and_one(self):
        result = combined_regime(
            self._make_normal_vol(),
            self._make_trending(),
            self._make_london_session(),
        )
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_confidence_weights(self):
        vol = VolatilityRegimeResult(VolatilityRegime.NORMAL, 50.0, 0.001)
        trend = TrendRegimeResult(0.0, TrendDirection.RANGING, 0.0)
        session = SessionRegimeResult(SessionName.ASIA, 0.7)

        result = combined_regime(vol, trend, session)
        expected = 0.4 * 1.0 + 0.4 * 0.5 + 0.2 * (0.7 / 1.5)
        self.assertAlmostEqual(result.confidence, expected, places=4)

    def test_custom_weights(self):
        vol = self._make_normal_vol()
        trend = self._make_trending()
        session = self._make_london_session()
        weights = RegimeWeights(volatility=1.0, trend=0.0, session=0.0)
        result = combined_regime(vol, trend, session, weights=weights)
        self.assertAlmostEqual(result.confidence, 1.0)

    def test_custom_weights_session_only(self):
        vol = self._make_normal_vol()
        trend = self._make_trending()
        session = SessionRegimeResult(SessionName.CLOSE, vol_multiplier=0.5)
        weights = RegimeWeights(volatility=0.0, trend=0.0, session=1.0)
        result = combined_regime(vol, trend, session, weights=weights)
        expected = 0.5 / 1.5
        self.assertAlmostEqual(result.confidence, expected, places=4)

    def test_frozen_dataclasses(self):
        vol = self._make_normal_vol()
        with self.assertRaises(AttributeError):
            vol.regime = VolatilityRegime.HIGH


if __name__ == "__main__":
    unittest.main()
