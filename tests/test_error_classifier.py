"""Tests for cTrader error classification tiers."""

import os
import sys
import unittest

from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

mock_modules = {
    "ctrader_open_api": mock.MagicMock(),
    "ctrader_open_api.client": mock.MagicMock(),
    "ctrader_open_api.messages": mock.MagicMock(),
    "ctrader_open_api.messages.OpenApiMessages_pb2": mock.MagicMock(),
    "ctrader_open_api.messages.OpenApiModelMessages_pb2": mock.MagicMock(),
    "ctrader_open_api.protobuf": mock.MagicMock(),
    "ctrader_open_api.tcpProtocol": mock.MagicMock(),
    "twisted.internet": mock.MagicMock(),
    "twisted.internet.reactor": mock.MagicMock(),
}
for mod_name, mod_obj in mock_modules.items():
    sys.modules.setdefault(mod_name, mod_obj)

from adapters.ctrader.error_classifier import ErrorTier, classify_error


class TestErrorClassifier(unittest.TestCase):
    def test_tier_1_transient_errors(self):
        result = classify_error("CONNECTION_LOST", "socket dropped")
        self.assertEqual(result.tier, ErrorTier.TIER_1_TRANSIENT)
        self.assertEqual(result.action, "reconnect")
        self.assertEqual(result.retry_after_ms, 0)
        self.assertTrue(result.is_recoverable)

    def test_tier_2_backoff_errors(self):
        result = classify_error("TOO_MANY_REQUESTS", "rate limited")
        self.assertEqual(result.tier, ErrorTier.TIER_2_BACKOFF)
        self.assertEqual(result.action, "retry")
        self.assertGreater(result.retry_after_ms, 0)
        self.assertTrue(result.is_recoverable)

    def test_tier_3a_operation_errors(self):
        result = classify_error("INVALID_SYMBOL", "bad symbol")
        self.assertEqual(result.tier, ErrorTier.TIER_3A_OPERATION)
        self.assertEqual(result.action, "reject_request")
        self.assertEqual(result.retry_after_ms, 0)
        self.assertFalse(result.is_recoverable)

    def test_tier_3b_system_errors(self):
        result = classify_error("AUTH_EXPIRED", "refresh token invalid")
        self.assertEqual(result.tier, ErrorTier.TIER_3B_SYSTEM)
        self.assertEqual(result.action, "halt")
        self.assertEqual(result.retry_after_ms, 0)
        self.assertFalse(result.is_recoverable)

    def test_unknown_defaults_to_tier_3a(self):
        result = classify_error("SOMETHING_NEW", "unexpected")
        self.assertEqual(result.tier, ErrorTier.TIER_3A_OPERATION)
        self.assertEqual(result.action, "reject_request")
        self.assertFalse(result.is_recoverable)

    def test_normalizes_case_and_whitespace(self):
        result = classify_error("  request_timeout ", "timeout")
        self.assertEqual(result.raw_code, "REQUEST_TIMEOUT")
        self.assertEqual(result.tier, ErrorTier.TIER_2_BACKOFF)

    def test_empty_code_becomes_unknown(self):
        result = classify_error("", "")
        self.assertEqual(result.raw_code, "UNKNOWN")
        self.assertEqual(result.tier, ErrorTier.TIER_3A_OPERATION)
        self.assertEqual(result.raw_description, "")


if __name__ == "__main__":
    unittest.main()
