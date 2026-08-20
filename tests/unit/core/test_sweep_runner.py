import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from backtest.engine import BacktestConfig, Bar
from backtest.parameter_sweep.grid import ParameterGrid
from backtest.parameter_sweep.result import SweepResult, SweepRow
from backtest.parameter_sweep.sweep_runner import SweepRunner
from backtest.strategies import BBStrategy


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
        grid = ParameterGrid(
            {
                "period": [15, 20, 25],
                "std_dev": [1.5, 2.0, 2.5],
            }
        )
        self.assertEqual(len(grid.param_names), 2)
        self.assertIn("period", grid.param_names)
        self.assertIn("std_dev", grid.param_names)

    def test_combinations_produces_9_points(self):
        grid = ParameterGrid(
            {
                "period": [15, 20, 25],
                "std_dev": [1.5, 2.0, 2.5],
            }
        )
        combos = grid.to_list()
        self.assertEqual(len(combos), 9)
        for combo in combos:
            self.assertIn("period", combo.params)
            self.assertIn("std_dev", combo.params)


class TestSweepResult(unittest.TestCase):
    def test_sweep_result_fields(self):
        row = SweepRow(
            params={"period": 20, "std_dev": 2.0},
            win_rate=55.0,
            max_dd=3.5,
            total_return=12.5,
            sharpe_ratio=1.2,
            trade_count=42,
        )
        result = SweepResult(rows=[row])
        self.assertEqual(len(result), 1)
        self.assertEqual(result.rows[0].params["period"], 20)
        self.assertEqual(result.rows[0].win_rate, 55.0)
        self.assertEqual(result.rows[0].max_dd, 3.5)


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
        bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid(
            {
                "period": [15, 20, 25],
                "std_dev": [1.5, 2.0, 2.5],
            }
        )

        runner = SweepRunner(
            config=config,
            bars=bars,
            strategy_factory=lambda point: BBStrategy(**point.params),
            max_workers=None,
        )
        result = runner.run(grid)

        self.assertEqual(len(result), 9)
        for row in result:
            self.assertIsInstance(row, SweepRow)
            self.assertIn("period", row.params)
            self.assertIn("std_dev", row.params)
            self.assertGreaterEqual(row.trade_count, 0)
            self.assertGreaterEqual(row.win_rate, 0.0)
            self.assertLessEqual(row.win_rate, 100.0)

    def test_parallel_run_produces_9_results(self):
        bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid(
            {
                "period": [15, 20, 25],
                "std_dev": [1.5, 2.0, 2.5],
            }
        )

        runner = SweepRunner(
            config=config,
            bars=bars,
            strategy_factory=lambda point: BBStrategy(**point.params),
            max_workers=2,
        )
        result = runner.run(grid)

        self.assertEqual(len(result), 9)

    def test_sequential_and_parallel_produce_identical_results(self):
        bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid(
            {
                "period": [15, 20, 25],
                "std_dev": [1.5, 2.0, 2.5],
            }
        )

        runner_seq = SweepRunner(
            config=config,
            bars=bars,
            strategy_factory=lambda point: BBStrategy(**point.params),
            max_workers=None,
        )
        runner_par = SweepRunner(
            config=config,
            bars=bars,
            strategy_factory=lambda point: BBStrategy(**point.params),
            max_workers=2,
        )

        seq_result = runner_seq.run(grid)
        par_result = runner_par.run(grid)

        self.assertEqual(len(seq_result), len(par_result))

        seq_sorted = sorted(seq_result.rows, key=lambda r: (r.params["period"], r.params["std_dev"]))
        par_sorted = sorted(par_result.rows, key=lambda r: (r.params["period"], r.params["std_dev"]))

        for seq_r, par_r in zip(seq_sorted, par_sorted):  # noqa: B905
            self.assertEqual(seq_r.params, par_r.params)
            self.assertAlmostEqual(seq_r.win_rate, par_r.win_rate, places=1)
            self.assertAlmostEqual(seq_r.max_dd, par_r.max_dd, places=2)
            self.assertAlmostEqual(seq_r.total_return, par_r.total_return, places=2)
            self.assertAlmostEqual(seq_r.sharpe_ratio, par_r.sharpe_ratio, places=2)

    def test_to_csv_produces_parseable_file(self):
        import pandas as pd

        bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid(
            {
                "period": [15, 20, 25],
                "std_dev": [1.5, 2.0, 2.5],
            }
        )

        runner = SweepRunner(
            config=config,
            bars=bars,
            strategy_factory=lambda point: BBStrategy(**point.params),
            max_workers=None,
        )
        result = runner.run(grid)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            csv_path = f.name

        try:
            rows_data = [
                {
                    "period": row.params["period"],
                    "std_dev": row.params["std_dev"],
                    "win_rate": row.win_rate,
                    "max_drawdown": row.max_dd,
                    "total_return": row.total_return,
                    "sharpe_ratio": row.sharpe_ratio,
                    "trade_count": row.trade_count,
                }
                for row in result.rows
            ]
            import csv

            with open(csv_path, "w", newline="") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=rows_data[0].keys())
                writer.writeheader()
                writer.writerows(rows_data)

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
        bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid(
            {
                "period": [15, 20, 25],
                "std_dev": [1.5, 2.0, 2.5],
            }
        )

        runner = SweepRunner(
            config=config,
            bars=bars,
            strategy_factory=lambda point: BBStrategy(**point.params),
            max_workers=None,
        )
        result = runner.run(grid)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json_path = f.name

        try:
            data = [
                {
                    "params": row.params,
                    "win_rate": row.win_rate,
                    "max_drawdown": row.max_dd,
                    "total_return": row.total_return,
                    "sharpe_ratio": row.sharpe_ratio,
                    "trade_count": row.trade_count,
                }
                for row in result.rows
            ]
            with open(json_path, "w") as f:
                json.dump(data, f)

            with open(json_path) as f:
                loaded_data = json.load(f)

            self.assertIsInstance(loaded_data, list)
            self.assertEqual(len(loaded_data), 9)

            required_fields = [
                "params",
                "win_rate",
                "max_drawdown",
                "total_return",
                "sharpe_ratio",
                "trade_count",
            ]
            for item in loaded_data:
                for field in required_fields:
                    self.assertIn(field, item)
                self.assertIn("period", item["params"])
                self.assertIn("std_dev", item["params"])
        finally:
            if os.path.exists(json_path):
                os.unlink(json_path)

    def test_all_grid_points_produce_results(self):
        bars = _trending_bars(500, "up")
        config = self._default_config()
        grid = ParameterGrid(
            {
                "period": [15, 20, 25],
                "std_dev": [1.5, 2.0, 2.5],
            }
        )

        runner = SweepRunner(
            config=config,
            bars=bars,
            strategy_factory=lambda point: BBStrategy(**point.params),
            max_workers=None,
        )
        result = runner.run(grid)

        param_combos = {(row.params["period"], row.params["std_dev"]) for row in result.rows}
        expected_combos = {
            (15, 1.5),
            (15, 2.0),
            (15, 2.5),
            (20, 1.5),
            (20, 2.0),
            (20, 2.5),
            (25, 1.5),
            (25, 2.0),
            (25, 2.5),
        }
        self.assertEqual(param_combos, expected_combos)


if __name__ == "__main__":
    unittest.main()
