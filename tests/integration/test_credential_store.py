"""Tests for CredentialStore — single source of truth for cTrader credentials.

All tests use tmp_path; no real credential files are touched.
Rewritten for the .env-only CredentialStore API (Phase 0.5+ commit c584d23).
The JSON-based test fixtures from the original file referenced a removed
credentials_path feature and were no longer valid.

Note: thread-safety behavior of CredentialStore's internal lock is inherited
from threading.Lock (stdlib) and covered by other test suites — not retested
here to avoid interaction with watchdog-based tests that run later in the
session.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from adapters.ctrader.credential_store import CredentialStore

VALID_ENV = """\
CTRADER_OPENAPI_CLIENT_ID="test_client_id"
CTRADER_OPENAPI_CLIENT_SECRET="test_secret"
CTRADER_OPENAPI_ACCESS_TOKEN="test_access_token"
CTRADER_OPENAPI_REFRESH_TOKEN="test_refresh_token"
CTRADER_OPENAPI_ACCOUNT_ID=12345678
CTRADER_OPENAPI_TRADER_LOGIN=5795523
CTRADER_OPENAPI_TOKEN_EXPIRES_AT=2026-12-31T23:59:59+00:00
"""


def _make_store(tmp_path: Path, env_name: str = ".env") -> CredentialStore:
    """Build a CredentialStore rooted in tmp_path."""
    return CredentialStore(env_path=str(tmp_path / env_name))


def _write_env(env_path: Path, content: str = VALID_ENV) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(content)


def test_load_from_env(tmp_path):
    """Load valid credentials from .env — all fields correct."""
    env_path = tmp_path / ".env"
    _write_env(env_path)

    store = CredentialStore(env_path=str(env_path))
    creds = store.load()

    assert creds.client_id == "test_client_id"
    assert creds.client_secret == "test_secret"  # noqa: S105
    assert creds.access_token == "test_access_token"  # noqa: S105
    assert creds.refresh_token == "test_refresh_token"  # noqa: S105
    assert creds.account_id == 12345678
    assert creds.trader_login == 5795523
    assert creds.expires_at is not None
    assert creds.expires_at.year == 2026


def test_caches_after_load(tmp_path):
    """load() populates cache; get() returns same instance without re-reading."""
    env_path = tmp_path / ".env"
    _write_env(env_path)

    store = CredentialStore(env_path=str(env_path))
    creds1 = store.load()
    creds2 = store.get()

    # Same object identity (cached)
    assert creds1 is creds2


def test_update_tokens_computes_expires_at(tmp_path):
    """update_tokens(expires_in=3600) → expires_at ~1h from now."""
    env_path = tmp_path / ".env"
    _write_env(env_path)

    store = CredentialStore(env_path=str(env_path))
    store.load()

    before = datetime.now(timezone.utc)
    store.update_tokens("new_access", "new_refresh", expires_in=3600)
    after = datetime.now(timezone.utc)

    creds = store.get()
    assert creds.access_token == "new_access"  # noqa: S105
    assert creds.refresh_token == "new_refresh"  # noqa: S105
    assert creds.expires_at is not None
    delta = creds.expires_at - before
    assert 3590 <= delta.total_seconds() <= 3615
    assert creds.expires_at > before
    assert creds.expires_at <= after + timedelta(seconds=3601)


def test_update_tokens_writes_atomically(tmp_path):
    """After update_tokens, .env on disk has new token values."""
    env_path = tmp_path / ".env"
    _write_env(env_path)

    store = CredentialStore(env_path=str(env_path))
    store.load()
    store.update_tokens("fresh_token", "fresh_refresh", expires_in=7200)

    on_disk = env_path.read_text()
    assert "CTRADER_OPENAPI_ACCESS_TOKEN=fresh_token" in on_disk
    assert "CTRADER_OPENAPI_REFRESH_TOKEN=fresh_refresh" in on_disk
    backup = env_path.with_suffix(".env.token_backup")
    assert backup.exists()
    assert "test_access_token" in backup.read_text()


def test_update_tokens_preserves_other_keys(tmp_path):
    """update_tokens only modifies token keys; other env entries stay intact."""
    env_path = tmp_path / ".env"
    _write_env(env_path)

    store = CredentialStore(env_path=str(env_path))
    store.load()
    store.update_tokens("fresh", "fresh_refresh", expires_in=3600)

    on_disk = env_path.read_text()
    assert "CTRADER_OPENAPI_CLIENT_ID=" in on_disk
    assert "test_client_id" in on_disk
    assert "CTRADER_OPENAPI_ACCOUNT_ID=" in on_disk
    assert "12345678" in on_disk


def test_missing_env_raises(tmp_path):
    """No .env at the configured path → RuntimeError."""
    env_path = tmp_path / ".env"
    assert not env_path.exists()

    store = CredentialStore(env_path=str(env_path))
    with pytest.raises(RuntimeError, match=r"No \.env found at"):
        store.load()
