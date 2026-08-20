import unittest

from quant.statistical_validation import (
    GoNogoDecision,
    check_full_bt_consistency,
    check_min_trade_count,
    check_multi_pair_validation,
    check_statistical_significance,
    evaluate_statistical_checks,
)


class TestCheckStatisticalSignificance(unittest.TestCase):
    def test_positive_pnls_significant(self):
        pnls = [10.0, 15.0, 20.0, 12.0, 18.0, 14.0, 16.0, 22.0, 11.0, 19.0]
        result = check_statistical_significance(pnls, alpha=0.10)
        self.assertTrue(result.passed)
        self.assertEqual(result.name, "statistical_significance")

    def test_negative_pnls_not_significant(self):
        pnls = [-10.0, -15.0, -20.0, -12.0, -18.0]
        result = check_statistical_significance(pnls, alpha=0.10)
        self.assertFalse(result.passed)

    def test_near_zero_pnls_not_significant(self):
        pnls = [0.1, -0.1, 0.2, -0.2, 0.0, 0.1, -0.1, 0.0, 0.05, -0.05]
        result = check_statistical_significance(pnls, alpha=0.10)
        self.assertFalse(result.passed)

    def test_single_trade_not_enough(self):
        result = check_statistical_significance([100.0], alpha=0.10)
        self.assertFalse(result.passed)
        self.assertIn("need >= 2", result.detail)

    def test_empty_pnls(self):
        result = check_statistical_significance([], alpha=0.10)
        self.assertFalse(result.passed)

    def test_large_positive_pnls_very_significant(self):
        pnls = [50.0] * 100
        result = check_statistical_significance(pnls, alpha=0.01)
        self.assertTrue(result.passed)

    def test_detail_contains_p_value(self):
        pnls = [10.0, 15.0, 20.0, 12.0, 18.0]
        result = check_statistical_significance(pnls, alpha=0.10)
        self.assertIn("p=", result.detail)
        self.assertIn("alpha=0.1", result.detail)


class TestCheckMinTradeCount(unittest.TestCase):
    def test_exactly_minimum(self):
        result = check_min_trade_count(50, minimum=50)
        self.assertTrue(result.passed)
        self.assertIn("50 trades", result.detail)

    def test_above_minimum(self):
        result = check_min_trade_count(75, minimum=50)
        self.assertTrue(result.passed)

    def test_below_minimum(self):
        result = check_min_trade_count(30, minimum=50)
        self.assertFalse(result.passed)
        self.assertIn("30 trades", result.detail)

    def test_zero_trades(self):
        result = check_min_trade_count(0, minimum=50)
        self.assertFalse(result.passed)

    def test_custom_minimum(self):
        result = check_min_trade_count(20, minimum=25)
        self.assertFalse(result.passed)
        result = check_min_trade_count(30, minimum=25)
        self.assertTrue(result.passed)


class TestCheckFullBtConsistency(unittest.TestCase):
    def test_positive_bt_positive_wf(self):
        result = check_full_bt_consistency(1000.0, True)
        self.assertTrue(result.passed)

    def test_negative_bt_negative_wf(self):
        result = check_full_bt_consistency(-500.0, False)
        self.assertTrue(result.passed)

    def test_negative_bt_positive_wf_inconclusive(self):
        result = check_full_bt_consistency(-500.0, True)
        self.assertFalse(result.passed)
        self.assertIn("inconclusive", result.detail)

    def test_positive_bt_negative_wf(self):
        result = check_full_bt_consistency(1000.0, False)
        self.assertFalse(result.passed)

    def test_zero_bt_positive_wf(self):
        result = check_full_bt_consistency(0.0, True)
        self.assertFalse(result.passed)


class TestCheckMultiPairValidation(unittest.TestCase):
    def test_two_pairs_confirmed(self):
        pair_results = {"EUR/USD": 1.5, "GBP/USD": 1.2, "AUD/USD": 0.8}
        result = check_multi_pair_validation(pair_results)
        self.assertTrue(result.passed)

    def test_one_pair_weak(self):
        pair_results = {"EUR/USD": 1.5, "GBP/USD": 0.8}
        result = check_multi_pair_validation(pair_results)
        self.assertFalse(result.passed)
        self.assertIn("weak", result.extra["status"])

    def test_no_pairs_failed(self):
        pair_results = {"EUR/USD": 0.8, "GBP/USD": 0.5}
        result = check_multi_pair_validation(pair_results)
        self.assertFalse(result.passed)
        self.assertIn("failed", result.extra["status"])

    def test_empty_pairs(self):
        result = check_multi_pair_validation({})
        self.assertFalse(result.passed)
        self.assertIn("failed", result.extra["status"])

    def test_all_pairs_positive(self):
        pair_results = {"EUR/USD": 1.5, "GBP/USD": 1.2, "AUD/USD": 1.1}
        result = check_multi_pair_validation(pair_results)
        self.assertTrue(result.passed)
        self.assertIn("confirmed", result.extra["status"])

    def test_many_pairs_two_pass(self):
        pair_results = {
            "EUR/USD": 1.5,
            "GBP/USD": 1.2,
            "AUD/USD": 0.8,
            "USD/JPY": 0.6,
            "USD/CHF": 0.4,
        }
        result = check_multi_pair_validation(pair_results)
        self.assertTrue(result.passed)


class TestEvaluateStatisticalChecks(unittest.TestCase):
    def test_strong_positive_go(self):
        pnls = [50.0] * 100
        result = evaluate_statistical_checks(pnls)
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)
        self.assertTrue(result.min_trades_met)
        self.assertTrue(result.significance_met)
        self.assertEqual(result.total_oos_trades, 100)

    def test_too_few_trades_inconclusive(self):
        pnls = [100.0, 200.0]
        result = evaluate_statistical_checks(pnls, min_trades=50)
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)
        self.assertFalse(result.min_trades_met)

    def test_negative_pnls_no_go(self):
        pnls = [-10.0] * 60
        result = evaluate_statistical_checks(pnls)
        self.assertEqual(result.decision, GoNogoDecision.NO_GO)

    def test_with_full_bt_consistency(self):
        pnls = [50.0] * 60
        result = evaluate_statistical_checks(pnls, full_bt_pnl=-1000.0)
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)
        self.assertFalse(result.full_bt_consistent)

    def test_bt_consistency_uses_aggregate_pnl_not_any_trade(self):
        mostly_losing = [-10.0, -20.0, -15.0, -8.0, -12.0, -9.0, -11.0, 0.5]
        self.assertTrue(any(p > 0 for p in mostly_losing))
        self.assertLess(sum(mostly_losing), 0)
        result = evaluate_statistical_checks(mostly_losing, full_bt_pnl=-500.0, min_trades=5)
        self.assertTrue(result.full_bt_consistent)
        self.assertEqual(result.decision, GoNogoDecision.NO_GO)

    def test_with_multi_pair_confirmed(self):
        pnls = [50.0] * 60
        pair_results = {"EUR/USD": 1.5, "GBP/USD": 1.2}
        result = evaluate_statistical_checks(pnls, pair_results=pair_results)
        self.assertEqual(result.decision, GoNogoDecision.GO)
        self.assertEqual(result.multi_pair_status, "confirmed")

    def test_with_multi_pair_weak(self):
        pnls = [50.0] * 60
        pair_results = {"EUR/USD": 1.5, "GBP/USD": 0.8}
        result = evaluate_statistical_checks(pnls, pair_results=pair_results)
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)
        self.assertEqual(result.multi_pair_status, "weak")

    def test_with_multi_pair_failed(self):
        pnls = [50.0] * 60
        pair_results = {"EUR/USD": 0.8, "GBP/USD": 0.5}
        result = evaluate_statistical_checks(pnls, pair_results=pair_results)
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)
        self.assertEqual(result.multi_pair_status, "failed")

    def test_empty_pnls(self):
        result = evaluate_statistical_checks([])
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)
        self.assertFalse(result.min_trades_met)
        self.assertIsNone(result.p_value)

    def test_p_value_set_for_sufficient_trades(self):
        pnls = [10.0, 15.0, 20.0, 12.0, 18.0]
        result = evaluate_statistical_checks(pnls)
        self.assertIsNotNone(result.p_value)

    def test_checks_list_populated(self):
        pnls = [10.0, 15.0, 20.0, 12.0, 18.0]
        result = evaluate_statistical_checks(pnls, full_bt_pnl=500.0)
        check_names = [c.name for c in result.checks]
        self.assertIn("statistical_significance", check_names)
        self.assertIn("min_trade_count", check_names)
        self.assertIn("full_bt_consistency", check_names)

    def test_full_bt_none_skipped(self):
        pnls = [50.0] * 60
        result = evaluate_statistical_checks(pnls)
        self.assertIsNone(result.full_bt_consistent)
        check_names = [c.name for c in result.checks]
        self.assertNotIn("full_bt_consistency", check_names)

    def test_pair_results_none_skipped(self):
        pnls = [50.0] * 60
        result = evaluate_statistical_checks(pnls)
        self.assertIsNone(result.multi_pair_status)
        check_names = [c.name for c in result.checks]
        self.assertNotIn("multi_pair_validation", check_names)


class TestGoNogoDecision(unittest.TestCase):
    def test_enum_values(self):
        self.assertEqual(GoNogoDecision.GO.value, "GO")
        self.assertEqual(GoNogoDecision.NO_GO.value, "NO_GO")
        self.assertEqual(GoNogoDecision.INCONCLUSIVE.value, "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
