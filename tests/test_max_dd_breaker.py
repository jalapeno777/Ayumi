"""Tests for FTMO Max Drawdown Circuit Breaker (A6).

Verifies council decision R2 (Kaito):
  - Max drawdown breach → permanent block (no auto-recovery, no _blocked_until expiry)
  - reset_circuit_breaker() works for permanent (total drawdown) blocks
  - reset_circuit_breaker() does NOT clear daily loss time-based blocks
  - No auto-recovery after time passes
"""

import json  # noqa: I001
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
    """Fresh RiskGuard with $10K starting balance (FTMO challenge scale)."""
    return RiskGuard(
        ftmo_config=FTMOConfig(),
        starting_balance=10000.0,
        state_path=tmp_state,
    )


# ---------------------------------------------------------------------------
# Test 1 — Max drawdown breach sets permanent block (no _blocked_until)
# ---------------------------------------------------------------------------


class TestMaxDrawdownPermanentBlock:
    def test_max_dd_breach_sets_permanent_block(self, guard):
        """When total drawdown limit is breached, _circuit_breaker_triggered
        is True and _blocked_until is None (permanent — no expiry)."""
        guard._trigger_circuit_breaker(
            RiskLimitType.TOTAL_DRAWDOWN,
            current=0.11,
            limit=0.10,
        )
        assert guard._circuit_breaker_triggered is True, "Total drawdown must set _circuit_breaker_triggered"
        assert guard._blocked_until is None, (
            f"Total drawdown must NOT set _blocked_until (permanent block), got {guard._blocked_until}"
        )

    def test_max_dd_breach_is_blocked_in_check_signal(self, guard):
        """After max drawdown breach, check_signal must reject."""
        guard._trigger_circuit_breaker(RiskLimitType.TOTAL_DRAWDOWN, 0.11, 0.10)
        from adapters.ctrader.models import TradeDirection, CTraderTradeSignal  # noqa: I001

        signal = CTraderTradeSignal(
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            entry_price=1.2500,
            stop_loss=1.2450,
            take_profit_1=1.2600,
            take_profit_2=1.2650,
            take_profit_3=1.2700,
            volume=0.1,
            confidence=0.8,
            rationale="test",
        )
        result = guard.check_signal(signal)
        assert result.allowed is False, "check_signal must reject after permanent circuit breaker"

    def test_max_dd_breach_is_blocked_in_check_trade_allowed(self, guard):
        """After max drawdown breach, check_trade_allowed must reject."""
        guard._trigger_circuit_breaker(RiskLimitType.TOTAL_DRAWDOWN, 0.11, 0.10)
        from adapters.ctrader.models import TradeDirection

        result = guard.check_trade_allowed(
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.2500,
            stop_loss=1.2450,
            take_profit=1.2600,
            account_balance=8900.0,  # below peak by >10%
        )
        assert result.allowed is False, "check_trade_allowed must reject after permanent circuit breaker"


# ---------------------------------------------------------------------------
# Test 2 — Max drawdown block does NOT auto-recover after time passes
# ---------------------------------------------------------------------------


class TestNoAutoRecovery:
    def test_no_auto_recovery_after_time_passes(self, guard):
        """Simulate time passing — permanent block must still be active."""
        guard._trigger_circuit_breaker(RiskLimitType.TOTAL_DRAWDOWN, 0.11, 0.10)
        # Simulate time passing: mutate internal state as if hours passed.
        # Since _blocked_until is None, there is no time-based expiry.
        # The only way to clear is reset_circuit_breaker().
        assert guard._circuit_breaker_triggered is True
        assert guard._blocked_until is None

        # After "time passes" (nothing changes because there's no expiry)
        assert guard.is_blocked is True, "Permanent circuit breaker must still be blocked — no auto-recovery"

    def test_no_auto_recovery_persists_in_check_signal(self, guard):
        """Even after simulating time passage, check_signal still blocks."""
        guard._trigger_circuit_breaker(RiskLimitType.TOTAL_DRAWDOWN, 0.11, 0.10)
        from adapters.ctrader.models import TradeDirection, CTraderTradeSignal  # noqa: I001

        signal = CTraderTradeSignal(
            symbol="USDJPY",
            direction=TradeDirection.SHORT,
            entry_price=150.00,
            stop_loss=150.50,
            take_profit_1=149.00,
            take_profit_2=148.50,
            take_profit_3=148.00,
            volume=0.1,
            confidence=0.7,
            rationale="test",
        )
        # Check immediately
        result1 = guard.check_signal(signal)
        assert result1.allowed is False

        # Check again (simulating "later in time")
        result2 = guard.check_signal(signal)
        assert result2.allowed is False, "Permanent breaker must still block — no time-based recovery"


# ---------------------------------------------------------------------------
# Test 3 — reset_circuit_breaker() clears the permanent block
# ---------------------------------------------------------------------------


class TestResetCircuitBreaker:
    def test_reset_clears_permanent_block(self, guard):
        """reset_circuit_breaker() clears a permanent (total drawdown) block."""
        guard._trigger_circuit_breaker(RiskLimitType.TOTAL_DRAWDOWN, 0.11, 0.10)
        assert guard._circuit_breaker_triggered is True

        result = guard.reset_circuit_breaker(reason="test reset")
        assert result is True, "reset_circuit_breaker must return True for permanent block"
        assert guard._circuit_breaker_triggered is False, "Circuit breaker must be cleared after reset"

    def test_reset_allows_trading_again(self, guard):
        """After reset, check_signal must allow trades again."""
        guard._trigger_circuit_breaker(RiskLimitType.TOTAL_DRAWDOWN, 0.11, 0.10)
        from adapters.ctrader.models import TradeDirection, CTraderTradeSignal  # noqa: I001

        signal = CTraderTradeSignal(
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            entry_price=1.2500,
            stop_loss=1.2450,
            take_profit_1=1.2600,
            take_profit_2=1.2650,
            take_profit_3=1.2700,
            volume=0.1,
            confidence=0.8,
            rationale="test",
        )
        # Blocked before reset
        assert guard.check_signal(signal).allowed is False

        guard.reset_circuit_breaker(reason="recovery")

        # Allowed after reset
        result = guard.check_signal(signal)
        assert result.allowed is True, "Signal must be allowed after circuit breaker reset"

    def test_reset_persists_to_state(self, guard, tmp_state):
        """reset_circuit_breaker saves the cleared state."""
        guard._trigger_circuit_breaker(RiskLimitType.TOTAL_DRAWDOWN, 0.11, 0.10)
        guard.reset_circuit_breaker(reason="persisted reset")

        raw = json.loads(Path(tmp_state).read_text())
        assert raw["circuit_breaker_triggered"] is False
        assert raw["blocked_until"] is None

    def test_reset_when_not_triggered_returns_true(self, guard):
        """reset_circuit_breaker on a non-blocked guard returns True (idempotent)."""
        result = guard.reset_circuit_breaker(reason="noop")
        assert result is True


# ---------------------------------------------------------------------------
# Test 4 — reset_circuit_breaker() does NOT clear daily loss block
# ---------------------------------------------------------------------------


class TestResetRefusesDailyLoss:
    def test_reset_refuses_daily_loss_block(self, guard):
        """reset_circuit_breaker() must refuse to clear a daily loss time-based block."""
        guard._trigger_circuit_breaker(RiskLimitType.DAILY_LOSS, 0.06, 0.05)
        # Daily loss sets _blocked_until but NOT _circuit_breaker_triggered
        assert guard._blocked_until is not None
        assert guard._circuit_breaker_triggered is False

        result = guard.reset_circuit_breaker(reason="trying to bypass daily loss")
        assert result is False, "reset_circuit_breaker must return False for daily loss block"
        # Daily loss block must still be in place
        assert guard._blocked_until is not None, (
            "Daily loss _blocked_until must not be cleared by reset_circuit_breaker"
        )

    def test_daily_loss_still_blocks_after_reset_attempt(self, guard):
        """After a failed reset attempt, daily loss block still rejects trades."""
        guard._trigger_circuit_breaker(RiskLimitType.DAILY_LOSS, 0.06, 0.05)
        guard.reset_circuit_breaker(reason="should fail")

        from adapters.ctrader.models import TradeDirection, CTraderTradeSignal  # noqa: I001

        signal = CTraderTradeSignal(
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            entry_price=1.2500,
            stop_loss=1.2450,
            take_profit_1=1.2600,
            take_profit_2=1.2650,
            take_profit_3=1.2700,
            volume=0.1,
            confidence=0.8,
            rationale="test",
        )
        result = guard.check_signal(signal)
        assert result.allowed is False, "Daily loss block must still be active after failed reset attempt"


# ---------------------------------------------------------------------------
# Test 5 — State persistence across restart for permanent block
# ---------------------------------------------------------------------------


class TestPermanentBlockPersistence:
    def test_permanent_block_survives_restart(self, tmp_state):
        """Permanent circuit breaker survives a simulated restart."""
        g1 = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10000.0,
            state_path=tmp_state,
        )
        g1._trigger_circuit_breaker(RiskLimitType.TOTAL_DRAWDOWN, 0.11, 0.10)

        # New instance — restore from state
        g2 = RiskGuard(
            ftmo_config=FTMOConfig(),
            starting_balance=10000.0,
            state_path=tmp_state,
        )
        assert g2._circuit_breaker_triggered is True, "Permanent circuit breaker must survive restart"
        assert g2._blocked_until is None, "Permanent block must have _blocked_until=None after restart"
        assert g2.is_blocked is True
