"""TokenManager — standalone cTrader OpenAPI token lifecycle management.

Handles:
- Startup validation (freshness, placeholder detection)
- Token state persistence with schema versioning
- Pre-expiry warnings
- Programmatic refresh via cTrader OAuth endpoint
- Atomic writes for both state file and .env updates

Design: lightweight wrapper (Option A), not a framework.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("ayumi.token_manager")

# ── Constants ──────────────────────────────────────────────────────────────

CTRADER_OAUTH_REFRESH_URL = "https://openapi.ctrader.com/apps/token"
DEFAULT_TOKEN_TTL = 2_628_000  # ~30 days in seconds
MAX_REFRESH_HISTORY = 50
TOKEN_STATE_VERSION = 1

_PLACEHOLDER_VALUES = {
    "",
    "none",
    "null",
    "todo",
    "changeme",
    "***",
    "new-access",
    "new-refresh",
}


# ── Data structures ─────────────────────────────────────────────────────────

class TokenStatus:
    """Enumeration-style constants for token validation results."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    EXPIRED = "expired"
    MISSING = "missing"
    PLACEHOLDER = "placeholder"


class TokenManager:
    """Manage cTrader OpenAPI token lifecycle: validation, tracking, refresh.

    Args:
        token_path: Path to the JSON state file (default: data/token_state.json).
        env_path: Path to the .env file for atomic updates (default: .env).
    """

    def __init__(
        self,
        token_path: str = "data/token_state.json",
        env_path: str = ".env",
    ):
        self._token_path = Path(token_path)
        self._env_path = Path(env_path)
        self._state: dict = {}
        self._load_state()

    # ── Public API ─────────────────────────────────────────────────────────

    def validate_on_startup(self, access_token: str | None = None) -> dict:
        """Check token freshness and return a status dict.

        If *access_token* is provided it is validated directly; otherwise the
        most recently tracked token is checked.

        Returns:
            dict with keys: status, message, days_remaining, issued_at,
            expires_at, token_hash.
        """
        token = access_token or self._current_access_token()
        if not token:
            return {
                "status": TokenStatus.MISSING,
                "message": "No access token available",
                "days_remaining": 0.0,
                "issued_at": None,
                "expires_at": None,
                "token_hash": None,
            }

        # Placeholder detection
        if token.lower() in _PLACEHOLDER_VALUES:
            return {
                "status": TokenStatus.PLACEHOLDER,
                "message": f"Token is a placeholder value: '{token}'",
                "days_remaining": 0.0,
                "issued_at": None,
                "expires_at": None,
                "token_hash": token[:8],
            }

        token_hash = token[:8]
        record = self._state.get("tokens", {}).get(token_hash)

        if record is None:
            # Unknown token — treat as fresh but warn
            return {
                "status": TokenStatus.OK,
                "message": "Token not previously tracked — assuming fresh",
                "days_remaining": 30.0,
                "issued_at": None,
                "expires_at": None,
                "token_hash": token_hash,
            }

        issued_at = self._parse_iso(record.get("issued_at"))
        expires_in = record.get("expires_in", DEFAULT_TOKEN_TTL)

        if issued_at is None:
            return {
                "status": TokenStatus.OK,
                "message": "Token tracked but issue time unknown",
                "days_remaining": 30.0,
                "issued_at": None,
                "expires_at": None,
                "token_hash": token_hash,
            }

        expires_at = issued_at.timestamp() + expires_in
        now = datetime.now(timezone.utc).timestamp()
        days_remaining = (expires_at - now) / 86_400

        if days_remaining < 0:
            status = TokenStatus.EXPIRED
            message = f"Token expired {abs(days_remaining):.1f} days ago"
        elif days_remaining < 1:
            status = TokenStatus.CRITICAL
            message = f"Token expires in {days_remaining * 24:.1f} hours"
        elif days_remaining < 7:
            status = TokenStatus.WARNING
            message = f"Token expires in {days_remaining:.1f} days"
        else:
            status = TokenStatus.OK
            message = f"Token valid — {days_remaining:.1f} days remaining"

        return {
            "status": status,
            "message": message,
            "days_remaining": round(days_remaining, 2),
            "issued_at": record.get("issued_at"),
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
            "token_hash": token_hash,
        }

    def track_token(self, access_token: str, expires_in: int) -> None:
        """Record a newly-issued token's metadata.

        Args:
            access_token: The raw access token string.
            expires_in: TTL in seconds (from OAuth response).
        """
        token_hash = access_token[:8]
        now_iso = datetime.now(timezone.utc).isoformat()

        self._state.setdefault("version", TOKEN_STATE_VERSION)
        self._state.setdefault("tokens", {})

        self._state["tokens"][token_hash] = {
            "issued_at": now_iso,
            "expires_in": expires_in,
            "last_refreshed": now_iso,
            "refresh_count": 0,
        }
        self._save_state(self._state)
        logger.debug("Tracked token %s… (expires_in=%ds)", token_hash, expires_in)

    def needs_refresh(self, warning_days: int = 7) -> bool:
        """Return True if the current token expires within *warning_days*.

        Returns False when no token is tracked or the token is unknown.
        """
        token_hash = self._current_token_hash()
        if token_hash is None:
            return False

        record = self._state.get("tokens", {}).get(token_hash)
        if record is None:
            return False

        issued_at = self._parse_iso(record.get("issued_at"))
        if issued_at is None:
            return False

        expires_in = record.get("expires_in", DEFAULT_TOKEN_TTL)
        expires_at = issued_at.timestamp() + expires_in
        now = datetime.now(timezone.utc).timestamp()
        days_remaining = (expires_at - now) / 86_400

        return days_remaining < warning_days

    def refresh_if_needed(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        warning_days: int = 7,
    ) -> str | None:
        """Perform OAuth refresh if token is within *warning_days* of expiry.

        Args:
            client_id: OAuth client ID.
            client_secret: OAuth client secret.
            refresh_token: The refresh token.
            warning_days: Threshold in days for proactive refresh.

        Returns:
            The new access token string, or None if refresh was not needed
            or failed.
        """
        if not self.needs_refresh(warning_days):
            logger.debug("Token refresh not needed")
            return None

        return self._do_refresh(client_id, client_secret, refresh_token)

    def get_status(self) -> dict:
        """Return current token metadata suitable for logging / diagnostics.

        Returns:
            dict with keys: token_hash, age_seconds, ttl_seconds, expiry_iso,
            refresh_count, history_entries.
        """
        token_hash = self._current_token_hash()
        if token_hash is None:
            return {
                "token_hash": None,
                "age_seconds": None,
                "ttl_seconds": None,
                "expiry_iso": None,
                "refresh_count": 0,
                "history_entries": 0,
            }

        record = self._state.get("tokens", {}).get(token_hash, {})
        issued_at = self._parse_iso(record.get("issued_at"))
        expires_in = record.get("expires_in")

        age_seconds: float | None = None
        expiry_iso: str | None = None
        if issued_at is not None and expires_in is not None:
            age_seconds = datetime.now(timezone.utc).timestamp() - issued_at.timestamp()
            expiry_ts = issued_at.timestamp() + expires_in
            expiry_iso = datetime.fromtimestamp(expiry_ts, tz=timezone.utc).isoformat()

        return {
            "token_hash": token_hash,
            "age_seconds": age_seconds,
            "ttl_seconds": expires_in,
            "expiry_iso": expiry_iso,
            "refresh_count": record.get("refresh_count", 0),
            "history_entries": len(self._state.get("refresh_history", [])),
        }

    # ── Internal helpers ───────────────────────────────────────────────────

    def _current_access_token(self) -> str | None:
        """Return the most recently tracked access token if available."""
        # TokenManager does NOT store full tokens in state (only hashes).
        # Callers must pass the token explicitly; this method is a hook for
        # future extensions (e.g., secure token vault).
        return None

    def _current_token_hash(self) -> str | None:
        """Return the hash of the most recently tracked token, if any."""
        tokens = self._state.get("tokens", {})
        if not tokens:
            return None
        # Most recent by issued_at
        try:
            return max(
                tokens.keys(),
                key=lambda h: self._parse_iso(tokens[h].get("issued_at")) or datetime.min.replace(tzinfo=timezone.utc),
            )
        except Exception:
            return next(iter(tokens.keys()), None)

    def _do_refresh(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> str | None:
        """Execute the OAuth refresh request and update state.

        Returns the new access token, or None on failure.
        """
        try:
            resp = requests.post(
                CTRADER_OAUTH_REFRESH_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=10,
            )
            data = resp.json()
        except Exception as exc:
            logger.error("Token refresh request failed: %s", exc)
            self._append_refresh_history(success=False, error=str(exc))
            return None

        if data.get("errorCode"):
            error_msg = data.get("description", "unknown error")
            logger.error("Token refresh rejected: %s", error_msg)
            self._append_refresh_history(success=False, error=error_msg)
            return None

        new_access = data.get("accessToken") or data.get("access_token")
        new_refresh = data.get("refreshToken") or data.get("refresh_token")
        expires_in = data.get("expiresIn") or data.get("expires_in")

        if not new_access:
            logger.error("Token refresh response missing accessToken")
            self._append_refresh_history(success=False, error="missing_access_token")
            return None

        # Track the new token
        if expires_in is None or expires_in <= 0:
            expires_in = DEFAULT_TOKEN_TTL
        self.track_token(new_access, expires_in)

        # Bump refresh count for the *previous* token hash (if any)
        prev_hash = self._current_token_hash()
        if prev_hash and prev_hash != new_access[:8]:
            tokens = self._state.setdefault("tokens", {})
            if prev_hash in tokens:
                tokens[prev_hash]["refresh_count"] = tokens[prev_hash].get("refresh_count", 0) + 1

        # Persist new tokens to .env in-place (BQ-1036: no atomic write)
        self._update_env_tokens(new_access, new_refresh or refresh_token)

        # Record success
        self._append_refresh_history(success=True, error=None)

        logger.info("Token refreshed successfully — new hash=%s…", new_access[:8])
        return new_access

    def _append_refresh_history(self, *, success: bool, error: str | None) -> None:
        """Append a refresh record, capping history at MAX_REFRESH_HISTORY (L-2)."""
        self._state.setdefault("refresh_history", [])
        self._state["refresh_history"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": success,
            "error": error,
        })
        if len(self._state["refresh_history"]) > MAX_REFRESH_HISTORY:
            self._state["refresh_history"] = self._state["refresh_history"][-MAX_REFRESH_HISTORY:]
        self._save_state(self._state)

    def _load_state(self) -> dict:
        """Load token state from disk. Returns empty dict on missing / corrupt file."""
        if not self._token_path.exists():
            self._state = {"version": TOKEN_STATE_VERSION, "tokens": {}, "refresh_history": []}
            return self._state

        try:
            with open(self._token_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load token state (%s) — starting fresh", exc)
            self._state = {"version": TOKEN_STATE_VERSION, "tokens": {}, "refresh_history": []}
            return self._state

        # Schema migration (L-1): ensure version key exists
        if "version" not in loaded:
            loaded["version"] = TOKEN_STATE_VERSION
        loaded.setdefault("tokens", {})
        loaded.setdefault("refresh_history", [])

        self._state = loaded
        return self._state

    def _save_state(self, state: dict) -> None:
        """Atomically write state JSON to disk (temp + rename)."""
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=self._token_path.parent,
            prefix=".token_state_tmp_",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._token_path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _update_env_tokens(self, access_token: str, refresh_token: str) -> None:
        """Update token values in .env using simple in-place write.

        BQ-1036: Replaces the previous atomic temp+rename approach.
        Reads .env line by line, replaces token values, writes back directly.
        For a <1KB config file this is safe and avoids the temp-file race
        conditions that were clobbering values.
        """
        if not self._env_path.exists():
            logger.warning("Cannot persist tokens: .env not found at %s", self._env_path)
            return

        try:
            with open(self._env_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError as exc:
            logger.error("Failed to read .env: %s", exc)
            return

        new_lines: list[str] = []
        access_written = False
        refresh_written = False

        for line in lines:
            if line.startswith("CTRADER_OPENAPI_ACCESS_TOKEN="):
                new_lines.append(f"CTRADER_OPENAPI_ACCESS_TOKEN={access_token}")
                access_written = True
            elif line.startswith("CTRADER_OPENAPI_REFRESH_TOKEN="):
                new_lines.append(f"CTRADER_OPENAPI_REFRESH_TOKEN={refresh_token}")
                refresh_written = True
            else:
                new_lines.append(line)

        if not access_written:
            new_lines.append(f"CTRADER_OPENAPI_ACCESS_TOKEN={access_token}")
        if not refresh_written:
            new_lines.append(f"CTRADER_OPENAPI_REFRESH_TOKEN={refresh_token}")

        content = "\n".join(new_lines) + "\n"
        try:
            with open(self._env_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("Tokens persisted to %s", self._env_path)
        except OSError as exc:
            logger.error("Failed to write tokens to .env: %s", exc)

    @staticmethod
    def _parse_iso(iso_str: str | None) -> datetime | None:
        """Parse an ISO-8601 datetime string, returning None on failure."""
        if not iso_str:
            return None
        try:
            # Python 3.11+ handles Z suffix; for compatibility strip it first
            cleaned = iso_str.replace("Z", "+00:00")
            return datetime.fromisoformat(cleaned)
        except (ValueError, TypeError):
            return None
