"""Mean reversion strategy with RSI and Bollinger Bands.

RSI with Bollinger Band confirmation for mean reversion signals.
"""
import pandas as pd
import numpy as np
from ..services.backtest.strategies import Strategy


class MeanReversionStrategy(Strategy):
    @property
    def name(self) -> str:
        return "MeanReversion"

    def __init__(self, rsi_period: int = 14, rsi_oversold: float = 30.0, rsi_overbought: float = 70.0,
                 bb_period: int = 20, bb_std: float = 2.0):
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.bb_period = bb_period
        self.bb_std = bb_std

    def get_parameters(self) -> dict:
        return {
            'rsi_period': self.rsi_period,
            'rsi_oversold': self.rsi_oversold,
            'rsi_overbought': self.rsi_overbought,
            'bb_period': self.bb_period,
            'bb_std': self.bb_std
        }

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=data.index)

        rsi = self._calculate_rsi(data['close'], self.rsi_period)
        bb_upper, bb_lower, bb_middle = self._calculate_bollinger_bands(data['close'])

        close = data['close']

        oversold_bounce = (rsi < self.rsi_oversold) & (close < bb_lower) & (close.shift(1) >= bb_lower)
        overbought_drop = (rsi > self.rsi_overbought) & (close > bb_upper) & (close.shift(1) <= bb_upper)

        signals[oversold_bounce] = 1
        signals[overbought_drop] = -1

        return signals

    def _calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def _calculate_bollinger_bands(self, prices: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
        middle = prices.rolling(window=self.bb_period).mean()
        std = prices.rolling(window=self.bb_period).std()
        upper = middle + (std * self.bb_std)
        lower = middle - (std * self.bb_std)
        return upper, lower, middle
