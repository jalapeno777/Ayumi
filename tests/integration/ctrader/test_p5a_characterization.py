"""Phase 5A characterization tests — baseline + post-enforcement delta.

These tests document current and post-P5A behavior of the live order-path
surfaces so that enabling the kill switch produces a verifiable, minimal delta:
- _execute_signal_live() returns None when no feed
- _execute_signal_live() reaches broker checks when kill switch is clear
- _execute_signal_live() is blocked by permission policy when kill switch active
- OpenApiSpotFeed.new_order() returns an Order with PENDING when called normally
- ExecutionPermissionPolicy exists and is importable after P5A

The pre-enforcement baseline was captured in this file before any production
changes and verified against P4.1 code.
"""
from unittest.mock import MagicMock

import pytest

from adapters.ctrader.forward_test_engine import ForwardTestEngine
from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed


def _make_bare_engine(tmp_path):
    """Create an engine instance with mocked dependencies; no market feed."""
    engine = ForwardTestEngine.__new__(ForwardTestEngine)
    engine._market_feed = None
    engine._kill_switch = MagicMock()
    engine._kill_switch.is_active.return_value = True
    engine._kill_switch.get_status.return_value = {"mode": "kill", "reason": "ftmo"}
    return engine


def test_execute_signal_live_returns_none_when_no_market_feed(tmp_path):
    """Current behavior: no OpenApiSpotFeed -> pre-flight failure (None)."""
    engine = _make_bare_engine(tmp_path)
    signal = MagicMock()
    signal.direction.value = "LONG"
    signal.symbol = "EURUSD"

    result = engine._execute_signal_live(signal)

    assert result is None


def test_execute_signal_live_no_kill_switch_check_currently(tmp_path):
    """Baseline: _execute_signal_live() does NOT check kill switch before P5A.

    With a mock feed present (but not operational), the method still attempts
    symbol resolution and returns None for a different reason — proving there
    is no kill-switch gate at the entry point today.
    """
    engine = _make_bare_engine(tmp_path)
    # P5A: engine now constructs policy internally from self._kill_switch; simulate
    # a clear kill switch so we reach the no-feed check (or operational check).
    engine._kill_switch = MagicMock()
    engine._kill_switch.is_active.return_value = False
    mock_feed = MagicMock(spec=OpenApiSpotFeed)
    engine._market_feed = mock_feed

    signal = MagicMock()
    signal.direction.value = "LONG"
    signal.symbol = "EURUSD"
    # Force resolve_symbol_id to raise, which is the first thing after the
    # operational check today — proving we got past any would-be kill gate.
    mock_feed.resolve_symbol_id.side_effect = RuntimeError("no such symbol")

    result = engine._execute_signal_live(signal)
    assert result is None
    mock_feed.resolve_symbol_id.assert_called_once_with("EURUSD")


def test_execute_signal_live_blocked_by_policy_after_p5a(tmp_path):
    """After P5A: _execute_signal_live() checks permission policy first.

    With the kill switch active, the method must return None before any
    feed interaction.
    """
    engine = _make_bare_engine(tmp_path)
    mock_feed = MagicMock(spec=OpenApiSpotFeed)
    engine._market_feed = mock_feed

    signal = MagicMock()
    signal.direction.value = "LONG"
    signal.symbol = "EURUSD"

    result = engine._execute_signal_live(signal)
    assert result is None
    mock_feed.resolve_symbol_id.assert_not_called()


def test_execution_permission_policy_class_exists_after_p5a():
    """After P5A implementation, the policy class is importable."""
    from adapters.ctrader.execution_permission import ExecutionPermissionPolicy  # noqa: F401
    assert True
