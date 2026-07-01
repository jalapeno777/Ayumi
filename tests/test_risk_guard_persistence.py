"""Tests for RiskGuard state persistence and daily-loss halt behavior.

Covers council decisions:
  R1 — state survives restarts
  R2 — daily loss halts until UTC midnight (not 5 min)
  R3 — UTC date consistency
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from adapters.ctrader.risk_guard import (
    FTMOConfig,
    RiskGuard,
    RiskLimitType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_state(tmp_path):
    """Return a temp file path for RiskGuard state."""
    return str(tmp_path / "risk_guard_state.json")


@pytest.fixture
def guard(tmp_state):
    """Fresh RiskGuard with isolated state file."""
    return RiskGuard(
        ftmo_config=FTMOConfig(),
        starting_balance=10000.0,
        state_path=tmp_state,
    )


# ---------------------------------------------------------------------------
# Test 1 — save_state writes valid JSON
# ---------------------------------------------------------------------------

class TestSaveState:
    def test_save_state_writes_valid_json(self, guard, tmp_state):
        """_save_state produces a parseable JSON file with all expected keys."""
        # Mutate some state so the file has non-default values
        guard._peak_balance = 10500.0
        guard._current_balance = 9800.0
        guard._daily_start_balance = 10000.0
        guard._current_day = date(2026, 7, 1)
        guard._daily_trade_count = 3
        guard._total_trades = 42
        guard._circuit_breaker_triggered = False
        guard._blocked_until = None

        guard._save_state()

        path = Path(tmp_state)
        assert path.exists(), "State file was not created"

        raw = json.loads(path.read_text())
        assert raw["peak_balance"] == 10500.0
        assert raw["current_balance"] == 9800.0
        assert raw["daily_start_balance"] == 10000.0
        assert raw["current_day"] == "2026-07-01"
        assert raw["daily_trade_count"] == 3
        assert raw["total_trades"] == 42
        assert raw["circuit_breaker_triggered"] is False
        assert raw["blocked_until"] is None
        # last_save_ts must be a valid ISO-8601 string
        parsed_ts = datetime.fromisoformat(raw["last_save_ts"])
        assert parsed_ts.tzinfo is not None, "last_save_ts must be timezone-aware"


# ---------------------------------------------------------------------------
# Test 2 — restore_state recovers all fields correctly
# ---------------------------------------------------------------------------

class TestRestoreState:
    def test_restore_state_recovers_all_fields(self, tmp_state):
        """A new RiskGuard instance picks up state previously saved."""
        # Phase 1 — create guard, set state, save
        g1 = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10000.0,
            state_path=tmp_state,
        )
        g1._peak_balance = 11200.0
        g1._current_balance = 9500.0
        g1._daily_start_balance = 10000.0
        g1._current_day = datetime.now(timezone.utc).date()
        g1._daily_trade_count = 5
        g1._total_trades = 30
        g1._circuit_breaker_triggered = True
        g1._blocked_until = datetime(2026, 7, 1, 23, 59, 59, tzinfo=timezone.utc)
        g1._save_state()

        # Phase 2 — new instance, same state file
        g2 = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10000.0,
            state_path=tmp_state,
        )

        assert g2._peak_balance == 11200.0
        assert g2._current_balance == 9500.0
        assert g2._daily_start_balance == 10000.0
        assert g2._daily_trade_count == 5
        assert g2._total_trades == 30
        assert g2._circuit_breaker_triggered is True
        assert g2._blocked_until == datetime(2026, 7, 1, 23, 59, 59, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test 3 — daily loss halt blocks until UTC midnight (not 5 min)
# ---------------------------------------------------------------------------

class TestDailyLossHalt:
    def test_daily_loss_blocks_until_utc_midnight(self, guard):
        """When daily loss triggers, blocked_until ≈ next UTC midnight, not +5 min."""
        # Simulate a daily-loss circuit breaker trigger
        now = datetime.now(timezone.utc)

        guard._trigger_circuit_breaker(
            RiskLimitType.DAILY_LOSS,
            current=0.06,
            limit=0.05,
        )

        # Should NOT set permanent circuit breaker for daily loss
        assert guard._circuit_breaker_triggered is False, (
            "Daily loss must not set permanent circuit_breaker_triggered"
        )

        # blocked_until should be close to next UTC midnight
        assert guard._blocked_until is not None
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        delta = abs((guard._blocked_until - next_midnight).total_seconds())
        assert delta < 5, (
            f"blocked_until should be ~UTC midnight, got {guard._blocked_until}, "
            f"expected ~{next_midnight}, delta={delta}s"
        )

        # Must NOT be 5 minutes from now
        five_min = now + timedelta(minutes=5)
        assert guard._blocked_until > five_min, (
            f"blocked_until ({guard._blocked_until}) must be well beyond 5 min ({five_min})"
        )

    def test_total_drawdown_uses_permanent_breaker(self, guard):
        """Total drawdown still uses permanent circuit breaker (unchanged behavior)."""
        guard._trigger_circuit_breaker(
            RiskLimitType.TOTAL_DRAWDOWN,
            current=0.11,
            limit=0.10,
        )
        assert guard._circuit_breaker_triggered is True, (
            "Total drawdown must set permanent circuit_breaker_triggered"
        )


# ---------------------------------------------------------------------------
# Test 4 — state survives simulated restart
# ---------------------------------------------------------------------------

class TestStateSurvivesRestart:
    def test_state_survives_simulated_restart(self, tmp_state):
        """Full cycle: create → trade → save → new instance → restore → verify."""
        # Create first instance and simulate trading
        g1 = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10000.0,
            state_path=tmp_state,
        )
        # Simulate 3 losing trades
        g1.record_trade(pnl=-50.0, is_win=False)
        g1.record_trade(pnl=-30.0, is_win=False)
        g1.record_trade(pnl=-20.0, is_win=False)

        # Save is called automatically inside record_trade, but verify file exists
        assert Path(tmp_state).exists(), "State file must exist after record_trade"

        # Capture g1 state
        g1_balance = g1._current_balance
        g1_peak = g1._peak_balance
        g1_daily = g1._daily_trade_count
        g1_total = g1._total_trades

        # Simulate restart — new instance with same state file
        g2 = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10000.0,  # original starting balance
            state_path=tmp_state,
        )

        # Verify all state was restored
        assert g2._current_balance == g1_balance, (
            f"Balance mismatch: g2={g2._current_balance}, g1={g1_balance}"
        )
        assert g2._peak_balance == g1_peak
        assert g2._daily_trade_count == g1_daily
        assert g2._total_trades == g1_total

    def test_blocked_state_survives_restart(self, tmp_state):
        """If guard was blocked by daily loss, block persists across restart."""
        g1 = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10000.0,
            state_path=tmp_state,
        )
        # Trigger daily loss halt
        g1._trigger_circuit_breaker(RiskLimitType.DAILY_LOSS, 0.06, 0.05)
        blocked_until_g1 = g1._blocked_until

        # Restart
        g2 = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10000.0,
            state_path=tmp_state,
        )

        # Block must persist (today's date matches so no day-rollover reset)
        assert g2._blocked_until == blocked_until_g1, (
            "Daily loss block must survive restart when same day"
        )
        assert g2._circuit_breaker_triggered is False


# ---------------------------------------------------------------------------
# Test R3 — UTC date consistency
# ---------------------------------------------------------------------------

class TestUTCDateConsistency:
    def test_no_date_today_in_source(self):
        """Verify risk_guard.py source has no date.today() calls (R3)."""
        import inspect
        from adapters.ctrader import risk_guard as rg_module

        source = inspect.getsource(rg_module.RiskGuard)
        assert "date.today()" not in source, (
            "date.today() found in RiskGuard source — must use "
            "datetime.now(timezone.utc).date() instead"
        )

    def test_update_daily_tracking_uses_utc(self, guard):
        """_update_daily_tracking sets _current_day to UTC today."""
        guard._update_daily_tracking()
        utc_today = datetime.now(timezone.utc).date()
        assert guard._current_day == utc_today, (
            f"_current_day={guard._current_day}, UTC today={utc_today}"
        )
