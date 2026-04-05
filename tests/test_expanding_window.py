import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from backtest.engine import Bar
from backtest.hybrid_strategy import RejectionMetrics
from backtest.runner import run_hybrid_backtest


def _make_bars(n: int, base_price: float = 1.1000) -> list[Bar]:
    bars = []
    price = base_price
    for i in range(n):
        bars.append(
            Bar(
                time=datetime(2024, 1, 1) + timedelta(hours=i),
                open=price,
                high=price + 0.0005,
                low=price - 0.0005,
                close=price + 0.0001 * (1 if i % 2 == 0 else -1),
                volume=1000,
            )
        )
        price += 0.0001 * (1 if i % 2 == 0 else -1)
    return bars


def _make_mock_strategy():
    strategy = MagicMock()
    strategy.evaluate.return_value = None
    strategy.metrics = RejectionMetrics()
    strategy.reset_metrics = MagicMock()
    return strategy


@patch("backtest.runner.HybridStrategy")
class TestExpandingWindowMode(unittest.TestCase):
    def test_expanding_window_report_has_mode(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(1000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="expanding"
        )
        self.assertEqual(report["config"]["window_mode"], "expanding")

    def test_rolling_window_report_has_mode(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(1000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="rolling"
        )
        self.assertEqual(report["config"]["window_mode"], "rolling")

    def test_default_mode_is_rolling(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(1000)
        report = run_hybrid_backtest(bars, pair="EURUSD", n_windows=3)
        self.assertEqual(report["config"]["window_mode"], "rolling")

    def test_invalid_window_mode_returns_empty(self, mock_strategy_cls):
        bars = _make_bars(1000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="invalid"
        )
        self.assertEqual(report["per_window"], [])
        self.assertFalse(report["go_nogo"])

    def test_expanding_produces_correct_window_count(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(1000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="expanding"
        )
        self.assertEqual(len(report["per_window"]), 3)

    def test_expanding_train_grows_across_windows(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(1000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="expanding"
        )
        windows = report["per_window"]
        self.assertGreater(windows[1]["train_bars"], windows[0]["train_bars"])
        self.assertGreater(windows[2]["train_bars"], windows[1]["train_bars"])

    def test_expanding_test_size_is_fixed(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(1000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="expanding"
        )
        windows = report["per_window"]
        test_sizes = [w["test_bars"] for w in windows]
        self.assertTrue(
            all(s == test_sizes[0] for s in test_sizes),
            f"Test sizes should be fixed: {test_sizes}",
        )

    def test_expanding_val_size_is_fixed(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(1000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="expanding"
        )
        windows = report["per_window"]
        val_sizes = [w["val_bars"] for w in windows]
        self.assertTrue(
            all(s == val_sizes[0] for s in val_sizes),
            f"Val sizes should be fixed: {val_sizes}",
        )

    def test_expanding_train_starts_from_bar_zero(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(1000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="expanding"
        )
        windows = report["per_window"]
        for w in windows:
            self.assertEqual(
                w["train_start"],
                "2024-01-01 00:00:00",
                "Train should always start from bar 0 in expanding mode",
            )

    def test_expanding_test_windows_dont_overlap(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(1000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="expanding"
        )
        windows = report["per_window"]
        for i in range(1, len(windows)):
            prev_test_start = windows[i - 1]["test_start"]
            curr_test_start = windows[i]["test_start"]
            prev_test_end = windows[i - 1]["test_end"]
            self.assertGreaterEqual(
                curr_test_start,
                prev_test_end,
                f"Window {i} test start should not overlap window {i-1} test end",
            )
            self.assertGreater(
                curr_test_start,
                prev_test_start,
                "Test windows should advance forward",
            )

    def test_expanding_no_overlap_between_train_and_test(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(1000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="expanding"
        )
        windows = report["per_window"]
        for w in windows:
            train_end = w["train_end"]
            val_end = w["val_end"]
            test_start = w["test_start"]
            self.assertLessEqual(
                train_end,
                val_end,
                "Train should end before or at val start",
            )
            self.assertLessEqual(
                val_end,
                test_start,
                "Val should end before or at test start (buffer in between)",
            )

    def test_expanding_test_not_in_train(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(2000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=4, window_mode="expanding"
        )
        windows = report["per_window"]
        for i, w in enumerate(windows):
            for j, w2 in enumerate(windows):
                if i < j:
                    self.assertLessEqual(
                        w["train_end"],
                        w2["test_start"],
                        f"Window {i} train end should be before window {j} test start",
                    )

    def test_expanding_last_window_reaches_end_of_data(self, mock_strategy_cls):
        mock_strategy_cls.return_value = _make_mock_strategy()
        bars = _make_bars(1000)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="expanding"
        )
        last = report["per_window"][-1]
        self.assertEqual(
            last["test_end"],
            bars[-1].time.strftime("%Y-%m-%d %H:%M:%S"),
            "Last window test should reach end of data",
        )

    def test_insufficient_bars_returns_empty(self, mock_strategy_cls):
        bars = _make_bars(50)
        report = run_hybrid_backtest(
            bars, pair="EURUSD", n_windows=3, window_mode="expanding"
        )
        self.assertEqual(report["per_window"], [])
        self.assertFalse(report["go_nogo"])


if __name__ == "__main__":
    unittest.main()
