"""Position sizing and risk management.

Implements Kelly criterion, fixed fractional, ATR-based dynamic sizing,
and other sizing methods.
"""
from abc import ABC, abstractmethod
from typing import Optional
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


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


class ATRDynamicSizing(SizingMethod):
    """ATR-based dynamic position sizing.

    Risk is the constant, size is the variable.
    High volatility → wider stop → smaller position → same dollar risk.

    The stop distance is derived from ATR rather than a fixed stop-loss price:
        effective_stop_distance = atr_multiplier × ATR(14)

    This keeps dollar risk consistent across varying volatility regimes.

    When ``atr`` is not supplied to :meth:`calculate_size`, the class falls
    back to the explicit ``stop_loss`` distance (behaving like
    :class:`FixedFractional`) so the ABC contract stays satisfied for callers
    that have not been wired to pass ATR yet.

    Configuration (via constructor):
        atr_multiplier: K — ATR multiplier for stop distance (default 1.5).
        risk_pct: Default risk fraction (default 0.005 = 0.5 %, FTMO-safe).
        contract_size: Units per standard lot (default 100 000).
        pip_value: Dollar value of one pip movement per standard lot
            (default 10.0, i.e. $10 / pip / lot for EURUSD).

    The ``contract_size`` and ``pip_value`` attributes are stored so that
    downstream code or future subclasses can convert the raw price-unit
    result into lots if needed.  The base ``calculate_size`` return value
    follows the same convention as the other sizing methods in this module
    (price-unit-denominated).
    """

    def __init__(
        self,
        atr_multiplier: float = 1.5,
        risk_pct: float = 0.005,
        contract_size: float = 100_000.0,
        pip_value: float = 10.0,
    ):
        if atr_multiplier <= 0:
            raise ValueError("atr_multiplier must be positive")
        if risk_pct <= 0 or risk_pct > 1.0:
            raise ValueError("risk_pct must be in (0, 1.0]")
        self.atr_multiplier = atr_multiplier
        self.default_risk_pct = risk_pct
        self.contract_size = contract_size
        self.pip_value = pip_value

    def calculate_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        risk_pct: Optional[float] = None,
        win_rate: Optional[float] = None,
        avg_win: Optional[float] = None,
        avg_loss: Optional[float] = None,
        atr: Optional[float] = None,
    ) -> float:
        """Return position size derived from ATR-based stop distance.

        Args:
            account_balance: Current account equity.
            entry_price: Planned entry price.
            stop_loss: Planned stop-loss price (fallback when *atr* is None).
            risk_pct: Override for constructor ``default_risk_pct``.
            atr: Current ATR(14) value in price units.  When provided,
                the stop distance is ``atr_multiplier × atr`` instead of
                ``|entry_price - stop_loss|``.
        """
        if account_balance <= 0:
            return 0.0

        effective_risk = risk_pct if risk_pct is not None else self.default_risk_pct
        if effective_risk <= 0:
            return 0.0

        # Derive stop distance: prefer ATR, fall back to explicit SL
        if atr is not None and atr > 0:
            stop_distance = self.atr_multiplier * atr
        else:
            stop_distance = abs(entry_price - stop_loss)

        if stop_distance == 0:
            return 0.0

        risk_amount = account_balance * effective_risk
        size = risk_amount / stop_distance

        logger.debug(
            "ATRDynamicSizing: balance=%.2f risk_pct=%.4f atr=%s K=%.2f "
            "stop_dist=%.6f size=%.4f",
            account_balance,
            effective_risk,
            f"{atr:.6f}" if atr is not None else "N/A",
            self.atr_multiplier,
            stop_distance,
            size,
        )
        return size


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
