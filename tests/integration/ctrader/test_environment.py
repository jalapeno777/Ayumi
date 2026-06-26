"""Tests for the cTrader environment model (WP-C)."""

import logging
import pytest

from adapters.ctrader.environment import (
    Environment,
    DEMO_HOSTS,
    LIVE_HOSTS,
    _infer_environment,
    validate_endpoint_environment,
    log_startup_environment,
)


# ── Environment.from_string ─────────────────────────────────────────────


class TestEnvironmentFromString:
    def test_demo(self):
        assert Environment.from_string("demo") == Environment.DEMO

    def test_live(self):
        assert Environment.from_string("live") == Environment.LIVE

    def test_offline(self):
        assert Environment.from_string("offline") == Environment.OFFLINE

    def test_practice_alias(self):
        assert Environment.from_string("practice") == Environment.DEMO

    def test_production_alias(self):
        assert Environment.from_string("production") == Environment.LIVE

    def test_real_alias(self):
        assert Environment.from_string("real") == Environment.LIVE

    def test_paper_alias(self):
        assert Environment.from_string("paper") == Environment.OFFLINE

    def test_case_insensitive(self):
        assert Environment.from_string("DEMO") == Environment.DEMO
        assert Environment.from_string("Live") == Environment.LIVE

    def test_whitespace_stripped(self):
        assert Environment.from_string("  demo  ") == Environment.DEMO

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown environment"):
            Environment.from_string("staging")


# ── Environment properties ──────────────────────────────────────────────


class TestEnvironmentProperties:
    def test_is_demo(self):
        assert Environment.DEMO.is_demo
        assert not Environment.LIVE.is_demo
        assert not Environment.OFFLINE.is_demo

    def test_is_live(self):
        assert Environment.LIVE.is_live
        assert not Environment.DEMO.is_live
        assert not Environment.OFFLINE.is_live

    def test_is_offline(self):
        assert Environment.OFFLINE.is_offline
        assert not Environment.DEMO.is_offline
        assert not Environment.LIVE.is_offline


# ── _infer_environment ──────────────────────────────────────────────────


class TestInferEnvironment:
    def test_demo_host(self):
        assert _infer_environment("demo.ctraderapi.com") == Environment.DEMO

    def test_demo_uk_host(self):
        assert _infer_environment("demo-uk-eqx-01.p.c-trader.com") == Environment.DEMO

    def test_live_host(self):
        assert _infer_environment("live.ctraderapi.com") == Environment.LIVE

    def test_live_uk_host(self):
        assert _infer_environment("live-uk-eqx-01.p.c-trader.com") == Environment.LIVE

    def test_unknown_host_is_offline(self):
        assert _infer_environment("localhost") == Environment.OFFLINE
        assert _infer_environment("some-random-host.com") == Environment.OFFLINE

    def test_case_insensitive(self):
        assert _infer_environment("DEMO.CTRADERAPI.COM") == Environment.DEMO
        assert _infer_environment("LIVE.CTRADERAPI.COM") == Environment.LIVE


# ── validate_endpoint_environment ───────────────────────────────────────


class TestValidateEndpointEnvironment:
    def test_demo_host_demo_env_passes(self):
        validate_endpoint_environment("demo.ctraderapi.com", Environment.DEMO)

    def test_live_host_live_env_passes(self):
        validate_endpoint_environment("live.ctraderapi.com", Environment.LIVE)

    def test_demo_host_live_env_raises(self):
        with pytest.raises(ValueError, match="Live environment.*demo endpoint"):
            validate_endpoint_environment("demo.ctraderapi.com", Environment.LIVE)

    def test_live_host_demo_env_raises(self):
        with pytest.raises(ValueError, match="Demo environment.*live endpoint"):
            validate_endpoint_environment("live.ctraderapi.com", Environment.DEMO)

    def test_unknown_host_passes_no_false_positive(self):
        # Unknown hosts should not trigger false positives
        validate_endpoint_environment("localhost", Environment.DEMO)
        validate_endpoint_environment("localhost", Environment.LIVE)

    def test_offline_env_no_check_needed(self):
        # OFFLINE never connects, so any host should be fine
        validate_endpoint_environment("live.ctraderapi.com", Environment.OFFLINE)
        validate_endpoint_environment("demo.ctraderapi.com", Environment.OFFLINE)


# ── log_startup_environment ─────────────────────────────────────────────


class TestLogStartupEnvironment:
    def test_does_not_log_secrets(self, caplog):
        caplog.set_level(logging.INFO, logger="ayumi.ctrader.environment")
        log_startup_environment(
            env=Environment.DEMO,
            host="demo.ctraderapi.com",
            account_id="12345",
            kill_switch_active=True,
            kill_switch_mode="freeze",
        )
        record = [r for r in caplog.records if r.name == "ayumi.ctrader.environment"]
        assert len(record) == 1
        msg = record[0].getMessage()
        assert "demo" in msg
        assert "demo.ctraderapi.com" in msg
        assert "12345" in msg
        assert "freeze" in msg
        # Ensure no secret-like fields appear
        assert "access_token" not in msg.lower()
        assert "refresh_token" not in msg.lower()
        assert "client_secret" not in msg.lower()
        assert "password" not in msg.lower()

    def test_logs_correct_mode(self, caplog):
        caplog.set_level(logging.INFO, logger="ayumi.ctrader.environment")
        log_startup_environment(
            env=Environment.LIVE,
            host="live.ctraderapi.com",
            account_id="999",
            kill_switch_active=False,
            kill_switch_mode="inactive",
        )
        record = [r for r in caplog.records if r.name == "ayumi.ctrader.environment"]
        msg = record[0].getMessage()
        assert "mode=live" in msg
        assert "kill_switch=inactive" in msg
