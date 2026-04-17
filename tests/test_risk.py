"""Tests for risk management and position sizing."""
import pytest
import pandas as pd
import numpy as np
from src.forex_trading.services.risk.position_sizing import (
    FixedFractional, KellyCriterion, KellyHalfFractional, FixedLotSize, RiskCalculator
)


def test_fixed_fractional():
    sizing = FixedFractional()
    size = sizing.calculate_size(
        account_balance=10000.0,
        entry_price=1.1000,
        stop_loss=1.0950,
        risk_pct=0.02
    )

    assert size > 0
    expected_size = (10000 * 0.02) / (1.1000 - 1.0950)
    assert abs(size - expected_size) < 0.01


def test_kelly_criterion():
    sizing = KellyCriterion()
    size = sizing.calculate_size(
        account_balance=10000.0,
        entry_price=1.1000,
        stop_loss=1.0950,
        risk_pct=0.02,
        win_rate=0.55,
        avg_win=100.0,
        avg_loss=80.0
    )

    assert size > 0


def test_kelly_half_fractional():
    sizing = KellyHalfFractional()
    size = sizing.calculate_size(
        account_balance=10000.0,
        entry_price=1.1000,
        stop_loss=1.0950,
        risk_pct=0.02
    )

    assert size > 0


def test_fixed_lot_size():
    sizing = FixedLotSize(lot_size=0.5)
    size = sizing.calculate_size(
        account_balance=10000.0,
        entry_price=1.1000,
        stop_loss=1.0950,
        risk_pct=0.02
    )

    assert size == 0.5


def test_risk_calculator_sharpe():
    returns = pd.Series([0.01, -0.005, 0.02, 0.015, -0.01])
    sharpe = RiskCalculator.calculate_sharpe(returns)

    assert isinstance(sharpe, float)


def test_risk_calculator_win_rate():
    trades = [
        {'pnl': 100},
        {'pnl': -50},
        {'pnl': 200},
        {'pnl': -30},
    ]
    win_rate = RiskCalculator.calculate_win_rate(trades)

    assert win_rate == 0.5


def test_risk_calculator_profit_factor():
    trades = [
        {'pnl': 100},
        {'pnl': -50},
        {'pnl': 200},
        {'pnl': -40},
    ]
    pf = RiskCalculator.calculate_profit_factor(trades)

    assert pf == 300 / 90


def test_risk_calculator_expectancy():
    trades = [
        {'pnl': 100},
        {'pnl': -50},
        {'pnl': 200},
    ]
    exp = RiskCalculator.calculate_expectancy(trades)

    assert exp == 250 / 3
