"""Single source of truth for cTrader credentials.

No other module should read credential files. Token refresh writes here
via update_tokens(). All reads go through get().

Migration: on first load, if data/.credentials is missing or has no
expires_at, reads from .env and initializes.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ayumi.credentials")

# Environment variable mapping for migration path
_ENV_MAPPING = {
    "CTRADER_OPENAPI_CLIENT_ID": "client_id",
    "CTRADER_OPENAPI_CLIENT_SECRET": "client_secret",
    "CTRADER_OPENAPI_ACCESS_TOKEN": "access_token",
    "CTRADER_OPENAPI_REFRESH_TOKEN": "refresh_token",
    "CTRADER_OPENAPI_ACCOUNT_ID": "account_id",
    "CTRADER_OPENAPI_TRADER_LOGIN": "trader_login",
}


@dataclass(frozen=True)
class Credentials:
    """Frozen credential snapshot."""
    client_id: str
    client_secret: str
    access_token: str
    refresh_token: str
    account_id: int
    trader_login: int
    expires_at: Optional[datetime] = None  # ISO-8601, computed from OAuth expires_in


class CredentialStore:
    """Thread-safe credential store with atomic writes.

    Single source of truth — no other module reads credential files.
    """

    def __init__(self, credentials_path: str | Path = "data/.credentials"):
        self._path = Path(credentials_path)
        self._lock = threading.Lock()
        self._cached: Credentials | None = None

    def load(self) -> Credentials:
        """Load credentials from file, with .env fallback for initial migration."""
        with self._lock:
            if self._cached is not None:
                return self._cached

            if self._path.exists():
                data = json.loads(self._path.read_text())
                # Valid credentials file with expires_at — use directly
                if data.get("access_token") and data.get("expires_at") is not None:
                    self._cached = self._dict_to_credentials(data)
                    return self._cached

            # Migration path: read from .env
            env_data = self._read_env()
            if env_data:
                logger.info(
                    "Migrating credentials from .env to %s", self._path
                )
                creds = self._dict_to_credentials(env_data)
                self._write_atomic(env_data)
                self._cached = creds
                return creds

            raise RuntimeError(
                "No credentials found in data/.credentials or .env"
            )

    def get(self) -> Credentials:
        """Get cached credentials (thread-safe)."""
        if self._cached is None:
            return self.load()
        return self._cached

    def update_tokens(
        self, access_token: str, refresh_token: str, expires_in: int
    ) -> None:
        """Update tokens atomically. Called ONLY by token_lifecycle.

        Args:
            access_token: New access token from OAuth
            refresh_token: New refresh token (may be same as old)
            expires_in: Seconds until access_token expires
        """
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        with self._lock:
            current = self._cached or self._load_unsafe()
            new_data = {
                "version": 1,
                "client_id": current.client_id,
                "client_secret": current.client_secret,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "account_id": str(current.account_id),
                "trader_login": str(current.trader_login),
                "expires_at": expires_at.isoformat(),
                "last_refreshed": datetime.now(timezone.utc).isoformat(),
            }
            self._write_atomic(new_data)
            self._cached = self._dict_to_credentials(new_data)
            logger.info("Tokens updated, expires_at=%s", expires_at.isoformat())

    # ── Internal helpers ───────────────────────────────────────────────────

    def _load_unsafe(self) -> Credentials:
        """Load without lock (caller must hold lock)."""
        if self._path.exists():
            data = json.loads(self._path.read_text())
            return self._dict_to_credentials(data)
        env_data = self._read_env()
        if env_data:
            creds = self._dict_to_credentials(env_data)
            self._write_atomic(env_data)
            return creds
        raise RuntimeError("No credentials found")

    def _read_env(self) -> dict | None:
        """Read credentials from .env file (migration path only)."""
        env_path = Path(".env")
        if not env_path.exists():
            return None

        creds: dict[str, str | int] = {}
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Strip inline comments
            if " #" in value:
                value = value.split(" #")[0].strip()

            if key in _ENV_MAPPING:
                field = _ENV_MAPPING[key]
                if field in ("account_id", "trader_login"):
                    creds[field] = int(value) if value else 0
                else:
                    creds[field] = value

        if "access_token" not in creds:
            return None

        creds.setdefault("version", 1)
        return creds

    def _dict_to_credentials(self, data: dict) -> Credentials:
        """Convert dict to Credentials dataclass.

        Handles string-or-int for account_id / trader_login (the on-disk
        JSON stores them as strings for portability).
        """
        expires_at = None
        ea = data.get("expires_at")
        if ea:
            try:
                expires_at = datetime.fromisoformat(ea)
            except (ValueError, TypeError):
                pass

        return Credentials(
            client_id=str(data.get("client_id", "")),
            client_secret=str(data.get("client_secret", "")),
            access_token=str(data.get("access_token", "")),
            refresh_token=str(data.get("refresh_token", "")),
            account_id=int(data.get("account_id", 0)),
            trader_login=int(data.get("trader_login", 0)),
            expires_at=expires_at,
        )

    def _write_atomic(self, data: dict) -> None:
        """Write JSON atomically (.tmp + rename) with chmod 600."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._path)
