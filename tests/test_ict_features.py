import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from backtest.ict_smc.models import ConfluenceSignal, SignalStrength
from backtest.engine import TradeDirection
from ml.features import (
    build_ict_features,
    build_feature_matrix,
    ICT_FEATURE_NAMES,
)


SIGNAL_TIME = datetime(2024, 6, 15, 10, 0, 0)
SIGNAL_TIME_2 = datetime(2024, 6, 15, 11, 0, 0)


def _make_signal(
    direction=TradeDirection.LONG,
    confidence=0.75,
    structure_score=0.8,
    ob_score=0.6,
    fvg_score=0.4,
    liq_sweep_score=0.5,
    pd_zone_score=0.7,
    session_score=0.8,
    confluence_count=4,
    risk_reward=2.5,
    signal_time=None,
) -> ConfluenceSignal:
    return ConfluenceSignal(
        direction=direction,
        strength=SignalStrength.STRONG,
        confidence_score=confidence,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1100,
        take_profit_2=1.1200,
        take_profit_3=1.1300,
        signal_time=signal_time or SIGNAL_TIME,
        rationale="test signal",
        has_order_block=True,
        has_fvg=True,
        has_liquidity_sweep=False,
        has_premium_discount_confluence=True,
        has_structure_alignment=True,
        confluence_count=confluence_count,
        risk_reward_ratio=risk_reward,
        structure_score=structure_score,
        ob_score=ob_score,
        fvg_score=fvg_score,
        liq_sweep_score=liq_sweep_score,
        pd_zone_score=pd_zone_score,
        session_score=session_score,
    )


def _make_df(n=50, seed=42):
    np.random.seed(seed)
    dates = pd.date_range("2024-06-15", periods=n, freq="1h")
    price = 1.1000
    prices = [price]
    for _ in range(n - 1):
        price += np.random.normal(0, 0.0005)
        prices.append(price)
    prices = np.array(prices)
    spread = 0.0002
    return pd.DataFrame(
        {
            "date": dates,
            "open": prices - spread * np.random.uniform(0, 1, n),
            "high": prices + spread * np.random.uniform(1, 3, n),
            "low": prices - spread * np.random.uniform(1, 3, n),
            "close": prices,
            "volume": np.random.randint(100, 10000, n),
        }
    )


class TestBuildICTFeatures:
    def test_extracts_all_ict_columns(self):
        signal = _make_signal()
        index = pd.DatetimeIndex([SIGNAL_TIME])
        result = build_ict_features([signal], index)
        for name in ICT_FEATURE_NAMES:
            assert name in result.columns

    def test_correct_values_from_signal(self):
        signal = _make_signal()
        index = pd.DatetimeIndex([SIGNAL_TIME])
        result = build_ict_features([signal], index)
        row = result.iloc[0]
        assert row["ict_confluence_score"] == 0.75
        assert row["ict_structure_score"] == 0.8
        assert row["ict_ob_score"] == 0.6
        assert row["ict_fvg_score"] == 0.4
        assert row["ict_liq_sweep_score"] == 0.5
        assert row["ict_pd_zone_score"] == 0.7
        assert row["ict_session_score"] == 0.8
        assert row["ict_bias_encoded"] == 1
        assert row["ict_confluence_count"] == 4
        assert row["ict_risk_reward"] == 2.5

    def test_bearish_bias_encoded_as_negative_one(self):
        signal = _make_signal(direction=TradeDirection.SHORT)
        index = pd.DatetimeIndex([SIGNAL_TIME])
        result = build_ict_features([signal], index)
        assert result.iloc[0]["ict_bias_encoded"] == -1

    def test_neutral_bias_encoded_as_zero(self):
        signal = _make_signal(direction=TradeDirection.NEUTRAL)
        index = pd.DatetimeIndex([SIGNAL_TIME])
        result = build_ict_features([signal], index)
        assert result.iloc[0]["ict_bias_encoded"] == 0

    def test_no_signals_returns_all_nan(self):
        index = pd.DatetimeIndex(pd.date_range("2024-06-15", periods=10, freq="1h"))
        result = build_ict_features([], index)
        assert len(result) == 10
        for name in ICT_FEATURE_NAMES:
            assert result[name].isna().all()

    def test_mismatched_timestamps_fill_nan(self):
        signal = _make_signal(signal_time=datetime(2024, 6, 15, 5, 0, 0))
        index = pd.DatetimeIndex(pd.date_range("2024-06-15", periods=10, freq="1h"))
        result = build_ict_features([signal], index)
        assert len(result) == 10
        non_null = result.dropna(how="all")
        assert len(non_null) == 1

    def test_multiple_signals_mapped_correctly(self):
        s1 = _make_signal(signal_time=SIGNAL_TIME, confidence=0.7)
        s2 = _make_signal(signal_time=SIGNAL_TIME_2, confidence=0.85)
        index = pd.DatetimeIndex([SIGNAL_TIME, SIGNAL_TIME_2])
        result = build_ict_features([s1, s2], index)
        assert result.iloc[0]["ict_confluence_score"] == 0.7
        assert result.iloc[1]["ict_confluence_score"] == 0.85


class TestBuildFeatureMatrixWithICT:
    def test_without_signals_unchanged(self):
        df = _make_df(100)
        features = build_feature_matrix(df)
        for name in ICT_FEATURE_NAMES:
            assert name not in features.columns

    def test_with_signals_includes_ict_columns(self):
        df = _make_df(100)
        signal = _make_signal(signal_time=df["date"].iloc[50])
        features = build_feature_matrix(df, signals=[signal])
        for name in ICT_FEATURE_NAMES:
            assert name in features.columns

    def test_with_signals_correct_row_populated(self):
        df = _make_df(100)
        signal = _make_signal(signal_time=df["date"].iloc[50], confidence=0.9)
        features = build_feature_matrix(df, signals=[signal])
        assert features.iloc[50]["ict_confluence_score"] == 0.9
        assert features.iloc[0]["ict_confluence_score"] != 0.9

    def test_backward_compatible_base_features(self):
        df = _make_df(100)
        base = build_feature_matrix(df)
        with_signals = build_feature_matrix(df, signals=[])
        for col in base.columns:
            assert col in with_signals.columns
        assert len(with_signals.columns) == len(base.columns)


class TestConfluenceSignalSubScores:
    def test_default_sub_scores_are_zero(self):
        signal = ConfluenceSignal(
            direction=TradeDirection.LONG,
            strength=SignalStrength.MODERATE,
            confidence_score=0.6,
            entry_price=1.1,
            stop_loss=1.09,
            take_profit_1=1.11,
            take_profit_2=1.12,
            take_profit_3=1.13,
            signal_time=SIGNAL_TIME,
            rationale="test",
        )
        assert signal.structure_score == 0.0
        assert signal.ob_score == 0.0
        assert signal.fvg_score == 0.0
        assert signal.liq_sweep_score == 0.0
        assert signal.pd_zone_score == 0.0
        assert signal.session_score == 0.0
