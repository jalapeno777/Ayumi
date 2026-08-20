"""Tests for session_logic: session detection, kill zones, DST, weekly modifiers."""

from __future__ import annotations  # noqa: I001

from datetime import datetime, time

from signal_engine.session_logic import (
    SessionAnalyzer,
    _is_dst,
    get_ny_kz_hours,
)


# ── Helpers ─────────────────────────────────────────────────────────


def _utc(year, month, day, hour, minute=0):
    """Create a naive UTC datetime (as used by the module)."""
    return datetime(year, month, day, hour, minute)


# ── Session Detection ───────────────────────────────────────────────


class TestSessionDetection:
    def setup_method(self):
        self.sa = SessionAnalyzer()

    def test_asia_session(self):
        assert self.sa.get_current_session(_utc(2026, 1, 1, 3, 0)) == "ASIA"

    def test_london_session(self):
        assert self.sa.get_current_session(_utc(2026, 1, 1, 10, 0)) == "LONDON"

    def test_ny_session(self):
        assert self.sa.get_current_session(_utc(2026, 1, 1, 18, 0)) == "NY"

    def test_london_ny_overlap(self):
        assert self.sa.get_current_session(_utc(2026, 1, 1, 14, 0)) == "LONDON_NY"

    def test_asia_london_overlap(self):
        assert self.sa.get_current_session(_utc(2026, 1, 1, 7, 30)) == "ASIA_LONDON"

    def test_outside_all_sessions(self):
        assert self.sa.get_current_session(_utc(2026, 1, 1, 22, 0)) == "OUTSIDE"

    def test_session_boundary_start(self):
        assert self.sa.get_current_session(_utc(2026, 1, 1, 0, 0)) != "OUTSIDE"

    def test_session_boundary_end(self):
        # At 21:00 UTC, NY session ends (end is exclusive)
        assert self.sa.get_current_session(_utc(2026, 1, 1, 21, 0)) == "OUTSIDE"


# ── DST ─────────────────────────────────────────────────────────────


class TestDST:
    def test_is_dst_summer(self):
        assert _is_dst(_utc(2026, 7, 1, 12, 0)) is True

    def test_is_dst_winter(self):
        assert _is_dst(_utc(2026, 1, 15, 12, 0)) is False

    def test_dst_transition_march(self):
        # 2026 DST starts March 8 (2nd Sunday)
        assert _is_dst(_utc(2026, 3, 7, 12, 0)) is False  # before
        assert _is_dst(_utc(2026, 3, 9, 12, 0)) is True  # after

    def test_dst_transition_november(self):
        # 2026 DST ends November 1 (1st Sunday)
        assert _is_dst(_utc(2026, 10, 31, 12, 0)) is True  # before
        assert _is_dst(_utc(2026, 11, 2, 12, 0)) is False  # after

    def test_get_ny_kz_hours_edt(self):
        start, end = get_ny_kz_hours(is_dst=True)
        assert start == time(12, 30)
        assert end == time(14, 0)

    def test_get_ny_kz_hours_est(self):
        start, end = get_ny_kz_hours(is_dst=False)
        assert start == time(13, 30)
        assert end == time(15, 0)


# ── Kill Zones ──────────────────────────────────────────────────────


class TestKillZones:
    def setup_method(self):
        self.sa = SessionAnalyzer()

    def test_asia_kill_zone(self):
        assert self.sa.is_kill_zone(_utc(2026, 6, 1, 0, 45)) is True

    def test_london_kill_zone(self):
        assert self.sa.is_kill_zone(_utc(2026, 6, 1, 7, 45)) is True

    def test_ny_kill_zone_edt(self):
        assert self.sa.is_kill_zone(_utc(2026, 6, 1, 13, 0)) is True

    def test_not_in_kill_zone(self):
        assert self.sa.is_kill_zone(_utc(2026, 6, 1, 5, 0)) is False

    def test_kill_zone_name_ny(self):
        assert self.sa.get_kill_zone_name(_utc(2026, 6, 1, 13, 0)) == "NY"

    def test_kill_zone_name_none(self):
        assert self.sa.get_kill_zone_name(_utc(2026, 6, 1, 5, 0)) is None


# ── Weekly Modifiers ────────────────────────────────────────────────


class TestWeeklyModifiers:
    def setup_method(self):
        self.sa = SessionAnalyzer()

    def test_monday_negative(self):
        assert self.sa.get_weekly_modifier(_utc(2026, 6, 1, 12, 0)) == -0.10  # Monday

    def test_tuesday_positive(self):
        assert self.sa.get_weekly_modifier(_utc(2026, 6, 2, 12, 0)) == 0.05

    def test_friday_negative(self):
        assert self.sa.get_weekly_modifier(_utc(2026, 6, 5, 12, 0)) == -0.10

    def test_thursday_neutral(self):
        assert self.sa.get_weekly_modifier(_utc(2026, 6, 4, 12, 0)) == 0.0


# ── Phase Scoring ───────────────────────────────────────────────────


class TestPhaseScoring:
    def setup_method(self):
        self.sa = SessionAnalyzer()

    def test_outside_session_zero_score(self):
        result = self.sa.score_session_phase("OUTSIDE")
        assert result["phase_score"] == 0.0

    def test_bar_closed_false_returns_zero(self):
        result = self.sa.score_session_phase_with_time("LONDON", _utc(2026, 6, 1, 8, 0), bar_closed=False)
        assert result["phase_score"] == 0.0
        assert result.get("bar_closed") is False

    def test_asia_control_tight_range(self):
        result = self.sa.score_session_phase("ASIA", price_action={"asia_range_pct": 0.01, "asia_direction": "bullish"})
        assert result.get("asia_control_score") == 1.0
        assert result["directional_bias"] == "bullish"
