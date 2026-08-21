"""Tests for cTrader error classification tiers.

(BQ-1037: previous version polluted sys.modules with MagicMock at import time,
breaking collection of other test files that needed the real ctrader_open_api
package. Fixed by importing the real module — ctrader_open_api is installed
and the import works fine.)
"""

from __future__ import annotations

from adapters.ctrader.error_classifier import ErrorTier, classify_error


class TestErrorClassifier:
    def test_tier_1_transient_errors(self):
        result = classify_error("CONNECTION_LOST", "socket dropped")
        assert result.tier == ErrorTier.TIER_1_TRANSIENT
        assert result.action == "reconnect"
        assert result.retry_after_ms == 0
        assert result.is_recoverable

    def test_tier_2_backoff_errors(self):
        result = classify_error("TOO_MANY_REQUESTS", "rate limited")
        assert result.tier == ErrorTier.TIER_2_BACKOFF
        assert result.action == "retry"
        assert result.retry_after_ms > 0
        assert result.is_recoverable

    def test_tier_3a_operation_errors(self):
        result = classify_error("INVALID_SYMBOL", "bad symbol")
        assert result.tier == ErrorTier.TIER_3A_OPERATION
        assert result.action == "reject_request"
        assert result.retry_after_ms == 0
        assert not result.is_recoverable

    def test_tier_3b_system_errors(self):
        result = classify_error("AUTH_EXPIRED", "refresh token invalid")
        assert result.tier == ErrorTier.TIER_3B_SYSTEM
        assert result.action == "halt"
        assert result.retry_after_ms == 0
        assert not result.is_recoverable

    def test_unknown_defaults_to_tier_3a(self):
        result = classify_error("SOMETHING_NEW", "unexpected")
        assert result.tier == ErrorTier.TIER_3A_OPERATION
        assert result.action == "reject_request"
        assert not result.is_recoverable

    def test_normalizes_case_and_whitespace(self):
        result = classify_error("  request_timeout ", "timeout")
        assert result.raw_code == "REQUEST_TIMEOUT"
        assert result.tier == ErrorTier.TIER_2_BACKOFF

    def test_empty_code_becomes_unknown(self):
        result = classify_error("", "")
        assert result.raw_code == "UNKNOWN"
        assert result.tier == ErrorTier.TIER_3A_OPERATION
        assert result.raw_description == ""
