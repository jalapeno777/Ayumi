"""Token lifecycle management — the ONLY module that calls the cTrader OAuth endpoint.

Proactive refresh: refreshes when expires_at < now + 5 days
Reactive refresh: called by session on AUTH_EXPIRED error
Thread-safe: uses a lock to prevent concurrent refreshes
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import requests

from .credential_store import CredentialStore

logger = logging.getLogger("ayumi.token_lifecycle")

# ── Constants ──────────────────────────────────────────────────────────────

OAUTH_URL = "https://openapi.ctrader.com/apps/token"
REFRESH_BUFFER = timedelta(days=5)  # refresh when < 5 days remaining (token TTL is 30 days)
REQUEST_TIMEOUT = 10  # seconds
PROACTIVE_CHECK_INTERVAL = 300  # seconds between proactive timer checks (5min — no need to hammer with 30-day tokens)


# ── Exceptions ─────────────────────────────────────────────────────────────


class TokenRefreshError(Exception):
    """Raised when token refresh fails.

    Attributes:
        retry: True if the caller should retry (HTTP 5xx, network errors).
               False for permanent failures (HTTP 400 invalid grant).
    """

    def __init__(self, message: str, *, retry: bool = False):
        super().__init__(message)
        self._retry = retry

    @property
    def retry(self) -> bool:
        """Whether the caller should retry the refresh."""
        return self._retry


# ── TokenLifecycle ─────────────────────────────────────────────────────────


class TokenLifecycle:
    """Owns the token refresh lifecycle.

    Only module that calls the cTrader OAuth endpoint.
    On successful refresh, writes new tokens to CredentialStore.

    Thread-safe: concurrent ensure_valid() / force_refresh() calls are
    serialized via a lock. If a refresh is already in progress, subsequent
    callers wait for it to complete and return the freshly-refreshed token.
    """

    def __init__(self, credential_store: CredentialStore):
        """Initialize with a CredentialStore.

        Reads client_id and client_secret from the credential store.
        """
        self._store = credential_store
        creds = credential_store.get()
        self._client_id = creds.client_id
        self._client_secret = creds.client_secret

        self._lock = threading.Lock()
        self._refreshing = threading.Event()
        # Track the last-known access token to avoid redundant reads
        self._access_token: str = creds.access_token
        self._expires_at: Optional[datetime] = creds.expires_at

        # Proactive timer
        self._timer_thread: Optional[threading.Thread] = None
        self._timer_stop = threading.Event()

    # ── Public API ─────────────────────────────────────────────────────────

    def ensure_valid(self) -> str:
        """Return a valid access token, refreshing if needed.

        If the token expires within REFRESH_BUFFER (5 days) or is already
        expired, a refresh is triggered. Thread-safe: concurrent callers
        block until the in-progress refresh finishes.

        Returns:
            A valid access token string.

        Raises:
            TokenRefreshError: If the OAuth refresh fails.
        """
        if self._is_valid():
            return self._access_token

        # Token needs refresh — acquire lock
        with self._lock:
            # Double-check after acquiring lock (another thread may have refreshed)
            if self._is_valid():
                return self._access_token
            return self._do_refresh()

    def force_refresh(self) -> str:
        """Force a token refresh regardless of expiry.

        Used when the session receives an AUTH_EXPIRED error from cTrader.
        Thread-safe: concurrent callers block until the in-progress refresh
        finishes, then return the new token.

        Returns:
            The new access token string.

        Raises:
            TokenRefreshError: If the OAuth refresh fails.
        """
        with self._lock:
            # If another thread just completed a refresh, check if token changed
            return self._do_refresh()

    @property
    def expires_at(self) -> Optional[datetime]:
        """Return the current token's expiry time, or None if unknown."""
        return self._expires_at

    def start_proactive_timer(
        self, on_refreshed: Optional[Callable[[str], None]] = None
    ) -> None:
        """Start a daemon thread that proactively refreshes before expiry.

        The thread checks expires_at every PROACTIVE_CHECK_INTERVAL (60s).
        If the token expires within REFRESH_BUFFER (5 days), it calls
        force_refresh(). On error, logs and continues (does not crash).

        Args:
            on_refreshed: Optional callback invoked with the new access
                          token after each successful proactive refresh.
        """
        if self._timer_thread is not None and self._timer_thread.is_alive():
            logger.warning("Proactive timer already running")
            return

        self._timer_stop.clear()
        self._timer_thread = threading.Thread(
            target=self._timer_loop,
            args=(on_refreshed,),
            name="token-proactive-timer",
            daemon=True,
        )
        self._timer_thread.start()
        logger.info("Proactive token timer started")

    def stop_proactive_timer(self) -> None:
        """Stop the proactive timer daemon thread."""
        if self._timer_thread is None:
            return
        self._timer_stop.set()
        self._timer_thread.join(timeout=PROACTIVE_CHECK_INTERVAL + 5)
        self._timer_thread = None
        logger.info("Proactive token timer stopped")

    # ── Internal ───────────────────────────────────────────────────────────

    def _is_valid(self) -> bool:
        """Check if the current token is still valid (with 5-day buffer)."""
        if self._expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        return self._expires_at - now > REFRESH_BUFFER

    def _sync_from_store(self) -> None:
        """Pull latest token data from credential_store (after external update)."""
        creds = self._store.get()
        self._access_token = creds.access_token
        self._expires_at = creds.expires_at

    def _do_refresh(self) -> str:
        """Execute the OAuth refresh request.

        Caller must hold self._lock.

        Returns:
            The new access token.

        Raises:
            TokenRefreshError: On any refresh failure.
        """
        # Get current refresh token from the store
        creds = self._store.get()
        refresh_token = creds.refresh_token

        if not refresh_token:
            raise TokenRefreshError(
                "No refresh_token available — manual intervention required"
            )

        logger.info("Refreshing cTrader access token")

        try:
            resp = requests.post(
                OAUTH_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.error("Token refresh network error: %s", exc)
            raise TokenRefreshError(
                f"Network error during token refresh: {exc}",
                retry=True,
            ) from exc

        # HTTP 400 = invalid grant (permanent failure)
        if resp.status_code == 400:
            body = resp.text[:500]
            logger.error(
                "Token refresh failed — HTTP 400: %s", body
            )
            raise TokenRefreshError(
                "Refresh token invalid — manual intervention required",
                retry=False,
            )

        # HTTP 5xx = server error (retryable)
        if resp.status_code >= 500:
            body = resp.text[:500]
            logger.error(
                "Token refresh failed — HTTP %d: %s",
                resp.status_code,
                body,
            )
            raise TokenRefreshError(
                f"OAuth server error (HTTP {resp.status_code})",
                retry=True,
            )

        # Any other non-200
        if resp.status_code != 200:
            body = resp.text[:500]
            logger.error(
                "Token refresh failed — HTTP %d: %s",
                resp.status_code,
                body,
            )
            raise TokenRefreshError(
                f"OAuth unexpected status {resp.status_code}",
                retry=False,
            )

        data = resp.json()

        # cTrader uses camelCase, but handle both
        new_access = data.get("accessToken") or data.get("access_token", "")
        new_refresh = data.get("refreshToken") or data.get("refresh_token", "")
        expires_in = data.get("expiresIn") or data.get("expires_in", 3600)

        if not new_access:
            raise TokenRefreshError(
                "OAuth response missing access token",
                retry=False,
            )

        # If no new refresh token returned, keep the old one
        if not new_refresh:
            new_refresh = refresh_token

        # Persist to credential store (computes expires_at internally)
        self._store.update_tokens(new_access, new_refresh, expires_in)

        # Update local cache
        creds = self._store.get()
        self._access_token = creds.access_token
        self._expires_at = creds.expires_at

        logger.info("Token refreshed — new expires_at=%s", self._expires_at)

        return self._access_token

    def _timer_loop(
        self, on_refreshed: Optional[Callable[[str], None]]
    ) -> None:
        """Proactive timer loop — runs in a daemon thread.

        Checks every PROACTIVE_CHECK_INTERVAL (5min). If the token expires within 5 days, calls
        force_refresh(). On error, logs and continues.
        """
        while not self._timer_stop.is_set():
            try:
                if not self._is_valid():
                    logger.debug(
                        "Proactive timer: token expiring soon, refreshing"
                    )
                    # force_refresh acquires the lock internally
                    new_token = self.force_refresh()
                    if on_refreshed is not None:
                        on_refreshed(new_token)
            except TokenRefreshError as exc:
                logger.error("Proactive refresh failed: %s", exc)
            except Exception as exc:
                logger.error(
                    "Proactive timer unexpected error: %s", exc,
                    exc_info=True,
                )

            # Wait for the check interval (interruptible)
            self._timer_stop.wait(timeout=PROACTIVE_CHECK_INTERVAL)
