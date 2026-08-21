"""Unit tests for is_forex_market_closed().

Covers the 18 boundary cases specified in card ee53643d (fix-weekend-market-closed):
- 8 OPEN  timestamps (Sun 21:00 UTC, Mon all day, Thu midday, Fri 21:59:59)
- 9 CLOSED timestamps (Fri 22:00 onward, all of Sat, Sun before 21:00)
- 3 exact-edge boundaries (Fri 21:59:59, Fri 22:00:00, Sun 21:00:00)

Real forex weekend: closes Friday 22:00 UTC, reopens Sunday 21:00 UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from adapters.ctrader.market_hours import is_forex_market_closed


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """Helper: build a UTC datetime for a specific (Y, M, D, H, M, S)."""
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


# Reference week: Monday 2026-07-06 ... Sunday 2026-07-12
# Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
_MON = _utc(2026, 7, 6, 12, 0)  # Monday midday
_TUE = _utc(2026, 7, 7, 12, 0)
_WED = _utc(2026, 7, 8, 12, 0)
_THU = _utc(2026, 7, 9, 12, 0)
_FRI_OPEN = _utc(2026, 7, 10, 12, 0)  # Friday midday — open
_FRI_215959 = _utc(2026, 7, 10, 21, 59, 59)  # Friday 21:59:59 — last open second
_FRI_220000 = _utc(2026, 7, 10, 22, 0, 0)  # Friday 22:00:00 — first closed second
_FRI_220001 = _utc(2026, 7, 10, 22, 0, 1)  # Friday 22:00:01 — closed
_SAT_0000 = _utc(2026, 7, 11, 0, 0)  # Saturday midnight — closed
_SAT_1200 = _utc(2026, 7, 11, 12, 0)  # Saturday midday — closed
_SAT_215959 = _utc(2026, 7, 11, 21, 59, 59)  # Saturday late — closed
_SAT_235959 = _utc(2026, 7, 11, 23, 59, 59)  # Saturday last second — closed
_SUN_0000 = _utc(2026, 7, 12, 0, 0)  # Sunday midnight — closed
_SUN_1200 = _utc(2026, 7, 12, 12, 0)  # Sunday midday — closed
_SUN_205959 = _utc(2026, 7, 12, 20, 59, 59)  # Sunday 20:59:59 — last closed second
_SUN_210000 = _utc(2026, 7, 12, 21, 0, 0)  # Sunday 21:00:00 — first open second
_SUN_210001 = _utc(2026, 7, 12, 21, 0, 1)  # Sunday 21:00:01 — open
_SUN_2200 = _utc(2026, 7, 12, 22, 0)  # Sunday late — open
_MON_0900 = _utc(2026, 7, 13, 9, 0)  # Next Monday morning — open
_MON_205959 = _utc(2026, 7, 13, 20, 59, 59)  # Next Monday 20:59:59 — open
_MON_2100 = _utc(2026, 7, 13, 21, 0)  # Next Monday 21:00 — open


# ── OPEN cases (8) ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "ts",
    [
        pytest.param(_SUN_210000, id="sun_21_00_00_exact_open"),
        pytest.param(_SUN_210001, id="sun_21_00_01"),
        pytest.param(_SUN_2200, id="sun_22_00"),
        pytest.param(_MON_0900, id="mon_09_00"),
        pytest.param(_MON_205959, id="mon_20_59_59"),
        pytest.param(_MON_2100, id="mon_21_00"),
        pytest.param(_THU, id="thu_12_00"),
        pytest.param(_FRI_215959, id="fri_21_59_59_last_open_second"),
    ],
)
def test_market_open(ts: datetime) -> None:
    assert is_forex_market_closed(ts) is False, f"Expected market OPEN at {ts.isoformat()} but got CLOSED"


# ── CLOSED cases (9) ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "ts",
    [
        pytest.param(_FRI_220000, id="fri_22_00_00_exact_closed"),
        pytest.param(_FRI_220001, id="fri_22_00_01"),
        pytest.param(_SAT_0000, id="sat_00_00"),
        pytest.param(_SAT_1200, id="sat_12_00"),
        pytest.param(_SAT_215959, id="sat_21_59_59"),
        pytest.param(_SAT_235959, id="sat_23_59_59"),
        pytest.param(_SUN_0000, id="sun_00_00"),
        pytest.param(_SUN_1200, id="sun_12_00"),
        pytest.param(_SUN_205959, id="sun_20_59_59_last_closed_second"),
    ],
)
def test_market_closed(ts: datetime) -> None:
    assert is_forex_market_closed(ts) is True, f"Expected market CLOSED at {ts.isoformat()} but got OPEN"


# ── Explicit boundary edges (spec calls out these three) ──────────────────────
def test_fri_21_59_59_open() -> None:
    """Exactly 1 second before close → still open."""
    assert is_forex_market_closed(_FRI_215959) is False


def test_fri_22_00_00_closed() -> None:
    """Exactly at close → closed (the boundary itself is closed)."""
    assert is_forex_market_closed(_FRI_220000) is True


def test_sun_21_00_00_open() -> None:
    """Exactly at reopen → open (the boundary itself is open)."""
    assert is_forex_market_closed(_SUN_210000) is False


# ── Regression guard: the 24h phantom window must be gone ──────────────────────
@pytest.mark.parametrize(
    "ts",
    [
        pytest.param(_SUN_2200, id="sun_22_to_23_59_was_phantom"),
        pytest.param(_MON, id="mon_12_was_phantom"),
        pytest.param(_MON_0900, id="mon_morning_was_phantom"),
        pytest.param(_MON_205959, id="mon_20_59_59_was_phantom"),
    ],
)
def test_phantom_window_now_open(ts: datetime) -> None:
    """Mon 00:00–20:59 + Sun 21:00–23:59 used to incorrectly return True.

    The previous logic treated Monday 00:00–20:59 UTC as 'still closed',
    producing ~24 phantom 'closed' hours per weekend that suppressed
    watchdog kill-switch checks and reconnect logic.
    """
    assert is_forex_market_closed(ts) is False, f"Phantom-closed regression at {ts.isoformat()}: market should be open"


# ── Default-arg path: no exception, returns a bool ────────────────────────────
def test_no_argument_uses_now() -> None:
    """Calling without an argument must not raise and must return a bool."""
    result = is_forex_market_closed()
    assert isinstance(result, bool)
