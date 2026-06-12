"""Tests for CTraderAuth — unified authentication facade."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from adapters.ctrader.auth import CTraderAuth
from adapters.ctrader.credentials import (
    CredentialManager,
    CredentialError,
    PlaceholderCredentialError,
)


@pytest.fixture
def tmp_project(tmp_path):
    """Create a fake project directory structure."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return tmp_path


@pytest.fixture
def sample_credentials():
    return {
        "client_id": "18449_test_client_id",
        "client_secret": "test_secret_value",
        "access_token": "real_access_token_abc123",
        "refresh_token": "real_refresh_token_xyz789",
        "account_id": "46877902",
        "trader_login": "5795523",
    }


@pytest.fixture
def cred_file(tmp_project, sample_credentials):
    """Write a credentials file in the temp project."""
    path = tmp_project / "data" / ".credentials"
    data = {
        "version": 1,
        "client_id": sample_credentials["client_id"],
        "client_secret": sample_credentials["client_secret"],
        "access_token": sample_credentials["access_token"],
        "refresh_token": sample_credentials["refresh_token"],
        "account_id": sample_credentials["account_id"],
        "trader_login": sample_credentials["trader_login"],
        "last_refreshed": "2026-06-12T18:00:00+00:00",
    }
    path.write_text(json.dumps(data, indent=2))
    return path


@pytest.fixture
def env_file(tmp_project, sample_credentials):
    """Write a .env with cTrader credentials."""
    path = tmp_project / ".env"
    path.write_text(
        f"CTRADER_OPENAPI_CLIENT_ID={sample_credentials['client_id']}\n"
        f"CTRADER_OPENAPI_CLIENT_SECRET={sample_credentials['client_secret']}\n"
        f"CTRADER_OPENAPI_ACCESS_TOKEN={sample_credentials['access_token']}\n"
        f"CTRADER_OPENAPI_REFRESH_TOKEN={sample_credentials['refresh_token']}\n"
        f"CTRADER_OPENAPI_ACCOUNT_ID={sample_credentials['account_id']}\n"
        f"CTRADER_OPENAPI_TRADER_LOGIN={sample_credentials['trader_login']}\n"
    )
    return path


def _make_auth(tmp_project, cred_file, env_file=None):
    """Helper to create a CTraderAuth from pre-existing files."""
    cred_mgr = CredentialManager(
        credentials_path=cred_file,
        env_path=env_file or tmp_project / ".env",
    )

    # Patch _project_root to return tmp_project
    with patch("adapters.ctrader.auth._project_root", return_value=tmp_project):
        auth = CTraderAuth.create(
            credentials_path=cred_file,
            env_path=env_file or tmp_project / ".env",
            token_state_path=tmp_project / "data" / "token_state.json",
            auto_migrate=False,
        )
    return auth


# ── Properties ─────────────────────────────────────────────────────────────

class TestProperties:
    def test_access_token(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        assert auth.access_token == "real_access_token_abc123"

    def test_refresh_token(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        assert auth.refresh_token == "real_refresh_token_xyz789"

    def test_client_id(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        assert auth.client_id == "18449_test_client_id"

    def test_client_secret(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        assert auth.client_secret == "test_secret_value"

    def test_account_id(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        assert auth.account_id == 46877902

    def test_trader_login(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        assert auth.trader_login == "5795523"


# ── Factory: create() ─────────────────────────────────────────────────────

class TestCreate:
    def test_create_from_existing_file(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        assert auth.access_token == "real_access_token_abc123"

    def test_create_auto_migrates(self, tmp_project, env_file):
        with patch("adapters.ctrader.auth._project_root", return_value=tmp_project):
            auth = CTraderAuth.create(
                credentials_path=tmp_project / "data" / ".credentials",
                env_path=env_file,
                token_state_path=tmp_project / "data" / "token_state.json",
                auto_migrate=True,
            )
        assert auth.access_token == "real_access_token_abc123"
        # Credentials file should now exist
        assert (tmp_project / "data" / ".credentials").exists()
        # .env tokens should be emptied
        env_text = env_file.read_text()
        assert "migrated to data/.credentials" in env_text

    def test_create_no_credentials_raises(self, tmp_project):
        with pytest.raises(CredentialError, match="No credentials"):
            with patch("adapters.ctrader.auth._project_root", return_value=tmp_project):
                CTraderAuth.create(
                    credentials_path=tmp_project / "data" / ".credentials",
                    env_path=tmp_project / ".env",
                    token_state_path=tmp_project / "data" / "token_state.json",
                    auto_migrate=True,
                )

    def test_create_no_auto_migrate_raises(self, tmp_project):
        with pytest.raises(CredentialError, match="not found"):
            with patch("adapters.ctrader.auth._project_root", return_value=tmp_project):
                CTraderAuth.create(
                    credentials_path=tmp_project / "data" / ".credentials",
                    env_path=tmp_project / ".env",
                    token_state_path=tmp_project / "data" / "token_state.json",
                    auto_migrate=False,
                )


# ── Authentication methods ────────────────────────────────────────────────

class TestAuthMethods:
    def test_app_authenticate(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        mock_client = MagicMock()
        auth.app_authenticate(mock_client)
        mock_client.send.assert_called_once()
        req = mock_client.send.call_args[0][0]
        assert req.clientId == "18449_test_client_id"

    def test_account_authenticate(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        mock_client = MagicMock()
        auth.account_authenticate(mock_client)
        mock_client.send.assert_called_once()
        req = mock_client.send.call_args[0][0]
        assert req.ctidTraderAccountId == 46877902
        assert req.accessToken == "real_access_token_abc123"

    def test_account_authenticate_override_id(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        mock_client = MagicMock()
        auth.account_authenticate(mock_client, account_id=99999)
        req = mock_client.send.call_args[0][0]
        assert req.ctidTraderAccountId == 99999


# ── Token management ───────────────────────────────────────────────────────

class TestTokenManagement:
    def test_update_tokens(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        auth.update_tokens("new_access_123", "new_refresh_456")
        assert auth.access_token == "new_access_123"
        assert auth.refresh_token == "new_refresh_456"
        # Verify persisted
        data = json.loads(cred_file.read_text())
        assert data["access_token"] == "new_access_123"

    def test_update_tokens_rejects_placeholder(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        with pytest.raises(PlaceholderCredentialError):
            auth.update_tokens("new-access", "valid_refresh")

    def test_load_credentials(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        creds = auth.load_credentials()
        assert creds["access_token"] == "real_access_token_abc123"

    def test_validate_startup(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        status = auth.validate_startup()
        assert status["status"] == "ok"
        assert status["token_hash"] == "real_acc"


# ── Token manager access ──────────────────────────────────────────────────

class TestTokenManagerAccess:
    def test_token_manager_property(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        from adapters.ctrader.token_manager import TokenManager
        assert isinstance(auth.token_manager, TokenManager)

    def test_credential_manager_property(self, tmp_project, cred_file):
        auth = _make_auth(tmp_project, cred_file)
        assert isinstance(auth.credential_manager, CredentialManager)
