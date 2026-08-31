"""Tests for the Discord trade-opened notifier.

These tests are offline-only: we monkeypatch ``urllib.request.urlopen`` (and
related symbols inside the notifier module) so no real HTTP traffic is
generated. Ayumi's trade path must NEVER depend on Discord availability, so
failure isolation is the most important property under test.
"""

from __future__ import annotations

import json
import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib import error as urllib_error

from adapters.ctrader.discord_notifier import DiscordNotifier, TradeOpenedEvent


def _wait_for_threads(timeout: float = 2.0) -> None:
    """Best-effort drain of any daemon notifier threads spawned during a test."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        alive = [t for t in threading.enumerate() if t.name == "discord-trade-notify" and t.is_alive()]
        if not alive:
            return
        time.sleep(0.02)
    # If we hit the deadline we let the test proceed — daemon threads will be
    # cleaned up when the interpreter exits, and our assertions already cover
    # what we care about.


def _event(**overrides) -> TradeOpenedEvent:
    base = dict(
        symbol="XAUUSD",
        direction="BUY",
        volume=0.10,
        entry_price=4489.625,
        stop_loss=4479.625,
        take_profit=4509.625,
        strategy_id="SRMR+",
        timestamp="2026-08-31T19:00:00+00:00",
        timeframe="M15",
        comment="regime=trending",
    )
    base.update(overrides)
    return TradeOpenedEvent(**base)


class TestPayloadFormatting(unittest.TestCase):
    def test_build_payload_contains_required_signal_fields(self):
        payload = DiscordNotifier._build_payload(_event())
        self.assertIn("embeds", payload)
        embed = payload["embeds"][0]
        desc = embed["description"]
        for needle in [
            "BUY",
            "XAUUSD",
            "0.1",  # 0.10 -> 0.1
            "4489.625",
            "4479.625",
            "4509.625",
            "SRMR+",
            "M15",
            "2026-08-31T19:00:00+00:00",
            "regime=trending",
        ]:
            self.assertIn(needle, desc)

    def test_build_payload_handles_missing_sl_tp(self):
        event = _event(stop_loss=None, take_profit=None, comment="")
        payload = DiscordNotifier._build_payload(event)
        desc = payload["embeds"][0]["description"]
        # The em-dash placeholder is used for missing SL/TP.
        self.assertIn("—", desc)
        # No comment line should be appended when empty.
        self.assertNotIn("Note:", desc)

    def test_build_payload_serializes_to_json(self):
        payload = DiscordNotifier._build_payload(_event())
        # Must be JSON-serializable without raising.
        json.dumps(payload)


class TestMissingWebhookURL(unittest.TestCase):
    def setUp(self):
        # Reset the class-level "warned" flag so each test sees a clean slate.
        DiscordNotifier._warned_missing = False

    def test_notifier_is_disabled_when_url_absent(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_WEBHOOK", None)
            n = DiscordNotifier()
        self.assertFalse(n.enabled)

    def test_notify_is_noop_when_disabled_and_warns_once(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_WEBHOOK", None)
            n = DiscordNotifier()
        # First call should be safe (no exception) and produce exactly one
        # warning. Subsequent calls stay silent.
        with self.assertLogs("adapters.ctrader.discord_notifier", level="WARNING") as cm:
            n.notify_trade_opened(_event())
            n.notify_trade_opened(_event())
            n.notify_trade_opened(_event())
        warned = [
            line for line in cm.output if "DISCORD_WEBHOOK is not set" in line
        ]
        self.assertEqual(len(warned), 1, msg=f"expected exactly one warning, got: {cm.output}")


class TestFailureIsolation(unittest.TestCase):
    """The notifier must NEVER let webhook failures propagate to the caller."""

    def setUp(self):
        DiscordNotifier._warned_missing = False

    def _post_side_effect(self):
        def _raise(req, **kwargs):
            raise urllib_error.URLError("network down")
        return _raise

    def test_notify_returns_immediately_when_post_fails(self):
        n = DiscordNotifier(
            webhook_url="https://discord.example/webhook",
            enabled=True,
            timeout_seconds=0.5,
        )
        with patch(
            "adapters.ctrader.discord_notifier.urllib_request.urlopen",
            side_effect=self._post_side_effect(),
        ):
            # Must not raise even though urlopen raises URLError.
            n.notify_trade_opened(_event())
        _wait_for_threads()

    def test_notify_handles_http_error_without_retry(self):
        n = DiscordNotifier(
            webhook_url="https://discord.example/webhook",
            enabled=True,
            timeout_seconds=0.5,
        )

        call_count = {"n": 0}

        def _http_error(req, **kwargs):
            call_count["n"] += 1
            raise urllib_error.HTTPError(
                url=req.full_url,
                code=404,
                msg="Not Found",
                hdrs={},  # type: ignore[arg-type]
                fp=None,
            )

        with patch(
            "adapters.ctrader.discord_notifier.urllib_request.urlopen",
            side_effect=_http_error,
        ):
            n.notify_trade_opened(_event())
        _wait_for_threads()
        # 4xx responses must NOT trigger a retry.
        self.assertEqual(call_count["n"], 1, msg="4xx must not retry")

    def test_notify_uses_fire_and_forget_thread(self):
        n = DiscordNotifier(
            webhook_url="https://discord.example/webhook",
            enabled=True,
            timeout_seconds=2.0,
        )

        block = threading.Event()
        observed: dict = {}

        def _slow(req, **kwargs):
            # Sleep on the *background* thread to prove the caller returned first.
            observed["thread_name"] = threading.current_thread().name
            block.wait(timeout=3.0)
            return MagicMock(status=204)

        caller_started = time.time()
        with patch(
            "adapters.ctrader.discord_notifier.urllib_request.urlopen",
            side_effect=_slow,
        ):
            n.notify_trade_opened(_event())
        caller_returned = time.time()
        # Caller should return essentially immediately (well under the 3s the
        # background thread will block).
        self.assertLess(caller_returned - caller_started, 0.5)

        # Let the background thread finish cleanly.
        block.set()
        _wait_for_threads()
        self.assertEqual(
            observed.get("thread_name"),
            "discord-trade-notify",
            msg="POST must run on the dedicated daemon thread, not the caller",
        )


class TestEnvVarResolution(unittest.TestCase):
    def setUp(self):
        DiscordNotifier._warned_missing = False

    def test_reads_url_from_env_when_not_passed_explicitly(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK": "https://example/wh"}):
            n = DiscordNotifier()
        self.assertTrue(n.enabled)

    def test_blank_env_var_disables_notifier(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK": "   "}):
            n = DiscordNotifier()
        self.assertFalse(n.enabled)


if __name__ == "__main__":
    unittest.main()
