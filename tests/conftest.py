"""Shared pytest fixtures for the Ayumi test suite.

Provides memory-safe, production-isolated fixtures for common components.
All fixtures use temporary paths or mocks — nothing writes to production state.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure src path is available
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "forex-bot"))


# ── Kill Switch ────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_state_dir(tmp_path):
    """Temporary state directory (never writes to production data/kill_switches)."""
    d = tmp_path / "kill_switches"
    d.mkdir()
    return str(d)


@pytest.fixture
def mock_kill_switch(tmp_state_dir):
    """KillSwitchManager with temp state dir — never triggers, no production writes.

    Uses the real KillSwitchManager pointed at a temp directory so state
    persistence logic is exercised, but nothing touches production paths.
    """
    from adapters.ctrader.kill_switch import KillSwitchManager
    return KillSwitchManager(state_dir=tmp_state_dir)


# ── Auth ───────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_auth():
    """CTraderAuth with fake credentials and all methods mocked.

    No network calls, no real credential files.
    """
    from adapters.ctrader.auth import CTraderAuth

    auth = MagicMock(spec=CTraderAuth)
    auth.access_token = "test_access_token_abc123"
    auth.refresh_token = "test_refresh_token_xyz789"
    auth.client_id = "18449_test_client_id"
    auth.client_secret = "test_secret_value"
    auth.account_id = 46877902
    auth.trader_login = "5795523"
    auth.app_authenticate = MagicMock()
    auth.account_authenticate = MagicMock()
    auth.update_tokens = MagicMock()
    auth.load_credentials = MagicMock(return_value={
        "access_token": "test_access_token_abc123",
        "refresh_token": "test_refresh_token_xyz789",
    })
    auth.validate_startup = MagicMock(return_value={
        "status": "ok",
        "token_hash": "test_acc",
    })
    return auth


# ── Connection ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_connection():
    """CTraderConnection with async mocks for connect/disconnect/send.

    No real TCP connections or network calls.
    """
    conn = MagicMock()
    conn.is_connected = False
    conn.connect = AsyncMock()
    conn.disconnect = AsyncMock()
    conn.send = AsyncMock()
    conn._socket = None
    return conn


# ── Risk Guard ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_risk_guard(mock_kill_switch):
    """RiskGuard with injected mock_kill_switch.

    Uses real FTMOConfig defaults but cannot trigger production kill switches.
    """
    from adapters.ctrader.risk_guard import FTMOConfig, RiskGuard
    rg = RiskGuard(ftmo_config=FTMOConfig(), starting_balance=100000.0)
    rg.set_kill_switch(mock_kill_switch)
    return rg


# ── Bar Builder ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_bar_builder():
    """Mock BarBuilder with fake tick data.

    BarBuilder is not a real class yet — this fixture provides a typed mock
    that can be updated when a concrete implementation lands.
    """
    bb = MagicMock()
    bb.add_tick = MagicMock()
    bb.get_completed_bars = MagicMock(return_value=[])
    bb.current_bar = MagicMock()
    return bb
