"""DST boundary tests for daily drawdown rollover on America/Toronto timezone.

Validates that the trading-day reset correctly handles daylight saving time
transitions:
  - Spring forward (2nd Sunday in March): EST → EDT (UTC-5 → UTC-4)
  - Fall back (1st Sunday in November): EDT → EST (UTC-4 → UTC-5)

The production code uses ``ZoneInfo("America/Toronto")`` which handles DST
automatically, but these tests guard against regressions and document the
expected UTC offsets at each boundary.

Covers acceptance criterion: "New DST boundary test added (spring forward,
fall back)"
"""

from datetime import datetime, timezone

import pytest
from zoneinfo import ZoneInfo

from risk.ftmo_guard import (
    FTMOAction,
    FTMOGuard,
    _TRADING_TZ,
    _toronto_midnight_utc,
    _trading_date,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def guard():
    """Fresh FTMOGuard with $10k starting balance."""
    return FTMOGuard(starting_balance=10_000.0)


# ---------------------------------------------------------------------------
# 1. _trading_date — spring-forward boundary (March 8, 2026)
# ---------------------------------------------------------------------------


class TestTradingDateSpringForward:
    """Verify _trading_date across the EST→EDT transition on March 8, 2026.

    Before spring forward: Toronto = EST (UTC-5), midnight = 05:00 UTC
    After spring forward:  Toronto = EDT (UTC-4), midnight = 04:00 UTC
    The clock jumps from 02:00 EST to 03:00 EDT (07:00 UTC).
    """

    def test_day_before_spring_forward(self):
        """March 7 evening UTC is still March 7 in Toronto (EST)."""
        # 22:00 UTC = 17:00 EST March 7
        result = _trading_date(datetime(2026, 3, 7, 22, 0, tzinfo=timezone.utc))
        assert result == "2026-03-07"

    def test_last_minute_before_midnight_est(self):
        """04:59 UTC March 8 = 23:59 EST March 7."""
        result = _trading_date(datetime(2026, 3, 8, 4, 59, tzinfo=timezone.utc))
        assert result == "2026-03-07"

    def test_midnight_est_triggers_new_day(self):
        """05:00 UTC March 8 = 00:00 EST March 8 (midnight Toronto)."""
        result = _trading_date(datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc))
        assert result == "2026-03-08"

    def test_just_before_spring_forward(self):
        """06:59 UTC March 8 = 01:59 EST March 8 (last moment before jump)."""
        result = _trading_date(datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc))
        assert result == "2026-03-08"

    def test_after_spring_forward_skipped_hour(self):
        """07:00 UTC March 8 = 03:00 EDT March 8 (2 AM skipped)."""
        result = _trading_date(datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc))
        assert result == "2026-03-08"

    def test_end_of_spring_forward_day(self):
        """03:59 UTC March 9 = 23:59 EDT March 8."""
        result = _trading_date(datetime(2026, 3, 9, 3, 59, tzinfo=timezone.utc))
        assert result == "2026-03-08"

    def test_midnight_edt_after_spring_forward(self):
        """04:00 UTC March 9 = 00:00 EDT March 9.

        This confirms midnight is now at 04:00 UTC (EDT) not 05:00 UTC (EST).
        """
        result = _trading_date(datetime(2026, 3, 9, 4, 0, tzinfo=timezone.utc))
        assert result == "2026-03-09"

    def test_midnight_offset_changes_across_boundary(self):
        """The UTC offset of Toronto midnight changes from 05:00 to 04:00
        after spring forward — confirm the day boundary shifts."""
        # Midnight March 8 (still EST): 05:00 UTC
        before = _trading_date(datetime(2026, 3, 8, 4, 59, tzinfo=timezone.utc))
        # Midnight March 9 (now EDT): 04:00 UTC
        after = _trading_date(datetime(2026, 3, 9, 3, 59, tzinfo=timezone.utc))
        assert before == "2026-03-07"
        assert after == "2026-03-08"


# ---------------------------------------------------------------------------
# 2. _trading_date — fall-back boundary (November 1, 2026)
# ---------------------------------------------------------------------------


class TestTradingDateFallBack:
    """Verify _trading_date across the EDT→EST transition on November 1, 2026.

    Before fall back: Toronto = EDT (UTC-4), midnight = 04:00 UTC
    After fall back:  Toronto = EST (UTC-5), midnight = 05:00 UTC
    The clock falls from 02:00 EDT to 01:00 EST (01:00-02:00 local repeats).
    """

    def test_day_before_fall_back(self):
        """October 31 evening UTC is still Oct 31 in Toronto (EDT)."""
        # 23:00 UTC = 19:00 EDT October 31
        result = _trading_date(datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc))
        assert result == "2026-10-31"

    def test_last_minute_before_midnight_edt(self):
        """03:59 UTC Nov 1 = 23:59 EDT Oct 31."""
        result = _trading_date(datetime(2026, 11, 1, 3, 59, tzinfo=timezone.utc))
        assert result == "2026-10-31"

    def test_midnight_edt_triggers_new_day(self):
        """04:00 UTC Nov 1 = 00:00 EDT Nov 1 (midnight Toronto)."""
        result = _trading_date(datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc))
        assert result == "2026-11-01"

    def test_after_fall_back(self):
        """08:00 UTC Nov 1 = 03:00 EST Nov 1 (after fall back to EST)."""
        result = _trading_date(datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc))
        assert result == "2026-11-01"

    def test_end_of_fall_back_day(self):
        """Nov 1 ends at 23:59 EST = 04:59 UTC Nov 2."""
        result = _trading_date(datetime(2026, 11, 2, 4, 59, tzinfo=timezone.utc))
        assert result == "2026-11-01"

    def test_midnight_est_after_fall_back(self):
        """05:00 UTC Nov 2 = 00:00 EST Nov 2.

        Confirms midnight shifted from 04:00 UTC (EDT) to 05:00 UTC (EST).
        """
        result = _trading_date(datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc))
        assert result == "2026-11-02"

    def test_midnight_offset_changes_across_boundary(self):
        """The UTC offset of Toronto midnight changes from 04:00 to 05:00
        after fall back — confirm the day boundary shifts."""
        # Midnight Nov 1 (EDT): 04:00 UTC
        before = _trading_date(datetime(2026, 11, 1, 3, 59, tzinfo=timezone.utc))
        # Midnight Nov 2 (EST): 05:00 UTC
        after = _trading_date(datetime(2026, 11, 2, 4, 59, tzinfo=timezone.utc))
        assert before == "2026-10-31"
        assert after == "2026-11-01"


# ---------------------------------------------------------------------------
# 3. _toronto_midnight_utc — DST boundary correctness
# ---------------------------------------------------------------------------


class TestTorontoMidnightUTCDST:
    """Verify _toronto_midnight_utc returns correct UTC instant at DST boundaries."""

    def test_before_spring_forward_midnight_at_05_utc(self):
        """On March 7 (EST), next Toronto midnight is 05:00 UTC March 8."""
        now = datetime(2026, 3, 7, 22, 0, tzinfo=timezone.utc)  # 17:00 EST
        midnight = _toronto_midnight_utc(now)
        assert midnight == datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc)

    def test_after_spring_forward_midnight_at_04_utc(self):
        """On March 8 evening (EDT), next Toronto midnight is 04:00 UTC March 9."""
        now = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)  # 08:00 EDT
        midnight = _toronto_midnight_utc(now)
        assert midnight == datetime(2026, 3, 9, 4, 0, tzinfo=timezone.utc)

    def test_before_fall_back_midnight_at_04_utc(self):
        """On Oct 31 evening (EDT), next Toronto midnight is 04:00 UTC Nov 1."""
        now = datetime(2026, 10, 31, 22, 0, tzinfo=timezone.utc)  # 18:00 EDT
        midnight = _toronto_midnight_utc(now)
        assert midnight == datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)

    def test_after_fall_back_midnight_at_05_utc(self):
        """On Nov 1 afternoon (EST), next Toronto midnight is 05:00 UTC Nov 2."""
        now = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)  # 13:00 EST
        midnight = _toronto_midnight_utc(now)
        assert midnight == datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 4. FTMOGuard daily reset — spring-forward boundary
# ---------------------------------------------------------------------------


class TestFTMOGuardDailyResetSpringForward:
    """Verify FTMOGuard resets daily loss across the spring-forward boundary."""

    def test_daily_loss_resets_across_spring_forward(self, guard):
        """Trigger a daily loss on March 7, then cross midnight (EST) into March 8.

        The midnight on March 8 is at 05:00 UTC (EST). After spring forward
        at 07:00 UTC, the day is still March 8 — no double reset.
        """
        # March 7 10:00 UTC (05:00 EST) — trigger daily loss
        guard.update(
            current_balance=9500.0,
            open_positions=0,
            now=datetime(2026, 3, 7, 10, 0, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct >= 5.0
        assert guard.action_level == FTMOAction.FREEZE

        # March 8 04:59 UTC (23:59 EST March 7) — still March 7, loss persists
        guard.update(
            current_balance=9500.0,
            open_positions=0,
            now=datetime(2026, 3, 8, 4, 59, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct >= 5.0  # not reset yet

        # March 8 05:00 UTC (00:00 EST March 8) — new day, loss resets
        action = guard.update(
            current_balance=10000.0,
            open_positions=0,
            now=datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct == 0.0
        assert action == FTMOAction.ALLOW

        # March 8 07:00 UTC (03:00 EDT) — still March 8, no second reset
        guard.update(
            current_balance=9500.0,
            open_positions=0,
            now=datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc),
        )
        # New daily loss triggered on March 8
        assert guard.daily_loss_pct >= 5.0

    def test_daily_loss_persists_through_spring_forward_day(self, guard):
        """Loss triggered after spring forward (EDT) resets at 04:00 UTC next day."""
        # March 8 08:00 UTC (04:00 EDT) — trigger loss
        guard.update(
            current_balance=9500.0,
            open_positions=0,
            now=datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct >= 5.0

        # March 9 03:59 UTC (23:59 EDT March 8) — still March 8, loss persists
        guard.update(
            current_balance=9500.0,
            open_positions=0,
            now=datetime(2026, 3, 9, 3, 59, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct >= 5.0  # not reset

        # March 9 04:00 UTC (00:00 EDT March 9) — new day
        action = guard.update(
            current_balance=10000.0,
            open_positions=0,
            now=datetime(2026, 3, 9, 4, 0, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct == 0.0
        assert action == FTMOAction.ALLOW


# ---------------------------------------------------------------------------
# 5. FTMOGuard daily reset — fall-back boundary
# ---------------------------------------------------------------------------


class TestFTMOGuardDailyResetFallBack:
    """Verify FTMOGuard resets daily loss across the fall-back boundary."""

    def test_daily_loss_resets_across_fall_back(self, guard):
        """Trigger daily loss on Oct 31 (EDT), cross midnight into Nov 1 (EDT).

        Fall back happens at 06:00 UTC (02:00 EDT → 01:00 EST).
        The next midnight (Nov 2) is at 05:00 UTC (EST).
        """
        # Oct 31 15:00 UTC (11:00 EDT) — trigger daily loss
        guard.update(
            current_balance=9500.0,
            open_positions=0,
            now=datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct >= 5.0

        # Nov 1 03:59 UTC (23:59 EDT Oct 31) — still Oct 31, loss persists
        guard.update(
            current_balance=9500.0,
            open_positions=0,
            now=datetime(2026, 11, 1, 3, 59, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct >= 5.0  # not reset

        # Nov 1 04:00 UTC (00:00 EDT Nov 1) — new day
        action = guard.update(
            current_balance=10000.0,
            open_positions=0,
            now=datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct == 0.0
        assert action == FTMOAction.ALLOW

    def test_daily_loss_after_fall_back_resets_at_est_midnight(self, guard):
        """Loss triggered after fall back (EST) resets at 05:00 UTC next day.

        Nov 1 afternoon is EST. The midnight for Nov 2 should be 05:00 UTC.
        """
        # Nov 1 18:00 UTC (13:00 EST) — trigger loss (after fall back)
        guard.update(
            current_balance=9500.0,
            open_positions=0,
            now=datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct >= 5.0

        # Nov 2 04:59 UTC (23:59 EST Nov 1) — still Nov 1, loss persists
        guard.update(
            current_balance=9500.0,
            open_positions=0,
            now=datetime(2026, 11, 2, 4, 59, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct >= 5.0  # not reset

        # Nov 2 05:00 UTC (00:00 EST Nov 2) — new day
        action = guard.update(
            current_balance=10000.0,
            open_positions=0,
            now=datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc),
        )
        assert guard.daily_loss_pct == 0.0
        assert action == FTMOAction.ALLOW


# ---------------------------------------------------------------------------
# 6. DST offset verification
# ---------------------------------------------------------------------------


class TestDSTOffsetVerification:
    """Document and verify the UTC offsets at each DST phase."""

    def test_est_offset_before_spring_forward(self):
        """March 7 is EST (UTC-5)."""
        utc_time = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
        toronto_time = utc_time.astimezone(ZoneInfo("America/Toronto"))
        assert toronto_time.utcoffset().total_seconds() == -5 * 3600

    def test_edt_offset_after_spring_forward(self):
        """March 8 afternoon is EDT (UTC-4)."""
        utc_time = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        toronto_time = utc_time.astimezone(ZoneInfo("America/Toronto"))
        assert toronto_time.utcoffset().total_seconds() == -4 * 3600

    def test_edt_offset_before_fall_back(self):
        """October 31 is EDT (UTC-4)."""
        utc_time = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        toronto_time = utc_time.astimezone(ZoneInfo("America/Toronto"))
        assert toronto_time.utcoffset().total_seconds() == -4 * 3600

    def test_est_offset_after_fall_back(self):
        """November 1 afternoon is EST (UTC-5)."""
        utc_time = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)
        toronto_time = utc_time.astimezone(ZoneInfo("America/Toronto"))
        assert toronto_time.utcoffset().total_seconds() == -5 * 3600

    def test_trading_tz_is_america_toronto(self):
        """Confirm _TRADING_TZ is set to America/Toronto."""
        assert str(_TRADING_TZ) == "America/Toronto"
