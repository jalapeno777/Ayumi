"""Regime-aware trend following strategy.

Trend following that adapts based on market regime classification.
Requires regime inputs from Sage's market research.
"""
import pandas as pd
import numpy as np
from typing import Optional
from ..services.backtest.strategies import Strategy


class RegimeAwareStrategy(Strategy):
    @property
    def name(self) -> str:
        return "RegimeAwareTrend"

    def __init__(self, fast_period: int = 20, slow_period: int = 50, 
                 atr_period: int = 14, regime: Optional[pd.Series] = None):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.regime = regime

    def get_parameters(self) -> dict:
        return {
            'fast_period': self.fast_period,
            'slow_period': self.slow_period,
            'atr_period': self.atr_period
        }

    def set_regime(self, regime: pd.Series):
        self.regime = regime

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=data.index)

        if self.regime is None:
            return signals

        fast_ema = data['close'].ewm(span=self.fast_period, adjust=False).mean()
        slow_ema = data['close'].ewm(span=self.slow_period, adjust=False).mean()
        atr = self._calculate_atr(data, self.atr_period)

        ema_cross = fast_ema - slow_ema
        ema_cross_normalized = ema_cross / atr

        aligned_bullish = (ema_cross > 0) & (self.regime.isin(['trending_up', 'risk_on']))
        aligned_bearish = (ema_cross < 0) & (self.regime.isin(['trending_down', 'risk_off']))

        strong_bullish = aligned_bullish & (ema_cross_normalized > 0.5)
        strong_bearish = aligned_bearish & (ema_cross_normalized < -0.5)

        signals[strong_bullish] = 1
        signals[strong_bearish] = -1

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


class RegimeClassifier:
    @staticmethod
    def classify_regime(data: pd.DataFrame, adx_period: int = 14) -> pd.Series:
        high = data['high']
        low = data['low']
        close = data['close']

        tr = pd.concat([
            high - low,
            abs(high - close.shift(1)),
            abs(low - close.shift(1))
        ], axis=1).max(axis=1)
        atr = tr.rolling(window=adx_period).mean()

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0

        atr_sma = atr.rolling(window=adx_period).mean()
        plus_di = 100 * (plus_dm.rolling(window=adx_period).mean() / atr_sma)
        minus_di = 100 * (minus_dm.rolling(window=adx_period).mean() / atr_sma)

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=adx_period).mean()

        volatility = atr / close * 100
        volatility_ma = volatility.rolling(window=20).mean()

        regime = pd.Series('ranging', index=data.index)

        regime[adx > 25] = 'trending'
        regime[(adx > 25) & (plus_di > minus_di) & (close.diff() > 0)] = 'trending_up'
        regime[(adx > 25) & (minus_di > plus_di) & (close.diff() < 0)] = 'trending_down'
        regime[volatility > volatility_ma * 1.5] = 'high_volatility'
        regime[(close.pct_change().rolling(window=10).mean() > 0.001)] = 'risk_on'
        regime[(close.pct_change().rolling(window=10).mean() < -0.001)] = 'risk_off'

        return regime
