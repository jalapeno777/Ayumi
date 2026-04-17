"""Regime-Switching Momentum strategy.

Switches between trend-following and mean-reversion based on detected market regime.
Uses ADX, ATR, and VIX for regime detection.
"""
import pandas as pd
import numpy as np
from typing import Optional
from ..services.backtest.strategies import Strategy


class RegimeSwitchingMomentumStrategy(Strategy):
    @property
    def name(self) -> str:
        return "RegimeSwitchingMomentum"

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 50,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        atr_period: int = 14,
        vix_period: int = 20,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        bb_period: int = 20,
        bb_std: float = 2.0,
        vix_data: Optional[pd.Series] = None,
        regime_confidence_threshold: float = 0.6
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.atr_period = atr_period
        self.vix_period = vix_period
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.vix_data = vix_data
        self.regime_confidence_threshold = regime_confidence_threshold

    def get_parameters(self) -> dict:
        return {
            'fast_period': self.fast_period,
            'slow_period': self.slow_period,
            'adx_period': self.adx_period,
            'adx_threshold': self.adx_threshold,
            'atr_period': self.atr_period,
            'vix_period': self.vix_period,
            'rsi_period': self.rsi_period,
            'rsi_oversold': self.rsi_oversold,
            'rsi_overbought': self.rsi_overbought,
            'bb_period': self.bb_period,
            'bb_std': self.bb_std,
            'regime_confidence_threshold': self.regime_confidence_threshold
        }

    def set_vix(self, vix_data: pd.Series):
        self.vix_data = vix_data

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=data.index)
        regime = self._classify_regime(data)
        trend_signals = self._generate_trend_signals(data, regime)
        mean_rev_signals = self._generate_mean_reversion_signals(data, regime)
        signals = np.where(regime['is_trending'] == 1, trend_signals, mean_rev_signals)
        return pd.Series(signals, index=data.index)

    def _classify_regime(self, data: pd.DataFrame) -> pd.DataFrame:
        high = data['high']
        low = data['low']
        close = data['close']

        atr = self._calculate_atr(data, self.atr_period)
        adx = self._calculate_adx(data, self.adx_period)

        volatility = atr / close * 100
        volatility_ma = volatility.rolling(window=20).mean()

        price_change = close.pct_change()
        momentum = price_change.rolling(window=10).mean()

        regime = pd.DataFrame(index=data.index)
        regime['adx'] = adx
        regime['volatility'] = volatility
        regime['momentum'] = momentum

        regime['is_trending'] = 0
        regime.loc[adx > self.adx_threshold, 'is_trending'] = 1

        regime['is_high_vol'] = (volatility > volatility_ma * 1.5).astype(int)

        if self.vix_data is not None:
            aligned_vix = self.vix_data.reindex(data.index, method='ffill')
            vix_ma = aligned_vix.rolling(window=self.vix_period).mean()
            vix_percentile = (aligned_vix - aligned_vix.rolling(window=252).min()) / \
                            (aligned_vix.rolling(window=252).max() - aligned_vix.rolling(window=252).min())
            regime['vix'] = aligned_vix
            regime['vix_percentile'] = vix_percentile
            regime.loc[vix_percentile > 0.8, 'is_trending'] = 0

        regime['trend_strength'] = np.minimum(adx / 50.0, 1.0)
        regime['mean_reversion_strength'] = np.minimum(volatility / (volatility_ma * 1.5), 1.0)

        regime['confidence'] = np.maximum(
            regime['trend_strength'],
            regime['mean_reversion_strength']
        )

        return regime

    def _generate_trend_signals(self, data: pd.DataFrame, regime: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=data.index)
        close = data['close']

        fast_ema = close.ewm(span=self.fast_period, adjust=False).mean()
        slow_ema = close.ewm(span=self.slow_period, adjust=False).mean()

        ema_cross = fast_ema - slow_ema
        ema_cross_normalized = ema_cross / self._calculate_atr(data, self.atr_period)

        plus_di = regime.get('plus_di', self._calculate_plus_di(data))
        minus_di = regime.get('minus_di', self._calculate_minus_di(data))

        bullish_cross = (fast_ema > slow_ema) & (fast_ema.shift(1) <= slow_ema.shift(1))
        bearish_cross = (fast_ema < slow_ema) & (fast_ema.shift(1) >= slow_ema.shift(1))

        strong_bullish = bullish_cross & (ema_cross_normalized > 0.3) & (regime['adx'] > self.adx_threshold)
        strong_bearish = bearish_cross & (ema_cross_normalized < -0.3) & (regime['adx'] > self.adx_threshold)

        signals[strong_bullish] = 1
        signals[strong_bearish] = -1

        return signals

    def _generate_mean_reversion_signals(self, data: pd.DataFrame, regime: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=data.index)
        close = data['close']

        rsi = self._calculate_rsi(close, self.rsi_period)
        bb_upper, bb_lower, _ = self._calculate_bollinger_bands(close)

        oversold_bounce = (rsi < self.rsi_oversold) & (close < bb_lower) & (close.shift(1) >= bb_lower)
        overbought_drop = (rsi > self.rsi_overbought) & (close > bb_upper) & (close.shift(1) <= bb_upper)

        signals[oversold_bounce] = 1
        signals[overbought_drop] = -1

        return signals

    def _calculate_atr(self, data: pd.DataFrame, period: int) -> pd.Series:
        high = data['high']
        low = data['low']
        close = data['close']

        tr = pd.concat([
            high - low,
            abs(high - close.shift(1)),
            abs(low - close.shift(1))
        ], axis=1).max(axis=1)

        atr = tr.rolling(window=period).mean()
        return atr

    def _calculate_adx(self, data: pd.DataFrame, period: int) -> pd.Series:
        high = data['high']
        low = data['low']
        close = data['close']

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = tr.rolling(window=period, min_periods=1).mean()

        plus_di = 100 * (plus_dm.rolling(window=period, min_periods=1).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period, min_periods=1).mean() / atr)

        di_sum = plus_di + minus_di
        di_sum = di_sum.replace(0, np.nan)

        dx = 100 * abs(plus_di - minus_di) / di_sum
        adx = dx.rolling(window=period, min_periods=1).mean()

        return adx

    def _calculate_plus_di(self, data: pd.DataFrame) -> pd.Series:
        high = data['high']
        low = data['low']
        close = data['close']

        plus_dm = high.diff().clip(lower=0)
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=self.adx_period, min_periods=1).mean()

        plus_di = 100 * (plus_dm.rolling(window=self.adx_period, min_periods=1).mean() / atr)
        return plus_di

    def _calculate_minus_di(self, data: pd.DataFrame) -> pd.Series:
        high = data['high']
        low = data['low']
        close = data['close']

        minus_dm = (-low.diff()).clip(lower=0)
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=self.adx_period, min_periods=1).mean()

        minus_di = 100 * (minus_dm.rolling(window=self.adx_period, min_periods=1).mean() / atr)
        return minus_di

    def _calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def _calculate_bollinger_bands(self, prices: pd.Series) -> tuple:
        middle = prices.rolling(window=self.bb_period).mean()
        std = prices.rolling(window=self.bb_period).std()
        upper = middle + (std * self.bb_std)
        lower = middle - (std * self.bb_std)
        return upper, lower, middle