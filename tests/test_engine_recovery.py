"""BQ-1330a: Engine FSM recovery — survive auth failure with retry.

Tests that ConnectionManager.authenticate_with_retry() correctly:
- Retries on auth failure (up to 3 attempts)
- Uses exponential backoff (1s, 2s, 4s)
- Does NOT permanently die on a single auth failure
- Eventually succeeds when a transient failure clears
- Gives up after max retries exhausted
"""

from unittest.mock import MagicMock, patch

import pytest
from adapters.ctrader.connection_manager import (
    AUTH_RETRY_BACKOFF_SECONDS,
    AUTH_RETRY_MAX_ATTEMPTS,
    ConnectionManager,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mgr():
    """ConnectionManager with metrics thread disabled."""
    m = ConnectionManager(metrics_log_path=None)
    yield m
    m.stop()


# ── Tests: auth retry succeeds ─────────────────────────────────────────────────


class TestAuthenticateWithRetrySuccess:
    """Engine stays alive when auth eventually succeeds."""

    def test_succeeds_on_first_attempt_no_retry(self, mgr):
        """Auth succeeds immediately — no retries needed."""
        auth_fn = MagicMock(return_value=True)

        result = mgr.authenticate_with_retry(auth_fn)

        assert result is True
        assert auth_fn.call_count == 1

    def test_succeeds_on_second_attempt_after_one_failure(self, mgr):
        """Engine survives first auth failure and succeeds on retry."""
        auth_fn = MagicMock(side_effect=[False, True])

        with patch("adapters.ctrader.connection_manager.time.sleep") as mock_sleep:
            result = mgr.authenticate_with_retry(auth_fn)

        assert result is True
        assert auth_fn.call_count == 2
        # Only 1 sleep call (between attempt 1 and 2)
        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_with(1.0)  # first backoff

    def test_succeeds_on_third_attempt(self, mgr):
        """Engine survives two auth failures and succeeds on attempt 3."""
        auth_fn = MagicMock(side_effect=[False, False, True])

        with patch("adapters.ctrader.connection_manager.time.sleep") as mock_sleep:
            result = mgr.authenticate_with_retry(auth_fn)

        assert result is True
        assert auth_fn.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)  # after attempt 1
        mock_sleep.assert_any_call(2.0)  # after attempt 2

    def test_succeeds_after_exception_then_recovery(self, mgr):
        """Auth raises exception on first attempt, succeeds on second."""
        auth_fn = MagicMock(side_effect=[RuntimeError("connection refused"), True])

        with patch("adapters.ctrader.connection_manager.time.sleep"):
            result = mgr.authenticate_with_retry(auth_fn)

        assert result is True
        assert auth_fn.call_count == 2

    def test_resets_reconnect_state_on_success(self, mgr):
        """reset_reconnect_state() is called after successful retry."""
        mgr._reconnect_attempt = 5  # simulate prior failures
        auth_fn = MagicMock(side_effect=[False, True])

        with patch("adapters.ctrader.connection_manager.time.sleep"):
            result = mgr.authenticate_with_retry(auth_fn)

        assert result is True
        assert mgr._reconnect_attempt == 0


# ── Tests: auth retry exhausted ────────────────────────────────────────────────


class TestAuthenticateWithRetryExhausted:
    """Engine gives up after max retries — but only after trying 3 times."""

    def test_all_three_attempts_fail_returns_false(self, mgr):
        """All 3 attempts fail → returns False (engine may die)."""
        auth_fn = MagicMock(return_value=False)

        with patch("adapters.ctrader.connection_manager.time.sleep"):
            result = mgr.authenticate_with_retry(auth_fn)

        assert result is False
        assert auth_fn.call_count == 3

    def test_all_three_attempts_raise_returns_false(self, mgr):
        """All 3 attempts raise exceptions → returns False."""
        auth_fn = MagicMock(side_effect=ConnectionError("auth server down"))

        with patch("adapters.ctrader.connection_manager.time.sleep"):
            result = mgr.authenticate_with_retry(auth_fn)

        assert result is False
        assert auth_fn.call_count == 3

    def test_does_not_exceed_max_attempts(self, mgr):
        """Exactly 3 attempts — no more."""
        auth_fn = MagicMock(return_value=False)

        with patch("adapters.ctrader.connection_manager.time.sleep"):
            mgr.authenticate_with_retry(auth_fn)

        assert auth_fn.call_count == AUTH_RETRY_MAX_ATTEMPTS


# ── Tests: exponential backoff timing ─────────────────────────────────────────


class TestExponentialBackoff:
    """Verify backoff schedule is exactly 1s, 2s, 4s."""

    def test_backoff_sequence_on_all_failures(self, mgr):
        """Backoff between attempts is 1s, 2s (2 sleeps for 3 attempts)."""
        auth_fn = MagicMock(return_value=False)

        with patch("adapters.ctrader.connection_manager.time.sleep") as mock_sleep:
            mgr.authenticate_with_retry(auth_fn)

        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [1.0, 2.0]

    def test_backoff_sequence_partial_failure(self, mgr):
        """Fails on attempt 1, sleeps 1s, fails on attempt 2, sleeps 2s,
        succeeds on attempt 3."""
        auth_fn = MagicMock(side_effect=[False, False, True])

        with patch("adapters.ctrader.connection_manager.time.sleep") as mock_sleep:
            mgr.authenticate_with_retry(auth_fn)

        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [1.0, 2.0]

    def test_backoff_constant_matches_spec(self):
        """Module-level constant matches BQ-1330a spec: (1, 2, 4)."""
        assert AUTH_RETRY_BACKOFF_SECONDS == (1.0, 2.0, 4.0)

    def test_custom_backoff_overrides_default(self, mgr):
        """Caller can supply custom backoff schedule."""
        auth_fn = MagicMock(return_value=False)

        with patch("adapters.ctrader.connection_manager.time.sleep") as mock_sleep:
            mgr.authenticate_with_retry(
                auth_fn,
                backoff_seconds=(0.5, 1.0),
            )

        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [0.5, 1.0]


# ── Tests: engine survival (integration-style) ────────────────────────────────


class TestEngineSurvival:
    """Engine-level survival behavior: does NOT permanently die on one failure."""

    def test_engine_survives_transient_auth_failure(self, mgr):
        """Simulate a transient auth failure: first attempt fails (token
        refresh race), second attempt succeeds. Engine must stay alive."""

        call_log = []

        def simulated_auth():
            call_log.append("auth_attempt")
            if len(call_log) == 1:
                raise RuntimeError("AUTH_EXPIRED: token refresh in progress")
            return True  # second attempt succeeds

        with patch("adapters.ctrader.connection_manager.time.sleep"):
            result = mgr.authenticate_with_retry(simulated_auth)

        assert result is True, "Engine must survive a transient auth failure"
        assert len(call_log) == 2, "Should retry exactly once after transient failure"

    def test_engine_survives_with_realistic_auth_pattern(self, mgr):
        """Realistic pattern: connect() raises on first try, succeeds on retry
        after the token lifecycle has a chance to refresh."""

        attempt_count = [0]

        def realistic_connect():
            attempt_count[0] += 1
            if attempt_count[0] == 1:
                # Simulate: OpenAPI client gets AUTH_EXPIRED error
                raise ConnectionError("Trading account not authorized")
            # Second attempt: token has been refreshed by another path
            return True

        with patch("adapters.ctrader.connection_manager.time.sleep"):
            result = mgr.authenticate_with_retry(realistic_connect)

        assert result is True
        assert attempt_count[0] == 2

    def test_engine_does_not_die_on_single_auth_failure(self, mgr):
        """The core BQ-1330a requirement: a single auth failure must NOT
        permanently kill the engine. It must retry at least once."""

        attempts = []

        def auth():
            attempts.append(1)
            if len(attempts) == 1:
                return False  # single failure
            return True  # recovery

        with patch("adapters.ctrader.connection_manager.time.sleep"):
            result = mgr.authenticate_with_retry(auth)

        assert result is True, "Single auth failure must not permanently kill engine"
        assert len(attempts) >= 2, "Engine must retry after first failure"


# ── Tests: default constants ───────────────────────────────────────────────────


class TestAuthRetryConstants:
    """Verify module-level defaults match BQ-1330a spec."""

    def test_default_max_attempts_is_3(self):
        assert AUTH_RETRY_MAX_ATTEMPTS == 3

    def test_default_backoff_is_exponential(self):
        """Each backoff step doubles: 1, 2, 4."""
        b = AUTH_RETRY_BACKOFF_SECONDS
        assert b[0] == 1.0
        for i in range(1, len(b)):
            assert b[i] == b[i - 1] * 2
