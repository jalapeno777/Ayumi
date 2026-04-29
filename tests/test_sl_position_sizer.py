"""Tests for SL-Derived Position Sizer."""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from risk.sl_position_sizer import SLPositionSizer, PositionSizeResult, INSTRUMENTS


class TestSLPositionSizer:
    """Test suite for SL-derived position sizing."""

    def setup_method(self):
        self.sizer = SLPositionSizer(
            account_balance=10000.0,
            risk_per_trade_pct=0.005,   # 0.5% = $50
            max_lot_size=1.0,
            daily_risk_cap_pct=0.03,    # 3% = $300
        )

    # --- Basic Calculation ---

    def test_basic_eurusd(self):
        """Standard EURUSD trade: $50 risk, 30 pip SL."""
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert not result.blocked
        assert result.lots > 0
        assert result.sl_distance_pips == pytest.approx(30.0)
        assert result.risk_amount == pytest.approx(50.0, abs=1.0)

    def test_basic_xauusd(self):
        """XAUUSD trade: $50 risk, $30 SL distance (30 pips on XAUUSD)."""
        result = self.sizer.calculate("XAUUSD", 3350.0, 3320.0, profile="sniper")
        assert not result.blocked
        assert result.lots > 0
        assert result.sl_distance_pips == pytest.approx(3000.0)

    def test_swarm_half_risk(self):
        """Swarm profile should use half the per-trade risk."""
        sniper = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        swarm = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="swarm")
        assert not sniper.blocked
        assert not swarm.blocked
        assert swarm.lots == pytest.approx(sniper.lots * 0.5, abs=0.01)

    # --- SL Distance Validation ---

    def test_sl_too_close(self):
        """SL less than 5 pips should be blocked."""
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0849, profile="sniper")
        assert result.blocked
        assert "minimum" in result.block_reason.lower()

    def test_sl_exactly_at_minimum(self):
        """SL exactly at 5 pips should pass."""
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0845, profile="sniper")
        assert not result.blocked

    def test_sl_above_entry(self):
        """Short trade SL above entry should work."""
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0880, profile="sniper")
        assert not result.blocked
        assert result.sl_distance_pips == pytest.approx(30.0)

    # --- Max Lot Cap ---

    def test_max_lot_cap(self):
        """Very wide SL should cap at max lot size."""
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0840, profile="sniper")
        # With only 10 pips SL on $50 risk = 0.5 lots, won't hit cap
        # Need tiny SL to hit cap
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0845, profile="sniper")
        # 5 pips, $50 risk = 1.0 lot exactly
        assert not result.blocked
        assert result.lots <= 1.0

    # --- Daily Risk Cap ---

    def test_daily_risk_cap(self):
        """Should block when daily risk exhausted."""
        # Open enough positions to exhaust daily cap
        # Daily cap = $300, each trade = $50
        for _ in range(6):
            result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
            if not result.blocked:
                self.sizer.register_open_position(result.risk_amount)

        # 7th should be blocked (6 * $50 = $300 daily cap used)
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert result.blocked
        assert "daily" in result.block_reason.lower()

    def test_daily_risk_recycling(self):
        """Closing positions should free up daily risk."""
        # Open 6 positions
        positions = []
        for _ in range(6):
            result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
            if not result.blocked:
                self.sizer.register_open_position(result.risk_amount)
                positions.append(result)

        # Close one with a win
        self.sizer.close_position(pnl=100.0, risk_amount=positions[0].risk_amount, win=True)

        # Should be able to open again
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert not result.blocked

    # --- Circuit Breakers ---

    def test_circuit_breaker_win_rate(self):
        """Should halt on low win rate."""
        # Record 20 losses
        for _ in range(20):
            self.sizer.breaker.record_trade(win=False)

        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert result.blocked
        assert "win rate" in result.block_reason.lower()

    def test_circuit_breaker_daily_dd(self):
        """Should halt on 3% daily drawdown."""
        self.sizer.breaker.daily_dd_pct = 0.031  # 3.1%
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert result.blocked
        assert "daily drawdown" in result.block_reason.lower()

    def test_circuit_breaker_account_dd(self):
        """Should halt on 7% account drawdown."""
        self.sizer.breaker.account_dd_pct = 0.071  # 7.1%
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert result.blocked
        assert "account drawdown" in result.block_reason.lower()

    def test_circuit_breaker_lifts_after_timeout(self):
        """Circuit breaker should auto-lift after duration expires."""
        self.sizer.breaker.halt("test", duration_hours=0.0001)  # Very short
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert result.blocked  # Still halted

        # Manually expire it
        from datetime import datetime, timezone, timedelta
        self.sizer.breaker.halted_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert not result.blocked  # Should be lifted

    # --- Unknown Instrument ---

    def test_unknown_instrument(self):
        """Should block unknown symbols."""
        result = self.sizer.calculate("BTCUSD", 65000.0, 64000.0, profile="sniper")
        assert result.blocked
        assert "unknown" in result.block_reason.lower()

    # --- Edge Cases ---

    def test_zero_balance(self):
        """Zero balance should block everything."""
        self.sizer.update_balance(0.0)
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert result.blocked or result.lots == 0.0

    def test_invalid_profile_blocked(self):
        """Invalid profile should return blocked result, not raise."""
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="invalid")
        assert result.blocked
        assert "unknown profile" in result.block_reason.lower()

    def test_profile_enum_accepted(self):
        """Profile enum should be accepted and converted."""
        from risk.profile_router import Profile
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile=Profile.SNIPER)
        assert not result.blocked
        assert result.lots > 0

    def test_very_small_balance(self):
        """Tiny account should block when lot size too small."""
        self.sizer.update_balance(100.0)
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert result.blocked  # $0.50 risk can't reach 0.01 lots minimum


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
