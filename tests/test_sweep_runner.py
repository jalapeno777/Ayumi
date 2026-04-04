import unittest
import json
import os
import tempfile
from datetime import datetime, timedelta

from backtest.engine import Bar, BacktestConfig
from backtest.strategies import BBStrategy
from backtest.sweep_runner import ParameterGrid, SweepRunner, SweepResult


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005, v=1000):
    base = datetime(2024, 1, 1, 10, 0)
    time = base + timedelta(hours=i)
    return Bar(time=time, open=o, high=h, low=low, close=c, volume=v)


def _trending_bars(n=200, trend="up"):
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


class TestParameterGrid(unittest.TestCase):
    def test_param_space_stored(self):
        grid = ParameterGrid({
            "period": [15, 20, 25],
            "std_dev": [1.5, 2.0, 2.5],
        })
        self.assertEqual(len(grid.param_space), 2)
        self.assertEqual(len(grid.param_space["period"]), 3)

    def test_combinations_produces_9_points(self):
        grid = ParameterGrid({
            "period": [15, 20, 25],
            "std_dev": [1.5, 2.0, 2.5],
        })
        combos = grid.combinations()
        self.assertEqual(len(combos), 9)
        for combo in combos:
            self.assertIn("period", combo)
            self.assertIn("std_dev", combo)


class TestSweepResult(unittest.TestCase):
    def test_sweep_result_fields(self):
        result = SweepResult(
            params={"period": 20, "std_dev": 2.0},
            win_rate=55.0,
            max_drawdown=3.5,
            total_return=12.5,
            sharpe_ratio=1.2,
            trade_count=42,
        )
        self.assertEqual(result.params["period"], 20)
        self.assertEqual(result.win_rate, 55.0)
        self.assertEqual(result.max_drawdown, 3.5)


class TestSweepRunner(unittest.TestCase):
    def _default_config(self):
        return BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            spread_pips=0.5,
            commission_per_lot=3.5,
            leverage=100,
            min_confidence=0.40,
            min_bars_before_signal=30,
            max_open_trades=1,
        )

    def test_sequential_run_produces_9_results(self):
        _bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid({
            "period": [15, 20, 25],
            "std_dev": [1.5, 2.0, 2.5],
        })

        runner = SweepRunner(
            engine=config,
            strategy_cls=BBStrategy,
            param_grid=grid,
            parallel=False,
        )
        results = runner.run()

        self.assertEqual(len(results), 9)
        for result in results:
            self.assertIsInstance(result, SweepResult)
            self.assertIn("period", result.params)
            self.assertIn("std_dev", result.params)
            self.assertGreaterEqual(result.trade_count, 0)
            self.assertGreaterEqual(result.win_rate, 0.0)
            self.assertLessEqual(result.win_rate, 100.0)

    def test_parallel_run_produces_9_results(self):
        _bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid({
            "period": [15, 20, 25],
            "std_dev": [1.5, 2.0, 2.5],
        })

        runner = SweepRunner(
            engine=config,
            strategy_cls=BBStrategy,
            param_grid=grid,
            parallel=True,
        )
        results = runner.run()

        self.assertEqual(len(results), 9)

    def test_sequential_and_parallel_produce_identical_results(self):
        _bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid({
            "period": [15, 20, 25],
            "std_dev": [1.5, 2.0, 2.5],
        })

        runner_seq = SweepRunner(
            engine=config,
            strategy_cls=BBStrategy,
            param_grid=grid,
            parallel=False,
        )
        runner_par = SweepRunner(
            engine=config,
            strategy_cls=BBStrategy,
            param_grid=grid,
            parallel=True,
        )

        seq_results = runner_seq.run()
        par_results = runner_par.run()

        self.assertEqual(len(seq_results), len(par_results))

        seq_sorted = sorted(seq_results, key=lambda r: (r.params["period"], r.params["std_dev"]))
        par_sorted = sorted(par_results, key=lambda r: (r.params["period"], r.params["std_dev"]))

        for seq_r, par_r in zip(seq_sorted, par_sorted):
            self.assertEqual(seq_r.params, par_r.params)
            self.assertAlmostEqual(seq_r.win_rate, par_r.win_rate, places=1)
            self.assertAlmostEqual(seq_r.max_drawdown, par_r.max_drawdown, places=2)
            self.assertAlmostEqual(seq_r.total_return, par_r.total_return, places=2)
            self.assertAlmostEqual(seq_r.sharpe_ratio, par_r.sharpe_ratio, places=2)

    def test_to_csv_produces_parseable_file(self):
        import pandas as pd

        _bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid({
            "period": [15, 20, 25],
            "std_dev": [1.5, 2.0, 2.5],
        })

        runner = SweepRunner(
            engine=config,
            strategy_cls=BBStrategy,
            param_grid=grid,
            parallel=False,
        )
        results = runner.run()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            csv_path = f.name

        try:
            runner.to_csv(results, csv_path)
            df = pd.read_csv(csv_path)

            self.assertEqual(len(df), 9)
            self.assertIn("period", df.columns)
            self.assertIn("std_dev", df.columns)
            self.assertIn("win_rate", df.columns)
            self.assertIn("max_drawdown", df.columns)
            self.assertIn("total_return", df.columns)
            self.assertIn("sharpe_ratio", df.columns)
            self.assertIn("trade_count", df.columns)

            for _, row in df.iterrows():
                self.assertGreaterEqual(row["trade_count"], 0)
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_to_json_produces_parseable_file(self):
        _bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid({
            "period": [15, 20, 25],
            "std_dev": [1.5, 2.0, 2.5],
        })

        runner = SweepRunner(
            engine=config,
            strategy_cls=BBStrategy,
            param_grid=grid,
            parallel=False,
        )
        results = runner.run()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json_path = f.name

        try:
            runner.to_json(results, json_path)
            with open(json_path, "r") as f:
                data = json.load(f)

            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 9)

            required_fields = ["params", "win_rate", "max_drawdown", "total_return", "sharpe_ratio", "trade_count"]
            for item in data:
                for field in required_fields:
                    self.assertIn(field, item)
                self.assertIn("period", item["params"])
                self.assertIn("std_dev", item["params"])
        finally:
            if os.path.exists(json_path):
                os.unlink(json_path)

    def test_all_grid_points_produce_results(self):
        _bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid({
            "period": [15, 20, 25],
            "std_dev": [1.5, 2.0, 2.5],
        })

        runner = SweepRunner(
            engine=config,
            strategy_cls=BBStrategy,
            param_grid=grid,
            parallel=False,
        )
        results = runner.run()

        param_combos = {(r.params["period"], r.params["std_dev"]) for r in results}
        expected_combos = {
            (15, 1.5), (15, 2.0), (15, 2.5),
            (20, 1.5), (20, 2.0), (20, 2.5),
            (25, 1.5), (25, 2.0), (25, 2.5),
        }
        self.assertEqual(param_combos, expected_combos)


if __name__ == "__main__":
    unittest.main()
