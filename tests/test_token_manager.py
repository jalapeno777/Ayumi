"""Tests for TokenManager (BQ-681).

Covers:
- Startup validation (fresh, expired, placeholder, missing)
- needs_refresh() with various remaining days
- State persistence (write → load → verify)
- refresh_history capped at 50 entries (L-2)
- Schema version field present (L-1)
- Atomic write (file exists after save)
- Edge cases: refresh response missing fields, 4xx/5xx errors (L-3)
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, "/home/TacoPants/projects/Ayumi/src/forex-bot/adapters/ctrader")
from token_manager import TokenManager, TokenStatus, CTRADER_OAUTH_REFRESH_URL, DEFAULT_TOKEN_TTL, MAX_REFRESH_HISTORY


@pytest.fixture
def tmp_token_path(tmp_path: Path) -> Path:
    """Return a temporary path for the token state file."""
    return tmp_path / "token_state.json"


@pytest.fixture
def tmp_env_path(tmp_path: Path) -> Path:
    """Return a temporary .env file path."""
    env = tmp_path / ".env"
    env.write_text("CTRADER_OPENAPI_ACCESS_TOKEN=old_access\nCTRADER_OPENAPI_REFRESH_TOKEN=old_refresh\n")
    return env


@pytest.fixture
def tm(tmp_token_path: Path, tmp_env_path: Path) -> TokenManager:
    """Return a TokenManager backed by temporary files."""
    return TokenManager(token_path=str(tmp_token_path), env_path=str(tmp_env_path))


# ─── validate_on_startup ────────────────────────────────────────────────────


class TestValidateOnStartup:
    def test_fresh_token_returns_ok(self, tm: TokenManager) -> None:
        token = "abcdefgh123456789"
        tm.track_token(token, DEFAULT_TOKEN_TTL)
        result = tm.validate_on_startup(token)
        assert result["status"] == TokenStatus.OK
        assert result["days_remaining"] > 20
        assert result["token_hash"] == "abcdefgh"

    def test_expired_token_returns_expired(self, tm: TokenManager) -> None:
        token = "expired01XYZ"
        # Manually back-date the issued_at to simulate expiry
        past = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - 40 * 86_400, tz=timezone.utc
        ).isoformat()
        # Use the correct hash (first 8 chars of the actual token value passed to validate_on_startup)
        tm._state = {
            "version": 1,
            "tokens": {
                "expired0": {  # hash = token[:8] = 'expired01XYZ'[:8]
                    "issued_at": past,
                    "expires_in": DEFAULT_TOKEN_TTL,
                    "last_refreshed": past,
                    "refresh_count": 0,
                }
            },
            "refresh_history": [],
        }
        tm._save_state(tm._state)
        # Re-load so internal state reflects back-dated value
        tm._load_state()

        result = tm.validate_on_startup(token)
        assert result["status"] == TokenStatus.EXPIRED
        assert result["days_remaining"] < 0
        assert "expired" in result["message"].lower()

    def test_placeholder_token_detected(self, tm: TokenManager) -> None:
        result = tm.validate_on_startup("new-access")
        assert result["status"] == TokenStatus.PLACEHOLDER
        assert result["token_hash"] == "new-acce"

    def test_missing_token(self, tm: TokenManager) -> None:
        result = tm.validate_on_startup("")
        assert result["status"] == TokenStatus.MISSING

    def test_unknown_token_returns_ok_but_warns(self, tm: TokenManager) -> None:
        result = tm.validate_on_startup("unknown123")
        assert result["status"] == TokenStatus.OK
        assert "not previously tracked" in result["message"]


# ─── needs_refresh ──────────────────────────────────────────────────────────


class TestNeedsRefresh:
    def test_five_days_remaining_true(self, tm: TokenManager) -> None:
        token = "token1234"
        # Issue 25 days ago (5 days remaining of 30-day TTL)
        past = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - 25 * 86_400, tz=timezone.utc
        ).isoformat()
        tm._state = {
            "version": 1,
            "tokens": {
                "token1234": {
                    "issued_at": past,
                    "expires_in": DEFAULT_TOKEN_TTL,
                    "last_refreshed": past,
                    "refresh_count": 0,
                }
            },
            "refresh_history": [],
        }
        tm._save_state(tm._state)
        tm._load_state()

        assert tm.needs_refresh(warning_days=7) is True

    def test_twenty_days_remaining_false(self, tm: TokenManager) -> None:
        token = "token5678"
        # Issue 10 days ago (20 days remaining of 30-day TTL)
        past = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - 10 * 86_400, tz=timezone.utc
        ).isoformat()
        tm._state = {
            "version": 1,
            "tokens": {
                "token5678": {
                    "issued_at": past,
                    "expires_in": DEFAULT_TOKEN_TTL,
                    "last_refreshed": past,
                    "refresh_count": 0,
                }
            },
            "refresh_history": [],
        }
        tm._save_state(tm._state)
        tm._load_state()

        assert tm.needs_refresh(warning_days=7) is False


# ─── State persistence ──────────────────────────────────────────────────────


class TestStatePersistence:
    def test_write_then_load_verifies(self, tm: TokenManager, tmp_token_path: Path) -> None:
        tm.track_token("mytoken123", 12345)
        # Create a fresh instance pointing at the same file
        tm2 = TokenManager(token_path=str(tmp_token_path), env_path=str(tm._env_path))
        state = tm2._load_state()
        assert "mytoken1" in state["tokens"]
        assert state["tokens"]["mytoken1"]["expires_in"] == 12345

    def test_schema_version_present(self, tm: TokenManager) -> None:
        tm.track_token("anytoken", DEFAULT_TOKEN_TTL)
        state = tm._load_state()
        assert "version" in state
        assert state["version"] == 1


# ─── refresh_history cap ────────────────────────────────────────────────────


class TestRefreshHistory:
    def test_history_capped_at_50(self, tm: TokenManager) -> None:
        for i in range(55):
            tm._append_refresh_history(success=True, error=None)

        state = tm._load_state()
        history = state["refresh_history"]
        assert len(history) == 50
        # Most recent entries should be preserved
        assert history[-1]["timestamp"] > history[0]["timestamp"]


# ─── Atomic write ───────────────────────────────────────────────────────────


class TestAtomicWrite:
    def test_file_exists_after_save(self, tm: TokenManager, tmp_token_path: Path) -> None:
        tm.track_token("atomic01", 1000)
        assert tmp_token_path.exists()
        data = json.loads(tmp_token_path.read_text())
        assert data["tokens"]["atomic01"]["expires_in"] == 1000


# ─── refresh_if_needed / _do_refresh edge cases ─────────────────────────────


class TestRefreshEdgeCases:
    def test_missing_fields_in_response(self, tm: TokenManager) -> None:
        """Simulate a 200 OK response missing access_token."""
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"expires_in": 3600}  # no accessToken
            mock_post.return_value = mock_resp

            result = tm._do_refresh("cid", "csecret", "rtoken")
            assert result is None
            state = tm._load_state()
            history = state["refresh_history"]
            assert history[-1]["success"] is False
            assert "missing_access_token" in history[-1]["error"]

    def test_4xx_error(self, tm: TokenManager) -> None:
        """Simulate a 4xx response with errorCode."""
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"errorCode": "INVALID_GRANT", "description": "bad refresh token"}
            mock_post.return_value = mock_resp

            result = tm._do_refresh("cid", "csecret", "rtoken")
            assert result is None
            state = tm._load_state()
            history = state["refresh_history"]
            assert history[-1]["success"] is False
            assert "bad refresh token" in history[-1]["error"]

    def test_network_exception(self, tm: TokenManager) -> None:
        """Simulate a requests exception (timeout, connection error)."""
        with patch("requests.post") as mock_post:
            mock_post.side_effect = Exception("Connection timeout")

            result = tm._do_refresh("cid", "csecret", "rtoken")
            assert result is None
            state = tm._load_state()
            history = state["refresh_history"]
            assert history[-1]["success"] is False
            assert "Connection timeout" in history[-1]["error"]

    def test_successful_refresh_returns_new_token(self, tm: TokenManager) -> None:
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "accessToken": "new_access_123",
                "refreshToken": "new_refresh_456",
                "expiresIn": 7200,
            }
            mock_post.return_value = mock_resp

            result = tm._do_refresh("cid", "csecret", "rtoken")
            assert result == "new_access_123"
            state = tm._load_state()
            assert "new_acce" in state["tokens"]
            history = state["refresh_history"]
            assert history[-1]["success"] is True
            assert history[-1]["error"] is None


# ─── get_status ─────────────────────────────────────────────────────────────


class TestGetStatus:
    def test_returns_none_when_no_token(self, tm: TokenManager) -> None:
        status = tm.get_status()
        assert status["token_hash"] is None
        assert status["age_seconds"] is None

    def test_returns_metrics_when_token_tracked(self, tm: TokenManager) -> None:
        tm.track_token("status01", DEFAULT_TOKEN_TTL)
        status = tm.get_status()
        assert status["token_hash"] == "status01"
        assert status["ttl_seconds"] == DEFAULT_TOKEN_TTL
        assert status["refresh_count"] == 0
        assert status["history_entries"] == 0
        assert isinstance(status["age_seconds"], float)


# ─── atomic .env write ──────────────────────────────────────────────────────


class TestAtomicEnvWrite:
    def test_env_updated_atomically(self, tm: TokenManager, tmp_env_path: Path) -> None:
        tm._atomic_env_write("updated_access", "updated_refresh")
        lines = tmp_env_path.read_text().splitlines()
        assert any("CTRADER_OPENAPI_ACCESS_TOKEN=updated_access" in line for line in lines)
        assert any("CTRADER_OPENAPI_REFRESH_TOKEN=updated_refresh" in line for line in lines)

    def test_env_created_if_keys_missing(self, tm: TokenManager, tmp_path: Path) -> None:
        bare_env = tmp_path / "bare.env"
        bare_env.write_text("OTHER_KEY=value\n")
        tm_bare = TokenManager(token_path=str(tmp_path / "token_state.json"), env_path=str(bare_env))
        tm_bare._atomic_env_write("new_access", "new_refresh")
        lines = bare_env.read_text().splitlines()
        assert any("CTRADER_OPENAPI_ACCESS_TOKEN=new_access" in line for line in lines)
        assert any("CTRADER_OPENAPI_REFRESH_TOKEN=new_refresh" in line for line in lines)


# ─── refresh_if_needed delegation ───────────────────────────────────────────


class TestRefreshIfNeeded:
    def test_skips_when_not_needed(self, tm: TokenManager) -> None:
        token = "fresh_tok"
        # Token issued just now
        tm.track_token(token, DEFAULT_TOKEN_TTL)
        with patch.object(tm, "_do_refresh") as mock_do:
            result = tm.refresh_if_needed("cid", "csecret", "rtoken", warning_days=7)
            assert result is None
            mock_do.assert_not_called()

    def test_delegates_when_needed(self, tm: TokenManager) -> None:
        token = "stale_tok"
        past = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - 25 * 86_400, tz=timezone.utc
        ).isoformat()
        tm._state = {
            "version": 1,
            "tokens": {
                "stale_tok": {
                    "issued_at": past,
                    "expires_in": DEFAULT_TOKEN_TTL,
                    "last_refreshed": past,
                    "refresh_count": 0,
                }
            },
            "refresh_history": [],
        }
        tm._save_state(tm._state)
        tm._load_state()

        with patch.object(tm, "_do_refresh", return_value="new_access") as mock_do:
            result = tm.refresh_if_needed("cid", "csecret", "rtoken", warning_days=7)
            assert result == "new_access"
            mock_do.assert_called_once_with("cid", "csecret", "rtoken")
