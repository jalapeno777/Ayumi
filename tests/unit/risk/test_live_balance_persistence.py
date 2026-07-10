"""Unit tests for live-balance persistence between cTrader sync intervals.

Tests the fix for the balance oscillation bug where
PaperTrader.update_market_prices recalculates _current_balance from
starting_balance on every tick, overwriting the live-synced balance.
"""

import json
from pathlib import Path

import pytest

from adapters.ctrader.risk_guard import FTMOConfig, RiskGuard


@pytest.fixture
def tmp_state_path(tmp_path):
    """Return a temporary state file path that won't clobber production."""
    return str(tmp_path / "test_risk_guard_state.json")


@pytest.fixture
def guard(tmp_state_path):
    """Fresh RiskGuard with $10K starting balance."""
    return RiskGuard(
        ftmo_config=FTMOConfig(),
        starting_balance=10_000.0,
        state_path=tmp_state_path,
    )


class TestLiveBalanceMode:
    """Tests for sync_live_balance / update_balance interaction."""

    def test_update_balance_works_before_live_mode(self, guard):
        """Before live mode, update_balance sets the balance normally."""
        guard.update_balance(9_500.0)
        assert guard._current_balance == 9_500.0

    def test_sync_live_balance_sets_balance(self, guard):
        """sync_live_balance updates current balance correctly."""
        guard.sync_live_balance(9_324.58)
        assert guard._current_balance == 9_324.58

    def test_update_balance_ignored_after_sync_live_balance(self, guard):
        """After live sync, update_balance must not overwrite the synced value.

        This is the core fix for the oscillation bug: PaperTrader calls
        update_balance on every tick with starting_balance + pnl, which
        reverts the balance to $10K. After sync_live_balance, those
        calls must be ignored.
        """
        guard.sync_live_balance(9_324.58)

        # Simulate PaperTrader tick recalculation
        guard.update_balance(10_000.0)

        assert guard._current_balance == 9_324.58, (
            "update_balance should be ignored after sync_live_balance"
        )

    def test_update_balance_updates_peak_before_live_mode(self, guard):
        """update_balance updates peak_balance before live mode."""
        guard.update_balance(12_000.0)
        assert guard._peak_balance == 12_000.0

    def test_sync_live_balance_updates_peak(self, guard):
        """sync_live_balance updates peak_balance when applicable."""
        guard.sync_live_balance(12_000.0)
        assert guard._peak_balance == 12_000.0

    def test_repeated_sync_live_balance_refreshes(self, guard):
        """Multiple sync calls update the balance each time."""
        guard.sync_live_balance(9_324.58)
        guard.sync_live_balance(9_400.00)
        assert guard._current_balance == 9_400.00

    def test_disable_live_balance_allows_update(self, guard):
        """After disabling live mode, update_balance works again."""
        guard.sync_live_balance(9_324.58)
        guard.disable_live_balance()
        guard.update_balance(10_000.0)
        assert guard._current_balance == 10_000.0

    def test_balance_persistence_between_syncs(self, guard):
        """Simulate the exact oscillation scenario from production.

        1. Live sync sets balance to $9,324.58
        2. Multiple paper trader ticks try to revert to $10,000
        3. Balance must stay at $9,324.58 throughout
        """
        guard.sync_live_balance(9_324.58)

        # Simulate 10 ticks over 60 seconds
        for _ in range(10):
            guard.update_balance(10_000.0)  # PaperTrader recalculation

        assert guard._current_balance == 9_324.58
        assert guard.current_drawdown_pct == pytest.approx(
            (10_000.0 - 9_324.58) / 10_000.0, rel=1e-4
        )

    def test_daily_pnl_stays_realistic_after_sync(self, guard):
        """daily_pnl should not show phantom $675.42 after sync.

        Before fix: balance reverted to $10K, daily_start was $9,324.58,
        so daily_pnl = $10K - $9,324.58 = $675.42 (phantom profit).

        After fix: balance stays at $9,324.58, daily_start was aligned
        to $9,324.58 on first sync, so daily_pnl = $0.00.
        """
        # First sync aligns daily_start to live balance (via engine logic)
        guard.sync_live_balance(9_324.58)
        guard._daily_start_balance = 9_324.58  # Simulate engine alignment

        # Paper trader tick recalculation
        guard.update_balance(10_000.0)

        daily_pnl = guard._current_balance - guard._daily_start_balance
        assert daily_pnl == pytest.approx(0.0, abs=0.01), (
            f"daily_pnl should be ~$0.00, got ${daily_pnl:.2f}"
        )

    def test_drawdown_correct_after_sync(self, guard):
        """Drawdown% should reflect real cTrader balance, not $10K default."""
        guard.sync_live_balance(9_324.58)

        # Paper trader tick
        guard.update_balance(10_000.0)

        # DD should be based on $9,324.58, not $10,000
        expected_dd = (10_000.0 - 9_324.58) / 10_000.0
        assert guard.current_drawdown_pct == pytest.approx(expected_dd, rel=1e-4)


class TestStartupSanityGate:
    """Tests for the startup sanity validation in _restore_state."""

    def test_sanity_gate_rejects_impossible_peak(self, tmp_state_path):
        """State with peak_balance > 2x starting_balance is rejected."""
        # Write a state file with impossible values
        Path(tmp_state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(tmp_state_path).write_text(json.dumps({
            "peak_balance": 25_000.0,  # 2.5x starting
            "current_balance": 10_000.0,
            "daily_start_balance": 10_000.0,
            "current_day": "2026-07-06",
            "daily_trade_count": 0,
            "total_trades": 0,
            "circuit_breaker_triggered": False,
            "blocked_until": None,
        }))

        guard = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10_000.0,
            state_path=tmp_state_path,
        )

        # State should be reset to starting_balance
        assert guard._peak_balance == 10_000.0
        assert guard._current_balance == 10_000.0
        assert guard._daily_start_balance == 10_000.0

    def test_sanity_gate_rejects_impossible_daily_start(self, tmp_state_path):
        """State with daily_start_balance > 2x starting_balance is rejected."""
        Path(tmp_state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(tmp_state_path).write_text(json.dumps({
            "peak_balance": 10_000.0,
            "current_balance": 10_000.0,
            "daily_start_balance": 21_000.0,  # 2.1x starting
            "current_day": "2026-07-06",
            "daily_trade_count": 0,
            "total_trades": 0,
            "circuit_breaker_triggered": False,
            "blocked_until": None,
        }))

        guard = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10_000.0,
            state_path=tmp_state_path,
        )

        assert guard._daily_start_balance == 10_000.0
        assert guard._peak_balance == 10_000.0

    def test_sanity_gate_allows_normal_values(self, tmp_state_path):
        """Normal state values (within 2x) are accepted."""
        Path(tmp_state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(tmp_state_path).write_text(json.dumps({
            "peak_balance": 10_500.0,  # Normal
            "current_balance": 9_324.58,  # Normal
            "daily_start_balance": 9_324.58,  # Normal
            "current_day": "2026-07-06",
            "daily_trade_count": 0,
            "total_trades": 0,
            "circuit_breaker_triggered": False,
            "blocked_until": None,
        }))

        guard = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10_000.0,
            state_path=tmp_state_path,
        )

        # Values should be loaded normally
        assert guard._peak_balance == 10_500.0
        assert guard._current_balance == 9_324.58
        assert guard._daily_start_balance == 9_324.58

    def test_sanity_gate_allows_balance_near_zero(self, tmp_state_path):
        """Balance below starting_balance is valid (trading losses)."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        # Compute the current trading day (17:00 America/Toronto rollover)
        # so the state file doesn't trigger the day-change reset logic.
        now_tz = datetime.now(ZoneInfo("America/Toronto"))
        if now_tz.hour >= 17:
            trading_day = now_tz.date()
        else:
            trading_day = now_tz.date() - timedelta(days=1)

        Path(tmp_state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(tmp_state_path).write_text(json.dumps({
            "peak_balance": 10_000.0,
            "current_balance": 3_000.0,  # Heavy losses but valid
            "daily_start_balance": 9_500.0,
            "current_day": trading_day.isoformat(),
            "daily_trade_count": 5,
            "total_trades": 10,
            "circuit_breaker_triggered": False,
            "blocked_until": None,
        }))

        guard = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10_000.0,
            state_path=tmp_state_path,
        )

        assert guard._current_balance == 3_000.0
        assert guard._daily_trade_count == 5
