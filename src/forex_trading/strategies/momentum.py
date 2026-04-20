"""Momentum crossover strategy with ADX filter.

EMA 20/50 crossover with ADX trend strength filter.
"""
import pandas as pd
import numpy as np
from ..services.backtest.strategies import Strategy, SignalType


class MomentumCrossoverStrategy(Strategy):
    @property
    def name(self) -> str:
        return "MomentumCrossover"

    def __init__(self, fast_period: int = 20, slow_period: int = 50, adx_period: int = 14, adx_threshold: float = 25.0):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold

    def get_parameters(self) -> dict:
        return {
            'fast_period': self.fast_period,
            'slow_period': self.slow_period,
            'adx_period': self.adx_period,
            'adx_threshold': self.adx_threshold
        }

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=data.index)

        fast_ema = data['close'].ewm(span=self.fast_period, adjust=False).mean()
        slow_ema = data['close'].ewm(span=self.slow_period, adjust=False).mean()

        adx = self._calculate_adx(data, self.adx_period)

        crossover = (fast_ema > slow_ema) & (fast_ema.shift(1) <= slow_ema.shift(1))
        crossunder = (fast_ema < slow_ema) & (fast_ema.shift(1) >= slow_ema.shift(1))

        signals[crossover & (adx > self.adx_threshold)] = 1
        signals[crossunder & (adx > self.adx_threshold)] = -1

        return signals

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
