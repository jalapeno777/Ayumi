"""Market hours utility for forex trading.

Forex market is closed from Friday ~21:55 UTC to Sunday ~21:00 UTC.
During market close, the cTrader feed stops sending ticks, which would
otherwise trigger the heartbeat-based kill switch.

Use this to gate kill switch triggers and feed health checks.
"""

from __future__ import annotations

from datetime import datetime, timezone

_WEEKEND_CLOSE_HOUR_UTC = 21
_WEEKEND_CLOSE_MINUTE_UTC = 55
_WEEKEND_OPEN_HOUR_UTC = 21


def is_forex_market_closed() -> bool:
    """Return True if the forex market is currently closed.

    Forex hours: closes Friday 21:55 UTC, opens Sunday 21:00 UTC.
    """
    now = datetime.now(timezone.utc)
    if now.weekday() == 4:  # Friday
        if now.hour > _WEEKEND_CLOSE_HOUR_UTC:
            return True
        if now.hour == _WEEKEND_CLOSE_HOUR_UTC and now.minute >= _WEEKEND_CLOSE_MINUTE_UTC:
            return True
    if now.weekday() == 5:  # Saturday
        return True
    if now.weekday() == 6:  # Sunday
        if now.hour < _WEEKEND_OPEN_HOUR_UTC:
            return True
        return False
    if now.weekday() == 0 and now.hour < _WEEKEND_OPEN_HOUR_UTC:  # Monday before open
        return True
    return False
