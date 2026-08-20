"""Unit tests for FTMO Guard — Best-day rule (Phase 0, BQ-1380).

The FTMO 1-Step best-day rule states: the single best day's profit must not
exceed 50% of the total positive-days profit. This file tests the
``record_daily_pnl`` / ``check_best_day_rule`` API surface and its
integration with the broader ``update()`` lifecycle.

Covers:
    1. Need ≥2 positive days to evaluate (single day → no violation)
    2. Boundary: best day = 50% exactly → no violation (strictly > 50% only)
    3. Strict: best day > 50% → FREEZE action + breach recorded
    4. Negative days excluded from positive-days total
    5. ``record_daily_pnl`` accumulates within the same CET day
    6. CET midnight rollover moves ``daily_pnl`` to ``daily_pnl_history``
    7. History trimming at ``MAX_PNL_HISTORY`` (60 entries)
    8. ``check_best_day_rule()`` returns ``None`` with empty history
    9. Best-day computation includes/excludes today's ``daily_pnl``
   10. Custom ``best_day_cap_pct`` overrides default
   11. Recovery from best-day freeze when rule no longer violated
   12. State serialization includes all best-day fields
"""

from __future__ import annotations  # noqa: I001

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from risk.ftmo_guard import (
    FTMOAction,
    FTMOBreachType,
    FTMOGuard,
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


@pytest.fixture
def guard_no_ks():
    """FTMO guard without a kill switch (for tests that don't trigger FREEZE)."""
    return FTMOGuard(kill_switch=None, starting_balance=10000.0)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _seed_history(guard: FTMOGuard, entries: list[tuple[str, float]]) -> None:
    """Replace the daily_pnl_history with a fixed list of (date, pnl) tuples.

    Bypasses ``record_daily_pnl`` to keep tests date-independent and to
    avoid accidental rollover side-effects.
    """
    guard._state.daily_pnl_history = [{"date": date, "pnl": pnl} for date, pnl in entries]


def _set_today(guard: FTMOGuard, date: str, pnl: float = 0.0) -> None:
    """Set today's daily_pnl and daily_pnl_date explicitly."""
    guard._state.daily_pnl = pnl
    guard._state.daily_pnl_date = date


# ── 1. Minimum 2 positive days required ─────────────────────────────────────


class TestMinimumPositiveDays:
    """Best-day rule is only meaningful with ≥2 positive days."""

    def test_single_positive_day_no_violation(self, guard):
        """A single positive day cannot violate the rule (need ≥2)."""
        _seed_history(guard, [("2026-07-08", 100.0)])
        _set_today(guard, "2026-07-09", 0.0)  # today has zero
        result = guard.check_best_day_rule()
        assert result is None

    def test_zero_positive_days_no_violation(self, guard):
        """With no recorded P&L, no violation possible."""
        assert guard.check_best_day_rule() is None

    def test_only_today_positive_no_violation(self, guard):
        """Today's daily_pnl alone (1 positive day) → no violation."""
        _set_today(guard, _trading_date(), 100.0)
        result = guard.check_best_day_rule()
        assert result is None

    def test_only_today_in_history_no_violation(self, guard):
        """One positive day in history + zero today → no violation."""
        _seed_history(guard, [("2026-07-08", 100.0)])
        _set_today(guard, "2026-07-09", 0.0)
        result = guard.check_best_day_rule()
        assert result is None


# ── 2. Boundary: best day = 50% exactly ────────────────────────────────────


class TestBoundary:
    """``best_day_ratio == 50%`` is allowed (only strictly > 50% violates)."""

    def test_two_equal_positive_days_no_violation(self, guard):
        """50/50 split: best day is exactly 50% of total — no violation."""
        _seed_history(guard, [("2026-07-08", 100.0)])
        _set_today(guard, "2026-07-09", 100.0)
        # best=100, total=200, ratio=0.50 → not > 0.50 → None
        result = guard.check_best_day_rule()
        assert result is None

    def test_three_equal_positive_days_no_violation(self, guard):
        """3 equal days: best is 33% of total — no violation."""
        _seed_history(
            guard,
            [("2026-07-07", 100.0), ("2026-07-08", 100.0)],
        )
        _set_today(guard, "2026-07-09", 100.0)
        result = guard.check_best_day_rule()
        assert result is None

    def test_asymmetric_but_under_cap(self, guard):
        """3-day asymmetric split with best at ~43% of total — no violation.

        Note: with only 2 days, the 'best' is always the larger of the two,
        forcing ratio > 50% unless they are exactly equal. Asymmetric
        splits below 50% require 3+ days.
        """
        # 3 days: 300 (best), 200, 200. Total=700. Ratio=300/700=42.9% < 50%
        _seed_history(
            guard,
            [("2026-07-08", 300.0), ("2026-07-09", 200.0)],
        )
        _set_today(guard, "2026-07-10", 200.0)
        result = guard.check_best_day_rule()
        assert result is None


# ── 3. Strict: best day > 50% → violation + FREEZE ────────────────────────


class TestStrictViolation:
    """``best_day_ratio > 50%`` → violation flagged, FREEZE action."""

    def test_two_days_60_40_violation(self, guard):
        """best=150, other=100 → 60% — violation."""
        _seed_history(guard, [("2026-07-08", 150.0)])  # best day in history
        _set_today(guard, "2026-07-09", 100.0)
        result = guard.check_best_day_rule()
        assert result is not None
        assert "Best day" in result
        assert "60.0%" in result
        assert "150.00" in result

    def test_violation_triggers_freeze_on_update(self, guard, kill_switch):
        """update() with a best-day violation should return FREEZE and call kill_switch."""
        _seed_history(guard, [("2026-07-08", 200.0)])
        _set_today(guard, "2026-07-09", 50.0)
        # best=200, total=250, ratio=0.80 > 0.5 → violation

        action = guard.update(current_balance=10000.0, open_positions=0)
        assert action == FTMOAction.FREEZE
        assert guard.action_level == FTMOAction.FREEZE
        kill_switch.activate_global_freeze.assert_called_once()

    def test_violation_records_best_day_breach(self, guard):
        """Best-day violation should add a BEST_DAY_RULE entry to breach_history."""
        _seed_history(guard, [("2026-07-08", 200.0)])
        _set_today(guard, "2026-07-09", 50.0)
        guard.update(current_balance=10000.0, open_positions=0)

        breach_types = [b["type"] for b in guard.state.breach_history]
        assert FTMOBreachType.BEST_DAY_RULE.value in breach_types

    def test_violation_with_multiple_history_days(self, guard):
        """Violation when many small days + one big day pushes best > 50%."""
        # 4 small days of 50 each = 200; 1 big day of 300 → best=300, total=500 → 60%
        _seed_history(
            guard,
            [
                ("2026-07-04", 50.0),
                ("2026-07-05", 50.0),
                ("2026-07-06", 50.0),
                ("2026-07-07", 50.0),
                ("2026-07-08", 300.0),  # best day
            ],
        )
        _set_today(guard, "2026-07-09", 0.0)
        result = guard.check_best_day_rule()
        assert result is not None
        # 300 / 500 = 0.6 → "60.0%"
        assert "60.0%" in result

    def test_today_is_best_day_violation(self, guard):
        """Today is the best day → violation."""
        _seed_history(guard, [("2026-07-08", 50.0)])
        _set_today(guard, "2026-07-09", 200.0)
        # best=200, total=250, ratio=0.80 → violation
        result = guard.check_best_day_rule()
        assert result is not None
        assert "Best day" in result

    def test_history_day_is_best_violation(self, guard):
        """A day in history is the best → violation."""
        _seed_history(guard, [("2026-07-08", 200.0)])
        _set_today(guard, "2026-07-09", 50.0)
        result = guard.check_best_day_rule()
        assert result is not None


# ── 4. Negative days excluded from positive-days total ─────────────────────


class TestNegativeDaysExcluded:
    """Negative-PnL days are NOT counted in the positive-days denominator."""

    def test_single_negative_day_no_violation(self, guard):
        """One negative day + zero today → 0 positive days → no violation."""
        _seed_history(guard, [("2026-07-08", -50.0)])
        _set_today(guard, "2026-07-09", 0.0)
        assert guard.check_best_day_rule() is None

    def test_negative_today_does_not_count(self, guard):
        """Negative today's daily_pnl is excluded from positive days."""
        _seed_history(guard, [("2026-07-08", 100.0)])
        _set_today(guard, "2026-07-09", -50.0)
        # Only 1 positive day in history → no violation
        assert guard.check_best_day_rule() is None

    def test_two_positive_minus_one_negative(self, guard):
        """2 positive (200, 100) + 1 negative (-500): best/total = 200/300 = 66.7% → violation."""
        _seed_history(
            guard,
            [("2026-07-07", -500.0), ("2026-07-08", 100.0)],
        )
        _set_today(guard, "2026-07-09", 200.0)
        # Positive days: 100 + 200 = 300. Best = 200. 200/300 = 66.7% → violation
        result = guard.check_best_day_rule()
        assert result is not None
        assert "66.7%" in result

    def test_zero_pnl_day_excluded(self, guard):
        """A day with PnL=0 is not a 'positive day' (strictly > 0)."""
        _seed_history(guard, [("2026-07-08", 0.0)])
        _set_today(guard, "2026-07-09", 100.0)
        # Only 1 positive day → no violation
        assert guard.check_best_day_rule() is None

    def test_mixed_positive_negative_does_not_crash(self, guard):
        """Edge: only negative days and zero today should yield None safely."""
        _seed_history(guard, [("2026-07-07", -100.0), ("2026-07-08", -50.0)])
        _set_today(guard, "2026-07-09", -25.0)
        # 0 positive days total → can't violate
        assert guard.check_best_day_rule() is None


# ── 5. record_daily_pnl accumulation ───────────────────────────────────────


class TestRecordDailyPnl:
    """``record_daily_pnl`` accumulates trades within a CET day."""

    def test_single_trade_records_correctly(self, guard):
        """Single trade with positive P&L is stored in daily_pnl."""
        guard.record_daily_pnl(100.0, "2026-07-08")
        assert guard.state.daily_pnl == pytest.approx(100.0)
        assert guard.state.daily_pnl_date == "2026-07-08"

    def test_multiple_trades_same_day_accumulate(self, guard):
        """Multiple trades on the same day sum together in daily_pnl."""
        guard.record_daily_pnl(100.0, "2026-07-08")
        guard.record_daily_pnl(50.0, "2026-07-08")
        guard.record_daily_pnl(-30.0, "2026-07-08")
        guard.record_daily_pnl(75.0, "2026-07-08")
        # Net: 100 + 50 - 30 + 75 = 195
        assert guard.state.daily_pnl == pytest.approx(195.0)
        assert guard.state.daily_pnl_date == "2026-07-08"

    def test_negative_trade_does_not_reset(self, guard):
        """A negative trade accumulates but does not reset daily_pnl to 0."""
        guard.record_daily_pnl(50.0, "2026-07-08")
        guard.record_daily_pnl(-20.0, "2026-07-08")
        assert guard.state.daily_pnl == pytest.approx(30.0)

    def test_default_date_uses_today(self, guard):
        """When no date provided, ``_trading_date()`` is used."""
        guard.record_daily_pnl(50.0)  # no date argument
        assert guard.state.daily_pnl == pytest.approx(50.0)
        assert guard.state.daily_pnl_date == _trading_date()

    def test_accumulation_independent_of_history(self, guard):
        """Accumulation does not write to history (rollover is separate)."""
        guard.record_daily_pnl(100.0, "2026-07-08")
        guard.record_daily_pnl(50.0, "2026-07-08")
        # History should not contain "2026-07-08" yet (not rolled over)
        for entry in guard.state.daily_pnl_history:
            assert entry["date"] != "2026-07-08"

    def test_explicit_date_overrides_today(self, guard):
        """Explicit date argument is used verbatim."""
        guard.record_daily_pnl(100.0, "2020-01-01")  # back-dated
        assert guard.state.daily_pnl == pytest.approx(100.0)
        assert guard.state.daily_pnl_date == "2020-01-01"


# ── 6. CET midnight rollover ────────────────────────────────────────────────


class TestTorontoRollover:
    """Daily P&L rolls to history when America/Toronto date changes."""

    def test_rollover_via_record_daily_pnl_date_change(self, guard):
        """Different date string in ``record_daily_pnl`` triggers rollover."""
        # Set up: today is "2026-07-08" with pnl=100
        _set_today(guard, "2026-07-08", 100.0)
        assert len(guard.state.daily_pnl_history) == 0

        # Record on a new date → triggers rollover
        guard.record_daily_pnl(50.0, "2026-07-09")

        # history should have day 07-08
        assert len(guard.state.daily_pnl_history) == 1
        assert guard.state.daily_pnl_history[0] == {
            "date": "2026-07-08",
            "pnl": 100.0,
        }
        # current day is 07-09 with pnl 50
        assert guard.state.daily_pnl == pytest.approx(50.0)
        assert guard.state.daily_pnl_date == "2026-07-09"

    def test_rollover_via_update_with_next_day(self, guard):
        """``update()`` with a ``now``-arg on the next Toronto day triggers rollover."""
        # Set up state as if we're on "2026-07-08" with 100 pnl recorded
        _set_today(guard, "2026-07-08", 100.0)
        guard._state.daily_loss_date = "2026-07-08"

        # Call update with a time on 2026-07-09 04:30 UTC (= 00:30 EDT)
        next_day = datetime(2026, 7, 9, 4, 30, tzinfo=timezone.utc)
        guard.update(current_balance=10000.0, open_positions=0, now=next_day)

        # history should contain day 07-08
        assert len(guard.state.daily_pnl_history) == 1
        assert guard.state.daily_pnl_history[0]["date"] == "2026-07-08"
        assert guard.state.daily_pnl_history[0]["pnl"] == pytest.approx(100.0)
        # current day is 07-09, pnl reset
        assert guard.state.daily_pnl == 0.0
        assert guard.state.daily_pnl_date == "2026-07-09"

    def test_no_rollover_within_same_day(self, guard):
        """``update()`` with same-day ``now`` should not trigger rollover."""
        _set_today(guard, "2026-07-08", 100.0)
        guard._state.daily_loss_date = "2026-07-08"

        same_day = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)  # 13:00 CET
        guard.update(current_balance=10000.0, open_positions=0, now=same_day)

        # No history entry created
        assert len(guard.state.daily_pnl_history) == 0
        # daily_pnl preserved
        assert guard.state.daily_pnl == pytest.approx(100.0)
        assert guard.state.daily_pnl_date == "2026-07-08"

    def test_rollover_records_exact_pnl(self, guard):
        """Rollover records the day's exact accumulated pnl, not reset value."""
        _set_today(guard, "2026-07-08", 0.0)
        guard.record_daily_pnl(150.0, "2026-07-08")
        guard.record_daily_pnl(-50.0, "2026-07-08")
        # daily_pnl = 100
        assert guard.state.daily_pnl == pytest.approx(100.0)

        # Trigger rollover
        guard.record_daily_pnl(75.0, "2026-07-09")

        assert guard.state.daily_pnl_history[0]["pnl"] == pytest.approx(100.0)
        assert guard.state.daily_pnl == pytest.approx(75.0)


# ── 7. History trimming at MAX_PNL_HISTORY ─────────────────────────────────


class TestHistoryTrimming:
    """History is trimmed to ``MAX_PNL_HISTORY`` (60) most recent entries."""

    def test_max_pnl_history_constant_value(self):
        """``MAX_PNL_HISTORY`` should be 60 (FTMO 60-day rolling window)."""
        assert FTMOGuard.MAX_PNL_HISTORY == 60

    def test_default_best_day_cap_pct_value(self):
        """``DEFAULT_BEST_DAY_CAP_PCT`` should be 0.50 (50% FTMO cap)."""
        assert FTMOGuard.DEFAULT_BEST_DAY_CAP_PCT == 0.50

    def test_history_trimmed_to_60_entries(self, guard):
        """After 64+ days, history should be trimmed to 60 most recent."""
        # Pre-populate 63 history entries
        for i in range(63):
            guard._state.daily_pnl_history.append(
                {
                    "date": f"2026-05-{i + 1:02d}",
                    "pnl": 100.0,
                }
            )
        assert len(guard._state.daily_pnl_history) == 63

        # Pre-set state: simulate today being a specific day with pnl
        _set_today(guard, "2026-05-01", 50.0)

        # Trigger rollover (appends 1 entry → 64, then trimmed to 60)
        guard.record_daily_pnl(25.0, "2026-05-02")

        assert len(guard.state.daily_pnl_history) == FTMOGuard.MAX_PNL_HISTORY
        assert len(guard.state.daily_pnl_history) == 60

    def test_history_at_60_not_over_trimmed(self, guard):
        """With 60 entries, rollover yields 61 then trim to exactly 60."""
        for i in range(60):
            guard._state.daily_pnl_history.append(
                {
                    "date": f"2026-05-{i + 1:02d}",
                    "pnl": 50.0,
                }
            )
        assert len(guard._state.daily_pnl_history) == 60

        _set_today(guard, "2026-05-01", 100.0)
        guard.record_daily_pnl(25.0, "2026-05-02")  # triggers rollover

        # After rollover: 61 entries, then trimmed to 60
        assert len(guard.state.daily_pnl_history) == 60

    def test_history_keeps_most_recent_entries(self, guard):
        """When trimming, the OLDEST entries are dropped (FIFO)."""
        for i in range(63):
            guard._state.daily_pnl_history.append(
                {
                    "date": f"day_{i:03d}",
                    "pnl": 100.0,
                }
            )

        _set_today(guard, "day_xxx", 100.0)
        guard.record_daily_pnl(50.0, "day_yyy")  # triggers rollover

        # First entry should NOT be the original first (day_000)
        first_date = guard.state.daily_pnl_history[0]["date"]
        assert first_date != "day_000"
        # Last entry should be the most recently appended (the rolled-over day)
        last_entry = guard.state.daily_pnl_history[-1]
        assert last_entry["date"] == "day_xxx"
        assert last_entry["pnl"] == pytest.approx(100.0)
        # 60 total entries
        assert len(guard.state.daily_pnl_history) == 60

    def test_history_trim_via_update_path(self, guard):
        """History trimming also runs during update() CET rollover."""
        # Pre-populate 62 history entries
        for i in range(62):
            guard._state.daily_pnl_history.append(
                {
                    "date": f"2026-04-{i + 1:02d}",
                    "pnl": 50.0,
                }
            )

        # Set up state as if we're on "2026-07-08" with pnl=100
        _set_today(guard, "2026-07-08", 100.0)
        guard._state.daily_loss_date = "2026-07-08"

        # update() with next-day now triggers rollover + trim
        # 04:30 UTC = 00:30 EDT (next Toronto day)
        next_day = datetime(2026, 7, 9, 4, 30, tzinfo=timezone.utc)
        guard.update(current_balance=10000.0, open_positions=0, now=next_day)

        # 62 + 1 (rolled over) = 63, then trimmed to 60
        assert len(guard.state.daily_pnl_history) == 60


# ── 8. check_best_day_rule edge cases ─────────────────────────────────────


class TestCheckBestDayRuleEdgeCases:
    """Edge cases and configuration of ``check_best_day_rule()``."""

    def test_empty_history_returns_none(self, guard):
        """Fresh guard with no trades returns None from ``check_best_day_rule``."""
        assert guard.check_best_day_rule() is None

    def test_today_zero_pnl_excluded(self, guard):
        """If today's daily_pnl is 0, it's not a positive day."""
        _seed_history(guard, [("2026-07-08", 100.0)])
        _set_today(guard, "2026-07-09", 0.0)
        # Only 1 positive day in history → no violation
        assert guard.check_best_day_rule() is None

    def test_today_negative_pnl_excluded(self, guard):
        """If today's daily_pnl is negative, it's excluded from positive days."""
        _seed_history(guard, [("2026-07-08", 100.0)])
        _set_today(guard, "2026-07-09", -50.0)
        assert guard.check_best_day_rule() is None

    def test_check_best_day_rule_is_thread_safe(self, guard):
        """``check_best_day_rule`` acquires the lock — verify it doesn't deadlock."""
        # If this returns, the lock is acquired/released properly
        result = guard.check_best_day_rule()
        assert result is None

    def test_check_best_day_rule_violation_message_format(self, guard):
        """Violation message should mention 'Best day', ratio, and cap."""
        _seed_history(guard, [("2026-07-08", 200.0)])
        _set_today(guard, "2026-07-09", 50.0)
        result = guard.check_best_day_rule()
        assert result is not None
        # The message should contain:
        assert "Best day" in result
        assert "80.0%" in result  # 200 / (200+50) = 0.80
        assert "50%" in result  # cap: 50%
        assert "200.00" in result  # best day value
        assert "250.00" in result  # total positive


# ── 9. Custom best_day_cap_pct ─────────────────────────────────────────────


class TestCustomBestDayCap:
    """Custom ``best_day_cap_pct`` overrides default 50%."""

    def test_custom_cap_30_violation(self, guard_no_ks):
        """cap=0.30 → 33% split violates."""
        # best=100, other=200, total=300, ratio=33% > 30% → violation
        custom_guard = FTMOGuard(
            kill_switch=None,
            starting_balance=10000.0,
            best_day_cap_pct=0.30,
        )
        _seed_history(custom_guard, [("2026-07-08", 100.0)])
        _set_today(custom_guard, "2026-07-09", 200.0)
        assert custom_guard.check_best_day_rule() is not None

    def test_custom_cap_30_allows_lower(self, guard_no_ks):
        """cap=0.30 → 29.4% split (4 days) is allowed."""
        custom_guard = FTMOGuard(
            kill_switch=None,
            starting_balance=10000.0,
            best_day_cap_pct=0.30,
        )
        # 4 days: best=100, others=80, 80, 80. Total=340. Ratio=29.4% < 30%
        # (2 days can't go below 50% unless equal; need 4 days for < 30%)
        _seed_history(
            custom_guard,
            [
                ("2026-07-07", 80.0),
                ("2026-07-08", 100.0),  # best day
                ("2026-07-09", 80.0),
            ],
        )
        _set_today(custom_guard, "2026-07-10", 80.0)
        assert custom_guard.check_best_day_rule() is None

    def test_cap_100_percent_never_violates(self, guard_no_ks):
        """cap=1.0 (100%) should never produce a violation."""
        cap_guard = FTMOGuard(
            kill_switch=None,
            starting_balance=10000.0,
            best_day_cap_pct=1.0,
        )
        # best=1000, other=0.01, total=1000.01, ratio ≈ 1.0
        # ratio = 1000/1000.01 ≈ 0.99999 < 1.0 → no violation
        _seed_history(cap_guard, [("2026-07-08", 0.01)])
        _set_today(cap_guard, "2026-07-09", 1000.0)
        assert cap_guard.check_best_day_rule() is None

    def test_cap_zero_violates_with_two_days(self, guard_no_ks):
        """cap=0 → any 2+ positive days violates (ratio > 0 always)."""
        cap_guard = FTMOGuard(
            kill_switch=None,
            starting_balance=10000.0,
            best_day_cap_pct=0.0,
        )
        _seed_history(cap_guard, [("2026-07-08", 50.0)])
        _set_today(cap_guard, "2026-07-09", 50.0)
        # 50/100 = 0.5 > 0 → violation
        assert cap_guard.check_best_day_rule() is not None

    def test_default_cap_is_50_percent(self):
        """FTMOGuard with no cap arg uses 50%."""
        default_guard = FTMOGuard(kill_switch=None, starting_balance=10000.0)
        assert default_guard._best_day_cap_pct == 0.50


# ── 10. Recovery from best-day freeze ──────────────────────────────────────


class TestRecoveryFromFreeze:
    """When the best-day rule is no longer violated, action recovers to ALLOW."""

    def test_recovery_when_ratio_drops_below_cap(self, guard, kill_switch):
        """After adding more positive days, the ratio drops below 50% → ALLOW."""
        # First trigger a violation
        _seed_history(guard, [("2026-07-08", 200.0)])
        _set_today(guard, "2026-07-09", 50.0)
        action = guard.update(current_balance=10000.0, open_positions=0)
        assert action == FTMOAction.FREEZE

        # Now add another equal positive day to history so ratio drops
        _seed_history(
            guard,
            [("2026-07-08", 200.0), ("2026-07-09", 200.0)],
        )
        _set_today(guard, "2026-07-10", 50.0)
        # Positive days: 200 + 200 + 50 = 450. Best = 200. 200/450 = 44.4% → no violation
        action = guard.update(current_balance=10000.0, open_positions=0)
        assert action == FTMOAction.ALLOW
        assert guard.action_level == FTMOAction.ALLOW

    def test_persistent_violation_stays_frozen(self, guard):
        """If the violation persists, action stays FREEZE."""
        _seed_history(guard, [("2026-07-08", 200.0)])
        _set_today(guard, "2026-07-09", 50.0)
        # First update triggers FREEZE
        guard.update(current_balance=10000.0, open_positions=0)
        assert guard.action_level == FTMOAction.FREEZE

        # Second update with same state — still violation → still FREEZE
        action = guard.update(current_balance=10000.0, open_positions=0)
        assert action == FTMOAction.FREEZE
        assert guard.action_level == FTMOAction.FREEZE

    def test_no_breach_when_ratio_at_boundary(self, guard):
        """At exactly 50%, no violation → action stays ALLOW."""
        _seed_history(guard, [("2026-07-08", 100.0)])
        _set_today(guard, "2026-07-09", 100.0)
        action = guard.update(current_balance=10000.0, open_positions=0)
        assert action == FTMOAction.ALLOW
        assert guard.action_level == FTMOAction.ALLOW


# ── 11. State serialization ───────────────────────────────────────────────


class TestStateSerialization:
    """Best-day rule fields are included in ``state.to_dict()`` and state property."""

    def test_state_includes_daily_pnl_fields(self, guard):
        """``FTMOState.to_dict()`` should include all best-day rule fields."""
        state_dict = guard.state.to_dict()
        assert "daily_pnl" in state_dict
        assert "daily_pnl_date" in state_dict
        assert "daily_pnl_history" in state_dict

    def test_state_property_returns_copy(self, guard):
        """``guard.state`` property should return a copy (not the live state)."""
        guard.record_daily_pnl(100.0, "2026-07-08")
        state1 = guard.state
        state1.daily_pnl = 999.0  # Mutate the copy
        state2 = guard.state
        # Real state should be unchanged
        assert state2.daily_pnl == pytest.approx(100.0)

    def test_state_history_copied_by_value(self, guard):
        """``daily_pnl_history`` in returned state should be a copy."""
        _seed_history(guard, [("2026-07-08", 100.0)])
        state1 = guard.state
        state1.daily_pnl_history.clear()  # Mutate the copy
        state2 = guard.state
        # Real state should be unchanged
        assert len(state2.daily_pnl_history) == 1
        assert state2.daily_pnl_history[0]["date"] == "2026-07-08"

    def test_get_status_includes_daily_pnl(self, guard):
        """``get_status()`` returns the same fields as ``to_dict()``."""
        guard.record_daily_pnl(75.0, "2026-07-08")
        status = guard.get_status()
        assert status["daily_pnl"] == pytest.approx(75.0)
        assert status["daily_pnl_date"] == "2026-07-08"
        assert "daily_pnl_history" in status


# ── 12. FTMOBreachType enum ────────────────────────────────────────────────


class TestBestDayBreachType:
    """``FTMOBreachType.BEST_DAY_RULE`` enum value exists and is correct."""

    def test_best_day_breach_enum_value(self):
        """``BEST_DAY_RULE`` should be a valid FTMOBreachType with value 'best_day_rule'."""
        assert FTMOBreachType.BEST_DAY_RULE.value == "best_day_rule"

    def test_best_day_breach_in_breach_history_detail(self, guard):
        """A best-day violation's breach detail should describe the violation."""
        _seed_history(guard, [("2026-07-08", 200.0)])
        _set_today(guard, "2026-07-09", 50.0)
        guard.update(current_balance=10000.0, open_positions=0)
        # Check breach history
        best_day_breaches = [b for b in guard.state.breach_history if b["type"] == FTMOBreachType.BEST_DAY_RULE.value]
        assert len(best_day_breaches) >= 1
        assert "Best day" in best_day_breaches[0]["detail"]
        assert best_day_breaches[0]["action"] == FTMOAction.FREEZE.value

    def test_breach_history_ts_is_iso_format(self, guard):
        """Each breach event has an ISO-format timestamp."""
        _seed_history(guard, [("2026-07-08", 200.0)])
        _set_today(guard, "2026-07-09", 50.0)
        guard.update(current_balance=10000.0, open_positions=0)
        for breach in guard.state.breach_history:
            assert "ts" in breach
            # ISO format: parseable by datetime.fromisoformat
            datetime.fromisoformat(breach["ts"])


# ── 13. update() integration: best-day check runs first ───────────────────


class TestUpdateIntegration:
    """Best-day rule runs as part of ``update()`` and is checked before other rules."""

    def test_best_day_checked_before_daily_loss(self, guard, kill_switch):
        """If both best-day and daily-loss would fire, best-day fires first."""
        # Set up best-day violation
        _seed_history(guard, [("2026-07-08", 200.0)])
        _set_today(guard, "2026-07-09", 50.0)
        # Also trigger daily loss: 5% of 10k = 500 below starting
        # balance = 10000 - 500 = 9500
        action = guard.update(current_balance=9500.0, open_positions=0)
        # Both should be FREEZE, but best-day is checked first
        assert action == FTMOAction.FREEZE
        # The first breach in history should be best-day
        first_breach = guard.state.breach_history[0]
        assert first_breach["type"] == FTMOBreachType.BEST_DAY_RULE.value

    def test_no_best_day_check_when_history_empty(self, guard):
        """With no history, best-day check returns None quickly."""
        # No _seed_history, no _set_today → fresh state
        action = guard.update(current_balance=10000.0, open_positions=0)
        assert action == FTMOAction.ALLOW
        # No breach should be recorded
        assert len(guard.state.breach_history) == 0

    def test_check_runs_every_update(self, guard, kill_switch):
        """Every ``update()`` call re-evaluates the best-day rule."""
        # First: no violation
        _seed_history(guard, [("2026-07-08", 100.0)])
        _set_today(guard, "2026-07-09", 100.0)
        action1 = guard.update(current_balance=10000.0, open_positions=0)
        assert action1 == FTMOAction.ALLOW

        # Now mutate state to a violation
        _set_today(guard, "2026-07-09", 500.0)
        # best=500, total=600, ratio=83.3% > 50% → violation
        action2 = guard.update(current_balance=10000.0, open_positions=0)
        assert action2 == FTMOAction.FREEZE
        kill_switch.activate_global_freeze.assert_called()
