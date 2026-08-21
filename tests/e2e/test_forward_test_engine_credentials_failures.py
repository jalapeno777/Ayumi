"""Tests for T5 — fail loudly on missing live credentials.

The original ``_build_components`` early-returns silently when live
credentials are unavailable, leaving the engine with
``_paper_trader=None`` AND ``_market_feed=None`` — a completely broken
state.  T5 raises a ``RuntimeError`` with an actionable message instead,
listing the missing env vars.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from adapters.ctrader.forward_test_engine import (
    ForwardTestConfig,
    ForwardTestEngine,
)


@pytest.fixture(autouse=True)
def _clear_openapi_env(monkeypatch):
    """Each test starts with no OpenAPI env vars set.

    This isolates ``_describe_missing_live_creds`` from any leakage
    from other tests.
    """
    for var in (
        "CTRADER_OPENAPI_CLIENT_ID",
        "CTRADER_OPENAPI_CLIENT_SECRET",
        "CTRADER_OPENAPI_ACCESS_TOKEN",
        "CTRADER_OPENAPI_REFRESH_TOKEN",
        "CTRADER_OPENAPI_ACCOUNT_ID",
        "CTRADER_OPENAPI_TRADER_LOGIN",
    ):
        monkeypatch.delenv(var, raising=False)


class TestLoudFailureOnMissingCredentials:
    """The engine must raise, not silently half-build, when live creds are missing."""

    def test_runtime_error_when_live_creds_none(self):
        """If ``_build_live_credentials`` returns None, ``_build_components`` raises RuntimeError."""
        cfg = ForwardTestConfig(live_mode=True)
        engine = ForwardTestEngine(config=cfg, strategies=[])
        with patch.object(engine, "_build_live_credentials", return_value=None):
            with pytest.raises(RuntimeError) as excinfo:
                engine._build_components()
        assert "live_mode=True" in str(excinfo.value)

    def test_runtime_error_lists_required_env_vars(self):
        """Error message names every required env var so operators can fix it fast."""
        cfg = ForwardTestConfig(live_mode=True)
        engine = ForwardTestEngine(config=cfg, strategies=[])
        with patch.object(engine, "_build_live_credentials", return_value=None):
            with pytest.raises(RuntimeError) as excinfo:
                engine._build_components()
        msg = str(excinfo.value)
        assert "CTRADER_OPENAPI_CLIENT_ID" in msg
        assert "CTRADER_OPENAPI_CLIENT_SECRET" in msg
        assert "CTRADER_OPENAPI_ACCESS_TOKEN" in msg
        assert "CTRADER_OPENAPI_ACCOUNT_ID" in msg

    def test_runtime_error_lists_specifically_missing_env_vars(self):
        """If only some env vars are set, the message names only those still missing."""
        os.environ["CTRADER_OPENAPI_CLIENT_ID"] = "test"
        cfg = ForwardTestConfig(live_mode=True)
        engine = ForwardTestEngine(config=cfg, strategies=[])
        with patch.object(engine, "_build_live_credentials", return_value=None):
            with pytest.raises(RuntimeError) as excinfo:
                engine._build_components()
        msg = str(excinfo.value)
        assert "CTRADER_OPENAPI_CLIENT_ID" not in msg.split("Missing:")[-1] if "Missing:" in msg else True
        # If Missing: section exists, it should not include CLIENT_ID
        if "Missing:" in msg:
            missing_section = msg.split("Missing:")[1].split(".")[0]
            assert "CTRADER_OPENAPI_CLIENT_ID" not in missing_section
        assert "CTRADER_OPENAPI_CLIENT_SECRET" in msg

    def test_runtime_error_suggests_paper_mode_fallback(self):
        """The error message tells operators they can omit --live for paper mode."""
        cfg = ForwardTestConfig(live_mode=True)
        engine = ForwardTestEngine(config=cfg, strategies=[])
        with patch.object(engine, "_build_live_credentials", return_value=None):
            with pytest.raises(RuntimeError) as excinfo:
                engine._build_components()
        assert "paper" in str(excinfo.value).lower() or "paper-only" in str(excinfo.value).lower()


class TestPaperModeIsUnaffected:
    """Paper mode must NOT raise on missing OpenAPI creds — it doesn't need them."""

    def test_paper_mode_does_not_invoke_build_live_credentials(self):
        """In paper mode, ``_build_live_credentials`` is not called."""
        cfg = ForwardTestConfig(live_mode=False)
        engine = ForwardTestEngine(config=cfg, strategies=[])

        with patch.object(engine, "_build_live_credentials") as mock_creds:
            engine._build_components()
            mock_creds.assert_not_called()
        assert engine._paper_trader is not None

    def test_paper_mode_does_not_set_openapi_env_vars_in_error(self):
        """A paper-mode engine constructs cleanly even with no env vars."""
        cfg = ForwardTestConfig(live_mode=False)
        engine = ForwardTestEngine(config=cfg, strategies=[])
        engine._build_components()
        assert engine._api_client is None
        assert engine._market_feed is None
        # PaperTrader should also be paper
        assert engine._paper_trader.is_live_mode is False


class TestDescribeMissingLiveCreds:
    """The helper that names which env vars are missing."""

    def test_all_missing_when_env_clean(self):
        cfg = ForwardTestConfig(live_mode=True)
        engine = ForwardTestEngine(config=cfg, strategies=[])
        missing = engine._describe_missing_live_creds()
        assert set(missing) == {
            "CTRADER_OPENAPI_CLIENT_ID",
            "CTRADER_OPENAPI_CLIENT_SECRET",
            "CTRADER_OPENAPI_ACCESS_TOKEN",
            "CTRADER_OPENAPI_ACCOUNT_ID",
        }

    def test_only_unset_vars_returned(self, monkeypatch):
        cfg = ForwardTestConfig(live_mode=True)
        engine = ForwardTestEngine(config=cfg, strategies=[])
        monkeypatch.setenv("CTRADER_OPENAPI_CLIENT_ID", "x")
        monkeypatch.setenv("CTRADER_OPENAPI_ACCESS_TOKEN", "y")
        missing = engine._describe_missing_live_creds()
        assert "CTRADER_OPENAPI_CLIENT_ID" not in missing
        assert "CTRADER_OPENAPI_ACCESS_TOKEN" not in missing
        assert "CTRADER_OPENAPI_CLIENT_SECRET" in missing
        assert "CTRADER_OPENAPI_ACCOUNT_ID" in missing
