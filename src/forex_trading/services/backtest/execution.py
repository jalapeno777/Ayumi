"""Execution simulation for realistic backtesting.

Models spread, slippage, and latency effects.
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class ExecutionConfig:
    spread_pips: float = 1.0
    slippage_pips: float = 0.5
    latency_ms: int = 100
    commission_per_lot: float = 7.0
    default_lot_size: float = 0.1


@dataclass
class ExecutionResult:
    executed_price: float
    slippage: float
    spread_cost: float
    commission: float
    total_cost: float
    timestamp: pd.Timestamp


class ExecutionSimulator:
    def __init__(self, config: Optional[ExecutionConfig] = None):
        self.config = config if config is not None else ExecutionConfig()

    def execute_long(self, signal_price: float, timestamp: pd.Timestamp, 
                     lot_size: Optional[float] = None, pair: str = "EURUSD") -> ExecutionResult:
        return self._execute(signal_price, timestamp, lot_size, pair, is_long=True)

    def execute_short(self, signal_price: float, timestamp: pd.Timestamp,
                      lot_size: Optional[float] = None, pair: str = "EURUSD") -> ExecutionResult:
        return self._execute(signal_price, timestamp, lot_size, pair, is_long=False)

    def _execute(self, signal_price: float, timestamp: pd.Timestamp,
                 lot_size: Optional[float], pair: str, is_long: bool) -> ExecutionResult:
        if lot_size is None:
            lot_size = self.config.default_lot_size

        spread_cost = self._calculate_spread(pair)
        slippage = self._calculate_slippage()
        
        if is_long:
            executed_price = signal_price + spread_cost + slippage
        else:
            executed_price = signal_price - spread_cost - slippage

        commission = self.config.commission_per_lot * lot_size
        total_cost = (spread_cost + slippage) * lot_size + commission

        return ExecutionResult(
            executed_price=executed_price,
            slippage=slippage,
            spread_cost=spread_cost,
            commission=commission,
            total_cost=total_cost,
            timestamp=timestamp
        )

    def _calculate_spread(self, pair: str) -> float:
        pair_spreads = {
            'EURUSD': 1.0,
            'GBPUSD': 1.5,
            'USDJPY': 1.0,
            'USDCHF': 1.5,
            'AUDUSD': 1.2,
            'USDCAD': 1.5,
            'NZDUSD': 1.5,
            'EURGBP': 2.0,
            'EURJPY': 2.0,
            'GBPJPY': 2.5,
        }
        return pair_spreads.get(pair, 1.5) * 0.0001

    def _calculate_slippage(self) -> float:
        return np.random.uniform(0, self.config.slippage_pips) * 0.0001

    def calculate_pip_value(self, pair: str, lot_size: float) -> float:
        pip_size = 0.0001 if 'JPY' not in pair else 0.01
        return lot_size * 100000 * pip_size
