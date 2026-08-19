"""Integration tests for P5A kill switch enforcement.

Verifies two-layer gating:
1. ExecutionPermissionPolicy blocks at OpenApiSpotFeed.new_order().
2. ForwardTestEngine._execute_signal_live() blocks before broker interaction.
"""

from unittest.mock import MagicMock, patch
from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed
from adapters.ctrader.execution_permission import ExecutionPermissionPolicy


def test_new_order_blocked_by_policy():
    """The killer test: policy denies → order never reaches broker."""
    feed = OpenApiSpotFeed(
        ctid_account_id=12345,
        client_id="x",
        client_secret="x",
        access_token="x",
        refresh_token="x",
        host="demo.ctraderapi.com",
        port=5035,
        token_lifecycle=MagicMock(),
    )
    policy = ExecutionPermissionPolicy(kill_switch=None)  # → DENY
    feed.set_permission_policy(policy)

    # Patch volume calc so the rejection path can build the rejected Order
    # object without needing a registered symbol. The symbol is irrelevant to
    # the policy check we are testing.
    with patch.object(feed._volume_calc, "volume_to_lots", return_value=1.0):
        order = feed.new_order(symbol_id=1, side="BUY", volume=1000)
    assert order.status.value == "rejected" or hasattr(order, "reason")
    assert "not_initialized" in getattr(order, "reason", "")


def test_new_order_allowed_when_policy_clear():
    """When policy allows, order construction proceeds normally."""
    feed = OpenApiSpotFeed(
        ctid_account_id=12345,
        client_id="x",
        client_secret="x",
        access_token="x",
        refresh_token="x",
        host="demo.ctraderapi.com",
        port=5035,
        token_lifecycle=MagicMock(),
    )
    mock_ks = MagicMock()
    mock_ks.is_active.return_value = False
    policy = ExecutionPermissionPolicy(kill_switch=mock_ks)
    feed.set_permission_policy(policy)

    # Without connection, we can't fully test order construction,
    # but we can verify the policy check passes (doesn't reject as DENY).
    # Any exception must be connection-related, NOT policy-related.
    with patch.object(feed, "_state_mgr") as mock_state:
        mock_state.is_operational = True
        try:
            result = feed.new_order(symbol_id=1, side="BUY", volume=1000)
            # If we got a result back, it must NOT be a policy rejection.
            # "not_connected" is acceptable — we have no real broker connection.
            # But "not_initialized" or explicit DENY is a policy bug.
            if hasattr(result, "status") and result.status.value == "rejected":
                reason = getattr(result, "reason", "") or getattr(result, "comment", "")
                assert "not_initialized" not in reason, (
                    f"Policy incorrectly DENIED — kill switch was inactive but got: {reason}"
                )
        except Exception as e:
            # Expected — no real connection. But must NOT be policy-related.
            err_str = str(e).lower()
            assert "not_initialized" not in err_str, (
                f"Policy blocked order despite inactive kill switch: {e}"
            )


# ------------------------------------------------------------------
# Phase 6: Dual-instance policy injection test
# ------------------------------------------------------------------


def test_api_client_has_policy_after_build_components():
    """After _build_components() in live mode, _api_client must have policy set."""
    from adapters.ctrader.forward_test_engine import (
        ForwardTestEngine,
        ForwardTestConfig,
    )

    cfg = ForwardTestConfig(
        symbols=["EURUSD"],
        live_mode=True,
        openapi_host="demo.ctraderapi.com",
        openapi_port=5035,
    )

    mock_lifecycle = MagicMock()
    mock_lifecycle.ensure_valid.return_value = "***"
    live_creds = {
        "ctid_account_id": 12345,
        "client_id": "test_id",
        "client_secret": "test_secret",
        "access_token": "test_token",
        "refresh_token": "test_refresh",
        "host": "demo.ctraderapi.com",
        "port": 5035,
        "token_lifecycle": mock_lifecycle,
    }

    engine = ForwardTestEngine(config=cfg, strategies=[])

    with (
        patch.object(engine, "_build_live_credentials", return_value=live_creds),
        patch(
            "adapters.ctrader.forward_test_engine.cTraderAPIClient"
        ) as mock_client_cls,
        patch("adapters.ctrader.forward_test_engine.OpenApiSpotFeed") as mock_feed_cls,
        patch("adapters.ctrader.forward_test_engine.PaperTrader") as mock_paper_cls,
        patch("adapters.ctrader.forward_test_engine.cTraderLiveAdapter"),
        patch("adapters.ctrader.forward_test_engine.TradeLogger"),
    ):
        mock_feed = MagicMock()
        mock_feed_cls.return_value = mock_feed
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_paper = MagicMock()
        mock_paper_cls.return_value = mock_paper

        engine._build_components()

        # Verify both instances received set_permission_policy with same policy.
        mock_feed.set_permission_policy.assert_called_once()
        mock_client.set_permission_policy.assert_called_once()
        feed_policy = mock_feed.set_permission_policy.call_args[0][0]
        client_policy = mock_client.set_permission_policy.call_args[0][0]
        assert feed_policy is client_policy, (
            "_market_feed and _api_client must share the same policy instance"
        )
        assert client_policy is not None, (
            "_api_client._permission_policy must be set after _build_components()"
        )
