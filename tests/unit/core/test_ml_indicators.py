"""Tests for ml/features.py indicator functions."""

import numpy as np
import pandas as pd
import pytest
from ml.features import keltner_channels, mfi, vwap


@pytest.fixture
def sample_ohlcv():
    n = 100
    np.random.seed(42)
    close = pd.Series(
        1.1000 + np.cumsum(np.random.randn(n) * 0.0005),
        name="close",
    )
    high = close + abs(np.random.randn(n) * 0.0003)
    low = close - abs(np.random.randn(n) * 0.0003)
    opn = close + np.random.randn(n) * 0.0001
    volume = pd.Series(np.random.randint(100, 10000, n).astype(float))
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    return pd.DataFrame(
        {
            "open": opn,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "date": dates,
        }
    )


class TestKeltnerChannels:
    def test_returns_three_series(self, sample_ohlcv):
        upper, mid, lower = keltner_channels(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
        )
        assert isinstance(upper, pd.Series)
        assert isinstance(mid, pd.Series)
        assert isinstance(lower, pd.Series)

    def test_upper_above_mid(self, sample_ohlcv):
        upper, mid, lower = keltner_channels(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
        )
        valid_idx = upper.dropna().index.intersection(mid.dropna().index)
        assert (upper[valid_idx] >= mid[valid_idx]).all()

    def test_lower_below_mid(self, sample_ohlcv):
        upper, mid, lower = keltner_channels(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
        )
        valid_idx = lower.dropna().index.intersection(mid.dropna().index)
        assert (lower[valid_idx] <= mid[valid_idx]).all()

    def test_custom_parameters(self, sample_ohlcv):
        upper, mid, lower = keltner_channels(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            ema_period=10,
            atr_period=5,
            atr_mult=2.0,
        )
        assert len(upper) == len(sample_ohlcv)

    def test_narrower_atr_mult(self, sample_ohlcv):
        narrow_upper, _, narrow_lower = keltner_channels(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            atr_mult=1.0,
        )
        wide_upper, _, wide_lower = keltner_channels(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            atr_mult=3.0,
        )
        valid_idx = narrow_upper.dropna().index.intersection(wide_upper.dropna().index)
        narrow_width = narrow_upper[valid_idx] - narrow_lower[valid_idx]
        wide_width = wide_upper[valid_idx] - wide_lower[valid_idx]
        assert (wide_width >= narrow_width).all()

    def test_initial_nans(self, sample_ohlcv):
        upper, mid, lower = keltner_channels(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            ema_period=20,
            atr_period=10,
        )
        assert upper.iloc[:9].isna().all()
        assert lower.iloc[:9].isna().all()


class TestMFI:
    def test_returns_series(self, sample_ohlcv):
        result = mfi(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            sample_ohlcv["volume"],
        )
        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_ohlcv)

    def test_range_0_to_100(self, sample_ohlcv):
        result = mfi(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            sample_ohlcv["volume"],
        )
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_custom_period(self, sample_ohlcv):
        result = mfi(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            sample_ohlcv["volume"],
            period=20,
        )
        assert isinstance(result, pd.Series)

    def test_initial_nans(self, sample_ohlcv):
        result = mfi(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            sample_ohlcv["volume"],
            period=14,
        )
        assert result.iloc[:13].isna().all()

    def test_zero_volume(self, sample_ohlcv):
        zero_vol = pd.Series(0.0, index=sample_ohlcv.index)
        result = mfi(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            zero_vol,
        )
        valid = result.dropna()
        assert len(valid) >= 0


class TestVWAP:
    def test_returns_series(self, sample_ohlcv):
        result = vwap(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            sample_ohlcv["volume"],
            sample_ohlcv["date"],
        )
        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_ohlcv)

    def test_vwap_near_typical_price(self, sample_ohlcv):
        result = vwap(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            sample_ohlcv["volume"],
            sample_ohlcv["date"],
        )
        typical = (sample_ohlcv["high"] + sample_ohlcv["low"] + sample_ohlcv["close"]) / 3
        valid = result.dropna()
        idx = valid.index
        diff = abs(valid - typical[idx])
        assert diff.mean() < 0.005

    def test_resets_on_new_day(self, sample_ohlcv):
        result = vwap(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            sample_ohlcv["volume"],
            sample_ohlcv["date"],
        )
        dates = sample_ohlcv["date"]
        for i in range(1, len(dates)):
            if dates.iloc[i].date() != dates.iloc[i - 1].date():
                if not np.isnan(result.iloc[i]) and not np.isnan(result.iloc[i - 1]):
                    assert abs(result.iloc[i] - result.iloc[i - 1]) > 0.0001

    def test_single_bar(self):
        high = pd.Series([1.1010])
        low = pd.Series([1.0990])
        close = pd.Series([1.1000])
        vol = pd.Series([1000.0])
        d = pd.Series([pd.Timestamp("2025-01-01")])
        result = vwap(high, low, close, vol, d)
        expected = (1.1010 + 1.0990 + 1.1000) / 3
        assert result.iloc[0] == pytest.approx(expected, abs=0.0001)
