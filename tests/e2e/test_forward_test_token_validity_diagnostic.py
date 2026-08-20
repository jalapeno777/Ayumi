"""Tests for ForwardTestEngine reconnect-diagnostic token_validity_remaining_s
emission (card 54f3c0fa).

The diagnostic must report the SECONDS REMAINING on the auth token
(``_token_expires_at - time.monotonic()``), NOT the raw monotonic
``_token_expires_at`` value. Reporting the raw value as ``token_age_s`` was
misleading operators during the Aug-18 auth storm — it sat frozen at
1,155,364 across 19 attempts because the absolute expiry was set once at
successful auth and never decreased.

These tests cover:
  * Numeric emission with proper format when ``_token_expires_at`` is set.
  * Strictly-decreasing value as ``time.monotonic()`` advances (proves
    the value is computed at log emission, not cached at auth time).
  * ``None`` emission when ``_token_expires_at`` is absent or None.
  * The diagnostic never emits the old misnamed ``token_age_s`` key.
"""

import json
import logging
import re  # noqa: F401
import unittest
from unittest.mock import MagicMock, patch

from adapters.ctrader.forward_test_engine import (
    ForwardTestConfig,
    ForwardTestEngine,
)


def _parse_diagnostic_json(record: logging.LogRecord) -> dict:
    """Pull the JSON payload out of a 'Reconnect diagnostic:' log record."""
    # record.msg is "Reconnect diagnostic: %s"; record.args is the JSON string.
    assert record.args, f"expected formatted args, got {record.args!r}"
    payload = record.args[0]
    assert isinstance(payload, str), f"expected JSON string, got {type(payload)}"
    return json.loads(payload)


class TestReconnectDiagnosticTokenValidity(unittest.TestCase):
    def _make_engine(self, market_feed):
        cfg = ForwardTestConfig(symbol="GBPUSD", max_reconnect_attempts=5)
        engine = ForwardTestEngine(config=cfg, strategies=[])
        engine._running = True
        engine._market_feed = market_feed
        # Make the reconnect path "fast" and short-circuit the actual feed
        # restart so we only exercise the diagnostic emission.
        engine._reconnect_delay = 0.0
        engine._start_market_feed = MagicMock(return_value=False)
        return engine

    def _capture_diagnostic_payload(self, engine, monotonic_value):
        """Run one ``_attempt_reconnect`` cycle with ``time.monotonic``
        pinned to ``monotonic_value``; return the parsed JSON payload
        from the emitted 'Reconnect diagnostic' log record."""
        captured = []

        class _Capture(logging.Handler):
            def emit(self, record):
                if record.getMessage().startswith("Reconnect diagnostic:"):
                    captured.append(record)

        handler = _Capture(level=logging.INFO)
        logger = logging.getLogger("ayumi.forward_test")
        logger.addHandler(handler)
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            with patch("adapters.ctrader.forward_test_engine.time") as mock_time_mod:
                mock_time_mod.monotonic.return_value = monotonic_value
                # Any other time attribute touched by the path
                # (``time.sleep`` etc.) should fall through to real time.
                mock_time_mod.side_effect = lambda *a, **kw: (
                    monotonic_value
                    if a == () and kw == {} and False  # never hit; below is the safe default
                    else __import__("time").time(*a, **kw)
                )
                # Simpler: allow all other attrs to be real time functions
                # while overriding only .monotonic.
                real_time = __import__("time")
                for attr in dir(real_time):
                    if attr.startswith("_") or attr == "monotonic":
                        continue
                    if not hasattr(mock_time_mod, attr):
                        setattr(mock_time_mod, attr, getattr(real_time, attr))
                engine._attempt_reconnect()
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

        assert captured, "expected at least one 'Reconnect diagnostic' log record"
        return _parse_diagnostic_json(captured[-1])

    # ------------------------------------------------------------------
    # Numeric & present
    # ------------------------------------------------------------------
    def test_emits_token_validity_remaining_s_when_expires_at_set(self):
        # _token_expires_at = 1000.0 (absolute monotonic expiry)
        # time.monotonic() = 800.0 → remaining = 200.0
        feed = MagicMock()
        feed._token_expires_at = 1000.0
        engine = self._make_engine(feed)

        payload = self._capture_diagnostic_payload(engine, monotonic_value=800.0)

        assert "token_validity_remaining_s" in payload, f"missing new diagnostic key in {payload!r}"
        assert "token_age_s" not in payload, f"old mislabeled key must be gone, got {payload!r}"
        assert payload["token_validity_remaining_s"] == 200.0
        assert isinstance(payload["token_validity_remaining_s"], (int, float))

    # ------------------------------------------------------------------
    # Strictly decreasing as monotonic clock advances
    # ------------------------------------------------------------------
    def test_value_strictly_decreases_as_monotonic_advances(self):
        feed = MagicMock()
        feed._token_expires_at = 5000.0
        engine = self._make_engine(feed)

        # First emission: clock at 4000.0 → remaining 1000.0
        first = self._capture_diagnostic_payload(engine, monotonic_value=4000.0)
        # Second emission: clock advanced by exactly 17.5s → remaining 982.5
        second = self._capture_diagnostic_payload(engine, monotonic_value=4017.5)

        delta = 17.5
        r1 = first["token_validity_remaining_s"]
        r2 = second["token_validity_remaining_s"]

        assert r1 == 1000.0
        assert r2 == 982.5
        # Strict decrease by exactly the clock delta — proves the value is
        # recomputed at log emission time and not cached.
        assert r2 < r1, f"expected strictly decreasing, got {r1} → {r2}"
        assert abs((r1 - r2) - delta) < 1e-9, f"expected delta {delta}, got {r1 - r2}"

    def test_value_strictly_decreases_across_three_emissions(self):
        """Triple-emission variant: prove the recompute happens every emit,
        not just the second one. This guards against an implementation that
        computes once and stores the result on ``self`` between calls."""
        feed = MagicMock()
        feed._token_expires_at = 10000.0
        engine = self._make_engine(feed)

        emissions = [
            self._capture_diagnostic_payload(engine, monotonic_value=1000.0),
            self._capture_diagnostic_payload(engine, monotonic_value=1010.0),
            self._capture_diagnostic_payload(engine, monotonic_value=1025.0),
        ]
        values = [e["token_validity_remaining_s"] for e in emissions]
        assert values == [9000.0, 8990.0, 8975.0], f"expected strictly decreasing by clock delta, got {values}"
        for prev, nxt in zip(values, values[1:]):  # noqa: B905
            assert nxt < prev

    # ------------------------------------------------------------------
    # None handling
    # ------------------------------------------------------------------
    def test_none_when_token_expires_at_attribute_absent(self):
        # A bare MagicMock() with no _token_expires_at attribute set should
        # yield None — getattr default plus the None-guard branch.
        feed = MagicMock(spec=[])  # spec=[] blocks auto-attr generation
        engine = self._make_engine(feed)

        payload = self._capture_diagnostic_payload(engine, monotonic_value=0.0)
        assert payload["token_validity_remaining_s"] is None

    def test_none_when_token_expires_at_is_explicit_none(self):
        feed = MagicMock()
        feed._token_expires_at = None
        engine = self._make_engine(feed)

        payload = self._capture_diagnostic_payload(engine, monotonic_value=12345.0)
        assert payload["token_validity_remaining_s"] is None

    def test_does_not_raise_arithmetic_on_none(self):
        """Regression guard: a previous-form implementation doing
        ``_token_expires_at - time.monotonic()`` without the None guard
        would have raised TypeError. Confirm the diagnostic emits cleanly
        instead of crashing the engine."""
        feed = MagicMock()
        feed._token_expires_at = None
        engine = self._make_engine(feed)

        # If this raises, the test fails with a clean traceback.
        self._capture_diagnostic_payload(engine, monotonic_value=999.0)


class TestDiagnosticPayloadShape(unittest.TestCase):
    """The diagnostic must keep the rest of its keys (attempt_no, backoff_s,
    last_error) intact while swapping the token key."""

    def test_keeps_existing_keys(self):
        feed = MagicMock()
        feed._token_expires_at = 500.0
        cfg = ForwardTestConfig(symbol="GBPUSD", max_reconnect_attempts=5)
        engine = ForwardTestEngine(config=cfg, strategies=[])
        engine._running = True
        engine._market_feed = feed
        engine._reconnect_delay = 7.5
        engine._start_market_feed = MagicMock(return_value=False)
        engine._health.last_error = RuntimeError("simulated")

        captured = []

        class _Cap(logging.Handler):
            def emit(self, record):
                if record.getMessage().startswith("Reconnect diagnostic:"):
                    captured.append(record)

        handler = _Cap(level=logging.INFO)
        logger = logging.getLogger("ayumi.forward_test")
        logger.addHandler(handler)
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            with patch("adapters.ctrader.forward_test_engine.time") as mock_time_mod:
                mock_time_mod.monotonic.return_value = 100.0
                real_time = __import__("time")
                for attr in dir(real_time):
                    if attr.startswith("_") or attr == "monotonic":
                        continue
                    if not hasattr(mock_time_mod, attr):
                        setattr(mock_time_mod, attr, getattr(real_time, attr))
                engine._attempt_reconnect()
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

        assert captured, "diagnostic record missing"
        payload = _parse_diagnostic_json(captured[-1])
        assert payload["attempt_no"] == 1
        assert payload["backoff_s"] == 7.5
        # last_error is str(... or "unknown")
        assert "simulated" in payload["last_error"]
        assert payload["token_validity_remaining_s"] == 400.0
        # And explicitly NOT the old key.
        assert "token_age_s" not in payload


if __name__ == "__main__":
    unittest.main()
