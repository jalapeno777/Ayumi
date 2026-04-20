"""Position sizing and risk management.

Implements Kelly criterion, fixed fractional, and other sizing methods.
"""
from abc import ABC, abstractmethod
from typing import Optional
import numpy as np
import pandas as pd


class SizingMethod(ABC):
    @abstractmethod
    def calculate_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        risk_pct: float,
        win_rate: Optional[float] = None,
        avg_win: Optional[float] = None,
        avg_loss: Optional[float] = None
    ) -> float:
        pass


class FixedFractional(SizingMethod):
    def calculate_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        risk_pct: float = 0.02,
        win_rate: Optional[float] = None,
        avg_win: Optional[float] = None,
        avg_loss: Optional[float] = None
    ) -> float:
        risk_amount = account_balance * risk_pct
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return 0.0
        return risk_amount / risk_per_unit


class KellyCriterion(SizingMethod):
    def calculate_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        risk_pct: float = 0.02,
        win_rate: Optional[float] = None,
        avg_win: Optional[float] = None,
        avg_loss: Optional[float] = None
    ) -> float:
        if win_rate is None or avg_win is None or avg_loss is None:
            return FixedFractional().calculate_size(
                account_balance, entry_price, stop_loss, risk_pct
            )

        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 1.0
        kelly_pct = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio
        kelly_pct = max(0.0, min(kelly_pct, 0.25))

        risk_amount = account_balance * min(kelly_pct, risk_pct)
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return 0.0
        return risk_amount / risk_per_unit


class KellyHalfFractional(SizingMethod):
    def calculate_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        risk_pct: float = 0.02,
        win_rate: Optional[float] = None,
        avg_win: Optional[float] = None,
        avg_loss: Optional[float] = None
    ) -> float:
        if win_rate is None or avg_win is None or avg_loss is None:
            return FixedFractional().calculate_size(
                account_balance, entry_price, stop_loss, risk_pct / 2
            )

        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 1.0
        kelly_pct = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio
        kelly_pct = max(0.0, min(kelly_pct * 0.5, risk_pct))

        risk_amount = account_balance * kelly_pct
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return 0.0
        return risk_amount / risk_per_unit


class FixedLotSize(SizingMethod):
    def __init__(self, lot_size: float = 0.1):
        self.lot_size = lot_size

    def calculate_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        risk_pct: float = 0.02,
        win_rate: Optional[float] = None,
        avg_win: Optional[float] = None,
        avg_loss: Optional[float] = None
    ) -> float:
        return self.lot_size


class RiskCalculator:
    @staticmethod
    def calculate_sharpe(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
        if len(returns) < 2:
            return 0.0
        excess = returns - risk_free_rate / 252
        return np.sqrt(252) * excess.mean() / excess.std() if excess.std() > 0 else 0.0

    @staticmethod
    def calculate_sortino(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
        if len(returns) < 2:
            return 0.0
        excess = returns - risk_free_rate / 252
        downside = returns[returns < 0]
        if len(downside) == 0:
            return np.inf
        downside_std = downside.std()
        return np.sqrt(252) * excess.mean() / downside_std if downside_std > 0 else 0.0

    @staticmethod
    def calculate_max_drawdown(equity: pd.Series) -> tuple[float, int]:
        running_max = equity.expanding().max()
        drawdown = (equity - running_max) / running_max
        max_dd = abs(drawdown.min())

        in_drawdown = False
        max_duration = 0
        current_duration = 0

        for i in range(len(equity)):
            if drawdown.iloc[i] < -0.001:
                if not in_drawdown:
                    in_drawdown = True
                    current_duration = 1
                else:
                    current_duration += 1
            else:
                if in_drawdown:
                    max_duration = max(max_duration, current_duration)
                    in_drawdown = False
                    current_duration = 0

        return max_dd, max_duration

    @staticmethod
    def calculate_calmar_ratio(total_return: float, max_drawdown: float, years: float = 1.0) -> float:
        if max_drawdown == 0:
            return 0.0
        return (total_return / years) / max_drawdown

    @staticmethod
    def calculate_win_rate(trades: list) -> float:
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
        return wins / len(trades)

    @staticmethod
    def calculate_profit_factor(trades: list) -> float:
        if not trades:
            return 0.0
        gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
        gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
        return gross_profit / gross_loss if gross_loss > 0 else 0.0

    @staticmethod
    def calculate_expectancy(trades: list) -> float:
        if not trades:
            return 0.0
        return sum(t['pnl'] for t in trades) / len(trades)
