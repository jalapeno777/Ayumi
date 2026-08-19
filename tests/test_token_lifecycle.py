"""Unit tests for TokenLifecycle — token refresh kill-switch, OAuth flow, and regression guards.

Covers:
- _refresh_disabled default (regression: must be False)
- ensure_valid(): happy path, expired token, disabled mode
- force_refresh(): success, HTTP 400, HTTP 5xx, network error, disabled mode
- _validate_token(): success, 401 rejection, network error (optimistic)
- _do_refresh_inner(): validates before persisting, handles missing refresh_token
- Regression: kill switch cannot silently revert to True

Card 64a235ea — cTrader token refresh auto-recovery.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

from adapters.ctrader.credential_store import Credentials
from adapters.ctrader.token_lifecycle import (
    TokenLifecycle,
    TokenRefreshError,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_credentials(
    *,
    access_token: str = "old-access-token",
    refresh_token: str = "old-refresh-token",
    expires_at: datetime | None = None,
) -> Credentials:
    """Build a Credentials snapshot for testing."""
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=15)
    return Credentials(
        client_id="test-client-id",
        client_secret="test-client-secret",
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=12345,
        trader_login=67890,
        expires_at=expires_at,
    )


def _make_mock_store(creds: Credentials | None = None) -> MagicMock:
    """Build a mock CredentialStore that returns the given credentials."""
    if creds is None:
        creds = _make_credentials()
    store = MagicMock()
    store.get.return_value = creds
    return store


def _make_lifecycle(creds: Credentials | None = None) -> TokenLifecycle:
    """Build a TokenLifecycle with a mock CredentialStore."""
    store = _make_mock_store(creds)
    return TokenLifecycle(store)


def _mock_oauth_response(
    *,
    status_code: int = 200,
    json_data: dict | None = None,
):
    """Build a mock requests.Response."""
    if json_data is None:
        json_data = {
            "accessToken": "new-access-token",
            "refreshToken": "new-refresh-token",
            "expiresIn": 3600,
        }
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


# ── Regression: kill-switch default ─────────────────────────────────────────


class TestRefreshDisabledDefault:
    """Regression tests ensuring _refresh_disabled defaults to False.

    These prevent the kill switch from silently being flipped back to True,
    which caused ~26h of forward-test downtime in July 2026 (4 outages).
    See card 64a235ea and docs/forex/ayumi-ctrader-token-rotation-runbook.md.
    """

    def test_refresh_disabled_is_false_by_default(self):
        """_refresh_disabled MUST default to False.

        Flipping it to True disables all OAuth refresh logic, causing
        token expiration → service death → manual intervention.
        """
        assert TokenLifecycle._refresh_disabled is False, (
            "_refresh_disabled must be False (refresh enabled). "
            "Re-enabling the kill switch will cause token-expiration outages. "
            "See card 64a235ea — 4 outages, ~26h downtime Jul 2026."
        )

    def test_refresh_disabled_can_be_overridden_per_instance(self):
        """Kill switch can be set per-instance for testing or emergency disable."""
        lc = _make_lifecycle()
        lc._refresh_disabled = True
        assert lc._refresh_disabled is True
        # Reset for other tests
        lc._refresh_disabled = False

    def test_ensure_valid_refreshes_when_disabled_is_false(self):
        """When _refresh_disabled=False, ensure_valid should attempt refresh on expired token."""
        expired_creds = _make_credentials(
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        lc = _make_lifecycle(expired_creds)

        refreshed_creds = _make_credentials(
            access_token="refreshed-token",
            expires_at=datetime.now(timezone.utc) + timedelta(days=15),
        )

        # Simulate store returning updated creds only after update_tokens
        def store_side_effect():
            if mock_update.called:
                return refreshed_creds
            return expired_creds

        mock_update = MagicMock()

        with (
            patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post,
            patch("adapters.ctrader.token_lifecycle.requests.get") as mock_get,
            patch.object(lc._store, "get", side_effect=store_side_effect),
            patch.object(lc._store, "update_tokens", mock_update),
        ):
            mock_post.return_value = _mock_oauth_response()
            mock_get.return_value = Mock(status_code=200)

            token = lc.ensure_valid()
            assert token == "refreshed-token"
            mock_update.assert_called_once()


# ── ensure_valid() ──────────────────────────────────────────────────────────


class TestEnsureValid:
    """Tests for ensure_valid() — proactive refresh entry point."""

    def test_returns_current_token_when_valid(self):
        """Token with >5 days remaining should be returned as-is."""
        creds = _make_credentials(
            expires_at=datetime.now(timezone.utc) + timedelta(days=20),
        )
        lc = _make_lifecycle(creds)

        token = lc.ensure_valid()
        assert token == "old-access-token"

    def test_returns_current_token_when_expires_at_unknown(self):
        """Token with expires_at=None is assumed fresh (manual token mode)."""
        creds = _make_credentials(expires_at=None)
        lc = _make_lifecycle(creds)

        token = lc.ensure_valid()
        assert token == "old-access-token"

    def test_triggers_refresh_when_expired(self):
        """Token past expiry should trigger OAuth refresh."""
        expired_creds = _make_credentials(
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        lc = _make_lifecycle(expired_creds)
        new_creds = _make_credentials(access_token="new-from-refresh")

        with (
            patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post,
            patch("adapters.ctrader.token_lifecycle.requests.get") as mock_get,
            patch.object(lc._store, "get", return_value=new_creds),
            patch.object(lc._store, "update_tokens"),
        ):
            mock_post.return_value = _mock_oauth_response()
            mock_get.return_value = Mock(status_code=200)

            token = lc.ensure_valid()
            assert token == "new-from-refresh"

    def test_disabled_returns_current_token_without_refresh(self):
        """When _refresh_disabled=True, ensure_valid returns current token."""
        expired_creds = _make_credentials(
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        lc = _make_lifecycle(expired_creds)
        lc._refresh_disabled = True

        token = lc.ensure_valid()
        assert token == "old-access-token"


# ── force_refresh() ─────────────────────────────────────────────────────────


class TestForceRefresh:
    """Tests for force_refresh() — reactive refresh on auth errors."""

    def test_force_refresh_success(self):
        """Successful refresh returns new access token."""
        lc = _make_lifecycle()
        new_creds = _make_credentials(access_token="force-refreshed-token")

        with (
            patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post,
            patch("adapters.ctrader.token_lifecycle.requests.get") as mock_get,
            patch.object(lc._store, "get", return_value=new_creds),
            patch.object(lc._store, "update_tokens") as mock_update,
        ):
            mock_post.return_value = _mock_oauth_response()
            mock_get.return_value = Mock(status_code=200)

            token = lc.force_refresh()
            assert token == "force-refreshed-token"
            mock_update.assert_called_once()

    def test_force_refresh_http_400_permanent_failure(self):
        """HTTP 400 (invalid grant) raises non-retryable TokenRefreshError."""
        lc = _make_lifecycle()

        with patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post:
            mock_post.return_value = _mock_oauth_response(
                status_code=400,
                json_data={"error": "invalid_grant"},
            )

            with pytest.raises(TokenRefreshError) as exc_info:
                lc.force_refresh()
            assert exc_info.value.retry is False

    def test_force_refresh_http_500_retryable(self):
        """HTTP 5xx raises retryable TokenRefreshError."""
        lc = _make_lifecycle()

        with patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post:
            mock_post.return_value = _mock_oauth_response(
                status_code=503,
                json_data={"error": "server_error"},
            )

            with pytest.raises(TokenRefreshError) as exc_info:
                lc.force_refresh()
            assert exc_info.value.retry is True

    def test_force_refresh_network_error_retryable(self):
        """Network errors raise retryable TokenRefreshError."""
        import requests as req

        lc = _make_lifecycle()

        with patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post:
            mock_post.side_effect = req.RequestException("Connection refused")

            with pytest.raises(TokenRefreshError) as exc_info:
                lc.force_refresh()
            assert exc_info.value.retry is True

    def test_force_refresh_disabled_returns_current_token(self):
        """When _refresh_disabled=True, force_refresh returns current token."""
        lc = _make_lifecycle()
        lc._refresh_disabled = True

        token = lc.force_refresh()
        assert token == "old-access-token"

    def test_force_refresh_no_refresh_token_raises(self):
        """Missing refresh_token raises permanent TokenRefreshError."""
        creds = _make_credentials(refresh_token="")
        lc = _make_lifecycle(creds)

        with pytest.raises(TokenRefreshError) as exc_info:
            lc.force_refresh()
        assert "No refresh_token" in str(exc_info.value)
        assert exc_info.value.retry is False


# ── _validate_token() ───────────────────────────────────────────────────────


class TestValidateToken:
    """Tests for _validate_token() — pre-commit token validation."""

    def test_validate_success(self):
        """Valid token returns True on HTTP 200."""
        lc = _make_lifecycle()

        with patch("adapters.ctrader.token_lifecycle.requests.get") as mock_get:
            mock_get.return_value = Mock(status_code=200)
            assert lc._validate_token("some-token") is True

    def test_validate_rejected_401(self):
        """Invalid token returns False on HTTP 401."""
        lc = _make_lifecycle()

        with patch("adapters.ctrader.token_lifecycle.requests.get") as mock_get:
            mock_get.return_value = Mock(status_code=401, text="Unauthorized")
            assert lc._validate_token("bad-token") is False

    def test_validate_rejected_403(self):
        """Forbidden token returns False on HTTP 403."""
        lc = _make_lifecycle()

        with patch("adapters.ctrader.token_lifecycle.requests.get") as mock_get:
            mock_get.return_value = Mock(status_code=403, text="Forbidden")
            assert lc._validate_token("bad-token") is False

    def test_validate_network_error_optimistic(self):
        """Network error during validation returns True (optimistic)."""
        import requests as req

        lc = _make_lifecycle()

        with patch("adapters.ctrader.token_lifecycle.requests.get") as mock_get:
            mock_get.side_effect = req.RequestException("Timeout")
            assert lc._validate_token("some-token") is True

    def test_validate_unexpected_status_optimistic(self):
        """Unexpected HTTP status returns True (optimistic)."""
        lc = _make_lifecycle()

        with patch("adapters.ctrader.token_lifecycle.requests.get") as mock_get:
            mock_get.return_value = Mock(status_code=418, text="I'm a teapot")
            assert lc._validate_token("some-token") is True


# ── _do_refresh_inner() validation gate ─────────────────────────────────────


class TestRefreshValidationGate:
    """Tests for the validation gate in _do_refresh_inner().

    Ensures refreshed tokens are validated against cTrader API before
    being committed to .env. If validation fails, old tokens are retained.
    """

    def test_validation_failure_prevents_persist(self):
        """If _validate_token returns False, tokens are NOT persisted."""
        lc = _make_lifecycle()

        with (
            patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post,
            patch.object(lc, "_validate_token", return_value=False),
            patch.object(lc._store, "update_tokens") as mock_update,
        ):
            mock_post.return_value = _mock_oauth_response()

            # Use force=True to skip the pre-refresh validity re-check
            with pytest.raises(TokenRefreshError) as exc_info:
                lc._do_refresh(force=True)
            assert "failed validation" in str(exc_info.value).lower()
            mock_update.assert_not_called()

    def test_validation_success_persists_tokens(self):
        """If _validate_token returns True, tokens ARE persisted."""
        lc = _make_lifecycle()
        new_creds = _make_credentials(access_token="validated-new-token")

        with (
            patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post,
            patch.object(lc, "_validate_token", return_value=True),
            patch.object(lc._store, "get", return_value=new_creds),
            patch.object(lc._store, "update_tokens") as mock_update,
        ):
            mock_post.return_value = _mock_oauth_response()

            # Use force=True to skip the pre-refresh validity re-check
            token = lc._do_refresh(force=True)
            assert token == "validated-new-token"
            mock_update.assert_called_once()


# ── Thread safety ───────────────────────────────────────────────────────────


class TestThreadSafety:
    """Verify concurrent access is serialized via lock."""

    def test_concurrent_ensure_valid_single_refresh(self):
        """Multiple concurrent ensure_valid() calls should trigger only one OAuth request."""
        expired_creds = _make_credentials(
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            access_token="pre-refresh-token",
        )
        refreshed_creds = _make_credentials(
            access_token="concurrent-result",
            expires_at=datetime.now(timezone.utc) + timedelta(days=15),
        )
        lc = _make_lifecycle(expired_creds)

        call_count = 0
        update_called = threading.Event()

        def fake_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _mock_oauth_response()

        def store_side_effect():
            if update_called.is_set():
                return refreshed_creds
            return expired_creds

        def fake_update(*args, **kwargs):
            update_called.set()

        with (
            patch(
                "adapters.ctrader.token_lifecycle.requests.post", side_effect=fake_post
            ),
            patch(
                "adapters.ctrader.token_lifecycle.requests.get",
                return_value=Mock(status_code=200),
            ),
            patch.object(lc._store, "get", side_effect=store_side_effect),
            patch.object(lc._store, "update_tokens", side_effect=fake_update),
        ):
            threads = []
            results = []

            def worker():
                results.append(lc.ensure_valid())

            for _ in range(5):
                t = threading.Thread(target=worker)
                threads.append(t)
                t.start()
            for t in threads:
                t.join()

            assert all(r == "concurrent-result" for r in results)
            # Exactly one OAuth call should have been made
            assert call_count == 1
