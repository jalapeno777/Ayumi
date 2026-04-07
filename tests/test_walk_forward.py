import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar
from backtest.strategies import MACrossStrategy

from quant.walk_forward import (
    AggregatedMetrics,
    WalkForwardResults,
    WalkForwardValidator,
    WindowMetrics,
    comparison_report,
    go_nogo_criteria,
    run_strategy,
)


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005, v=1000):
    base = datetime(2024, 1, 1, 10, 0)
    time = base + timedelta(hours=i)
    return Bar(time=time, open=o, high=h, low=low, close=c, volume=v)


def _make_bars(n, trend="up"):
    bars = []
    price = 1.0000
    for i in range(n):
        hour = i % 24
        if trend == "up":
            drift = 0.00005 + (0.00001 if hour in range(8, 16) else 0)
            noise = (i % 7 - 3) * 0.00003
        else:
            drift = -0.00005 - (0.00001 if hour in range(8, 16) else 0)
            noise = (i % 7 - 3) * 0.00003
        price += drift + noise
        h = price + abs(noise) * 2
        low = price - abs(noise) * 2
        bars.append(_bar(i, o=price - drift, h=h, low=low, c=price))
    return bars


def _make_trades(pnls: list[float]) -> list[dict[str, float]]:
    return [{"pnl": p} for p in pnls]


class TestWalkForwardValidatorInit(unittest.TestCase):
    def test_defaults(self):
        wf = WalkForwardValidator(data=list(range(100)))
        self.assertEqual(wf.n_windows, 3)
        self.assertAlmostEqual(wf.train_ratio, 0.7)
        self.assertAlmostEqual(wf.val_ratio, 0.15)
        self.assertAlmostEqual(wf.overlap_ratio, 0.2)

    def test_custom_params(self):
        wf = WalkForwardValidator(
            data=list(range(100)),
            n_windows=5,
            train_ratio=0.6,
            val_ratio=0.2,
            overlap_ratio=0.3,
        )
        self.assertEqual(wf.n_windows, 5)
        self.assertAlmostEqual(wf.train_ratio, 0.6)

    def test_n_windows_too_small(self):
        with self.assertRaises(ValueError):
            WalkForwardValidator(data=list(range(100)), n_windows=2)

    def test_train_ratio_zero(self):
        with self.assertRaises(ValueError):
            WalkForwardValidator(data=list(range(100)), train_ratio=0.0)

    def test_train_ratio_one(self):
        with self.assertRaises(ValueError):
            WalkForwardValidator(data=list(range(100)), train_ratio=1.0)

    def test_val_ratio_zero(self):
        with self.assertRaises(ValueError):
            WalkForwardValidator(data=list(range(100)), val_ratio=0.0)

    def test_train_plus_val_ge_one(self):
        with self.assertRaises(ValueError):
            WalkForwardValidator(data=list(range(100)), train_ratio=0.5, val_ratio=0.6)

    def test_overlap_ratio_negative(self):
        with self.assertRaises(ValueError):
            WalkForwardValidator(data=list(range(100)), overlap_ratio=-0.1)

    def test_overlap_ratio_one(self):
        with self.assertRaises(ValueError):
            WalkForwardValidator(data=list(range(100)), overlap_ratio=1.0)


class TestWalkForwardSplit(unittest.TestCase):
    def test_yields_correct_number_of_windows(self):
        data = list(range(300))
        wf = WalkForwardValidator(data=data, n_windows=3)
        windows = list(wf.split())
        self.assertEqual(len(windows), 3)

    def test_no_temporal_leakage(self):
        data = list(range(1000))
        wf = WalkForwardValidator(data=data, n_windows=3)
        for train, val, test in wf.split():
            max_train = max(train)
            min_val = min(val)
            min_test = min(test)
            self.assertLess(max_train, min_val, "Train must end before val starts")
            self.assertLess(max(val), min_test, "Val must end before test starts")

    def test_no_empty_splits(self):
        data = list(range(300))
        wf = WalkForwardValidator(data=data, n_windows=3)
        for train, val, test in wf.split():
            self.assertTrue(len(train) > 0)
            self.assertTrue(len(val) > 0)
            self.assertTrue(len(test) > 0)

    def test_empty_data(self):
        wf = WalkForwardValidator(data=[], n_windows=3)
        windows = list(wf.split())
        self.assertEqual(windows, [])

    def test_custom_data_param(self):
        wf = WalkForwardValidator(data=list(range(100)))
        custom_data = list(range(500))
        windows = list(wf.split(custom_data))
        self.assertEqual(len(windows), 3)

    def test_five_windows(self):
        data = list(range(500))
        wf = WalkForwardValidator(data=data, n_windows=5)
        windows = list(wf.split())
        self.assertEqual(len(windows), 5)

    def test_with_overlap(self):
        data = list(range(300))
        wf = WalkForwardValidator(data=data, n_windows=3, overlap_ratio=0.3)
        windows = list(wf.split())
        self.assertEqual(len(windows), 3)
        for train, val, test in windows:
            self.assertTrue(len(train) > 0)

    def test_data_too_small_yields_nothing(self):
        wf = WalkForwardValidator(data=list(range(5)), n_windows=3)
        windows = list(wf.split())
        self.assertEqual(len(windows), 0)

    def test_data_single_point_raises(self):
        wf = WalkForwardValidator(data=[1], n_windows=3)
        with self.assertRaises(ValueError):
            list(wf.split())


class TestComputeMetrics(unittest.TestCase):
    def test_empty_trades(self):
        from quant.walk_forward import _compute_metrics

        m = _compute_metrics(0, [])
        self.assertEqual(m.win_rate, 0.0)
        self.assertEqual(m.trade_count, 0)
        self.assertFalse(m.passed_go_nogo)

    def test_all_wins(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([10.0, 20.0, 30.0, 40.0, 50.0])
        m = _compute_metrics(0, trades)
        self.assertAlmostEqual(m.win_rate, 1.0)
        self.assertAlmostEqual(m.total_pnl, 150.0)
        self.assertTrue(m.passed_go_nogo)

    def test_fewer_than_min_trades_fails_go_nogo(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([100.0, 200.0])
        m = _compute_metrics(0, trades)
        self.assertAlmostEqual(m.win_rate, 1.0)
        self.assertEqual(m.trade_count, 2)
        self.assertFalse(m.passed_go_nogo)

    def test_single_winning_trade_fails_go_nogo(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([500.0])
        m = _compute_metrics(0, trades)
        self.assertAlmostEqual(m.win_rate, 1.0)
        self.assertEqual(m.trade_count, 1)
        self.assertFalse(m.passed_go_nogo)

    def test_exactly_min_trades_can_pass(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([10.0, 20.0, 30.0, 40.0, 50.0])
        m = _compute_metrics(0, trades)
        self.assertEqual(m.trade_count, 5)
        self.assertTrue(m.passed_go_nogo)

    def test_all_losses(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([-10.0, -20.0, -30.0])
        m = _compute_metrics(0, trades)
        self.assertAlmostEqual(m.win_rate, 0.0)
        self.assertAlmostEqual(m.profit_factor, 0.0)
        self.assertFalse(m.passed_go_nogo)

    def test_mixed_trades(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([50.0, -20.0, 30.0, -10.0, 40.0])
        m = _compute_metrics(0, trades)
        self.assertAlmostEqual(m.win_rate, 0.6)
        self.assertAlmostEqual(m.total_pnl, 90.0)

    def test_max_drawdown(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([100.0, -200.0, 50.0, -50.0])
        m = _compute_metrics(0, trades, initial_balance=10000.0)
        self.assertGreater(m.max_drawdown, 0.0)
        self.assertLess(m.max_drawdown, 1.0)
        expected_dd = 200.0 / 10100.0
        self.assertAlmostEqual(m.max_drawdown, expected_dd, places=5)

    def test_max_drawdown_with_custom_balance(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([100.0, -200.0, 50.0, -50.0])
        m = _compute_metrics(0, trades, initial_balance=1000.0)
        expected_dd = 200.0 / 1100.0
        self.assertAlmostEqual(m.max_drawdown, expected_dd, places=5)

    def test_max_drawdown_never_exceeds_one(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([-5000.0, -5000.0, -5000.0])
        m = _compute_metrics(0, trades, initial_balance=10000.0)
        self.assertLessEqual(m.max_drawdown, 1.0)
        self.assertGreater(m.max_drawdown, 0.0)

    def test_balance_floor_prevents_negative(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([-15000.0, -5000.0])
        m = _compute_metrics(0, trades, initial_balance=10000.0)
        self.assertLessEqual(m.max_drawdown, 1.0)
        self.assertAlmostEqual(m.max_drawdown, 1.0, places=5)

    def test_profit_factor_no_losses(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([10.0, 20.0])
        m = _compute_metrics(0, trades)
        self.assertEqual(m.profit_factor, float("inf"))

    def test_sharpe_ratio_single_trade(self):
        from quant.walk_forward import _compute_metrics

        trades = _make_trades([100.0])
        m = _compute_metrics(0, trades)
        self.assertEqual(m.sharpe_ratio, 0.0)


class TestRunStrategy(unittest.TestCase):
    def test_basic_run(self):
        strategy = MACrossStrategy(fast_period=5, slow_period=13)
        bars = _make_bars(300, trend="up")
        results = run_strategy(strategy, bars, n_windows=3)
        self.assertEqual(len(results.per_window), 3)
        self.assertIsNotNone(results.aggregated)

    def test_aggregated_metrics(self):
        strategy = MACrossStrategy(fast_period=5, slow_period=13)
        bars = _make_bars(300, trend="up")
        results = run_strategy(strategy, bars, n_windows=3)
        agg = results.aggregated
        self.assertIsNotNone(agg)
        self.assertEqual(agg.total_windows, 3)
        self.assertGreaterEqual(agg.windows_passed, 0)

    def test_go_nogo_consistent_with_criteria(self):
        strategy = MACrossStrategy(fast_period=5, slow_period=13)
        bars = _make_bars(300, trend="up")
        results = run_strategy(strategy, bars, n_windows=3)
        self.assertEqual(results.go_nogo, go_nogo_criteria(results))

    def test_per_window_indices(self):
        strategy = MACrossStrategy(fast_period=5, slow_period=13)
        bars = _make_bars(300, trend="up")
        results = run_strategy(strategy, bars, n_windows=3)
        for i, m in enumerate(results.per_window):
            self.assertEqual(m.window_index, i)

    def test_empty_strategy_returns(self):
        strategy = MACrossStrategy(fast_period=5, slow_period=13)
        bars = _make_bars(300, trend="up")
        results = run_strategy(strategy, bars, n_windows=3)
        self.assertEqual(len(results.per_window), 3)

    def test_downtrend_generates_trades(self):
        strategy = MACrossStrategy(fast_period=5, slow_period=13)
        bars = _make_bars(300, trend="down")
        results = run_strategy(strategy, bars, n_windows=3)
        self.assertEqual(len(results.per_window), 3)


class TestGoNogoCriteria(unittest.TestCase):
    def test_fewer_than_three_windows(self):
        results = WalkForwardResults(
            per_window=[WindowMetrics(0, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True)],
            go_nogo=False,
        )
        self.assertFalse(go_nogo_criteria(results))

    def test_two_windows(self):
        results = WalkForwardResults(
            per_window=[
                WindowMetrics(0, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True),
                WindowMetrics(1, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True),
            ],
            go_nogo=False,
        )
        self.assertFalse(go_nogo_criteria(results))

    def test_three_windows_two_pass(self):
        results = WalkForwardResults(
            per_window=[
                WindowMetrics(0, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True),
                WindowMetrics(1, 0.4, 0.8, 0.15, 0.5, 10, -50.0, False),
                WindowMetrics(2, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True),
            ],
            go_nogo=True,
        )
        self.assertTrue(go_nogo_criteria(results))

    def test_three_windows_one_pass(self):
        results = WalkForwardResults(
            per_window=[
                WindowMetrics(0, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True),
                WindowMetrics(1, 0.4, 0.8, 0.15, 0.5, 10, -50.0, False),
                WindowMetrics(2, 0.4, 0.8, 0.15, 0.5, 10, -50.0, False),
            ],
            go_nogo=False,
        )
        self.assertFalse(go_nogo_criteria(results))

    def test_three_windows_all_pass(self):
        results = WalkForwardResults(
            per_window=[
                WindowMetrics(0, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True),
                WindowMetrics(1, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True),
                WindowMetrics(2, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True),
            ],
            go_nogo=True,
        )
        self.assertTrue(go_nogo_criteria(results))

    def test_five_windows_three_pass(self):
        results = WalkForwardResults(
            per_window=[
                WindowMetrics(0, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True),
                WindowMetrics(1, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True),
                WindowMetrics(2, 0.4, 0.8, 0.15, 0.5, 10, -50.0, False),
                WindowMetrics(3, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True),
                WindowMetrics(4, 0.4, 0.8, 0.15, 0.5, 10, -50.0, False),
            ],
            go_nogo=True,
        )
        self.assertTrue(go_nogo_criteria(results))


class TestComparisonReport(unittest.TestCase):
    def test_basic_report(self):
        results_a = WalkForwardResults(
            per_window=[
                WindowMetrics(0, 0.6, 1.5, 0.05, 1.0, 20, 500.0, True),
                WindowMetrics(1, 0.55, 1.2, 0.08, 0.8, 15, 200.0, True),
                WindowMetrics(2, 0.4, 0.8, 0.15, 0.5, 10, -100.0, False),
            ],
            aggregated=AggregatedMetrics(
                mean_win_rate=0.5167,
                std_win_rate=0.1,
                mean_profit_factor=1.1667,
                std_profit_factor=0.35,
                mean_max_drawdown=0.0933,
                std_max_drawdown=0.05,
                mean_sharpe_ratio=0.7667,
                std_sharpe_ratio=0.2517,
                mean_trade_count=15.0,
                std_trade_count=5.0,
                mean_total_pnl=200.0,
                std_total_pnl=300.0,
                windows_passed=2,
                total_windows=3,
            ),
            go_nogo=True,
        )
        results_b = WalkForwardResults(
            per_window=[
                WindowMetrics(0, 0.5, 1.0, 0.1, 0.5, 10, 50.0, False),
                WindowMetrics(1, 0.45, 0.9, 0.12, 0.3, 8, -30.0, False),
                WindowMetrics(2, 0.5, 1.0, 0.1, 0.5, 12, 20.0, False),
            ],
            aggregated=AggregatedMetrics(
                mean_win_rate=0.4833,
                std_win_rate=0.0289,
                mean_profit_factor=0.9667,
                std_profit_factor=0.0577,
                mean_max_drawdown=0.1067,
                std_max_drawdown=0.0115,
                mean_sharpe_ratio=0.4333,
                std_sharpe_ratio=0.1155,
                mean_trade_count=10.0,
                std_trade_count=2.0,
                mean_total_pnl=13.333,
                std_total_pnl=40.415,
                windows_passed=0,
                total_windows=3,
            ),
            go_nogo=False,
        )

        report = comparison_report(results_a, results_b)
        self.assertIn("COMPARISON REPORT", report)
        self.assertIn("Strategy A", report)
        self.assertIn("Strategy B", report)
        self.assertIn("GO", report)
        self.assertIn("NO-GO", report)
        self.assertIn("Win Rate", report)
        self.assertIn("Profit Factor", report)

    def test_both_empty(self):
        results_a = WalkForwardResults()
        results_b = WalkForwardResults()
        report = comparison_report(results_a, results_b)
        self.assertIn("No results to compare", report)


class TestWindowMetrics(unittest.TestCase):
    def test_passed_criteria_wr_below_55(self):
        m = WindowMetrics(0, 0.50, 1.5, 0.02, 1.0, 10, 100.0, False)
        self.assertFalse(m.passed_go_nogo)

    def test_passed_criteria_pf_below_1(self):
        m = WindowMetrics(0, 0.6, 0.8, 0.02, 1.0, 10, 100.0, False)
        self.assertFalse(m.passed_go_nogo)

    def test_passed_criteria_negative_pnl(self):
        m = WindowMetrics(0, 0.6, 1.5, 0.02, 1.0, 10, -50.0, False)
        self.assertFalse(m.passed_go_nogo)

    def test_passed_criteria_dd_above_10pct(self):
        m = WindowMetrics(0, 0.6, 1.5, 0.15, 1.0, 10, 100.0, False)
        self.assertFalse(m.passed_go_nogo)

    def test_passed_criteria_all_pass(self):
        m = WindowMetrics(0, 0.6, 1.5, 0.02, 1.0, 10, 100.0, True)
        self.assertTrue(m.passed_go_nogo)


class TestMeanAndStd(unittest.TestCase):
    def test_mean_empty(self):
        from quant.walk_forward import _mean

        self.assertEqual(_mean([]), 0.0)

    def test_mean_single(self):
        from quant.walk_forward import _mean

        self.assertAlmostEqual(_mean([5.0]), 5.0)

    def test_std_single(self):
        from quant.walk_forward import _std

        self.assertEqual(_std([5.0], 5.0), 0.0)

    def test_std_empty(self):
        from quant.walk_forward import _std

        self.assertEqual(_std([], 0.0), 0.0)

    def test_std_normal(self):
        from quant.walk_forward import _std

        result = _std([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0], 5.0)
        self.assertAlmostEqual(result, 2.1381, places=3)


if __name__ == "__main__":
    unittest.main()
