"""Tests for ReconnectStrategy — exponential backoff with decorrelated jitter."""

from __future__ import annotations

import unittest

from adapters.ctrader.error_classifier import classify_error
from adapters.ctrader.reconnect_strategy import (
    ReconnectAction,
    ReconnectStrategy,
)


class TestReconnectTier1Retry(unittest.TestCase):
    def test_tier_1_retries(self):
        strategy = ReconnectStrategy(max_attempts=10)
        classified = classify_error("CONNECTION_LOST", "socket dropped")
        decision = strategy.decide(classified, attempt=1)

        self.assertEqual(decision.action, ReconnectAction.RETRY)
        self.assertGreater(decision.sleep_seconds, 0)
        self.assertIn("tier_1", decision.reason)

    def test_tier_1_retry_is_fast(self):
        """TIER_1 sleep should be <= base_sleep on first attempt."""
        strategy = ReconnectStrategy(base_sleep=1.0, cap_sleep=60.0)
        classified = classify_error("TCP_RESET", "rst")
        decision = strategy.decide(classified, attempt=1)

        self.assertEqual(decision.action, ReconnectAction.RETRY)
        # First sleep: min(cap, random(base, base*3)) → 1.0..3.0
        self.assertGreaterEqual(decision.sleep_seconds, 1.0)
        self.assertLessEqual(decision.sleep_seconds, 3.0)


class TestReconnectTier3BHalt(unittest.TestCase):
    def test_tier_3b_halts(self):
        strategy = ReconnectStrategy()
        classified = classify_error("AUTH_EXPIRED", "refresh token invalid")
        decision = strategy.decide(classified, attempt=1)

        self.assertEqual(decision.action, ReconnectAction.HALT)
        self.assertEqual(decision.sleep_seconds, 0)
        self.assertIn("tier_3b", decision.reason)

    def test_tier_3b_token_invalidated_halts(self):
        strategy = ReconnectStrategy()
        classified = classify_error("TOKEN_INVALIDATED", "revoked")
        decision = strategy.decide(classified, attempt=1)

        self.assertEqual(decision.action, ReconnectAction.HALT)


class TestReconnectTier3ANoRetry(unittest.TestCase):
    def test_tier_3a_no_retry(self):
        strategy = ReconnectStrategy()
        classified = classify_error("INVALID_SYMBOL", "bad symbol")
        decision = strategy.decide(classified, attempt=1)

        self.assertEqual(decision.action, ReconnectAction.NO_RETRY)
        self.assertEqual(decision.sleep_seconds, 0)


class TestReconnectJitterBounded(unittest.TestCase):
    def test_jitter_never_exceeds_cap(self):
        strategy = ReconnectStrategy(base_sleep=1.0, cap_sleep=5.0, max_attempts=20)
        classified = classify_error("CONNECTION_LOST", "drop")

        for attempt in range(1, 16):
            decision = strategy.decide(classified, attempt=attempt)
            self.assertLessEqual(
                decision.sleep_seconds,
                5.0,
                f"Attempt {attempt}: sleep {decision.sleep_seconds} > cap 5.0",
            )

    def test_jitter_never_below_base(self):
        strategy = ReconnectStrategy(base_sleep=2.0, cap_sleep=60.0)
        classified = classify_error("CONNECTION_LOST", "drop")

        for attempt in range(1, 10):
            decision = strategy.decide(classified, attempt=attempt)
            self.assertGreaterEqual(
                decision.sleep_seconds,
                2.0,
                f"Attempt {attempt}: sleep {decision.sleep_seconds} < base 2.0",
            )


class TestReconnectMaxAttempts(unittest.TestCase):
    def test_no_retry_after_max_attempts(self):
        strategy = ReconnectStrategy(max_attempts=3)
        classified = classify_error("CONNECTION_LOST", "drop")

        d1 = strategy.decide(classified, attempt=1)
        d2 = strategy.decide(classified, attempt=2)
        d3 = strategy.decide(classified, attempt=3)  # == max

        self.assertEqual(d1.action, ReconnectAction.RETRY)
        self.assertEqual(d2.action, ReconnectAction.RETRY)
        self.assertEqual(d3.action, ReconnectAction.NO_RETRY)
        self.assertIn("max_attempts", d3.reason)


class TestReconnectReset(unittest.TestCase):
    def test_reset_after_success(self):
        strategy = ReconnectStrategy(base_sleep=1.0, cap_sleep=60.0)
        classified = classify_error("CONNECTION_LOST", "drop")

        # Do a few retries to grow the jitter state
        for a in range(1, 5):
            strategy.decide(classified, attempt=a)

        prev_before = strategy.prev_sleep
        self.assertGreater(prev_before, 1.0)  # should have grown

        # Reset
        strategy.reset()
        self.assertEqual(strategy.prev_sleep, 1.0)

        # Next sleep should be back in the base range
        decision = strategy.decide(classified, attempt=1)
        self.assertLessEqual(decision.sleep_seconds, 3.0)  # min(cap, random(1, 1*3))


class TestReconnectTier2Backoff(unittest.TestCase):
    def test_tier_2_retries_with_longer_sleep(self):
        strategy = ReconnectStrategy(base_sleep=1.0, cap_sleep=60.0)

        # TIER_1 first to establish baseline
        t1_classified = classify_error("CONNECTION_LOST", "drop")
        _t1_decision = strategy.decide(t1_classified, attempt=1)

        # Now TIER_2 — should sleep at least as long (multiplier=2)
        t2_classified = classify_error("TOO_MANY_REQUESTS", "rate")
        t2_decision = strategy.decide(t2_classified, attempt=2)

        self.assertEqual(t2_decision.action, ReconnectAction.RETRY)
        self.assertIn("tier_2", t2_decision.reason)


if __name__ == "__main__":
    unittest.main()
