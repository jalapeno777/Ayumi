"""Tests for CredentialManager — atomic credential storage."""

import json
import os
import stat
import tempfile
from pathlib import Path

import pytest

from adapters.ctrader.credentials import (
    CredentialManager,
    CredentialError,
    PlaceholderCredentialError,
    CREDENTIALS_VERSION,
)


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory with .env and credentials paths."""
    return tmp_path


@pytest.fixture
def cred_mgr(tmp_dir):
    """CredentialManager pointing at temp paths."""
    return CredentialManager(
        credentials_path=tmp_dir / "data" / ".credentials",
        env_path=tmp_dir / ".env",
    )


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
def sample_env_content():
    """Return .env content with cTrader credentials."""
    return (
        "CTRADER_HOST=demo.ctraderapi.com\n"
        "CTRADER_OPENAPI_CLIENT_ID=18449_test_client_id\n"
        "CTRADER_OPENAPI_CLIENT_SECRET=test_secret_value\n"
        "CTRADER_OPENAPI_ACCESS_TOKEN=real_access_token_abc123\n"
        "CTRADER_OPENAPI_REFRESH_TOKEN=real_refresh_token_xyz789\n"
        "CTRADER_OPENAPI_ACCOUNT_ID=46877902\n"
        "CTRADER_OPENAPI_TRADER_LOGIN=5795523\n"
        "SOME_OTHER_VAR=keep_me\n"
    )


# ── Save / Load ────────────────────────────────────────────────────────────

class TestSaveLoad:
    def test_save_creates_file(self, cred_mgr, sample_credentials):
        cred_mgr.save(sample_credentials)
        assert cred_mgr._path.exists()

    def test_save_sets_permissions_600(self, cred_mgr, sample_credentials):
        cred_mgr.save(sample_credentials)
        mode = os.stat(cred_mgr._path).st_mode
        assert (mode & 0o777) == 0o600

    def test_load_roundtrip(self, cred_mgr, sample_credentials):
        cred_mgr.save(sample_credentials)
        loaded = cred_mgr.load()
        assert loaded["client_id"] == sample_credentials["client_id"]
        assert loaded["access_token"] == sample_credentials["access_token"]
        assert loaded["version"] == CREDENTIALS_VERSION

    def test_load_missing_file_raises(self, cred_mgr):
        with pytest.raises(CredentialError, match="not found"):
            cred_mgr.load()

    def test_load_corrupt_file_raises(self, cred_mgr):
        cred_mgr._path.parent.mkdir(parents=True, exist_ok=True)
        cred_mgr._path.write_text("NOT JSON{{{")
        with pytest.raises(CredentialError, match="Failed to load"):
            cred_mgr.load()

    def test_load_wrong_version_raises(self, cred_mgr, sample_credentials):
        cred_mgr.save(sample_credentials)
        # Tamper with version
        data = json.loads(cred_mgr._path.read_text())
        data["version"] = 999
        cred_mgr._path.write_text(json.dumps(data))
        with pytest.raises(CredentialError, match="Unsupported"):
            cred_mgr.load()


# ── Placeholder detection ──────────────────────────────────────────────────

class TestPlaceholderDetection:
    @pytest.mark.parametrize("placeholder", [
        "new-access", "new-refresh", "REPLACE", "xxx", "",
    ])
    def test_rejects_placeholder_access_token(self, cred_mgr, sample_credentials, placeholder):
        sample_credentials["access_token"] = placeholder
        with pytest.raises(PlaceholderCredentialError):
            cred_mgr.save(sample_credentials)

    @pytest.mark.parametrize("placeholder", [
        "new-access", "REPLACE", "xxx", "",
    ])
    def test_rejects_placeholder_refresh_token(self, cred_mgr, sample_credentials, placeholder):
        sample_credentials["refresh_token"] = placeholder
        with pytest.raises(PlaceholderCredentialError):
            cred_mgr.save(sample_credentials)


# ── Update tokens ──────────────────────────────────────────────────────────

class TestUpdateTokens:
    def test_update_tokens(self, cred_mgr, sample_credentials):
        cred_mgr.save(sample_credentials)
        cred_mgr.update_tokens("new_real_access", "new_real_refresh")
        loaded = cred_mgr.load()
        assert loaded["access_token"] == "new_real_access"
        assert loaded["refresh_token"] == "new_real_refresh"

    def test_update_tokens_rejects_placeholder(self, cred_mgr, sample_credentials):
        cred_mgr.save(sample_credentials)
        with pytest.raises(PlaceholderCredentialError):
            cred_mgr.update_tokens("new-access", "valid_refresh")

    def test_update_tokens_rejects_missing_file(self, cred_mgr):
        with pytest.raises(CredentialError, match="does not exist"):
            cred_mgr.update_tokens("access", "refresh")


# ── Migration ──────────────────────────────────────────────────────────────

class TestMigration:
    def test_needs_migration_true(self, cred_mgr, sample_env_content):
        cred_mgr._env_path.write_text(sample_env_content)
        assert cred_mgr.needs_migration() is True

    def test_needs_migration_false_empty_env(self, cred_mgr):
        cred_mgr._env_path.write_text("SOME_VAR=value\n")
        assert cred_mgr.needs_migration() is False

    def test_needs_migration_false_placeholder_tokens(self, cred_mgr):
        env = (
            "CTRADER_OPENAPI_ACCESS_TOKEN=new-access\n"
            "CTRADER_OPENAPI_REFRESH_TOKEN=new-refresh\n"
        )
        cred_mgr._env_path.write_text(env)
        assert cred_mgr.needs_migration() is False

    def test_needs_migration_false_no_env_file(self, cred_mgr):
        assert cred_mgr.needs_migration() is False

    def test_migrate_from_env(self, cred_mgr, sample_env_content):
        cred_mgr._env_path.write_text(sample_env_content)
        result = cred_mgr.migrate_from_env()
        assert result["client_id"] == "18449_test_client_id"
        assert result["access_token"] == "real_access_token_abc123"

        # Verify credentials file created
        assert cred_mgr._path.exists()
        loaded = cred_mgr.load()
        assert loaded["access_token"] == "real_access_token_abc123"

    def test_migrate_preserves_env_tokens(self, cred_mgr, sample_env_content):
        """BQ-1036: Migration must NOT empty .env token values."""
        cred_mgr._env_path.write_text(sample_env_content)
        cred_mgr.migrate_from_env()

        env_text = cred_mgr._env_path.read_text()
        # Tokens should STILL be in .env (backup)
        assert "real_access_token_abc123" in env_text
        # Other vars should remain intact
        assert "SOME_OTHER_VAR=keep_me" in env_text
        # Credentials file should have the values
        loaded = cred_mgr.load()
        assert loaded["access_token"] == "real_access_token_abc123"

    def test_migrate_no_real_credentials_raises(self, cred_mgr):
        env = (
            "CTRADER_OPENAPI_ACCESS_TOKEN=new-access\n"
            "CTRADER_OPENAPI_REFRESH_TOKEN=new-refresh\n"
        )
        cred_mgr._env_path.write_text(env)
        with pytest.raises(CredentialError, match="No real credentials"):
            cred_mgr.migrate_from_env()

    def test_migrate_missing_env_raises(self, cred_mgr):
        with pytest.raises(CredentialError, match="No real credentials"):
            cred_mgr.migrate_from_env()


# ── Startup check ──────────────────────────────────────────────────────────

class TestStartupCheck:
    def test_dual_source_detected(self, cred_mgr, sample_env_content, sample_credentials):
        # Write credentials file
        cred_mgr.save(sample_credentials)
        # Also keep tokens in .env
        cred_mgr._env_path.write_text(sample_env_content)
        result = cred_mgr.startup_check()
        assert result is not None
        assert "Dual source" in result["error"]

    def test_clean_state_no_warning(self, cred_mgr, sample_credentials):
        cred_mgr.save(sample_credentials)
        result = cred_mgr.startup_check()
        assert result is None

    def test_has_dual_source(self, cred_mgr, sample_env_content, sample_credentials):
        cred_mgr.save(sample_credentials)
        cred_mgr._env_path.write_text(sample_env_content)
        assert cred_mgr.has_dual_source() is True

    def test_no_dual_source_when_only_file(self, cred_mgr, sample_credentials):
        cred_mgr.save(sample_credentials)
        assert cred_mgr.has_dual_source() is False
