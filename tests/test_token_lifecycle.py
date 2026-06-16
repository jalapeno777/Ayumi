"""Tests for TokenLifecycle — single token refresh path for cTrader OAuth.

All HTTP calls are mocked. No real OAuth requests are made.
"""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from adapters.ctrader.credential_store import CredentialStore
from adapters.ctrader.token_lifecycle import (
    OAUTH_URL,
    REFRESH_BUFFER,
    TokenLifecycle,
    TokenRefreshError,
)

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


def _make_store(tmp_path) -> CredentialStore:
    """Build a CredentialStore with valid creds on disk."""
    cred_path = tmp_path / "data" / ".credentials"
    cred_path.parent.mkdir(parents=True)
    cred_path.write_text(json.dumps(VALID_CREDS))
    store = CredentialStore(credentials_path=str(cred_path))
    store.load()
    return store


def _mock_oauth_response(
    access_token="new_access_token",
    refresh_token="new_refresh_token",
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


def _make_expiring_store(tmp_path, minutes_to_expiry: int) -> CredentialStore:
    """Build a store whose token expires in N minutes."""
    creds = dict(VALID_CREDS)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes_to_expiry)
    creds["expires_at"] = expires_at.isoformat()
    cred_path = tmp_path / "data" / ".credentials"
    cred_path.parent.mkdir(parents=True)
    cred_path.write_text(json.dumps(creds))
    store = CredentialStore(credentials_path=str(cred_path))
    store.load()
    return store


# ── Tests ──────────────────────────────────────────────────────────────────


def test_ensure_valid_returns_cached_token(tmp_path):
    """Token expires in 1h — ensure_valid returns it without refresh."""
    store = _make_expiring_store(tmp_path, minutes_to_expiry=60)
    tl = TokenLifecycle(credential_store=store)

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        token = tl.ensure_valid()

    assert token == "test_access_token"
    # OAuth endpoint should NOT have been called
    mock_req.post.assert_not_called()


def test_ensure_valid_refreshes_when_expiring_soon(tmp_path):
    """Token expires in 2min (< 5min buffer) — triggers refresh."""
    store = _make_expiring_store(tmp_path, minutes_to_expiry=2)
    tl = TokenLifecycle(credential_store=store)

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        mock_req.post.return_value = _mock_oauth_response(
            access_token="refreshed_token", expires_in=3600
        )
        mock_req.RequestException = Exception  # needed for except clause

        token = tl.ensure_valid()

    assert token == "refreshed_token"
    mock_req.post.assert_called_once()

    # Verify the OAuth call used the right endpoint and payload
    call_args = mock_req.post.call_args
    assert call_args[0][0] == OAUTH_URL
    sent_data = call_args[1]["data"]
    assert sent_data["grant_type"] == "refresh_token"
    assert sent_data["client_id"] == "test_client_id"
    assert sent_data["client_secret"] == "test_secret"


def test_force_refresh_updates_credential_store(tmp_path):
    """Force refresh — verify credential_store.update_tokens is called."""
    store = _make_store(tmp_path)
    tl = TokenLifecycle(credential_store=store)

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        mock_req.post.return_value = _mock_oauth_response(
            access_token="forced_new_token",
            refresh_token="forced_new_refresh",
            expires_in=7200,
        )
        mock_req.RequestException = Exception

        token = tl.force_refresh()

    assert token == "forced_new_token"

    # Verify the store was updated
    creds = store.get()
    assert creds.access_token == "forced_new_token"
    assert creds.refresh_token == "forced_new_refresh"
    assert creds.expires_at is not None


def test_force_refresh_on_http400_raises(tmp_path):
    """HTTP 400 = invalid grant — TokenRefreshError with retry=False."""
    store = _make_store(tmp_path)
    tl = TokenLifecycle(credential_store=store)

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        mock_req.post.return_value = _mock_oauth_response(status_code=400)
        mock_req.RequestException = Exception

        with pytest.raises(TokenRefreshError) as exc_info:
            tl.force_refresh()

    assert exc_info.value.retry is False
    assert "manual intervention" in str(exc_info.value).lower()


def test_force_refresh_on_http500_raises_retryable(tmp_path):
    """HTTP 500 = server error — TokenRefreshError with retry=True."""
    store = _make_store(tmp_path)
    tl = TokenLifecycle(credential_store=store)

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        mock_req.post.return_value = _mock_oauth_response(status_code=500)
        mock_req.RequestException = Exception

        with pytest.raises(TokenRefreshError) as exc_info:
            tl.force_refresh()

    assert exc_info.value.retry is True
    assert "server error" in str(exc_info.value).lower()


def test_concurrent_refresh_is_serialized(tmp_path):
    """10 threads call ensure_valid simultaneously — OAuth called exactly ONCE."""
    store = _make_expiring_store(tmp_path, minutes_to_expiry=0)
    # Token is already expired
    tl = TokenLifecycle(credential_store=store)

    call_count = 0
    count_lock = threading.Lock()

    def fake_post(*args, **kwargs):
        nonlocal call_count
        with count_lock:
            call_count += 1
        # Simulate small network latency
        time.sleep(0.05)
        return _mock_oauth_response(
            access_token="concurrent_token", expires_in=3600
        )

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        mock_req.post.side_effect = fake_post
        mock_req.RequestException = Exception

        results: list[str] = []
        errors: list[Exception] = []

        def worker():
            try:
                results.append(tl.ensure_valid())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(errors) == 0, f"Thread errors: {errors}"
    assert len(results) == 10
    # All results should be the same token
    assert all(r == "concurrent_token" for r in results)
    # OAuth endpoint called exactly ONCE despite 10 concurrent threads
    assert call_count == 1, f"OAuth called {call_count} times, expected 1"


def test_proactive_timer_refreshes_before_expiry(tmp_path):
    """Token expires in 3min — proactive timer fires refresh within 60s."""
    store = _make_expiring_store(tmp_path, minutes_to_expiry=3)
    tl = TokenLifecycle(credential_store=store)

    refreshed_tokens: list[str] = []
    callback_event = threading.Event()

    def on_refreshed(token: str):
        refreshed_tokens.append(token)
        callback_event.set()

    with patch("adapters.ctrader.token_lifecycle.requests") as mock_req:
        mock_req.post.return_value = _mock_oauth_response(
            access_token="timer_refreshed_token", expires_in=3600
        )
        mock_req.RequestException = Exception

        tl.start_proactive_timer(on_refreshed=on_refreshed)

        # Wait up to 10s for the callback to fire
        # (timer checks every 60s but first check is immediate on loop entry)
        assert callback_event.wait(timeout=15), (
            "Proactive timer did not refresh within timeout"
        )

        tl.stop_proactive_timer()

    assert len(refreshed_tokens) == 1
    assert refreshed_tokens[0] == "timer_refreshed_token"
    mock_req.post.assert_called()
