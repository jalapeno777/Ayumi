"""Strategy protocol for the backtesting engine.

All trading strategies must implement this protocol.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import pandas as pd


class SignalType(Enum):
    LONG = 1
    SHORT = -1
    NEUTRAL = 0


@dataclass
class Signal:
    type: SignalType
    strength: float
    timestamp: pd.Timestamp
    metadata: dict


@dataclass
class StopLossTakeProfit:
    stop_loss: float
    take_profit: float


class Strategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        pass

    @abstractmethod
    def get_parameters(self) -> dict:
        pass

    def validate_data(self, data: pd.DataFrame) -> bool:
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        return all(col in data.columns for col in required_cols)

    def generate_sl_tp(self, data: pd.DataFrame, signal: float, entry_price: float,
                       atr_period: int = 14, sl_atr_multiplier: float = 1.5,
                       tp_atr_multiplier: float = 2.0) -> Optional[StopLossTakeProfit]:
        if atr_period < 1 or sl_atr_multiplier <= 0 or tp_atr_multiplier <= 0:
            return None
        high = data['high']
        low = data['low']
        close = data['close']
        tr = pd.concat([
            high - low,
            abs(high - close.shift(1)),
            abs(low - close.shift(1))
        ], axis=1).max(axis=1)
        atr = tr.rolling(window=atr_period).mean()
        current_atr = atr.iloc[-1]
        if pd.isna(current_atr) or current_atr <= 0:
            return None
        if signal > 0:
            sl = entry_price - current_atr * sl_atr_multiplier
            tp = entry_price + current_atr * tp_atr_multiplier
        else:
            sl = entry_price + current_atr * sl_atr_multiplier
            tp = entry_price - current_atr * tp_atr_multiplier
        return StopLossTakeProfit(stop_loss=sl, take_profit=tp)
