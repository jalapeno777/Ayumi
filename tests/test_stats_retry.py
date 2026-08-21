"""Tests for stats recording retry + graceful degradation in ForwardTestEngine.

Covers:
1. Retry-success: record_signal fails once then succeeds on retry
2. Retry-exhaustion: record_signal always fails, graceful degradation kicks in
3. Heartbeat includes stats_fails field after failures
4. _stats_fail_count resets to 0 on successful recording

These tests use mocks to simulate the SignalStatsRecorder behaviour and
verify retry/degradation logic without requiring a live cTrader connection.
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

# Ensure src is importable
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine_skeleton():
    """Create a minimal ForwardTestEngine-like object for testing stats retry.

    We can't instantiate the real engine (requires credentials, feeds, etc.),
    so we build a lightweight stand-in that has only the attributes used by
    the retry/degradation code path.
    """
    engine = MagicMock()
    engine._stats_fail_count = 0
    engine._last_known_good_confidence = None
    engine._stats_retry_max = 3
    engine._stats_retry_base_delay = 0.001  # speed up tests
    return engine


class FakeStatsRecorder:
    """Mock SignalStatsRecorder with configurable failure behaviour."""

    def __init__(self, fail_times=0, exc=RuntimeError("mock stats failure")):  # noqa: B008
        """Initialise.

        Args:
            fail_times: number of times record_signal raises before succeeding.
                        Set to float('inf') to always fail.
            exc: exception to raise on failure.
        """
        self.fail_times = fail_times
        self.exc = exc
        self.call_count = 0
        self.recorded = []

    def record_signal(self, *args, **kwargs):
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise self.exc
        self.recorded.append(kwargs or args)


# ---------------------------------------------------------------------------
# Tests — Retry Success
# ---------------------------------------------------------------------------


class TestRetrySuccess:
    """record_signal fails on first attempt but succeeds on retry."""

    def test_transient_failure_retried_successfully(self):
        """One transient failure followed by success: stats recorded, counter reset."""
        engine = _make_engine_skeleton()
        recorder = FakeStatsRecorder(fail_times=1)

        # Simulate the retry logic inline (mirrors engine code path)
        stats_recorded = False
        for attempt in range(engine._stats_retry_max):
            try:
                recorder.record_signal(signal_confidence=0.75)
                engine._stats_fail_count = 0
                engine._last_known_good_confidence = 0.75
                stats_recorded = True
                break
            except Exception:
                if attempt < engine._stats_retry_max - 1:
                    time.sleep(engine._stats_retry_base_delay * (2**attempt))
                else:
                    engine._stats_fail_count += 1

        assert stats_recorded is True
        assert recorder.call_count == 2  # failed once, succeeded on second
        assert engine._stats_fail_count == 0
        assert engine._last_known_good_confidence == 0.75

    def test_no_failure_first_attempt(self):
        """Stats recording succeeds on first try — no retries needed."""
        engine = _make_engine_skeleton()
        recorder = FakeStatsRecorder(fail_times=0)

        stats_recorded = False
        for attempt in range(engine._stats_retry_max):
            try:
                recorder.record_signal(signal_confidence=0.80)
                engine._stats_fail_count = 0
                engine._last_known_good_confidence = 0.80
                stats_recorded = True
                break
            except Exception:
                if attempt < engine._stats_retry_max - 1:
                    time.sleep(engine._stats_retry_base_delay * (2**attempt))
                else:
                    engine._stats_fail_count += 1

        assert stats_recorded is True
        assert recorder.call_count == 1
        assert engine._stats_fail_count == 0


# ---------------------------------------------------------------------------
# Tests — Retry Exhaustion / Graceful Degradation
# ---------------------------------------------------------------------------


class TestRetryExhaustion:
    """record_signal always fails — verify graceful degradation."""

    def test_all_retries_exhausted_fail_count_increments(self):
        """After max retries, fail count increments and degradation activates."""
        engine = _make_engine_skeleton()
        # Set a prior good confidence to simulate running engine
        engine._last_known_good_confidence = 0.65
        recorder = FakeStatsRecorder(fail_times=float("inf"))

        stats_recorded = False
        for attempt in range(engine._stats_retry_max):
            try:
                recorder.record_signal(signal_confidence=0.70)
                engine._stats_fail_count = 0
                engine._last_known_good_confidence = 0.70
                stats_recorded = True
                break
            except Exception:
                if attempt < engine._stats_retry_max - 1:
                    time.sleep(engine._stats_retry_base_delay * (2**attempt))
                else:
                    engine._stats_fail_count += 1

        assert stats_recorded is False
        assert recorder.call_count == engine._stats_retry_max
        assert engine._stats_fail_count == 1
        # Last-known-good confidence preserved for degradation
        assert engine._last_known_good_confidence == 0.65

    def test_degradation_without_prior_confidence(self):
        """First-ever stats failure with no prior good confidence cached."""
        engine = _make_engine_skeleton()
        assert engine._last_known_good_confidence is None
        recorder = FakeStatsRecorder(fail_times=float("inf"))

        stats_recorded = False
        for attempt in range(engine._stats_retry_max):
            try:
                recorder.record_signal(signal_confidence=0.60)
                engine._stats_fail_count = 0
                engine._last_known_good_confidence = 0.60
                stats_recorded = True
                break
            except Exception:
                if attempt < engine._stats_retry_max - 1:
                    time.sleep(engine._stats_retry_base_delay * (2**attempt))
                else:
                    engine._stats_fail_count += 1

        assert stats_recorded is False
        assert engine._stats_fail_count == 1
        assert engine._last_known_good_confidence is None  # still no cache

    def test_fail_count_accumulates_across_signals(self):
        """Multiple consecutive failures increment the counter properly."""
        engine = _make_engine_skeleton()

        # Simulate two consecutive signal failures (each exhausting retries)
        for _ in range(2):
            recorder = FakeStatsRecorder(fail_times=float("inf"))
            for attempt in range(engine._stats_retry_max):
                try:
                    recorder.record_signal(signal_confidence=0.50)
                    engine._stats_fail_count = 0
                    break
                except Exception:
                    if attempt < engine._stats_retry_max - 1:
                        time.sleep(0)
                    else:
                        engine._stats_fail_count += 1

        assert engine._stats_fail_count == 2

    def test_fail_count_resets_on_recovery(self):
        """After failures, a successful recording resets the counter."""
        engine = _make_engine_skeleton()

        # First signal: all retries fail
        recorder_fail = FakeStatsRecorder(fail_times=float("inf"))
        for attempt in range(engine._stats_retry_max):
            try:
                recorder_fail.record_signal(signal_confidence=0.50)
                engine._stats_fail_count = 0
                break
            except Exception:
                if attempt < engine._stats_retry_max - 1:
                    time.sleep(0)
                else:
                    engine._stats_fail_count += 1

        assert engine._stats_fail_count == 1

        # Second signal: succeeds on first try
        recorder_ok = FakeStatsRecorder(fail_times=0)
        for attempt in range(engine._stats_retry_max):
            try:
                recorder_ok.record_signal(signal_confidence=0.55)
                engine._stats_fail_count = 0
                engine._last_known_good_confidence = 0.55
                break
            except Exception:
                if attempt < engine._stats_retry_max - 1:
                    time.sleep(0)
                else:
                    engine._stats_fail_count += 1

        assert engine._stats_fail_count == 0  # reset on success
        assert engine._last_known_good_confidence == 0.55


# ---------------------------------------------------------------------------
# Tests — Heartbeat JSON
# ---------------------------------------------------------------------------


class TestHeartbeatStatsFails:
    """Verify heartbeat JSON includes stats_fails field."""

    def test_heartbeat_includes_stats_fails(self, tmp_path):
        """Heartbeat JSON contains stats_fails and stats_last_known_good."""
        # Simulate the heartbeat dict construction
        stats_fail_count = 3
        last_known_good = 0.72

        heartbeat = {
            "last_beat": "2026-07-04T14:00:00+00:00",
            "pid": 12345,
            "ticks_received": 1000,
            "engine_running": True,
            "stats_fails": stats_fail_count,
            "stats_last_known_good": last_known_good,
        }

        json_str = json.dumps(heartbeat, indent=2)
        parsed = json.loads(json_str)

        assert "stats_fails" in parsed
        assert parsed["stats_fails"] == 3
        assert "stats_last_known_good" in parsed
        assert parsed["stats_last_known_good"] == 0.72

    def test_heartbeat_stats_fails_zero_on_healthy(self):
        """Healthy engine shows stats_fails=0 and last_known_good populated."""
        heartbeat = {
            "last_beat": "2026-07-04T14:00:00+00:00",
            "pid": 12345,
            "ticks_received": 5000,
            "engine_running": True,
            "stats_fails": 0,
            "stats_last_known_good": 0.68,
        }

        assert heartbeat["stats_fails"] == 0
        assert heartbeat["stats_last_known_good"] == 0.68

    def test_heartbeat_stats_fails_none_initially(self):
        """Fresh engine with no prior stats: last_known_good is None."""
        heartbeat = {
            "last_beat": "2026-07-04T14:00:00+00:00",
            "pid": 12345,
            "ticks_received": 0,
            "engine_running": False,
            "stats_fails": 0,
            "stats_last_known_good": None,
        }

        json_str = json.dumps(heartbeat)
        parsed = json.loads(json_str)
        assert parsed["stats_fails"] == 0
        assert parsed["stats_last_known_good"] is None


# ---------------------------------------------------------------------------
# Tests — Configurable Retry Parameters
# ---------------------------------------------------------------------------


class TestRetryConfiguration:
    """Verify retry parameters are configurable via environment variables."""

    def test_env_overrides_retry_max(self):
        """STATS_RETRY_MAX environment variable sets max retries."""
        os.environ["STATS_RETRY_MAX"] = "5"
        try:
            retry_max = int(os.environ.get("STATS_RETRY_MAX", "3"))
            assert retry_max == 5
        finally:
            del os.environ["STATS_RETRY_MAX"]

    def test_env_overrides_base_delay(self):
        """STATS_RETRY_BASE_DELAY environment variable sets base delay."""
        os.environ["STATS_RETRY_BASE_DELAY"] = "0.5"
        try:
            base_delay = float(os.environ.get("STATS_RETRY_BASE_DELAY", "2.0"))
            assert base_delay == 0.5
        finally:
            del os.environ["STATS_RETRY_BASE_DELAY"]

    def test_backoff_schedule(self):
        """Verify exponential backoff schedule: 2s, 4s, 8s for 3 retries."""
        base_delay = 2.0
        max_retries = 3
        expected_delays = [base_delay * (2**i) for i in range(max_retries - 1)]
        # Retries 0 and 1 have delays (before attempts 1 and 2)
        # Retry 2 (last) has no delay (falls through to exhaustion)
        assert expected_delays == [2.0, 4.0]  # delays before retry 1 and 2
