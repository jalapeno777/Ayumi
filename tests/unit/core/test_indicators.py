import math  # noqa: I001
import unittest

import numpy as np
import pandas as pd

from indicators import (
    atr,
    atr_percentile,
    bollinger_bands,
    ema,
    macd,
    roc,
    rsi,
    sma,
    std,
    stochastic,
    adx,
)

CLOSES_20 = [
    44.0,
    44.34,
    44.09,
    43.61,
    44.33,
    44.83,
    45.10,
    45.42,
    45.84,
    46.08,
    45.89,
    46.03,
    45.61,
    46.28,
    46.28,
    46.00,
    46.03,
    46.41,
    46.22,
    46.56,
]

HIGHS_20 = [
    44.34,
    44.52,
    44.40,
    44.33,
    44.58,
    45.10,
    45.35,
    45.65,
    46.05,
    46.42,
    46.10,
    46.28,
    46.03,
    46.61,
    46.60,
    46.18,
    46.12,
    46.67,
    46.42,
    46.82,
]

LOWS_20 = [
    43.87,
    44.03,
    43.78,
    43.47,
    43.87,
    44.63,
    44.90,
    45.10,
    45.50,
    45.78,
    45.48,
    45.50,
    45.25,
    45.78,
    45.86,
    45.70,
    45.62,
    45.96,
    45.85,
    46.06,
]


class TestSMA(unittest.TestCase):
    def test_basic(self):
        result = sma([1, 2, 3, 4, 5], 3)
        self.assertTrue(math.isnan(result.iloc[0]))
        self.assertTrue(math.isnan(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 2.0)
        self.assertAlmostEqual(result.iloc[3], 3.0)
        self.assertAlmostEqual(result.iloc[4], 4.0)

    def test_known_value(self):
        result = sma(CLOSES_20, 14)
        expected = sum(CLOSES_20[6:20]) / 14
        self.assertAlmostEqual(result.iloc[19], expected, places=4)

    def test_returns_series(self):
        result = sma([1, 2, 3], 2)
        self.assertIsInstance(result, pd.Series)

    def test_accepts_series_input(self):
        s = pd.Series([1.0, 2.0, 3.0])
        result = sma(s, 2)
        self.assertAlmostEqual(result.iloc[1], 1.5)


class TestEMA(unittest.TestCase):
    def test_basic(self):
        result = ema([1, 2, 3, 4, 5], 3)
        alpha = 2 / (3 + 1)
        expected = 1.0
        for v in [2, 3, 4, 5]:
            expected = alpha * v + (1 - alpha) * expected
        self.assertAlmostEqual(result.iloc[0], 1.0, places=4)
        self.assertAlmostEqual(result.iloc[4], expected, places=4)

    def test_known_value(self):
        result = ema(CLOSES_20, 5)
        alpha = 2 / (5 + 1)
        expected = CLOSES_20[0]
        for val in CLOSES_20[1:]:
            expected = alpha * val + (1 - alpha) * expected
        self.assertAlmostEqual(result.iloc[19], expected, places=3)


class TestStd(unittest.TestCase):
    def test_population_std(self):
        result = std([2, 4, 4, 4, 5, 5, 7, 9], 8)
        self.assertAlmostEqual(result.iloc[7], 2.0, places=4)

    def test_short_input_nan(self):
        result = std([1, 2], 5)
        self.assertTrue(math.isnan(result.iloc[1]))


class TestRSI(unittest.TestCase):
    def test_mostly_gains_high_rsi(self):
        closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 22, 24]
        result = rsi(closes, 14)
        self.assertGreater(result.iloc[15], 80.0)

    def test_all_losses(self):
        closes = [25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10]
        result = rsi(closes, 14)
        self.assertAlmostEqual(result.iloc[15], 0.0, places=1)

    def test_wilder_rsi_known_value(self):
        closes = list(range(40, 60)) + list(range(60, 40, -1)) + list(range(40, 50))
        result = rsi(closes, 14)
        self.assertTrue(0 <= result.iloc[-1] <= 100)

    def test_flat_prices(self):
        closes = [100.0] * 20
        result = rsi(closes, 14)
        self.assertTrue(math.isnan(result.iloc[-1]))

    def test_returns_nan_before_period(self):
        result = rsi([1, 2, 3], 14)
        self.assertTrue(result.isna().all())


class TestATR(unittest.TestCase):
    def test_wilder_smoothing(self):
        result = atr(HIGHS_20, LOWS_20, CLOSES_20, 14)
        self.assertTrue(math.isnan(result.iloc[0]))
        self.assertFalse(math.isnan(result.iloc[19]))

    def test_first_valid_at_period(self):
        result = atr(HIGHS_20, LOWS_20, CLOSES_20, 14)
        self.assertTrue(math.isnan(result.iloc[12]))
        self.assertFalse(math.isnan(result.iloc[13]))

    def test_atr_positive(self):
        result = atr(HIGHS_20, LOWS_20, CLOSES_20, 14)
        valid = result.dropna()
        self.assertTrue((valid > 0).all())


class TestADX(unittest.TestCase):
    def test_short_input_returns_nan(self):
        result = adx(HIGHS_20[:10], LOWS_20[:10], CLOSES_20[:10], 14)
        self.assertTrue(result.isna().all())

    def test_returns_valid_for_sufficient_data(self):
        highs = [float(50 + i % 5) for i in range(50)]
        lows = [float(45 + i % 5) for i in range(50)]
        closes = [float(47 + i % 4) for i in range(50)]
        result = adx(highs, lows, closes, 14)
        self.assertFalse(math.isnan(result.iloc[49]))

    def test_adx_range(self):
        highs = [float(50 + i % 5) for i in range(50)]
        lows = [float(45 + i % 5) for i in range(50)]
        closes = [float(47 + i % 4) for i in range(50)]
        result = adx(highs, lows, closes, 14)
        valid = result.dropna()
        self.assertTrue((valid >= 0).all() & (valid <= 100).all())

    def test_strong_trend_higher_adx(self):
        uptrend_highs = [float(100 + i) for i in range(50)]
        uptrend_lows = [float(98 + i) for i in range(50)]
        uptrend_closes = [float(99 + i) for i in range(50)]
        result = adx(uptrend_highs, uptrend_lows, uptrend_closes, 14)
        self.assertGreater(result.iloc[49], 50.0)

    def test_matches_volatility_squeeze_reference(self):
        result = adx(HIGHS_20, LOWS_20, CLOSES_20, 14)
        n = len(CLOSES_20)
        tr_list = []
        plus_dm_list = []
        minus_dm_list = []
        for i in range(1, n):
            tr_val = max(
                HIGHS_20[i] - LOWS_20[i],
                abs(HIGHS_20[i] - HIGHS_20[i - 1]),
                abs(LOWS_20[i] - LOWS_20[i - 1]),
            )
            up = HIGHS_20[i] - HIGHS_20[i - 1]
            down = LOWS_20[i - 1] - LOWS_20[i]
            plus_dm = up if up > down and up > 0 else 0.0
            minus_dm = down if down > up and down > 0 else 0.0
            tr_list.append(tr_val)
            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        smoothed_tr = sum(tr_list[:14])
        smoothed_plus_dm = sum(plus_dm_list[:14])
        smoothed_minus_dm = sum(minus_dm_list[:14])
        dx_values = []
        for i in range(14, len(tr_list)):
            smoothed_tr = smoothed_tr - smoothed_tr / 14 + tr_list[i]
            smoothed_plus_dm = smoothed_plus_dm - smoothed_plus_dm / 14 + plus_dm_list[i]
            smoothed_minus_dm = smoothed_minus_dm - smoothed_minus_dm / 14 + minus_dm_list[i]
            if smoothed_tr == 0:
                dx_values.append(0.0)
                continue
            plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
            minus_di = 100.0 * smoothed_minus_dm / smoothed_tr
            di_sum = plus_di + minus_di
            dx = 100.0 * abs(plus_di - minus_di) / di_sum if di_sum != 0 else 0.0
            dx_values.append(dx)

        if len(dx_values) >= 14:
            adx_val = sum(dx_values[:14]) / 14
            for i in range(14, len(dx_values)):
                adx_val = (adx_val * 13 + dx_values[i]) / 14
            self.assertAlmostEqual(result.iloc[19], adx_val, places=4)


class TestBollingerBands(unittest.TestCase):
    def test_basic_structure(self):
        upper, mid, lower = bollinger_bands(CLOSES_20, 5, 2.0)
        self.assertEqual(len(upper), 20)
        self.assertEqual(len(mid), 20)
        self.assertEqual(len(lower), 20)

    def test_upper_greater_than_lower(self):
        upper, mid, lower = bollinger_bands(CLOSES_20, 5, 2.0)
        valid = ~upper.isna()
        self.assertTrue((upper[valid] >= mid[valid]).all())
        self.assertTrue((mid[valid] >= lower[valid]).all())

    def test_mid_equals_sma(self):
        _, mid, _ = bollinger_bands(CLOSES_20, 5, 2.0)
        expected = sma(CLOSES_20, 5)
        pd.testing.assert_series_equal(mid, expected)

    def test_band_width(self):
        upper, mid, lower = bollinger_bands(CLOSES_20, 5, 2.0)
        valid = ~upper.isna()
        std_series = std(CLOSES_20, 5)
        self.assertTrue(
            np.allclose(
                (upper[valid] - lower[valid]).values,
                (2 * 2.0 * std_series[valid]).values,
            )
        )


class TestMACD(unittest.TestCase):
    def test_structure(self):
        macd_line, signal_line, histogram = macd(CLOSES_20)
        self.assertEqual(len(macd_line), 20)
        self.assertEqual(len(signal_line), 20)
        self.assertEqual(len(histogram), 20)

    def test_histogram_equals_difference(self):
        macd_line, signal_line, histogram = macd(CLOSES_20)
        pd.testing.assert_series_equal(histogram, macd_line - signal_line)

    def test_uptrend_positive_macd(self):
        closes = [float(i) for i in range(1, 51)]
        macd_line, _, _ = macd(closes)
        self.assertGreater(macd_line.iloc[-1], 0)


class TestStochastic(unittest.TestCase):
    def test_structure(self):
        k, d = stochastic(HIGHS_20, LOWS_20, CLOSES_20)
        self.assertEqual(len(k), 20)
        self.assertEqual(len(d), 20)

    def test_k_range(self):
        k, _ = stochastic(HIGHS_20, LOWS_20, CLOSES_20)
        valid = k.dropna()
        self.assertTrue((valid >= 0).all() & (valid <= 100).all())

    def test_d_is_sma_of_k(self):
        k, d = stochastic(HIGHS_20, LOWS_20, CLOSES_20, 14, 3)
        expected_d = k.rolling(window=3, min_periods=3).mean()
        pd.testing.assert_series_equal(d, expected_d)

    def test_at_high(self):
        k, _ = stochastic([10, 10, 10], [5, 5, 5], [10, 10, 10], 3, 3)
        self.assertAlmostEqual(k.iloc[2], 100.0)

    def test_at_low(self):
        k, _ = stochastic([10, 10, 10], [5, 5, 5], [5, 5, 5], 3, 3)
        self.assertAlmostEqual(k.iloc[2], 0.0)


class TestROC(unittest.TestCase):
    def test_known_value(self):
        result = roc([100, 110], 1)
        self.assertTrue(math.isnan(result.iloc[0]))
        self.assertAlmostEqual(result.iloc[1], 10.0)

    def test_negative_roc(self):
        result = roc([100, 90], 1)
        self.assertAlmostEqual(result.iloc[1], -10.0)

    def test_longer_period(self):
        result = roc([100, 105, 110, 120], 2)
        self.assertTrue(math.isnan(result.iloc[0]))
        self.assertTrue(math.isnan(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 10.0)
        self.assertAlmostEqual(result.iloc[3], (120 - 105) / 105 * 100)


class TestATRPercentile(unittest.TestCase):
    def test_returns_series(self):
        result = atr_percentile(HIGHS_20, LOWS_20, CLOSES_20, 5, 10)
        self.assertIsInstance(result, pd.Series)

    def test_range(self):
        highs = [float(50 + i % 5) for i in range(100)]
        lows = [float(45 + i % 5) for i in range(100)]
        closes = [float(47 + i % 4) for i in range(100)]
        result = atr_percentile(highs, lows, closes, 14, 50)
        valid = result.dropna()
        self.assertTrue((valid >= 0).all() & (valid <= 1).all())


class TestAcceptsSeriesInput(unittest.TestCase):
    def test_sma_series(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = sma(s, 3)
        self.assertAlmostEqual(result.iloc[2], 2.0)

    def test_rsi_series(self):
        s = pd.Series(CLOSES_20)
        result = rsi(s, 14)
        self.assertIsInstance(result, pd.Series)

    def test_atr_series(self):
        h = pd.Series(HIGHS_20)
        l = pd.Series(LOWS_20)  # noqa: E741
        c = pd.Series(CLOSES_20)
        result = atr(h, l, c, 14)
        self.assertIsInstance(result, pd.Series)

    def test_adx_series(self):
        h = pd.Series(HIGHS_20)
        l = pd.Series(LOWS_20)  # noqa: E741
        c = pd.Series(CLOSES_20)
        result = adx(h, l, c, 14)
        self.assertIsInstance(result, pd.Series)


if __name__ == "__main__":
    unittest.main()
