"""Tests for ml/optuna_optimizer.py (V2 walk-forward version)."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call

from backtest.engine import Bar
from quant.walk_forward import (
    AggregatedMetrics,
    WalkForwardResults,
    WindowMetrics,
)


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005, v=1000):
    base = datetime(2024, 1, 1, 10, 0)
    t = base + timedelta(hours=i)
    return Bar(time=t, open=o, high=h, low=low, close=c, volume=v)


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


def _mock_wf(
    win_rate=0.6, profit_factor=1.5, max_drawdown=0.05,
    trade_count=20.0, total_pnl=500.0, windows_passed=2, total_windows=3,
    go_nogo=True,
):
    windows = []
    for i in range(total_windows):
        passed = i < windows_passed
        windows.append(WindowMetrics(
            window_index=i,
            win_rate=win_rate if passed else 0.4,
            profit_factor=profit_factor if passed else 0.8,
            max_drawdown=max_drawdown if passed else 0.15,
            sharpe_ratio=1.0 if passed else 0.3,
            trade_count=int(trade_count) if passed else 5,
            total_pnl=total_pnl / total_windows if passed else -100,
            passed_go_nogo=passed,
        ))
    agg = AggregatedMetrics(
        mean_win_rate=win_rate, std_win_rate=0.05,
        mean_profit_factor=profit_factor, std_profit_factor=0.3,
        mean_max_drawdown=max_drawdown, std_max_drawdown=0.02,
        mean_sharpe_ratio=1.0, std_sharpe_ratio=0.2,
        mean_trade_count=trade_count, std_trade_count=5.0,
        mean_total_pnl=total_pnl, std_total_pnl=100.0,
        windows_passed=windows_passed, total_windows=total_windows,
    )
    return WalkForwardResults(per_window=windows, aggregated=agg, go_nogo=go_nogo)


class TestApplyTrialParams(unittest.TestCase):
    """Test _apply_trial_params patches tts_module correctly."""

    def setUp(self):
        import backtest.strategies.tts_strategy as tts
        self._tts = tts

    def test_continuous_params_applied(self):
        from ml.optuna_optimizer import _apply_trial_params, restore_defaults
        trial = MagicMock()
        trial.suggest_float.side_effect = [0.30, 0.5, -0.05]
        trial.suggest_categorical.return_value = True

        applied = _apply_trial_params(trial)

        self.assertAlmostEqual(applied["base_confidence"], 0.30)
        self.assertAlmostEqual(applied["negative_weight"], 0.5)
        self.assertAlmostEqual(applied["kz_penalty"], -0.05)

        restore_defaults()

    def test_booster_switches(self):
        from ml.optuna_optimizer import (
            _apply_trial_params, restore_defaults, BOOSTER_SWITCHES,
        )
        trial = MagicMock()
        # 3 continuous + 11 boosters + 9 negatives = 23 suggest_float/categorical calls
        trial.suggest_float.side_effect = [0.25, 1.0, -0.03]
        # First booster True, rest False
        switch_results = [True] + [False] * (len(BOOSTER_SWITCHES) - 1)
        switch_results += [True] * 9  # all negatives on
        trial.suggest_categorical.side_effect = switch_results

        applied = _apply_trial_params(trial)

        self.assertEqual(len(applied["enabled_boosters"]), 1)
        self.assertEqual(applied["enabled_boosters"][0], BOOSTER_SWITCHES[0])
        self.assertEqual(len(applied["enabled_negatives"]), 9)

        restore_defaults()

    def test_restore_defaults_resets(self):
        from ml.optuna_optimizer import restore_defaults
        restore_defaults()
        import backtest.strategies.tts_strategy as tts
        self.assertAlmostEqual(tts.MW_BASE_CONFIDENCE, 0.30)
        self.assertAlmostEqual(tts.NEGATIVE_WEIGHT, 1.0)


class TestBuildWFObjective(unittest.TestCase):
    """Test walk-forward objective function."""

    @patch("ml.optuna_optimizer.run_strategy_walk_forward")
    def test_pruned_on_no_aggregation(self, mock_wf):
        mock_wf.return_value = WalkForwardResults(
            per_window=[], aggregated=None, go_nogo=False,
        )
        from ml.optuna_optimizer import build_wf_objective

        bars = _make_bars(500)
        objective = build_wf_objective("EURUSD", "M15", bars)

        import optuna
        study = optuna.create_study(direction="maximize")
        trial = study.ask()

        with self.assertRaises(optuna.TrialPruned):
            objective(trial)

    @patch("ml.optuna_optimizer.run_strategy_walk_forward")
    def test_pruned_on_low_trades(self, mock_wf):
        mock_wf.return_value = _mock_wf(trade_count=2.0, total_windows=3)
        from ml.optuna_optimizer import build_wf_objective

        bars = _make_bars(500)
        objective = build_wf_objective("EURUSD", "M15", bars)

        import optuna
        study = optuna.create_study(direction="maximize")
        trial = study.ask()

        with self.assertRaises(optuna.TrialPruned):
            objective(trial)

    @patch("ml.optuna_optimizer.run_strategy_walk_forward")
    def test_valid_trial_returns_score(self, mock_wf):
        mock_wf.return_value = _mock_wf(win_rate=0.6, trade_count=25.0)
        from ml.optuna_optimizer import build_wf_objective

        bars = _make_bars(500)
        objective = build_wf_objective("EURUSD", "M15", bars)

        import optuna
        study = optuna.create_study(direction="maximize")
        trial = study.ask()

        score = objective(trial)
        self.assertGreater(score, 0)
        self.assertAlmostEqual(trial.user_attrs["win_rate"], 0.6)

    @patch("ml.optuna_optimizer.run_strategy_walk_forward")
    def test_go_nogo_penalty(self, mock_wf):
        from ml.optuna_optimizer import build_wf_objective
        bars = _make_bars(500)
        objective = build_wf_objective("EURUSD", "M15", bars)

        import optuna

        # Go result
        mock_wf.return_value = _mock_wf(go_nogo=True, win_rate=0.6, trade_count=25.0)
        study_go = optuna.create_study(direction="maximize")
        score_go = objective(study_go.ask())

        # No-go result
        mock_wf.return_value = _mock_wf(go_nogo=False, win_rate=0.6, trade_count=25.0)
        study_no = optuna.create_study(direction="maximize")
        score_no = objective(study_no.ask())

        self.assertLess(score_no, score_go)

    @patch("ml.optuna_optimizer.run_strategy_walk_forward")
    def test_restore_called_on_exception(self, mock_wf):
        from ml.optuna_optimizer import build_wf_objective, restore_defaults
        mock_wf.side_effect = RuntimeError("boom")

        bars = _make_bars(500)
        objective = build_wf_objective("EURUSD", "M15", bars)

        import optuna
        study = optuna.create_study(direction="maximize")
        trial = study.ask()

        with self.assertRaises(optuna.TrialPruned):
            objective(trial)

        # tts_module should still be restored
        import backtest.strategies.tts_strategy as tts
        self.assertAlmostEqual(tts.MW_BASE_CONFIDENCE, 0.30)


class TestGridSearch(unittest.TestCase):
    """Test grid search helper."""

    @patch("ml.optuna_optimizer.run_strategy_walk_forward")
    @patch("ml.optuna_optimizer.load_bars")
    def test_grid_returns_sorted_results(self, mock_load, mock_wf):
        mock_load.return_value = _make_bars(500)
        mock_wf.return_value = _mock_wf(win_rate=0.55, trade_count=20.0)

        from ml.optuna_optimizer import run_grid

        result = run_grid("EURUSD", "M15",
                          base_values=[0.25, 0.30],
                          neg_weight_values=[0.0, 1.0],
                          kz_penalty_values=[-0.05])

        self.assertGreater(len(result["rows"]), 0)
        self.assertIn("best_grid_row", result)
        self.assertIn("win_rate", result["best_grid_row"])

    @patch("ml.optuna_optimizer.run_strategy_walk_forward")
    @patch("ml.optuna_optimizer.load_bars")
    def test_grid_handles_errors(self, mock_load, mock_wf):
        mock_load.return_value = _make_bars(500)
        mock_wf.side_effect = RuntimeError("fail")

        from ml.optuna_optimizer import run_grid

        result = run_grid("EURUSD", "M15",
                          base_values=[0.25],
                          neg_weight_values=[0.0],
                          kz_penalty_values=[-0.05])

        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["win_rate"], 0)


class TestUpdateConfig(unittest.TestCase):
    """Test per_symbol_config update logic."""

    def test_skip_when_below_threshold(self):
        from ml.optuna_optimizer import update_per_symbol_config

        result = {
            "should_update_config": False,
            "best_params": {},
            "best_user_attrs": {"win_rate": 0.35},
        }
        self.assertFalse(update_per_symbol_config("EURUSD", "M15", result))

    def test_skip_when_no_config_file(self):
        from pathlib import Path
        from ml.optuna_optimizer import update_per_symbol_config
        import ml.optuna_optimizer as opt_mod

        orig = opt_mod.PROJECT_ROOT
        opt_mod.PROJECT_ROOT = Path("/tmp/nonexistent_ayumi_test")
        try:
            result = {
                "should_update_config": True,
                "best_params": {},
                "best_user_attrs": {"win_rate": 0.50},
            }
            self.assertFalse(update_per_symbol_config("EURUSD", "M15", result))
        finally:
            opt_mod.PROJECT_ROOT = orig


class TestSearchSpaceConstants(unittest.TestCase):
    """Verify the reduced search space is correct size."""

    def test_booster_switches_count(self):
        from ml.optuna_optimizer import BOOSTER_SWITCHES, NEGATIVE_SWITCHES
        self.assertEqual(len(BOOSTER_SWITCHES), 11)
        self.assertEqual(len(NEGATIVE_SWITCHES), 9)

    def test_total_dims(self):
        # 3 continuous + 11 boosters + 9 negatives = 23 dims (was 31+)
        from ml.optuna_optimizer import (
            BOOSTER_SWITCHES, NEGATIVE_SWITCHES,
            BASE_CONF_RANGE, NEG_WEIGHT_RANGE, KZ_PENALTY_RANGE,
        )
        continuous = 3
        switches = len(BOOSTER_SWITCHES) + len(NEGATIVE_SWITCHES)
        total = continuous + switches
        self.assertLess(total, 25)


if __name__ == "__main__":
    unittest.main()
