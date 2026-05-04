from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from engine.health_monitor import (
    HealthAlert,
    HealthAlertKind,
    HealthMonitor,
    HealthMonitorConfig,
    HealthSnapshot,
)


def _make_config(**overrides) -> HealthMonitorConfig:
    defaults = dict(
        data_silence_threshold_sec=5.0,
        zero_signal_tick_threshold=10,
        zero_pnl_variance_trade_threshold=5,
        check_interval_sec=0.1,
        min_uptime_before_alerts_sec=0.0,
    )
    defaults.update(overrides)
    return HealthMonitorConfig(**defaults)


class TestHealthMonitorDataSilence:
    def test_healthy_with_recent_ticks(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        mon.record_tick()
        alerts = mon.check()
        assert alerts == []
        assert mon.healthy is True

    def test_alerts_on_no_ticks_past_threshold(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        mon.record_tick(tick_at=datetime.now(timezone.utc) - timedelta(seconds=10))
        alerts = mon.check()
        assert len(alerts) == 1
        assert alerts[0].kind == HealthAlertKind.DATA_SILENCE
        assert mon.healthy is False

    def test_no_alert_below_min_uptime(self):
        mon = HealthMonitor(config=_make_config(min_uptime_before_alerts_sec=120.0))
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        alerts = mon.check()
        silence_alerts = [a for a in alerts if a.kind == HealthAlertKind.DATA_SILENCE]
        assert silence_alerts == []

    def test_no_ticks_at_all_past_threshold(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        alerts = mon.check()
        assert any(a.kind == HealthAlertKind.DATA_SILENCE for a in alerts)

    def test_alert_callback_fired(self):
        collected = []
        mon = HealthMonitor(config=_make_config(), on_alert=collected.append)
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        mon.record_tick(tick_at=datetime.now(timezone.utc) - timedelta(seconds=10))
        mon.check()
        assert len(collected) == 1
        assert collected[0].kind == HealthAlertKind.DATA_SILENCE


class TestHealthMonitorZeroSignals:
    def test_healthy_when_ticks_below_threshold(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        for _ in range(5):
            mon.record_tick()
        alerts = mon.check()
        signal_alerts = [a for a in alerts if a.kind == HealthAlertKind.ZERO_SIGNALS]
        assert signal_alerts == []

    def test_alerts_on_zero_signals_after_threshold_ticks(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        for _ in range(10):
            mon.record_tick()
        alerts = mon.check()
        assert any(a.kind == HealthAlertKind.ZERO_SIGNALS for a in alerts)

    def test_no_alert_when_signals_exist(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        for _ in range(10):
            mon.record_tick()
        mon.record_signal()
        alerts = mon.check()
        signal_alerts = [a for a in alerts if a.kind == HealthAlertKind.ZERO_SIGNALS]
        assert signal_alerts == []


class TestHealthMonitorZeroPnLVariance:
    def test_healthy_when_fewer_trades_than_threshold(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        for _ in range(3):
            mon.record_trade_pnl(0.0)
        alerts = mon.check()
        pnl_alerts = [a for a in alerts if a.kind == HealthAlertKind.ZERO_PNL_VARIANCE]
        assert pnl_alerts == []

    def test_alerts_on_zero_variance(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        for _ in range(5):
            mon.record_trade_pnl(0.0)
        alerts = mon.check()
        assert any(a.kind == HealthAlertKind.ZERO_PNL_VARIANCE for a in alerts)
        assert mon.healthy is False

    def test_no_alert_with_varying_pnl(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        mon.record_trade_pnl(10.0)
        mon.record_trade_pnl(-5.0)
        mon.record_trade_pnl(20.0)
        mon.record_trade_pnl(-3.0)
        mon.record_trade_pnl(7.0)
        alerts = mon.check()
        pnl_alerts = [a for a in alerts if a.kind == HealthAlertKind.ZERO_PNL_VARIANCE]
        assert pnl_alerts == []


class TestHealthMonitorSnapshot:
    def test_snapshot_reflects_state(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        mon.record_tick()
        mon.record_signal()
        mon.record_trade_pnl(5.0)
        snap = mon.get_snapshot()
        assert snap.ticks_received == 1
        assert snap.signals_generated == 1
        assert snap.trades_completed == 1

    def test_reset_clears_alerts(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        mon.record_tick(tick_at=datetime.now(timezone.utc) - timedelta(seconds=10))
        mon.check()
        assert mon.healthy is False
        mon.reset_alerts()
        assert mon.healthy is True
        assert mon.get_snapshot().alerts == []


class TestHealthMonitorThreadSafety:
    def test_concurrent_recording(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)

        def record_ticks(n):
            for _ in range(n):
                mon.record_tick()

        threads = [
            threading.Thread(target=record_ticks, args=(100,)) for _ in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = mon.get_snapshot()
        assert snap.ticks_received == 1000

    def test_start_stop_lifecycle(self):
        mon = HealthMonitor(config=_make_config(check_interval_sec=0.05))
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        mon.record_tick()
        mon.start()
        time.sleep(0.15)
        snap = mon.get_snapshot()
        assert snap.last_check_at is not None
        mon.stop()
        assert mon._thread is None


class TestHealthMonitorFailSafe:
    def test_check_exception_does_not_propagate(self):
        mon = HealthMonitor(config=_make_config())
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)

        original = mon._check_data_silence
        mon._check_data_silence = lambda: (_ for _ in ()).throw(RuntimeError("boom"))

        alerts = mon.check()
        assert isinstance(alerts, list)

    def test_callback_exception_does_not_propagate(self):
        def bad_callback(alert):
            raise RuntimeError("callback boom")

        mon = HealthMonitor(config=_make_config(), on_alert=bad_callback)
        mon._start_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        mon.record_tick(tick_at=datetime.now(timezone.utc) - timedelta(seconds=10))
        alerts = mon.check()
        assert len(alerts) == 1
