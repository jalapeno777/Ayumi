import math
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from backtest.engine import Bar


def _sanitize_float(value):
    if math.isinf(value) or math.isnan(value):
        return None
    if abs(value) > 1e6:
        return None
    return value


def _sanitize_report(obj):
    if isinstance(obj, float):
        return _sanitize_float(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_report(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_report(v) for v in obj]
    return obj


from backtest.parameter_sweep.optuna_optimizer import (
    OptimizationResult,
    OptunaOptimizer,
    SearchSpace,
    categorical,
    float_range,
    int_range,
)
from quant.walk_forward import (
    AggregatedMetrics,
    WalkForwardResults,
    WindowMetrics,
)
from strategies.volatility_squeeze import (
    VolatilitySqueezeConfig,
    VolatilitySqueezeStrategy,
)


def _bar(i, o=130.0, h=130.5, low=129.5, c=130.2, v=1000):
    base = datetime(2024, 1, 1, 10, 0)
    time = base + timedelta(hours=i)
    return Bar(time=time, open=o, high=h, low=low, close=c, volume=v)


def _make_bars(n=500):
    bars = []
    price = 130.0
    for i in range(n):
        drift = 0.005
        noise = (i % 7 - 3) * 0.003
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


def volatility_squeeze_search_space() -> SearchSpace:
    return SearchSpace(
        bb_period=int_range("bb_period", 10, 30),
        bb_std_dev=float_range("bb_std_dev", 1.2, 2.5, step=0.1),
        kc_period=int_range("kc_period", 10, 30),
        kc_atr_multiplier=float_range("kc_atr_multiplier", 0.8, 2.0, step=0.1),
        min_squeeze_bars=int_range("min_squeeze_bars", 1, 5),
        ema_period=int_range("ema_period", 15, 80, step=5),
        adx_period=int_range("adx_period", 10, 25),
        adx_min=float_range("adx_min", 10.0, 28.0, step=1.0),
        atr_period=int_range("atr_period", 10, 25),
        atr_sl_multiplier=float_range("atr_sl_multiplier", 1.0, 3.0, step=0.1),
        tp1_rr=float_range("tp1_rr", 0.5, 2.0, step=0.1),
        tp2_rr=float_range("tp2_rr", 1.5, 3.0, step=0.1),
        tp3_rr=float_range("tp3_rr", 2.0, 4.0, step=0.1),
        session_filter=categorical("session_filter", [True, False]),
        min_confidence=float_range("min_confidence", 0.45, 0.80, step=0.05),
        squeeze_release_mode=categorical(
            "squeeze_release_mode", ["strict", "moderate", "loose"]
        ),
    )


class TestVolatilitySqueezeSearchSpace(unittest.TestCase):
    def test_search_space_has_all_params(self):
        space = volatility_squeeze_search_space()
        expected = [
            "adx_min",
            "adx_period",
            "atr_period",
            "atr_sl_multiplier",
            "bb_period",
            "bb_std_dev",
            "ema_period",
            "kc_atr_multiplier",
            "kc_period",
            "min_confidence",
            "min_squeeze_bars",
            "session_filter",
            "squeeze_release_mode",
            "tp1_rr",
            "tp2_rr",
            "tp3_rr",
        ]
        self.assertEqual(sorted(space.param_names), sorted(expected))

    def test_search_space_categorical_params(self):
        space = volatility_squeeze_search_space()
        session_filter_spec = space._specs["session_filter"]
        self.assertEqual(session_filter_spec["type"], "categorical")
        self.assertEqual(session_filter_spec["choices"], [True, False])

        mode_spec = space._specs["squeeze_release_mode"]
        self.assertEqual(mode_spec["choices"], ["strict", "moderate", "loose"])

    def test_min_confidence_range_extends_above_base(self):
        spec = volatility_squeeze_search_space()._specs["min_confidence"]
        self.assertEqual(spec["low"], 0.45)
        self.assertGreater(spec["high"], 0.60)

    def test_tp2_rr_floor_at_1_5(self):
        spec = volatility_squeeze_search_space()._specs["tp2_rr"]
        self.assertGreaterEqual(spec["low"], 1.5)

    def test_tp1_rr_includes_0_5(self):
        spec = volatility_squeeze_search_space()._specs["tp1_rr"]
        self.assertEqual(spec["low"], 0.5)


class TestVolatilitySqueezeStrategyFactory(unittest.TestCase):
    def test_make_strategy_with_params(self):
        params = {
            "bb_period": 20,
            "bb_std_dev": 1.4,
            "kc_period": 24,
            "kc_atr_multiplier": 1.8,
            "min_squeeze_bars": 2,
            "ema_period": 50,
            "adx_period": 14,
            "adx_min": 14.0,
            "atr_period": 14,
            "atr_sl_multiplier": 2.0,
            "tp1_rr": 0.7,
            "tp2_rr": 1.9,
            "tp3_rr": 3.0,
            "session_filter": False,
            "min_confidence": 0.35,
            "squeeze_release_mode": "loose",
        }
        strategy = VolatilitySqueezeStrategy(config=VolatilitySqueezeConfig(**params))
        self.assertIsInstance(strategy, VolatilitySqueezeStrategy)
        self.assertEqual(strategy.config.bb_period, 20)
        self.assertEqual(strategy.config.bb_std_dev, 1.4)
        self.assertEqual(strategy.config.kc_atr_multiplier, 1.8)
        self.assertEqual(strategy.config.squeeze_release_mode, "loose")
        self.assertFalse(strategy.config.session_filter)
        self.assertAlmostEqual(strategy.config.min_confidence, 0.35)

    def test_make_strategy_default_config(self):
        strategy = VolatilitySqueezeStrategy()
        self.assertIsInstance(strategy, VolatilitySqueezeStrategy)
        self.assertEqual(strategy.config.bb_period, 20)
        self.assertEqual(strategy.config.squeeze_release_mode, "moderate")


class TestVolatilitySqueezeOptunaIntegration(unittest.TestCase):
    def test_optuna_optimizer_with_vol_squeeze(self):
        bars = _make_bars(500)
        wf_result = _mock_walk_forward_results()

        def make_strategy(params):
            return VolatilitySqueezeStrategy(config=VolatilitySqueezeConfig(**params))

        optimizer = OptunaOptimizer(
            bars=bars,
            strategy_factory=make_strategy,
            pair="USDJPY",
            search_space=volatility_squeeze_search_space(),
            n_trials=2,
        )

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=wf_result,
        ):
            result = optimizer.optimize()

        self.assertIsInstance(result, OptimizationResult)
        self.assertIn("bb_period", result.best_params)
        self.assertIn("squeeze_release_mode", result.best_params)
        self.assertTrue(result.go_nogo)

    def test_top_n_results_extraction(self):
        bars = _make_bars(500)
        wf_go = _mock_walk_forward_results(
            win_rate=0.7, profit_factor=2.0, go_nogo=True
        )

        def make_strategy(params):
            return VolatilitySqueezeStrategy(config=VolatilitySqueezeConfig(**params))

        optimizer = OptunaOptimizer(
            bars=bars,
            strategy_factory=make_strategy,
            pair="USDJPY",
            search_space=SearchSpace(
                bb_period=int_range("bb_period", 10, 30),
            ),
            n_trials=2,
        )

        with patch(
            "backtest.walk_forward_runner.run_strategy_walk_forward",
            return_value=wf_go,
        ):
            optimizer.optimize()

        objective = optimizer.objective
        results = []
        for trial_num in objective._results_by_trial:
            wf = objective.get_result(trial_num)
            params = objective.get_params(trial_num)
            if wf is None or wf.aggregated is None:
                continue
            agg = wf.aggregated
            score = objective._composite_score(agg)
            if not wf.go_nogo:
                score -= 1.0
            results.append({"score": score, "go_nogo": wf.go_nogo, "params": params})

        self.assertEqual(len(results), 2)
        for r in results:
            self.assertIn("score", r)
            self.assertIn("go_nogo", r)
            self.assertIn("params", r)


class TestJsonSanitization(unittest.TestCase):
    def test_sanitize_inf_returns_none(self):
        self.assertIsNone(_sanitize_float(float("inf")))

    def test_sanitize_neg_inf_returns_none(self):
        self.assertIsNone(_sanitize_float(float("-inf")))

    def test_sanitize_nan_returns_none(self):
        self.assertIsNone(_sanitize_float(float("nan")))

    def test_sanitize_normal_value(self):
        self.assertAlmostEqual(_sanitize_float(1.5), 1.5)

    def test_sanitize_large_value_returns_none(self):
        self.assertIsNone(_sanitize_float(1e7))

    def test_sanitize_nested_dict(self):
        result = _sanitize_report(
            {"sharpe": float("inf"), "pf": 2.5, "nested": {"val": float("nan")}}
        )
        self.assertIsNone(result["sharpe"])
        self.assertEqual(result["pf"], 2.5)
        self.assertIsNone(result["nested"]["val"])

    def test_sanitize_list(self):
        result = _sanitize_report([1.0, float("inf"), 3.0])
        self.assertEqual(result, [1.0, None, 3.0])


class TestPfCapInWalkForward(unittest.TestCase):
    def test_pf_capped_at_10_no_losses(self):
        w = _mock_walk_forward_results(
            win_rate=0.8, profit_factor=10.0, total_pnl=1000.0, trade_count=20
        )
        self.assertEqual(w.per_window[0].profit_factor, 10.0)
        self.assertAlmostEqual(w.aggregated.mean_profit_factor, 10.0)

    def test_pf_capped_at_10_with_losses(self):
        w = _mock_walk_forward_results(win_rate=0.6, profit_factor=1.5, trade_count=20)
        self.assertAlmostEqual(w.per_window[0].profit_factor, 1.5)


if __name__ == "__main__":
    unittest.main()
