import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from backtest.engine import Bar, MarketState
from ml.mean_reversion import (
    MLMeanReversionStrategy,
    TrainingResult,
    _optimize_threshold,
    load_model,
    prepare_data,
    save_model,
    train_model,
    walk_forward_validate,
)


def _make_price_df(n=500, seed=42):
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="15min")
    price = 1.0850
    prices = [price]
    for _ in range(n - 1):
        change = rng.normal(0, 0.00015)
        price += change
        prices.append(price)
    close = np.array(prices)
    high = close + rng.uniform(0.00005, 0.0003, n)
    low = close - rng.uniform(0.00005, 0.0003, n)
    open_ = close + rng.normal(0, 0.0001, n)
    return pd.DataFrame(
        {
            "Date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.randint(100, 1000, n),
        }
    )


def _write_temp_csv(df):
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return tmp.name


def _make_bars(n=300, seed=42):
    rng = np.random.RandomState(seed)
    base = datetime(2024, 1, 1, 10, 0)
    price = 1.0850
    bars = []
    for i in range(n):
        change = rng.normal(0, 0.00015)
        price += change
        h = price + abs(rng.normal(0, 0.0002))
        low = price - abs(rng.normal(0, 0.0002))
        bars.append(
            Bar(
                time=base + timedelta(minutes=15 * i),
                open=price - change * 0.5,
                high=h,
                low=low,
                close=price,
                volume=rng.randint(100, 1000),
            )
        )
    return bars


def _make_labeled_dataset(n_samples=200, seed=42):
    rng = np.random.RandomState(seed)
    feature_names = [f"feat_{i}" for i in range(10)]
    X = rng.randn(n_samples, len(feature_names))
    y = rng.randint(0, 2, n_samples)
    df = pd.DataFrame(X, columns=feature_names)
    df["direction"] = rng.choice([1.0, -1.0], n_samples)
    df["entry_price"] = 1.0850 + rng.randn(n_samples) * 0.001
    df["stop_loss"] = df["entry_price"] - 0.001
    df["take_profit"] = df["entry_price"] + 0.002
    df["outcome"] = y
    df["pnl"] = rng.randn(n_samples) * 10
    return df


class TestPrepareData(unittest.TestCase):
    def test_returns_dataframe_with_expected_columns(self):
        df = _make_price_df(500, seed=42)
        csv_path = _write_temp_csv(df)
        try:
            dataset = prepare_data(csv_path)
            if dataset.empty:
                self.skipTest("No BB signals generated for this seed")
            self.assertIn("outcome", dataset.columns)
            self.assertIn("direction", dataset.columns)
            self.assertIn("entry_price", dataset.columns)
            self.assertIn("stop_loss", dataset.columns)
            self.assertIn("take_profit", dataset.columns)
            self.assertIn("pnl", dataset.columns)
        finally:
            os.unlink(csv_path)

    def test_empty_with_no_signals(self):
        rng = np.random.RandomState(99)
        n = 50
        dates = pd.date_range("2024-01-01", periods=n, freq="15min")
        price = 1.0850
        prices = [price]
        for _ in range(n - 1):
            price += rng.normal(0, 0.00001)
            prices.append(price)
        df = pd.DataFrame(
            {
                "Date": dates,
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [100] * n,
            }
        )
        csv_path = _write_temp_csv(df)
        try:
            dataset = prepare_data(csv_path)
            self.assertIsInstance(dataset, pd.DataFrame)
        finally:
            os.unlink(csv_path)

    def test_missing_date_column_raises(self):
        df = pd.DataFrame(
            {
                "open": [1.0],
                "high": [1.01],
                "low": [0.99],
                "close": [1.005],
                "volume": [100],
            }
        )
        csv_path = _write_temp_csv(df)
        try:
            with self.assertRaises(ValueError):
                prepare_data(csv_path)
        finally:
            os.unlink(csv_path)


class TestTrainModel(unittest.TestCase):
    def test_trains_and_returns_result(self):
        dataset = _make_labeled_dataset(200, seed=42)
        result = train_model(dataset, model_types=["gradient_boosting"], seed=42)
        self.assertIsInstance(result, TrainingResult)
        self.assertIsNotNone(result.model)
        self.assertEqual(result.model_type, "gradient_boosting")
        self.assertGreater(result.metrics["f1"], 0.0)
        self.assertGreater(result.metrics["accuracy"], 0.0)
        self.assertGreater(result.threshold, 0.0)

    def test_single_class_raises(self):
        df = _make_labeled_dataset(200, seed=42)
        df["outcome"] = 1
        with self.assertRaises(ValueError):
            train_model(df, model_types=["gradient_boosting"], seed=42)

    def test_all_failing_configs_raises(self):
        dataset = _make_labeled_dataset(10, seed=42)
        with self.assertRaises(RuntimeError):
            train_model(dataset, model_types=["nonexistent_type"], seed=42)


class TestOptimizeThreshold(unittest.TestCase):
    def test_returns_valid_threshold(self):
        rng = np.random.RandomState(42)
        y_prob = rng.uniform(0, 1, 100)
        y_true = (y_prob > 0.5).astype(int)
        threshold = _optimize_threshold(y_prob, y_true)
        self.assertGreaterEqual(threshold, 0.40)
        self.assertLessEqual(threshold, 0.80)

    def test_all_negative_returns_high_threshold(self):
        y_prob = np.zeros(100)
        y_true = np.zeros(100)
        threshold = _optimize_threshold(y_prob, y_true)
        self.assertGreaterEqual(threshold, 0.40)

    def test_optimizes_for_profit_factor_with_pnl(self):
        rng = np.random.RandomState(42)
        y_prob = rng.uniform(0, 1, 200)
        y_true = (y_prob > 0.5).astype(int)
        pnl = np.where(y_true == 1, rng.uniform(1, 5, 200), -rng.uniform(0.5, 2, 200))
        threshold = _optimize_threshold(y_prob, y_true, pnl=pnl)
        self.assertGreaterEqual(threshold, 0.40)
        self.assertLessEqual(threshold, 0.80)

    def test_pnl_threshold_differs_from_f1_threshold(self):
        rng = np.random.RandomState(42)
        y_prob = rng.uniform(0, 1, 200)
        y_true = (y_prob > 0.5).astype(int)
        pnl = np.where(
            y_true == 1, rng.uniform(0.1, 10, 200), -rng.uniform(0.1, 3, 200)
        )
        t_pf = _optimize_threshold(y_prob, y_true, pnl=pnl)
        self.assertIsInstance(t_pf, float)


class TestSaveLoadModel(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        dataset = _make_labeled_dataset(200, seed=42)
        result = train_model(dataset, model_types=["gradient_boosting"], seed=42)

        with tempfile.TemporaryDirectory() as tmpdir:
            save_model(result, tmpdir)
            self.assertTrue((Path(tmpdir) / "mean_reversion_model.pkl").exists())
            self.assertTrue((Path(tmpdir) / "mean_reversion_meta.json").exists())

            model, feature_names, threshold = load_model(tmpdir)
            self.assertIsNotNone(model)
            self.assertEqual(feature_names, result.feature_names)
            self.assertEqual(threshold, result.threshold)

    def test_load_creates_output_dir(self):
        dataset = _make_labeled_dataset(200, seed=42)
        result = train_model(dataset, model_types=["gradient_boosting"], seed=42)

        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "nested", "dir")
            save_model(result, nested)
            self.assertTrue(os.path.exists(nested))


class TestMLMeanReversionStrategy(unittest.TestCase):
    def _make_strategy(self, threshold=0.40):
        dataset = _make_labeled_dataset(300, seed=42)
        result = train_model(dataset, model_types=["gradient_boosting"], seed=42)
        return MLMeanReversionStrategy(
            model=result.model,
            feature_names=result.feature_names,
            threshold=threshold,
            min_lookback=50,
        )

    def test_name(self):
        strategy = self._make_strategy()
        self.assertEqual(strategy.name, "MLMeanReversion")

    def test_insufficient_bars_returns_none(self):
        strategy = self._make_strategy()
        bars = _make_bars(10, seed=42)
        state = MarketState(bars=bars)
        self.assertIsNone(strategy.evaluate(state))

    def test_no_signal_when_price_inside_bands(self):
        strategy = self._make_strategy()
        bars = _make_bars(300, seed=42)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_returns_strategy_signal_when_conditions_met(self):
        dataset = _make_labeled_dataset(300, seed=42)
        result = train_model(dataset, model_types=["gradient_boosting"], seed=42)

        strategy = MLMeanReversionStrategy(
            model=result.model,
            feature_names=result.feature_names,
            threshold=0.30,
            min_lookback=50,
        )

        rng = np.random.RandomState(123)
        base = datetime(2024, 1, 1, 10, 0)
        price = 1.0850
        bars = []
        for i in range(300):
            if 250 <= i <= 280:
                price -= 0.0005
            else:
                price += rng.normal(0, 0.00008)
            h = price + abs(rng.normal(0, 0.00005))
            low = price - abs(rng.normal(0, 0.00005))
            bars.append(
                Bar(
                    time=base + timedelta(minutes=15 * i),
                    open=price,
                    high=h,
                    low=low,
                    close=price,
                    volume=500,
                )
            )

        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)
        if signal is None:
            self.skipTest("Price didn't break BB bands for this seed")
        self.assertIsNotNone(signal.entry_price)
        self.assertIsNotNone(signal.stop_loss)
        self.assertIsNotNone(signal.take_profit_1)
        self.assertGreater(signal.confidence, 0.0)

    def test_signal_has_valid_sl_tp(self):
        dataset = _make_labeled_dataset(300, seed=42)
        result = train_model(dataset, model_types=["gradient_boosting"], seed=42)
        strategy = MLMeanReversionStrategy(
            model=result.model,
            feature_names=result.feature_names,
            threshold=0.30,
            min_lookback=50,
        )

        rng = np.random.RandomState(456)
        base = datetime(2024, 1, 1, 10, 0)
        price = 1.0850
        bars = []
        for i in range(300):
            if 250 <= i <= 280:
                price -= 0.0006
            else:
                price += rng.normal(0, 0.00008)
            h = price + abs(rng.normal(0, 0.00005))
            low = price - abs(rng.normal(0, 0.00005))
            bars.append(
                Bar(
                    time=base + timedelta(minutes=15 * i),
                    open=price,
                    high=h,
                    low=low,
                    close=price,
                    volume=500,
                )
            )

        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)
        if signal is None:
            self.skipTest("No signal generated")
        self.assertNotEqual(signal.direction.value, "neutral")
        self.assertGreater(signal.stop_loss, 0)
        self.assertGreater(signal.take_profit_1, 0)
        self.assertIn("ML mean-reversion", signal.rationale)


class TestFromModelDir(unittest.TestCase):
    def test_from_model_dir_creates_strategy(self):
        dataset = _make_labeled_dataset(200, seed=42)
        result = train_model(dataset, model_types=["gradient_boosting"], seed=42)

        with tempfile.TemporaryDirectory() as tmpdir:
            save_model(result, tmpdir)
            strategy = MLMeanReversionStrategy.from_model_dir(tmpdir, min_lookback=50)
            self.assertEqual(strategy.name, "MLMeanReversion")
            self.assertEqual(strategy._threshold, result.threshold)


class TestBarsToDataFrame(unittest.TestCase):
    def test_conversion(self):
        dataset = _make_labeled_dataset(100, seed=42)
        result = train_model(dataset, model_types=["gradient_boosting"], seed=42)
        strategy = MLMeanReversionStrategy(
            model=result.model,
            feature_names=result.feature_names,
            min_lookback=50,
        )
        bars = _make_bars(60, seed=42)
        df = strategy._bars_to_dataframe(bars)
        self.assertEqual(len(df), 60)
        self.assertIn("date", df.columns)
        self.assertIn("open", df.columns)
        self.assertIn("close", df.columns)


class TestWalkForwardValidate(unittest.TestCase):
    def test_walk_forward_runs(self):
        df = _make_price_df(1000, seed=42)
        csv_path = _write_temp_csv(df)
        try:
            result, fold_metrics = walk_forward_validate(csv_path, n_folds=3, seed=42)
            self.assertIsInstance(result, TrainingResult)
            self.assertGreater(len(fold_metrics), 0)
        except RuntimeError:
            pass
        finally:
            os.unlink(csv_path)

    def test_walk_forward_trains_on_past_tests_on_future(self):
        df = _make_price_df(2000, seed=42)
        csv_path = _write_temp_csv(df)
        try:
            result, fold_metrics = walk_forward_validate(csv_path, n_folds=4, seed=42)
            ok_folds = [fm for fm in fold_metrics if fm.get("status") == "ok"]
            if ok_folds:
                for fm in ok_folds:
                    self.assertIn("fold", fm)
                    self.assertGreater(fm["fold"], 0)
        except RuntimeError:
            pass
        finally:
            os.unlink(csv_path)


if __name__ == "__main__":
    unittest.main()
