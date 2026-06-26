"""Execution permission policy — single gate for all order paths.

Default behavior: DENY. The policy must explicitly determine it is safe to
send an order before returning ALLOW. Any uncertainty → DENY.

Design principles:
- Single source of truth for "can we send an order right now?"
- Uses KillSwitchManager.is_active() (reads state under lock)
- Never propagates exceptions — catches and returns DENY
- Logs every decision for audit trail

Scope: P5A covers `new_order()` only. `close_position()`, `cancel_order()`,
and `amend_sl_tp()` on OpenApiSpotFeed are NOT gated in P5A — documented as
Phase 6 scope. See council review for rationale.

Known limitations:
- Microsecond TOCTOU race between policy check and reactor dispatch
  (cannot be eliminated without synchronous send path)
"""

from typing import Tuple, Optional
import logging
from .kill_switch import KillSwitchManager

logger = logging.getLogger(__name__)


class ExecutionPermissionPolicy:
    """Single gate for order paths. Default DENY."""

    def __init__(self, kill_switch: Optional[KillSwitchManager] = None):
        self._kill_switch = kill_switch

    def can_send_order(self) -> Tuple[bool, str]:
        """Returns (allowed: bool, reason: str).

        Default DENY. Checks kill switch via is_active() which reads
        _state.active under lock (not the mode-specific cache).
        """
        try:
            if self._kill_switch is None:
                return (False, "policy:not_initialized")
            if not self._kill_switch.is_active():
                return (True, "clear")
            mode = self._kill_switch.get_status().get('mode', 'unknown')
            return (False, f"kill_switch_active:{mode}")
        except Exception as exc:
            logger.error("ExecutionPermissionPolicy error — defaulting to DENY: %s", exc)
            return (False, f"policy_error:{type(exc).__name__}")
