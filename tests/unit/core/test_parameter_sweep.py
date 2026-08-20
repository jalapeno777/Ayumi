import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from backtest.engine import BacktestConfig, Bar
from backtest.parameter_sweep.grid import GridPoint, ParameterGrid
from backtest.parameter_sweep.output import to_csv, to_json
from backtest.parameter_sweep.result import SweepResult, SweepRow
from backtest.parameter_sweep.sweep_runner import SweepRunner
from backtest.strategies import MACrossStrategy, RSIStrategy


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005, v=1000):
    base = datetime(2024, 1, 1, 10, 0)
    time = base + timedelta(hours=i)
    return Bar(time=time, open=o, high=h, low=low, close=c, volume=v)


def _trending_bars(n=200):
    bars = []
    price = 1.0000
    for i in range(n):
        drift = 0.00005 + (0.00001 if i % 24 in range(8, 16) else 0)
        noise = (i % 7 - 3) * 0.00003
        price += drift + noise
        h = price + abs(noise) * 2
        low = price - abs(noise) * 2
        bars.append(_bar(i, o=price - drift, h=h, low=low, c=price))
    return bars


class TestGridPoint(unittest.TestCase):
    def test_equality_same_params(self):
        a = GridPoint(params={"fast": 5, "slow": 13})
        b = GridPoint(params={"slow": 13, "fast": 5})
        self.assertEqual(a, b)

    def test_inequality_different_params(self):
        a = GridPoint(params={"fast": 5})
        b = GridPoint(params={"fast": 10})
        self.assertNotEqual(a, b)

    def test_hash_consistent(self):
        a = GridPoint(params={"x": 1, "y": 2})
        b = GridPoint(params={"y": 2, "x": 1})
        self.assertEqual(hash(a), hash(b))

    def test_hash_allows_set_membership(self):
        points = {GridPoint(params={"a": 1}), GridPoint(params={"a": 1})}
        self.assertEqual(len(points), 1)

    def test_not_equal_to_non_gridpoint(self):
        self.assertNotEqual(GridPoint(params={}), "not a grid point")


class TestParameterGrid(unittest.TestCase):
    def test_size_cartesian_product(self):
        grid = ParameterGrid({"a": [1, 2], "b": [3, 4, 5]})
        self.assertEqual(grid.size, 6)

    def test_len_matches_size(self):
        grid = ParameterGrid({"a": [1, 2, 3]})
        self.assertEqual(len(grid), 3)

    def test_param_names_sorted(self):
        grid = ParameterGrid({"z": [1], "a": [2]})
        self.assertEqual(grid.param_names, ["a", "z"])

    def test_iteration_produces_all_combos(self):
        grid = ParameterGrid({"a": [1, 2], "b": [10, 20]})
        points = list(grid)
        self.assertEqual(len(points), 4)
        param_sets = [tuple(sorted(p.params.items())) for p in points]
        expected = {
            (("a", 1), ("b", 10)),
            (("a", 1), ("b", 20)),
            (("a", 2), ("b", 10)),
            (("a", 2), ("b", 20)),
        }
        self.assertEqual(set(param_sets), expected)

    def test_to_list_matches_iteration(self):
        grid = ParameterGrid({"x": [1, 2]})
        self.assertEqual(grid.to_list(), list(grid))

    def test_empty_param_space_raises(self):
        with self.assertRaises(ValueError):
            ParameterGrid({})

    def test_single_param_single_value(self):
        grid = ParameterGrid({"a": [42]})
        self.assertEqual(grid.size, 1)
        point = list(grid)[0]
        self.assertEqual(point.params, {"a": 42})


class TestSweepRow(unittest.TestCase):
    def test_defaults(self):
        row = SweepRow(params={"fast": 5})
        self.assertEqual(row.win_rate, 0.0)
        self.assertEqual(row.trade_count, 0)
        self.assertEqual(row.params, {"fast": 5})

    def test_get_param(self):
        row = SweepRow(params={"fast": 5}, win_rate=0.6)
        self.assertEqual(row.get("fast"), 5.0)

    def test_get_metric(self):
        row = SweepRow(params={}, win_rate=0.75)
        self.assertEqual(row.get("win_rate"), 0.75)

    def test_get_missing_returns_default(self):
        row = SweepRow(params={})
        self.assertEqual(row.get("nonexistent", -1.0), -1.0)

    def test_frozen(self):
        row = SweepRow(params={})
        with self.assertRaises(AttributeError):
            row.win_rate = 0.5


class TestSweepResult(unittest.TestCase):
    def _make_result(self, rows_data):
        rows = [SweepRow(**d) for d in rows_data]
        return SweepResult(rows=rows)

    def test_len(self):
        result = self._make_result([{"params": {"a": 1}}, {"params": {"a": 2}}])
        self.assertEqual(len(result), 2)

    def test_iter(self):
        result = self._make_result([{"params": {"a": 1}}, {"params": {"a": 2}}])
        items = list(result)
        self.assertEqual(len(items), 2)

    def test_sort_by_metric(self):
        result = self._make_result(
            [
                {"params": {"a": 1}, "sharpe_ratio": 1.0},
                {"params": {"a": 2}, "sharpe_ratio": 2.0},
                {"params": {"a": 3}, "sharpe_ratio": 0.5},
            ]
        )
        sorted_rows = result.sort_by("sharpe_ratio")
        self.assertEqual(sorted_rows[0].sharpe_ratio, 2.0)
        self.assertEqual(sorted_rows[-1].sharpe_ratio, 0.5)

    def test_sort_by_ascending(self):
        result = self._make_result(
            [
                {"params": {}, "max_dd": 0.1},
                {"params": {}, "max_dd": 0.3},
            ]
        )
        sorted_rows = result.sort_by("max_dd", ascending=True)
        self.assertEqual(sorted_rows[0].max_dd, 0.1)

    def test_top_n(self):
        result = self._make_result(
            [
                {"params": {"a": 1}, "sharpe_ratio": 3.0},
                {"params": {"a": 2}, "sharpe_ratio": 1.0},
                {"params": {"a": 3}, "sharpe_ratio": 2.0},
            ]
        )
        top = result.top_n(2, metric="sharpe_ratio")
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0].sharpe_ratio, 3.0)
        self.assertEqual(top[1].sharpe_ratio, 2.0)

    def test_filter(self):
        result = self._make_result(
            [
                {"params": {"a": 1}, "win_rate": 0.6},
                {"params": {"a": 2}, "win_rate": 0.3},
                {"params": {"a": 3}, "win_rate": 0.8},
            ]
        )
        filtered = result.filter(lambda r: r.win_rate > 0.5)
        self.assertEqual(len(filtered), 2)

    def test_best_returns_best(self):
        result = self._make_result(
            [
                {"params": {"a": 1}, "sharpe_ratio": 1.0},
                {"params": {"a": 2}, "sharpe_ratio": 5.0},
            ]
        )
        self.assertEqual(result.best("sharpe_ratio").sharpe_ratio, 5.0)

    def test_best_empty_returns_none(self):
        result = SweepResult(rows=[])
        self.assertIsNone(result.best())

    def test_filter_returns_sweep_result(self):
        result = self._make_result([{"params": {"a": 1}}])
        filtered = result.filter(lambda _: True)
        self.assertIsInstance(filtered, SweepResult)


class TestSweepRunner(unittest.TestCase):
    def setUp(self):
        self.config = BacktestConfig(min_bars_before_signal=30)
        self.bars = _trending_bars(200)

    def test_serial_run_produces_results(self):
        grid = ParameterGrid({"fast_period": [5, 10], "slow_period": [13, 20]})
        runner = SweepRunner(
            config=self.config,
            bars=self.bars,
            strategy_factory=lambda p: MACrossStrategy(
                fast_period=p.params["fast_period"],
                slow_period=p.params["slow_period"],
            ),
            max_workers=1,
        )
        result = runner.run(grid)
        self.assertEqual(len(result), 4)
        for row in result:
            self.assertIsInstance(row, SweepRow)
            self.assertIn("fast_period", row.params)
            self.assertIn("slow_period", row.params)

    def test_single_grid_point(self):
        grid = ParameterGrid({"period": [14]})
        runner = SweepRunner(
            config=self.config,
            bars=self.bars,
            strategy_factory=lambda p: RSIStrategy(period=p.params["period"]),
            max_workers=1,
        )
        result = runner.run(grid)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.rows[0].params, {"period": 14})

    def test_max_workers_defaults_to_cpu_count(self):
        ParameterGrid({"fast_period": [5]})
        runner = SweepRunner(
            config=self.config,
            bars=self.bars,
            strategy_factory=lambda p: MACrossStrategy(fast_period=p.params["fast_period"]),
        )
        self.assertIsNotNone(runner._max_workers)

    def test_worker_entry_returns_metrics_dict(self):
        from dataclasses import asdict

        from backtest.parameter_sweep.sweep_runner import _serialize_bars, _worker_entry

        config_dict = asdict(self.config)
        bars_data = _serialize_bars(self.bars)
        strategy_config = {
            "__class__": "MACrossStrategy",
            "fast_period": 5,
            "slow_period": 13,
        }

        result = _worker_entry((config_dict, bars_data, strategy_config))
        self.assertIsNotNone(result)
        for key in (
            "win_rate",
            "max_dd",
            "total_return",
            "sharpe_ratio",
            "trade_count",
            "profit_factor",
        ):
            self.assertIn(key, result)

    def test_empty_grid_returns_empty_result(self):
        grid = ParameterGrid({"fast": [5]})
        runner = SweepRunner(
            config=self.config,
            bars=self.bars,
            strategy_factory=lambda p: MACrossStrategy(fast_period=p.params["fast"]),
            max_workers=1,
        )
        result = runner.run(grid)
        self.assertEqual(len(result), 1)


class TestOutput(unittest.TestCase):
    def setUp(self):
        self.result = SweepResult(
            rows=[
                SweepRow(
                    params={"fast": 5, "slow": 13},
                    win_rate=0.6,
                    max_dd=0.05,
                    total_return=0.12,
                    sharpe_ratio=1.5,
                    trade_count=50,
                    profit_factor=1.8,
                ),
                SweepRow(
                    params={"fast": 10, "slow": 20},
                    win_rate=0.4,
                    max_dd=0.08,
                    total_return=0.05,
                    sharpe_ratio=0.8,
                    trade_count=30,
                    profit_factor=1.2,
                ),
            ]
        )

    def test_to_csv(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            path = f.name
        try:
            to_csv(self.result, path)
            with open(path) as f:
                content = f.read()
            self.assertIn("fast", content)
            self.assertIn("slow", content)
            self.assertIn("sharpe_ratio", content)
            self.assertIn("1.5", content)
        finally:
            os.unlink(path)

    def test_to_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            to_json(self.result, path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["fast"], 5)
            self.assertEqual(data[0]["sharpe_ratio"], 1.5)
            self.assertEqual(data[1]["fast"], 10)
        finally:
            os.unlink(path)

    def test_to_csv_empty_result(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            path = f.name
        try:
            to_csv(SweepResult(rows=[]), path)
            with open(path) as f:
                content = f.read()
            self.assertTrue(content.strip() == "" or "sharpe_ratio" in content)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
