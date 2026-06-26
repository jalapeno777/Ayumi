"""Unit tests for ExecutionPermissionPolicy (P5A).

Covers the three critical safety properties:
1. Default DENY for every uncertain state.
2. Uses KillSwitchManager.is_active() (not mode-specific caches).
3. Never propagates exceptions.
"""
import pytest
from unittest.mock import MagicMock
from adapters.ctrader.execution_permission import ExecutionPermissionPolicy


def test_policy_denies_when_kill_switch_none():
    policy = ExecutionPermissionPolicy(kill_switch=None)
    allowed, reason = policy.can_send_order()
    assert allowed is False
    assert "not_initialized" in reason


def test_policy_denies_when_kill_switch_active():
    mock_ks = MagicMock()
    mock_ks.is_active.return_value = True
    mock_ks.get_status.return_value = {"mode": "kill", "reason": "ftmo"}
    policy = ExecutionPermissionPolicy(kill_switch=mock_ks)
    allowed, reason = policy.can_send_order()
    assert allowed is False
    assert "kill" in reason


def test_policy_allows_when_clear():
    mock_ks = MagicMock()
    mock_ks.is_active.return_value = False
    policy = ExecutionPermissionPolicy(kill_switch=mock_ks)
    allowed, reason = policy.can_send_order()
    assert allowed is True
    assert reason == "clear"


def test_policy_denies_on_is_active_exception():
    mock_ks = MagicMock()
    mock_ks.is_active.side_effect = RuntimeError("state corrupted")
    policy = ExecutionPermissionPolicy(kill_switch=mock_ks)
    allowed, reason = policy.can_send_order()
    assert allowed is False
    assert "policy_error" in reason


def test_policy_denies_on_constructor_exception():
    mock_ks = MagicMock()
    mock_ks.get_status.side_effect = KeyError("missing mode")
    mock_ks.is_active.return_value = True
    policy = ExecutionPermissionPolicy(kill_switch=mock_ks)
    allowed, reason = policy.can_send_order()
    assert allowed is False


def test_policy_uses_is_active_not_globally_killed():
    """Rei's blocker: must use is_active() to cover both KILL and FREEZE."""
    mock_ks = MagicMock()
    mock_ks.is_active.return_value = True
    mock_ks.is_globally_killed.return_value = False  # cache says no
    mock_ks.is_globally_frozen.return_value = False  # cache says no
    mock_ks.get_status.return_value = {"mode": "freeze"}
    policy = ExecutionPermissionPolicy(kill_switch=mock_ks)
    allowed, reason = policy.can_send_order()
    assert allowed is False, "Must use is_active(), not mode-specific caches"
    assert "freeze" in reason
