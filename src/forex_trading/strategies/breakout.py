"""Breakout strategy using Donchian channel with volume filter.

Donchian channel breakout with volume confirmation.
"""
import pandas as pd
import numpy as np
from ..services.backtest.strategies import Strategy


class BreakoutStrategy(Strategy):
    @property
    def name(self) -> str:
        return "Breakout"

    def __init__(self, channel_period: int = 20, volume_ma_period: int = 20, 
                 volume_threshold: float = 1.5):
        self.channel_period = channel_period
        self.volume_ma_period = volume_ma_period
        self.volume_threshold = volume_threshold

    def get_parameters(self) -> dict:
        return {
            'channel_period': self.channel_period,
            'volume_ma_period': self.volume_ma_period,
            'volume_threshold': self.volume_threshold
        }

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=data.index)

        donchian_upper = data['high'].rolling(window=self.channel_period).max()
        donchian_lower = data['low'].rolling(window=self.channel_period).min()
        donchian_middle = (donchian_upper + donchian_lower) / 2

        volume_ma = data['volume'].rolling(window=self.volume_ma_period).mean()
        volume_ratio = data['volume'] / volume_ma

        close = data['close']
        prev_close = close.shift(1)

        bullish_breakout = (
            (close > donchian_upper.shift(1)) &
            (prev_close <= donchian_upper.shift(1)) &
            (volume_ratio > self.volume_threshold)
        )

        bearish_breakout = (
            (close < donchian_lower.shift(1)) &
            (prev_close >= donchian_lower.shift(1)) &
            (volume_ratio > self.volume_threshold)
        )

        signals[bullish_breakout] = 1
        signals[bearish_breakout] = -1

        return signals
