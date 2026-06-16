"""Heartbeat watchdog for cTrader dual-connection health.

Monitors last-successful-ping timestamps for each connection role and
triggers state transitions when silence thresholds are exceeded.

Thresholds (from research doc section 3):
    - 30s of silence → DEGRADED (connection still usable but suspect)
    - 90s of silence → FAILED   (connection considered dead)

The watchdog runs as a daemon thread and is fully synchronous — no asyncio.
It reads ``last_successful_ping_ms`` from each registered ConnectionStateManager
and pushes state transitions through the existing ConnectionManager.

Public API::

    watchdog = ConnectionWatchdog(connection_manager)
    watchdog.register(ConnectionRole.MARKET_DATA, state_mgr)
    watchdog.start()
    ...
    watchdog.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .connection_manager import ConnectionManager, ConnectionRole
from .connection_state import ConnectionState, ConnectionStateManager

logger = logging.getLogger("ayumi.connection.watchdog")

# ── Constants ──────────────────────────────────────────────────────────────

DEGRADED_THRESHOLD_S = 30.0   # silence → DEGRADED
FAILED_THRESHOLD_S = 90.0     # silence → FAILED
POLL_INTERVAL_S = 5.0         # how often the watchdog loop checks


# ── Per-role tracking ──────────────────────────────────────────────────────

@dataclass
class _RoleTracker:
    """Tracks silence for a single connection role."""

    state_mgr: ConnectionStateManager
    last_ping_ms: float = field(default_factory=time.time)  # epoch seconds
    notified_degraded: bool = False
    notified_failed: bool = False


# ── Watchdog ───────────────────────────────────────────────────────────────

class ConnectionWatchdog:
    """Daemon-thread heartbeat watchdog for cTrader connections.

    Args:
        connection_manager: The unified ConnectionManager that owns both
            connections.  State transitions are pushed through it.
        degraded_threshold: Seconds of silence before marking DEGRADED.
        failed_threshold: Seconds of silence before marking FAILED.
        poll_interval: How often the watchdog thread checks timestamps.
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
        *,
        degraded_threshold: float = DEGRADED_THRESHOLD_S,
        failed_threshold: float = FAILED_THRESHOLD_S,
        poll_interval: float = POLL_INTERVAL_S,
    ):
        self._mgr = connection_manager
        self._degraded_threshold = degraded_threshold
        self._failed_threshold = failed_threshold
        self._poll_interval = poll_interval

        self._lock = threading.Lock()
        self._trackers: dict[ConnectionRole, _RoleTracker] = {}

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── Registration ───────────────────────────────────────────────────────

    def register(
        self,
        role: ConnectionRole,
        state_mgr: ConnectionStateManager,
    ) -> None:
        """Register a connection's state manager for monitoring."""
        with self._lock:
            self._trackers[role] = _RoleTracker(state_mgr=state_mgr)
        logger.info("[Watchdog] Registered %s for monitoring", role.value)

    def unregister(self, role: ConnectionRole) -> None:
        """Stop monitoring a role."""
        with self._lock:
            self._trackers.pop(role, None)
        logger.info("[Watchdog] Unregistered %s", role.value)

    # ── Heartbeat API ──────────────────────────────────────────────────────

    def record_ping(self, role: ConnectionRole) -> None:
        """Record a successful heartbeat / ping for *role*.

        Resets the silence timer and, if the connection was DEGRADED,
        transitions it back to AUTHENTICATED.
        """
        now = time.time()
        with self._lock:
            tracker = self._trackers.get(role)
            if tracker is None:
                return
            tracker.last_ping_ms = now
            was_degraded = tracker.notified_degraded
            tracker.notified_degraded = False
            tracker.notified_failed = False

        if was_degraded:
            # Try to transition back to AUTHENTICATED
            tracker_obj = self._trackers.get(role)
            if tracker_obj:
                tracker_obj.state_mgr.transition_to(
                    ConnectionState.AUTHENTICATED,
                    reason="heartbeat_recovered",
                )
            logger.info("[Watchdog] %s heartbeat recovered — resetting timer", role.value)

    # ── Thread lifecycle ───────────────────────────────────────────────────

    def start(self) -> None:
        """Start the watchdog daemon thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            logger.debug("[Watchdog] Already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ctrader-connection-watchdog",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "[Watchdog] Started (degraded=%ss, failed=%ss, poll=%ss)",
            self._degraded_threshold, self._failed_threshold, self._poll_interval,
        )

    def stop(self) -> None:
        """Stop the watchdog thread (idempotent)."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._poll_interval * 2)
        self._thread = None
        logger.info("[Watchdog] Stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Internal loop ──────────────────────────────────────────────────────

    def _run(self) -> None:
        """Main watchdog loop."""
        while not self._stop_event.wait(self._poll_interval):
            try:
                self._check_all()
            except Exception as exc:
                logger.error("[Watchdog] Check cycle error: %s", exc)

    def _check_all(self) -> None:
        """Check silence thresholds for all registered roles."""
        now = time.time()
        with self._lock:
            trackers_snapshot = list(self._trackers.items())

        for role, tracker in trackers_snapshot:
            silence = now - tracker.last_ping_ms

            # FAILED threshold
            if silence >= self._failed_threshold and not tracker.notified_failed:
                tracker.notified_failed = True
                tracker.notified_degraded = True  # already past degraded
                logger.error(
                    "[Watchdog] %s FAILED — %.1fs of silence (threshold: %ss)",
                    role.value, silence, self._failed_threshold,
                )
                tracker.state_mgr.transition_to(
                    ConnectionState.FAILED,
                    reason=f"heartbeat_silence_{silence:.0f}s",
                )

            # DEGRADED threshold
            elif silence >= self._degraded_threshold and not tracker.notified_degraded:
                tracker.notified_degraded = True
                logger.warning(
                    "[Watchdog] %s DEGRADED — %.1fs of silence (threshold: %ss)",
                    role.value, silence, self._degraded_threshold,
                )
                tracker.state_mgr.transition_to(
                    ConnectionState.DEGRADED,
                    reason=f"heartbeat_silence_{silence:.0f}s",
                )

    # ── Diagnostics ────────────────────────────────────────────────────────

    def get_silence(self, role: ConnectionRole) -> Optional[float]:
        """Return seconds since last ping for *role*, or None if untracked."""
        with self._lock:
            tracker = self._trackers.get(role)
            if tracker is None:
                return None
            return time.time() - tracker.last_ping_ms
