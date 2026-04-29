"""
Session definitions, phase scoring, and kill zone logic.

Implements §8 of the Signal & Confidence Engine spec.

Forex sessions are UTC-based:
- Asia: 00:00-07:00 UTC (§8.1)
- London: 07:00-16:00 UTC
- New York: 12:00-21:00 UTC
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional
from enum import Enum


class Session(Enum):
    ASIA = "asia"
    LONDON = "london"
    NEW_YORK = "ny"
    CLOSED = "closed"  # Weekend / no session


class SessionPhase(Enum):
    OPENING = "opening"   # First 90 minutes: score 1.0 (§8.2)
    MID = "mid"           # After 90min, before last 60min: score 0.5
    CLOSING = "closing"   # Last 60 minutes: score 0.2


@dataclass
class SessionInfo:
    session: Session
    phase: SessionPhase
    is_kill_zone: bool
    is_overlap: bool
    phase_score: float
    session_score: float  # Kill zone / overlap = 1.0, else 0.06


# §8.1 Session definitions with kill zone windows
SESSION_DEFINITIONS = {
    Session.ASIA: {
        "start": time(0, 0),
        "end": time(7, 0),
        "kill_start": time(0, 0),
        "kill_end": time(1, 30),
    },
    Session.LONDON: {
        "start": time(7, 0),
        "end": time(16, 0),
        "kill_start": time(7, 0),
        "kill_end": time(8, 30),
    },
    Session.NEW_YORK: {
        "start": time(12, 0),
        "end": time(21, 0),
        "kill_start": time(12, 30),
        "kill_end": time(14, 0),
    },
}

# Overlap windows — during overlaps, the later session takes priority
OVERLAPS = [
    (Session.ASIA, Session.LONDON, time(7, 0), time(8, 0)),
    (Session.LONDON, Session.NEW_YORK, time(12, 0), time(16, 0)),
]


def get_session_at_utc(dt: datetime) -> Session:
    """Return the active session at a given UTC datetime (§8.1)."""
    utc_time = dt.time()

    # Check overlaps first — later session takes priority
    for s1, s2, overlap_start, overlap_end in OVERLAPS:
        if overlap_start <= utc_time < overlap_end:
            return s2

    # Regular sessions
    if time(0, 0) <= utc_time < time(7, 0):
        return Session.ASIA
    elif time(7, 0) <= utc_time < time(12, 0):
        return Session.LONDON
    elif time(12, 0) <= utc_time < time(21, 0):
        return Session.NEW_YORK
    else:
        return Session.CLOSED


def get_session_info(dt: datetime) -> SessionInfo:
    """
    Get full session info including phase and kill zone status.
    
    Phase scoring (§8.2):
    - Opening (first 90 min): 1.0
    - Mid (after 90 min, before last 60 min): 0.5
    - Closing (last 60 min): 0.2
    
    Session score (§8.2):
    - Kill zone or overlap: 1.0
    - Otherwise: 0.06
    """
    session = get_session_at_utc(dt)
    utc_time = dt.time()

    sess_def = SESSION_DEFINITIONS.get(session)
    if sess_def is None:
        return SessionInfo(
            session=Session.CLOSED,
            phase=SessionPhase.MID,
            is_kill_zone=False,
            is_overlap=False,
            phase_score=0.0,
            session_score=0.0,
        )

    start = sess_def["start"]
    end = sess_def["end"]
    session_duration_min = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    minutes_in = (utc_time.hour * 60 + utc_time.minute) - (start.hour * 60 + start.minute)

    # Determine phase (§8.2)
    if minutes_in < 90:
        phase = SessionPhase.OPENING
        phase_score = 1.0
    elif minutes_in > session_duration_min - 60:
        phase = SessionPhase.CLOSING
        phase_score = 0.2
    else:
        phase = SessionPhase.MID
        phase_score = 0.5

    # Kill zone check
    is_kill_zone = sess_def["kill_start"] <= utc_time < sess_def["kill_end"]

    # Overlap check
    is_overlap = any(
        ov_start <= utc_time < ov_end for _, _, ov_start, ov_end in OVERLAPS
    )

    # Session score: kill zone or overlap gets full weight, otherwise minimal
    session_score = 1.0 if (is_kill_zone or is_overlap) else 0.06

    return SessionInfo(
        session=session,
        phase=phase,
        is_kill_zone=is_kill_zone,
        is_overlap=is_overlap,
        phase_score=phase_score,
        session_score=session_score,
    )


# §8.3 Weekly structural model
WEEKLY_MODIFIERS = {
    0: -0.10,  # Monday: fake move day, don't chase spike
    1: 0.05,   # Tuesday: true trend day
    2: 0.05,   # Wednesday: midweek reversal window
    3: 0.0,    # Thursday: neutral
    4: -0.10,  # Friday: unpredictable, reduce size
    5: -0.10,  # Saturday (weekend)
    6: -0.10,  # Sunday (weekend)
}


def get_weekly_modifier(dt: datetime) -> float:
    """Return confidence modifier based on day of week (§8.3).
    
    These modifiers are additive offsets to the FINAL confidence score,
    NOT multiplied by the session weight. See §7.1 weight note.
    """
    return WEEKLY_MODIFIERS.get(dt.weekday(), 0.0)


# §8.4 Asia range qualification
ASIA_RANGE_THRESHOLD = 0.02  # 2.0% — Asia setups only valid if range < 2.0%


def is_asia_range_valid(asia_range_pct: float, is_consolidating: bool) -> bool:
    """
    Check if Asia range qualifies for valid setups (§8.4).
    
    Asia range must be < 2.0% AND in consolidating state.
    Wide Asia ranges (> 2.0%) invalidate Asia-based setups.
    """
    return asia_range_pct < ASIA_RANGE_THRESHOLD and is_consolidating


# §8.5 Pre-US mandatory exit
PRE_US_EXIT_UTC = time(13, 0)  # 8:00 AM NY = 13:00 UTC


def is_pre_us_exit_required(dt: datetime, setup_session: Session) -> bool:
    """
    Check if pre-US mandatory exit applies (§8.5).
    
    Asia→UK setups must exit before 8:00 AM NY (13:00 UTC).
    """
    if setup_session not in (Session.ASIA, Session.LONDON):
        return False
    return dt.time() >= PRE_US_EXIT_UTC


# §8.4 Asia measurement window
ASIA_MEASURE_START = time(0, 0)
ASIA_MEASURE_END = time(7, 0)
# Exclude 07:00-07:30 (profit-taking distortion per spec)
ASIA_EXCLUDE_START = time(7, 0)
ASIA_EXCLUDE_END = time(7, 30)


def is_asia_measurement_window(dt: datetime) -> bool:
    """Check if time is within valid Asia measurement window (§8.4).
    
    Asia measurement: 00:00-07:00 UTC, excluding 07:00-07:30
    for profit-taking distortion.
    """
    utc_time = dt.time()
    in_asia = ASIA_MEASURE_START <= utc_time < ASIA_MEASURE_END
    in_exclude = ASIA_EXCLUDE_START <= utc_time < ASIA_EXCLUDE_END
    return in_asia and not in_exclude
