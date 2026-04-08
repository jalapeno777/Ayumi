import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from backtest.engine import Bar
from backtest.parameter_sweep.optuna_optimizer import (
    OptunaOptimizer,
    OptimizationResult,
    SearchSpace,
    WalkForwardObjective,
    categorical,
    float_range,
    int_range,
    session_range_mr_search_space,
)
from quant.walk_forward import (
    AggregatedMetrics,
    WalkForwardResults,
    WindowMetrics,
)


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005, v=1000):
    base = datetime(2024, 1, 1, 10, 0)
    time = base + timedelta(hours=i)
    return Bar(time=time, open=o, high=h, low=low, close=c, volume=v)


def _make_bars(n=500):
    bars = []
    price = 1.0000
    for i in range(n):
        drift = 0.00005
        noise = (i % 7 - 3) * 0.00003
        price += drift + noise
        h = price + abs(noise) * 2
        low = price - abs(noise) * 2
        bars.append(_bar(i, o=price - drift, h=h, low=low, c=price))
    return bars


def _mock_walk_forward_results(
    win_rate=0.6,
    profit_factor=1.5,
    max_drawdown=0.05,
    sharpe_ratio=1.0,
    trade_count=20.0,
    total_pnl=500.0,
    windows_passed=3,
    total_windows=5,
    go_nogo=True,
):
    windows = []
    for i in range(total_windows):
        passed = i < windows_passed
        windows.append(
            WindowMetrics(
                window_index=i,
                win_rate=win_rate if passed else 0.4,
                profit_factor=profit_factor if passed else 0.8,
                max_drawdown=max_drawdown if passed else 0.15,
                sharpe_ratio=sharpe_ratio if passed else 0.3,
                trade_count=int(trade_count) if passed else 5,
                total_pnl=total_pnl / total_windows if passed else -100,
                passed_go_nogo=passed,
            )
        )
    agg = AggregatedMetrics(
        mean_win_rate=win_rate,
        std_win_rate=0.05,
        mean_profit_factor=profit_factor,
        std_profit_factor=0.3,
        mean_max_drawdown=max_drawdown,
        std_max_drawdown=0.02,
        mean_sharpe_ratio=sharpe_ratio,
        std_sharpe_ratio=0.2,
        mean_trade_count=trade_count,
        std_trade_count=5.0,
        mean_total_pnl=total_pnl,
        std_total_pnl=100.0,
        windows_passed=windows_passed,
        total_windows=total_windows,
    )
    return WalkForwardResults(per_window=windows, aggregated=agg, go_nogo=go_nogo)


class TestSearchSpaceHelpers(unittest.TestCase):
    def test_int_range_spec(self):
        spec = int_range("period", 5, 20)
        self.assertEqual(spec["type"], "int")
        self.assertEqual(spec["low"], 5)
        self.assertEqual(spec["high"], 20)
        self.assertEqual(spec["step"], 1)

    def test_int_range_with_step(self):
        spec = int_range("period", 5, 20, step=5)
        self.assertEqual(spec["step"], 5)

    def test_float_range_spec(self):
        spec = float_range("multiplier", 0.5, 3.0, step=0.1)
        self.assertEqual(spec["type"], "float")
        self.assertEqual(spec["low"], 0.5)
        self.assertEqual(spec["high"], 3.0)
        self.assertEqual(spec["step"], 0.1)

    def test_float_range_log(self):
        spec = float_range("lr", 1e-5, 1e-1, log=True)
        self.assertTrue(spec["log"])
        self.assertNotIn("step", spec)

    def test_categorical_spec(self):
        spec = categorical("method", ["a", "b", "c"])
        self.assertEqual(spec["type"], "categorical")
        self.assertEqual(spec["choices"], ["a", "b", "c"])

    def test_invalid_spec_raises(self):
        with self.assertRaises(ValueError):
            SearchSpace(bad_param={"not_type": "int", "low": 1, "high": 10})


class TestSearchSpace(unittest.TestCase):
    def test_create_search_space(self):
        space = SearchSpace(
            period=int_range("period", 5, 20),
            mult=float_range("mult", 0.5, 3.0),
        )
        self.assertEqual(space.param_names, ["mult", "period"])

    def test_session_range_mr_search_space(self):
        space = session_range_mr_search_space()
        self.assertIn("atr_period", space.param_names)
        self.assertIn("rsi_period", space.param_names)
        self.assertIn("tp1_rr", space.param_names)
        self.assertIn("ema_trend_period", space.param_names)
        self.assertEqual(len(space.param_names), 13)

    def test_suggest_with_mock_trial(self):
        space = SearchSpace(
            fast=int_range("fast", 5, 10),
            slow=int_range("slow", 13, 26),
        )
        trial = MagicMock()
        trial.suggest_int.side_effect = [7, 20]
        params = space.suggest(trial)
        self.assertEqual(params, {"fast": 7, "slow": 20})
        self.assertEqual(trial.suggest_int.call_count, 2)

    def test_suggest_categorical(self):
        space = SearchSpace(
            method=categorical("method", ["a", "b"]),
        )
        trial = MagicMock()
        trial.suggest_categorical.return_value = "b"
        params = space.suggest(trial)
        self.assertEqual(params, {"method": "b"})

    def test_suggest_float(self):
        space = SearchSpace(
            mult=float_range("mult", 0.5, 3.0, step=0.1),
        )
        trial = MagicMock()
        trial.suggest_float.return_value = 2.0
        params = space.suggest(trial)
        self.assertEqual(params, {"mult": 2.0})

    def test_suggest_with_prefix(self):
        space = SearchSpace(
            period=int_range("period", 5, 20),
        )
        trial = MagicMock()
        trial.suggest_int.return_value = 10
        params = space.suggest(trial, prefix="strategy_")
        self.assertEqual(params, {"period": 10})
        trial.suggest_int.assert_called_once_with(
            "strategy_period", 5, 20, step=1, log=False
        )

    def test_unknown_type_raises(self):
        space = SearchSpace(
            bad={"type": "unknown", "low": 1, "high": 10},
        )
        trial = MagicMock()
        with self.assertRaises(ValueError):
            space.suggest(trial)


class TestWalkForwardObjective(unittest.TestCase):
    def test_composite_score_weights_default(self):
        bars = _make_bars(500)
        obj = WalkForwardObjective(
            bars=bars,
            strategy_factory=lambda p: MagicMock(),
            pair="GBPUSD",
            search_space=session_range_mr_search_space(),
        )
        agg = AggregatedMetrics(
            mean_win_rate=0.6,
            std_win_rate=0.05,
            mean_profit_factor=1.5,
            std_profit_factor=0.3,
            mean_max_drawdown=0.05,
            std_max_drawdown=0.02,
            mean_sharpe_ratio=1.0,
            std_sharpe_ratio=0.2,
            mean_trade_count=20.0,
            std_trade_count=5.0,
            mean_total_pnl=500.0,
            std_total_pnl=100.0,
            windows_passed=3,
            total_windows=5,
        )
        score = obj._composite_score(agg)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_composite_score_custom_weights(self):
        bars = _make_bars(500)
        obj = WalkForwardObjective(
            bars=bars,
            strategy_factory=lambda p: MagicMock(),
            pair="GBPUSD",
            search_space=session_range_mr_search_space(),
            composite_weights={"win_rate": 1.0},
        )
        agg = AggregatedMetrics(
            mean_win_rate=0.7,
            std_win_rate=0.0,
            mean_profit_factor=0.0,
            std_profit_factor=0.0,
            mean_max_drawdown=0.0,
            std_max_drawdown=0.0,
            mean_sharpe_ratio=0.0,
            std_sharpe_ratio=0.0,
            mean_trade_count=10.0,
            std_trade_count=0.0,
            mean_total_pnl=0.0,
            std_total_pnl=0.0,
            windows_passed=3,
            total_windows=5,
        )
        score = obj._composite_score(agg)
        self.assertAlmostEqual(score, 0.7)

    def test_pruned_on_no_aggregation(self):
        bars = _make_bars(500)
        obj = WalkForwardObjective(
            bars=bars,
            strategy_factory=lambda p: MagicMock(),
            pair="GBPUSD",
            search_space=session_range_mr_search_space(),
        )
        no_agg_result = WalkForwardResults(
            per_window=[], aggregated=None, go_nogo=False
        )
        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=no_agg_result,
        ):
            import optuna

            study = optuna.create_study(direction="maximize")
            trial = study.ask()
            with self.assertRaises(optuna.TrialPruned):
                obj(trial)

    def test_pruned_on_exception(self):
        bars = _make_bars(500)
        obj = WalkForwardObjective(
            bars=bars,
            strategy_factory=lambda p: MagicMock(),
            pair="GBPUSD",
            search_space=session_range_mr_search_space(),
        )
        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            side_effect=ValueError("test error"),
        ):
            import optuna

            study = optuna.create_study(direction="maximize")
            trial = study.ask()
            with self.assertRaises(optuna.TrialPruned):
                obj(trial)

    def test_pruned_on_low_trade_count(self):
        bars = _make_bars(500)
        obj = WalkForwardObjective(
            bars=bars,
            strategy_factory=lambda p: MagicMock(),
            pair="GBPUSD",
            search_space=session_range_mr_search_space(),
        )
        low_trade_result = _mock_walk_forward_results(trade_count=2.0)
        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=low_trade_result,
        ):
            import optuna

            study = optuna.create_study(direction="maximize")
            trial = study.ask()
            with self.assertRaises(optuna.TrialPruned):
                obj(trial)

    def test_go_nogo_penalty(self):
        bars = _make_bars(500)
        obj = WalkForwardObjective(
            bars=bars,
            strategy_factory=lambda p: MagicMock(),
            pair="GBPUSD",
            search_space=session_range_mr_search_space(),
        )
        go_result = _mock_walk_forward_results(go_nogo=True)
        no_go_result = _mock_walk_forward_results(go_nogo=False)

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=go_result,
        ):
            import optuna

            study_go = optuna.create_study(direction="maximize")
            trial_go = study_go.ask()
            score_go = obj(trial_go)

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=no_go_result,
        ):
            study_no_go = optuna.create_study(direction="maximize")
            trial_no_go = study_no_go.ask()
            score_no_go = obj(trial_no_go)

        self.assertAlmostEqual(score_no_go, score_go - 1.0, places=5)

    def test_custom_weights_validation(self):
        bars = _make_bars(500)
        with self.assertRaises(ValueError):
            WalkForwardObjective(
                bars=bars,
                strategy_factory=lambda p: MagicMock(),
                pair="GBPUSD",
                search_space=session_range_mr_search_space(),
                composite_weights={"win_rate": 0.5, "profit_factor": 0.6},
            )


class TestOptimizationResult(unittest.TestCase):
    def test_default_fields(self):
        result = OptimizationResult(
            best_params={"atr_period": 14},
            best_value=0.75,
        )
        self.assertEqual(result.best_params, {"atr_period": 14})
        self.assertEqual(result.best_value, 0.75)
        self.assertIsNone(result.best_walk_forward)
        self.assertEqual(result.n_trials, 0)
        self.assertFalse(result.go_nogo)
        self.assertEqual(result.study_summary, {})

    def test_with_walk_forward(self):
        wf = _mock_walk_forward_results()
        result = OptimizationResult(
            best_params={"atr_period": 14},
            best_value=0.75,
            best_walk_forward=wf,
            n_trials=50,
            go_nogo=True,
        )
        self.assertTrue(result.go_nogo)
        self.assertEqual(result.n_trials, 50)
        self.assertIsNotNone(result.best_walk_forward)


class TestOptunaOptimizer(unittest.TestCase):
    def test_objective_accessible(self):
        bars = _make_bars(500)
        optimizer = OptunaOptimizer(
            bars=bars,
            strategy_factory=lambda p: MagicMock(),
            pair="GBPUSD",
            search_space=session_range_mr_search_space(),
            n_trials=5,
        )
        self.assertIsInstance(optimizer.objective, WalkForwardObjective)

    def test_optimize_with_mock(self):
        bars = _make_bars(500)
        wf_result = _mock_walk_forward_results()

        optimizer = OptunaOptimizer(
            bars=bars,
            strategy_factory=lambda p: MagicMock(),
            pair="GBPUSD",
            search_space=SearchSpace(
                period=int_range("period", 5, 20),
            ),
            n_trials=3,
        )

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=wf_result,
        ):
            result = optimizer.optimize()

        self.assertIsInstance(result, OptimizationResult)
        self.assertIn("period", result.best_params)
        self.assertTrue(result.go_nogo)
        self.assertGreater(result.n_trials, 0)

    def test_optimize_pruned_trials(self):
        bars = _make_bars(500)
        no_agg_result = WalkForwardResults(
            per_window=[], aggregated=None, go_nogo=False
        )

        optimizer = OptunaOptimizer(
            bars=bars,
            strategy_factory=lambda p: MagicMock(),
            pair="GBPUSD",
            search_space=SearchSpace(
                period=int_range("period", 5, 20),
            ),
            n_trials=3,
        )

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=no_agg_result,
        ):
            result = optimizer.optimize()

        self.assertIsInstance(result, OptimizationResult)
        self.assertGreater(result.n_trials, 0)
        self.assertFalse(result.go_nogo)
        self.assertEqual(result.study_summary["n_complete"], 0)

    def test_optimize_custom_direction(self):
        bars = _make_bars(500)
        wf_result = _mock_walk_forward_results()

        optimizer = OptunaOptimizer(
            bars=bars,
            strategy_factory=lambda p: MagicMock(),
            pair="GBPUSD",
            search_space=SearchSpace(
                period=int_range("period", 5, 20),
            ),
            n_trials=2,
            direction="maximize",
        )

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=wf_result,
        ):
            result = optimizer.optimize()

        self.assertIsInstance(result, OptimizationResult)


class TestIntegration(unittest.TestCase):
    def test_full_flow_with_minimal_data(self):
        bars = _make_bars(500)
        wf_result = _mock_walk_forward_results(win_rate=0.65, profit_factor=1.8)

        space = SearchSpace(
            fast=int_range("fast", 5, 10),
            slow=int_range("slow", 13, 26),
        )

        optimizer = OptunaOptimizer(
            bars=bars,
            strategy_factory=lambda p: MagicMock(name=str(p)),
            pair="GBPUSD",
            search_space=space,
            n_trials=3,
        )

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=wf_result,
        ):
            result = optimizer.optimize()

        self.assertTrue(result.go_nogo)
        self.assertIn("fast", result.best_params)
        self.assertIn("slow", result.best_params)
        self.assertEqual(result.study_summary["n_trials"], 3)


if __name__ == "__main__":
    unittest.main()
