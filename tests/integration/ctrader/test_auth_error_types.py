"""Tests for centralized auth error classification (WP-B)."""

import pytest
from unittest.mock import MagicMock, patch

from adapters.ctrader.auth_error_types import (
    AuthFaultType,
    AuthFaultPolicy,
    ERROR_CLASSIFICATIONS,
    POLICIES,
    classify_error,
    get_policy,
)


# ── Unit tests: classification buckets ─────────────────────────────────────


class TestClassifyError:
    def test_refreshable_token_expiry(self):
        """CH_OAUTH_TOKEN_EXPIRED → REFRESHABLE_TOKEN_FAULT."""
        ft = classify_error("CH_OAUTH_TOKEN_EXPIRED")
        assert ft == AuthFaultType.REFRESHABLE_TOKEN_FAULT

    def test_invalid_token_refreshable(self):
        """CH_INVALID_TOKEN → REFRESHABLE_TOKEN_FAULT."""
        ft = classify_error("CH_INVALID_TOKEN")
        assert ft == AuthFaultType.REFRESHABLE_TOKEN_FAULT

    def test_session_expired_refreshable(self):
        """SESSION_EXPIRED → REFRESHABLE_TOKEN_FAULT."""
        ft = classify_error("SESSION_EXPIRED")
        assert ft == AuthFaultType.REFRESHABLE_TOKEN_FAULT

    def test_access_denied_no_refresh(self):
        """ACCESS_DENIED → PERMISSION_OR_ACCESS_DENIED (no refresh)."""
        ft = classify_error("ACCESS_DENIED")
        assert ft == AuthFaultType.PERMISSION_OR_ACCESS_DENIED
        policy = POLICIES[ft]
        assert policy.can_refresh is False
        assert policy.requires_escalation is True

    def test_invalid_request_no_refresh(self):
        """INVALID_REQUEST → MALFORMED_REQUEST (no refresh)."""
        ft = classify_error("INVALID_REQUEST")
        assert ft == AuthFaultType.MALFORMED_REQUEST
        policy = POLICIES[ft]
        assert policy.can_refresh is False
        assert policy.requires_escalation is True

    def test_account_not_authorized_kill_switch(self):
        """CH_ACCOUNT_NOT_AUTHORIZED → activate_kill_switch=True."""
        ft = classify_error("CH_ACCOUNT_NOT_AUTHORIZED")
        assert ft == AuthFaultType.ACCOUNT_AUTHORIZATION_FAULT
        policy = POLICIES[ft]
        assert policy.activate_kill_switch is True
        assert policy.can_refresh is False

    def test_trading_account_not_authorized(self):
        """CH_TRADING_ACCOUNT_NOT_AUTHORIZED → ACCOUNT_AUTHORIZATION_FAULT."""
        ft = classify_error("CH_TRADING_ACCOUNT_NOT_AUTHORIZED")
        assert ft == AuthFaultType.ACCOUNT_AUTHORIZATION_FAULT
        policy = POLICIES[ft]
        assert policy.activate_kill_switch is True

    def test_unknown_code_with_access_denied_description(self):
        """Unknown code with 'access denied' in description → PERMISSION_OR_ACCESS_DENIED."""
        ft = classify_error("SOME_NEW_CODE", "User access denied for resource")
        assert ft == AuthFaultType.PERMISSION_OR_ACCESS_DENIED

    def test_unknown_code_with_not_authorized_description(self):
        """Unknown code with 'not authorized' → ACCOUNT_AUTHORIZATION_FAULT."""
        ft = classify_error("WEIRD_ERROR", "Account is not authorized for trading")
        assert ft == AuthFaultType.ACCOUNT_AUTHORIZATION_FAULT

    def test_unknown_code_with_malformed_description(self):
        """Unknown code with 'malformed' → MALFORMED_REQUEST."""
        ft = classify_error("WEIRD_ERROR", "Request was malformed")
        assert ft == AuthFaultType.MALFORMED_REQUEST

    def test_unknown_code_with_timeout_description(self):
        """Unknown code with 'timeout' → TRANSIENT_CONNECTION_FAULT."""
        ft = classify_error("WEIRD_ERROR", "Connection timeout")
        assert ft == AuthFaultType.TRANSIENT_CONNECTION_FAULT

    def test_unknown_fatal(self):
        """Truly unknown code → UNKNOWN_FATAL_AUTH_FAULT."""
        ft = classify_error("COMPLETELY_UNKNOWN_CODE")
        assert ft == AuthFaultType.UNKNOWN_FATAL_AUTH_FAULT

    def test_transient_connection_can_reconnect(self):
        """Transient connection fault → can_reconnect=True."""
        ft = classify_error("WEIRD_ERROR", "Server unreachable")
        assert ft == AuthFaultType.TRANSIENT_CONNECTION_FAULT
        policy = POLICIES[ft]
        assert policy.can_reconnect is True
        assert policy.can_refresh is False


class TestGetPolicy:
    def test_get_policy_returns_matching_tuple(self):
        """get_policy() returns (fault_type, policy) matching POLICIES."""
        ft, policy = get_policy("CH_OAUTH_TOKEN_EXPIRED")
        assert ft == AuthFaultType.REFRESHABLE_TOKEN_FAULT
        assert policy is POLICIES[ft]
        assert policy.can_refresh is True

    def test_get_policy_access_denied(self):
        """get_policy for ACCESS_DENIED returns no-refresh policy."""
        ft, policy = get_policy("ACCESS_DENIED")
        assert policy.can_refresh is False
        assert policy.requires_escalation is True

    def test_get_policy_with_description(self):
        """get_policy uses description for heuristic classification."""
        ft, policy = get_policy("UNKNOWN_X", "timeout detected")
        assert ft == AuthFaultType.TRANSIENT_CONNECTION_FAULT
        assert policy.can_reconnect is True


class TestAuthFaultPolicy:
    def test_should_fail_closed_default(self):
        """Default policy (no orders allowed) fails closed."""
        policy = AuthFaultPolicy()
        assert policy.should_fail_closed is True

    def test_should_fail_closed_when_orders_allowed(self):
        """Policy with can_send_orders=True does not fail closed."""
        policy = AuthFaultPolicy(can_send_orders=True)
        assert policy.should_fail_closed is False

    def test_all_policies_fail_closed_for_orders(self):
        """No policy in the table allows order sending."""
        for ft, policy in POLICIES.items():
            assert policy.can_send_orders is False, f"{ft} should not allow orders"


# ── Integration tests: wiring into OpenApiSpotFeed ─────────────────────────


class TestSpotFeedErrorWiring:
    """Test that the spot feed uses the classification system correctly."""

    def _make_feed(self):
        """Create a minimal mock feed with the _handle_error method."""
        from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed

        feed = OpenApiSpotFeed.__new__(OpenApiSpotFeed)
        feed._auth_circuit_open = False
        feed._refresh_in_progress = False
        feed._last_reactive_refresh_time = 0.0
        feed._token_lifecycle = None
        feed._auth_error_count = 0
        return feed

    @patch("adapters.ctrader.open_api_spot_feed.logger")
    def test_token_expired_triggers_refresh(self, mock_logger):
        """CH_OAUTH_TOKEN_EXPIRED triggers the refresh path."""
        feed = self._make_feed()

        msg = MagicMock()
        msg.errorCode = "CH_OAUTH_TOKEN_EXPIRED"
        msg.description = "Token expired"

        with patch.object(feed, "_refresh_token_and_reauth") as mock_refresh:
            feed._handle_error(msg)
            mock_refresh.assert_called_once()

    @patch("adapters.ctrader.open_api_spot_feed.logger")
    def test_access_denied_does_not_trigger_refresh(self, mock_logger):
        """ACCESS_DENIED does NOT trigger refresh — fails closed."""
        feed = self._make_feed()

        msg = MagicMock()
        msg.errorCode = "ACCESS_DENIED"
        msg.description = "Access denied"

        with patch.object(feed, "_refresh_token_and_reauth") as mock_refresh:
            feed._handle_error(msg)
            mock_refresh.assert_not_called()

    @patch("adapters.ctrader.open_api_spot_feed.logger")
    def test_invalid_request_does_not_trigger_refresh(self, mock_logger):
        """INVALID_REQUEST does NOT trigger refresh."""
        feed = self._make_feed()

        msg = MagicMock()
        msg.errorCode = "INVALID_REQUEST"
        msg.description = "Invalid request"

        with patch.object(feed, "_refresh_token_and_reauth") as mock_refresh:
            feed._handle_error(msg)
            mock_refresh.assert_not_called()

    @patch("adapters.ctrader.open_api_spot_feed.logger")
    def test_account_not_authorized_does_not_trigger_refresh(self, mock_logger):
        """CH_ACCOUNT_NOT_AUTHORIZED does NOT trigger refresh."""
        feed = self._make_feed()

        msg = MagicMock()
        msg.errorCode = "CH_ACCOUNT_NOT_AUTHORIZED"
        msg.description = "Account not authorized"

        with patch.object(feed, "_refresh_token_and_reauth") as mock_refresh:
            feed._handle_error(msg)
            mock_refresh.assert_not_called()

    @patch("adapters.ctrader.open_api_spot_feed.logger")
    def test_kill_switch_recommended_for_account_fault(self, mock_logger):
        """Account authorization fault logs kill switch recommendation."""
        feed = self._make_feed()

        msg = MagicMock()
        msg.errorCode = "CH_ACCOUNT_NOT_AUTHORIZED"
        msg.description = "Account not authorized"

        feed._handle_error(msg)

        # Check that kill switch recommendation was logged
        error_calls = [str(c) for c in mock_logger.error.call_args_list]
        assert any("kill switch" in c.lower() or "Kill switch" in c for c in error_calls), \
            f"Expected kill switch log, got: {error_calls}"

    @patch("adapters.ctrader.open_api_spot_feed.logger")
    def test_already_logged_in_short_circuits(self, mock_logger):
        """ALREADY_LOGGED_IN sets authed and does not classify."""
        feed = self._make_feed()
        feed._authed = MagicMock()

        msg = MagicMock()
        msg.errorCode = "ALREADY_LOGGED_IN"

        with patch.object(feed, "_refresh_token_and_reauth") as mock_refresh:
            feed._handle_error(msg)
            mock_refresh.assert_not_called()
