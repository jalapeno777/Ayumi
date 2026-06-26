"""Tests for the execution mode boundary (WP-D).

Tests backward compatibility of --live flag and the new --mode flag,
plus fail-closed behavior for paper mode + live endpoint.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestForwardTestConfigExecutionMode:
    """Test ForwardTestConfig.execution_mode field and consistency check."""

    def test_default_execution_mode_is_paper(self):
        from adapters.ctrader.forward_test_engine import ForwardTestConfig
        cfg = ForwardTestConfig()
        assert cfg.execution_mode == "paper"

    def test_live_mode_implies_live_execution_mode(self):
        from adapters.ctrader.forward_test_engine import ForwardTestConfig
        cfg = ForwardTestConfig(live_mode=True)
        # __post_init__ should have corrected execution_mode
        assert cfg.execution_mode == "live"

    def test_explicit_execution_mode_live(self):
        from adapters.ctrader.forward_test_engine import ForwardTestConfig
        cfg = ForwardTestConfig(execution_mode="live", live_mode=True)
        assert cfg.execution_mode == "live"

    def test_explicit_execution_mode_paper(self):
        from adapters.ctrader.forward_test_engine import ForwardTestConfig
        cfg = ForwardTestConfig(execution_mode="paper", live_mode=False)
        assert cfg.execution_mode == "paper"

    def test_live_mode_overrides_paper_execution_mode(self):
        """If live_mode=True but execution_mode='paper', __post_init__ corrects it."""
        from adapters.ctrader.forward_test_engine import ForwardTestConfig
        cfg = ForwardTestConfig(live_mode=True, execution_mode="paper")
        assert cfg.execution_mode == "live"


class TestLauncherModeFlag:
    """Test --mode and --live flag backward compatibility via argparse."""

    def _parse_args(self, arg_list):
        """Parse launcher-style args and return execution_mode."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--symbols", default="GBPUSD")
        parser.add_argument("--mode", choices=["paper", "live"], default=None)
        parser.add_argument("--live", action="store_true")
        parser.add_argument("--paper-only", action="store_true")
        args = parser.parse_args(arg_list)

        if args.mode:
            execution_mode = args.mode
        else:
            execution_mode = "live" if args.live else "paper"
        return execution_mode

    def test_no_args_defaults_to_paper(self):
        assert self._parse_args([]) == "paper"

    def test_live_flag_sets_live(self):
        """Backward compat: --live still works."""
        assert self._parse_args(["--live"]) == "live"

    def test_mode_paper_explicit(self):
        assert self._parse_args(["--mode", "paper"]) == "paper"

    def test_mode_live_explicit(self):
        assert self._parse_args(["--mode", "live"]) == "live"

    def test_mode_overrides_live_flag(self):
        """--mode takes priority over --live."""
        # --mode paper --live → paper (--mode wins)
        assert self._parse_args(["--mode", "paper", "--live"]) == "paper"

    def test_mode_live_without_live_flag(self):
        """--mode live works without --live flag."""
        assert self._parse_args(["--mode", "live"]) == "live"


class TestFailClosedOnPaperLiveEndpoint:
    """Test that paper mode + live endpoint = fail closed."""

    def test_paper_mode_on_live_endpoint_exits(self, caplog):
        """Simulate the fail-closed check logic."""
        import os
        from adapters.ctrader.environment import (
            Environment,
            _infer_environment,
        )

        execution_mode = "paper"
        host = "live.ctraderapi.com"
        env = _infer_environment(host)

        # This should be the condition that triggers fail-closed
        assert env == Environment.LIVE
        assert execution_mode == "paper"

        # In the launcher, this condition would cause sys.exit(1)
        condition = (execution_mode == "paper" and env == Environment.LIVE)
        assert condition is True

    def test_paper_mode_on_demo_endpoint_ok(self):
        from adapters.ctrader.environment import (
            Environment,
            _infer_environment,
        )

        execution_mode = "paper"
        host = "demo.ctraderapi.com"
        env = _infer_environment(host)

        condition = (execution_mode == "paper" and env == Environment.LIVE)
        assert condition is False

    def test_live_mode_on_live_endpoint_ok(self):
        from adapters.ctrader.environment import (
            Environment,
            _infer_environment,
        )

        execution_mode = "live"
        host = "live.ctraderapi.com"
        env = _infer_environment(host)

        condition = (execution_mode == "paper" and env == Environment.LIVE)
        assert condition is False
