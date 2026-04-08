import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from backtest.engine import Bar
from backtest.parameter_sweep.optuna_optimizer import (
    OptimizationResult,
    OptunaOptimizer,
    SearchSpace,
    WalkForwardObjective,
    volatility_squeeze_search_space,
)
from quant.walk_forward import (
    AggregatedMetrics,
    WalkForwardResults,
    WindowMetrics,
)


def _bar(i, o=148.0, h=148.5, low=147.5, c=148.25, v=1000):
    base = datetime(2024, 1, 1, 10, 0)
    time = base + timedelta(hours=i)
    return Bar(time=time, open=o, high=h, low=low, close=c, volume=v)


def _make_usdjpy_bars(n=500):
    bars = []
    price = 148.00
    for i in range(n):
        drift = 0.005
        noise = (i % 7 - 3) * 0.003
        price += drift + noise
        h = price + abs(noise) * 2
        low = price - abs(noise) * 2
        bars.append(_bar(i, o=price - drift, h=h, low=low, c=price))
    return bars


def _mock_walk_forward_results(
    win_rate=0.65,
    profit_factor=1.8,
    max_drawdown=0.04,
    sharpe_ratio=1.5,
    trade_count=15.0,
    total_pnl=800.0,
    windows_passed=4,
    total_windows=5,
    go_nogo=True,
):
    windows = []
    for i in range(total_windows):
        passed = i < windows_passed
        windows.append(
            WindowMetrics(
                window_index=i,
                win_rate=win_rate if passed else 0.45,
                profit_factor=profit_factor if passed else 0.9,
                max_drawdown=max_drawdown if passed else 0.12,
                sharpe_ratio=sharpe_ratio if passed else 0.4,
                trade_count=int(trade_count) if passed else 5,
                total_pnl=total_pnl / total_windows if passed else -50,
                passed_go_nogo=passed,
            )
        )
    agg = AggregatedMetrics(
        mean_win_rate=win_rate,
        std_win_rate=0.04,
        mean_profit_factor=profit_factor,
        std_profit_factor=0.25,
        mean_max_drawdown=max_drawdown,
        std_max_drawdown=0.01,
        mean_sharpe_ratio=sharpe_ratio,
        std_sharpe_ratio=0.15,
        mean_trade_count=trade_count,
        std_trade_count=4.0,
        mean_total_pnl=total_pnl,
        std_total_pnl=80.0,
        windows_passed=windows_passed,
        total_windows=total_windows,
    )
    return WalkForwardResults(
        per_window=windows,
        aggregated=agg,
        go_nogo=go_nogo,
    )


class TestVolatilitySqueezeSearchSpace(unittest.TestCase):
    def test_search_space_returns_search_space_instance(self):
        ss = volatility_squeeze_search_space()
        self.assertIsInstance(ss, SearchSpace)

    def test_search_space_has_all_config_params(self):
        ss = volatility_squeeze_search_space()
        expected_params = {
            "bb_period", "bb_std_dev", "kc_period", "kc_atr_multiplier",
            "min_squeeze_bars", "ema_period",
            "adx_period", "adx_min", "atr_period", "atr_sl_multiplier",
            "tp1_rr", "tp2_rr", "tp3_rr", "session_filter",
            "min_confidence", "squeeze_release_mode",
        }
        self.assertEqual(set(ss.param_names), expected_params)

    def test_search_space_param_count(self):
        ss = volatility_squeeze_search_space()
        self.assertEqual(len(ss.param_names), 16)

    def test_int_params_have_valid_ranges(self):
        import optuna
        ss = volatility_squeeze_search_space()
        study = optuna.create_study(direction="maximize")
        trial = study.ask()
        params = ss.suggest(trial)
        int_params = ["bb_period", "kc_period", "min_squeeze_bars", "ema_period",
                       "adx_period", "atr_period"]
        for param in int_params:
            self.assertIsInstance(params[param], int)
            self.assertGreaterEqual(params[param], 1)

    def test_float_params_have_valid_ranges(self):
        import optuna
        ss = volatility_squeeze_search_space()
        study = optuna.create_study(direction="maximize")
        trial = study.ask()
        params = ss.suggest(trial)
        float_params = ["bb_std_dev", "kc_atr_multiplier", "atr_sl_multiplier",
                         "tp1_rr", "tp2_rr", "tp3_rr", "adx_min", "min_confidence"]
        for param in float_params:
            self.assertIsInstance(params[param], float)

    def test_categorical_params_have_valid_choices(self):
        import optuna
        ss = volatility_squeeze_search_space()
        study = optuna.create_study(direction="maximize")
        trial = study.ask()
        params = ss.suggest(trial)
        self.assertEqual(params["session_filter"], False)
        self.assertIn(params["squeeze_release_mode"], ["loose", "moderate"])

    def test_params_can_construct_config(self):
        from strategies.volatility_squeeze import VolatilitySqueezeConfig
        ss = volatility_squeeze_search_space()
        mock_trial = MagicMock()
        mock_trial.suggest_int = lambda k, low, h, step=1, log=False: low
        mock_trial.suggest_float = lambda k, low, h, step=None, log=False: low if step is None else low
        mock_trial.suggest_categorical = lambda k, v: v[0]
        params = ss.suggest(mock_trial)
        config = VolatilitySqueezeConfig(**params)
        self.assertIsInstance(config, VolatilitySqueezeConfig)


class TestVolatilitySqueezeOptunaOptimizer(unittest.TestCase):
    def test_optimizer_creates_study(self):
        bars = _make_usdjpy_bars(200)
        ss = volatility_squeeze_search_space()
        wf_result = _mock_walk_forward_results()

        def make_strategy(params):
            from strategies.volatility_squeeze import VolatilitySqueezeStrategy, VolatilitySqueezeConfig
            return VolatilitySqueezeStrategy(config=VolatilitySqueezeConfig(**params))

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=wf_result,
        ):
            optimizer = OptunaOptimizer(
                bars=bars,
                strategy_factory=make_strategy,
                pair="USDJPY",
                search_space=ss,
                n_trials=3,
                seed=42,
            )
            result = optimizer.optimize()

        self.assertIsInstance(result, OptimizationResult)
        self.assertEqual(result.n_trials, 3)
        self.assertIsInstance(result.best_params, dict)

    def test_optimizer_returns_best_params_with_go_nogo(self):
        bars = _make_usdjpy_bars(200)
        ss = volatility_squeeze_search_space()
        wf_result = _mock_walk_forward_results(go_nogo=True)

        def make_strategy(params):
            from strategies.volatility_squeeze import VolatilitySqueezeStrategy, VolatilitySqueezeConfig
            return VolatilitySqueezeStrategy(config=VolatilitySqueezeConfig(**params))

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=wf_result,
        ):
            optimizer = OptunaOptimizer(
                bars=bars,
                strategy_factory=make_strategy,
                pair="USDJPY",
                search_space=ss,
                n_trials=5,
                seed=42,
            )
            result = optimizer.optimize()

        self.assertTrue(result.go_nogo)
        self.assertIn("bb_period", result.best_params)
        self.assertIn("kc_atr_multiplier", result.best_params)

    def test_optimizer_with_no_go_result(self):
        bars = _make_usdjpy_bars(200)
        ss = volatility_squeeze_search_space()
        wf_result = _mock_walk_forward_results(
            win_rate=0.40, profit_factor=0.8, go_nogo=False, windows_passed=1
        )

        def make_strategy(params):
            from strategies.volatility_squeeze import VolatilitySqueezeStrategy, VolatilitySqueezeConfig
            return VolatilitySqueezeStrategy(config=VolatilitySqueezeConfig(**params))

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=wf_result,
        ):
            optimizer = OptunaOptimizer(
                bars=bars,
                strategy_factory=make_strategy,
                pair="USDJPY",
                search_space=ss,
                n_trials=3,
                seed=42,
            )
            result = optimizer.optimize()

        self.assertFalse(result.go_nogo)

    def test_study_summary_has_expected_keys(self):
        bars = _make_usdjpy_bars(200)
        ss = volatility_squeeze_search_space()
        wf_result = _mock_walk_forward_results()

        def make_strategy(params):
            from strategies.volatility_squeeze import VolatilitySqueezeStrategy, VolatilitySqueezeConfig
            return VolatilitySqueezeStrategy(config=VolatilitySqueezeConfig(**params))

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=wf_result,
        ):
            optimizer = OptunaOptimizer(
                bars=bars,
                strategy_factory=make_strategy,
                pair="USDJPY",
                search_space=ss,
                n_trials=3,
                seed=42,
            )
            result = optimizer.optimize()

        self.assertIn("n_trials", result.study_summary)
        self.assertIn("n_complete", result.study_summary)
        self.assertIn("n_pruned", result.study_summary)
        self.assertIn("sampler", result.study_summary)


class TestVolatilitySqueezeObjectivePruning(unittest.TestCase):
    def test_pruned_on_no_aggregation(self):
        import optuna
        bars = _make_usdjpy_bars(200)
        ss = volatility_squeeze_search_space()

        def make_strategy(params):
            from strategies.volatility_squeeze import VolatilitySqueezeStrategy, VolatilitySqueezeConfig
            return VolatilitySqueezeStrategy(config=VolatilitySqueezeConfig(**params))

        no_agg_result = WalkForwardResults(
            per_window=[], aggregated=None, go_nogo=False
        )

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=no_agg_result,
        ):
            obj = WalkForwardObjective(
                bars=bars,
                strategy_factory=make_strategy,
                pair="USDJPY",
                search_space=ss,
            )
            study = optuna.create_study(direction="maximize")
            trial = study.ask()
            with self.assertRaises(optuna.TrialPruned):
                obj(trial)

    def test_pruned_on_low_trade_count(self):
        import optuna
        bars = _make_usdjpy_bars(200)
        ss = volatility_squeeze_search_space()

        def make_strategy(params):
            from strategies.volatility_squeeze import VolatilitySqueezeStrategy, VolatilitySqueezeConfig
            return VolatilitySqueezeStrategy(config=VolatilitySqueezeConfig(**params))

        low_trade_result = _mock_walk_forward_results(trade_count=3.0)

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=low_trade_result,
        ):
            obj = WalkForwardObjective(
                bars=bars,
                strategy_factory=make_strategy,
                pair="USDJPY",
                search_space=ss,
            )
            study = optuna.create_study(direction="maximize")
            trial = study.ask()
            with self.assertRaises(optuna.TrialPruned):
                obj(trial)


if __name__ == "__main__":
    unittest.main()
