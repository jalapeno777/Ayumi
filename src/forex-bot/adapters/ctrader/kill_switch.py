"""Kill Switch Manager — centralized safety system for trading operations.

Provides global kill/freeze activation, file-based state persistence, and
audit logging. Designed as the single source of truth for kill switch state
across all trading components.

Design principles:
  - Fail-safe defaults: corrupt/missing state → KILL
  - Atomic file writes: temp + rename, never partial writes
  - Append-only audit log
  - In-memory fast path with file durability
"""

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Optional

logger = logging.getLogger("ayumi.ctrader.kill_switch")


# ── Constants ─────────────────────────────────────────────────────────────────

STATE_VERSION = 1
DEFAULT_STATE_DIR = "data/kill_switches"
GLOBAL_STATE_FILE = "global.state"
HISTORY_FILE = "history.jsonl"


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class GlobalKillState:
    """Serializable global kill switch state."""
    version: int = STATE_VERSION
    active: bool = False
    level: str = "global"
    mode: str = "kill"          # "kill" or "freeze"
    reason: str = ""
    triggered_by: str = ""
    triggered_at: Optional[str] = None
    positions_closed: bool = False
    close_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "GlobalKillState":
        return cls(
            version=data.get("version", STATE_VERSION),
            active=data.get("active", False),
            level=data.get("level", "global"),
            mode=data.get("mode", "kill"),
            reason=data.get("reason", ""),
            triggered_by=data.get("triggered_by", ""),
            triggered_at=data.get("triggered_at"),
            positions_closed=data.get("positions_closed", False),
            close_count=data.get("close_count", 0),
            metadata=data.get("metadata", {}),
        )


# ── KillSwitchManager ────────────────────────────────────────────────────────

class KillSwitchManager:
    """Centralized kill switch state manager.

    Single source of truth for all kill switch state.
    Used by ForwardTestEngine, PaperTrader, and external interfaces.

    Thread-safe. File-persisted. Fail-safe.
    """

    # Kill levels
    LEVEL_GLOBAL = "global"
    LEVEL_ACCOUNT = "account"
    LEVEL_SESSION = "session"
    LEVEL_STRATEGY = "strategy"

    # Kill modes
    MODE_KILL = "kill"
    MODE_FREEZE = "freeze"

    def __init__(self, state_dir: str = DEFAULT_STATE_DIR):
        self._state_dir = Path(state_dir)
        self._state_file = self._state_dir / GLOBAL_STATE_FILE
        self._history_file = self._state_dir / HISTORY_FILE
        self._lock = RLock()

        # Ensure state directory exists
        self._state_dir.mkdir(parents=True, exist_ok=True)

        # In-memory state (fast path)
        self._state: GlobalKillState = GlobalKillState()

        # Load persisted state
        self._load_state()

        # Cached flags for ultra-fast path (< 0.01ms)
        self._killed_cache: bool = self._state.active and self._state.mode == self.MODE_KILL
        self._frozen_cache: bool = self._state.active and self._state.mode == self.MODE_FREEZE

    # ── Public API: Query ──────────────────────────────────────────────────

    def is_globally_killed(self) -> bool:
        """Fast-path check: is the system globally killed?

        Target latency: < 0.01ms (single bool read, no I/O).
        """
        return self._killed_cache

    def is_globally_frozen(self) -> bool:
        """Fast-path check: is the system globally frozen?

        Target latency: < 0.01ms (single bool read, no I/O).
        """
        return self._frozen_cache

    def is_active(self) -> bool:
        """Is any kill switch active (kill or freeze)?"""
        return self._state.active

    def get_status(self) -> dict:
        """Full status dict for external consumption."""
        with self._lock:
            return self._state.to_dict()

    # ── Public API: Activation ─────────────────────────────────────────────

    def activate_global_kill(
        self,
        reason: str,
        triggered_by: str,
        close_positions: bool = True,
    ) -> None:
        """Activate global KILL — stops all new trades AND closes positions.

        Args:
            reason: Human-readable reason for the kill.
            triggered_by: Who/what triggered the kill (e.g. "manual", "watchdog").
            close_positions: If True, signal that positions should be closed.
                (Actual closing is done by the engine/paper_trader, not here.)
        """
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            was_active = self._state.active

            self._state = GlobalKillState(
                version=STATE_VERSION,
                active=True,
                level=self.LEVEL_GLOBAL,
                mode=self.MODE_KILL,
                reason=reason,
                triggered_by=triggered_by,
                triggered_at=now,
                positions_closed=not close_positions,  # False = still need to close
                close_count=0,
                metadata={},
            )

            self._killed_cache = True
            self._frozen_cache = False

            self._save_state()
            self._append_history({
                "ts": now,
                "event": "activated",
                "level": self.LEVEL_GLOBAL,
                "mode": self.MODE_KILL,
                "reason": reason,
                "triggered_by": triggered_by,
                "close_positions": close_positions,
                "was_reactivation": was_active,
            })

            if was_active:
                logger.warning(
                    "Global kill RE-ACTIVATED (was already active): reason=%s, by=%s",
                    reason, triggered_by,
                )
            else:
                logger.critical(
                    "GLOBAL KILL ACTIVATED: reason=%s, by=%s, close_positions=%s",
                    reason, triggered_by, close_positions,
                )

    def activate_global_freeze(self, reason: str, triggered_by: str) -> None:
        """Activate global FREEZE — stops new trades, holds existing positions.

        Args:
            reason: Human-readable reason for the freeze.
            triggered_by: Who/what triggered the freeze.
        """
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            was_active = self._state.active

            self._state = GlobalKillState(
                version=STATE_VERSION,
                active=True,
                level=self.LEVEL_GLOBAL,
                mode=self.MODE_FREEZE,
                reason=reason,
                triggered_by=triggered_by,
                triggered_at=now,
                positions_closed=True,  # Freeze doesn't close positions
                close_count=0,
                metadata={},
            )

            self._killed_cache = False
            self._frozen_cache = True

            self._save_state()
            self._append_history({
                "ts": now,
                "event": "activated",
                "level": self.LEVEL_GLOBAL,
                "mode": self.MODE_FREEZE,
                "reason": reason,
                "triggered_by": triggered_by,
                "was_reactivation": was_active,
            })

            logger.warning(
                "GLOBAL FREEZE ACTIVATED: reason=%s, by=%s",
                reason, triggered_by,
            )

    def deactivate(self, reason: str = "manual_recovery") -> None:
        """Deactivate any active kill/freeze.

        Args:
            reason: Reason for deactivation.
        """
        with self._lock:
            if not self._state.active:
                logger.info("Deactivate called but no kill switch active")
                return

            now = datetime.now(timezone.utc).isoformat()
            prev_mode = self._state.mode
            prev_reason = self._state.reason

            self._state = GlobalKillState(
                version=STATE_VERSION,
                active=False,
            )

            self._killed_cache = False
            self._frozen_cache = False

            self._save_state()
            self._append_history({
                "ts": now,
                "event": "deactivated",
                "level": self.LEVEL_GLOBAL,
                "previous_mode": prev_mode,
                "previous_reason": prev_reason,
                "reason": reason,
            })

            logger.info(
                "Kill switch DEACTIVATED: previous_mode=%s, previous_reason=%s, reason=%s",
                prev_mode, prev_reason, reason,
            )

    # ── Public API: Position Close Tracking ────────────────────────────────

    def record_positions_closed(self, count: int) -> None:
        """Record that positions were closed as part of a kill activation."""
        with self._lock:
            self._state.positions_closed = True
            self._state.close_count = count
            self._save_state()
            self._append_history({
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "positions_closed",
                "count": count,
            })

    # ── Persistence ────────────────────────────────────────────────────────

    def _save_state(self) -> None:
        """Atomic write state to file (temp + rename).

        Never raises on failure — logs CRITICAL but continues operating
        in-memory. The safety implication of a failed write is that the
        kill switch won't survive a restart, which is logged.
        """
        try:
            data = self._state.to_dict()
            json_str = json.dumps(data, indent=2)

            # Write to temp file in the SAME directory (guaranteed same filesystem)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._state_dir),
                prefix=".global.state.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(json_str)
                    f.flush()
                    os.fsync(f.fileno())
                # Atomic rename
                os.replace(tmp_path, str(self._state_file))
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
            logger.critical(
                "Failed to persist kill switch state: %s — "
                "KILL SWITCH WILL NOT SURVIVE RESTART",
                exc,
            )

    def _load_state(self) -> None:
        """Load state from file on startup.

        Fail-safe behavior:
          - File missing: start inactive (fresh start)
          - File corrupt: default to KILL (safest assumption)
          - File valid: use persisted state
        """
        if not self._state_file.exists():
            logger.info("No kill switch state file found — starting INACTIVE")
            return

        try:
            raw = self._state_file.read_text()
            data = json.loads(raw)
            self._state = GlobalKillState.from_dict(data)

            if self._state.active:
                if self._state.mode == self.MODE_KILL:
                    logger.critical(
                        "STARTUP: Kill switch is ACTIVE (KILL mode): "
                        "reason=%s, triggered_by=%s, triggered_at=%s",
                        self._state.reason,
                        self._state.triggered_by,
                        self._state.triggered_at,
                    )
                elif self._state.mode == self.MODE_FREEZE:
                    logger.critical(
                        "STARTUP: Kill switch is ACTIVE (FREEZE mode): "
                        "reason=%s, triggered_by=%s, triggered_at=%s",
                        self._state.reason,
                        self._state.triggered_by,
                        self._state.triggered_at,
                    )

            logger.info("Kill switch state loaded: active=%s, mode=%s",
                        self._state.active, self._state.mode)

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            # Corrupt file → fail-safe: default to KILL
            logger.critical(
                "Kill switch state file CORRUPT (%s) — defaulting to KILL for safety",
                exc,
            )
            self._state = GlobalKillState(
                version=STATE_VERSION,
                active=True,
                level=self.LEVEL_GLOBAL,
                mode=self.MODE_KILL,
                reason="corrupt_state_file",
                triggered_by="system_fail_safe",
                triggered_at=datetime.now(timezone.utc).isoformat(),
            )
            self._save_state()
            self._append_history({
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "fail_safe_activated",
                "level": self.LEVEL_GLOBAL,
                "mode": self.MODE_KILL,
                "reason": "corrupt_state_file",
                "triggered_by": "system_fail_safe",
                "error": str(exc),
            })

    def _append_history(self, event: dict) -> None:
        """Append event to history.jsonl (append-only audit log).

        Uses >> append mode. Never raises on failure — logs warning.
        """
        try:
            with open(self._history_file, "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as exc:
            logger.warning("Failed to append kill switch history: %s", exc)
