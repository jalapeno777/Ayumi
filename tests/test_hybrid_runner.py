import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from backtest.engine import Bar, BacktestMetrics
from backtest.runner import (
    _metrics_to_dict,
    _aggregate_metrics,
    _print_summary_table,
    _run_window_backtest,
    run_hybrid_backtest,
)
from backtest.hybrid_strategy import HybridStrategy, HybridConfig


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005, v=1000):
    base = datetime(2024, 1, 1, 8, 0)
    time = base + timedelta(hours=i)
    return Bar(time=time, open=o, high=h, low=low, close=c, volume=v)


def _trending_bars(n=500, trend="up"):
    bars = []
    price = 1.0000
    for i in range(n):
        hour = (i + 8) % 24
        drift = 0.00005 if trend == "up" else -0.00005
        if 8 <= hour <= 20:
            drift *= 1.5
        noise = (i % 7 - 3) * 0.00003
        price += drift + noise
        h = price + abs(noise) * 2
        low = price - abs(noise) * 2
        bars.append(_bar(i, o=price - drift, h=h, low=low, c=price))
    return bars


def _fake_metrics(**overrides):
    defaults = {
        "starting_balance": 10000.0,
        "ending_balance": 10500.0,
        "total_pnl": 500.0,
        "total_pnl_pct": 5.0,
        "win_rate": 60.0,
        "total_trades": 30,
        "winning_trades": 18,
        "losing_trades": 12,
        "breakeven_trades": 0,
        "avg_win": 50.0,
        "avg_loss": -30.0,
        "largest_win": 150.0,
        "largest_loss": -80.0,
        "profit_factor": 1.8,
        "max_drawdown_pct": 3.5,
        "max_drawdown_dollar": 350.0,
        "max_daily_loss_dollar": 100.0,
        "sharpe_ratio": 1.2,
        "avg_risk_reward": 1.67,
        "expectancy": 10.0,
        "avg_holding_bars": 12.0,
        "equity_curve": [],
        "trades": [],
        "total_spread_cost": 15.0,
        "total_commission_cost": 10.0,
        "rejected_signals": 5,
    }
    defaults.update(overrides)
    return BacktestMetrics(**defaults)


class TestMetricsToDict(unittest.TestCase):
    def test_converts_all_fields(self):
        m = _fake_metrics()
        d = _metrics_to_dict(m)
        self.assertEqual(d["trades"], 30)
        self.assertAlmostEqual(d["win_rate"], 60.0)
        self.assertAlmostEqual(d["profit_factor"], 1.8)
        self.assertAlmostEqual(d["sharpe"], 1.2)
        self.assertAlmostEqual(d["max_dd"], 3.5)
        self.assertAlmostEqual(d["total_pnl"], 500.0)
        self.assertEqual(d["rejected"], 5)

    def test_rounds_floats(self):
        m = _fake_metrics(win_rate=60.12345, profit_factor=1.876543)
        d = _metrics_to_dict(m)
        self.assertAlmostEqual(d["win_rate"], 60.12)
        self.assertAlmostEqual(d["profit_factor"], 1.8765)


class TestAggregateMetrics(unittest.TestCase):
    def test_empty_input(self):
        result = _aggregate_metrics([])
        self.assertEqual(result, {})

    def test_single_window(self):
        windows = [{
            "window_id": 0,
            "test_metrics": {
                "win_rate": 60.0,
                "profit_factor": 1.5,
                "sharpe": 1.0,
                "max_dd": 3.0,
                "total_pnl": 500.0,
                "trades": 30,
            },
            "passed_go_nogo": True,
        }]
        result = _aggregate_metrics(windows)
        self.assertEqual(result["mean_win_rate"], 60.0)
        self.assertEqual(result["std_win_rate"], 0.0)
        self.assertEqual(result["windows_passed"], 1)
        self.assertEqual(result["total_windows"], 1)

    def test_multiple_windows(self):
        windows = [
            {
                "window_id": i,
                "test_metrics": {
                    "win_rate": 55.0 + i * 5.0,
                    "profit_factor": 1.4 + i * 0.2,
                    "sharpe": 0.8 + i * 0.3,
                    "max_dd": 3.0 + i * 0.5,
                    "total_pnl": 400.0 + i * 100.0,
                    "trades": 20 + i * 5,
                },
                "passed_go_nogo": i < 3,
            }
            for i in range(5)
        ]
        result = _aggregate_metrics(windows)
        self.assertAlmostEqual(result["mean_win_rate"], 65.0)
        self.assertTrue(result["std_win_rate"] > 0)
        self.assertEqual(result["windows_passed"], 3)
        self.assertEqual(result["total_windows"], 5)
        self.assertTrue(result["go_nogo"])

    def test_skips_error_windows(self):
        windows = [
            {"window_id": 0, "error": "Insufficient test bars"},
            {
                "window_id": 1,
                "test_metrics": {
                    "win_rate": 60.0,
                    "profit_factor": 1.5,
                    "sharpe": 1.0,
                    "max_dd": 3.0,
                    "total_pnl": 500.0,
                    "trades": 30,
                },
                "passed_go_nogo": True,
            },
        ]
        result = _aggregate_metrics(windows)
        self.assertEqual(result["total_windows"], 1)
        self.assertEqual(result["mean_win_rate"], 60.0)

    def test_go_nogo_logic(self):
        windows = [
            {
                "window_id": i,
                "test_metrics": {
                    "win_rate": 60.0,
                    "profit_factor": 1.5,
                    "sharpe": 1.0,
                    "max_dd": 3.0,
                    "total_pnl": 500.0,
                    "trades": 30,
                },
                "passed_go_nogo": i == 0,
            }
            for i in range(3)
        ]
        result = _aggregate_metrics(windows)
        self.assertFalse(result["go_nogo"])
        self.assertEqual(result["windows_passed"], 1)


class TestPrintSummaryTable(unittest.TestCase):
    def test_prints_without_error(self):
        import io
        windows = [{
            "window_id": 0,
            "test_metrics": {
                "trades": 30,
                "win_rate": 60.0,
                "profit_factor": 1.8,
                "sharpe": 1.2,
                "max_dd": 3.5,
                "total_pnl": 500.0,
            },
            "passed_go_nogo": True,
        }]
        agg = {
            "mean_win_rate": 60.0,
            "std_win_rate": 0.0,
            "mean_profit_factor": 1.8,
            "std_profit_factor": 0.0,
            "mean_sharpe": 1.2,
            "std_sharpe": 0.0,
            "mean_max_dd": 3.5,
            "std_max_dd": 0.0,
            "mean_total_pnl": 500.0,
            "std_total_pnl": 0.0,
            "mean_trades": 30.0,
            "std_trades": 0.0,
            "windows_passed": 1,
            "total_windows": 1,
            "go_nogo": True,
        }
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            _print_summary_table(windows, agg, "EURUSD")
        output = captured.getvalue()
        self.assertIn("EURUSD", output)
        self.assertIn("GO", output)
        self.assertIn("AGGREGATE", output)

    def test_handles_empty_aggregate(self):
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            _print_summary_table([], {}, "EURUSD")
        output = captured.getvalue()
        self.assertIn("EURUSD", output)


class TestRunWindowBacktest(unittest.TestCase):
    def test_returns_metrics_for_valid_bars(self):
        bars = _trending_bars(100)
        strategy = HybridStrategy(config=HybridConfig(min_confidence=0.1))
        metrics = _run_window_backtest(bars, strategy)
        self.assertIsInstance(metrics, BacktestMetrics)
        self.assertEqual(metrics.starting_balance, 10000.0)

    def test_returns_empty_metrics_for_short_bars(self):
        bars = _trending_bars(10)
        strategy = HybridStrategy()
        metrics = _run_window_backtest(bars, strategy)
        self.assertEqual(metrics.total_trades, 0)
        self.assertEqual(metrics.starting_balance, 10000.0)

    def test_respects_risk_parameters(self):
        bars = _trending_bars(100)
        strategy = HybridStrategy(config=HybridConfig(min_confidence=0.1))
        metrics = _run_window_backtest(
            bars, strategy,
            starting_balance=5000.0,
            risk_per_trade_pct=0.01,
        )
        self.assertEqual(metrics.starting_balance, 5000.0)


class TestRunHybridBacktest(unittest.TestCase):
    def test_returns_empty_for_insufficient_bars(self):
        bars = _trending_bars(50)
        result = run_hybrid_backtest(bars)
        self.assertEqual(result["per_window"], [])
        self.assertFalse(result["go_nogo"])

    def test_runs_all_windows_direct(self):
        bars = _trending_bars(600)
        result = run_hybrid_backtest(bars, pair="EURUSD", n_windows=2)

        self.assertEqual(len(result["per_window"]), 2)
        self.assertIn("config", result)
        self.assertIn("aggregated", result)
        self.assertIn("go_nogo", result)
        self.assertIn("per_window", result)

        config = result["config"]
        self.assertEqual(config["pair"], "EURUSD")
        self.assertEqual(config["n_windows"], 2)
        self.assertAlmostEqual(config["risk_per_trade_pct"], 0.005)

    def test_window_has_train_val_test_metrics(self):
        bars = _trending_bars(600)
        result = run_hybrid_backtest(bars, n_windows=2)

        for w in result["per_window"]:
            if "error" in w:
                continue
            self.assertIn("train_metrics", w)
            self.assertIn("val_metrics", w)
            self.assertIn("test_metrics", w)
            self.assertIn("passed_go_nogo", w)
            self.assertIn("train_bars", w)
            self.assertIn("val_bars", w)
            self.assertIn("test_bars", w)

    def test_json_report_saved(self):
        bars = _trending_bars(600)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            report_path = f.name

        try:
            run_hybrid_backtest(bars, report_path=report_path)

            self.assertTrue(os.path.exists(report_path))
            with open(report_path) as f:
                saved = json.load(f)

            self.assertIn("config", saved)
            self.assertIn("per_window", saved)
            self.assertIn("aggregated", saved)
            self.assertEqual(len(saved["per_window"]), 5)
        finally:
            os.unlink(report_path)

    def test_handles_window_with_insufficient_test_bars(self):
        bars = _trending_bars(550)
        result = run_hybrid_backtest(bars, n_windows=5)

        total = len(result["per_window"])
        self.assertGreater(total, 0)

    def test_config_has_ftmo_params(self):
        bars = _trending_bars(600)
        result = run_hybrid_backtest(bars)

        config = result["config"]
        self.assertEqual(config["max_open_trades"], 3)
        self.assertEqual(config["spread_pips"], 0.5)
        self.assertEqual(config["commission_per_lot"], 3.5)
        self.assertEqual(config["sessions"], ["london", "ny_am", "ny_pm"])
        self.assertAlmostEqual(config["max_daily_drawdown_pct"], 0.03)
        self.assertAlmostEqual(config["max_total_drawdown_pct"], 0.05)


class TestWindowSplitCorrectness(unittest.TestCase):
    def test_split_ratios_are_correct(self):
        n = 1000
        bars = _trending_bars(n)
        result = run_hybrid_backtest(
            bars, n_windows=2,
            train_ratio=0.60, val_ratio=0.15, test_ratio=0.15,
        )

        for w in result["per_window"]:
            if "error" in w:
                continue
            total_bars = w["train_bars"] + w["val_bars"] + w["test_bars"]
            window_size = n // 2
            self.assertLessEqual(total_bars, window_size)

            train_pct = w["train_bars"] / window_size
            self.assertAlmostEqual(train_pct, 0.60, delta=0.02)


if __name__ == "__main__":
    unittest.main()
