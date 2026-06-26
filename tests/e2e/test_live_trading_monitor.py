import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from _project_root import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "scripts" / "live_trading_monitor.py"
spec = importlib.util.spec_from_file_location("live_trading_monitor", SCRIPT_PATH)
live_trading_monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live_trading_monitor)


@pytest.fixture(autouse=True)
def _register_live_trading_monitor(monkeypatch):
    """Register live_trading_monitor in sys.modules via monkeypatch (auto-restored)."""
    monkeypatch.setitem(sys.modules, "scripts.live_trading_monitor", live_trading_monitor)


TradingState = live_trading_monitor.TradingState
Alert = live_trading_monitor.Alert
CheckType = live_trading_monitor.CheckType
check_process_health = live_trading_monitor.check_process_health
check_last_trade_time = live_trading_monitor.check_last_trade_time
check_daily_pnl = live_trading_monitor.check_daily_pnl
check_circuit_breaker = live_trading_monitor.check_circuit_breaker
is_active_trading_hours = live_trading_monitor.is_active_trading_hours
load_state = live_trading_monitor.load_state
save_state = live_trading_monitor.save_state


class TestTradingState:
    def test_default_state(self):
        state = TradingState()
        assert state.pid is None
        assert state.last_trade_time is None
        assert state.starting_balance == 100000.0
        assert state.current_balance == 100000.0
        assert state.daily_trades == 0
        assert state.circuit_breaker_triggered is False

    def test_state_with_values(self):
        state = TradingState(
            pid=12345,
            last_trade_time=datetime.now(timezone.utc).isoformat(),
            current_balance=95000.0,
            daily_trades=5,
            daily_wins=3,
            daily_losses=2,
        )
        assert state.pid == 12345
        assert state.current_balance == 95000.0
        assert state.daily_trades == 5


class TestAlert:
    def test_alert_creation(self):
        alert = Alert(
            severity="critical",
            check_type="circuit",
            message="Circuit breaker triggered",
            details={"loss_pct": 6.5},
        )
        assert alert.severity == "critical"
        assert alert.check_type == "circuit"
        assert alert.message == "Circuit breaker triggered"
        assert alert.details["loss_pct"] == 6.5


class TestCheckProcessHealth:
    def test_no_pid_file(self, tmp_path):
        pid_file = tmp_path / "trading_bot.pid"
        state = TradingState()

        with patch.object(live_trading_monitor, "PID_FILE", pid_file):
            result = check_process_health(state)

        assert result.severity == "warning"
        assert "No PID file found" in result.message

    def test_valid_pid(self, tmp_path):
        pid_file = tmp_path / "trading_bot.pid"
        pid_file.write_text(str(os.getpid()))

        state = TradingState()

        with patch.object(live_trading_monitor, "PID_FILE", pid_file):
            result = check_process_health(state)

        assert result.severity == "info"
        assert os.getpid() == result.details["pid"]


class TestCheckLastTradeTime:
    def test_no_trades_recorded(self):
        state = TradingState()
        result = check_last_trade_time(state)

        assert result.severity == "warning"
        assert "No trades recorded" in result.message

    def test_recent_trade(self):
        state = TradingState(last_trade_time=datetime.now(timezone.utc).isoformat())
        result = check_last_trade_time(state)

        assert result.severity == "info"
        assert "hours ago" in result.message


class TestCheckDailyPnL:
    def test_no_significant_change(self):
        state = TradingState(
            starting_balance=100000.0,
            current_balance=100000.0,
            daily_trades=0,
        )
        result = check_daily_pnl(state)

        assert result.severity == "info"
        assert "0.00" in result.message

    def test_profitable_day(self):
        state = TradingState(
            starting_balance=100000.0,
            current_balance=101000.0,
            daily_trades=5,
            daily_wins=3,
            daily_losses=2,
        )
        result = check_daily_pnl(state)

        assert result.severity == "info"
        assert "+$1000.00" in result.message or "+1.00%" in result.message

    def test_circuit_breaker_triggered(self):
        state = TradingState(
            starting_balance=100000.0,
            current_balance=94000.0,
            circuit_breaker_triggered=True,
        )
        result = check_daily_pnl(state)

        assert result.severity == "critical"
        assert "CIRCUIT BREAKER" in result.message


class TestCheckCircuitBreaker:
    def test_within_limits(self):
        state = TradingState(
            starting_balance=100000.0,
            current_balance=99000.0,
        )
        result = check_circuit_breaker(state)

        assert result.severity == "info"
        assert "OK" in result.message
        assert state.circuit_breaker_triggered is False

    def test_exceeds_ftmo_limit(self):
        state = TradingState(
            starting_balance=100000.0,
            current_balance=94000.0,
        )
        result = check_circuit_breaker(state)

        assert result.severity == "critical"
        assert "CIRCUIT BREAKER" in result.message
        assert state.circuit_breaker_triggered is True


class TestIsActiveTradingHours:
    def test_within_active_hours(self):
        with patch.object(live_trading_monitor, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(
                2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc
            )
            assert is_active_trading_hours() is True

    def test_outside_active_hours_early(self):
        with patch.object(live_trading_monitor, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(
                2024, 1, 1, 3, 0, 0, tzinfo=timezone.utc
            )
            assert is_active_trading_hours() is False

    def test_outside_active_hours_late(self):
        with patch.object(live_trading_monitor, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(
                2024, 1, 1, 23, 0, 0, tzinfo=timezone.utc
            )
            assert is_active_trading_hours() is False


class TestStatePersistence:
    def test_save_and_load_state(self, tmp_path):
        state_file = tmp_path / "trading_state.json"

        original_state = TradingState(
            pid=12345,
            last_trade_time=datetime.now(timezone.utc).isoformat(),
            starting_balance=100000.0,
            current_balance=95000.0,
            daily_trades=10,
            daily_wins=6,
            daily_losses=4,
            circuit_breaker_triggered=True,
        )

        with patch.object(live_trading_monitor, "STATE_FILE", state_file):
            save_state(original_state)
            loaded_state = load_state()

        assert loaded_state.pid == 12345
        assert loaded_state.current_balance == 95000.0
        assert loaded_state.daily_trades == 10
        assert loaded_state.circuit_breaker_triggered is True

    def test_load_invalid_state(self, tmp_path):
        state_file = tmp_path / "trading_state.json"
        state_file.write_text("invalid json{{{")

        with patch.object(live_trading_monitor, "STATE_FILE", state_file):
            state = load_state()

        assert state.starting_balance == 100000.0


class TestCheckType:
    def test_check_type_values(self):
        assert CheckType.HEALTH.value == "health"
        assert CheckType.TRADE_TIME.value == "trade_time"
        assert CheckType.DAILY_PNL.value == "daily_pnl"
        assert CheckType.CIRCUIT.value == "circuit"
        assert CheckType.CONNECTION.value == "connection"
        assert CheckType.ALL.value == "all"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
