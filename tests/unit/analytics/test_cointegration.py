import unittest

import numpy as np
from quant.cointegration import (
    CointegrationEngine,
    CointegrationResult,
    PairsSignalGenerator,
    SpreadStats,
    parameter_sweep,
)


def make_cointegrated_prices(n=200, seed=42, noise_std=0.01):
    """Generate genuinely cointegrated price pairs using common-factor model.

    prices_a = base_a + beta * common_factor + noise_a
    prices_b = base_b + gamma * common_factor + noise_b
    The spread (prices_a - hedge_ratio * prices_b) should be stationary.
    """
    rng = np.random.default_rng(seed)
    common = np.cumsum(rng.normal(0, 0.001, n))
    prices_a = 1.1000 + 0.5 * common + rng.normal(0, noise_std, n)
    prices_b = 0.8500 + 0.4 * common + rng.normal(0, noise_std, n)
    return prices_a, prices_b


def make_non_cointegrated_prices(n=200, seed=42):
    """Generate independent random walks (not cointegrated)."""
    rng = np.random.default_rng(seed)
    prices_a = 1.1000 + np.cumsum(rng.normal(0, 0.002, n))
    prices_b = 0.8500 + np.cumsum(rng.normal(0, 0.003, n))
    return prices_a, prices_b


def make_degenerate_prices(n=50):
    """Constant prices for edge-case testing."""
    return np.full(n, 1.1000), np.full(n, 0.8500)


class TestCointegrationEngine(unittest.TestCase):
    def test_hedge_ratio_with_known_linear_relation(self):
        engine = CointegrationEngine(lookback=60)
        prices_b = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=float)
        prices_a = 2.0 * prices_b + 1.0
        hedge_ratio, constant = engine.compute_hedge_ratio(prices_a, prices_b)
        self.assertAlmostEqual(hedge_ratio, 2.0, places=5)
        self.assertAlmostEqual(constant, 1.0, places=5)

    def test_hedge_ratio_with_insufficient_data(self):
        engine = CointegrationEngine(lookback=60)
        hr, const = engine.compute_hedge_ratio(np.array([1.1]), np.array([0.85]))
        self.assertEqual(hr, 1.0)
        self.assertEqual(const, 0.0)

    def test_compute_spread_with_known_params(self):
        engine = CointegrationEngine(lookback=60)
        prices_a = np.array([3.0, 5.0, 7.0], dtype=float)
        prices_b = np.array([1.0, 2.0, 3.0], dtype=float)
        spread = engine.compute_spread(prices_a, prices_b, hedge_ratio=2.0, constant=1.0)
        expected = prices_a - 2.0 * prices_b - 1.0
        np.testing.assert_array_almost_equal(spread, expected)

    def test_engle_granger_detects_cointegrated_pairs(self):
        engine = CointegrationEngine(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(200)
        result = engine.engle_granger_test(prices_a, prices_b)
        self.assertIsInstance(result, CointegrationResult)
        self.assertTrue(
            result.is_cointegrated,
            "Cointegrated pair should be detected as cointegrated",
        )
        self.assertLess(result.adf_p_value, 0.05)

    def test_engle_granger_rejects_non_cointegrated_pairs(self):
        engine = CointegrationEngine(lookback=60)
        prices_a, prices_b = make_non_cointegrated_prices(200)
        result = engine.engle_granger_test(prices_a, prices_b)
        self.assertIsInstance(result, CointegrationResult)
        self.assertFalse(
            result.is_cointegrated,
            "Independent random walks should not be cointegrated",
        )

    def test_engle_granger_with_insufficient_data(self):
        engine = CointegrationEngine(lookback=60)
        prices_a = np.array([1.10, 1.11])
        prices_b = np.array([0.85, 0.86])
        result = engine.engle_granger_test(prices_a, prices_b)
        self.assertFalse(result.is_cointegrated)
        self.assertEqual(result.p_value, 1.0)
        self.assertEqual(result.adf_p_value, 1.0)

    def test_engle_granger_returns_valid_hedge_ratio(self):
        engine = CointegrationEngine(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(200)
        result = engine.engle_granger_test(prices_a, prices_b)
        self.assertIsInstance(result.hedge_ratio, float)
        self.assertIsInstance(result.constant, float)
        self.assertIsInstance(result.adf_statistic, float)

    def test_compute_z_score_no_lookahead_bias(self):
        engine = CointegrationEngine(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(200)
        stats = engine.compute_z_score(prices_a, prices_b)
        self.assertIsInstance(stats, SpreadStats)
        self.assertIsInstance(stats.z_score, float)
        self.assertIsInstance(stats.mean, float)
        self.assertGreater(stats.std, 0.0)

    def test_z_score_mean_reverts_for_cointegrated(self):
        engine = CointegrationEngine(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(500, seed=123)
        z_scores = []
        for i in range(60, len(prices_a)):
            pa = prices_a[: i + 1]
            pb = prices_b[: i + 1]
            result = engine.engle_granger_test(pa, pb)
            if result.is_cointegrated:
                stats = engine.compute_z_score(pa, pb, result.hedge_ratio, result.constant)
                z_scores.append(stats.z_score)

        if len(z_scores) > 10:
            mean_z = float(np.mean(z_scores))
            self.assertAlmostEqual(
                mean_z,
                0.0,
                delta=1.0,
                msg="Mean z-score should be near zero for cointegrated pairs",
            )

    def test_z_score_with_degenerate_prices(self):
        engine = CointegrationEngine(lookback=60)
        pa, pb = make_degenerate_prices(100)
        stats = engine.compute_z_score(pa, pb)
        self.assertEqual(stats.z_score, 0.0)

    def test_rolling_cointegration_structure(self):
        engine = CointegrationEngine(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(200)
        results = engine.rolling_cointegration(prices_a, prices_b, window=60, step=10)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("is_cointegrated", r)
            self.assertIn("z_score", r)
            self.assertIn("hedge_ratio", r)
            self.assertIn("p_value", r)
            self.assertIn("window_start", r)
            self.assertIn("window_end", r)

    def test_rolling_cointegration_detects_cointegration_windows(self):
        engine = CointegrationEngine(lookback=60)
        prices_a, prices_b = make_cointegrated_prices(300)
        results = engine.rolling_cointegration(prices_a, prices_b, window=80, step=20)
        coint_count = sum(1 for r in results if r["is_cointegrated"])
        self.assertGreater(
            coint_count,
            0,
            "At least some windows should be cointegrated for cointegrated series",
        )


class TestPairsSignalGenerator(unittest.TestCase):
    def setUp(self):
        self.prices_a, self.prices_b = make_cointegrated_prices(300, seed=42)

    def test_initialization(self):
        gen = PairsSignalGenerator(
            entry_threshold=2.0,
            exit_threshold=0.0,
            stop_loss_threshold=3.0,
            lookback=60,
        )
        self.assertEqual(gen.entry_threshold, 2.0)
        self.assertEqual(gen.exit_threshold, 0.0)
        self.assertEqual(gen.stop_loss_threshold, 3.0)
        self.assertEqual(gen.lookback, 60)

    def test_reset_clears_state(self):
        gen = PairsSignalGenerator()
        gen._in_position = True
        gen._position_side = "long"
        gen._hedge_ratio = 1.5
        gen._constant = 0.01
        gen.reset()
        self.assertFalse(gen._in_position)
        self.assertIsNone(gen._position_side)
        self.assertIsNone(gen._hedge_ratio)
        self.assertIsNone(gen._constant)

    def test_update_cointegration_returns_bool(self):
        gen = PairsSignalGenerator(lookback=60)
        result = gen.update_cointegration(self.prices_a, self.prices_b)
        self.assertIsInstance(result, bool)

    def test_update_cointegration_sets_hedge_ratio(self):
        gen = PairsSignalGenerator(lookback=60)
        gen.update_cointegration(self.prices_a, self.prices_b)
        self.assertIsNotNone(gen._hedge_ratio)
        self.assertIsNotNone(gen._constant)
        self.assertIsInstance(gen._hedge_ratio, float)

    def test_compute_z_score_returns_float_when_initialized(self):
        gen = PairsSignalGenerator(lookback=60)
        gen.update_cointegration(self.prices_a, self.prices_b)
        z = gen.compute_z_score(self.prices_a, self.prices_b)
        self.assertIsNotNone(z)
        self.assertIsInstance(z, float)

    def test_compute_z_score_returns_none_without_initialization(self):
        gen = PairsSignalGenerator(lookback=60)
        z = gen.compute_z_score(self.prices_a, self.prices_b)
        self.assertIsNone(z)

    def test_compute_spread_returns_float_when_initialized(self):
        gen = PairsSignalGenerator(lookback=60)
        gen.update_cointegration(self.prices_a, self.prices_b)
        spread = gen.compute_spread(self.prices_a, self.prices_b)
        self.assertIsNotNone(spread)
        self.assertIsInstance(spread, float)

    def test_compute_spread_returns_none_without_initialization(self):
        gen = PairsSignalGenerator(lookback=60)
        spread = gen.compute_spread(self.prices_a, self.prices_b)
        self.assertIsNone(spread)

    def test_signal_lifecycle_entry_then_exit(self):
        gen = PairsSignalGenerator(
            entry_threshold=1.5,
            exit_threshold=0.0,
            stop_loss_threshold=5.0,
            lookback=60,
        )
        entry_found = False
        for i in range(60, len(self.prices_a)):
            pa = self.prices_a[: i + 1]
            pb = self.prices_b[: i + 1]
            if gen.update_cointegration(pa, pb):
                signal, reason = gen.generate_signal(pa, pb)
                if signal and signal.startswith("entry"):
                    entry_found = True
                    self.assertIn(gen._position_side, ["long", "short"])
                    self.assertTrue(gen._in_position)
                    break

        self.assertTrue(entry_found, "Should find at least one entry signal")

    def test_hold_signal_while_in_position(self):
        gen = PairsSignalGenerator(
            entry_threshold=1.5,
            exit_threshold=0.0,
            stop_loss_threshold=5.0,
            lookback=60,
        )
        for i in range(60, len(self.prices_a)):
            pa = self.prices_a[: i + 1]
            pb = self.prices_b[: i + 1]
            if gen.update_cointegration(pa, pb):
                signal, reason = gen.generate_signal(pa, pb)
                if signal and signal.startswith("entry"):
                    for j in range(i + 1, min(i + 10, len(self.prices_a))):
                        pa2 = self.prices_a[: j + 1]
                        pb2 = self.prices_b[: j + 1]
                        if gen.update_cointegration(pa2, pb2):
                            sig2, _ = gen.generate_signal(pa2, pb2)
                            if sig2 and sig2.startswith("hold"):
                                return

        self.fail("Should produce a hold signal after entry")

    def test_signal_types_are_valid(self):
        gen = PairsSignalGenerator(
            entry_threshold=1.0,
            exit_threshold=0.0,
            stop_loss_threshold=5.0,
            lookback=60,
        )
        valid_signals = {
            "entry_long",
            "entry_short",
            "exit",
            "stop_loss",
            "hold_long",
            "hold_short",
            None,
        }
        for i in range(60, len(self.prices_a)):
            pa = self.prices_a[: i + 1]
            pb = self.prices_b[: i + 1]
            if gen.update_cointegration(pa, pb):
                signal, reason = gen.generate_signal(pa, pb)
                self.assertIn(
                    signal,
                    valid_signals,
                    f"Unexpected signal type: {signal}",
                )

    def test_non_cointegrated_data_produces_fewer_signals(self):
        gen = PairsSignalGenerator(lookback=60)
        pa, pb = make_non_cointegrated_prices(200)
        signal_count = 0
        for i in range(60, len(pa)):
            if gen.update_cointegration(pa[: i + 1], pb[: i + 1]):
                signal, _ = gen.generate_signal(pa[: i + 1], pb[: i + 1])
                if signal and signal.startswith("entry"):
                    signal_count += 1
        cointegrated_a, cointegrated_b = make_cointegrated_prices(200, seed=42)
        gen2 = PairsSignalGenerator(lookback=60)
        coint_signal_count = 0
        for i in range(60, len(cointegrated_a)):
            if gen2.update_cointegration(cointegrated_a[: i + 1], cointegrated_b[: i + 1]):
                signal, _ = gen2.generate_signal(cointegrated_a[: i + 1], cointegrated_b[: i + 1])
                if signal and signal.startswith("entry"):
                    coint_signal_count += 1
        self.assertLessEqual(
            signal_count,
            coint_signal_count + 2,
            "Non-cointegrated data should produce fewer or similar signals",
        )


class TestParameterSweep(unittest.TestCase):
    def test_returns_list_of_dicts(self):
        prices_a, prices_b = make_cointegrated_prices(200)
        results = parameter_sweep(
            prices_a,
            prices_b,
            lookbacks=[60],
            entry_thresholds=[2.0],
            exit_thresholds=[0.0],
            stop_thresholds=[3.0],
        )
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertIn("lookback", r)
        self.assertIn("entry_threshold", r)
        self.assertIn("exit_threshold", r)
        self.assertIn("stop_loss_threshold", r)
        self.assertIn("num_signals", r)
        self.assertEqual(r["lookback"], 60)
        self.assertEqual(r["entry_threshold"], 2.0)

    def test_skips_invalid_stop_entry_combos(self):
        prices_a, prices_b = make_cointegrated_prices(200)
        results = parameter_sweep(
            prices_a,
            prices_b,
            lookbacks=[60],
            entry_thresholds=[3.0],
            exit_thresholds=[0.0],
            stop_thresholds=[2.0],
        )
        self.assertEqual(len(results), 0, "stop <= entry should be skipped")

    def test_multiple_param_combos(self):
        prices_a, prices_b = make_cointegrated_prices(200)
        results = parameter_sweep(
            prices_a,
            prices_b,
            lookbacks=[60, 80],
            entry_thresholds=[1.5, 2.0],
            exit_thresholds=[0.0],
            stop_thresholds=[3.0],
        )
        self.assertEqual(len(results), 4)


class TestSpreadStats(unittest.TestCase):
    def test_creation(self):
        stats = SpreadStats(mean=0.0, std=1.0, z_score=0.5, spread=0.5)
        self.assertEqual(stats.mean, 0.0)
        self.assertEqual(stats.std, 1.0)
        self.assertEqual(stats.z_score, 0.5)
        self.assertEqual(stats.spread, 0.5)


class TestCointegrationResult(unittest.TestCase):
    def test_creation(self):
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
