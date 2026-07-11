"""
Configurable session time definitions for the trading bot.
All times are UTC.
"""

from dataclasses import dataclass
from datetime import time
from enum import Enum

import pandas as pd


@dataclass(frozen=True)
class SessionDefinition:
    """Defines a trading session with start and end times."""

    start: time
    end: time


# Killzone session times (when major exchanges have high volume)
class KillzoneHours:
    LONDON_OPEN_START = time(7, 0)
    LONDON_OPEN_END = time(9, 0)
    NY_OPEN_START = time(12, 0)
    NY_OPEN_END = time(14, 0)
    OVERLAP_START = time(13, 0)
    OVERLAP_END = time(16, 0)


# Session range mean reversion times
class SessionRangeHours:
    ASIAN_START = time(0, 0)
    ASIAN_END = time(7, 0)
    EARLY_LONDON_END = time(9, 0)
    LONDON_START = time(7, 0)
    LONDON_END = time(11, 0)
    NY_OPEN_START = time(12, 0)
    NY_OPEN_END = time(15, 0)
    LONDON_NY_OVERLAP_START = time(12, 0)
    LONDON_NY_OVERLAP_END = time(16, 0)
    NY_CLOSE_START = time(16, 0)
    NY_CLOSE_END = time(20, 0)


# Default killzone sessions - tuples of (start, end)
DEFAULT_KILLZONES = [
    (KillzoneHours.LONDON_OPEN_START, KillzoneHours.LONDON_OPEN_END),
    (KillzoneHours.NY_OPEN_START, KillzoneHours.NY_OPEN_END),
    (KillzoneHours.OVERLAP_START, KillzoneHours.OVERLAP_END),
]

# Default preferred sessions for strategy filtering
DEFAULT_PREFERRED_SESSIONS = {"london", "ny_am"}


class TradingSession(Enum):
    """Major forex trading sessions used for spread modelling.

    Boundaries are UTC and align with typical institutional hours.
    """

    ASIAN = "asian"
    LONDON = "london"
    NY_OVERLAP = "ny_overlap"
    NY_AFTERNOON = "ny_afternoon"
    OFF_HOURS = "off_hours"


# UTC time windows for each session
_SESSION_WINDOWS = {
    TradingSession.ASIAN: (time(0, 0), time(7, 0)),
    TradingSession.LONDON: (time(7, 0), time(12, 0)),
    TradingSession.NY_OVERLAP: (time(12, 0), time(16, 0)),
    TradingSession.NY_AFTERNOON: (time(16, 0), time(20, 0)),
    TradingSession.OFF_HOURS: (time(20, 0), time(23, 59)),
}


def get_trading_session(timestamp: pd.Timestamp) -> TradingSession:
    """Return the :class:`TradingSession` for *timestamp* (UTC).

    Parameters
    ----------
    timestamp:
        A timezone-aware or naive ``pd.Timestamp``.  If naive it is
        assumed to be UTC.

    Returns
    -------
    TradingSession
    """
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC")
    t = timestamp.time()

    for session, (start, end) in _SESSION_WINDOWS.items():
        if start <= t < end:
            return session

    # Handles the 23:59 → 00:00 boundary
    return TradingSession.ASIAN
