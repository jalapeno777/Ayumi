"""Identity-keyed SLPositionSizer tests — Phase 5 refactor acceptance.

Tests the new signal_id-keyed API, thread-safety, and error cases
introduced in the Phase 5 risk-sizer refactor.
"""

from __future__ import annotations  # noqa: I001

import threading

import pytest

from risk.sl_position_sizer import SLPositionSizer


class TestIdentityKeyedRiskSizer:
    def setup_method(self):
        self.sizer = SLPositionSizer(
            account_balance=100_000.0,
            risk_per_trade_pct=0.005,
            daily_risk_cap_pct=0.03,
        )

    # ── Register / open_risk ─────────────────────────────────────────

    def test_register_stores_risk_keyed_by_signal_id(self):
        self.sizer.register("sig-1", 100.0)
        self.sizer.register("sig-2", 150.0)
        assert self.sizer.open_risk == pytest.approx(250.0)
        assert self.sizer.open_positions == {"sig-1": 100.0, "sig-2": 150.0}

    def test_register_duplicate_raises_value_error(self):
        self.sizer.register("sig-1", 100.0)
        with pytest.raises(ValueError, match="sig-1.*already registered"):
            self.sizer.register("sig-1", 200.0)
        # First amount is preserved
        assert self.sizer.open_risk == pytest.approx(100.0)

    # ── Cancel ─────────────────────────────────────────────────────────

    def test_cancel_removes_risk_by_key(self):
        self.sizer.register("sig-1", 100.0)
        self.sizer.register("sig-2", 150.0)
        self.sizer.cancel("sig-1")
        assert self.sizer.open_risk == pytest.approx(150.0)
        assert "sig-1" not in self.sizer.open_positions
        assert "sig-2" in self.sizer.open_positions

    def test_cancel_unknown_is_idempotent(self):
        """Cancel on unknown signal_id should log warning and return gracefully."""
        # Should NOT raise — idempotent cancel prevents timeout/crash race.
        self.sizer.cancel("missing")
        assert self.sizer.open_risk == pytest.approx(0.0)

    def test_double_cancel_is_idempotent(self):
        """Second cancel for the same signal_id must be a no-op, not raise."""
        self.sizer.register("sig-1", 100.0)
        self.sizer.cancel("sig-1")
        self.sizer.cancel("sig-1")  # Should not raise
        assert self.sizer.open_risk == pytest.approx(0.0)

    # ── Close ──────────────────────────────────────────────────────────

    def test_close_removes_risk_and_records_pnl(self):
        self.sizer.register("sig-1", 100.0)
        self.sizer.close("sig-1", pnl=80.0)
        assert self.sizer.open_risk == pytest.approx(0.0)
        assert "sig-1" not in self.sizer.open_positions

    def test_close_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="Cannot close unknown signal_id='missing'"):
            self.sizer.close("missing", pnl=0.0)

    def test_close_already_cancelled_raises_key_error(self):
        self.sizer.register("sig-1", 100.0)
        self.sizer.cancel("sig-1")
        with pytest.raises(KeyError, match="Cannot close unknown signal_id='sig-1'"):
            self.sizer.close("sig-1", pnl=0.0)

    # ── Daily accounting via new API ───────────────────────────────────

    def test_close_loss_counts_toward_daily_risk_used(self):
        self.sizer.register("sig-1", 100.0)
        self.sizer.close("sig-1", pnl=-60.0)
        # Actual loss consumed; recycling frees open risk
        assert self.sizer.open_risk == pytest.approx(0.0)
        assert self.sizer._daily_risk_used == pytest.approx(60.0)

    def test_close_win_does_not_count_toward_daily_risk_used(self):
        self.sizer.register("sig-1", 100.0)
        self.sizer.close("sig-1", pnl=80.0)
        assert self.sizer.open_risk == pytest.approx(0.0)
        assert self.sizer._daily_risk_used == pytest.approx(0.0)

    # ── Thread safety ────────────────────────────────────────────────

    def test_concurrent_register_no_lost_updates(self):
        """2 threads each register 50 distinct positions concurrently."""

        def do_register(start: int):
            for i in range(50):
                sid = f"thread-{start}-pos-{i}"
                self.sizer.register(sid, 10.0)

        threads = [
            threading.Thread(target=do_register, args=(0,)),
            threading.Thread(target=do_register, args=(1,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert self.sizer.open_risk == pytest.approx(1000.0)  # 100 * 10
        assert len(self.sizer.open_positions) == 100

    def test_concurrent_register_and_cancel_consistent(self):
        """Register many positions, then race cancellations — open_risk ends correct."""
        n = 100
        for i in range(n):
            self.sizer.register(f"pos-{i}", 10.0)

        def cancel_half(start: int):
            for i in range(start, n, 2):
                self.sizer.cancel(f"pos-{i}")

        threads = [
            threading.Thread(target=cancel_half, args=(0,)),
            threading.Thread(target=cancel_half, args=(1,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert self.sizer.open_risk == pytest.approx(0.0)
        assert self.sizer.open_positions == {}

    # ── Backward-compat scalar API still works ( Phase 4 callers ) ─────

    def test_legacy_register_open_position_still_works(self):
        self.sizer.register_open_position(75.0)
        assert self.sizer.open_risk == pytest.approx(75.0)

    def test_legacy_cancel_position_still_works(self):
        self.sizer.register_open_position(100.0)
        self.sizer.cancel_position(40.0)
        assert self.sizer.open_risk == pytest.approx(60.0)

    def test_legacy_close_position_still_works(self):
        self.sizer.register_open_position(100.0)
        self.sizer.close_position(pnl=-50.0, risk_amount=100.0, win=False)
        assert self.sizer.open_risk == pytest.approx(0.0)
        assert self.sizer._daily_risk_used == pytest.approx(50.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
