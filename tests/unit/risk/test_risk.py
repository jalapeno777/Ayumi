"""Tests for risk management and position sizing.

Rewritten for post-refactor API (card 99a4d28d).
- Class-based sizing → functional API
- FixedFractional() → fixed_fractional()
- KellyCriterion() → kelly_criterion()
"""

from __future__ import annotations

import pytest

from quant.position_sizing import (
    DynamicSizingConfig,
    fixed_fractional,
    kelly_criterion,
    dynamic_sizing,
    check_position_limits,
)


class TestFixedFractional:
    def test_basic_sizing(self):
        size = fixed_fractional(
            account_balance=10_000.0,
            risk_pct=2.0,
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert size > 0
        # risk_amount = 10000 * 0.02 = 200
        # stop_distance = 0.005
        # risk_per_lot = 0.005 * 100000 = 500
        # lots = 200 / 500 = 0.4
        assert size == pytest.approx(0.4, rel=0.01)

    def test_zero_balance_returns_zero(self):
        size = fixed_fractional(0, 2.0, 1.1, 1.09)
        assert size == 0.0

    def test_zero_risk_returns_zero(self):
        size = fixed_fractional(10_000, 0, 1.1, 1.09)
        assert size == 0.0

    def test_zero_stop_distance_returns_zero(self):
        size = fixed_fractional(10_000, 2.0, 1.1, 1.1)
        assert size == 0.0

    def test_short_trade(self):
        size = fixed_fractional(
            account_balance=10_000.0,
            risk_pct=1.0,
            entry_price=1.1000,
            stop_loss=1.1050,
        )
        assert size > 0
        # risk = 100, distance = 0.005, per_lot = 500
        assert size == pytest.approx(0.2, rel=0.01)


class TestKellyCriterion:
    def test_positive_edge(self):
        kelly = kelly_criterion(win_rate=0.6, avg_win=100, avg_loss=50)
        assert kelly > 0
        # b = 100/50 = 2
        # kelly = (2*0.6 - 0.4) / 2 = 0.8/2 = 0.4
        # half-kelly = 0.2
        assert kelly == pytest.approx(0.2, rel=0.01)

    def test_no_edge(self):
        kelly = kelly_criterion(win_rate=0.5, avg_win=100, avg_loss=100)
        # b=1, kelly = (1*0.5 - 0.5)/1 = 0
        assert kelly == 0.0

    def test_negative_edge(self):
        kelly = kelly_criterion(win_rate=0.3, avg_win=100, avg_loss=100)
        assert kelly == 0.0

    def test_zero_loss_returns_zero(self):
        kelly = kelly_criterion(win_rate=0.9, avg_win=100, avg_loss=0)
        assert kelly == 0.0

    def test_capped_at_half(self):
        kelly = kelly_criterion(win_rate=0.99, avg_win=1000, avg_loss=1)
        assert kelly <= 0.5


class TestDynamicSizing:
    def test_no_streak_no_pnl(self):
        size = dynamic_sizing(1.0, 0.0, 0, 0)
        assert size == pytest.approx(1.0)

    def test_winning_streak_increases(self):
        size = dynamic_sizing(1.0, 100.0, 3, 0)
        assert size > 1.0

    def test_losing_streak_decreases(self):
        size = dynamic_sizing(1.0, -100.0, 0, 3)
        assert size < 1.0

    def test_clamped_to_max(self):
        config = DynamicSizingConfig(max_multiplier=1.5)
        size = dynamic_sizing(1.0, 10_000, 100, 0, config)
        assert size == pytest.approx(1.5)

    def test_clamped_to_min(self):
        config = DynamicSizingConfig(min_multiplier=0.5)
        size = dynamic_sizing(1.0, -10_000, 0, 100, config)
        assert size == pytest.approx(0.5)

    def test_zero_base_returns_zero(self):
        size = dynamic_sizing(0, 100, 5, 0)
        assert size == 0.0


class TestCheckPositionLimits:
    def test_within_limits(self):
        assert (
            check_position_limits(
                {"EURUSD": 0.5}, "GBPUSD", max_per_pair=1.0, max_total=3.0
            )
            is True
        )

    def test_max_per_pair(self):
        assert (
            check_position_limits(
                {"EURUSD": 1.0}, "EURUSD", max_per_pair=1.0, max_total=3.0
            )
            is False
        )

    def test_max_total(self):
        assert (
            check_position_limits(
                {"EURUSD": 1.5, "GBPUSD": 1.5},
                "USDJPY",
                max_per_pair=1.0,
                max_total=3.0,
            )
            is False
        )

    def test_new_pair_no_positions(self):
        assert (
            check_position_limits({}, "EURUSD", max_per_pair=1.0, max_total=3.0) is True
        )
