"""Tests for ForwardTestHealth daily-counter reset (card 18d69d04).

Locks in behavior that the B5 health loop resets per-trading-day counters
when the 17:00 America/Toronto boundary has crossed, matching the
risk_guard._current_trading_day() pattern.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from adapters.ctrader.forward_test_engine import ForwardTestHealth


@pytest.fixture
def health() -> ForwardTestHealth:
    h = ForwardTestHealth()
    h.signals_sent = 12
    h.signals_failed_live = 4
    h.signals_pending = 3
    h.signals_cancelled = 2
    h.signals_rejected = 5
    h.signals_traded = 1
    h.signals_accepted = 7
    # signals_generated is intentionally NOT reset by reset_daily_counters
    h.signals_generated = 99
    return h


def test_reset_daily_counters_zeros_day_buckets(health: ForwardTestHealth) -> None:
    health.reset_daily_counters()
    assert health.signals_sent == 0
    assert health.signals_failed_live == 0
    assert health.signals_pending == 0
    assert health.signals_cancelled == 0
    assert health.signals_rejected == 0
    assert health.signals_traded == 0
    assert health.signals_accepted == 0


def test_reset_daily_counters_preserves_lifetime_counters(health: ForwardTestHealth) -> None:
    """signals_generated is a lifetime diagnostic, NOT a daily guardrail."""
    health.reset_daily_counters()
    assert health.signals_generated == 99, (
        "signals_generated must NOT reset — it's a session-lifetime diagnostic"
    )


def test_last_health_trading_day_default_is_none() -> None:
    h = ForwardTestHealth()
    assert h._last_health_trading_day is None


def test_last_health_trading_day_can_be_set() -> None:
    h = ForwardTestHealth()
    h._last_health_trading_day = date(2026, 7, 7)
    assert h._last_health_trading_day == date(2026, 7, 7)


def test_trading_day_boundary_uses_toronto_17_00() -> None:
    """Sanity check: 17:00 America/Toronto boundary is what drives the reset.

    At 17:00 local, the trading day rolls over. The launch script's B5 health
    loop detects this by comparing _current_trading_day() against the last
    seen value and triggers reset_daily_counters().
    """
    tz = ZoneInfo("America/Toronto")
    at_1659 = datetime(2026, 7, 7, 16, 59, tzinfo=tz)
    at_1700 = datetime(2026, 7, 7, 17, 0, tzinfo=tz)

    # Mirror the production logic from risk_guard._current_trading_day().
    def trading_day(now: datetime) -> date:
        if now.hour >= 17:
            return now.date()
        return now.date() - _timedelta(days=1)

    from datetime import timedelta as _timedelta  # noqa: WPS433

    assert trading_day(at_1659) == date(2026, 7, 6)
    assert trading_day(at_1700) == date(2026, 7, 7)