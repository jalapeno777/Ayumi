"""Tests for ForwardTestEngine quote credential wiring (AYUAA-776)."""

import os
import unittest
from unittest.mock import patch

from adapters.ctrader.forward_test_engine import ForwardTestConfig, ForwardTestEngine


class TestForwardTestEngineQuoteCredentials(unittest.TestCase):
    def _make_config(self, **overrides) -> ForwardTestConfig:
        defaults = dict(
            symbol="GBPUSD",
            quote_host="test.host.com",
            quote_port=5211,
            quote_sender_sub_id="QUOTE",
        )
        defaults.update(overrides)
        return ForwardTestConfig(**defaults)

    def setUp(self):
        self._env_backup = {}
        for key in [
            "CTRADER_HOST",
            "CTRADER_SSL_PORT",
            "CTRADER_SENDER_COMP_ID",
            "CTRADER_TARGET_COMP_ID",
            "CTRADER_QUOTE_SENDER_SUB_ID",
            "CTRADER_QUOTE_TARGET_SUB_ID",
            "CTRADER_ACCOUNT",
            "CTRADER_PASSWORD",
        ]:
            if key in os.environ:
                self._env_backup[key] = os.environ.pop(key)

    def tearDown(self):
        for key, val in self._env_backup.items():
            os.environ[key] = val
        for key in list(self._env_backup.keys()):
            os.environ.pop(key, None)

    def test_default_sender_sub_id_is_quote(self):
        config = self._make_config()
        engine = ForwardTestEngine(config=config, strategies=[])
        creds = engine._build_quote_credentials()
        assert creds.sender_sub_id == "QUOTE"

    def test_env_override_sender_sub_id(self):
        os.environ["CTRADER_QUOTE_SENDER_SUB_ID"] = "CUSTOM"
        config = self._make_config()
        engine = ForwardTestEngine(config=config, strategies=[])
        creds = engine._build_quote_credentials()
        assert creds.sender_sub_id == "CUSTOM"

    def test_target_sub_id_defaults_to_sender_sub_id(self):
        config = self._make_config()
        engine = ForwardTestEngine(config=config, strategies=[])
        creds = engine._build_quote_credentials()
        assert creds.target_sub_id == "QUOTE"

    def test_env_override_target_sub_id(self):
        os.environ["CTRADER_QUOTE_TARGET_SUB_ID"] = "Q_TARGET"
        config = self._make_config()
        engine = ForwardTestEngine(config=config, strategies=[])
        creds = engine._build_quote_credentials()
        assert creds.target_sub_id == "Q_TARGET"

    def test_config_override_sender_sub_id(self):
        config = self._make_config(quote_sender_sub_id="MYQUOTE")
        engine = ForwardTestEngine(config=config, strategies=[])
        creds = engine._build_quote_credentials()
        assert creds.sender_sub_id == "MYQUOTE"

    def test_config_override_target_sub_id(self):
        config = self._make_config(
            quote_sender_sub_id="MYQUOTE",
            quote_target_sub_id="MYQTARGET",
        )
        engine = ForwardTestEngine(config=config, strategies=[])
        creds = engine._build_quote_credentials()
        assert creds.sender_sub_id == "MYQUOTE"
        assert creds.target_sub_id == "MYQTARGET"

    def test_env_takes_priority_over_config(self):
        os.environ["CTRADER_QUOTE_SENDER_SUB_ID"] = "ENV_QUOTE"
        config = self._make_config(quote_sender_sub_id="CFG_QUOTE")
        engine = ForwardTestEngine(config=config, strategies=[])
        creds = engine._build_quote_credentials()
        assert creds.sender_sub_id == "ENV_QUOTE"

    def test_host_from_env(self):
        os.environ["CTRADER_HOST"] = "env.host.com"
        os.environ["CTRADER_ACCOUNT"] = "12345"
        os.environ["CTRADER_PASSWORD"] = "pw"
        config = self._make_config()
        engine = ForwardTestEngine(config=config, strategies=[])
        creds = engine._build_quote_credentials()
        assert creds.host == "env.host.com"

    def test_host_falls_back_to_config(self):
        os.environ["CTRADER_ACCOUNT"] = "12345"
        os.environ["CTRADER_PASSWORD"] = "pw"
        config = self._make_config(quote_host="fallback.host.com")
        engine = ForwardTestEngine(config=config, strategies=[])
        with patch("dotenv.load_dotenv"):
            creds = engine._build_quote_credentials()
        assert creds.host == "fallback.host.com"


class TestForwardTestConfigDefaults(unittest.TestCase):
    def test_quote_sender_sub_id_default(self):
        cfg = ForwardTestConfig()
        assert cfg.quote_sender_sub_id == "QUOTE"

    def test_quote_target_sub_id_default_none(self):
        cfg = ForwardTestConfig()
        assert cfg.quote_target_sub_id is None

    def test_quote_port_default(self):
        cfg = ForwardTestConfig()
        assert cfg.quote_port == 5211

    def test_use_ssl_default(self):
        cfg = ForwardTestConfig()
        assert cfg.use_ssl is True
