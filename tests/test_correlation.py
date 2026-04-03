import unittest

import numpy as np
import pandas as pd

from quant.correlation import (
    CorrelationTracker,
    Position,
    check_correlated_exposure,
    correlation_matrix,
    portfolio_exposure,
    rolling_correlation,
)


def _price_series(values: list[float], start: float = 1.0) -> pd.Series:
    prices = start * np.cumprod(np.array([1.0] + values))
    return pd.Series(prices, index=pd.date_range("2024-01-01", periods=len(prices), freq="D"))


class TestRollingCorrelation(unittest.TestCase):
    def test_identical_series_correlation_one(self):
        np.random.seed(42)
        noise = 1 + np.random.randn(60) * 0.001
        s = _price_series(list(noise))
        result = rolling_correlation(s, s, window=20)
        self.assertAlmostEqual(result.iloc[-1], 1.0, places=2)

    def test_opposite_series_correlation_negative_one(self):
        np.random.seed(42)
        noise_a = 1 + np.random.randn(60) * 0.001
        noise_b = 1 - noise_a + 1  # inverse returns
        up = _price_series(list(noise_a))
        down = _price_series(list(noise_b))
        result = rolling_correlation(up, down, window=20)
        self.assertLess(result.iloc[-1], -0.5)

    def test_unrelated_series_low_correlation(self):
        np.random.seed(42)
        rand_a = _price_series(list(1 + np.random.randn(60) * 0.01))
        rand_b = _price_series(list(1 + np.random.randn(60) * 0.01))
        result = rolling_correlation(rand_a, rand_b, window=20)
        self.assertFalse(pd.isna(result.iloc[-1]))


class TestCorrelationMatrix(unittest.TestCase):
    def test_diagonal_ones(self):
        np.random.seed(42)
        prices = {
            "EURUSD": _price_series(list(1 + np.random.randn(60) * 0.001)),
            "GBPUSD": _price_series(list(1 + np.random.randn(60) * 0.001)),
        }
        mat = correlation_matrix(prices, window=20)
        self.assertAlmostEqual(mat.loc["EURUSD", "EURUSD"], 1.0, places=5)
        self.assertAlmostEqual(mat.loc["GBPUSD", "GBPUSD"], 1.0, places=5)

    def test_symmetric_matrix(self):
        np.random.seed(42)
        prices = {
            "EURUSD": _price_series(list(1 + np.random.randn(60) * 0.001)),
            "GBPUSD": _price_series(list(1 + np.random.randn(60) * 0.001)),
        }
        mat = correlation_matrix(prices, window=20)
        self.assertAlmostEqual(mat.loc["EURUSD", "GBPUSD"], mat.loc["GBPUSD", "EURUSD"], places=5)


class TestCheckCorrelatedExposure(unittest.TestCase):
    def test_no_warning_below_threshold(self):
        np.random.seed(42)
        prices = {
            "EURUSD": _price_series(list(1 + np.random.randn(60) * 0.001)),
            "GBPUSD": _price_series(list(1 - np.random.randn(60) * 0.001)),
        }
        corr = correlation_matrix(prices, window=20)
        positions: list[Position] = [
            {"symbol": "EURUSD", "exposure": 0.5},
            {"symbol": "GBPUSD", "exposure": 0.5},
        ]
        warnings = check_correlated_exposure(positions, corr, threshold=0.9)
        self.assertEqual(len(warnings), 0)

    def test_warning_above_threshold(self):
        np.random.seed(42)
        noise = 1 + np.random.randn(60) * 0.001
        prices = {
            "EURUSD": _price_series(list(noise)),
            "GBPUSD": _price_series(list(noise)),  # identical = correlation ~1
        }
        corr = correlation_matrix(prices, window=20)
        positions: list[Position] = [
            {"symbol": "EURUSD", "exposure": 0.5},
            {"symbol": "GBPUSD", "exposure": 0.5},
        ]
        warnings = check_correlated_exposure(positions, corr, threshold=0.7)
        self.assertGreater(len(warnings), 0)
        self.assertIn("EURUSD", warnings[0])
        self.assertIn("GBPUSD", warnings[0])


class TestPortfolioExposure(unittest.TestCase):
    def test_single_position_full_exposure(self):
        np.random.seed(42)
        prices = {"EURUSD": _price_series(list(1 + np.random.randn(60) * 0.001))}
        corr = correlation_matrix(prices, window=20)
        positions: list[Position] = [{"symbol": "EURUSD", "exposure": 1.0}]
        exposure = portfolio_exposure(positions, corr)
        self.assertAlmostEqual(exposure, 1.0, places=5)

    def test_uncorrelated_positions_sum_exposure(self):
        np.random.seed(42)
        prices = {
            "EURUSD": _price_series(list(1 + np.random.randn(60) * 0.001)),
            "USDJPY": _price_series(list(1 - np.random.randn(60) * 0.001)),
        }
        corr = correlation_matrix(prices, window=20)
        positions: list[Position] = [
            {"symbol": "EURUSD", "exposure": 0.5},
            {"symbol": "USDJPY", "exposure": 0.5},
        ]
        exposure = portfolio_exposure(positions, corr)
        self.assertGreater(exposure, 0.5)


class TestCorrelationTracker(unittest.TestCase):
    def test_incremental_update_single_pair(self):
        np.random.seed(42)
        tracker = CorrelationTracker(pairs=["EURUSD"], window=20)
        self.assertFalse(tracker.is_initialized)

        for i in range(25):
            tracker.update({"EURUSD": 1.0 + i * 0.001})

        self.assertTrue(tracker.is_initialized)
        self.assertIsNotNone(tracker.correlation_matrix)
        self.assertAlmostEqual(tracker.correlation_matrix.loc["EURUSD", "EURUSD"], 1.0, places=5)

    def test_incremental_update_multiple_pairs(self):
        np.random.seed(42)
        tracker = CorrelationTracker(pairs=["EURUSD", "GBPUSD"], window=20)

        for i in range(25):
            tracker.update({
                "EURUSD": 1.0 + i * 0.001,
                "GBPUSD": 1.0 + i * 0.001,
            })

        self.assertTrue(tracker.is_initialized)
        mat = tracker.correlation_matrix
        self.assertAlmostEqual(mat.loc["EURUSD", "GBPUSD"], 1.0, places=2)

    def test_tracker_check_exposure(self):
        np.random.seed(42)
        tracker = CorrelationTracker(pairs=["EURUSD", "GBPUSD"], window=20, threshold=0.7)

        for i in range(25):
            tracker.update({
                "EURUSD": 1.0 + i * 0.001,
                "GBPUSD": 1.0 + i * 0.001,
            })

        positions: list[Position] = [
            {"symbol": "EURUSD", "exposure": 0.5},
            {"symbol": "GBPUSD", "exposure": 0.5},
        ]
        warnings = tracker.check_exposure(positions)
        self.assertGreater(len(warnings), 0)

    def test_tracker_get_portfolio_exposure(self):
        np.random.seed(42)
        tracker = CorrelationTracker(pairs=["EURUSD"], window=20)

        for i in range(25):
            tracker.update({"EURUSD": 1.0 + i * 0.001})

        positions: list[Position] = [{"symbol": "EURUSD", "exposure": 1.0}]
        exposure = tracker.get_portfolio_exposure(positions)
        self.assertAlmostEqual(exposure, 1.0, places=5)

    def test_tracker_not_initialized_until_window_met(self):
        tracker = CorrelationTracker(pairs=["EURUSD"], window=10)
        self.assertFalse(tracker.is_initialized)

        for i in range(10):
            tracker.update({"EURUSD": 1.0 + i * 0.001})

        self.assertFalse(tracker.is_initialized)

        tracker.update({"EURUSD": 1.0 + 10 * 0.001})
        self.assertTrue(tracker.is_initialized)

    def test_tracker_empty_prices(self):
        tracker = CorrelationTracker(pairs=["EURUSD", "GBPUSD"], window=20)
        result = tracker.update({})
        self.assertFalse(tracker.is_initialized)
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()