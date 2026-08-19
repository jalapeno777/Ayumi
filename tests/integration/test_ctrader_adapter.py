"""Tests for cTrader adapter fixes applied in BQ-1327.

Verifies the three archived fixes are present in the live code:
1. setDisconnectedCallback support
2. _APP_AUTH_RES_PAYLOAD_TYPE / _ACCT_AUTH_RES_PAYLOAD_TYPE constants
3. _reauth_in_progress guard preventing concurrent auth races
"""

import threading
from unittest.mock import MagicMock, patch

import pytest


# ── Module-level constant verification ───────────────────────────────────


class TestAuthPayloadConstants:
    """BQ-1327 Fix 2: Auth payload type constants must exist with correct values."""

    def test_app_auth_res_payload_type(self):
        from adapters.ctrader.open_api_client import _APP_AUTH_RES_PAYLOAD_TYPE

        assert _APP_AUTH_RES_PAYLOAD_TYPE == 2101

    def test_acct_auth_res_payload_type(self):
        from adapters.ctrader.open_api_client import _ACCT_AUTH_RES_PAYLOAD_TYPE

        assert _ACCT_AUTH_RES_PAYLOAD_TYPE == 2103

    def test_spot_feed_reexports_app_auth_constant(self):
        """The shim should re-export the constant for consumers."""
        from adapters.ctrader.open_api_spot_feed import _APP_AUTH_RES_PAYLOAD_TYPE

        assert _APP_AUTH_RES_PAYLOAD_TYPE == 2101

    def test_spot_feed_reexports_acct_auth_constant(self):
        from adapters.ctrader.open_api_spot_feed import _ACCT_AUTH_RES_PAYLOAD_TYPE

        assert _ACCT_AUTH_RES_PAYLOAD_TYPE == 2103


# ── _reauth_in_progress guard ────────────────────────────────────────────


class TestReauthGuard:
    """BQ-1327 Fix 3: _reauth_in_progress guard prevents concurrent auth races."""

    def test_guard_exists_as_event(self):
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        assert isinstance(client._reauth_in_progress, threading.Event)

    def test_guard_clear_on_init(self):
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        assert not client._reauth_in_progress.is_set()

    def test_connect_returns_true_if_already_connected(self):
        """If already connected, connect() should short-circuit without racing."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        client._connected = True
        assert client.connect() is True

    def test_connect_waits_if_reauth_in_progress(self):
        """If reauth is already underway, second connect() should wait and return."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        client._reauth_in_progress.set()
        # Should timeout waiting and return False (not raise or race)
        assert client.connect() is False

    def test_guard_cleared_on_disconnect(self):
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        client._reauth_in_progress.set()
        client.disconnect()
        assert not client._reauth_in_progress.is_set()

    def test_guard_cleared_after_successful_connect(self):
        """Guard should be cleared in the finally block after connect completes."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        # Mock _do_connect to succeed
        client._do_connect = MagicMock(return_value=True)
        result = client.connect()
        assert result is True
        client._do_connect.assert_called_once()
        assert not client._reauth_in_progress.is_set()

    def test_guard_cleared_after_failed_connect(self):
        """Guard should be cleared even if connect fails."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        client._do_connect = MagicMock(return_value=False)
        result = client.connect()
        assert result is False
        assert not client._reauth_in_progress.is_set()

    def test_guard_cleared_after_exception(self):
        """Guard should be cleared even if connect raises."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        client._do_connect = MagicMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            client.connect()
        assert not client._reauth_in_progress.is_set()


# ── setDisconnectedCallback ──────────────────────────────────────────────


class TestDisconnectedCallback:
    """BQ-1327 Fix 1: setDisconnectedCallback support in the live client."""

    def test_callback_attribute_exists(self):
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        assert client._on_disconnected is None

    def test_set_disconnected_callback(self):
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        cb = MagicMock()
        client.setDisconnectedCallback(cb)
        assert client._on_disconnected is cb

    def test_on_tcp_disconnected_invokes_callback(self):
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        client._connected = True
        cb = MagicMock()
        client.setDisconnectedCallback(cb)
        client._on_tcp_disconnected(None)
        cb.assert_called_once_with(client)
        assert not client._connected

    def test_on_tcp_disconnected_no_callback_no_error(self):
        """Should not raise if no callback registered."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        client._connected = True
        client._on_tcp_disconnected(None)  # should not raise
        assert not client._connected

    def test_on_tcp_disconnected_callback_exception_swallowed(self):
        """Callback errors should be logged, not raised."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        client._connected = True
        bad_cb = MagicMock(side_effect=ValueError("bad callback"))
        client.setDisconnectedCallback(bad_cb)
        client._on_tcp_disconnected(None)  # should not raise
        assert not client._connected

    def test_on_tcp_disconnected_clears_reauth_guard(self):
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        client._connected = True
        client._reauth_in_progress.set()
        client._on_tcp_disconnected(None)
        assert not client._reauth_in_progress.is_set()


# ── Auth response validation ─────────────────────────────────────────────


class TestAuthResponseValidation:
    """BQ-1327: _is_valid_auth_response validates payload types."""

    def test_valid_app_auth_response(self):
        from adapters.ctrader.open_api_client import (
            CTraderOpenApiClient,
            _APP_AUTH_RES_PAYLOAD_TYPE,
        )

        client = CTraderOpenApiClient("id", "secret", 123)
        response = MagicMock()
        response.payloadType = _APP_AUTH_RES_PAYLOAD_TYPE
        assert (
            client._is_valid_auth_response(response, _APP_AUTH_RES_PAYLOAD_TYPE, "app")
            is True
        )

    def test_valid_acct_auth_response(self):
        from adapters.ctrader.open_api_client import (
            CTraderOpenApiClient,
            _ACCT_AUTH_RES_PAYLOAD_TYPE,
        )

        client = CTraderOpenApiClient("id", "secret", 123)
        response = MagicMock()
        response.payloadType = _ACCT_AUTH_RES_PAYLOAD_TYPE
        assert (
            client._is_valid_auth_response(
                response, _ACCT_AUTH_RES_PAYLOAD_TYPE, "account"
            )
            is True
        )

    def test_error_payload_type_rejected(self):
        from adapters.ctrader.open_api_client import (
            CTraderOpenApiClient,
            _APP_AUTH_RES_PAYLOAD_TYPE,
        )

        client = CTraderOpenApiClient("id", "secret", 123)
        response = MagicMock()
        response.payloadType = 2142  # error response
        with patch("adapters.ctrader.open_api_client.Protobuf.extract") as mock_extract:
            mock_payload = MagicMock()
            mock_payload.errorCode = "CH_AUTH_FAILED"
            mock_extract.return_value = mock_payload
            result = client._is_valid_auth_response(
                response, _APP_AUTH_RES_PAYLOAD_TYPE, "app"
            )
        assert result is False

    def test_unexpected_payload_type_rejected(self):
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        response = MagicMock()
        response.payloadType = 9999
        assert client._is_valid_auth_response(response, 2101, "app") is False

    def test_none_payload_type_rejected(self):
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient("id", "secret", 123)
        response = MagicMock()
        response.payloadType = None
        assert client._is_valid_auth_response(response, 2101, "app") is False


# ── BQ-1327 comment presence ─────────────────────────────────────────────


class TestBQ1327CommentPresence:
    """Verify that BQ-1327 reference comments exist at each fix location."""

    def test_constants_have_bq_comment(self):
        import adapters.ctrader.open_api_client as mod

        source = open(mod.__file__).read()
        assert "BQ-1327" in source

    def test_reauth_guard_has_bq_comment(self):
        import adapters.ctrader.open_api_client as mod

        source = open(mod.__file__).read()
        # Guard should be annotated
        assert source.count("BQ-1327") >= 4  # constants, guard, callback, validation

    def test_spot_feed_shim_has_bq_comment(self):
        import adapters.ctrader.open_api_spot_feed as mod

        source = open(mod.__file__).read()
        assert "BQ-1327" in source
