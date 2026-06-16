"""Tests for CredentialStore — single source of truth for cTrader credentials.

All tests use tmp_path; no real credential files are touched.
"""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from adapters.ctrader.credential_store import Credentials, CredentialStore


# ── Fixtures ───────────────────────────────────────────────────────────────

VALID_CREDS = {
    "version": 1,
    "client_id": "test_client_id",
    "client_secret": "test_secret",
    "access_token": "test_access_token",
    "refresh_token": "test_refresh_token",
    "account_id": "12345678",
    "trader_login": "5795523",
    "expires_at": "2026-12-31T23:59:59+00:00",
    "last_refreshed": "2026-06-16T12:00:00+00:00",
}

VALID_ENV = """\
CTRADER_OPENAPI_CLIENT_ID="env_client_id"
CTRADER_OPENAPI_CLIENT_SECRET="env_secret"
CTRADER_OPENAPI_ACCESS_TOKEN="env_access_token"
CTRADER_OPENAPI_REFRESH_TOKEN="env_refresh_token"
CTRADER_OPENAPI_ACCOUNT_ID=46877902
CTRADER_OPENAPI_TRADER_LOGIN=5795523
"""


def _make_store(tmp_path: Path, creds_file: str = "data/.credentials") -> CredentialStore:
    """Build a CredentialStore rooted in tmp_path."""
    return CredentialStore(credentials_path=str(tmp_path / creds_file))


# ── Tests ──────────────────────────────────────────────────────────────────


def test_load_from_file(tmp_path):
    """Load valid credentials from JSON file — all fields correct."""
    cred_path = tmp_path / "data" / ".credentials"
    cred_path.parent.mkdir(parents=True)
    cred_path.write_text(json.dumps(VALID_CREDS))

    store = CredentialStore(credentials_path=str(cred_path))
    creds = store.load()

    assert creds.client_id == "test_client_id"
    assert creds.client_secret == "test_secret"
    assert creds.access_token == "test_access_token"
    assert creds.refresh_token == "test_refresh_token"
    assert creds.account_id == 12345678
    assert creds.trader_login == 5795523
    assert creds.expires_at is not None
    assert creds.expires_at.year == 2026


def test_migration_from_env(tmp_path, monkeypatch):
    """When credentials file is missing, migrate from .env."""
    # CWD to tmp_path so .env is found
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(VALID_ENV)

    cred_path = tmp_path / "data" / ".credentials"
    store = CredentialStore(credentials_path=str(cred_path))
    creds = store.load()

    assert creds.client_id == "env_client_id"
    assert creds.access_token == "env_access_token"
    assert creds.refresh_token == "env_refresh_token"
    assert creds.account_id == 46877902
    assert creds.trader_login == 5795523

    # File should now exist on disk
    assert cred_path.exists()
    written = json.loads(cred_path.read_text())
    assert written["access_token"] == "env_access_token"
    assert written["account_id"] == 46877902


def test_update_tokens_computes_expires_at(tmp_path):
    """update_tokens(expires_in=3600) → expires_at ~1h from now."""
    cred_path = tmp_path / "data" / ".credentials"
    cred_path.parent.mkdir(parents=True)
    cred_path.write_text(json.dumps(VALID_CREDS))

    store = CredentialStore(credentials_path=str(cred_path))
    store.load()  # populate cache

    before = datetime.now(timezone.utc)
    store.update_tokens("new_access", "new_refresh", expires_in=3600)
    after = datetime.now(timezone.utc)

    creds = store.get()
    assert creds.access_token == "new_access"
    assert creds.refresh_token == "new_refresh"
    assert creds.expires_at is not None
    # expires_at should be ~3600s from now
    delta = creds.expires_at - before
    assert 3590 <= delta.total_seconds() <= 3615
    # And after `after` (computed before call + after call)
    assert creds.expires_at > before
    assert creds.expires_at <= after + timedelta(seconds=3601)


def test_update_tokens_writes_atomically(tmp_path):
    """After update_tokens, file on disk has new values."""
    cred_path = tmp_path / "data" / ".credentials"
    cred_path.parent.mkdir(parents=True)
    cred_path.write_text(json.dumps(VALID_CREDS))

    store = CredentialStore(credentials_path=str(cred_path))
    store.load()
    store.update_tokens("fresh_token", "fresh_refresh", expires_in=7200)

    on_disk = json.loads(cred_path.read_text())
    assert on_disk["access_token"] == "fresh_token"
    assert on_disk["refresh_token"] == "fresh_refresh"
    assert "expires_at" in on_disk
    assert on_disk["last_refreshed"] is not None


def test_thread_safety(tmp_path):
    """10 threads calling get() simultaneously — no corruption."""
    cred_path = tmp_path / "data" / ".credentials"
    cred_path.parent.mkdir(parents=True)
    cred_path.write_text(json.dumps(VALID_CREDS))

    store = CredentialStore(credentials_path=str(cred_path))
    results: list[Credentials] = []
    errors: list[Exception] = []

    def worker():
        try:
            # Small jitter to increase contention
            time.sleep(0.001)
            results.append(store.get())
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Errors in threads: {errors}"
    assert len(results) == 10
    # All results must be identical
    first = results[0]
    for r in results[1:]:
        assert r == first, "Thread results diverged — cache corruption"


def test_missing_file_raises(tmp_path, monkeypatch):
    """No credentials file AND no .env → RuntimeError."""
    monkeypatch.chdir(tmp_path)
    # Ensure no .env exists in tmp_path
    assert not (tmp_path / ".env").exists()

    store = CredentialStore(credentials_path=str(tmp_path / "nonexistent.json"))
    with pytest.raises(RuntimeError, match="No credentials found"):
        store.load()
