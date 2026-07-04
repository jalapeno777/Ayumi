"""Tests for FTMO Guard — FTMO challenge rule enforcement.

Covers:
    1. Daily loss tracking and CET midnight reset
    2. Max concurrent position enforcement
    3. Drawdown breaker at 8% (reduce) and 9% (freeze)
    4. Kill switch integration (freeze activation on breach)
    5. Position size multiplier (1.0 / 0.5 / 0.0)
    6. Position gate (should_allow_new_position)
    7. Daily reset recovery from freeze
    8. Edge cases (zero starting balance, DD reduce→freeze escalation)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from risk.ftmo_guard import (
    FTMOAction,
    FTMOGuard,
    _cet_date,
    _cet_midnight_utc,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def kill_switch():
    """Mock kill switch that records all calls."""
    ks = MagicMock()
    ks.is_active.return_value = False
    ks.is_disabled = False
    return ks


@pytest.fixture
def guard(kill_switch):
    """Standard FTMO guard with $10,000 starting balance."""
    return FTMOGuard(
        kill_switch=kill_switch,
        starting_balance=10000.0,
    )


# ── 1. Daily Loss Tracking ───────────────────────────────────────────────────

class TestDailyLoss:
    """Tests for daily loss limit enforcement."""

    def test_no_breach_when_loss_below_limit(self, guard):
        """Daily loss of 3% should not trigger any action."""
        # 3% loss = $300 drop from $10k
        action = guard.update(current_balance=9700.0, open_positions=1)
        assert action == FTMOAction.ALLOW
        assert guard.daily_loss_pct == pytest.approx(3.0, abs=0.01)

    def test_freeze_on_daily_loss_breach(self, guard, kill_switch):
        """Daily loss of 4%+ should trigger FREEZE and call kill_switch."""
        # 4% loss = $400 drop
        action = guard.update(current_balance=9600.0, open_positions=1)
        assert action == FTMOAction.FREEZE
        assert guard.daily_loss_pct >= 4.0
        # Kill switch should have been called for freeze
        kill_switch.activate_global_freeze.assert_called_once()
        call_kwargs = kill_switch.activate_global_freeze.call_args
        assert "ftmo_guard" in str(call_kwargs)

    def test_daily_loss_resets_at_cet_midnight(self, guard):
        """Daily loss should reset when CET date changes."""
        # Trigger a daily loss
        guard.update(current_balance=9500.0, open_positions=0)
        assert guard.daily_loss_pct >= 5.0

        # Simulate next CET day
        next_day = datetime(2026, 7, 5, 0, 30, tzinfo=timezone.utc)  # 01:30 CET July 5
        action = guard.update(current_balance=10000.0, open_positions=0, now=next_day)
        assert guard.daily_loss_pct == 0.0
        assert action == FTMOAction.ALLOW

    def test_daily_reset_recovers_from_freeze(self, guard):
        """If frozen by daily loss, CET midnight should allow trading again."""
        # Hit daily loss freeze
        guard.update(current_balance=9500.0, open_positions=0)
        assert guard.action_level == FTMOAction.FREEZE

        # Next CET day, balance recovered
        next_day = datetime(2026, 7, 5, 0, 30, tzinfo=timezone.utc)
        guard.update(current_balance=10000.0, open_positions=0, now=next_day)
        assert guard.action_level == FTMOAction.ALLOW


# ── 2. Position Limit ────────────────────────────────────────────────────────

class TestPositionLimit:
    """Tests for max concurrent position enforcement."""

    def test_allows_within_limit(self, guard):
        """3 positions (at the limit) should be fine for update, but 4 breaches."""
        action = guard.update(current_balance=10000.0, open_positions=3)
        assert action == FTMOAction.ALLOW

    def test_freeze_on_position_limit_breach(self, guard, kill_switch):
        """4 concurrent positions should trigger FREEZE."""
        action = guard.update(current_balance=10000.0, open_positions=4)
        assert action == FTMOAction.FREEZE
        kill_switch.activate_global_freeze.assert_called_once()

    def test_position_gate_rejects_at_limit(self, guard):
        """should_allow_new_position should reject when already at max."""
        guard.update(current_balance=10000.0, open_positions=3)
        allowed, reason = guard.should_allow_new_position()
        assert allowed is False
        assert "limit" in reason.lower()


# ── 3. Drawdown Breaker ──────────────────────────────────────────────────────

class TestDrawdownBreaker:
    """Tests for drawdown circuit breaker."""

    def test_reduce_at_8_pct_dd(self, guard):
        """8% drawdown from peak should trigger REDUCE_50."""
        # Raise peak above starting to separate DD from daily loss
        guard.update(current_balance=11000.0, open_positions=1)  # New peak $11k
        # 8% DD from $11k = $10,120 — still above $10k starting (no daily loss)
        action = guard.update(current_balance=10120.0, open_positions=1)
        assert action == FTMOAction.REDUCE_50
        assert guard.current_dd_pct >= 8.0

    def test_freeze_at_9_pct_dd(self, guard, kill_switch):
        """9% drawdown should trigger FREEZE."""
        guard.update(current_balance=10000.0, open_positions=1)  # Set peak
        action = guard.update(current_balance=9100.0, open_positions=1)
        assert action == FTMOAction.FREEZE
        assert guard.current_dd_pct >= 9.0
        kill_switch.activate_global_freeze.assert_called_once()

    def test_reduce_does_not_downgrade_from_freeze(self, guard):
        """Once in FREEZE, a reduce-level DD should not downgrade to REDUCE_50."""
        guard.update(current_balance=11000.0, open_positions=1)  # Peak $11k
        # 9% DD from $11k → $10,010 (still above starting, no daily loss)
        guard.update(current_balance=10010.0, open_positions=1)
        assert guard.action_level == FTMOAction.FREEZE

        # Balance recovers slightly to ~8.5% DD — should stay frozen
        guard.update(current_balance=10065.0, open_positions=1)
        assert guard.action_level == FTMOAction.FREEZE

    def test_dd_escalation_reduce_to_freeze(self, guard):
        """Drawdown worsening from reduce to freeze should escalate."""
        guard.update(current_balance=11000.0, open_positions=1)  # Peak $11k
        # 8.5% DD → reduce
        guard.update(current_balance=10065.0, open_positions=1)
        assert guard.action_level == FTMOAction.REDUCE_50

        # 9.5% DD → freeze (escalation)
        guard.update(current_balance=9955.0, open_positions=1)  # 9.5% of $11k
        assert guard.action_level == FTMOAction.FREEZE


# ── 4. Size Multiplier ───────────────────────────────────────────────────────

class TestSizeMultiplier:
    """Tests for position size multiplier."""

    def test_normal_multiplier(self, guard):
        """Normal state → 1.0 multiplier."""
        guard.update(current_balance=10000.0, open_positions=1)
        assert guard.get_size_multiplier() == 1.0

    def test_reduce_multiplier(self, guard):
        """Reduce mode → 0.5 multiplier."""
        guard.update(current_balance=11000.0, open_positions=1)  # Peak
        guard.update(current_balance=10120.0, open_positions=1)  # 8% DD from peak
        assert guard.get_size_multiplier() == 0.5

    def test_freeze_multiplier(self, guard):
        """Freeze state → 0.0 multiplier."""
        guard.update(current_balance=9500.0, open_positions=0)  # 5% daily loss
        assert guard.get_size_multiplier() == 0.0


# ── 5. Position Gate ─────────────────────────────────────────────────────────

class TestPositionGate:
    """Tests for should_allow_new_position."""

    def test_allow_in_normal_state(self, guard):
        guard.update(current_balance=10000.0, open_positions=1)
        allowed, reason = guard.should_allow_new_position()
        assert allowed is True
        assert reason == "OK"

    def test_allow_with_reduce_message(self, guard):
        guard.update(current_balance=11000.0, open_positions=1)  # Peak
        guard.update(current_balance=10065.0, open_positions=1)  # 8.5% DD
        allowed, reason = guard.should_allow_new_position()
        assert allowed is True
        assert "halve" in reason.lower()

    def test_reject_in_freeze(self, guard):
        guard.update(current_balance=9500.0, open_positions=0)  # 5% loss → freeze
        allowed, reason = guard.should_allow_new_position()
        assert allowed is False
        assert "freeze" in reason.lower()


# ── 6. Kill Switch Integration ───────────────────────────────────────────────

class TestKillSwitchIntegration:
    """Tests for kill switch integration."""

    def test_freeze_calls_kill_switch(self, kill_switch):
        """FTMO freeze should call kill_switch.activate_global_freeze."""
        guard = FTMOGuard(kill_switch=kill_switch, starting_balance=10000.0)
        guard.update(current_balance=9500.0, open_positions=0)  # 5% daily loss
        kill_switch.activate_global_freeze.assert_called_once()
        call_args = kill_switch.activate_global_freeze.call_args
        assert "FTMO" in call_args.kwargs.get("reason", call_args[1].get("reason", ""))
        assert call_args.kwargs.get("triggered_by") == "ftmo_guard" or call_args[1].get("triggered_by") == "ftmo_guard"

    def test_no_kill_switch_call_when_no_breach(self, kill_switch):
        """No breach → no kill switch call."""
        guard = FTMOGuard(kill_switch=kill_switch, starting_balance=10000.0)
        guard.update(current_balance=9999.0, open_positions=1)
        kill_switch.activate_global_freeze.assert_not_called()
        kill_switch.activate_global_kill.assert_not_called()

    def test_works_without_kill_switch(self):
        """FTMOGuard should operate without a kill_switch (None)."""
        guard = FTMOGuard(kill_switch=None, starting_balance=10000.0)
        action = guard.update(current_balance=9500.0, open_positions=0)
        assert action == FTMOAction.FREEZE  # Still tracks, just doesn't call KS


# ── 7. CET Helpers ───────────────────────────────────────────────────────────

class TestCETHelpers:
    """Tests for CET date/midnight utilities."""

    def test_cet_date_returns_yyyy_mm_dd(self):
        result = _cet_date(datetime(2026, 7, 4, 23, 30, tzinfo=timezone.utc))
        # 23:30 UTC + 1h = 00:30 CET July 5
        assert result == "2026-07-05"

    def test_cet_midnight_utc_returns_next_midnight(self):
        """CET midnight should be 23:00 UTC (00:00 CET next day)."""
        now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
        midnight = _cet_midnight_utc(now)
        # Next CET midnight after 12:00 UTC July 4 = 23:00 UTC July 4 = 00:00 CET July 5
        assert midnight.day == 4
        assert midnight.hour == 23

    def test_cet_date_changes_at_midnight(self):
        """UTC 22:59 and UTC 23:00 should be different CET dates."""
        before = _cet_date(datetime(2026, 7, 4, 22, 59, tzinfo=timezone.utc))
        after = _cet_date(datetime(2026, 7, 4, 23, 0, tzinfo=timezone.utc))
        assert before == "2026-07-04"
        assert after == "2026-07-05"


# ── 8. Edge Cases ────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge case and robustness tests."""

    def test_invalid_dd_thresholds(self):
        """dd_reduce_pct >= dd_freeze_pct should raise ValueError."""
        with pytest.raises(ValueError, match="must be <"):
            FTMOGuard(dd_reduce_pct=9.0, dd_freeze_pct=9.0)

    def test_invalid_daily_loss_pct(self):
        """Non-positive daily loss pct should raise ValueError."""
        with pytest.raises(ValueError, match="positive"):
            FTMOGuard(max_daily_loss_pct=0.0)

    def test_breach_history_accumulates(self, guard):
        """Multiple breaches should accumulate in history."""
        guard.update(current_balance=10000.0, open_positions=1)  # Peak
        guard.update(current_balance=9200.0, open_positions=1)   # 8% DD
        guard.update(current_balance=9050.0, open_positions=1)   # 9.5% DD
        assert len(guard.state.breach_history) >= 2

    def test_peak_balance_updates_on_new_high(self, guard):
        """Peak balance should track new highs."""
        guard.update(current_balance=10000.0, open_positions=0)
        guard.update(current_balance=10500.0, open_positions=0)
        assert guard.state.peak_balance == 10500.0
        # DD from new peak
        guard.update(current_balance=9800.0, open_positions=0)  # ~6.7% from 10.5k
        assert guard.current_dd_pct > 6.0

    def test_recovery_from_reduce(self, guard):
        """Reduce mode should recover to ALLOW when balance improves."""
        guard.update(current_balance=11000.0, open_positions=1)  # Peak
        guard.update(current_balance=10065.0, open_positions=1)  # 8.5% DD → reduce
        assert guard.action_level == FTMOAction.REDUCE_50

        # Balance recovers to near peak
        guard.update(current_balance=10950.0, open_positions=1)  # ~0.5% DD
        assert guard.action_level == FTMOAction.ALLOW

    def test_get_status_returns_dict(self, guard):
        """get_status should return a serializable dict."""
        guard.update(current_balance=9700.0, open_positions=2)
        status = guard.get_status()
        assert isinstance(status, dict)
        assert "starting_balance" in status
        assert "daily_loss_pct" in status
        assert "action_level" in status
        assert status["open_position_count"] == 2
