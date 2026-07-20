"""FTMO Challenge guard for backtesting.

Models the FTMO Challenge/Funded account loss rules precisely:

**1-Step Challenge:**
- Daily loss limit: 3% of initial balance
- Max loss: 10% **trailing** from highest midnight balance
  (the floor rises as the account grows and never comes back down)

**2-Step Challenge:**
- Daily loss limit: 5% of initial balance
- Max loss: 10% **static** from initial balance

Used during walk-forward backtesting and paper trading to ensure
strategies comply with FTMO constraints before going live.

Walk-through example (from research doc):
    Day 1: balance $10,000 → floor $9,000
    Day 5: balance $10,800 → floor $9,720
    Day 9: balance $11,200 → floor $10,080
    Day 15: balance drops to $10,050 → breach ($10,050 < $10,080)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Literal, Optional

logger = logging.getLogger("ayumi.backtest.ftmo_guard")

# CET = UTC+1 (simplified; DST doesn't affect weekday midnight resets)
_CET_OFFSET = timedelta(hours=1)

ChallengeType = Literal["1-step", "2-step"]

# FTMO official thresholds (verified 2026-07, ftmo.com/en/trading-objectives/)
_DAILY_LOSS_PCT = {"1-step": 0.03, "2-step": 0.05}
_MAX_LOSS_PCT = {"1-step": 0.10, "2-step": 0.10}


@dataclass
class FTMOGuardConfig:
    """Configuration for FTMO guard parameters."""

    initial_balance: float = 10_000.0
    challenge_type: ChallengeType = "1-step"
    track_id: str = ""
    # Overrides for testing / custom prop firms
    daily_loss_pct: Optional[float] = None
    max_loss_pct: Optional[float] = None


class FTMOGuard:
    """FTMO Challenge loss-rule enforcement for backtesting.

    Call :meth:`record_midnight_balance` at the start of each trading day
    (00:00 CET) to checkpoint the trailing floor.  Call
    :meth:`check_entry` before opening any position to verify both the
    daily and total loss limits are respected.

    Args:
        initial_balance: Starting account balance in account currency.
        track_id: FTMO track/account identifier (for logging only).
        challenge_type: ``'1-step'`` (trailing) or ``'2-step'`` (static).
    """

    def __init__(
        self,
        initial_balance: float = 10_000.0,
        track_id: str = "",
        challenge_type: ChallengeType = "1-step",
        config: Optional[FTMOGuardConfig] = None,
    ):
        if config:
            self._initial_balance = config.initial_balance
            self._challenge_type = config.challenge_type
            self._track_id = config.track_id
            daily_override = config.daily_loss_pct
            max_override = config.max_loss_pct
        else:
            self._initial_balance = initial_balance
            self._challenge_type = challenge_type
            self._track_id = track_id
            daily_override = None
            max_override = None

        self._daily_loss_limit_pct = daily_override or _DAILY_LOSS_PCT[self._challenge_type]
        self._max_loss_limit_pct = max_override or _MAX_LOSS_PCT[self._challenge_type]

        # Highest midnight balance seen (for trailing floor)
        self._highest_midnight_balance: float = self._initial_balance
        # Balance at start of current trading day (for daily loss tracking)
        self._daily_start_balance: float = self._initial_balance
        # Current day key (CET date string)
        self._current_day: Optional[str] = None

    @property
    def initial_balance(self) -> float:
        return self._initial_balance

    @property
    def challenge_type(self) -> ChallengeType:
        return self._challenge_type

    @property
    def highest_midnight_balance(self) -> float:
        return self._highest_midnight_balance

    # ── Floor computation ──────────────────────────────────────────────────

    def compute_floor(self) -> float:
        """Return the absolute balance floor below which the challenge is failed.

        - **1-step:** ``highest_midnight_balance × (1 - max_loss_pct)``
        - **2-step:** ``initial_balance × (1 - max_loss_pct)``
        """
        if self._challenge_type == "1-step":
            return self._highest_midnight_balance * (1.0 - self._max_loss_limit_pct)
        return self._initial_balance * (1.0 - self._max_loss_limit_pct)

    # ── Headroom ───────────────────────────────────────────────────────────

    def remaining_daily_loss(self, balance: float, open_pnl: float = 0.0) -> float:
        """Return remaining daily loss headroom in account currency.

        ``balance`` is the current account balance.  ``open_pnl`` is the
        unrealised P&L of currently open positions (negative = floating loss).
        """
        effective_balance = balance + open_pnl
        daily_limit = self._initial_balance * self._daily_loss_limit_pct
        current_daily_loss = max(0.0, self._daily_start_balance - effective_balance)
        return daily_limit - current_daily_loss

    def remaining_total_loss(self, balance: float) -> float:
        """Return remaining total loss headroom in account currency."""
        return balance - self.compute_floor()

    # ── Entry gate ─────────────────────────────────────────────────────────

    def check_entry(
        self,
        planned_risk_dollars: float,
        balance: float | None = None,
        open_pnl: float = 0.0,
    ) -> bool:
        """Return ``True`` if a new position with the given risk is allowed.

        Checks both daily and total loss limits.  ``planned_risk_dollars``
        is the expected loss in account currency if the stop-loss is hit.
        ``balance`` defaults to the last recorded midnight balance.
        """
        effective_balance = balance if balance is not None else self._daily_start_balance

        # Daily loss headroom must cover the planned risk (including open P/L)
        daily_remaining = self.remaining_daily_loss(effective_balance, open_pnl)
        if planned_risk_dollars > daily_remaining:
            logger.warning(
                "FTMO guard: planned risk $%.2f exceeds daily headroom $%.2f "
                "(balance $%.2f, open_pnl $%.2f, %s)",
                planned_risk_dollars,
                daily_remaining,
                effective_balance,
                open_pnl,
                self._track_id or "no-track",
            )
            return False

        # Total loss headroom must cover the planned risk
        total_remaining = self.remaining_total_loss(effective_balance)
        if planned_risk_dollars > total_remaining:
            logger.warning(
                "FTMO guard: planned risk $%.2f exceeds total headroom $%.2f "
                "(balance $%.2f, %s)",
                planned_risk_dollars,
                total_remaining,
                effective_balance,
                self._track_id or "no-track",
            )
            return False

        return True

    # ── Daily checkpoint ───────────────────────────────────────────────────

    def record_midnight_balance(self, balance: float) -> None:
        """Record the account balance at America/Toronto midnight.

        Call this at the start of each trading day (00:00 America/Toronto).
        For 1-step challenge, updates the trailing highest if balance exceeds
        the previous peak.  Always resets the daily loss tracking.
        """
        if balance > self._highest_midnight_balance:
            old_floor = self.compute_floor()
            self._highest_midnight_balance = balance
            new_floor = self.compute_floor()
            if new_floor > old_floor:
                logger.info(
                    "FTMO trailing floor raised: $%.2f → $%.2f "
                    "(balance $%.2f, %s)",
                    old_floor,
                    new_floor,
                    balance,
                    self._track_id or "no-track",
                )
        self._daily_start_balance = balance

    def reset_day(self, balance: float) -> None:
        """Alias for :meth:`record_midnight_balance`."""
        self.record_midnight_balance(balance)

    # ── Status ─────────────────────────────────────────────────────────────

    def is_breached(self, balance: float) -> bool:
        """Return ``True`` if the current balance is below the floor."""
        return balance < self.compute_floor()

    def status(self, balance: float) -> dict:
        """Return a status dict for logging / UI display."""
        return {
            "challenge_type": self._challenge_type,
            "initial_balance": self._initial_balance,
            "highest_midnight_balance": self._highest_midnight_balance,
            "current_floor": self.compute_floor(),
            "remaining_total": self.remaining_total_loss(balance),
            "daily_start_balance": self._daily_start_balance,
            "daily_limit_pct": self._daily_loss_limit_pct,
            "max_loss_pct": self._max_loss_limit_pct,
            "breached": self.is_breached(balance),
        }
