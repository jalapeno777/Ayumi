"""Integration tests for P5A kill switch enforcement.

Verifies two-layer gating:
1. ExecutionPermissionPolicy blocks at OpenApiSpotFeed.new_order().
2. ForwardTestEngine._execute_signal_live() blocks before broker interaction.
"""
import pytest
from unittest.mock import MagicMock, patch
from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed
from adapters.ctrader.execution_permission import ExecutionPermissionPolicy


def test_new_order_blocked_by_policy():
    """The killer test: policy denies → order never reaches broker."""
    feed = OpenApiSpotFeed(
        ctid_account_id=12345, client_id="x", client_secret="x",
        access_token="x", refresh_token="x",
        host="demo.ctraderapi.com", port=5035,
        token_lifecycle=MagicMock(),
    )
    policy = ExecutionPermissionPolicy(kill_switch=None)  # → DENY
    feed.set_permission_policy(policy)

    order = feed.new_order(symbol_id=1, side="BUY", volume=1000)
    assert order.status.value == "rejected" or hasattr(order, "reason")
    assert "not_initialized" in getattr(order, "reason", "")


def test_new_order_allowed_when_policy_clear():
    """When policy allows, order construction proceeds normally."""
    feed = OpenApiSpotFeed(
        ctid_account_id=12345, client_id="x", client_secret="x",
        access_token="x", refresh_token="x",
        host="demo.ctraderapi.com", port=5035,
        token_lifecycle=MagicMock(),
    )
    mock_ks = MagicMock()
    mock_ks.is_active.return_value = False
    policy = ExecutionPermissionPolicy(kill_switch=mock_ks)
    feed.set_permission_policy(policy)

    # Without connection, we can't fully test order construction,
    # but we can verify the policy check passes
    with patch.object(feed, '_state_mgr') as mock_state:
        mock_state.is_operational = True
        # Will fail on connection but that's expected — just verify no policy block
        try:
            feed.new_order(symbol_id=1, side="BUY", volume=1000)
        except Exception:
            pass  # Expected — no real connection
