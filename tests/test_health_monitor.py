"""Tests for the structured health-reporting HealthMonitor."""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock

import pytest

from engine.health_monitor import HealthMonitor


# --------------------------------------------------------------------- #
# Test capture handler
# --------------------------------------------------------------------- #

class _LogCapture:
    """Minimal logging handler that stores records for assertions."""

    def __init__(self):
        self.records: list[logging.LogRecord] = []

    def __call__(self, record: logging.LogRecord):
        self.records.append(record)


@pytest.fixture()
def capture_logger():
    """Attach a capture handler to the health-monitor logger."""
    cap = _LogCapture()
    handler = logging.Handler()
    handler.emit = cap
    logger = logging.getLogger("ayumi.forward_test")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield cap
    logger.removeHandler(handler)


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #

def _make_mock(**kwattrs):
    """Create a MagicMock with the given attribute values."""
    m = MagicMock()
    for k, v in kwattrs.items():
        setattr(m, k, v)
    return m


# --------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------- #


class TestHealthMonitorEmit:
    def test_emit_health_logs_b5_format(self, capture_logger):
        """_emit_health must produce a [B5 Health] INFO line."""
        mon = HealthMonitor(interval_seconds=999)
        mon._start_time = time.monotonic()
        mon._market_data_feed = _make_mock(
            ticks_received=100, ticks_per_second=2.5,
            bars_built=10, signals_generated=5,
            paper_trades=3, balance=10000.0,
        )
        mon._order_gateway = _make_mock(live_fills=2)

        mon._emit_health()

        b5_lines = [
            r for r in capture_logger.records
            if "[B5 Health]" in r.getMessage() and r.levelno == logging.INFO
        ]
        assert len(b5_lines) >= 1
        msg = b5_lines[0].getMessage()
        # Verify the expected field names are present
        assert "ticks=" in msg
        assert "tps=" in msg
        assert "bars=" in msg
        assert "signals=" in msg
        assert "uptime=" in msg

    def test_emit_health_includes_paper_and_live_counts(self, capture_logger):
        """paper_trades and live_fills must be separate fields."""
        mon = HealthMonitor(interval_seconds=999)
        mon._start_time = time.monotonic()
        mon._market_data_feed = _make_mock(
            ticks_received=200, ticks_per_second=1.0,
            bars_built=20, signals_generated=8,
            paper_trades=15, balance=5000.0,
        )
        mon._order_gateway = _make_mock(live_fills=7)

        mon._emit_health()

        b5_info = [
            r for r in capture_logger.records
            if "[B5 Health]" in r.getMessage() and r.levelno == logging.INFO
        ][0]
        msg = b5_info.getMessage()
        assert "paper_trades=15" in msg
        assert "live_fills=7" in msg


class TestHealthMonitorWarnings:
    def test_warning_when_session_not_subscribed(self, capture_logger):
        """If session_state != SUBSCRIBED and uptime > 60s, emit WARNING."""
        mon = HealthMonitor(interval_seconds=999)
        # Set start_time far enough back to exceed the 60s grace period
        mon._start_time = time.monotonic() - 120.0
        mon._session = _make_mock(state="SessionState.CONNECTING")

        mon._emit_health()

        warnings = [
            r for r in capture_logger.records
            if r.levelno == logging.WARNING and "session_state" in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "CONNECTING" in warnings[0].getMessage()


class TestHealthMonitorLifecycle:
    def test_start_stop_idempotent(self):
        """Calling start()/stop() multiple times must not crash."""
        mon = HealthMonitor(interval_seconds=999)

        # Double-start — second call is a no-op
        mon.start()
        mon.start()
        assert mon._thread is not None

        # Double-stop — second call is a no-op
        mon.stop()
        mon.stop()
        assert mon._thread is None


class TestHealthMonitorStrategies:
    def test_per_strategy_health(self, capture_logger):
        """Attached strategies produce [S1 Health] lines."""
        mon = HealthMonitor(interval_seconds=999)
        mon._start_time = time.monotonic()
        mon._strategies = {
            "ICT_Killzone": {"evals": 10, "no_signal": 3, "last_eval_monotonic": time.monotonic() - 5.0},
            "SMC_FVG": {"evals": 8, "no_signal": 1, "last_eval_monotonic": time.monotonic() - 12.0},
        }

        mon._emit_health()

        s1_lines = [
            r for r in capture_logger.records
            if "[S1 Health]" in r.getMessage()
        ]
        assert len(s1_lines) == 2  # one per strategy

        # Verify sorted order (ICT_Killzone before SMC_FVG)
        first = s1_lines[0].getMessage()
        second = s1_lines[1].getMessage()
        assert "ICT_Killzone" in first
        assert "SMC_FVG" in second
        assert "evals=10" in first
        assert "no_signal=3" in first
        assert "evals=8" in second
