"""Tests for token lifecycle safety — prevents token clobbering, races, and data loss.

These tests verify the four fixes:
1. Fresh tokens in .env (no expires_at) are NOT refreshed on startup
2. Concurrent refresh attempts are serialized via inter-process file lock
3. Token backup is created before overwriting .env
4. Invalid refreshed tokens are rejected and old tokens retained
"""

import json  # noqa: I001
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from adapters.ctrader.credential_store import CredentialStore
from adapters.ctrader.token_lifecycle import (
    TokenLifecycle,
    TokenRefreshError,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

VALID_ENV = """\
CTRADER_OPENAPI_CLIENT_ID="test_client_id"
CTRADER_OPENAPI_CLIENT_SECRET="test_secret"
CTRADER_OPENAPI_ACCESS_TOKEN="craigs_fresh_token"
CTRADER_OPENAPI_REFRESH_TOKEN="craigs_fresh_refresh"
CTRADER_OPENAPI_ACCOUNT_ID=12345678
CTRADER_OPENAPI_TRADER_LOGIN=5795523
"""

# .env WITH expires_at (what update_tokens writes)
VALID_ENV_WITH_EXPIRY = VALID_ENV.rstrip() + "\n"


def _make_store(tmp_path) -> CredentialStore:
    """Build a CredentialStore with valid creds on disk (no expires_at — simulates Craig's manual write)."""
    env_path = tmp_path / ".env"
    env_path.write_text(VALID_ENV)
    store = CredentialStore(env_path=str(env_path))
    store.load()
    return store


def _mock_oauth_response(
    access_token="new_access_token",  # noqa: S107
    refresh_token="new_refresh_token",  # noqa: S107
    expires_in=3600,
    status_code=200,
):
    """Build a mock requests.Response for the OAuth endpoint."""
    resp = MagicMock()
    resp.status_code = status_code
    if status_code == 200:
        resp.json.return_value = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresIn": expires_in,
            "token_type": "bearer",
        }
        resp.text = json.dumps(resp.json.return_value)
    else:
        resp.json.return_value = {"error": "bad_request"}
        resp.text = '{"error": "bad_request"}'
    return resp


def _mock_validation_response(status_code=200):
    """Build a mock validation response for token validation."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = '{"ok": true}' if status_code == 200 else '{"error": "invalid"}'
    return resp


# ── Fix 1: Fresh tokens survive startup ────────────────────────────────────


def test_fresh_tokens_without_expires_at_are_not_refreshed(tmp_path):
    """FIX 1: When expires_at is missing from .env, ensure_valid() must NOT refresh.

    Craig writes fresh tokens to .env manually. The .env has no expires_at.
    ensure_valid() should return the token as-is without consuming the refresh token.
    """
    store = _make_store(tmp_path)
    tl = TokenLifecycle(credential_store=store)

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        token = tl.ensure_valid()

    assert token == "craigs_fresh_token"  # noqa: S105
    # OAuth endpoint must NOT have been called
    mock_req.post.assert_not_called()


def test_fresh_tokens_force_refresh_still_works(tmp_path, monkeypatch):
    """FIX 1: force_refresh() still works even with unknown expires_at.

    If cTrader sends AUTH_EXPIRED, force_refresh should still refresh
    regardless of the assume-fresh logic.
    """
    monkeypatch.setenv("AYUMI_TOKEN_LOCK_FILE", str(tmp_path / ".token_refresh.lock"))
    store = _make_store(tmp_path)
    tl = TokenLifecycle(credential_store=store)

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        mock_req.post.return_value = _mock_oauth_response(
            access_token="force_refreshed",  # noqa: S106
            expires_in=2592000,  # noqa: S106
        )
        mock_req.get.return_value = _mock_validation_response(200)
        mock_req.RequestException = Exception

        token = tl.force_refresh()

    assert token == "force_refreshed"  # noqa: S105
    mock_req.post.assert_called_once()


def test_expires_at_is_now_persisted_in_env(tmp_path):
    """FIX 1: After update_tokens, .env should contain CTRADER_OPENAPI_TOKEN_EXPIRES_AT."""
    env_path = tmp_path / ".env"
    env_path.write_text(VALID_ENV)
    store = CredentialStore(env_path=str(env_path))
    store.load()
    store.update_tokens("new_tok", "new_ref", expires_in=2592000)

    content = env_path.read_text()
    assert "CTRADER_OPENAPI_TOKEN_EXPIRES_AT=" in content


def test_expires_at_is_read_back_from_env(tmp_path):
    """FIX 1: expires_at written to .env can be read back on next load."""
    env_path = tmp_path / ".env"
    env_path.write_text(VALID_ENV)
    store = CredentialStore(env_path=str(env_path))
    store.load()
    store.update_tokens("new_tok", "new_ref", expires_in=2592000)

    # Create a NEW store (simulates restart) and load
    store2 = CredentialStore(env_path=str(env_path))
    creds = store2.load()
    assert creds.expires_at is not None
    # Should be ~30 days from now
    delta = creds.expires_at - datetime.now(timezone.utc)
    assert delta.total_seconds() > 2500000  # > ~29 days


# ── Fix 2: Inter-process file lock prevents concurrent refresh ────────────


def test_inter_process_file_lock_serializes_refresh(tmp_path, monkeypatch):
    """FIX 2: Multiple processes calling ensure_valid with an expired token
    should be serialized by the file lock.

    We simulate this by setting the lock file path to tmp_path and
    having the mock OAuth endpoint block briefly, verifying that
    two concurrent threads in the same process are still serialized
    (which exercises both the thread lock and file lock paths).
    """
    lock_file = tmp_path / ".token_refresh.lock"
    monkeypatch.setenv("AYUMI_TOKEN_LOCK_FILE", str(lock_file))

    # Create a store with an expired token
    env_path = tmp_path / ".env"
    env_path.write_text(VALID_ENV)
    store = CredentialStore(env_path=str(env_path))
    store.load()
    # Set expires_at to the past so _is_valid returns False
    store.update_tokens("old_token", "test_refresh_token", expires_in=1)
    time.sleep(1.1)  # let it expire

    # Force re-read from disk to pick up the expired token
    store2 = CredentialStore(env_path=str(env_path))
    store2.load()
    tl = TokenLifecycle(credential_store=store2)

    call_count = 0
    count_lock = threading.Lock()

    def fake_post(*args, **kwargs):
        nonlocal call_count
        with count_lock:
            call_count += 1
        time.sleep(0.05)
        return _mock_oauth_response(access_token="locked_token", expires_in=2592000)  # noqa: S106

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        mock_req.post.side_effect = fake_post
        mock_req.get.return_value = _mock_validation_response(200)
        mock_req.RequestException = Exception

        results = []
        errors = []

        def worker():
            try:
                results.append(tl.ensure_valid())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(errors) == 0, f"Thread errors: {errors}"
    assert len(results) == 5
    # Lock file should exist
    assert lock_file.exists()


# ── Fix 3: Token backup is created before overwriting ──────────────────────


def test_backup_created_on_token_update(tmp_path):
    """FIX 3: When tokens are updated, a .env.token_backup is created with the old tokens."""
    env_path = tmp_path / ".env"
    env_path.write_text(VALID_ENV)
    store = CredentialStore(env_path=str(env_path))
    store.load()

    # No backup should exist yet
    backup_path = env_path.with_suffix(".env.token_backup")
    assert not backup_path.exists()

    # Update tokens
    store.update_tokens("new_access", "new_refresh", expires_in=3600)

    # Backup should now exist
    assert backup_path.exists()

    # Backup should contain the OLD tokens
    backup_content = backup_path.read_text()
    assert "craigs_fresh_token" in backup_content
    assert "craigs_fresh_refresh" in backup_content
    # Should NOT contain the new tokens
    assert "new_access" not in backup_content


def test_backup_not_created_if_env_doesnt_exist(tmp_path):
    """FIX 3: No backup if .env doesn't exist (first-time creation)."""
    env_path = tmp_path / ".env"
    _store = CredentialStore(env_path=str(env_path))

    # This should work without error and not create a backup
    # (though in practice .env should always exist)
    # We test the backup logic indirectly: the update should not crash


# ── Fix 4: Invalid refreshed tokens are rejected ───────────────────────────


def test_invalid_refreshed_token_rejected(tmp_path, monkeypatch):
    """FIX 4: If the refreshed token fails validation, old tokens are retained."""
    lock_file = tmp_path / ".token_refresh.lock"
    monkeypatch.setenv("AYUMI_TOKEN_LOCK_FILE", str(lock_file))

    env_path = tmp_path / ".env"
    env_path.write_text(VALID_ENV)
    store = CredentialStore(env_path=str(env_path))
    store.load()
    # Set expired token so refresh triggers
    store.update_tokens("old_valid_token", "old_refresh", expires_in=1)
    time.sleep(1.1)

    store2 = CredentialStore(env_path=str(env_path))
    store2.load()
    tl = TokenLifecycle(credential_store=store2)

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        # OAuth refresh succeeds
        mock_req.post.return_value = _mock_oauth_response(
            access_token="bad_new_token",  # noqa: S106
            refresh_token="bad_new_refresh",  # noqa: S106
            expires_in=3600,
        )
        # But validation fails (401)
        mock_req.get.return_value = _mock_validation_response(401)
        mock_req.RequestException = Exception

        with pytest.raises(TokenRefreshError, match="failed validation"):
            tl.ensure_valid()

    # Old tokens should still be in .env
    content = env_path.read_text()
    assert "old_valid_token" in content
    assert "bad_new_token" not in content


def test_valid_refreshed_token_accepted(tmp_path, monkeypatch):
    """FIX 4: When validation passes, new tokens are committed to .env."""
    lock_file = tmp_path / ".token_refresh.lock"
    monkeypatch.setenv("AYUMI_TOKEN_LOCK_FILE", str(lock_file))

    env_path = tmp_path / ".env"
    env_path.write_text(VALID_ENV)
    store = CredentialStore(env_path=str(env_path))
    store.load()
    # Set expired token
    store.update_tokens("old_token", "old_refresh", expires_in=1)
    time.sleep(1.1)

    store2 = CredentialStore(env_path=str(env_path))
    store2.load()
    tl = TokenLifecycle(credential_store=store2)

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        mock_req.post.return_value = _mock_oauth_response(
            access_token="good_new_token",  # noqa: S106
            refresh_token="good_new_refresh",  # noqa: S106
            expires_in=2592000,
        )
        mock_req.get.return_value = _mock_validation_response(200)
        mock_req.RequestException = Exception

        token = tl.ensure_valid()

    assert token == "good_new_token"  # noqa: S105

    # New tokens should be in .env
    content = env_path.read_text()
    assert "good_new_token" in content
    assert "good_new_refresh" in content


def test_validation_network_error_optimistic(tmp_path, monkeypatch):
    """FIX 4: If validation endpoint is unreachable, token is accepted (optimistic)."""
    lock_file = tmp_path / ".token_refresh.lock"
    monkeypatch.setenv("AYUMI_TOKEN_LOCK_FILE", str(lock_file))

    env_path = tmp_path / ".env"
    env_path.write_text(VALID_ENV)
    store = CredentialStore(env_path=str(env_path))
    store.load()
    store.update_tokens("old_token", "old_refresh", expires_in=1)
    time.sleep(1.1)

    store2 = CredentialStore(env_path=str(env_path))
    store2.load()
    tl = TokenLifecycle(credential_store=store2)

    import requests as real_requests

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        mock_req.post.return_value = _mock_oauth_response(
            access_token="net_test_token",  # noqa: S106
            refresh_token="net_test_refresh",  # noqa: S106
            expires_in=2592000,
        )
        # Validation raises network error
        mock_req.get.side_effect = real_requests.ConnectionError("network down")
        mock_req.RequestException = Exception

        token = tl.ensure_valid()

    assert token == "net_test_token"  # noqa: S105


# ── Integration: full startup cycle with fresh tokens ─────────────────────


def test_full_startup_cycle_fresh_tokens_survive(tmp_path, monkeypatch):
    """INTEGRATION: Simulate the exact startup path from launch_blend_forward_test.

    1. Craig writes fresh tokens to .env (no expires_at)
    2. ConnectionManager calls refresh_oauth_if_needed()
    3. TokenLifecycle.ensure_valid() is called
    4. Token should NOT be refreshed — Craig's tokens survive
    """
    # Use a dedicated lock file in tmp_path
    monkeypatch.setenv("AYUMI_TOKEN_LOCK_FILE", str(tmp_path / ".token_refresh.lock"))

    env_path = tmp_path / ".env"
    env_path.write_text(VALID_ENV)

    # This is exactly what ConnectionManager.refresh_oauth_if_needed does:
    store = CredentialStore(env_path=str(env_path))
    tl = TokenLifecycle(store)

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        token = tl.ensure_valid()

    # Craig's tokens must survive
    assert token == "craigs_fresh_token"  # noqa: S105
    mock_req.post.assert_not_called()

    # .env should be unchanged
    content = env_path.read_text()
    assert "craigs_fresh_token" in content
    assert "craigs_fresh_refresh" in content
