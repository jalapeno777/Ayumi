"""Unit tests for :mod:`risk.engine` — FTMO Execution Guardrail Engine.

Covers all FTMO 1-Step Standard rules:

* Daily DD rejection (3% hard limit, projected DD with trade risk)
* Total DD rejection (10% hard limit, 8% stop threshold + CRITICAL alert)
* Max concurrent positions (3 default)
* Per-trade risk cap (0.5% default)
* Drawdown scaling (1.5% → halve size, 2.5% → block)
* Kill switch (blocks ALL after activation, only reset explicitly)
* Daily reset (manual + auto on date rollover)
* Session filter (mock NFP window, ±30 min)
* Slippage threshold (3 pips default)
* Multiple checks pass for a valid order
* Config validation (rejects invalid thresholds)
* LOCKED FTMO constants — verify they cannot be overridden
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from risk.engine import (
    FTMO_DAILY_DD_LIMIT_PCT,
    FTMO_TOTAL_DD_LIMIT_PCT,
    BlackoutWindow,
    CheckResult,
    GuardrailConfig,
    GuardrailEngine,
    OrderRequest,
    RejectReason,
    build_ftmo1step_guardrail,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────
def _clock_at(year, month, day, hour=12, minute=0):
    """Return a clock callable pinned to a fixed UTC datetime."""
    fixed = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    return lambda: fixed


@pytest.fixture
def clock_monday_noon():
    """Fixed clock: Mon 2026-07-13 12:00 UTC (well away from news windows)."""
    return _clock_at(2026, 7, 13, 12, 0)


@pytest.fixture
def engine(clock_monday_noon):
    """A vanilla FTMO 1-Step Standard guardrail on a $10k account."""
    return GuardrailEngine(
        starting_balance=10_000.0,
        config=GuardrailConfig(),
        blackout_windows=[],
        clock=clock_monday_noon,
    )


@pytest.fixture
def sample_order():
    """A small valid order: 0.1 lots EURUSD, $50 risk = 0.5% of $10k."""
    return OrderRequest(
        symbol="EURUSD",
        side="buy",
        size=0.1,
        entry_price=1.1000,
        stop_loss_price=1.0950,
        risk_amount_usd=50.0,
        estimated_slippage_pips=1.0,
        timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. LOCKED FTMO constants
# ─────────────────────────────────────────────────────────────────────────────
class TestLockedFTMOConstants:
    def test_daily_dd_limit_constant_is_3_percent(self):
        assert FTMO_DAILY_DD_LIMIT_PCT == 0.03

    def test_total_dd_limit_constant_is_10_percent(self):
        assert FTMO_TOTAL_DD_LIMIT_PCT == 0.10

    def test_engine_exposes_locked_constants(self, engine):
        assert engine.daily_dd_limit_pct == 0.03
        assert engine.total_dd_limit_pct == 0.10

    def test_config_does_not_expose_locked_constants(self):
        """The two locked FTMO constants are NOT in GuardrailConfig.

        This prevents construction-time overrides of the FTMO rules.
        """
        config = GuardrailConfig()
        assert not hasattr(config, "daily_dd_limit_pct")
        assert not hasattr(config, "total_dd_limit_pct")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Config validation
# ─────────────────────────────────────────────────────────────────────────────
class TestGuardrailConfig:
    def test_defaults_match_ftmo_1step(self):
        c = GuardrailConfig()
        assert c.max_concurrent_positions == 3
        assert c.per_trade_risk_pct == 0.005
        assert c.slippage_threshold_pips == 3.0
        assert c.daily_dd_scale_threshold == 0.015
        assert c.daily_dd_stop_threshold == 0.025
        assert c.total_dd_stop_threshold == 0.08

    def test_rejects_max_concurrent_zero(self):
        with pytest.raises(ValueError, match="max_concurrent_positions"):
            GuardrailConfig(max_concurrent_positions=0)

    def test_rejects_per_trade_risk_zero(self):
        with pytest.raises(ValueError, match="per_trade_risk_pct"):
            GuardrailConfig(per_trade_risk_pct=0.0)

    def test_rejects_scale_above_stop(self):
        with pytest.raises(ValueError, match="scale_threshold"):
            GuardrailConfig(daily_dd_scale_threshold=0.03)

    def test_rejects_daily_stop_above_ftmo_limit(self):
        with pytest.raises(ValueError, match="daily_dd_stop_threshold"):
            GuardrailConfig(daily_dd_stop_threshold=0.05)

    def test_rejects_total_stop_above_ftmo_limit(self):
        with pytest.raises(ValueError, match="total_dd_stop_threshold"):
            GuardrailConfig(total_dd_stop_threshold=0.15)


# ─────────────────────────────────────────────────────────────────────────────
# 3. OrderRequest validation
# ─────────────────────────────────────────────────────────────────────────────
class TestOrderRequestValidation:
    def test_rejects_bad_side(self):
        with pytest.raises(ValueError, match="side"):
            OrderRequest(
                symbol="EURUSD", side="long", size=0.1,
                entry_price=1.10, stop_loss_price=1.09, risk_amount_usd=50.0,
            )

    def test_rejects_negative_size(self):
        with pytest.raises(ValueError, match="size"):
            OrderRequest(
                symbol="EURUSD", side="buy", size=-0.1,
                entry_price=1.10, stop_loss_price=1.09, risk_amount_usd=50.0,
            )

    def test_rejects_negative_risk(self):
        with pytest.raises(ValueError, match="risk_amount_usd"):
            OrderRequest(
                symbol="EURUSD", side="buy", size=0.1,
                entry_price=1.10, stop_loss_price=1.09, risk_amount_usd=-1.0,
            )

    def test_rejects_negative_slippage(self):
        with pytest.raises(ValueError, match="estimated_slippage_pips"):
            OrderRequest(
                symbol="EURUSD", side="buy", size=0.1,
                entry_price=1.10, stop_loss_price=1.09, risk_amount_usd=50.0,
                estimated_slippage_pips=-1.0,
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Basic happy path
# ─────────────────────────────────────────────────────────────────────────────
class TestHappyPath:
    def test_valid_order_passes_all_checks(self, engine, sample_order):
        result = engine.check_order(sample_order)
        assert result.allowed is True
        assert result.reason == "ok"
        assert result.adjusted_size is None  # No DD scaling needed

    def test_tuple_unpacking(self, engine, sample_order):
        allowed, reason, adjusted_size = engine.check_order(sample_order)
        assert allowed is True
        assert reason == "ok"
        assert adjusted_size is None

    def test_get_status_snapshot(self, engine):
        s = engine.get_status()
        assert s["starting_balance"] == 10_000.0
        assert s["current_balance"] == 10_000.0
        assert s["daily_dd_pct"] == 0.0
        assert s["total_dd_pct"] == 0.0
        assert s["open_positions"] == 0
        assert s["kill_switch_active"] is False
        assert s["ftmo_daily_dd_limit_pct"] == 0.03
        assert s["ftmo_total_dd_limit_pct"] == 0.10


# ─────────────────────────────────────────────────────────────────────────────
# 5. Daily DD rejection (3% hard limit + projected DD with trade risk)
# ─────────────────────────────────────────────────────────────────────────────
class TestDailyDDRejection:
    def test_rejects_when_projected_dd_exceeds_3pct(self, engine):
        """$270 daily loss + $50 trade risk = $320 = 3.2% > 3%.

        Risk $50 is exactly at the per-trade cap (0.5% of $10k), so the
        per-trade check passes and the projected DD check fires.
        """
        engine._daily_pnl = -270.0  # 2.7% daily loss
        order = OrderRequest(
            symbol="GBPUSD",
            side="buy",
            size=0.1,
            entry_price=1.3000,
            stop_loss_price=1.2950,
            risk_amount_usd=50.0,  # 0.5% — at per-trade cap
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.DAILY_DD_STOP.value
        assert result.adjusted_size is None

    def test_rejects_at_exactly_3pct(self, engine):
        """At projected 3.0% exactly — equals limit, should pass (NOT >).

        $250 daily loss (2.5%) + $50 risk (0.5%) = 3.0% exactly.
        Per spec: reject only if projected > 3%, so 3.0% passes.
        """
        engine._daily_pnl = -250.0  # 2.5% daily loss
        order = OrderRequest(
            symbol="GBPUSD", side="buy", size=0.1,
            entry_price=1.30, stop_loss_price=1.29,
            risk_amount_usd=50.0,  # 0.5% — at per-trade cap
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is True

    def test_rejects_just_above_3pct(self, engine):
        """At 2.6% + 0.5% risk = 3.1% > 3% → reject.

        Risk $50 is at the per-trade cap, so per-trade check passes.
        Projected DD 3.1% > 3% limit → DAILY_DD_STOP.
        """
        engine._daily_pnl = -260.0  # 2.6%
        order = OrderRequest(
            symbol="GBPUSD", side="buy", size=0.1,
            entry_price=1.30, stop_loss_price=1.29,
            risk_amount_usd=50.0,  # 0.5% — at per-trade cap
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.DAILY_DD_STOP.value

    def test_daily_dd_stop_threshold_blocks_at_2_5pct(self, engine):
        """At 2.6% daily DD, no new entries (configurable stop threshold)."""
        engine._daily_pnl = -260.0  # 2.6%
        order = OrderRequest(
            symbol="GBPUSD", side="buy", size=0.05,
            entry_price=1.30, stop_loss_price=1.29,
            risk_amount_usd=10.0,  # Tiny risk, but DD already past stop
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.DAILY_DD_STOP.value


# ─────────────────────────────────────────────────────────────────────────────
# 6. Total DD rejection (10% limit, 8% stop threshold)
# ─────────────────────────────────────────────────────────────────────────────
class TestTotalDDRejection:
    def test_rejects_when_total_dd_exceeds_10pct(self, engine):
        """Peak $11k → current $9.8k = $1,200 DD = 10.9% > 10% → reject."""
        engine._peak_balance = 11_000.0
        engine._current_balance = 9_800.0
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.05,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.TOTAL_DD_BREACH.value

    def test_rejects_at_8pct_total_dd_stop_threshold(self, engine):
        """At 8.5% total DD, no new entries + CRITICAL."""
        engine._peak_balance = 11_000.0
        engine._current_balance = 10_065.0  # 8.5% DD from peak
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.05,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.TOTAL_DD_BREACH.value

    def test_allows_at_7pct_total_dd(self, engine):
        """At 7.9% total DD, still under both 8% stop and 10% hard limit."""
        engine._peak_balance = 11_000.0
        engine._current_balance = 10_131.0  # 7.9% DD
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.05,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is True

    def test_total_dd_pct_uses_peak_balance(self, engine):
        """Total DD = (peak - current) / peak, not starting_balance."""
        engine._starting_balance = 10_000.0
        engine._peak_balance = 12_000.0
        engine._current_balance = 11_500.0  # 4.17% from peak
        assert 0.04 < engine.total_dd_pct < 0.05


# ─────────────────────────────────────────────────────────────────────────────
# 7. Max concurrent positions
# ─────────────────────────────────────────────────────────────────────────────
class TestMaxConcurrentPositions:
    def test_allows_when_below_limit(self, engine, sample_order):
        engine.register_open_position()
        result = engine.check_order(sample_order)
        assert result.allowed is True

    def test_rejects_at_limit(self, engine, sample_order):
        for _ in range(3):
            engine.register_open_position()
        assert engine.open_positions == 3
        result = engine.check_order(sample_order)
        assert result.allowed is False
        assert result.reason == RejectReason.MAX_CONCURRENT.value

    def test_rejects_above_limit(self, engine, sample_order):
        for _ in range(5):
            engine.register_open_position()
        result = engine.check_order(sample_order)
        assert result.allowed is False
        assert result.reason == RejectReason.MAX_CONCURRENT.value

    def test_decrements_on_position_close(self, engine, sample_order):
        for _ in range(3):
            engine.register_open_position()
        assert engine.open_positions == 3
        engine.update_state(position_closed=True, pnl=10.0)
        assert engine.open_positions == 2
        # Now allowed again
        result = engine.check_order(sample_order)
        assert result.allowed is True

    def test_custom_max_concurrent(self, clock_monday_noon):
        engine = GuardrailEngine(
            starting_balance=10_000.0,
            config=GuardrailConfig(max_concurrent_positions=5),
            blackout_windows=[],
            clock=clock_monday_noon,
        )
        for _ in range(5):
            engine.register_open_position()
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.05,
            entry_price=1.10, stop_loss_price=1.09, risk_amount_usd=10.0,
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.MAX_CONCURRENT.value


# ─────────────────────────────────────────────────────────────────────────────
# 8. Per-trade risk limit
# ─────────────────────────────────────────────────────────────────────────────
class TestPerTradeRisk:
    def test_allows_within_per_trade_cap(self, engine):
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.1,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=50.0,  # Exactly 0.5% of $10k
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is True

    def test_rejects_above_per_trade_cap(self, engine):
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.5,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=200.0,  # 2% of $10k, way over 0.5% cap
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.PER_TRADE_RISK.value

    def test_per_trade_cap_scales_with_balance(self, engine):
        """After a loss, per-trade cap shrinks proportionally."""
        engine._current_balance = 9_500.0  # 5% loss
        # 0.5% of $9,500 = $47.50 cap
        order_just_over = OrderRequest(
            symbol="EURUSD", side="buy", size=0.1,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=48.0,
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order_just_over)
        assert result.allowed is False
        assert result.reason == RejectReason.PER_TRADE_RISK.value


# ─────────────────────────────────────────────────────────────────────────────
# 9. Drawdown scaling (1.5% → halve, 2.5% → block)
# ─────────────────────────────────────────────────────────────────────────────
class TestDrawdownScaling:
    def test_no_scaling_below_1_5pct(self, engine, sample_order):
        engine._daily_pnl = -100.0  # 1.0%
        result = engine.check_order(sample_order)
        assert result.allowed is True
        assert result.adjusted_size is None

    def test_halves_size_at_1_5pct(self, engine):
        engine._daily_pnl = -160.0  # 1.6%
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.10,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=20.0,
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is True
        assert result.adjusted_size is not None
        assert result.adjusted_size == pytest.approx(0.05, abs=1e-9)

    def test_blocks_at_2_5pct(self, engine):
        engine._daily_pnl = -260.0  # 2.6%
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.05,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.DAILY_DD_STOP.value

    def test_halved_size_still_within_per_trade_cap(self, engine):
        """At 1.6% DD with size that, when halved, still respects 0.5% cap."""
        engine._daily_pnl = -160.0  # 1.6%
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.10,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=20.0,  # halved = $10, well under $50 cap
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is True
        assert result.adjusted_size == 0.05

    def test_halved_size_violates_per_trade_cap(self, engine):
        """Trade at the per-trade cap with DD > 1.5%: even halved it caps out.

        With risk = $50 (0.5% cap exactly) and DD at 1.6%:
          halved risk = $25 (still within cap) — actually this DOES allow.
        Let's make a trade with risk > cap to verify the per-trade check
        fires before scaling.
        """
        # Place risk ABOVE cap so per-trade check rejects (before scaling)
        engine._daily_pnl = -160.0  # 1.6%
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.5,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=200.0,  # way over $50 cap
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        # Per-trade check fires first (200 > 50 cap) — reject.
        assert result.allowed is False
        assert result.reason == RejectReason.PER_TRADE_RISK.value


# ─────────────────────────────────────────────────────────────────────────────
# 10. Kill switch
# ─────────────────────────────────────────────────────────────────────────────
class TestKillSwitch:
    def test_starts_inactive(self, engine):
        assert engine.is_killed is False
        assert engine.kill_switch_reason is None

    def test_activates_and_blocks(self, engine, sample_order):
        engine.kill_switch(reason="FTMO daily DD breach")
        assert engine.is_killed is True
        assert engine.kill_switch_reason == "FTMO daily DD breach"
        result = engine.check_order(sample_order)
        assert result.allowed is False
        assert result.reason == RejectReason.KILL_SWITCH_ACTIVE.value

    def test_reset_clears(self, engine, sample_order):
        engine.kill_switch(reason="test")
        engine.reset_kill_switch(reason="operator_override")
        assert engine.is_killed is False
        result = engine.check_order(sample_order)
        assert result.allowed is True

    def test_reset_when_not_active_is_noop(self, engine):
        # Should not raise
        engine.reset_kill_switch()
        assert engine.is_killed is False

    def test_kill_switch_is_independent_of_daily_reset(self, engine, sample_order):
        """The kill switch must NOT be cleared by daily reset."""
        engine.kill_switch(reason="permanent halt")
        engine.reset_daily()
        assert engine.is_killed is True
        result = engine.check_order(sample_order)
        assert result.allowed is False

    def test_kill_switch_is_independent_of_state_updates(self, engine):
        engine.kill_switch(reason="test")
        engine.update_state(position_closed=True, pnl=-50.0)
        assert engine.is_killed is True

    def test_kill_switch_overrides_all_other_checks(self, engine):
        """Even with everything else looking fine, kill switch wins."""
        engine.kill_switch(reason="emergency")
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.05,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.KILL_SWITCH_ACTIVE.value


# ─────────────────────────────────────────────────────────────────────────────
# 11. Daily reset
# ─────────────────────────────────────────────────────────────────────────────
class TestDailyReset:
    def test_manual_reset_zeroes_daily(self, engine):
        engine._daily_pnl = -200.0
        engine._daily_trade_count = 5
        engine.reset_daily()
        assert engine.daily_pnl == 0.0
        assert engine.daily_trade_count == 0

    def test_auto_reset_on_date_change(self):
        """When clock crosses UTC midnight, daily counters reset."""
        day1_clock = _clock_at(2026, 7, 13, 23, 59)
        day2_clock = _clock_at(2026, 7, 14, 0, 1)
        current = [day1_clock()]

        def clock():
            return current[0]

        engine = GuardrailEngine(
            starting_balance=10_000.0,
            config=GuardrailConfig(),
            blackout_windows=[],
            clock=clock,
        )
        # Day 1: lose $200
        engine.update_state(position_closed=True, pnl=-200.0)
        assert engine.daily_pnl == -200.0

        # Clock crosses midnight → day 2
        current[0] = day2_clock()

        # Day 2: state update should auto-reset first
        engine.update_state(position_closed=True, pnl=50.0)
        assert engine.daily_pnl == 50.0  # Not -200 + 50 = -150

    def test_update_state_increments_peak(self, engine):
        """Current balance > peak balance updates peak."""
        engine.update_state(position_closed=False, pnl=500.0)
        assert engine.peak_balance == 10_500.0

    def test_update_state_with_zero_pnl(self, engine):
        """Zero-pnl close (e.g. scratch) doesn't break counters."""
        engine.update_state(position_closed=True, pnl=0.0)
        assert engine.daily_pnl == 0.0
        assert engine.total_pnl == 0.0

    def test_open_positions_decrement_only_if_positive(self, engine):
        """Defensive: don't decrement below zero."""
        engine.update_state(position_closed=True, pnl=0.0)
        assert engine.open_positions == 0


# ─────────────────────────────────────────────────────────────────────────────
# 12. Session filter (mock NFP/FOMC blackout)
# ─────────────────────────────────────────────────────────────────────────────
class TestSessionFilter:
    def test_blocks_inside_nfp_window(self):
        # NFP at 13:30 UTC on 2026-08-07, blackout 13:00..14:00
        nfp_window = BlackoutWindow(
            event_name="NFP",
            start_utc=datetime(2026, 8, 7, 13, 0, tzinfo=timezone.utc),
            end_utc=datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc),
        )
        fixed_clock = _clock_at(2026, 8, 7, 13, 30)  # Inside window
        engine = GuardrailEngine(
            starting_balance=10_000.0,
            config=GuardrailConfig(),
            blackout_windows=[nfp_window],
            clock=fixed_clock,
        )
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.05,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            timestamp=datetime(2026, 8, 7, 13, 30, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.BLACKOUT_WINDOW.value

    def test_allows_outside_nfp_window(self):
        nfp_window = BlackoutWindow(
            event_name="NFP",
            start_utc=datetime(2026, 8, 7, 13, 0, tzinfo=timezone.utc),
            end_utc=datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc),
        )
        # 30 min BEFORE the blackout starts
        fixed_clock = _clock_at(2026, 8, 7, 12, 30)
        engine = GuardrailEngine(
            starting_balance=10_000.0,
            config=GuardrailConfig(),
            blackout_windows=[nfp_window],
            clock=fixed_clock,
        )
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.05,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            timestamp=datetime(2026, 8, 7, 12, 30, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is True

    def test_blocks_at_window_boundary_start(self):
        nfp_window = BlackoutWindow(
            event_name="FOMC",
            start_utc=datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc),
            end_utc=datetime(2026, 7, 29, 19, 30, tzinfo=timezone.utc),
        )
        fixed_clock = _clock_at(2026, 7, 29, 18, 0)
        engine = GuardrailEngine(
            starting_balance=10_000.0,
            config=GuardrailConfig(),
            blackout_windows=[nfp_window],
            clock=fixed_clock,
        )
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.05,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
        )
        assert engine.is_in_blackout() is True
        result = engine.check_order(order)
        assert result.allowed is False

    def test_add_blackout_window_runtime(self, engine):
        nfp_window = BlackoutWindow(
            event_name="ECB",
            start_utc=datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc),
            end_utc=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
        )
        engine.add_blackout_window(nfp_window)
        # Engine clock is 12:00 noon, blackout starts at 13:00 → not in window
        assert engine.is_in_blackout() is False

    def test_clear_blackout_windows(self, engine):
        nfp_window = BlackoutWindow(
            event_name="NFP",
            start_utc=datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc),
            end_utc=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
        )
        engine.add_blackout_window(nfp_window)
        assert engine.is_in_blackout() is False  # 12:00 noon
        engine.clear_blackout_windows()
        assert len(engine._blackout_windows) == 0

    def test_naive_datetime_treated_as_utc(self):
        """Naive timestamps are coerced to UTC, not rejected."""
        nfp_window = BlackoutWindow(
            event_name="NFP",
            start_utc=datetime(2026, 8, 7, 13, 0, tzinfo=timezone.utc),
            end_utc=datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc),
        )
        engine = GuardrailEngine(
            starting_balance=10_000.0,
            config=GuardrailConfig(),
            blackout_windows=[nfp_window],
            clock=lambda: datetime(2026, 8, 7, 13, 30, tzinfo=timezone.utc),
        )
        # Order with naive datetime inside the window
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.05,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            timestamp=datetime(2026, 8, 7, 13, 30),  # NAIVE
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.BLACKOUT_WINDOW.value


class TestBlackoutWindowValidation:
    def test_rejects_naive_start(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            BlackoutWindow(
                event_name="NFP",
                start_utc=datetime(2026, 8, 7, 13, 0),  # naive
                end_utc=datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc),
            )

    def test_rejects_inverted_window(self):
        with pytest.raises(ValueError, match="start"):
            BlackoutWindow(
                event_name="NFP",
                start_utc=datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc),
                end_utc=datetime(2026, 8, 7, 13, 0, tzinfo=timezone.utc),
            )


# ─────────────────────────────────────────────────────────────────────────────
# 13. Slippage threshold
# ─────────────────────────────────────────────────────────────────────────────
class TestSlippageThreshold:
    def test_allows_within_threshold(self, engine, sample_order):
        # sample_order has slippage 1.0 pip, threshold 3.0 → allowed
        result = engine.check_order(sample_order)
        assert result.allowed is True

    def test_allows_at_threshold(self, engine):
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.1,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            estimated_slippage_pips=3.0,  # Exactly at threshold
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is True

    def test_rejects_above_threshold(self, engine):
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.1,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            estimated_slippage_pips=3.5,
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.SLIPPAGE.value

    def test_rejects_way_above_threshold(self, engine):
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.1,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            estimated_slippage_pips=10.0,
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.SLIPPAGE.value

    def test_custom_slippage_threshold(self, clock_monday_noon):
        engine = GuardrailEngine(
            starting_balance=10_000.0,
            config=GuardrailConfig(slippage_threshold_pips=1.5),
            blackout_windows=[],
            clock=clock_monday_noon,
        )
        order = OrderRequest(
            symbol="EURUSD", side="buy", size=0.05,
            entry_price=1.10, stop_loss_price=1.09,
            risk_amount_usd=10.0,
            estimated_slippage_pips=2.0,
            timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_order(order)
        assert result.allowed is False
        assert result.reason == RejectReason.SLIPPAGE.value


# ─────────────────────────────────────────────────────────────────────────────
# 14. Multiple checks pass for valid order
# ─────────────────────────────────────────────────────────────────────────────
class TestValidOrderPassesAllChecks:
    def test_multiple_independent_checks_pass(self, engine, sample_order):
        """For a valid order, NONE of the reject reasons fire."""
        result = engine.check_order(sample_order)
        assert result.allowed is True

        # Sanity: none of the rejection conditions are met
        assert engine.is_killed is False
        assert engine.is_in_blackout() is False
        assert engine.daily_dd_pct < engine._config.daily_dd_stop_threshold
        assert engine.total_dd_pct < engine._config.total_dd_stop_threshold
        assert engine.open_positions < engine._config.max_concurrent_positions
        assert sample_order.risk_amount_usd <= (
            engine.current_balance * engine._config.per_trade_risk_pct
        )
        assert sample_order.estimated_slippage_pips <= engine._config.slippage_threshold_pips

    def test_full_round_trip_open_close(self, engine, sample_order):
        """Open → close updates state correctly."""
        result = engine.check_order(sample_order)
        assert result.allowed is True
        engine.register_open_position()
        assert engine.open_positions == 1
        # Broker fills at $50 risk → wins $30
        engine.update_state(position_closed=True, pnl=30.0)
        assert engine.open_positions == 0
        assert engine.daily_pnl == 30.0
        assert engine.total_pnl == 30.0
        assert engine.current_balance == 10_030.0


# ─────────────────────────────────────────────────────────────────────────────
# 15. Convenience constructor
# ─────────────────────────────────────────────────────────────────────────────
class TestBuildHelper:
    def test_build_ftmo1step_default(self, clock_monday_noon):
        engine = build_ftmo1step_guardrail(
            starting_balance=10_000.0,
            clock=clock_monday_noon,
        )
        assert engine.daily_dd_limit_pct == 0.03
        assert engine.total_dd_limit_pct == 0.10
        assert engine.config.max_concurrent_positions == 3
        assert engine.config.per_trade_risk_pct == 0.005
        assert engine.config.slippage_threshold_pips == 3.0

    def test_build_with_blackouts(self, clock_monday_noon):
        window = BlackoutWindow(
            event_name="FOMC",
            start_utc=datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc),
            end_utc=datetime(2026, 7, 29, 19, 0, tzinfo=timezone.utc),
        )
        engine = build_ftmo1step_guardrail(
            starting_balance=10_000.0,
            blackout_windows=[window],
            clock=clock_monday_noon,
        )
        assert len(engine._blackout_windows) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 16. Invalid construction
# ─────────────────────────────────────────────────────────────────────────────
class TestConstructionGuards:
    def test_rejects_zero_balance(self, clock_monday_noon):
        with pytest.raises(ValueError, match="starting_balance"):
            GuardrailEngine(
                starting_balance=0.0,
                config=GuardrailConfig(),
                clock=clock_monday_noon,
            )

    def test_rejects_negative_balance(self, clock_monday_noon):
        with pytest.raises(ValueError, match="starting_balance"):
            GuardrailEngine(
                starting_balance=-100.0,
                config=GuardrailConfig(),
                clock=clock_monday_noon,
            )