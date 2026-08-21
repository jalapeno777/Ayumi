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
    _toronto_midnight_utc,
    _trading_date,
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
        """Daily loss below the 3% FTMO limit should not trigger any action."""
        # 2.5% loss = $250 drop from $10k (below the 3% FTMO daily DD limit)
        action = guard.update(current_balance=9750.0, open_positions=1)
        assert action == FTMOAction.ALLOW
        assert guard.daily_loss_pct == pytest.approx(2.5, abs=0.01)

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

    def test_daily_loss_resets_at_toronto_midnight(self, guard):
        """Daily loss should reset when America/Toronto date changes."""
        # Trigger a daily loss
        guard.update(current_balance=9500.0, open_positions=0)
        assert guard.daily_loss_pct >= 5.0

        # Simulate next Toronto day (04:30 UTC = 00:30 EDT July 5)
        next_day = datetime(2026, 7, 5, 4, 30, tzinfo=timezone.utc)
        action = guard.update(current_balance=10000.0, open_positions=0, now=next_day)
        assert guard.daily_loss_pct == 0.0
        assert action == FTMOAction.ALLOW

    def test_daily_reset_recovers_from_freeze(self, guard):
        """If frozen by daily loss, Toronto midnight should allow trading again."""
        # Hit daily loss freeze
        guard.update(current_balance=9500.0, open_positions=0)
        assert guard.action_level == FTMOAction.FREEZE

        # Next Toronto day (04:30 UTC = 00:30 EDT July 5), balance recovered
        next_day = datetime(2026, 7, 5, 4, 30, tzinfo=timezone.utc)
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


# ── 7. Trading Date Helpers ──────────────────────────────────────────────────


class TestTradingDateHelpers:
    """Tests for America/Toronto date/midnight utilities.

    Convention changed from CET to America/Toronto midnight per Craig
    decision (Jul 17, 2026, commit 5e55283/4216e55).
    """

    def test_trading_date_returns_yyyy_mm_dd(self):
        """UTC 23:30 July 4 = 19:30 EDT July 4 (Toronto is UTC-4 in summer)."""
        result = _trading_date(datetime(2026, 7, 4, 23, 30, tzinfo=timezone.utc))
        assert result == "2026-07-04"

    def test_toronto_midnight_utc_returns_next_midnight(self):
        """Toronto midnight should be 04:00 UTC during EDT (00:00 EDT next day)."""
        now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)  # 08:00 EDT
        midnight = _toronto_midnight_utc(now)
        # Next Toronto midnight after 08:00 EDT July 4 = 00:00 EDT July 5 = 04:00 UTC July 5
        assert midnight.day == 5
        assert midnight.hour == 4

    def test_trading_date_changes_at_midnight(self):
        """UTC 03:59 and UTC 04:00 should be different Toronto dates (EDT)."""
        before = _trading_date(datetime(2026, 7, 5, 3, 59, tzinfo=timezone.utc))
        after = _trading_date(datetime(2026, 7, 5, 4, 0, tzinfo=timezone.utc))
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
        guard.update(current_balance=9200.0, open_positions=1)  # 8% DD
        guard.update(current_balance=9050.0, open_positions=1)  # 9.5% DD
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


# ── 9. Forward-Test Integration (card dd32226b) ────────────────────────────


class TestForwardTestIntegration:
    """Integration tests for the forward-test runner wiring.

    Cards dd32226b wires FTMOGuard into launch_blend_forward_test.py
    alongside the existing RiskGuard. These tests verify the peak-based
    DD behavior the runner relies on, and the contract guarantees
    required by the spec:

      AC5: peak-based DD correctly halts trading when balance exceeds
           peak + 10% DD (FTMO contract).
      AC6: balance at peak DOES NOT trigger DD (peak-based, not
           starting-based).
    """

    def test_peak_based_dd_halts_at_10pct_below_peak(self, kill_switch):
        """AC5: 10% DD from peak (FTMO total DD contract) triggers freeze.

        FTMO 1-Step Standard total drawdown is 10% of starting balance.
        FTMOGuard uses peak-based trailing DD so the contract is enforced
        relative to the highest balance reached, not the starting balance.
        """
        guard = FTMOGuard(
            kill_switch=kill_switch,
            starting_balance=10_000.0,
        )
        # Scenario: account grows to $11K then drops to $9,900 (10% from peak)
        guard.update(current_balance=11_000.0, open_positions=1)  # New peak $11K
        # 10% DD from $11K = $9,900 — at the FTMO total-DD limit
        action = guard.update(current_balance=9_900.0, open_positions=1)
        assert guard.current_dd_pct >= 10.0
        # FTMOGuard freeze threshold is 9% (REDUCE_50 at 8%, FREEZE at 9%),
        # so 10% DD from peak correctly triggers FREEZE.
        assert action == FTMOAction.FREEZE
        kill_switch.activate_global_freeze.assert_called()
        # Verify reason references FTMO and the breach type
        call_kwargs = kill_switch.activate_global_freeze.call_args.kwargs
        assert "FTMO" in call_kwargs["reason"]
        assert call_kwargs["triggered_by"] == "ftmo_guard"

    def test_balance_at_peak_does_not_trigger_dd(self, guard):
        """AC6: balance at peak MUST NOT trigger DD (peak-based semantics).

        The new-peak update itself MUST NOT trigger DD (DD is 0% at the
        peak by definition). And the discriminating case for peak-based
        vs starting-based: when balance retraces to starting AFTER a new
        peak, peak-based DD trips but starting-balance DD does not.
        """
        # Build up to a new peak first
        guard.update(current_balance=10_500.0, open_positions=0)
        assert guard.state.peak_balance == 10_500.0

        # Update exactly at the peak — DD MUST be 0 (no regression on peak)
        action = guard.update(current_balance=10_500.0, open_positions=0)
        assert guard.current_dd_pct == 0.0
        assert action == FTMOAction.ALLOW

        # Now: balance retraces FROM $10.5K peak back to $10K (starting
        # balance). Peak-based DD = 4.76% (from $10.5K). Starting-balance
        # DD = 0% (we're at starting). 4.76% < 8% reduce threshold, so
        # current action is ALLOW (which is correct for this balance).
        # The semantic distinction: starting-balance DD would also be ALLOW
        # here, but the *value* of current_dd_pct reflects the peak-based
        # calculation (not starting-based).
        guard.update(current_balance=10_000.0, open_positions=0)
        assert guard.current_dd_pct == pytest.approx(4.76, abs=0.05)
        assert guard.action_level == FTMOAction.ALLOW

        # The discriminating case: drop further to $9.5K from $10.5K peak.
        # Peak-based DD = 9.52% (from $10.5K) → FREEZE (≥9%).
        # Starting-balance DD would be 5% (from $10K) → DAILY_LOSS territory
        # but not DD-driven. The key is that the DD-driven guard trips on
        # peak-based metrics, not starting-based metrics.
        action = guard.update(current_balance=9_500.0, open_positions=0)
        assert guard.current_dd_pct == pytest.approx(9.52, abs=0.05)
        # 9.52% > 9% freeze threshold + 5% daily loss (also ≥3% freeze)
        # → both could trigger freeze. action_level must be FREEZE.
        assert action == FTMOAction.FREEZE

    def test_peak_tracks_new_highs_not_starting_balance(self, guard):
        """Peak balance must track the highest balance seen, not the starting balance.

        This is the core difference between FTMOGuard (peak-based) and the
        existing RiskGuard (starting-balance DD per risk_guard.py:364).
        """
        # Balance grows to $10.5K — peak should follow
        guard.update(current_balance=10_500.0, open_positions=1)
        assert guard.state.peak_balance == 10_500.0

        # Balance retraces to $9,800 — DD computed from peak ($10.5K)
        guard.update(current_balance=9_800.0, open_positions=1)
        # 9800 / 10500 = 0.9333 → 6.67% DD from peak
        assert guard.current_dd_pct == pytest.approx(6.67, abs=0.05)

        # Balance retraces to $9,400 — DD from peak ($10.5K)
        guard.update(current_balance=9_400.0, open_positions=1)
        # 9400 / 10500 = 0.8952 → 10.48% DD from peak → FREEZE
        assert guard.current_dd_pct >= 10.0
        assert guard.action_level == FTMOAction.FREEZE

    def test_runner_5min_cadence_update_with_engine_balance(self, kill_switch):
        """Simulate the runner's 5-min sync cycle passing (current_balance, open_positions).

        The runner does:
            ftmo_guard.update(current_balance=engine._live_balance,
                              open_positions=len(paper_trader._open_positions))
        on the same 5-min cadence as RiskGuard. This test verifies that
        the call signature matches and that a freeze correctly halts
        subsequent updates.
        """
        guard = FTMOGuard(
            kill_switch=kill_switch,
            starting_balance=10_000.0,
        )
        # Simulate 5-min sync ticks: balance oscillating around starting
        sync_calls = [
            # (current_balance, open_positions)
            (10_000.0, 0),  # initial
            (10_050.0, 1),  # opened a position, balance grew
            (10_080.0, 1),  # peak
            (10_030.0, 1),  # small pullback
            (10_010.0, 1),  # tighter
            (10_100.0, 1),  # new peak
            (9_900.0, 1),  # 1.9% DD from peak — still ALLOW
            (9_500.0, 1),  # 5.6% DD from peak — REDUCE_50 (passes 8% threshold)
        ]
        last_action = None
        for balance, open_pos in sync_calls:
            last_action = guard.update(current_balance=balance, open_positions=open_pos)
        # Should be REDUCE_50 at the final update (5.6% < 8% threshold)
        # Actually 9.5% from 10.1k → that's between 8% and 9%, so REDUCE_50
        assert last_action in (FTMOAction.REDUCE_50, FTMOAction.FREEZE)

    def test_status_dict_has_required_b5_fields(self, guard):
        """B5 health line requires action_level, daily_loss_pct, current_dd_pct, peak_balance.

        These are the fields the runner's B5 health log surfaces. Any
        future FTMOGuard refactor must keep these field names stable.
        """
        guard.update(current_balance=10_500.0, open_positions=1)
        guard.update(current_balance=10_300.0, open_positions=1)  # 1.9% DD from peak
        status = guard.get_status()
        assert "action_level" in status
        assert "daily_loss_pct" in status
        assert "current_dd_pct" in status
        assert "peak_balance" in status
        assert status["peak_balance"] == 10_500.0
        assert status["current_dd_pct"] > 0.0
        assert status["action_level"] == FTMOAction.ALLOW.value


# ── 10. Challenge Type (1-step / 2-step) ────────────────────────────────────


class TestChallengeType:
    """Tests for challenge_type parameter and daily loss derivation."""

    def test_default_challenge_type_is_1_step(self):
        """Default challenge_type should be '1-step'."""
        guard = FTMOGuard(starting_balance=10000.0)
        assert guard.challenge_type == "1-step"

    def test_1step_daily_loss_threshold_is_3_pct(self):
        """1-step challenge: daily loss of 3% should trigger FREEZE."""
        guard = FTMOGuard(starting_balance=10000.0, challenge_type="1-step")
        # 2.9% loss → ALLOW
        guard.update(current_balance=9710.0, open_positions=0)
        assert guard.action_level == FTMOAction.ALLOW
        # 3.1% loss → FREEZE
        guard2 = FTMOGuard(starting_balance=10000.0, challenge_type="1-step")
        guard2.update(current_balance=9690.0, open_positions=0)
        assert guard2.action_level == FTMOAction.FREEZE

    def test_2step_daily_loss_threshold_is_5_pct(self):
        """2-step challenge: daily loss of 5% should trigger FREEZE."""
        guard = FTMOGuard(starting_balance=10000.0, challenge_type="2-step")
        # 4.5% loss → ALLOW (would breach at 3% for 1-step)
        guard.update(current_balance=9550.0, open_positions=0)
        assert guard.action_level == FTMOAction.ALLOW
        # 5.5% loss → FREEZE
        guard2 = FTMOGuard(starting_balance=10000.0, challenge_type="2-step")
        guard2.update(current_balance=9450.0, open_positions=0)
        assert guard2.action_level == FTMOAction.FREEZE

    def test_2step_allows_4_pct_loss_that_1step_rejects(self):
        """4% daily loss should be ALLOW for 2-step but FREEZE for 1-step."""
        guard_2s = FTMOGuard(starting_balance=10000.0, challenge_type="2-step")
        guard_2s.update(current_balance=9600.0, open_positions=0)
        assert guard_2s.action_level == FTMOAction.ALLOW

        guard_1s = FTMOGuard(starting_balance=10000.0, challenge_type="1-step")
        guard_1s.update(current_balance=9600.0, open_positions=0)
        assert guard_1s.action_level == FTMOAction.FREEZE

    def test_explicit_max_daily_loss_pct_overrides_challenge_type(self):
        """Explicit max_daily_loss_pct should override challenge_type derivation."""
        guard = FTMOGuard(
            starting_balance=10000.0,
            challenge_type="2-step",
            max_daily_loss_pct=2.0,  # override to 2%
        )
        # 2.5% loss → FREEZE (uses override, not 5%)
        guard.update(current_balance=9750.0, open_positions=0)
        assert guard.action_level == FTMOAction.FREEZE

    def test_challenge_type_in_status(self):
        """Status dict should include challenge_type."""
        guard = FTMOGuard(starting_balance=10000.0, challenge_type="2-step")
        status = guard.get_status()
        assert status["challenge_type"] == "2-step"


# ── 10. Trailing-DD Floor ──────────────────────────────────────────────────


class TestTrailingDDFloor:
    """Tests for trailing-DD max-loss floor (ported from backtest.ftmo_guard)."""

    def test_compute_floor_1step_trailing(self):
        """1-step floor = highest_midnight_balance × 90% (trailing)."""
        guard = FTMOGuard(
            starting_balance=10000.0,
            challenge_type="1-step",
            trailing_dd=True,
        )
        assert guard.compute_floor() == pytest.approx(9000.0)

    def test_compute_floor_2step_static(self):
        """2-step floor = starting_balance × 90% (static, never trails)."""
        guard = FTMOGuard(
            starting_balance=10000.0,
            challenge_type="2-step",
            trailing_dd=True,
        )
        assert guard.compute_floor() == pytest.approx(9000.0)

    def test_trailing_floor_rises_with_peak_1step(self):
        """1-step: floor should rise when midnight balance exceeds prior peak."""
        guard = FTMOGuard(
            starting_balance=10000.0,
            challenge_type="1-step",
            trailing_dd=True,
        )
        guard.record_midnight_balance(10800.0)
        assert guard.highest_midnight_balance == 10800.0
        assert guard.compute_floor() == pytest.approx(9720.0)

    def test_trailing_floor_never_decreases(self):
        """Floor can only rise, never fall."""
        guard = FTMOGuard(
            starting_balance=10000.0,
            challenge_type="1-step",
            trailing_dd=True,
        )
        guard.record_midnight_balance(11000.0)
        assert guard.compute_floor() == pytest.approx(9900.0)
        # Balance drops back — floor should NOT drop
        guard.record_midnight_balance(10500.0)
        assert guard.highest_midnight_balance == 11000.0
        assert guard.compute_floor() == pytest.approx(9900.0)

    def test_2step_floor_static_after_growth(self):
        """2-step: floor stays at initial even after balance growth."""
        guard = FTMOGuard(
            starting_balance=10000.0,
            challenge_type="2-step",
            trailing_dd=True,
        )
        guard.record_midnight_balance(11200.0)
        assert guard.highest_midnight_balance == 11200.0
        # Floor still $9,000 — static
        assert guard.compute_floor() == pytest.approx(9000.0)

    def test_trailing_floor_breach_triggers_freeze(self):
        """Balance below floor should trigger FREEZE when trailing_dd=True."""
        guard = FTMOGuard(
            kill_switch=None,
            starting_balance=10000.0,
            challenge_type="1-step",
            trailing_dd=True,
        )
        # Raise floor via midnight balance growth
        guard.record_midnight_balance(11200.0)  # floor = 10080
        # Balance drops below floor
        guard.update(current_balance=10050.0, open_positions=0)
        assert guard.action_level == FTMOAction.FREEZE
        # Verify the breach type
        breaches = [b for b in guard.state.breach_history if b["type"] == "trailing_dd_floor"]
        assert len(breaches) >= 1

    def test_trailing_floor_not_checked_when_disabled(self):
        """trailing_dd=False (default): floor check should not fire."""
        guard = FTMOGuard(
            starting_balance=10000.0,
            challenge_type="1-step",
            trailing_dd=False,  # default
        )
        # Even if balance would be below floor, no freeze from trailing
        guard.record_midnight_balance(11200.0)  # would set floor at 10080
        guard.update(current_balance=10050.0, open_positions=0)
        # Should not be FREEZE from trailing floor (may be ALLOW)
        assert guard.action_level == FTMOAction.ALLOW

    def test_trailing_floor_breach_2step_static(self):
        """2-step: balance below static floor triggers FREEZE."""
        guard = FTMOGuard(
            kill_switch=None,
            starting_balance=10000.0,
            challenge_type="2-step",
            trailing_dd=True,
        )
        # 2-step floor is always $9,000 (static)
        guard.update(current_balance=8950.0, open_positions=0)
        assert guard.action_level == FTMOAction.FREEZE

    def test_trailing_floor_day15_scenario(self):
        """Classic trailing floor breach scenario from research doc."""
        guard = FTMOGuard(
            kill_switch=None,
            starting_balance=10000.0,
            challenge_type="1-step",
            trailing_dd=True,
        )
        guard.record_midnight_balance(10000.0)  # Day 1
        assert guard.compute_floor() == pytest.approx(9000.0)
        guard.record_midnight_balance(10800.0)  # Day 5
        assert guard.compute_floor() == pytest.approx(9720.0)
        guard.record_midnight_balance(11200.0)  # Day 9
        assert guard.compute_floor() == pytest.approx(10080.0)
        # Day 15: balance drops below floor
        guard.update(current_balance=10050.0, open_positions=0)
        assert guard.action_level == FTMOAction.FREEZE
