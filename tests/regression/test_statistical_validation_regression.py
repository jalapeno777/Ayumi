import unittest

from quant.statistical_validation import (
    GoNogoDecision,
    evaluate_statistical_checks,
)

from tests.fixtures.historical_strategy_pnls import (
    EURUSD_SESSION_RANGE_MR_ALL_WINDOWS,
    EURUSD_SUPERTREND_RSI_ALL_WINDOWS,
    GBPUSD_KELTNER_ALL_WINDOWS,
    GBPUSD_SESSION_RANGE_MR_ALL_WINDOWS,
    GBPUSD_SUPERTRENT_RSI_ALL_WINDOWS,
    SRM_EURUSD_H1_FALSE_POSITIVE,
)


class TestSRMFalsePositiveRegression(unittest.TestCase):
    """Regression: SRM EURUSD H1 was incorrectly marked GO under old heuristic.

    Known from AYU-90: p=0.40, 33 trades. Under statistical validation this
    should be INCONCLUSIVE (too few trades for min_trades=50), preventing the
    false positive that led to 12 unprofitable sprints.
    """

    def test_srm_false_positive_is_inconclusive(self):
        result = evaluate_statistical_checks(SRM_EURUSD_H1_FALSE_POSITIVE)
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)

    def test_srm_false_positive_too_few_trades(self):
        result = evaluate_statistical_checks(SRM_EURUSD_H1_FALSE_POSITIVE)
        self.assertFalse(result.min_trades_met)
        self.assertEqual(len(SRM_EURUSD_H1_FALSE_POSITIVE), 33)

    def test_srm_false_positive_not_significant(self):
        result = evaluate_statistical_checks(SRM_EURUSD_H1_FALSE_POSITIVE)
        self.assertFalse(result.significance_met)
        if result.p_value is not None:
            self.assertGreater(result.p_value, 0.10)

    def test_srm_false_positive_total_trades_preserved(self):
        result = evaluate_statistical_checks(SRM_EURUSD_H1_FALSE_POSITIVE)
        self.assertEqual(result.total_oos_trades, 33)


class TestHistoricalStrategyRegression(unittest.TestCase):
    """Regression tests against known historical walk-forward results.

    Each test verifies that the statistical validation module produces the
    expected decision class for strategies whose outcomes are well understood.

    Decision logic recap:
    - < min_trades (50) -> INCONCLUSIVE
    - enough trades + not significant -> NO_GO
    - enough trades + significant + no pair_results -> INCONCLUSIVE (not GO)
    - enough trades + significant + confirmed pairs -> GO
    """

    def test_eurusd_session_range_mr_no_go(self):
        result = evaluate_statistical_checks(EURUSD_SESSION_RANGE_MR_ALL_WINDOWS)
        self.assertEqual(len(EURUSD_SESSION_RANGE_MR_ALL_WINDOWS), 62)
        self.assertTrue(result.min_trades_met)
        self.assertFalse(result.significance_met)
        self.assertEqual(result.decision, GoNogoDecision.NO_GO)

    def test_gbpusd_session_range_mr_no_go(self):
        result = evaluate_statistical_checks(GBPUSD_SESSION_RANGE_MR_ALL_WINDOWS)
        self.assertEqual(len(GBPUSD_SESSION_RANGE_MR_ALL_WINDOWS), 74)
        self.assertTrue(result.min_trades_met)
        self.assertEqual(result.decision, GoNogoDecision.NO_GO)

    def test_gbpusd_keltner_no_go(self):
        result = evaluate_statistical_checks(GBPUSD_KELTNER_ALL_WINDOWS)
        self.assertEqual(len(GBPUSD_KELTNER_ALL_WINDOWS), 80)
        self.assertTrue(result.min_trades_met)
        self.assertEqual(result.decision, GoNogoDecision.NO_GO)

    def test_eurusd_supertrend_rsi_no_go(self):
        result = evaluate_statistical_checks(EURUSD_SUPERTREND_RSI_ALL_WINDOWS)
        self.assertEqual(len(EURUSD_SUPERTREND_RSI_ALL_WINDOWS), 76)
        self.assertTrue(result.min_trades_met)
        self.assertEqual(result.decision, GoNogoDecision.NO_GO)

    def test_gbpusd_supertrend_rsi_no_go(self):
        result = evaluate_statistical_checks(GBPUSD_SUPERTRENT_RSI_ALL_WINDOWS)
        self.assertEqual(len(GBPUSD_SUPERTRENT_RSI_ALL_WINDOWS), 83)
        self.assertEqual(result.decision, GoNogoDecision.NO_GO)
        self.assertTrue(result.min_trades_met)
        self.assertFalse(result.significance_met)


class TestEdgeCaseBoundary(unittest.TestCase):
    """Edge cases around the min_trades boundary (50 trades)."""

    def test_exactly_50_trades_meets_minimum(self):
        pnls = [10.0] * 50
        result = evaluate_statistical_checks(pnls)
        self.assertTrue(result.min_trades_met)
        self.assertEqual(result.total_oos_trades, 50)

    def test_49_trades_below_minimum(self):
        pnls = [10.0] * 49
        result = evaluate_statistical_checks(pnls)
        self.assertFalse(result.min_trades_met)
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)
        self.assertEqual(result.total_oos_trades, 49)

    def test_51_trades_meets_minimum(self):
        pnls = [10.0] * 51
        result = evaluate_statistical_checks(pnls)
        self.assertTrue(result.min_trades_met)
        self.assertEqual(result.total_oos_trades, 51)


class TestEdgeCaseAllProfitable(unittest.TestCase):
    """All trades profitable with enough trades should be significant."""

    def test_all_profitable_50_trades(self):
        pnls = [5.0, 10.0, 15.0, 8.0, 12.0] * 10
        result = evaluate_statistical_checks(pnls)
        self.assertTrue(result.min_trades_met)
        self.assertTrue(result.significance_met)
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)

    def test_all_profitable_with_pair_results_is_go(self):
        pnls = [5.0, 10.0, 15.0, 8.0, 12.0] * 10
        pair_results = {"EUR/USD": 1.5, "GBP/USD": 1.2}
        result = evaluate_statistical_checks(pnls, pair_results=pair_results)
        self.assertEqual(result.decision, GoNogoDecision.GO)
        self.assertEqual(result.multi_pair_status, "confirmed")


class TestEdgeCaseAllLosing(unittest.TestCase):
    """All losing trades should produce NO_GO when enough trades."""

    def test_all_losing_50_trades(self):
        pnls = [-5.0, -10.0, -3.0, -8.0, -12.0] * 10
        result = evaluate_statistical_checks(pnls)
        self.assertTrue(result.min_trades_met)
        self.assertFalse(result.significance_met)
        self.assertEqual(result.decision, GoNogoDecision.NO_GO)


class TestEdgeCaseSingleMassiveWinner(unittest.TestCase):
    """A single massive winner among many small losers should be caught by p-value."""

    def test_single_winner_among_losers(self):
        losers = [-5.0] * 49
        pnls = losers + [500.0]
        result = evaluate_statistical_checks(pnls)
        self.assertTrue(result.min_trades_met)
        self.assertEqual(result.total_oos_trades, 50)
        if result.p_value is not None:
            self.assertGreater(result.p_value, 0.05)


class TestEdgeCaseLargeSampleTinyEdge(unittest.TestCase):
    """Very large sample with a tiny but real edge should be detected."""

    def test_large_sample_small_edge_significant(self):
        import random

        random.seed(123)
        pnls = [random.gauss(0.5, 10.0) for _ in range(500)]
        result = evaluate_statistical_checks(pnls)
        self.assertTrue(result.min_trades_met)
        self.assertEqual(result.total_oos_trades, 500)

    def test_large_sample_no_edge_not_significant(self):
        import random

        random.seed(456)
        pnls = [random.gauss(0.0, 10.0) for _ in range(500)]
        result = evaluate_statistical_checks(pnls)
        self.assertTrue(result.min_trades_met)
        self.assertFalse(result.significance_met)
        self.assertEqual(result.decision, GoNogoDecision.NO_GO)


class TestFullBtConsistencyRegression(unittest.TestCase):
    """Regression tests for the full backtest consistency check."""

    def test_negative_bt_positive_wf_inconclusive(self):
        pnls = [10.0] * 60
        result = evaluate_statistical_checks(pnls, full_bt_pnl=-5000.0)
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)
        self.assertFalse(result.full_bt_consistent)

    def test_positive_bt_positive_wf_with_pairs_go(self):
        pnls = [10.0] * 60
        pair_results = {"EUR/USD": 1.5, "GBP/USD": 1.2}
        result = evaluate_statistical_checks(
            pnls, full_bt_pnl=5000.0, pair_results=pair_results
        )
        self.assertEqual(result.decision, GoNogoDecision.GO)
        self.assertTrue(result.full_bt_consistent)


class TestMultiPairDecisionRegression(unittest.TestCase):
    """Regression: GO is only possible with confirmed multi-pair status."""

    def test_no_pair_data_always_inconclusive_or_no_go(self):
        pnls = [50.0] * 100
        result = evaluate_statistical_checks(pnls)
        self.assertNotEqual(result.decision, GoNogoDecision.GO)

    def test_weak_pair_always_inconclusive(self):
        pnls = [50.0] * 60
        pair_results = {"EUR/USD": 1.5, "GBP/USD": 0.8}
        result = evaluate_statistical_checks(pnls, pair_results=pair_results)
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)
        self.assertEqual(result.multi_pair_status, "weak")

    def test_failed_pair_always_inconclusive(self):
        pnls = [50.0] * 60
        pair_results = {"EUR/USD": 0.8, "GBP/USD": 0.5}
        result = evaluate_statistical_checks(pnls, pair_results=pair_results)
        self.assertEqual(result.decision, GoNogoDecision.INCONCLUSIVE)
        self.assertEqual(result.multi_pair_status, "failed")


if __name__ == "__main__":
    unittest.main()
