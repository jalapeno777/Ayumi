"""Unit tests for backtest FTMO guard — trailing drawdown model."""

from __future__ import annotations

import pytest

from backtest.ftmo_guard import FTMOGuard, FTMOGuardConfig


# ── Walk-through scenarios from research doc ────────────────────────────────
# Day 1: balance $10,000 → floor $9,000
# Day 5: balance $10,800 → floor $9,720
# Day 9: balance $11,200 → floor $10,080
# Day 15: balance drops to $10,050 → breach ($10,050 < $10,080)


class TestFTMOGuard1Step:
    """1-Step Challenge: 10% trailing max loss, 3% daily loss."""

    def test_initial_floor(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        assert guard.compute_floor() == pytest.approx(9_000)

    def test_trailing_floor_rises_with_peak(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        # Day 5: balance rises to $10,800
        guard.record_midnight_balance(10_800)
        assert guard.highest_midnight_balance == 10_800
        assert guard.compute_floor() == pytest.approx(9_720)

    def test_trailing_floor_never_decreases(self):
        """Key property: floor can only rise, never fall."""
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        guard.record_midnight_balance(11_000)
        assert guard.compute_floor() == pytest.approx(9_900)
        # Balance drops back, floor should NOT drop
        guard.record_midnight_balance(10_500)
        assert guard.highest_midnight_balance == 11_000
        assert guard.compute_floor() == pytest.approx(9_900)

    def test_day_15_breach_scenario(self):
        """The classic trailing floor breach."""
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        # Day-by-day progression
        guard.record_midnight_balance(10_000)  # Day 1
        assert guard.compute_floor() == pytest.approx(9_000)

        guard.record_midnight_balance(10_800)  # Day 5
        assert guard.compute_floor() == pytest.approx(9_720)

        guard.record_midnight_balance(11_200)  # Day 9
        assert guard.compute_floor() == pytest.approx(10_080)

        # Day 15: balance drops below floor
        assert guard.is_breached(10_050) is True
        assert guard.is_breached(10_080) is False  # exactly at floor is OK

    def test_remaining_total_loss_at_start(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        # At initial balance, $1000 of headroom
        assert guard.remaining_total_loss(10_000) == pytest.approx(1_000)

    def test_remaining_total_loss_after_trailing_rise(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        guard.record_midnight_balance(11_200)
        # Floor is $10,080, balance $11,200 → headroom $1,120
        assert guard.remaining_total_loss(11_200) == pytest.approx(1_120)

    def test_remaining_daily_loss(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        # Daily limit is 3% = $300
        assert guard.remaining_daily_loss(10_000) == pytest.approx(300)
        # If balance dropped $200 today
        guard._daily_start_balance = 10_000
        assert guard.remaining_daily_loss(9_800) == pytest.approx(100)
        # With open losses
        assert guard.remaining_daily_loss(9_900, open_pnl=-100) == pytest.approx(100)

    def test_check_entry_within_limits(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        # $200 risk on $10k account with $300 daily limit → OK
        assert guard.check_entry(200) is True

    def test_check_entry_exceeds_daily_limit(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        # $400 risk > $300 daily limit → rejected
        assert guard.check_entry(400) is False

    def test_check_entry_blocked_by_total_loss(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        guard.record_midnight_balance(11_200)
        # Floor $10,080; balance $10,100 leaves only $20 total headroom
        assert guard.check_entry(50, balance=10_100) is False

    def test_check_entry_uses_open_pnl(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        # $100 risk is within daily headroom ($300), but $150 floating loss
        # leaves only $150 daily headroom → $200 risk rejected
        assert guard.check_entry(200, balance=10_000, open_pnl=-150) is False
        assert guard.check_entry(100, balance=10_000, open_pnl=-150) is True

    def test_status_dict(self):
        guard = FTMOGuard(
            initial_balance=10_000,
            track_id="TEST-001",
            challenge_type="1-step",
        )
        guard.record_midnight_balance(10_500)
        s = guard.status(10_500)
        assert s["challenge_type"] == "1-step"
        assert s["initial_balance"] == 10_000
        assert s["highest_midnight_balance"] == 10_500
        assert s["current_floor"] == pytest.approx(9_450)
        assert s["remaining_total"] == pytest.approx(1_050)
        assert s["breached"] is False


class TestFTMOGuard2Step:
    """2-Step Challenge: 10% static max loss, 5% daily loss."""

    def test_initial_floor(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="2-step")
        assert guard.compute_floor() == pytest.approx(9_000)

    def test_static_floor_does_not_rise(self):
        """Key difference from 1-step: floor is always based on initial balance."""
        guard = FTMOGuard(initial_balance=10_000, challenge_type="2-step")
        guard.record_midnight_balance(11_200)
        assert guard.highest_midnight_balance == 11_200
        # Floor stays at $9,000 regardless of balance growth
        assert guard.compute_floor() == pytest.approx(9_000)

    def test_remaining_total_loss_with_growth(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="2-step")
        guard.record_midnight_balance(11_200)
        # Balance $11,200, floor $9,000 → headroom $2,200
        assert guard.remaining_total_loss(11_200) == pytest.approx(2_200)

    def test_daily_loss_two_step(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="2-step")
        assert guard.remaining_daily_loss(10_000) == pytest.approx(500)


class TestFTMOGuardConfigOverride:
    """Test custom thresholds via FTMOGuardConfig."""

    def test_custom_daily_loss(self):
        cfg = FTMOGuardConfig(
            initial_balance=10_000,
            challenge_type="1-step",
            daily_loss_pct=0.05,  # override to 5%
        )
        guard = FTMOGuard(config=cfg)
        assert guard.remaining_daily_loss(10_000) == pytest.approx(500)

    def test_custom_max_loss(self):
        cfg = FTMOGuardConfig(
            initial_balance=10_000,
            challenge_type="1-step",
            max_loss_pct=0.05,  # 5%
        )
        guard = FTMOGuard(config=cfg)
        # Floor = $10k × 0.95 = $9,500
        assert guard.compute_floor() == pytest.approx(9_500)


class TestDay14NarrowRoom:
    """Day 14 scenario: floor has risen, leaving very narrow room."""

    def test_narrow_room_restricts_entries(self):
        guard = FTMOGuard(initial_balance=10_000, challenge_type="1-step")
        # Simulate growth to $11,200 by Day 9
        guard.record_midnight_balance(11_200)
        # Floor is now $10,080
        assert guard.compute_floor() == pytest.approx(10_080)
        # Day 13 midnight balance $10,300 sets daily start for Day 14
        guard.record_midnight_balance(10_300)
        # On Day 14 balance dropped to $10,200:
        # - total headroom = $10,200 - $10,080 = $120
        # - daily loss so far = $10,300 - $10,200 = $100 → headroom $200
        assert guard.remaining_total_loss(10_200) == pytest.approx(120)
        assert guard.remaining_daily_loss(10_200) == pytest.approx(200)
        # A trade risking $200 would exceed the remaining total headroom
        assert guard.check_entry(200, balance=10_200) is False
        assert guard.check_entry(100, balance=10_200) is True
