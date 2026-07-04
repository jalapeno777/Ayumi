"""FTMO Guard — enforces FTMO challenge rules for funded account trading.

Implements three core FTMO protections:

1. **Daily loss limit** — freeze trading when daily loss reaches 4% of
   starting balance.  Resets at CET midnight.
2. **Max concurrent positions** — reject new positions beyond 3.
3. **Drawdown breaker** — reduce new position size by 50% at 8% drawdown,
   freeze all trading at 9% drawdown.

When a threshold is breached, :class:`FTMOGuard` calls the existing
:class:`~adapters.ctrader.kill_switch.KillSwitchManager` to activate
a global freeze or kill.

All methods are synchronous and thread-safe via an internal ``RLock``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Protocol

logger = logging.getLogger("ayumi.risk.ftmo_guard")

# ── CET timezone helpers ──────────────────────────────────────────────────────

# CET = UTC+1, CEST = UTC+2.
# We use a fixed UTC+1 offset for "CET midnight" reset purposes.
# DST transitions happen on Sunday 01:00 UTC (last Sunday March/October),
# which means the reset window is never ambiguous for weekday trading.
CET_UTC_OFFSET = timedelta(hours=1)


def _cet_date(now: Optional[datetime] = None) -> str:
    """Return the current CET date as ``YYYY-MM-DD`` string."""
    if now is None:
        now = datetime.now(timezone.utc)
    cet_now = now + CET_UTC_OFFSET
    return cet_now.strftime("%Y-%m-%d")


def _cet_midnight_utc(now: Optional[datetime] = None) -> datetime:
    """Return the next CET midnight as a UTC datetime."""
    if now is None:
        now = datetime.now(timezone.utc)
    cet_now = now + CET_UTC_OFFSET
    # Midnight tonight in CET = 00:00 CET tomorrow
    cet_midnight = (cet_now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # Convert back to UTC
    return cet_midnight - CET_UTC_OFFSET


# ── Enums ────────────────────────────────────────────────────────────────────

class FTMOBreachType(str, Enum):
    """Type of FTMO rule breach."""
    DAILY_LOSS = "daily_loss"
    POSITION_LIMIT = "position_limit"
    DD_REDUCE = "dd_reduce"
    DD_FREEZE = "dd_freeze"


class FTMOAction(str, Enum):
    """Action level dictated by FTMO guard."""
    ALLOW = "allow"          # Normal trading
    REDUCE_50 = "reduce_50"  # Reduce new position size by 50%
    FREEZE = "freeze"        # No new positions, hold existing
    KILL = "kill"            # Close all positions


# ── Protocol for kill_switch integration ─────────────────────────────────────

class KillSwitchLike(Protocol):
    """Protocol for kill switch objects (duck-typed)."""

    def activate_global_freeze(self, reason: str, triggered_by: str) -> None: ...
    def activate_global_kill(
        self, reason: str, triggered_by: str, close_positions: bool = True
    ) -> None: ...
    def is_active(self) -> bool: ...


# ── State ────────────────────────────────────────────────────────────────────

@dataclass
class FTMOState:
    """Serializable FTMO guard state."""
    starting_balance: float = 0.0
    peak_balance: float = 0.0
    current_balance: float = 0.0
    daily_loss_pct: float = 0.0
    daily_loss_date: Optional[str] = None    # CET date for the current daily loss tracking
    open_position_count: int = 0
    current_dd_pct: float = 0.0
    action_level: str = FTMOAction.ALLOW.value
    breach_history: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "starting_balance": self.starting_balance,
            "peak_balance": self.peak_balance,
            "current_balance": self.current_balance,
            "daily_loss_pct": self.daily_loss_pct,
            "daily_loss_date": self.daily_loss_date,
            "open_position_count": self.open_position_count,
            "current_dd_pct": self.current_dd_pct,
            "action_level": self.action_level,
            "breach_history": list(self.breach_history),
        }


# ── FTMOGuard ────────────────────────────────────────────────────────────────

class FTMOGuard:
    """FTMO rule enforcement guard.

    Monitors account metrics and enforces FTMO challenge rules:
    daily loss limit, concurrent position cap, and drawdown breaker.

    Call :meth:`update` after every fill or periodic check to keep
    state current.  Call :meth:`should_allow_new_position` before
    opening any new position.

    Args:
        kill_switch: KillSwitchManager (or compatible) for global activation.
        starting_balance: Account starting balance (for daily loss % calc).
        max_daily_loss_pct: Daily loss threshold (default 4.0%).
        max_concurrent_positions: Max simultaneous positions (default 3).
        dd_reduce_pct: Drawdown % that triggers size reduction (default 8.0).
        dd_freeze_pct: Drawdown % that triggers freeze (default 9.0).
    """

    # Default FTMO parameters
    DEFAULT_MAX_DAILY_LOSS_PCT = 4.0
    DEFAULT_MAX_POSITIONS = 3
    DEFAULT_DD_REDUCE_PCT = 8.0
    DEFAULT_DD_FREEZE_PCT = 9.0

    def __init__(
        self,
        kill_switch: Optional[KillSwitchLike] = None,
        starting_balance: float = 10000.0,
        max_daily_loss_pct: float = DEFAULT_MAX_DAILY_LOSS_PCT,
        max_concurrent_positions: int = DEFAULT_MAX_POSITIONS,
        dd_reduce_pct: float = DEFAULT_DD_REDUCE_PCT,
        dd_freeze_pct: float = DEFAULT_DD_FREEZE_PCT,
    ):
        if dd_reduce_pct >= dd_freeze_pct:
            raise ValueError(
                f"dd_reduce_pct ({dd_reduce_pct}) must be < dd_freeze_pct ({dd_freeze_pct})"
            )
        if max_daily_loss_pct <= 0:
            raise ValueError("max_daily_loss_pct must be positive")

        self._lock = threading.RLock()
        self._kill_switch = kill_switch
        self._max_daily_loss_pct = max_daily_loss_pct
        self._max_positions = max_concurrent_positions
        self._dd_reduce_pct = dd_reduce_pct
        self._dd_freeze_pct = dd_freeze_pct

        self._state = FTMOState(
            starting_balance=starting_balance,
            peak_balance=starting_balance,
            current_balance=starting_balance,
            daily_loss_date=_cet_date(),
        )

    # ── Public API: State queries ──────────────────────────────────────────

    @property
    def state(self) -> FTMOState:
        """Current FTMO state (thread-safe copy)."""
        with self._lock:
            return FTMOState(**self._state.to_dict())

    @property
    def action_level(self) -> FTMOAction:
        """Current action level (ALLOW / REDUCE_50 / FREEZE / KILL)."""
        with self._lock:
            return FTMOAction(self._state.action_level)

    @property
    def daily_loss_pct(self) -> float:
        """Current daily loss as percentage of starting balance."""
        with self._lock:
            return self._state.daily_loss_pct

    @property
    def current_dd_pct(self) -> float:
        """Current drawdown percentage from peak."""
        with self._lock:
            return self._state.current_dd_pct

    @property
    def open_position_count(self) -> int:
        """Number of currently open positions."""
        with self._lock:
            return self._state.open_position_count

    def get_status(self) -> dict:
        """Full status dict for external consumption / logging."""
        with self._lock:
            return self._state.to_dict()

    # ── Public API: Updates ────────────────────────────────────────────────

    def update(
        self,
        current_balance: float,
        open_positions: int,
        now: Optional[datetime] = None,
    ) -> FTMOAction:
        """Update account metrics and check all FTMO rules.

        This is the primary entry point — call after every fill or
        during periodic risk checks.

        Args:
            current_balance: Current account equity/balance.
            open_positions: Current number of open positions.
            now: Override for current time (testing). Defaults to UTC now.

        Returns:
            Current :class:`FTMOAction` level after all checks.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        with self._lock:
            # ── CET midnight daily reset ───────────────────────────────────
            cet_today = _cet_date(now)
            if self._state.daily_loss_date != cet_today:
                logger.info(
                    "FTMO daily reset: %s → %s",
                    self._state.daily_loss_date,
                    cet_today,
                )
                self._state.daily_loss_pct = 0.0
                self._state.daily_loss_date = cet_today
                # If we were frozen due to daily loss, allow trading again
                if self._state.action_level == FTMOAction.FREEZE.value:
                    self._set_action(FTMOAction.ALLOW, "Daily reset at CET midnight")

            # ── Update balance metrics ─────────────────────────────────────
            self._state.current_balance = current_balance
            self._state.open_position_count = open_positions

            if current_balance > self._state.peak_balance:
                self._state.peak_balance = current_balance

            # ── Calculate daily loss ───────────────────────────────────────
            daily_loss = self._state.starting_balance - current_balance
            if self._state.starting_balance > 0:
                self._state.daily_loss_pct = max(
                    0.0, (daily_loss / self._state.starting_balance) * 100.0
                )

            # ── Calculate drawdown from peak ───────────────────────────────
            if self._state.peak_balance > 0:
                dd = (self._state.peak_balance - current_balance) / self._state.peak_balance * 100.0
                self._state.current_dd_pct = max(0.0, dd)
            else:
                self._state.current_dd_pct = 0.0

            # ── Check rules (order: most severe first) ─────────────────────

            # Daily loss check
            if self._state.daily_loss_pct >= self._max_daily_loss_pct:
                self._breach(
                    FTMOBreachType.DAILY_LOSS,
                    f"Daily loss {self._state.daily_loss_pct:.2f}% ≥ limit {self._max_daily_loss_pct}%",
                    FTMOAction.FREEZE,
                )
                return self.action_level

            # Drawdown freeze check
            if self._state.current_dd_pct >= self._dd_freeze_pct:
                self._breach(
                    FTMOBreachType.DD_FREEZE,
                    f"Drawdown {self._state.current_dd_pct:.2f}% ≥ freeze threshold {self._dd_freeze_pct}%",
                    FTMOAction.FREEZE,
                )
                return self.action_level

            # Drawdown reduce check
            if self._state.current_dd_pct >= self._dd_reduce_pct:
                self._breach(
                    FTMOBreachType.DD_REDUCE,
                    f"Drawdown {self._state.current_dd_pct:.2f}% ≥ reduce threshold {self._dd_reduce_pct}%",
                    FTMOAction.REDUCE_50,
                )
                return self.action_level

            # Position limit check
            if open_positions > self._max_positions:
                self._breach(
                    FTMOBreachType.POSITION_LIMIT,
                    f"Positions {open_positions} > max {self._max_positions}",
                    FTMOAction.FREEZE,
                )
                return self.action_level

            # All clear — recover from reduce/freeze if rules no longer breached
            if self._state.action_level != FTMOAction.ALLOW.value:
                # Daily loss and DD can recover without CET reset
                self._set_action(FTMOAction.ALLOW, "Metrics within FTMO limits")
            return self.action_level

    # ── Public API: Position gating ───────────────────────────────────────

    def should_allow_new_position(self) -> tuple[bool, str]:
        """Gate check for opening a new position.

        Returns:
            Tuple of (allowed: bool, reason: str).
            If allowed with REDUCE_50, caller should halve position size.
        """
        with self._lock:
            level = FTMOAction(self._state.action_level)

            if level == FTMOAction.FREEZE:
                return False, f"FTMO freeze active: daily_loss={self._state.daily_loss_pct:.2f}%, dd={self._state.current_dd_pct:.2f}%"

            if level == FTMOAction.KILL:
                return False, "FTMO kill active — all positions should be closed"

            if self._state.open_position_count >= self._max_positions:
                return False, f"Position limit reached: {self._state.open_position_count}/{self._max_positions}"

            if level == FTMOAction.REDUCE_50:
                return True, "FTMO reduce mode — halve position size"

            return True, "OK"

    def get_size_multiplier(self) -> float:
        """Return the position size multiplier based on current FTMO state.

        Returns:
            1.0 (normal), 0.5 (reduce mode), or 0.0 (frozen).
        """
        with self._lock:
            level = FTMOAction(self._state.action_level)
            if level in (FTMOAction.FREEZE, FTMOAction.KILL):
                return 0.0
            if level == FTMOAction.REDUCE_50:
                return 0.5
            return 1.0

    # ── Internal ───────────────────────────────────────────────────────────

    def _breach(
        self,
        breach_type: FTMOBreachType,
        detail: str,
        action: FTMOAction,
    ) -> None:
        """Record a breach and activate kill switch if needed."""
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": breach_type.value,
            "detail": detail,
            "action": action.value,
            "daily_loss_pct": self._state.daily_loss_pct,
            "dd_pct": self._state.current_dd_pct,
            "open_positions": self._state.open_position_count,
        }
        self._state.breach_history.append(event)
        self._set_action(action, detail)

        logger.warning("FTMO BREACH [%s]: %s → action=%s", breach_type.value, detail, action.value)

        # Activate kill switch for freeze/kill actions
        if self._kill_switch is not None:
            if action == FTMOAction.FREEZE:
                self._kill_switch.activate_global_freeze(
                    reason=f"FTMO: {detail}",
                    triggered_by="ftmo_guard",
                )
            elif action == FTMOAction.KILL:
                self._kill_switch.activate_global_kill(
                    reason=f"FTMO: {detail}",
                    triggered_by="ftmo_guard",
                    close_positions=True,
                )

    def _set_action(self, action: FTMOAction, reason: str) -> None:
        """Set the current action level (does not escalate downward)."""
        old = FTMOAction(self._state.action_level)
        # Only escalate or recover, never silently downgrade freeze→reduce
        if action == FTMOAction.ALLOW:
            # Recovery — allowed from reduce/freeze if metrics improved
            logger.info("FTMO action recovered: %s → ALLOW (%s)", old.value, reason)
        elif old == FTMOAction.FREEZE and action == FTMOAction.REDUCE_50:
            # Don't downgrade freeze to reduce — freeze is more severe
            return
        elif old == FTMOAction.KILL and action != FTMOAction.KILL:
            # Don't downgrade kill to anything
            return

        self._state.action_level = action.value
