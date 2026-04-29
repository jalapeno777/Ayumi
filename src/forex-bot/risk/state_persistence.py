"""State persistence for risk system — saves/restores sizer state across restarts."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from risk.sl_position_sizer import SLPositionSizer

logger = logging.getLogger("ayumi.risk")


class StatePersistence:
    """Saves and restores risk system state across restarts."""

    def __init__(self, state_path: str = "data/risk_state.json"):
        self._path = Path(state_path)

    def get_state(self, sizer: SLPositionSizer) -> dict:
        """Extract sizer state as dict (for inspection or serialization)."""
        breaker = sizer.breaker
        return {
            "account_balance": sizer.account_balance,
            "peak_balance": sizer._peak_balance,
            "daily_risk_used": sizer._daily_risk_used,
            "open_risk": sizer._open_risk,
            "circuit_breaker": {
                "halted": breaker.halted,
                "halted_until": breaker.halted_until.isoformat() if breaker.halted_until else None,
                "halt_reason": breaker.halt_reason,
                "recent_trades": breaker.recent_trades,
                "daily_dd_pct": breaker.daily_dd_pct,
                "account_dd_pct": breaker.account_dd_pct,
            },
        }

    def save(self, sizer: SLPositionSizer) -> None:
        """Persist current sizer state atomically."""
        state = self.get_state(sizer)
        self._atomic_write(state)
        logger.info("Saved risk state to %s", self._path)

    def restore(self, sizer: SLPositionSizer) -> bool:
        """Restore sizer state from disk. Returns True if successful."""
        if not self._path.exists():
            logger.warning("No state file at %s — starting fresh", self._path)
            return False

        try:
            raw = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Corrupt state file %s: %s", self._path, e)
            return False

        try:
            sizer.account_balance = raw.get("account_balance", sizer.account_balance)
            sizer._peak_balance = raw.get("peak_balance", sizer.account_balance)
            sizer._daily_risk_used = raw.get("daily_risk_used", 0.0)
            sizer._open_risk = raw.get("open_risk", 0.0)

            cb = raw.get("circuit_breaker", {})
            breaker = sizer.breaker
            breaker.halted = cb.get("halted", False)
            breaker.halt_reason = cb.get("halt_reason", "")
            breaker.recent_trades = cb.get("recent_trades", [])
            breaker.daily_dd_pct = cb.get("daily_dd_pct", 0.0)
            breaker.account_dd_pct = cb.get("account_dd_pct", 0.0)

            halted_until = cb.get("halted_until")
            if halted_until:
                from datetime import datetime, timezone
                breaker.halted_until = datetime.fromisoformat(halted_until)
            else:
                breaker.halted_until = None

            logger.info("Restored risk state from %s", self._path)
            return True
        except Exception as e:
            logger.error("Failed to restore state: %s", e)
            return False

    def _atomic_write(self, state: dict) -> None:
        """Write state atomically via temp file + rename."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent, suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, str(self._path))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
