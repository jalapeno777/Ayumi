"""Unit tests for ExecutionPermissionPolicy (P5A).

Covers the three critical safety properties:
1. Default DENY for every uncertain state.
2. Uses KillSwitchManager.is_active() (not mode-specific caches).
3. Never propagates exceptions.
"""

from unittest.mock import MagicMock

from adapters.ctrader.execution_permission import ExecutionPermissionPolicy
from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed


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


# ------------------------------------------------------------------
# Phase 6: Broker-mutating gate tests
# ------------------------------------------------------------------


def test_cancel_order_blocked_by_policy():
    """cancel_order must return False without broker communication when kill switch is active."""
    feed = OpenApiSpotFeed(
        ctid_account_id=12345,
        client_id="x",
        client_secret="x",  # noqa: S106
        access_token="x",  # noqa: S106
        refresh_token="x",  # noqa: S106
        host="demo.ctraderapi.com",
        port=5035,
        token_lifecycle=MagicMock(),
    )
    mock_ks = MagicMock()
    mock_ks.is_active.return_value = True
    mock_ks.get_status.return_value = {"mode": "kill", "reason": "ftfo"}
    policy = ExecutionPermissionPolicy(kill_switch=mock_ks)
    feed.set_permission_policy(policy)

    result = feed.cancel_order(order_id=99999)
    assert result is False


def test_close_position_blocked_by_policy():
    """close_position must return False without broker communication when kill switch is active."""
    feed = OpenApiSpotFeed(
        ctid_account_id=12345,
        client_id="x",
        client_secret="x",  # noqa: S106
        access_token="x",  # noqa: S106
        refresh_token="x",  # noqa: S106
        host="demo.ctraderapi.com",
        port=5035,
        token_lifecycle=MagicMock(),
    )
    mock_ks = MagicMock()
    mock_ks.is_active.return_value = True
    mock_ks.get_status.return_value = {"mode": "kill", "reason": "ftfo"}
    policy = ExecutionPermissionPolicy(kill_switch=mock_ks)
    feed.set_permission_policy(policy)

    result = feed.close_position(position_id=99999, volume=1000)
    assert result is False
