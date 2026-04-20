"""Carry trade signal based on interest rate differentials.

Generates signals based on interest rate differentials between currency pairs.
"""
import pandas as pd
import numpy as np
from typing import Optional
from ..services.backtest.strategies import Strategy


class CarryTradeStrategy(Strategy):
    @property
    def name(self) -> str:
        return "CarryTrade"

    RATE_DATA = {
        'EURUSD': {'base_rate': 4.25, 'quote_rate': 5.50},
        'GBPUSD': {'base_rate': 4.75, 'quote_rate': 5.50},
        'USDJPY': {'base_rate': 5.50, 'quote_rate': 0.25},
        'USDCHF': {'base_rate': 5.50, 'quote_rate': 1.00},
        'AUDUSD': {'base_rate': 4.35, 'quote_rate': 5.50},
        'USDCAD': {'base_rate': 5.50, 'quote_rate': 3.75},
        'NZDUSD': {'base_rate': 4.25, 'quote_rate': 5.50},
        'EURGBP': {'base_rate': 4.25, 'quote_rate': 4.75},
        'EURJPY': {'base_rate': 4.25, 'quote_rate': 0.25},
        'GBPJPY': {'base_rate': 4.75, 'quote_rate': 0.25},
    }

    def __init__(self, rate_diff_threshold: float = 1.0, 
                 momentum_period: int = 20,
                 use_dynamic_threshold: bool = True):
        self.rate_diff_threshold = rate_diff_threshold
        self.momentum_period = momentum_period
        self.use_dynamic_threshold = use_dynamic_threshold

    def get_parameters(self) -> dict:
        return {
            'rate_diff_threshold': self.rate_diff_threshold,
            'momentum_period': self.momentum_period,
            'use_dynamic_threshold': self.use_dynamic_threshold
        }

    def set_rates(self, pair: str, base_rate: float, quote_rate: float):
        self.RATE_DATA[pair] = {'base_rate': base_rate, 'quote_rate': quote_rate}

    def generate_signals(self, data: pd.DataFrame, pair: str = "EURUSD") -> pd.Series:
        signals = pd.Series(0, index=data.index)

        if pair not in self.RATE_DATA:
            return signals

        rates = self.RATE_DATA[pair]
        rate_diff = rates['quote_rate'] - rates['base_rate']

        momentum = data['close'].pct_change(self.momentum_period)

        dynamic_threshold = self.rate_diff_threshold
        if self.use_dynamic_threshold:
            dynamic_threshold = max(self.rate_diff_threshold, abs(momentum.std() * 2))

        if rate_diff > dynamic_threshold:
            signals[momentum > 0] = 1
        elif rate_diff < -dynamic_threshold:
            signals[momentum < 0] = -1

        return signals

    def get_rate_differential(self, pair: str) -> float:
        if pair not in self.RATE_DATA:
            return 0.0
        rates = self.RATE_DATA[pair]
        return rates['quote_rate'] - rates['base_rate']

    def get_annualized_carry(self, pair: str, lot_size: float = 0.1) -> float:
        rate_diff = self.get_rate_differential(pair)
        pip_value = lot_size * 100000 * 0.0001
        daily_carry = pip_value * rate_diff / 365
        return daily_carry * 252
