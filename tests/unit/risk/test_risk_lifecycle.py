"""Phase 6 — Risk Lifecycle tests: close() wiring + daily reset.

Tests that:
6A — Closing a position calls sizer.close(signal_id, pnl), releasing risk.
6B — Day-boundary detection triggers reset_daily(), zeroing _daily_risk_used
     while preserving open_positions.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from forward_test.blend_runner import BlendForwardTestRunner


def _fresh_state_path() -> str:
    return f"/tmp/test_risk_lifecycle_{uuid.uuid4().hex}.json"


class TestCloseLifecycle:
    """Verify that closing a position releases risk via sizer.close()."""

    def setup_method(self):
        # Use a fresh state path per test so StatePersistence restore() does
        # not leak daily_risk_used or account_balance across test cases.
        self.state_path = _fresh_state_path()
        self.config = {
            "account_balance": 10_000.0,
            "risk_per_trade_pct": 0.005,
            "daily_risk_cap_pct": 0.03,
            "state_path": self.state_path,
        }
        self.runner = BlendForwardTestRunner(self.config)
        self.runner.start()

    def teardown_method(self):
        try:
            os.unlink(self.state_path)
        except FileNotFoundError:
            pass

    def test_close_reduces_open_risk(self):
        """After close(), open_risk decreases by the registered risk_amount."""
        signal_id = "test_sig_1"
        risk_amount = 50.0

        self.runner._sizer.register(signal_id, risk_amount)
        assert self.runner._sizer.open_risk == pytest.approx(risk_amount)

        self.runner.on_fill(signal_id, fill_price=1.1000, pnl=30.0)

        assert self.runner._sizer.open_risk == pytest.approx(0.0)
        assert signal_id not in self.runner._open_positions

    def test_close_with_loss_records_daily_risk(self):
        """A losing close adds realized loss to _daily_risk_used."""
        signal_id = "test_sig_loss"
        risk_amount = 80.0

        self.runner._sizer.register(signal_id, risk_amount)
        self.runner.on_fill(signal_id, fill_price=1.0900, pnl=-50.0)

        assert self.runner._sizer.open_risk == pytest.approx(0.0)
        assert self.runner._sizer._daily_risk_used == pytest.approx(50.0)

    def test_close_with_win_does_not_increase_daily_risk(self):
        """A winning close does not consume additional daily risk."""
        signal_id = "test_sig_win"
        risk_amount = 60.0

        self.runner._sizer.register(signal_id, risk_amount)
        pre_daily = self.runner._sizer._daily_risk_used

        self.runner.on_fill(signal_id, fill_price=1.1100, pnl=75.0)

        assert self.runner._sizer._daily_risk_used == pytest.approx(pre_daily)

    def test_close_pnl_updates_account_balance(self):
        """Closing with a win increases balance; a loss decreases it."""
        signal_id = "test_sig_pnl"
        risk_amount = 100.0

        self.runner._sizer.register(signal_id, risk_amount)
        pre_balance = self.runner._sizer.account_balance

        self.runner.on_fill(signal_id, fill_price=1.1050, pnl=150.0)

        assert self.runner._sizer.open_risk == pytest.approx(0.0)
        assert self.runner._sizer.account_balance == pytest.approx(pre_balance + 150.0)

    def test_close_loss_decreases_account_balance(self):
        """Closing with a loss decreases account balance."""
        signal_id = "test_sig_loss_pnl"
        risk_amount = 100.0

        self.runner._sizer.register(signal_id, risk_amount)
        pre_balance = self.runner._sizer.account_balance

        self.runner.on_fill(signal_id, fill_price=1.0950, pnl=-150.0)

        assert self.runner._sizer.open_risk == pytest.approx(0.0)
        assert self.runner._sizer.account_balance == pytest.approx(pre_balance - 150.0)
        assert self.runner._sizer._daily_risk_used == pytest.approx(150.0)

    def test_close_unknown_signal_id_logs_warning(self):
        """Closing an unknown signal_id logs warning and does not crash."""
        self.runner.on_fill("unknown_sig", fill_price=1.0, pnl=0.0)
        assert self.runner._sizer.open_risk == pytest.approx(0.0)

    def test_close_position_alias_works(self):
        """close_position() method works as alias for on_fill()."""
        signal_id = "test_alias"
        risk_amount = 70.0

        self.runner._sizer.register(signal_id, risk_amount)
        self.runner.close_position(signal_id, pnl=20.0)

        assert self.runner._sizer.open_risk == pytest.approx(0.0)

    def test_close_position_with_mapping(self):
        """close_position(position_id, pnl) uses position mapping to find signal_id."""
        signal_id = "strategy_abc_1234567890.12"
        position_id = "POS_001"
        risk_amount = 90.0

        self.runner._sizer.register(signal_id, risk_amount)
        self.runner.register_position_mapping(position_id, signal_id)

        assert self.runner._sizer.open_risk == pytest.approx(risk_amount)

        self.runner.close_position(position_id, pnl=-30.0)

        assert self.runner._sizer.open_risk == pytest.approx(0.0)
        assert self.runner._sizer._daily_risk_used == pytest.approx(30.0)
        assert position_id not in self.runner._position_id_to_signal_id

    def test_multiple_close_releases_each_position(self):
        """Closing multiple positions releases each one independently."""
        signals = [("sig_a", 50.0), ("sig_b", 70.0), ("sig_c", 30.0)]
        for sid, risk in signals:
            self.runner._sizer.register(sid, risk)

        assert self.runner._sizer.open_risk == pytest.approx(150.0)

        self.runner.on_fill("sig_b", fill_price=1.0, pnl=0.0)
        assert self.runner._sizer.open_risk == pytest.approx(80.0)

        self.runner.on_fill("sig_a", fill_price=1.0, pnl=0.0)
        assert self.runner._sizer.open_risk == pytest.approx(30.0)

        self.runner.on_fill("sig_c", fill_price=1.0, pnl=0.0)
        assert self.runner._sizer.open_risk == pytest.approx(0.0)


class TestDailyReset:
    """Verify that day-boundary triggers reset_daily()."""

    def setup_method(self):
        self.state_path = _fresh_state_path()
        self.config = {
            "account_balance": 10_000.0,
            "risk_per_trade_pct": 0.005,
            "daily_risk_cap_pct": 0.03,
            "state_path": self.state_path,
        }
        self.runner = BlendForwardTestRunner(self.config)
        self.runner.start()

    def teardown_method(self):
        try:
            os.unlink(self.state_path)
        except FileNotFoundError:
            pass

    def test_reset_daily_zeros_daily_risk_used(self):
        """reset_daily() sets _daily_risk_used to 0."""
        self.runner._sizer._daily_risk_used = 150.0

        self.runner._sizer.reset_daily()

        assert self.runner._sizer._daily_risk_used == pytest.approx(0.0)

    def test_reset_daily_preserves_open_positions(self):
        """reset_daily() does NOT touch _open_positions."""
        self.runner._sizer.register("sig_open_1", 100.0)
        self.runner._sizer.register("sig_open_2", 200.0)
        self.runner._sizer._daily_risk_used = 80.0

        self.runner._sizer.reset_daily()

        assert self.runner._sizer.open_risk == pytest.approx(300.0)
        assert "sig_open_1" in self.runner._sizer.open_positions
        assert "sig_open_2" in self.runner._sizer.open_positions

    def test_daily_reset_via_blend_runner(self):
        """daily_reset() on blend_runner resets sizer and logs."""
        self.runner._sizer._daily_risk_used = 120.0
        self.runner._sizer.register("sig_x", 50.0)

        self.runner.daily_reset()

        assert self.runner._sizer._daily_risk_used == pytest.approx(0.0)
        assert self.runner._sizer.open_risk == pytest.approx(50.0)
        assert "sig_x" in self.runner._sizer.open_positions

    def test_check_daily_reset_on_new_day(self):
        """_check_daily_reset triggers on day change."""
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        self.runner._current_day = yesterday.strftime("%Y-%m-%d")
        self.runner._sizer._daily_risk_used = 200.0

        now = datetime.now(timezone.utc)
        self.runner._check_daily_reset(now)

        assert self.runner._sizer._daily_risk_used == pytest.approx(0.0)
        assert self.runner._current_day == now.strftime("%Y-%m-%d")

    def test_check_daily_reset_same_day_no_reset(self):
        """_check_daily_reset does NOT reset on same day."""
        today = datetime.now(timezone.utc)
        day_str = today.strftime("%Y-%m-%d")
        self.runner._current_day = day_str
        self.runner._sizer._daily_risk_used = 200.0

        self.runner._check_daily_reset(today)

        assert self.runner._sizer._daily_risk_used == pytest.approx(200.0)

    def test_check_daily_reset_first_call_no_reset(self):
        """First call to _check_daily_reset (current_day=None) should not reset."""
        self.runner._current_day = None
        self.runner._sizer._daily_risk_used = 100.0

        now = datetime.now(timezone.utc)
        self.runner._check_daily_reset(now)

        assert self.runner._sizer._daily_risk_used == pytest.approx(100.0)
        assert self.runner._current_day == now.strftime("%Y-%m-%d")

    def test_daily_reset_after_losses_allows_new_trades(self):
        """After daily reset, daily_risk_remaining should reflect the reset."""
        daily_cap = self.runner._sizer.account_balance * self.runner._sizer.daily_risk_cap_pct
        self.runner._sizer._daily_risk_used = daily_cap * 0.95

        remaining_before = self.runner._sizer.daily_risk_remaining
        assert remaining_before < daily_cap * 0.1

        self.runner._sizer.reset_daily()

        remaining_after = self.runner._sizer.daily_risk_remaining
        assert remaining_after == pytest.approx(daily_cap, rel=1e-3)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
