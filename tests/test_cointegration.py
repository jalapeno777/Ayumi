import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

import numpy as np
from quant.cointegration import (
    CointegrationEngine,
    CointegrationResult,
    SpreadStats,
    PairsSignalGenerator,
    parameter_sweep,
)


def make_cointegrated_prices(n=200, seed=42):
    np.random.seed(seed)
    t = np.linspace(0, 10, n)
    common_factor = np.sin(t) + np.random.normal(0, 0.1, n)

    prices_a = 1.1000 + 0.05 * common_factor + np.random.normal(0, 0.01, n)
    prices_b = 0.8500 + 0.04 * common_factor + np.random.normal(0, 0.01, n)

    return prices_a, prices_b


def make_non_cointegrated_prices(n=200, seed=42):
    np.random.seed(seed)
    prices_a = 1.1000 + np.cumsum(np.random.normal(0, 0.002, n))
    prices_b = 0.8500 + np.cumsum(np.random.normal(0, 0.003, n))
    return prices_a, prices_b


class TestCointegrationEngine(unittest.TestCase):
    def test_hedge_ratio_calculation(self):
        engine = CointegrationEngine(lookback=60)
        prices_a = np.array([1.10, 1.11, 1.12, 1.13, 1.14])
        prices_b = np.array([0.85, 0.86, 0.87, 0.88, 0.89])
        hedge_ratio, constant = engine.compute_hedge_ratio(prices_a, prices_b)
        self.assertIsInstance(hedge_ratio, float)
        self.assertIsInstance(constant, float)

    def test_compute_spread(self):
        engine = CointegrationEngine(lookback=60)
        prices_a = np.array([1.10, 1.11, 1.12, 1.13, 1.14])
        prices_b = np.array([0.85, 0.86, 0.87, 0.88, 0.89])
        spread = engine.compute_spread(prices_a, prices_b, hedge_ratio=1.0, constant=0.0)
        self.assertEqual(len(spread), len(prices_a))
        self.assertIsInstance(spread, np.ndarray)

    def test_engle_granger_test_with_sufficient_data(self):
        engine = CointegrationEngine(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(200)
        result = engine.engle_granger_test(prices_a, prices_b)
        self.assertIsInstance(result, CointegrationResult)
        self.assertIsInstance(result.is_cointegrated, bool)
        self.assertIsInstance(result.p_value, float)
        self.assertIsInstance(result.hedge_ratio, float)
        self.assertIsInstance(result.constant, float)

    def test_engle_granger_test_with_insufficient_data(self):
        engine = CointegrationEngine(lookback=60)
        prices_a = np.array([1.10, 1.11])
        prices_b = np.array([0.85, 0.86])
        result = engine.engle_granger_test(prices_a, prices_b)
        self.assertFalse(result.is_cointegrated)
        self.assertEqual(result.p_value, 1.0)

    def test_compute_z_score(self):
        engine = CointegrationEngine(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(200)
        spread_stats = engine.compute_z_score(prices_a, prices_b)
        self.assertIsInstance(spread_stats, SpreadStats)
        self.assertIsInstance(spread_stats.mean, float)
        self.assertIsInstance(spread_stats.std, float)
        self.assertIsInstance(spread_stats.z_score, float)
        self.assertIsInstance(spread_stats.spread, float)

    def test_rolling_cointegration(self):
        engine = CointegrationEngine(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(200)
        results = engine.rolling_cointegration(prices_a, prices_b, window=60, step=10)
        self.assertIsInstance(results, list)
        if results:
            self.assertIn("is_cointegrated", results[0])
            self.assertIn("z_score", results[0])
            self.assertIn("hedge_ratio", results[0])


class TestPairsSignalGenerator(unittest.TestCase):
    def test_initialization(self):
        generator = PairsSignalGenerator(
            entry_threshold=2.0,
            exit_threshold=0.0,
            stop_loss_threshold=3.0,
            lookback=60,
        )
        self.assertEqual(generator.entry_threshold, 2.0)
        self.assertEqual(generator.exit_threshold, 0.0)
        self.assertEqual(generator.stop_loss_threshold, 3.0)
        self.assertEqual(generator.lookback, 60)

    def test_reset(self):
        generator = PairsSignalGenerator()
        generator._in_position = True
        generator._position_side = "long"
        generator.reset()
        self.assertFalse(generator._in_position)
        self.assertIsNone(generator._position_side)
        self.assertIsNone(generator._hedge_ratio)

    def test_update_cointegration_success(self):
        generator = PairsSignalGenerator(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(200)
        result = generator.update_cointegration(prices_a, prices_b)
        self.assertIsInstance(result, bool)

    def test_generate_signal_no_position(self):
        generator = PairsSignalGenerator(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(200)
        generator.update_cointegration(prices_a, prices_b)

        for i in range(60, len(prices_a)):
            pa = prices_a[: i + 1]
            pb = prices_b[: i + 1]
            generator.update_cointegration(pa, pb)
            signal, reason = generator.generate_signal(pa, pb)
            if signal is not None:
                self.assertIsInstance(signal, str)
                self.assertIsInstance(reason, str)
                break

    def test_compute_z_score(self):
        generator = PairsSignalGenerator(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(200)
        generator.update_cointegration(prices_a, prices_b)
        z_score = generator.compute_z_score(prices_a, prices_b)
        if z_score is not None:
            self.assertIsInstance(z_score, float)


class TestParameterSweep(unittest.TestCase):
    def test_parameter_sweep_returns_list(self):
        prices_a, prices_b = make_cointegrated_prices(200)
        lookbacks = [60]
        entry_thresholds = [2.0]
        exit_thresholds = [0.0]
        stop_thresholds = [3.0]

        results = parameter_sweep(
            prices_a, prices_b, lookbacks, entry_thresholds, exit_thresholds, stop_thresholds
        )
        self.assertIsInstance(results, list)


class TestSpreadStats(unittest.TestCase):
    def test_spread_stats_creation(self):
        stats = SpreadStats(mean=0.0, std=1.0, z_score=0.5, spread=0.5)
        self.assertEqual(stats.mean, 0.0)
        self.assertEqual(stats.std, 1.0)
        self.assertEqual(stats.z_score, 0.5)
        self.assertEqual(stats.spread, 0.5)


class TestCointegrationResult(unittest.TestCase):
    def test_cointegration_result_creation(self):
        result = CointegrationResult(
            is_cointegrated=True,
            p_value=0.01,
            hedge_ratio=1.2,
            constant=0.01,
            adf_statistic=-3.5,
            adf_p_value=0.01,
        )
        self.assertTrue(result.is_cointegrated)
        self.assertEqual(result.p_value, 0.01)
        self.assertEqual(result.hedge_ratio, 1.2)
        self.assertEqual(result.constant, 0.01)
        self.assertEqual(result.adf_statistic, -3.5)
        self.assertEqual(result.adf_p_value, 0.01)


if __name__ == "__main__":
    unittest.main()
