import unittest
from datetime import datetime

import pandas as pd

from ml.features import (
    BiasDirection,
    ICTSignal,
    build_ict_features,
    add_ict_features,
    ICT_FEATURE_NAMES,
)


def _make_signal(
    *,
    timestamp=None,
    bias=BiasDirection.BULLISH,
    confidence_score=0.75,
    structure_alignment=True,
    order_block=True,
    fvg=False,
    liquidity_sweep=True,
    premium_discount=True,
    session_quality=0.8,
    confluence_count=4,
    risk_reward_ratio=2.0,
) -> ICTSignal:
    return ICTSignal(
        timestamp=timestamp or datetime.utcnow(),
        bias=bias,
        confidence_score=confidence_score,
        structure_alignment=structure_alignment,
        order_block=order_block,
        fvg=fvg,
        liquidity_sweep=liquidity_sweep,
        premium_discount=premium_discount,
        session_quality=session_quality,
        confluence_count=confluence_count,
        risk_reward_ratio=risk_reward_ratio,
    )


class TestBuildICTFeatures(unittest.TestCase):
    def test_single_bullish_signal(self):
        ts = datetime(2024, 1, 1, 12, 0, 0)
        sig = _make_signal(timestamp=ts, bias=BiasDirection.BULLISH, confidence_score=0.85)
        index = pd.DatetimeIndex([ts])
        df = build_ict_features([sig], index)

        self.assertEqual(len(df), 1)
        self.assertAlmostEqual(df["confluence_score"].iloc[0], 0.85)
        self.assertEqual(df["bias_encoded"].iloc[0], 1)
        self.assertEqual(df["structure_score"].iloc[0], 1.0)
        self.assertEqual(df["ob_score"].iloc[0], 1.0)
        self.assertEqual(df["fvg_score"].iloc[0], 0.0)
        self.assertEqual(df["liq_sweep_score"].iloc[0], 1.0)
        self.assertEqual(df["pd_zone_score"].iloc[0], 1.0)

    def test_bearish_signal(self):
        ts = datetime(2024, 1, 1, 12, 0, 0)
        sig = _make_signal(timestamp=ts, bias=BiasDirection.BEARISH)
        index = pd.DatetimeIndex([ts])
        df = build_ict_features([sig], index)

        self.assertEqual(df["bias_encoded"].iloc[0], -1)

    def test_neutral_signal(self):
        ts = datetime(2024, 1, 1, 12, 0, 0)
        sig = _make_signal(timestamp=ts, bias=BiasDirection.NEUTRAL)
        index = pd.DatetimeIndex([ts])
        df = build_ict_features([sig], index)

        self.assertEqual(df["bias_encoded"].iloc[0], 0)

    def test_empty_list_returns_empty_df(self):
        index = pd.DatetimeIndex([datetime(2024, 1, 1, 12, 0, 0)])
        df = build_ict_features([], index)
        self.assertTrue(df.empty)

    def test_multiple_signals(self):
        ts1 = datetime(2024, 1, 1, 12, 0, 0)
        ts2 = datetime(2024, 1, 1, 13, 0, 0)
        ts3 = datetime(2024, 1, 1, 14, 0, 0)
        signals = [
            _make_signal(timestamp=ts1, bias=BiasDirection.BULLISH, confidence_score=0.9),
            _make_signal(timestamp=ts2, bias=BiasDirection.BEARISH, confidence_score=0.7),
            _make_signal(timestamp=ts3, bias=BiasDirection.NEUTRAL, confidence_score=0.5),
        ]
        index = pd.DatetimeIndex([ts1, ts2, ts3])
        df = build_ict_features(signals, index)

        self.assertEqual(len(df), 3)
        self.assertAlmostEqual(df["confluence_score"].iloc[0], 0.9)
        self.assertAlmostEqual(df["confluence_score"].iloc[1], 0.7)
        self.assertAlmostEqual(df["confluence_score"].iloc[2], 0.5)
        self.assertEqual(df["bias_encoded"].tolist(), [1, -1, 0])

    def test_boolean_flags_converted_to_scores(self):
        ts = datetime(2024, 1, 1, 12, 0, 0)
        sig_all_true = _make_signal(
            timestamp=ts,
            structure_alignment=True,
            order_block=True,
            fvg=True,
            liquidity_sweep=True,
            premium_discount=True,
        )
        index = pd.DatetimeIndex([ts])
        df_true = build_ict_features([sig_all_true], index)
        self.assertEqual(df_true["structure_score"].iloc[0], 1.0)
        self.assertEqual(df_true["ob_score"].iloc[0], 1.0)
        self.assertEqual(df_true["fvg_score"].iloc[0], 1.0)
        self.assertEqual(df_true["liq_sweep_score"].iloc[0], 1.0)
        self.assertEqual(df_true["pd_zone_score"].iloc[0], 1.0)

        sig_all_false = _make_signal(
            timestamp=ts,
            structure_alignment=False,
            order_block=False,
            fvg=False,
            liquidity_sweep=False,
            premium_discount=False,
        )
        df_false = build_ict_features([sig_all_false], index)
        self.assertEqual(df_false["structure_score"].iloc[0], 0.0)
        self.assertEqual(df_false["ob_score"].iloc[0], 0.0)
        self.assertEqual(df_false["fvg_score"].iloc[0], 0.0)
        self.assertEqual(df_false["liq_sweep_score"].iloc[0], 0.0)
        self.assertEqual(df_false["pd_zone_score"].iloc[0], 0.0)

    def test_session_score_passed_through(self):
        ts = datetime(2024, 1, 1, 12, 0, 0)
        sig = _make_signal(timestamp=ts, session_quality=0.9)
        index = pd.DatetimeIndex([ts])
        df = build_ict_features([sig], index)
        self.assertAlmostEqual(df["session_score"].iloc[0], 0.9)

    def test_confluence_count_and_risk_reward(self):
        ts = datetime(2024, 1, 1, 12, 0, 0)
        sig = _make_signal(timestamp=ts, confluence_count=5, risk_reward_ratio=2.5)
        index = pd.DatetimeIndex([ts])
        df = build_ict_features([sig], index)
        self.assertEqual(df["confluence_count"].iloc[0], 5)
        self.assertAlmostEqual(df["risk_reward"].iloc[0], 2.5)


class TestAddICTFeatures(unittest.TestCase):
    def test_add_ict_features_merges_correctly(self):
        base_features = pd.DataFrame({
            "atr_14": [0.001, 0.0012],
            "rsi": [50.0, 55.0],
        }, index=pd.DatetimeIndex([datetime(2024, 1, 1, 12, 0, 0), datetime(2024, 1, 1, 13, 0, 0)]))

        ts1 = datetime(2024, 1, 1, 12, 0, 0)
        ts2 = datetime(2024, 1, 1, 13, 0, 0)
        ict_features = pd.DataFrame({
            "confluence_score": [0.8, 0.6],
            "bias_encoded": [1, -1],
        }, index=pd.DatetimeIndex([ts1, ts2]))

        result = add_ict_features(base_features, ict_features)

        self.assertEqual(len(result), 2)
        self.assertIn("atr_14", result.columns)
        self.assertIn("confluence_score", result.columns)
        self.assertAlmostEqual(result["confluence_score"].iloc[0], 0.8)

    def test_add_ict_features_with_empty_ict(self):
        base_features = pd.DataFrame({
            "atr_14": [0.001],
        }, index=pd.DatetimeIndex([datetime(2024, 1, 1, 12, 0, 0)]))
        empty_ict = pd.DataFrame(columns=["confluence_score"])

        result = add_ict_features(base_features, empty_ict)
        self.assertEqual(len(result), 1)
        self.assertNotIn("confluence_score", result.columns)


class TestICTFeatureNames(unittest.TestCase):
    def test_ict_feature_names_list(self):
        expected = [
            "confluence_score",
            "structure_score",
            "ob_score",
            "fvg_score",
            "liq_sweep_score",
            "pd_zone_score",
            "session_score",
            "bias_encoded",
            "confluence_count",
            "risk_reward",
        ]
        self.assertEqual(ICT_FEATURE_NAMES, expected)


class TestBiasDirection(unittest.TestCase):
    def test_bullish_value(self):
        self.assertEqual(BiasDirection.BULLISH.value, 1)

    def test_neutral_value(self):
        self.assertEqual(BiasDirection.NEUTRAL.value, 0)

    def test_bearish_value(self):
        self.assertEqual(BiasDirection.BEARISH.value, -1)


class TestICTSignal(unittest.TestCase):
    def test_ict_signal_creation(self):
        sig = ICTSignal(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            bias=BiasDirection.BULLISH,
            confidence_score=0.75,
            structure_alignment=True,
            order_block=True,
            fvg=False,
            liquidity_sweep=True,
            premium_discount=False,
            session_quality=0.8,
            confluence_count=3,
            risk_reward_ratio=2.0,
        )
        self.assertEqual(sig.bias, BiasDirection.BULLISH)
        self.assertAlmostEqual(sig.confidence_score, 0.75)
        self.assertEqual(sig.confluence_count, 3)


if __name__ == "__main__":
    unittest.main()