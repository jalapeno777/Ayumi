"""Unit tests for Kill Switch Auto-Triggers (Phase 1E.2).

Tests cover:
  - Watchdog detects stale heartbeat → activates kill
  - Watchdog ignores stale heartbeat during weekend/market closed
  - Watchdog ignores stale heartbeat when engine_running=false (clean shutdown)
  - RiskGuard circuit breaker → activates kill switch
  - Feed disconnect → activates freeze
  - Error rate > 50% → activates freeze
  - Heartbeat file atomic write
  - Kill switch audit log entries for auto-triggers
"""

import json
import logging
import os
import tempfile
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from adapters.ctrader.kill_switch import KillSwitchManager
from adapters.ctrader.risk_guard import (
    FTMOConfig,
    RiskGuard,
    RiskLimitType,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_state_dir(tmp_path):
    """Provide a temporary kill switch state directory."""
    d = tmp_path / "kill_switches"
    d.mkdir()
    return str(d)


@pytest.fixture
def tmp_heartbeat_file(tmp_path):
    """Provide a temporary heartbeat file path."""
    return str(tmp_path / "heartbeat_trading.json")


@pytest.fixture
def ksm(tmp_state_dir):
    """Fresh KillSwitchManager with temp state dir."""
    return KillSwitchManager(state_dir=tmp_state_dir)


@pytest.fixture
def watchdog(tmp_heartbeat_file, tmp_state_dir):
    """Create a KillSwitchWatchdog instance for testing."""
    from scripts.kill_switch_watchdog import KillSwitchWatchdog

    return KillSwitchWatchdog(
        heartbeat_file=tmp_heartbeat_file,
        check_interval=1,
        stale_threshold=30,
        state_dir=tmp_state_dir,
    )


def _write_heartbeat(filepath: str, age_seconds: float = 0, engine_running: bool = True):
    """Helper: write a heartbeat file with a given age."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    data = {
        "last_beat": ts.isoformat(),
        "pid": 12345,
        "ticks_received": 1000,
        "engine_running": engine_running,
    }
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    Path(filepath).write_text(json.dumps(data, indent=2))


# ── Watchdog: Stale Heartbeat → Kill ─────────────────────────────────────────

class TestWatchdogStaleHeartbeat:
    def test_stale_heartbeat_activates_kill(self, watchdog, tmp_heartbeat_file, tmp_state_dir):
        """Watchdog detects stale heartbeat and activates global kill."""
        # Write a heartbeat that's 60s old (stale > 30s threshold)
        _write_heartbeat(tmp_heartbeat_file, age_seconds=60)

        result = watchdog.check_once()

        # Should return False (stale detected, kill activated)
        assert result is False

        # Kill switch should be active
        ksm = KillSwitchManager(state_dir=tmp_state_dir)
        assert ksm.is_globally_killed()
        status = ksm.get_status()
        assert status["reason"] == "heartbeat_stale"
        assert status["triggered_by"] == "watchdog"

    def test_fresh_heartbeat_no_kill(self, watchdog, tmp_heartbeat_file, tmp_state_dir):
        """Watchdog does not activate kill when heartbeat is fresh."""
        _write_heartbeat(tmp_heartbeat_file, age_seconds=5)

        result = watchdog.check_once()
        assert result is True

        ksm = KillSwitchManager(state_dir=tmp_state_dir)
        assert not ksm.is_active()

    def test_missing_heartbeat_file_activates_kill(self, watchdog, tmp_state_dir):
        """Watchdog activates kill when heartbeat file doesn't exist."""
        # Don't write any heartbeat file
        result = watchdog.check_once()
        assert result is False

        ksm = KillSwitchManager(state_dir=tmp_state_dir)
        assert ksm.is_globally_killed()
        assert ksm.get_status()["reason"] == "heartbeat_stale"

    def test_clean_shutdown_no_kill(self, watchdog, tmp_heartbeat_file, tmp_state_dir):
        """Watchdog ignores stale heartbeat when engine_running=false (clean shutdown)."""
        _write_heartbeat(
            tmp_heartbeat_file, age_seconds=120, engine_running=False
        )

        result = watchdog.check_once()
        assert result is True

        ksm = KillSwitchManager(state_dir=tmp_state_dir)
        assert not ksm.is_active()

    def test_corrupt_heartbeat_file(self, watchdog, tmp_heartbeat_file, tmp_state_dir):
        """Watchdog handles corrupt heartbeat gracefully (treats as stale)."""
        Path(tmp_heartbeat_file).parent.mkdir(parents=True, exist_ok=True)
        Path(tmp_heartbeat_file).write_text("{ broken json")

        result = watchdog.check_once()
        assert result is False

        ksm = KillSwitchManager(state_dir=tmp_state_dir)
        assert ksm.is_globally_killed()

    def test_audit_log_entry_for_watchdog_trigger(self, watchdog, tmp_heartbeat_file, tmp_state_dir):
        """Verify audit log entry is created when watchdog triggers kill."""
        _write_heartbeat(tmp_heartbeat_file, age_seconds=60)

        watchdog.check_once()

        history_file = Path(tmp_state_dir) / "history.jsonl"
        assert history_file.exists()

        lines = history_file.read_text().strip().split("\n")
        event = json.loads(lines[-1])
        assert event["event"] == "activated"
        assert event["mode"] == "kill"
        assert event["reason"] == "heartbeat_stale"
        assert event["triggered_by"] == "watchdog"


# ── Watchdog: Weekend / Market Closed ────────────────────────────────────────

class TestWatchdogWeekend:
    def test_stale_heartbeat_ignored_on_saturday(self, watchdog, tmp_heartbeat_file, tmp_state_dir):
        """Watchdog ignores stale heartbeat on Saturday (market closed)."""
        _write_heartbeat(tmp_heartbeat_file, age_seconds=120)

        # Mock Saturday
        saturday = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)  # Saturday
        with patch("scripts.kill_switch_watchdog._is_forex_market_closed", return_value=True):
            result = watchdog.check_once()

        assert result is True

        ksm = KillSwitchManager(state_dir=tmp_state_dir)
        assert not ksm.is_active()

    def test_stale_heartbeat_ignored_friday_late(self, watchdog, tmp_heartbeat_file, tmp_state_dir):
        """Watchdog ignores stale heartbeat on Friday after 21:55 UTC."""
        _write_heartbeat(tmp_heartbeat_file, age_seconds=120)

        with patch("scripts.kill_switch_watchdog._is_forex_market_closed", return_value=True):
            result = watchdog.check_once()

        assert result is True

        ksm = KillSwitchManager(state_dir=tmp_state_dir)
        assert not ksm.is_active()

    def test_stale_heartbeat_ignored_sunday_early(self, watchdog, tmp_heartbeat_file, tmp_state_dir):
        """Watchdog ignores stale heartbeat on Sunday before 21:00 UTC."""
        _write_heartbeat(tmp_heartbeat_file, age_seconds=120)

        with patch("scripts.kill_switch_watchdog._is_forex_market_closed", return_value=True):
            result = watchdog.check_once()

        assert result is True

    def test_kill_not_re_triggered_on_weekend(self, watchdog, tmp_heartbeat_file, tmp_state_dir):
        """Verify no audit log entries are created during weekend."""
        _write_heartbeat(tmp_heartbeat_file, age_seconds=120)

        with patch("scripts.kill_switch_watchdog._is_forex_market_closed", return_value=True):
            watchdog.check_once()

        history_file = Path(tmp_state_dir) / "history.jsonl"
        if history_file.exists():
            content = history_file.read_text().strip()
            assert content == ""


# ── Watchdog: Market Hours Helper ────────────────────────────────────────────

class TestMarketHoursHelper:
    def test_saturday_is_closed(self):
        from scripts.kill_switch_watchdog import _is_forex_market_closed
        saturday = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
        assert _is_forex_market_closed(saturday) is True

    def test_tuesday_is_open(self):
        from scripts.kill_switch_watchdog import _is_forex_market_closed
        tuesday = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)
        assert _is_forex_market_closed(tuesday) is False

    def test_friday_before_close_is_open(self):
        from scripts.kill_switch_watchdog import _is_forex_market_closed
        friday_early = datetime(2026, 6, 5, 18, 0, 0, tzinfo=timezone.utc)
        assert _is_forex_market_closed(friday_early) is False

    def test_friday_at_close_is_closed(self):
        from scripts.kill_switch_watchdog import _is_forex_market_closed
        friday_close = datetime(2026, 6, 5, 21, 55, 0, tzinfo=timezone.utc)
        assert _is_forex_market_closed(friday_close) is True

    def test_friday_after_close_is_closed(self):
        from scripts.kill_switch_watchdog import _is_forex_market_closed
        friday_late = datetime(2026, 6, 5, 22, 30, 0, tzinfo=timezone.utc)
        assert _is_forex_market_closed(friday_late) is True

    def test_sunday_before_open_is_closed(self):
        from scripts.kill_switch_watchdog import _is_forex_market_closed
        sunday_early = datetime(2026, 6, 7, 18, 0, 0, tzinfo=timezone.utc)
        assert _is_forex_market_closed(sunday_early) is True

    def test_sunday_after_open_is_open(self):
        from scripts.kill_switch_watchdog import _is_forex_market_closed
        sunday_late = datetime(2026, 6, 7, 22, 0, 0, tzinfo=timezone.utc)
        assert _is_forex_market_closed(sunday_late) is False


# ── RiskGuard Circuit Breaker → Kill Switch ──────────────────────────────────

class TestRiskGuardKillSwitch:
    def test_daily_loss_breach_activates_kill(self, tmp_state_dir):
        """RiskGuard daily loss breach activates global kill switch."""
        with patch.dict("sys.modules"):
            rg = RiskGuard(
                ftmo_config=FTMOConfig(
                    daily_loss_limit_pct=0.05,
                    total_drawdown_limit_pct=0.10,
                ),
                starting_balance=100_000.0,
            )

        # Patch KillSwitchManager to use our tmp dir
        with patch(
            "adapters.ctrader.kill_switch.KillSwitchManager"
        ) as MockKS:
            mock_instance = MagicMock()
            MockKS.return_value = mock_instance

            # Simulate daily loss limit breach
            rg._current_balance = 94_000.0  # 6% loss > 5% limit
            rg._daily_start_balance = 100_000.0

            rg._trigger_circuit_breaker(
                RiskLimitType.DAILY_LOSS,
                current=0.06,
                limit=0.05,
            )

            # Verify kill switch was activated
            mock_instance.activate_global_kill.assert_called_once_with(
                "ftmo_daily_loss_limit", "risk_guard", close_positions=True
            )

    def test_total_drawdown_breach_activates_kill(self):
        """RiskGuard total drawdown breach activates global kill switch."""
        rg = RiskGuard(
            ftmo_config=FTMOConfig(
                daily_loss_limit_pct=0.05,
                total_drawdown_limit_pct=0.10,
            ),
            starting_balance=100_000.0,
        )

        with patch(
            "adapters.ctrader.kill_switch.KillSwitchManager"
        ) as MockKS:
            mock_instance = MagicMock()
            MockKS.return_value = mock_instance

            rg._trigger_circuit_breaker(
                RiskLimitType.TOTAL_DRAWDOWN,
                current=0.12,
                limit=0.10,
            )

            mock_instance.activate_global_kill.assert_called_once_with(
                "ftmo_total_drawdown", "risk_guard", close_positions=True
            )

    def test_risk_guard_failure_does_not_crash(self):
        """If kill switch activation raises, risk guard continues."""
        rg = RiskGuard(starting_balance=100_000.0)

        with patch(
            "adapters.ctrader.kill_switch.KillSwitchManager"
        ) as MockKS:
            mock_instance = MagicMock()
            mock_instance.activate_global_kill.side_effect = RuntimeError("boom")
            MockKS.return_value = mock_instance

            # Should NOT raise
            rg._trigger_circuit_breaker(
                RiskLimitType.DAILY_LOSS, 0.06, 0.05
            )

            # Risk guard circuit breaker should still be triggered
            assert rg._circuit_breaker_triggered is True

    def test_non_loss_breach_no_kill(self):
        """Non-loss circuit breaker (e.g. max_trades) does not activate kill."""
        rg = RiskGuard(starting_balance=100_000.0)

        with patch(
            "adapters.ctrader.kill_switch.KillSwitchManager"
        ) as MockKS:
            mock_instance = MagicMock()
            MockKS.return_value = mock_instance

            # MAX_TRADES is not DAILY_LOSS or TOTAL_DRAWDOWN
            rg._trigger_circuit_breaker(
                RiskLimitType.MAX_TRADES, 10, 10
            )

            mock_instance.activate_global_kill.assert_not_called()


# ── Feed Disconnect → Freeze ─────────────────────────────────────────────────

class TestFeedDisconnectFreeze:
    def _make_engine_mock(self, tmp_state_dir):
        """Create a mock engine with minimal attrs for feed health check."""
        from adapters.ctrader.forward_test_engine import (
            ForwardTestEngine,
            ForwardTestConfig,
        )

        config = ForwardTestConfig()
        # We can't fully construct the engine (needs strategies etc),
        # so we create a partial mock
        engine = ForwardTestEngine.__new__(ForwardTestEngine)
        engine._config = config
        engine._kill_switch = KillSwitchManager(state_dir=tmp_state_dir)
        engine._market_feed = MagicMock()
        engine._health = MagicMock()
        engine._health.last_tick_at = None
        engine._lock = __import__("threading").RLock()
        engine._feed_disconnect_frozen = False
        engine._running = True
        return engine

    @pytest.mark.xfail(reason="P5A scope-out: freeze activation code intentionally remains commented out per Phase 4 priority list. Tracked in P5A closeout.")
    def test_feed_disconnect_activates_freeze(self, tmp_state_dir):
        """Feed disconnect triggers GLOBAL FREEZE."""
        engine = self._make_engine_mock(tmp_state_dir)
        engine._market_feed.is_running = False
        engine._health.last_tick_at = None

        engine._check_feed_health_kill_switch()

        assert engine._kill_switch.is_globally_frozen()
        assert engine._kill_switch.get_status()["reason"] == "feed_disconnect"
        assert engine._feed_disconnect_frozen is True

    def test_feed_no_tick_yet_no_freeze(self, tmp_state_dir):
        """Feed connected but no tick yet should not freeze (still initializing)."""
        engine = self._make_engine_mock(tmp_state_dir)
        engine._market_feed.is_running = True
        engine._health.last_tick_at = None

        engine._check_feed_health_kill_switch()

        # Should NOT freeze — feed is still initializing
        assert not engine._kill_switch.is_active()

    @pytest.mark.xfail(reason="P5A scope-out: freeze activation code intentionally remains commented out per Phase 4 priority list. Tracked in P5A closeout.")
    def test_feed_reconnect_no_auto_recovery(self, tmp_state_dir):
        """Feed reconnect does NOT auto-recover (manual recovery required)."""
        engine = self._make_engine_mock(tmp_state_dir)
        engine._market_feed.is_running = False
        engine._health.last_tick_at = None

        # First: trigger freeze
        engine._check_feed_health_kill_switch()
        assert engine._kill_switch.is_globally_frozen()

        # Now: feed comes back
        engine._market_feed.is_running = True
        engine._health.last_tick_at = datetime.now(timezone.utc)

        engine._check_feed_health_kill_switch()

        # Kill switch should STILL be active (no auto-recovery)
        assert engine._kill_switch.is_globally_frozen()

    @pytest.mark.xfail(reason="P5A scope-out: freeze activation code intentionally remains commented out per Phase 4 priority list. Tracked in P5A closeout.")
    def test_feed_freeze_not_re_triggered(self, tmp_state_dir):
        """Feed disconnect freeze should not re-activate every cycle."""
        engine = self._make_engine_mock(tmp_state_dir)
        engine._market_feed.is_running = False
        engine._health.last_tick_at = None

        # First check
        engine._check_feed_health_kill_switch()
        assert engine._kill_switch.is_globally_frozen()

        # Second check — should not error or re-trigger
        engine._check_feed_health_kill_switch()
        assert engine._kill_switch.is_globally_frozen()


# ── Error Rate Monitor → Freeze ──────────────────────────────────────────────

class TestErrorRateFreeze:
    def _make_engine_mock(self, tmp_state_dir):
        """Create a mock engine with minimal attrs for error rate check."""
        from adapters.ctrader.forward_test_engine import (
            ForwardTestEngine,
            ForwardTestConfig,
        )

        engine = ForwardTestEngine.__new__(ForwardTestEngine)
        config = ForwardTestConfig()
        engine._config = config
        engine._kill_switch = KillSwitchManager(state_dir=tmp_state_dir)
        engine._eval_timestamps = deque()
        engine._eval_errors = deque()
        engine._lock = __import__("threading").RLock()
        engine._running = True
        return engine

    @pytest.mark.xfail(reason="P5A scope-out: freeze activation code intentionally remains commented out per Phase 4 priority list. Tracked in P5A closeout.")
    def test_high_error_rate_activates_freeze(self, tmp_state_dir):
        """Error rate > 50% in 60s window activates freeze."""
        engine = self._make_engine_mock(tmp_state_dir)

        # Simulate 10 evaluations, 6 errors (60% > 50%)
        now = time.monotonic()
        for i in range(10):
            engine._eval_timestamps.append(now - 1)
        for i in range(6):
            engine._eval_errors.append(now - 1)

        engine._check_error_rate()

        assert engine._kill_switch.is_globally_frozen()
        assert engine._kill_switch.get_status()["reason"] == "high_error_rate"

    def test_low_error_rate_no_freeze(self, tmp_state_dir):
        """Error rate <= 50% does NOT activate freeze."""
        engine = self._make_engine_mock(tmp_state_dir)

        now = time.monotonic()
        for i in range(10):
            engine._eval_timestamps.append(now - 1)
        for i in range(3):
            engine._eval_errors.append(now - 1)

        engine._check_error_rate()

        assert not engine._kill_switch.is_active()

    def test_too_few_evals_no_freeze(self, tmp_state_dir):
        """Fewer than 5 evaluations does not trigger freeze (not enough data)."""
        engine = self._make_engine_mock(tmp_state_dir)

        now = time.monotonic()
        for i in range(3):
            engine._eval_timestamps.append(now - 1)
        for i in range(3):
            engine._eval_errors.append(now - 1)

        engine._check_error_rate()

        assert not engine._kill_switch.is_active()

    def test_old_errors_pruned(self, tmp_state_dir):
        """Errors older than 60s window are pruned."""
        engine = self._make_engine_mock(tmp_state_dir)

        now = time.monotonic()
        # 5 old errors (90s ago)
        for i in range(5):
            engine._eval_timestamps.append(now - 90)
            engine._eval_errors.append(now - 90)

        # 5 recent successful evaluations (0 errors)
        for i in range(5):
            engine._eval_timestamps.append(now - 1)

        engine._check_error_rate()

        # Old errors should be pruned, current rate is 0%
        assert not engine._kill_switch.is_active()

    @pytest.mark.xfail(reason="P5A scope-out: freeze activation code intentionally remains commented out per Phase 4 priority list. Tracked in P5A closeout.")
    def test_counters_clear_after_freeze(self, tmp_state_dir):
        """Counters are cleared after freeze to prevent re-trigger every cycle."""
        engine = self._make_engine_mock(tmp_state_dir)

        now = time.monotonic()
        for i in range(10):
            engine._eval_timestamps.append(now - 1)
        for i in range(6):
            engine._eval_errors.append(now - 1)

        engine._check_error_rate()

        assert engine._kill_switch.is_globally_frozen()
        assert len(engine._eval_timestamps) == 0
        assert len(engine._eval_errors) == 0


# ── Heartbeat Atomic Write ───────────────────────────────────────────────────

class TestHeartbeatAtomicWrite:
    def _make_engine_mock(self, tmp_path, tmp_state_dir):
        from adapters.ctrader.forward_test_engine import (
            ForwardTestEngine,
            ForwardTestConfig,
        )

        engine = ForwardTestEngine.__new__(ForwardTestEngine)
        config = ForwardTestConfig()
        engine._config = config
        engine._kill_switch = KillSwitchManager(state_dir=tmp_state_dir)
        engine._heartbeat_file = str(tmp_path / "heartbeat_trading.json")
        engine._heartbeat_pid = 99999
        engine._health = MagicMock()
        engine._health.ticks_received = 500
        engine._running = True
        engine._lock = __import__("threading").RLock()
        return engine

    def test_heartbeat_atomic_write(self, tmp_path, tmp_state_dir):
        """Heartbeat file is written atomically and is valid JSON."""
        engine = self._make_engine_mock(tmp_path, tmp_state_dir)

        engine._write_heartbeat()

        heartbeat_path = Path(engine._heartbeat_file)
        assert heartbeat_path.exists()

        data = json.loads(heartbeat_path.read_text())
        assert "last_beat" in data
        assert data["pid"] == 99999
        assert data["ticks_received"] == 500
        assert data["engine_running"] is True

    def test_heartbeat_no_temp_files_left(self, tmp_path, tmp_state_dir):
        """No temp files left after heartbeat write."""
        engine = self._make_engine_mock(tmp_path, tmp_state_dir)

        engine._write_heartbeat()

        parent = Path(engine._heartbeat_file).parent
        tmp_files = list(parent.glob(".heartbeat_trading.*.tmp"))
        assert len(tmp_files) == 0

    def test_heartbeat_multiple_writes(self, tmp_path, tmp_state_dir):
        """Multiple rapid heartbeat writes produce valid file each time."""
        engine = self._make_engine_mock(tmp_path, tmp_state_dir)

        for i in range(20):
            engine._health.ticks_received = i * 100
            engine._write_heartbeat()

        data = json.loads(Path(engine._heartbeat_file).read_text())
        assert data["ticks_received"] == 1900

    def test_heartbeat_engine_not_running(self, tmp_path, tmp_state_dir):
        """Heartbeat reflects engine_running=false on clean shutdown."""
        engine = self._make_engine_mock(tmp_path, tmp_state_dir)
        engine._running = False

        engine._write_heartbeat()

        data = json.loads(Path(engine._heartbeat_file).read_text())
        assert data["engine_running"] is False


# ── Audit Log Entries for Auto-Triggers ──────────────────────────────────────

class TestAutoTriggerAuditLog:
    def test_watchdog_audit_log(self, watchdog, tmp_heartbeat_file, tmp_state_dir):
        """Watchdog trigger creates proper audit log entry."""
        _write_heartbeat(tmp_heartbeat_file, age_seconds=60)

        watchdog.check_once()

        history_file = Path(tmp_state_dir) / "history.jsonl"
        lines = history_file.read_text().strip().split("\n")
        event = json.loads(lines[-1])

        assert event["event"] == "activated"
        assert event["reason"] == "heartbeat_stale"
        assert event["triggered_by"] == "watchdog"
        assert event["mode"] == "kill"
        assert event["close_positions"] is True

    def test_multiple_auto_triggers_in_audit_log(self, watchdog, tmp_heartbeat_file, tmp_state_dir):
        """Multiple auto-triggers are all logged in audit history."""
        _write_heartbeat(tmp_heartbeat_file, age_seconds=60)
        watchdog.check_once()

        # Manually trigger freeze
        ksm = KillSwitchManager(state_dir=tmp_state_dir)
        ksm.activate_global_freeze("test_freeze", "test_suite")

        history_file = Path(tmp_state_dir) / "history.jsonl"
        lines = history_file.read_text().strip().split("\n")
        events = [json.loads(l) for l in lines]

        # Should have at least 2 events
        assert len(events) >= 2
        assert events[0]["reason"] == "heartbeat_stale"
        assert events[0]["triggered_by"] == "watchdog"
        assert events[1]["reason"] == "test_freeze"
