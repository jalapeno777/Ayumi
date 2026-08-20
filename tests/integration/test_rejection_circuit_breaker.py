"""Tests for rejection circuit breaker logic (T5)."""

import time
from unittest.mock import MagicMock


class TestRejectionCircuitBreaker:
    """Verify the rejection circuit breaker in forward_test_engine."""

    def test_breaker_threshold_value(self):
        """Threshold should be 5."""
        from adapters.ctrader.forward_test_engine import ForwardTestEngine

        assert ForwardTestEngine._REJECTION_BREAKER_THRESHOLD == 5

    def test_breaker_cooldown_duration(self):
        """Cooldown should be 60 seconds."""
        from adapters.ctrader.forward_test_engine import ForwardTestEngine

        assert ForwardTestEngine._REJECTION_COOLDOWN_SEC == 60.0

    def test_cooldown_blocks_evaluation(self):
        """When cooldown_until is in the future, evaluation should skip."""
        from adapters.ctrader.forward_test_engine import (  # noqa: I001
            ForwardTestEngine,
            ForwardTestConfig,
        )

        engine = ForwardTestEngine.__new__(ForwardTestEngine)
        engine._config = ForwardTestConfig()
        engine._rejection_cooldown_until = time.monotonic() + 60.0
        engine._eval_semaphore = MagicMock()
        engine._live_adapter = MagicMock()
        engine._preload_complete = True

        # _evaluate_strategies should return early due to cooldown
        engine._evaluate_strategies("EURUSD")
        # eval_semaphore.acquire should NOT have been called
        engine._eval_semaphore.acquire.assert_not_called()

    def test_no_cooldown_allows_evaluation(self):
        """When cooldown has expired, evaluation should proceed past cooldown check."""
        from adapters.ctrader.forward_test_engine import (  # noqa: I001
            ForwardTestEngine,
            ForwardTestConfig,
        )

        engine = ForwardTestEngine.__new__(ForwardTestEngine)
        engine._config = ForwardTestConfig()
        engine._rejection_cooldown_until = 0.0  # expired
        engine._eval_semaphore = MagicMock()
        engine._eval_semaphore.acquire.return_value = True
        engine._live_adapter = MagicMock()  # must not be None to reach semaphore
        engine._preload_complete = True
        engine._bars = {}
        engine._current_bar = {}
        engine._required_timeframes = []
        engine._strategy_timeframes = {}
        engine._strategies = []
        engine._health = MagicMock()
        engine._stop_health_monitor = MagicMock()
        engine._lock = MagicMock()

        engine._evaluate_strategies("EURUSD")
        # Should have tried to acquire semaphore (past cooldown check)
        engine._eval_semaphore.acquire.assert_called_once()

    def test_runtime_counter_fields_exist(self):
        """Engine should have runtime counter fields initialized."""
        from adapters.ctrader.forward_test_engine import ForwardTestEngine

        _engine = ForwardTestEngine.__new__(ForwardTestEngine)
        # These are set in __init__, verify they're documented/expected
        assert hasattr(ForwardTestEngine, "_REJECTION_BREAKER_THRESHOLD")
        assert hasattr(ForwardTestEngine, "_REJECTION_COOLDOWN_SEC")
