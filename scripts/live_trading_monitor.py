#!/usr/bin/env python3
"""
Live Trading Monitor and Alert System

Monitors:
1. Health check: verify trading process is running
2. Last trade time: alert if no trade in 24 hours during active trading hours
3. Daily P&L summary: equity change, trades taken, win rate
4. Circuit breaker alerts: notify if daily loss exceeds FTMO 5% limit
5. FIX connection monitoring: alert if connection drops

Usage:
    python live_trading_monitor.py [--check-type TYPE]

Check types:
    health       - Process health check only
    trade_time   - Last trade time check
    daily_pnl    - Daily P&L summary
    circuit      - Circuit breaker status
    connection   - FIX connection check
    all          - All checks (default)
"""

import argparse
import json
import logging
import os
import socket
import ssl
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


STATE_FILE = Path(__file__).parent.parent / "data" / "trading_state.json"
PID_FILE = Path(__file__).parent.parent / "data" / "trading_bot.pid"


def load_dotenv():
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                os.environ.setdefault(key, val)


load_dotenv()


PAPERCLIP_API_URL = os.environ.get("PAPERCLIP_API_URL", "http://localhost:3101")
PAPERCLIP_ALERT_KEY = os.environ.get(
    "PAPERCLIP_ALERT_KEY", os.environ.get("PAPERCLIP_API_KEY", "")
)
PAPERCLIP_ISSUE_ID = os.environ.get("PAPERCLIP_ISSUE_ID", "")


FTMO_DAILY_LOSS_LIMIT = 0.05
NO_TRADE_ALERT_HOURS = 24
ACTIVE_TRADING_HOURS = (6, 22)
DEFAULT_STARTING_BALANCE = float(os.environ.get("FTMO_STARTING_BALANCE", "100000"))


class CheckType(Enum):
    HEALTH = "health"
    TRADE_TIME = "trade_time"
    DAILY_PNL = "daily_pnl"
    CIRCUIT = "circuit"
    CONNECTION = "connection"
    ALL = "all"


@dataclass
class TradingState:
    pid: Optional[int] = None
    last_trade_time: Optional[str] = None
    last_check_time: Optional[str] = None
    starting_balance: float = DEFAULT_STARTING_BALANCE
    daily_starting_balance: float = DEFAULT_STARTING_BALANCE
    current_balance: float = DEFAULT_STARTING_BALANCE
    daily_trades: int = 0
    daily_wins: int = 0
    daily_losses: int = 0
    daily_pnl: float = 0.0
    circuit_breaker_triggered: bool = False
    last_circuit_breaker_check: Optional[str] = None


STATE_ALLOWLIST = {
    "pid",
    "last_trade_time",
    "last_check_time",
    "starting_balance",
    "daily_starting_balance",
    "current_balance",
    "daily_trades",
    "daily_wins",
    "daily_losses",
    "daily_pnl",
    "circuit_breaker_triggered",
    "last_circuit_breaker_check",
}


@dataclass
class Alert:
    severity: str
    check_type: str
    message: str
    details: dict = field(default_factory=dict)


def load_state() -> TradingState:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            return TradingState(**data)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to load state: {e}")
    return TradingState()


def save_state(state: TradingState):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(
            {
                "pid": state.pid,
                "last_trade_time": state.last_trade_time,
                "last_check_time": state.last_check_time,
                "starting_balance": state.starting_balance,
                "daily_starting_balance": state.daily_starting_balance,
                "current_balance": state.current_balance,
                "daily_trades": state.daily_trades,
                "daily_wins": state.daily_wins,
                "daily_losses": state.daily_losses,
                "daily_pnl": state.daily_pnl,
                "circuit_breaker_triggered": state.circuit_breaker_triggered,
                "last_circuit_breaker_check": state.last_circuit_breaker_check,
            },
            indent=2,
        )
    )


def check_process_health(state: TradingState) -> Alert:
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            state.pid = pid
            return Alert(
                severity="info",
                check_type="health",
                message=f"Trading process is running (PID: {pid})",
                details={"pid": pid},
            )
        except (ValueError, ProcessLookupError, PermissionError) as e:
            return Alert(
                severity="warning",
                check_type="health",
                message="Trading process not running or PID file invalid",
                details={"error": str(e)},
            )
    return Alert(
        severity="warning",
        check_type="health",
        message="No PID file found - trading process may not be running",
        details={},
    )


def is_active_trading_hours() -> bool:
    now = datetime.now(timezone.utc)
    return ACTIVE_TRADING_HOURS[0] <= now.hour < ACTIVE_TRADING_HOURS[1]


def check_last_trade_time(state: TradingState) -> Alert:
    if not state.last_trade_time:
        return Alert(
            severity="warning",
            check_type="trade_time",
            message="No trades recorded yet",
            details={},
        )

    last_trade = datetime.fromisoformat(state.last_trade_time)
    hours_since_trade = (datetime.now(timezone.utc) - last_trade).total_seconds() / 3600

    if is_active_trading_hours() and hours_since_trade > NO_TRADE_ALERT_HOURS:
        return Alert(
            severity="critical",
            check_type="trade_time",
            message=f"No trade in {hours_since_trade:.1f} hours during active trading hours",
            details={
                "hours_since_trade": hours_since_trade,
                "last_trade": state.last_trade_time,
            },
        )

    return Alert(
        severity="info",
        check_type="trade_time",
        message=f"Last trade {hours_since_trade:.1f} hours ago",
        details={
            "hours_since_trade": hours_since_trade,
            "last_trade": state.last_trade_time,
        },
    )


def check_daily_pnl(state: TradingState) -> Alert:
    equity_change = state.current_balance - state.daily_starting_balance
    equity_change_pct = (
        (equity_change / state.daily_starting_balance) * 100
        if state.daily_starting_balance > 0
        else 0
    )

    win_rate = (
        (state.daily_wins / state.daily_trades * 100) if state.daily_trades > 0 else 0
    )

    if state.circuit_breaker_triggered:
        return Alert(
            severity="critical",
            check_type="daily_pnl",
            message=f"CIRCUIT BREAKER TRIGGERED - Daily loss limit ({FTMO_DAILY_LOSS_LIMIT * 100}%) exceeded",
            details={
                "daily_pnl": state.daily_pnl,
                "equity_change": equity_change,
                "equity_change_pct": equity_change_pct,
                "trades": state.daily_trades,
                "wins": state.daily_wins,
                "losses": state.daily_losses,
                "win_rate": win_rate,
            },
        )

    if abs(equity_change_pct) > 0.1:
        return Alert(
            severity="info",
            check_type="daily_pnl",
            message=f"Daily P&L: ${equity_change:.2f} ({equity_change_pct:+.2f}%) | Trades: {state.daily_trades} | Win rate: {win_rate:.0f}%",
            details={
                "daily_pnl": state.daily_pnl,
                "equity_change": equity_change,
                "equity_change_pct": equity_change_pct,
                "trades": state.daily_trades,
                "wins": state.daily_wins,
                "losses": state.daily_losses,
                "win_rate": win_rate,
            },
        )

    return Alert(
        severity="info",
        check_type="daily_pnl",
        message="Daily P&L: $0.00 (0.00%) | No significant changes",
        details={
            "daily_pnl": 0,
            "equity_change": 0,
            "equity_change_pct": 0,
            "trades": state.daily_trades,
            "wins": state.daily_wins,
            "losses": state.daily_losses,
            "win_rate": win_rate,
        },
    )


def check_circuit_breaker(state: TradingState) -> Alert:
    daily_loss_pct = (
        (state.daily_starting_balance - state.current_balance)
        / state.daily_starting_balance
        if state.daily_starting_balance > 0
        else 0
    )

    if daily_loss_pct >= FTMO_DAILY_LOSS_LIMIT:
        state.circuit_breaker_triggered = True
        state.last_circuit_breaker_check = datetime.now(timezone.utc).isoformat()
        return Alert(
            severity="critical",
            check_type="circuit",
            message=f"CIRCUIT BREAKER: Daily loss {daily_loss_pct * 100:.2f}% exceeds FTMO limit {FTMO_DAILY_LOSS_LIMIT * 100}%",
            details={
                "daily_loss_pct": daily_loss_pct,
                "ftmo_limit_pct": FTMO_DAILY_LOSS_LIMIT * 100,
                "balance": state.current_balance,
                "starting_balance": state.starting_balance,
            },
        )

    if state.circuit_breaker_triggered:
        return Alert(
            severity="warning",
            check_type="circuit",
            message="Circuit breaker already triggered - trading paused",
            details={
                "daily_loss_pct": daily_loss_pct,
                "triggered_at": state.last_circuit_breaker_check,
            },
        )

    return Alert(
        severity="info",
        check_type="circuit",
        message=f"Circuit breaker OK - Daily loss {daily_loss_pct * 100:.2f}% within limit",
        details={
            "daily_loss_pct": daily_loss_pct,
            "ftmo_limit_pct": FTMO_DAILY_LOSS_LIMIT * 100,
        },
    )


def check_fix_connection() -> Alert:
    host = os.environ.get("CTRADER_HOST")
    port_str = os.environ.get("CTRADER_SSL_PORT", "5212")

    if not host or not port_str:
        return Alert(
            severity="warning",
            check_type="connection",
            message="cTrader credentials not configured",
            details={},
        )

    try:
        port = int(port_str)
    except ValueError:
        return Alert(
            severity="warning",
            check_type="connection",
            message=f"Invalid port configured: {port_str}",
            details={"host": host, "port_str": port_str},
        )

    verify_ssl = os.environ.get("CTRADER_VERIFY_SSL", "true").lower() != "false"

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            if verify_ssl:
                ssl_context = ssl.create_default_context()
            else:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            ssl_sock = ssl_context.wrap_socket(sock, server_hostname=host)
            try:
                ssl_sock.connect((host, port))
                return Alert(
                    severity="info",
                    check_type="connection",
                    message=f"FIX connection to {host}:{port} successful",
                    details={"host": host, "port": port},
                )
            finally:
                ssl_sock.close()
        finally:
            sock.close()
    except socket.timeout:
        return Alert(
            severity="critical",
            check_type="connection",
            message=f"FIX connection timeout to {host}:{port}",
            details={"host": host, "port": port},
        )
    except ConnectionRefusedError:
        return Alert(
            severity="critical",
            check_type="connection",
            message=f"FIX connection refused - {host}:{port}",
            details={"host": host, "port": port},
        )
    except Exception as e:
        return Alert(
            severity="critical",
            check_type="connection",
            message=f"FIX connection error: {e}",
            details={"host": host, "port": port, "error": str(e)},
        )


def post_alert_to_paperclip(alert: Alert, issue_id: str) -> bool:
    if not PAPERCLIP_ALERT_KEY or not issue_id:
        logger.warning("Paperclip credentials not configured")
        return False

    headers = {
        "Authorization": f"Bearer {PAPERCLIP_ALERT_KEY}",
        "Content-Type": "application/json",
    }

    emoji = {
        "critical": "🚨",
        "warning": "⚠️",
        "info": "ℹ️",
    }.get(alert.severity, "ℹ️")

    comment_body = f"""## Live Trading Monitor Alert {emoji}

**Check:** {alert.check_type}
**Severity:** {alert.severity.upper()}
**Time:** {datetime.now(timezone.utc).isoformat()}

**Message:** {alert.message}

**Details:**
```
{json.dumps(alert.details, indent=2)}
```
"""

    try:
        response = httpx.post(
            f"{PAPERCLIP_API_URL}/api/issues/{issue_id}/comments",
            headers=headers,
            json={"body": comment_body},
            timeout=10,
        )
        if response.status_code in (200, 201):
            logger.info(
                f"Alert posted to Paperclip: {alert.check_type} - {alert.message}"
            )
            return True
        else:
            logger.error(
                f"Failed to post alert: {response.status_code} {response.text}"
            )
            return False
    except Exception as e:
        logger.error(f"Error posting to Paperclip: {e}")
        return False


def run_check(
    check_type: CheckType, state: TradingState, dry_run: bool = False
) -> list[Alert]:
    alerts = []

    if check_type == CheckType.HEALTH:
        alerts.append(check_process_health(state))
    elif check_type == CheckType.TRADE_TIME:
        alerts.append(check_last_trade_time(state))
    elif check_type == CheckType.DAILY_PNL:
        alerts.append(check_daily_pnl(state))
    elif check_type == CheckType.CIRCUIT:
        alerts.append(check_circuit_breaker(state))
    elif check_type == CheckType.CONNECTION:
        alerts.append(check_fix_connection())
    elif check_type == CheckType.ALL:
        alerts.append(check_process_health(state))
        alerts.append(check_last_trade_time(state))
        alerts.append(check_daily_pnl(state))
        alerts.append(check_circuit_breaker(state))
        alerts.append(check_fix_connection())

    if not dry_run and PAPERCLIP_ISSUE_ID:
        for alert in alerts:
            if alert.severity in ("critical", "warning"):
                post_alert_to_paperclip(alert, PAPERCLIP_ISSUE_ID)

    return alerts


def main():
    parser = argparse.ArgumentParser(description="Live Trading Monitor")
    parser.add_argument(
        "--check-type",
        type=str,
        choices=["health", "trade_time", "daily_pnl", "circuit", "connection", "all"],
        default="all",
        help="Type of check to run",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Don't post to Paperclip"
    )
    parser.add_argument(
        "--update-state", type=str, help="Update state from JSON string"
    )
    args = parser.parse_args()

    state = load_state()

    if args.update_state:
        try:
            updates = json.loads(args.update_state)
            for key, value in updates.items():
                if key in STATE_ALLOWLIST:
                    setattr(state, key, value)
            save_state(state)
            logger.info(f"State updated: {updates}")
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to update state: {e}")
            return 1

    check_type = CheckType(args.check_type)
    alerts = run_check(check_type, state, dry_run=args.dry_run)

    for alert in alerts:
        print(f"[{alert.severity.upper()}] {alert.check_type}: {alert.message}")

    state.last_check_time = datetime.now(timezone.utc).isoformat()
    save_state(state)

    critical_count = sum(1 for a in alerts if a.severity == "critical")
    return 0 if critical_count == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
