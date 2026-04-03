import os
import sys
import tempfile
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from ml.features import (
    sma, ema, atr, rsi, bollinger_bands, roc,
    stochastic, macd, volatility_percentile, trend_alignment,
    higher_highs, lower_lows, engulfing_bullish, engulfing_bearish,
    pin_bar_bullish, pin_bar_bearish, session_features,
    build_feature_matrix, load_csv,
)
from ml.signal_simulator import (
    ma_crossover_signals, rsi_divergence_signals, bb_mean_reversion_signals,
    momentum_signals, label_trades, generate_all_signals, build_labeled_dataset,
)
from ml.predict import SignalFilter, create_filter_integration_stub


def make_test_df(n=200, seed=42):
    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = 1.1000
    prices = [price]
    for _ in range(n - 1):
        price += np.random.normal(0, 0.0005)
        prices.append(price)
    prices = np.array(prices)
    spread = 0.0002
    return pd.DataFrame({
        "date": dates,
        "open": prices - spread * np.random.uniform(0, 1, n),
        "high": prices + spread * np.random.uniform(1, 3, n),
        "low": prices - spread * np.random.uniform(1, 3, n),
        "close": prices,
        "volume": np.random.randint(100, 10000, n),
    })


class TestIndicators:
    def test_sma(self):
        s = pd.Series([1, 2, 3, 4, 5], dtype=float)
        result = sma(s, 3)
        assert len(result) == 5
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == 2.0

    def test_ema(self):
        s = pd.Series([1, 2, 3, 4, 5], dtype=float)
        result = ema(s, 3)
        assert len(result) == 5
        assert result.iloc[4] > result.iloc[0]

    def test_atr(self):
        df = make_test_df(50)
        result = atr(df["high"], df["low"], df["close"], 14)
        assert len(result) == 50
        assert pd.isna(result.iloc[0])
        assert (result.dropna() > 0).all()

    def test_rsi(self):
        s = pd.Series(range(1, 51), dtype=float)
        result = rsi(s, 14)
        assert len(result) == 50
        valid = result.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_bollinger_bands(self):
        s = pd.Series(np.random.randn(50).cumsum() + 100)
        upper, mid, lower = bollinger_bands(s, 20, 2.0)
        assert len(upper) == 50
        assert (upper >= mid).all() if not mid.isna().any() else True
        assert (mid >= lower).all() if not mid.isna().any() else True

    def test_roc(self):
        s = pd.Series(range(1, 51), dtype=float)
        result = roc(s, 12)
        assert len(result) == 50
        assert pd.isna(result.iloc[0])

    def test_stochastic(self):
        df = make_test_df(50)
        k, d = stochastic(df["high"], df["low"], df["close"])
        assert len(k) == 50
        assert len(d) == 50

    def test_macd(self):
        s = pd.Series(np.random.randn(100).cumsum() + 100)
        line, signal, hist = macd(s)
        assert len(line) == 100
        assert len(signal) == 100
        assert len(hist) == 100

    def test_volatility_percentile(self):
        s = pd.Series(np.random.uniform(0.0001, 0.001, 100))
        result = volatility_percentile(s, 50)
        assert len(result) == 100
        valid = result.dropna()
        assert (valid >= 0).all() and (valid <= 1).all()

    def test_trend_alignment(self):
        s = pd.Series(np.random.randn(50).cumsum() + 100)
        result = trend_alignment(s)
        assert len(result) == 50
        assert set(result.dropna().unique()).issubset({-1, 1})

    def test_session_features(self):
        dates = pd.Series(pd.date_range("2023-01-02", periods=24, freq="1h"))
        result = session_features(dates)
        assert "hour" in result.columns
        assert "killzone_london" in result.columns
        assert "day_of_week" in result.columns

    def test_build_feature_matrix(self):
        df = make_test_df(100)
        features = build_feature_matrix(df)
        assert len(features) == 100
        assert "rsi" in features.columns
        assert "atr_14" in features.columns
        assert "bb_pct_b" in features.columns
        assert "killzone_london" in features.columns


class TestSignalSimulator:
    def test_ma_crossover_signals(self):
        df = make_test_df(100)
        sigs = ma_crossover_signals(df)
        assert "direction" in sigs.columns
        assert "entry_price" in sigs.columns
        assert "stop_loss" in sigs.columns
        assert sigs["direction"].isin([-1, 1]).all()

    def test_rsi_divergence_signals(self):
        df = make_test_df(100)
        sigs = rsi_divergence_signals(df)
        assert "strategy" in sigs.columns
        assert (sigs["strategy"] == "rsi_divergence").all()

    def test_bb_mean_reversion_signals(self):
        df = make_test_df(100)
        sigs = bb_mean_reversion_signals(df)
        assert "strategy" in sigs.columns

    def test_momentum_signals(self):
        df = make_test_df(100)
        sigs = momentum_signals(df)
        assert "strategy" in sigs.columns
        assert (sigs["strategy"] == "momentum").all()

    def test_label_trades(self):
        df = make_test_df(100)
        sigs = ma_crossover_signals(df)
        if len(sigs) == 0:
            return
        labeled = label_trades(sigs, df, max_holding_bars=50)
        if labeled.empty:
            return
        assert "outcome" in labeled.columns
        assert "pnl" in labeled.columns
        assert labeled["outcome"].isin([0, 1]).all()

    def test_generate_all_signals(self):
        df = make_test_df(100)
        sigs = generate_all_signals(df)
        assert "direction" in sigs.columns
        assert "strategy" in sigs.columns

    def test_build_labeled_dataset(self):
        df = make_test_df(100)
        features = build_feature_matrix(df)
        dataset = build_labeled_dataset(df, features, max_holding_bars=50)
        if len(dataset) == 0:
            return
        assert "outcome" in dataset.columns
        assert "rsi" in dataset.columns
        assert "atr_14" in dataset.columns


class TestPredict:
    def test_create_filter_integration_stub(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            tmp_path = f.name
        create_filter_integration_stub("/tmp/model_dir", tmp_path)
        with open(tmp_path) as f:
            content = f.read()
        os.unlink(tmp_path)
        assert "filter_signal" in content
        assert "MODEL_DIR" in content

    def test_signal_filter_predict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import pickle
            import json
            from sklearn.ensemble import GradientBoostingClassifier

            model = GradientBoostingClassifier(n_estimators=10, max_depth=2, random_state=42)
            X = np.random.randn(50, 5)
            y = np.random.randint(0, 2, 50)
            model.fit(X, y)

            with open(os.path.join(tmpdir, "signal_filter.pkl"), "wb") as f:
                pickle.dump(model, f)
            with open(os.path.join(tmpdir, "signal_filter_meta.json"), "w") as f:
                json.dump({"feature_names": ["a", "b", "c", "d", "e"], "model_type": "GradientBoosting"}, f)

            sf = SignalFilter(tmpdir)
            result = sf.predict(pd.Series({"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}))
            assert "approve" in result
            assert "confidence" in result

    def test_signal_filter_predict_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import pickle
            import json
            from sklearn.ensemble import GradientBoostingClassifier

            model = GradientBoostingClassifier(n_estimators=10, max_depth=2, random_state=42)
            X = np.random.randn(50, 3)
            y = np.random.randint(0, 2, 50)
            model.fit(X, y)

            with open(os.path.join(tmpdir, "signal_filter.pkl"), "wb") as f:
                pickle.dump(model, f)
            with open(os.path.join(tmpdir, "signal_filter_meta.json"), "w") as f:
                json.dump({"feature_names": ["a", "b", "c"], "model_type": "GradientBoosting"}, f)

            sf = SignalFilter(tmpdir)
            features_df = pd.DataFrame(
                np.random.randn(10, 3), columns=["a", "b", "c"]
            )
            results = sf.predict_batch(features_df)
            assert len(results) == 10
            assert "approve" in results.columns
            assert "confidence" in results.columns

    def test_signal_filter_missing_features(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import pickle
            import json
            from sklearn.ensemble import GradientBoostingClassifier

            model = GradientBoostingClassifier(n_estimators=10, max_depth=2, random_state=42)
            X = np.random.randn(50, 3)
            y = np.random.randint(0, 2, 50)
            model.fit(X, y)

            with open(os.path.join(tmpdir, "signal_filter.pkl"), "wb") as f:
                pickle.dump(model, f)
            with open(os.path.join(tmpdir, "signal_filter_meta.json"), "w") as f:
                json.dump({"feature_names": ["a", "b", "c"], "model_type": "GradientBoosting"}, f)

            sf = SignalFilter(tmpdir)
            result = sf.predict(pd.Series({"a": 1}))
            assert result["approve"] is False
            assert "missing features" in result["reason"]
