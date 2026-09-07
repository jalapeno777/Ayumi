"""Tests for SL-Derived Position Sizer."""

import pytest
from risk.sl_position_sizer import SLPositionSizer


class TestSLPositionSizer:
    """Test suite for SL-derived position sizing."""

    def setup_method(self):
        self.sizer = SLPositionSizer(
            account_balance=10000.0,
            risk_per_trade_pct=0.005,  # 0.5% = $50
            max_lot_size=1.0,
            daily_risk_cap_pct=0.03,  # 3% = $300
            max_positions_per_symbol=10,  # High default for daily-cap-only tests
            max_total_open_risk=10000.0,  # High default for daily-cap-only tests
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
        """XAUUSD trade: $50 risk, $30 SL distance (300 pips on XAUUSD).

        Canonical XAUUSD pip_size per cTrader convention = 0.1; so a
        $30 price-distance SL is 30 / 0.1 = 300 pips (not 3000).
        See ``utils.pip_value.pip_value_for_symbol``.
        """
        result = self.sizer.calculate("XAUUSD", 3350.0, 3320.0, profile="sniper")
        assert not result.blocked
        assert result.lots > 0
        assert result.sl_distance_pips == pytest.approx(300.0)

    def test_swarm_half_risk(self):
        """Swarm profile should use half the per-trade risk."""
        sniper = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        swarm = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="swarm")
        assert not sniper.blocked
        assert not swarm.blocked
        assert swarm.lots == pytest.approx(sniper.lots * 0.5, abs=0.01)

    def test_basic_audusd(self):
        """Standard AUDUSD trade: $50 risk, 30 pip SL."""
        result = self.sizer.calculate("AUDUSD", 0.6650, 0.6620, profile="sniper")
        assert not result.blocked
        assert result.lots > 0
        assert result.sl_distance_pips == pytest.approx(30.0)
        assert result.risk_amount == pytest.approx(50.0, abs=1.0)

    def test_basic_usdchf(self):
        """Standard USDCHF trade: $50 risk, 30 pip SL."""
        result = self.sizer.calculate("USDCHF", 0.8850, 0.8820, profile="sniper")
        assert not result.blocked
        assert result.lots > 0
        assert result.sl_distance_pips == pytest.approx(30.0)
        assert result.risk_amount == pytest.approx(50.0, abs=1.0)

    def test_basic_usdcad(self):
        """Standard USDCAD trade: $50 risk, 30 pip SL."""
        result = self.sizer.calculate("USDCAD", 1.3700, 1.3670, profile="sniper")
        assert not result.blocked
        assert result.lots > 0
        assert result.sl_distance_pips == pytest.approx(30.0)
        assert result.risk_amount == pytest.approx(50.0, abs=1.0)

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
        from datetime import datetime, timedelta, timezone

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

    # --- Daily Reset (Phase 6B: FTMO CET midnight reset) ---

    def test_reset_daily_restores_full_budget(self):
        """After reset_daily(), daily_risk_remaining should equal the full
        account_balance * daily_risk_cap_pct budget — no realized losses
        from prior days should leak into today's budget."""
        # Simulate prior-day realized loss: $150 accumulated
        # (which would otherwise shrink today's $300 cap to $150)
        result = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert not result.blocked
        self.sizer.register_open_position(result.risk_amount)
        # Close as a loss — accumulates into _daily_risk_used
        self.sizer.close_position(pnl=-50.0, risk_amount=result.risk_amount, win=False)
        assert self.sizer._daily_risk_used > 0

        # Sanity: prior to reset, remaining is reduced by used + open_risk
        pre_remaining = self.sizer.daily_risk_remaining
        full_budget = self.sizer.account_balance * self.sizer.daily_risk_cap_pct
        assert pre_remaining < full_budget

        # Now reset — should zero _daily_risk_used and restore full budget
        self.sizer.reset_daily(cet_date="2026-07-09")

        # Daily used is zeroed
        assert self.sizer._daily_risk_used == 0.0
        # Full budget restored (no open positions left after the close)
        assert self.sizer.daily_risk_remaining == pytest.approx(full_budget, abs=1e-6)
        # breaker.daily_dd_pct also reset
        assert self.sizer.breaker.daily_dd_pct == 0.0

    def test_reset_daily_carries_open_positions(self):
        """reset_daily() must NOT touch _open_risk — open positions carry
        over so their reserved risk continues to consume the daily cap
        (recycling behaviour)."""
        # Open 3 positions
        results = []
        for _ in range(3):
            r = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
            assert not r.blocked
            self.sizer.register_open_position(r.risk_amount)
            results.append(r)

        # Add a realized loss too
        self.sizer.close_position(pnl=-25.0, risk_amount=results[0].risk_amount, win=False)

        pre_open_risk = self.sizer.open_risk
        pre_open_count = len(self.sizer.open_positions)
        pre_daily_used = self.sizer._daily_risk_used
        assert pre_open_risk > 0
        assert pre_open_count == 2  # 3 opened, 1 closed (and lost)
        assert pre_daily_used > 0

        self.sizer.reset_daily()

        # Open positions preserved
        assert self.sizer.open_risk == pytest.approx(pre_open_risk, abs=1e-6)
        assert len(self.sizer.open_positions) == pre_open_count
        # Daily losses zeroed
        assert self.sizer._daily_risk_used == 0.0
        # Remaining budget reflects only open risk now (full - open)
        expected_remaining = max(
            0.0,
            self.sizer.account_balance * self.sizer.daily_risk_cap_pct - self.sizer.open_risk,
        )
        assert self.sizer.daily_risk_remaining == pytest.approx(expected_remaining, abs=1e-6)

    def test_reset_daily_logs_transition(self, caplog):
        """reset_daily() must log the pre→post transition so operators can
        verify the daily counter was zeroed while open positions carried."""
        import logging

        # Accumulate some state
        r = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert not r.blocked
        self.sizer.register_open_position(r.risk_amount)
        self.sizer.close_position(pnl=-50.0, risk_amount=r.risk_amount, win=False)

        with caplog.at_level(logging.INFO, logger="risk.sl_position_sizer"):
            self.sizer.reset_daily(cet_date="2026-07-09")

        # Find the reset log line
        reset_lines = [rec for rec in caplog.records if "reset_daily" in rec.getMessage().lower()]
        assert reset_lines, f"Expected a reset_daily log entry, got: {[r.getMessage() for r in caplog.records]}"
        msg = reset_lines[-1].getMessage()
        # Log should mention pre-reset daily_used, post=0, carried positions
        assert "daily_used" in msg
        assert "open_risk" in msg
        assert "positions_carried" in msg
        assert "cet_date=2026-07-09" in msg

    def test_reset_daily_idempotent(self):
        """Calling reset_daily() twice in a row should be safe and leave
        the state identical (idempotent)."""
        r = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert not r.blocked
        self.sizer.register_open_position(r.risk_amount)
        self.sizer.close_position(pnl=-50.0, risk_amount=r.risk_amount, win=False)

        self.sizer.reset_daily()
        first_remaining = self.sizer.daily_risk_remaining
        first_open_risk = self.sizer.open_risk

        # Second reset — no positions, no losses, should be a no-op
        self.sizer.reset_daily()
        assert self.sizer.daily_risk_remaining == pytest.approx(first_remaining, abs=1e-6)
        assert self.sizer.open_risk == pytest.approx(first_open_risk, abs=1e-6)
        assert self.sizer._daily_risk_used == 0.0

    def test_reset_daily_optional_cet_date(self):
        """reset_daily() must accept being called without cet_date (backward
        compat — some legacy call sites may still pass no arg)."""
        r = self.sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert not r.blocked
        self.sizer.register_open_position(r.risk_amount)
        self.sizer.close_position(pnl=-50.0, risk_amount=r.risk_amount, win=False)
        # Should not raise
        self.sizer.reset_daily()
        assert self.sizer._daily_risk_used == 0.0

    # --- Concurrent Position Limits (Phase 5b) ---

    def test_max_positions_per_symbol_blocks_second(self):
        """Should block a second position on the same symbol."""
        sizer = SLPositionSizer(
            account_balance=10000.0,
            risk_per_trade_pct=0.005,
            max_positions_per_symbol=1,
        )
        # First position succeeds
        r1 = sizer.calculate("GBPUSD", 1.2850, 1.2820, profile="sniper")
        assert not r1.blocked
        sizer.register("sig_001", r1.risk_amount, symbol="GBPUSD")

        # Second position on same symbol should be blocked
        r2 = sizer.calculate("GBPUSD", 1.2860, 1.2830, profile="sniper")
        assert r2.blocked
        assert "already open for GBPUSD" in r2.block_reason

    def test_max_positions_per_symbol_allows_different_symbols(self):
        """Different symbols should not interfere with each other."""
        sizer = SLPositionSizer(
            account_balance=10000.0,
            risk_per_trade_pct=0.005,
            max_positions_per_symbol=1,
        )
        r1 = sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        assert not r1.blocked
        sizer.register("sig_eur_1", r1.risk_amount, symbol="EURUSD")

        r2 = sizer.calculate("GBPUSD", 1.2850, 1.2820, profile="sniper")
        assert not r2.blocked
        sizer.register("sig_gbp_1", r2.risk_amount, symbol="GBPUSD")

    def test_max_positions_per_symbol_release_on_close(self):
        """After closing a position, should allow new one on same symbol."""
        sizer = SLPositionSizer(
            account_balance=10000.0,
            risk_per_trade_pct=0.005,
            max_positions_per_symbol=1,
        )
        r1 = sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        sizer.register("sig_001", r1.risk_amount, symbol="EURUSD")

        # Close the position
        sizer.close("sig_001", pnl=50.0)

        # Should be able to open again
        r2 = sizer.calculate("EURUSD", 1.0860, 1.0830, profile="sniper")
        assert not r2.blocked

    def test_max_total_open_risk_blocks_when_exceeded(self):
        """Should block when total open risk + new risk exceeds cap."""
        sizer = SLPositionSizer(
            account_balance=10000.0,
            risk_per_trade_pct=0.005,  # $50 per trade
            max_total_open_risk=100.0,  # $100 cap = 2 positions max
            max_positions_per_symbol=10,  # Don't interfere with this test
        )
        # Open 2 positions ($100 total open risk)
        r1 = sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        sizer.register("sig_001", r1.risk_amount, symbol="EURUSD")

        r2 = sizer.calculate("GBPUSD", 1.2850, 1.2820, profile="sniper")
        sizer.register("sig_002", r2.risk_amount, symbol="GBPUSD")

        # 3rd should be blocked: $100 open + $50 new = $150 > $100 cap
        r3 = sizer.calculate("AUDUSD", 0.6650, 0.6620, profile="sniper")
        assert r3.blocked
        assert "exceeds max" in r3.block_reason
        assert "$100.00" in r3.block_reason

    def test_max_total_open_risk_blocks_9_gbpusd_scenario(self):
        """Reproduces the original bug: 9 GBPUSD positions at $50 each.

        With max_positions_per_symbol=1 and max_total_open_risk=150,
        only 1 position should be allowed — positions 2-9 must be blocked.
        """
        sizer = SLPositionSizer(
            account_balance=9314.0,
            risk_per_trade_pct=0.005,  # ~$46.57 per trade
            max_positions_per_symbol=1,
            max_total_open_risk=150.0,
        )
        r1 = sizer.calculate("GBPUSD", 1.2850, 1.2820, profile="sniper")
        assert not r1.blocked
        sizer.register("sig_001", r1.risk_amount, symbol="GBPUSD")

        # Attempts 2-9 must all be blocked
        for i in range(2, 10):
            r = sizer.calculate("GBPUSD", 1.2860 + i * 0.001, 1.2830 + i * 0.001, profile="sniper")
            assert r.blocked, f"Position #{i} should be blocked"
            assert "already open for GBPUSD" in r.block_reason

    def test_per_symbol_check_logged_in_block_reason(self):
        """Block reason for per-symbol limit must contain the symbol name."""
        sizer = SLPositionSizer(
            account_balance=10000.0,
            max_positions_per_symbol=1,
        )
        r1 = sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        sizer.register("sig_001", r1.risk_amount, symbol="EURUSD")

        r2 = sizer.calculate("EURUSD", 1.0860, 1.0830, profile="sniper")
        assert r2.blocked
        assert "EURUSD" in r2.block_reason
        assert "1" in r2.block_reason  # max count

    def test_total_open_risk_check_logged_with_amounts(self):
        """Block reason for total open risk must contain dollar amounts."""
        sizer = SLPositionSizer(
            account_balance=10000.0,
            risk_per_trade_pct=0.005,
            max_total_open_risk=75.0,
            max_positions_per_symbol=10,
        )
        r1 = sizer.calculate("EURUSD", 1.0850, 1.0820, profile="sniper")
        sizer.register("sig_001", r1.risk_amount, symbol="EURUSD")

        r2 = sizer.calculate("GBPUSD", 1.2850, 1.2820, profile="sniper")
        assert r2.blocked
        assert "$" in r2.block_reason
        assert "75.00" in r2.block_reason  # max cap amount


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
