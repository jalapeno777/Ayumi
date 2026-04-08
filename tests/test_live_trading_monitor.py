import importlib.util
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "live_trading_monitor.py"
spec = importlib.util.spec_from_file_location("live_trading_monitor", SCRIPT_PATH)
live_trading_monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live_trading_monitor)
sys.modules["scripts.live_trading_monitor"] = live_trading_monitor

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


class TestPostAlertToPaperclip:
    def test_no_credentials_logs_warning(self, caplog):
        post_alert = live_trading_monitor.post_alert_to_paperclip
        alert = Alert(
            severity="critical",
            check_type="health",
            message="Test alert",
            details={},
        )
        with patch.object(live_trading_monitor, "PAPERCLIP_ALERT_KEY", ""):
            result = post_alert(alert, "test-issue-id")
        assert result is False
        assert "Paperclip credentials not configured" in caplog.text

    def test_missing_issue_id(self, caplog):
        post_alert = live_trading_monitor.post_alert_to_paperclip
        alert = Alert(
            severity="warning",
            check_type="health",
            message="Test alert",
            details={},
        )
        with patch.object(live_trading_monitor, "PAPERCLIP_ALERT_KEY", "test-key"):
            result = post_alert(alert, "")
        assert result is False

    def test_http_error_returns_false(self, caplog):
        post_alert = live_trading_monitor.post_alert_to_paperclip
        alert = Alert(
            severity="critical",
            check_type="circuit",
            message="Circuit breaker triggered",
            details={},
        )
        with patch.object(live_trading_monitor, "PAPERCLIP_ALERT_KEY", "test-key"):
            with patch("httpx.post") as mock_post:
                mock_post.side_effect = Exception("Network error")
                result = post_alert(alert, "test-issue-id")
        assert result is False
        assert "Error posting to Paperclip" in caplog.text


class TestCheckFixConnection:
    def test_no_credentials_configured(self):
        check_fix = live_trading_monitor.check_fix_connection
        with patch.dict(
            os.environ, {"CTRADER_HOST": "", "CTRADER_SSL_PORT": "5212"}, clear=False
        ):
            os.environ.pop("CTRADER_HOST", None)
            result = check_fix()
        assert result.severity == "warning"
        assert "not configured" in result.message

    def test_invalid_port(self):
        check_fix = live_trading_monitor.check_fix_connection
        with patch.dict(
            os.environ, {"CTRADER_HOST": "test.host", "CTRADER_SSL_PORT": "not-a-port"}
        ):
            result = check_fix()
        assert result.severity == "warning"
        assert "Invalid port" in result.message

    def test_connection_timeout(self):
        check_fix = live_trading_monitor.check_fix_connection
        with patch.dict(
            os.environ,
            {
                "CTRADER_HOST": "127.0.0.1",
                "CTRADER_SSL_PORT": "59999",
                "CTRADER_VERIFY_SSL": "false",
            },
        ):
            with patch("ssl.SSLContext.wrap_socket") as mock_wrap:
                mock_wrap.side_effect = socket.timeout("timed out")
                result = check_fix()
        assert result.severity == "critical"
        assert "timeout" in result.message.lower()

    def test_connection_refused(self):
        check_fix = live_trading_monitor.check_fix_connection
        with patch.dict(
            os.environ,
            {
                "CTRADER_HOST": "127.0.0.1",
                "CTRADER_SSL_PORT": "59999",
                "CTRADER_VERIFY_SSL": "false",
            },
        ):
            with patch("ssl.SSLContext.wrap_socket") as mock_wrap:
                mock_wrap.side_effect = ConnectionRefusedError
                result = check_fix()
        assert result.severity == "critical"
        assert "refused" in result.message.lower()


class TestFTMOStartingBalance:
    def test_default_balance(self):
        state = TradingState()
        assert state.starting_balance == 100000.0
        assert state.daily_starting_balance == 100000.0

    def test_custom_balance_via_constructor(self):
        state = TradingState(
            starting_balance=50000.0,
            current_balance=50000.0,
            daily_starting_balance=50000.0,
        )
        assert state.starting_balance == 50000.0
        assert state.daily_starting_balance == 50000.0


class TestResetDailyStats:
    def test_resets_on_new_day(self):
        reset_func = live_trading_monitor.reset_daily_stats_if_new_day
        state = TradingState(
            current_balance=95000.0,
            daily_trades=5,
            daily_wins=3,
            daily_losses=2,
            daily_pnl=-5000.0,
            circuit_breaker_triggered=True,
            last_trading_date="2024-01-01",
        )
        with patch.object(live_trading_monitor, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(
                2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc
            )
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            result = reset_func(state)
        assert result is True
        assert state.daily_starting_balance == 95000.0
        assert state.daily_trades == 0
        assert state.circuit_breaker_triggered is False
        assert state.last_trading_date == "2024-01-02"

    def test_no_reset_same_day(self):
        reset_func = live_trading_monitor.reset_daily_stats_if_new_day
        state = TradingState(
            current_balance=95000.0,
            daily_trades=5,
            circuit_breaker_triggered=True,
            last_trading_date="2024-01-01",
        )
        with patch.object(live_trading_monitor, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(
                2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc
            )
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            result = reset_func(state)
        assert result is False
        assert state.daily_trades == 5
        assert state.circuit_breaker_triggered is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
