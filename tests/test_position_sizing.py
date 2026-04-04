import unittest

from quant.position_sizing import (
    DynamicSizingConfig,
    check_position_limits,
    dynamic_sizing,
    fixed_fractional,
    kelly_criterion,
)


class TestFixedFractional(unittest.TestCase):
    def test_standard_calculation(self):
        result = fixed_fractional(10000, 1.0, 1.1000, 1.0950)
        self.assertAlmostEqual(result, 0.2, places=4)

    def test_zero_balance(self):
        result = fixed_fractional(0, 1.0, 1.1000, 1.0950)
        self.assertEqual(result, 0.0)

    def test_negative_balance(self):
        result = fixed_fractional(-100, 1.0, 1.1000, 1.0950)
        self.assertEqual(result, 0.0)

    def test_zero_risk_pct(self):
        result = fixed_fractional(10000, 0, 1.1000, 1.0950)
        self.assertEqual(result, 0.0)

    def test_negative_risk_pct(self):
        result = fixed_fractional(10000, -1.0, 1.1000, 1.0950)
        self.assertEqual(result, 0.0)

    def test_zero_stop_distance(self):
        result = fixed_fractional(10000, 1.0, 1.1000, 1.1000)
        self.assertEqual(result, 0.0)

    def test_short_position(self):
        result = fixed_fractional(10000, 1.0, 1.1000, 1.1050)
        self.assertAlmostEqual(result, 0.2, places=4)

    def test_high_risk_pct(self):
        result = fixed_fractional(10000, 5.0, 1.1000, 1.0950)
        self.assertAlmostEqual(result, 1.0, places=4)

    def test_small_balance(self):
        result = fixed_fractional(100, 1.0, 1.1000, 1.0950)
        self.assertAlmostEqual(result, 0.002, places=4)


class TestKellyCriterion(unittest.TestCase):
    def test_positive_edge(self):
        result = kelly_criterion(0.6, 200, 100)
        self.assertAlmostEqual(result, 0.2, places=4)

    def test_half_kelly_cap(self):
        result = kelly_criterion(0.8, 500, 100)
        expected_full_kelly = (5.0 * 0.8 - 0.2) / 5.0
        expected_half_kelly = expected_full_kelly / 2.0
        self.assertAlmostEqual(result, expected_half_kelly, places=4)

    def test_negative_edge_returns_zero(self):
        result = kelly_criterion(0.3, 100, 200)
        self.assertEqual(result, 0.0)

    def test_break_even_returns_zero(self):
        result = kelly_criterion(0.5, 100, 100)
        self.assertEqual(result, 0.0)

    def test_zero_avg_loss(self):
        result = kelly_criterion(0.6, 200, 0)
        self.assertEqual(result, 0.0)

    def test_perfect_win_rate(self):
        result = kelly_criterion(1.0, 100, 100)
        self.assertAlmostEqual(result, 0.5, places=4)

    def test_zero_win_rate(self):
        result = kelly_criterion(0.0, 100, 100)
        self.assertEqual(result, 0.0)

    def test_capped_at_50_percent(self):
        result = kelly_criterion(0.99, 1000, 1)
        self.assertLessEqual(result, 0.5)


class TestDynamicSizing(unittest.TestCase):
    def test_neutral_returns_base(self):
        result = dynamic_sizing(1.0, 0.0, 0, 0)
        self.assertAlmostEqual(result, 1.0, places=4)

    def test_positive_pnl_increases(self):
        result = dynamic_sizing(1.0, 500, 0, 0)
        self.assertGreater(result, 1.0)

    def test_negative_pnl_decreases(self):
        result = dynamic_sizing(1.0, -500, 0, 0)
        self.assertLess(result, 1.0)

    def test_win_streak_increases(self):
        result = dynamic_sizing(1.0, 0.0, 3, 0)
        self.assertGreater(result, 1.0)

    def test_loss_streak_decreases(self):
        result = dynamic_sizing(1.0, 0.0, 0, 3)
        self.assertLess(result, 1.0)

    def test_max_multiplier_cap(self):
        cfg = DynamicSizingConfig(
            max_multiplier=1.5, win_increase=1.0, max_streak_impact=10.0
        )
        result = dynamic_sizing(1.0, 5000, 10, 0, config=cfg)
        self.assertAlmostEqual(result, 1.5, places=4)

    def test_min_multiplier_floor(self):
        cfg = DynamicSizingConfig(
            min_multiplier=0.5, loss_reduction=1.0, max_streak_impact=10.0
        )
        result = dynamic_sizing(1.0, -5000, 0, 10, config=cfg)
        self.assertAlmostEqual(result, 0.5, places=4)

    def test_zero_base_returns_zero(self):
        result = dynamic_sizing(0.0, 500, 3, 0)
        self.assertEqual(result, 0.0)

    def test_negative_base_returns_zero(self):
        result = dynamic_sizing(-1.0, 500, 3, 0)
        self.assertEqual(result, 0.0)

    def test_combined_pnl_and_streak(self):
        result = dynamic_sizing(1.0, 500, 2, 0)
        result_neutral = dynamic_sizing(1.0, 500, 0, 0)
        self.assertGreater(result, result_neutral)

    def test_custom_config(self):
        cfg = DynamicSizingConfig(
            min_multiplier=0.8,
            max_multiplier=1.2,
            win_increase=0.05,
            loss_reduction=0.05,
        )
        result = dynamic_sizing(1.0, 1000, 0, 0, config=cfg)
        self.assertGreaterEqual(result, 0.8)
        self.assertLessEqual(result, 1.2)


class TestCheckPositionLimits(unittest.TestCase):
    def test_no_positions_allowed(self):
        result = check_position_limits({}, "EURUSD", 1.0, 5.0)
        self.assertTrue(result)

    def test_pair_at_limit(self):
        positions = {"EURUSD": 1.0}
        result = check_position_limits(positions, "EURUSD", 1.0, 5.0)
        self.assertFalse(result)

    def test_pair_below_limit(self):
        positions = {"EURUSD": 0.5}
        result = check_position_limits(positions, "EURUSD", 1.0, 5.0)
        self.assertTrue(result)

    def test_total_at_limit(self):
        positions = {"EURUSD": 3.0, "GBPUSD": 2.0}
        result = check_position_limits(positions, "AUDUSD", 1.0, 5.0)
        self.assertFalse(result)

    def test_total_below_limit(self):
        positions = {"EURUSD": 2.0, "GBPUSD": 1.0}
        result = check_position_limits(positions, "AUDUSD", 1.0, 5.0)
        self.assertTrue(result)

    def test_pair_limit_blocks_even_if_total_ok(self):
        positions = {"EURUSD": 2.0}
        result = check_position_limits(positions, "EURUSD", 2.0, 10.0)
        self.assertFalse(result)

    def test_new_pair_not_in_positions(self):
        positions = {"EURUSD": 1.0}
        result = check_position_limits(positions, "GBPUSD", 1.0, 5.0)
        self.assertTrue(result)

    def test_zero_max_per_pair(self):
        result = check_position_limits({}, "EURUSD", 0.0, 5.0)
        self.assertFalse(result)

    def test_zero_max_total(self):
        result = check_position_limits({}, "EURUSD", 1.0, 0.0)
        self.assertFalse(result)

    def test_empty_positions_zero_totals(self):
        result = check_position_limits({}, "EURUSD", 0.0, 0.0)
        self.assertFalse(result)


class TestDynamicSizingConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = DynamicSizingConfig()
        self.assertEqual(cfg.min_multiplier, 0.5)
        self.assertEqual(cfg.max_multiplier, 1.5)
        self.assertEqual(cfg.loss_reduction, 0.1)
        self.assertEqual(cfg.win_increase, 0.1)
        self.assertEqual(cfg.max_streak_impact, 0.5)

    def test_custom_values(self):
        cfg = DynamicSizingConfig(min_multiplier=0.7, max_multiplier=1.3)
        self.assertEqual(cfg.min_multiplier, 0.7)
        self.assertEqual(cfg.max_multiplier, 1.3)


if __name__ == "__main__":
    unittest.main()
