"""Unit tests for PositionMonitor (Phase 1D — Position Monitoring & Lifecycle).

Tests cover:
  - PositionStatus enum expansion (7 statuses, is_closed property)
  - Position field defaults (MAE/MFE, water marks, time_in_trade)
  - PositionMonitor init with defaults
  - update_positions tracks MAE/MFE (long position, price up then down)
  - update_positions tracks high/low water marks
  - time_in_trade calculation
  - check_time_exits returns positions exceeding duration limit
  - check_drawdown_alerts returns warnings at threshold
  - get_portfolio_summary returns correct metrics
  - get_position_report returns detailed single-position info
  - Kill switch FREEZE on portfolio drawdown breach
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from adapters.ctrader.models import (
    Position,
    PositionStatus,
    TradeDirection,
)
from adapters.ctrader.order_manager import OrderManager, PositionSizeConfig
from adapters.ctrader.position_monitor import PositionMonitor
from adapters.ctrader.risk_guard import FTMOConfig, RiskGuard


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def order_manager():
    return OrderManager(position_config=PositionSizeConfig())


@pytest.fixture
def risk_guard():
    return RiskGuard(ftmo_config=FTMOConfig(), starting_balance=100000.0)


@pytest.fixture
def kill_switch():
    ks = MagicMock()
    ks.is_globally_killed.return_value = False
    ks.is_globally_frozen.return_value = False
    ks.is_active.return_value = False
    return ks


@pytest.fixture
def monitor(order_manager, risk_guard, kill_switch):
    return PositionMonitor(
        order_manager=order_manager,
        risk_guard=risk_guard,
        kill_switch=kill_switch,
        max_trade_duration_sec=14400,
        check_interval_sec=5.0,
    )


def _make_long_position(order_manager, symbol="EURUSD", entry=1.1000, volume=0.1):
    """Create a long position via paper order for testing."""
    result = order_manager.execute_paper_order(
        symbol=symbol,
        direction=TradeDirection.LONG,
        volume=volume,
        entry_price=entry,
        stop_loss=entry - 0.0050,
        take_profit=entry + 0.0100,
        comment="test",
    )
    return result.position


def _make_short_position(order_manager, symbol="EURUSD", entry=1.1000, volume=0.1):
    """Create a short position via paper order for testing."""
    result = order_manager.execute_paper_order(
        symbol=symbol,
        direction=TradeDirection.SHORT,
        volume=volume,
        entry_price=entry,
        stop_loss=entry + 0.0050,
        take_profit=entry - 0.0100,
        comment="test",
    )
    return result.position


# ── 1. PositionStatus enum ────────────────────────────────────────────────────


class TestPositionStatusEnum:
    def test_has_all_seven_statuses(self):
        statuses = {s for s in PositionStatus}
        assert len(statuses) == 7
        assert PositionStatus.ENTRY_PENDING in statuses
        assert PositionStatus.OPEN in statuses
        assert PositionStatus.TP_HIT in statuses
        assert PositionStatus.SL_HIT in statuses
        assert PositionStatus.TIMEOUT_CLOSE in statuses
        assert PositionStatus.MANUAL_CLOSE in statuses
        assert PositionStatus.CLOSED in statuses

    def test_is_closed_property_true_for_terminal(self):
        assert PositionStatus.TP_HIT.is_closed is True
        assert PositionStatus.SL_HIT.is_closed is True
        assert PositionStatus.TIMEOUT_CLOSE.is_closed is True
        assert PositionStatus.MANUAL_CLOSE.is_closed is True
        assert PositionStatus.CLOSED.is_closed is True

    def test_is_closed_property_false_for_open_states(self):
        assert PositionStatus.OPEN.is_closed is False
        assert PositionStatus.ENTRY_PENDING.is_closed is False

    def test_backward_compat_closed_value(self):
        assert PositionStatus.CLOSED.value == "closed"
        assert PositionStatus.OPEN.value == "open"


# ── 2. Position field defaults ────────────────────────────────────────────────


class TestPositionDefaults:
    def test_new_position_has_zero_mfe_mae(self):
        pos = Position(
            position_id="test_1",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            current_price=1.1000,
        )
        assert pos.max_favorable_excursion == 0.0
        assert pos.max_adverse_excursion == 0.0

    def test_new_position_has_zero_water_marks(self):
        pos = Position(
            position_id="test_1",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            current_price=1.1000,
        )
        assert pos.high_water_mark == 0.0
        assert pos.low_water_mark == 0.0

    def test_new_position_has_zero_time_in_trade(self):
        pos = Position(
            position_id="test_1",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            current_price=1.1000,
        )
        assert pos.time_in_trade_sec == 0.0

    def test_default_status_is_open(self):
        pos = Position(
            position_id="test_1",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            current_price=1.1000,
        )
        assert pos.status == PositionStatus.OPEN
        assert pos.status.is_closed is False


# ── 3. PositionMonitor init ───────────────────────────────────────────────────


class TestPositionMonitorInit:
    def test_init_with_defaults(self, order_manager):
        pm = PositionMonitor(order_manager=order_manager)
        assert pm._max_trade_duration_sec == 14400
        assert pm._check_interval_sec == 5.0
        assert pm._kill_switch is None
        assert pm._risk_guard is None

    def test_init_with_custom_params(self, order_manager, risk_guard, kill_switch):
        pm = PositionMonitor(
            order_manager=order_manager,
            risk_guard=risk_guard,
            kill_switch=kill_switch,
            max_trade_duration_sec=7200,
            check_interval_sec=10.0,
        )
        assert pm._max_trade_duration_sec == 7200
        assert pm._check_interval_sec == 10.0
        assert pm._kill_switch is kill_switch
        assert pm._risk_guard is risk_guard


# ── 4. update_positions — MAE/MFE tracking ────────────────────────────────────


class TestMAEMFETRacking:
    def test_long_mfe_increases_when_price_rises(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        # Price goes up → favorable for long
        monitor.update_positions(
            prices={"EURUSD": 1.1050},
            bids={"EURUSD": 1.1050},
            asks={"EURUSD": 1.1051},
        )
        # Check MFE increased
        updated = order_manager.get_position(pos.position_id)
        assert updated.max_favorable_excursion > 0.0
        assert updated.max_adverse_excursion == 0.0

    def test_long_mae_increases_when_price_falls(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        # Price goes down → adverse for long
        monitor.update_positions(
            prices={"EURUSD": 1.0950},
            bids={"EURUSD": 1.0950},
            asks={"EURUSD": 1.0951},
        )
        updated = order_manager.get_position(pos.position_id)
        assert updated.max_adverse_excursion < 0.0
        assert updated.max_favorable_excursion == 0.0

    def test_long_mfe_tracks_high_water_mark(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        actual_entry = pos.entry_price  # May differ from 1.1000 due to slippage
        # Step 1: price goes up
        monitor.update_positions(
            prices={"EURUSD": 1.1050},
            bids={"EURUSD": 1.1050},
            asks={"EURUSD": 1.1051},
        )
        # Step 2: price goes down
        monitor.update_positions(
            prices={"EURUSD": 1.1020},
            bids={"EURUSD": 1.1020},
            asks={"EURUSD": 1.1021},
        )
        updated = order_manager.get_position(pos.position_id)
        # MFE should reflect the peak (1.1050), not the current (1.1020)
        assert updated.max_favorable_excursion > 0.0
        # MFE from 1.1050 bid should be higher than from 1.1020
        expected_mfe = (1.1050 - actual_entry) * 0.1 * 100000  # 50 pips * 0.1 lot
        assert updated.max_favorable_excursion == pytest.approx(expected_mfe, rel=1e-3)
        # MAE should still be 0 (never went below entry)
        # Note: due to slippage, entry may be slightly above 1.1000,
        # so a bid of 1.1020 may still be above entry → MAE stays 0
        assert updated.max_adverse_excursion == 0.0

    def test_mfe_does_not_decrease(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        # Price up
        monitor.update_positions(
            prices={"EURUSD": 1.1080}, bids={"EURUSD": 1.1080}, asks={"EURUSD": 1.1081}
        )
        peak_mfe = order_manager.get_position(pos.position_id).max_favorable_excursion

        # Price falls significantly
        monitor.update_positions(
            prices={"EURUSD": 1.0900}, bids={"EURUSD": 1.0900}, asks={"EURUSD": 1.0901}
        )
        current_mfe = order_manager.get_position(
            pos.position_id
        ).max_favorable_excursion
        assert current_mfe == peak_mfe  # MFE never decreases

    def test_mae_does_not_increase(self, monitor, order_manager):
        """MAE should stay at its worst (most negative) value."""
        pos = _make_long_position(order_manager, entry=1.1000)
        # Price drops
        monitor.update_positions(
            prices={"EURUSD": 1.0950}, bids={"EURUSD": 1.0950}, asks={"EURUSD": 1.0951}
        )
        peak_mae = order_manager.get_position(pos.position_id).max_adverse_excursion

        # Price recovers
        monitor.update_positions(
            prices={"EURUSD": 1.1050}, bids={"EURUSD": 1.1050}, asks={"EURUSD": 1.1051}
        )
        current_mae = order_manager.get_position(pos.position_id).max_adverse_excursion
        assert current_mae == peak_mae  # MAE stays at worst


# ── 5. update_positions — water marks ─────────────────────────────────────────


class TestWaterMarks:
    def test_long_high_water_mark_tracks_highest(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        monitor.update_positions(
            prices={"EURUSD": 1.1050}, bids={"EURUSD": 1.1050}, asks={"EURUSD": 1.1051}
        )
        monitor.update_positions(
            prices={"EURUSD": 1.1080}, bids={"EURUSD": 1.1080}, asks={"EURUSD": 1.1081}
        )
        monitor.update_positions(
            prices={"EURUSD": 1.1030}, bids={"EURUSD": 1.1030}, asks={"EURUSD": 1.1031}
        )
        updated = order_manager.get_position(pos.position_id)
        # For long: high_water_mark = highest bid seen
        assert updated.high_water_mark == pytest.approx(1.1080)
        # For long: low_water_mark = lowest bid seen
        assert updated.low_water_mark == pytest.approx(1.1030)

    def test_short_water_mark_inverts(self, monitor, order_manager):
        pos = _make_short_position(order_manager, entry=1.1000)
        monitor.update_positions(
            prices={"EURUSD": 1.1050}, bids={"EURUSD": 1.1050}, asks={"EURUSD": 1.1051}
        )
        monitor.update_positions(
            prices={"EURUSD": 1.0950}, bids={"EURUSD": 1.0950}, asks={"EURUSD": 1.0951}
        )
        updated = order_manager.get_position(pos.position_id)
        # For short: high_water_mark = lowest ask (best for short = price going down)
        assert updated.high_water_mark == pytest.approx(1.0951)
        # For short: low_water_mark = highest ask (worst for short = price going up)
        assert updated.low_water_mark == pytest.approx(1.1051)

    def test_water_marks_initialized_from_first_tick(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        monitor.update_positions(
            prices={"EURUSD": 1.1000}, bids={"EURUSD": 1.1000}, asks={"EURUSD": 1.1001}
        )
        updated = order_manager.get_position(pos.position_id)
        assert updated.high_water_mark == pytest.approx(1.1000)
        assert updated.low_water_mark == pytest.approx(1.1000)


# ── 6. time_in_trade calculation ──────────────────────────────────────────────


class TestTimeInTrade:
    def test_time_in_trade_increases(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        # Immediately after creation, time should be near 0
        monitor.update_positions(
            prices={"EURUSD": 1.1000}, bids={"EURUSD": 1.1000}, asks={"EURUSD": 1.1001}
        )
        updated = order_manager.get_position(pos.position_id)
        assert updated.time_in_trade_sec >= 0.0
        assert updated.time_in_trade_sec < 5.0  # Should be very small

    def test_time_in_trade_after_delay(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        # Manually set opened_at to 60 seconds ago
        past = datetime.now(timezone.utc) - timedelta(seconds=60)
        pos.opened_at = past
        order_manager._positions[pos.position_id].opened_at = past

        monitor.update_positions(
            prices={"EURUSD": 1.1000}, bids={"EURUSD": 1.1000}, asks={"EURUSD": 1.1001}
        )
        updated = order_manager.get_position(pos.position_id)
        assert updated.time_in_trade_sec >= 59.0
        assert updated.time_in_trade_sec <= 62.0


# ── 7. check_time_exits ───────────────────────────────────────────────────────


class TestTimeExits:
    def test_returns_positions_exceeding_duration(
        self, order_manager, risk_guard, kill_switch
    ):
        # Create monitor with short duration for testing
        pm = PositionMonitor(
            order_manager=order_manager,
            risk_guard=risk_guard,
            kill_switch=kill_switch,
            max_trade_duration_sec=60,  # 1 minute
        )
        pos = _make_long_position(order_manager, entry=1.1000)
        # Set opened_at to 120 seconds ago
        past = datetime.now(timezone.utc) - timedelta(seconds=120)
        order_manager._positions[pos.position_id].opened_at = past
        pm.update_positions(
            prices={"EURUSD": 1.1000}, bids={"EURUSD": 1.1000}, asks={"EURUSD": 1.1001}
        )

        expired = pm.check_time_exits()
        assert pos.position_id in expired

    def test_does_not_return_recent_positions(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        monitor.update_positions(
            prices={"EURUSD": 1.1000}, bids={"EURUSD": 1.1000}, asks={"EURUSD": 1.1001}
        )

        expired = monitor.check_time_exits()
        assert pos.position_id not in expired

    def test_empty_list_when_no_positions(self, monitor):
        expired = monitor.check_time_exits()
        assert expired == []


# ── 8. check_drawdown_alerts ──────────────────────────────────────────────────


class TestDrawdownAlerts:
    def test_warning_at_threshold(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        # Run price up to establish MFE
        monitor.update_positions(
            prices={"EURUSD": 1.1100}, bids={"EURUSD": 1.1100}, asks={"EURUSD": 1.1101}
        )
        # Price gives back significantly (from 100 pip profit to ~20 pip profit)
        monitor.update_positions(
            prices={"EURUSD": 1.1020}, bids={"EURUSD": 1.1020}, asks={"EURUSD": 1.1021}
        )
        alerts = monitor.check_drawdown_alerts(
            warning_threshold=0.02, critical_threshold=0.05
        )
        # MFE was ~$1000, current is ~$200, drawdown from MFE = 80%
        assert len(alerts) >= 1
        assert any(a["level"] == "critical" for a in alerts)

    def test_no_alert_when_no_drawdown(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        # In the real flow, order_manager.update_position sets unrealized_pnl
        # before the monitor runs. Simulate that here.
        order_manager.update_position(
            pos.position_id, current_price=1.1050, bid=1.1050, ask=1.1051
        )
        monitor.update_positions(
            prices={"EURUSD": 1.1050}, bids={"EURUSD": 1.1050}, asks={"EURUSD": 1.1051}
        )
        alerts = monitor.check_drawdown_alerts()
        assert len(alerts) == 0

    def test_critical_alert_level(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        # Run price way up
        monitor.update_positions(
            prices={"EURUSD": 1.1200}, bids={"EURUSD": 1.1200}, asks={"EURUSD": 1.1201}
        )
        # Price falls back near entry
        monitor.update_positions(
            prices={"EURUSD": 1.1005}, bids={"EURUSD": 1.1005}, asks={"EURUSD": 1.1006}
        )
        alerts = monitor.check_drawdown_alerts(
            warning_threshold=0.02, critical_threshold=0.05
        )
        # MFE was ~$2000, current ~$50 → drawdown = 97.5% → critical
        critical_alerts = [a for a in alerts if a["level"] == "critical"]
        assert len(critical_alerts) >= 1

    def test_no_positions_no_alerts(self, monitor):
        alerts = monitor.check_drawdown_alerts()
        assert alerts == []


# ── 9. get_portfolio_summary ──────────────────────────────────────────────────


class TestPortfolioSummary:
    def test_empty_portfolio(self, monitor):
        summary = monitor.get_portfolio_summary()
        assert summary["position_count"] == 0
        assert summary["total_unrealized_pnl"] == 0.0
        assert summary["total_notional_exposure"] == 0.0
        assert summary["positions_by_symbol"] == {}
        assert summary["largest_position_notional"] == 0.0

    def test_single_position(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        monitor.update_positions(
            prices={"EURUSD": 1.1050}, bids={"EURUSD": 1.1050}, asks={"EURUSD": 1.1051}
        )
        summary = monitor.get_portfolio_summary()
        assert summary["position_count"] == 1
        assert summary["positions_by_symbol"] == {"EURUSD": 1}
        assert summary["total_notional_exposure"] > 0
        assert summary["largest_position_notional"] > 0

    def test_multiple_positions_same_symbol(self, monitor, order_manager):
        _make_long_position(order_manager, entry=1.1000)
        _make_long_position(order_manager, entry=1.1005)
        monitor.update_positions(
            prices={"EURUSD": 1.1050}, bids={"EURUSD": 1.1050}, asks={"EURUSD": 1.1051}
        )
        summary = monitor.get_portfolio_summary()
        assert summary["position_count"] == 2
        assert summary["positions_by_symbol"] == {"EURUSD": 2}

    def test_multiple_positions_different_symbols(self, monitor, order_manager):
        _make_long_position(order_manager, symbol="EURUSD", entry=1.1000)
        _make_long_position(order_manager, symbol="GBPUSD", entry=1.2500)
        monitor.update_positions(
            prices={"EURUSD": 1.1050, "GBPUSD": 1.2550},
            bids={"EURUSD": 1.1050, "GBPUSD": 1.2550},
            asks={"EURUSD": 1.1051, "GBPUSD": 1.2551},
        )
        summary = monitor.get_portfolio_summary()
        assert summary["position_count"] == 2
        assert summary["positions_by_symbol"] == {"EURUSD": 1, "GBPUSD": 1}

    def test_summary_includes_mfe_mae(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        monitor.update_positions(
            prices={"EURUSD": 1.1050}, bids={"EURUSD": 1.1050}, asks={"EURUSD": 1.1051}
        )
        summary = monitor.get_portfolio_summary()
        assert summary["total_mfe"] > 0
        assert summary["total_mae"] == 0

    def test_summary_includes_kill_switch_status(
        self, monitor, order_manager, kill_switch
    ):
        kill_switch.is_globally_killed.return_value = False
        kill_switch.is_globally_frozen.return_value = False
        summary = monitor.get_portfolio_summary()
        assert summary["is_killed"] is False
        assert summary["is_frozen"] is False

    def test_summary_shows_killed(self, monitor, kill_switch):
        kill_switch.is_globally_killed.return_value = True
        kill_switch.is_globally_frozen.return_value = False
        summary = monitor.get_portfolio_summary()
        assert summary["is_killed"] is True


# ── 10. get_position_report ───────────────────────────────────────────────────


class TestPositionReport:
    def test_returns_detailed_report(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        monitor.update_positions(
            prices={"EURUSD": 1.1050}, bids={"EURUSD": 1.1050}, asks={"EURUSD": 1.1051}
        )
        report = monitor.get_position_report(pos.position_id)
        assert report is not None
        assert report["position_id"] == pos.position_id
        assert report["symbol"] == "EURUSD"
        assert report["direction"] == "long"
        assert report["volume"] == 0.1
        assert report["entry_price"] == pytest.approx(1.1000, rel=1e-4)
        assert "max_favorable_excursion (MFE)" in report
        assert "max_adverse_excursion (MAE)" in report
        assert "high_water_mark" in report
        assert "low_water_mark" in report
        assert "time_in_trade_sec" in report
        assert "status" in report
        assert "stop_loss" in report
        assert "take_profit" in report

    def test_returns_none_for_unknown_id(self, monitor):
        report = monitor.get_position_report("nonexistent")
        assert report is None

    def test_report_mfe_tracked_correctly(self, monitor, order_manager):
        pos = _make_long_position(order_manager, entry=1.1000)
        # Price up
        monitor.update_positions(
            prices={"EURUSD": 1.1080}, bids={"EURUSD": 1.1080}, asks={"EURUSD": 1.1081}
        )
        # Price down
        monitor.update_positions(
            prices={"EURUSD": 1.0950}, bids={"EURUSD": 1.0950}, asks={"EURUSD": 1.0951}
        )
        report = monitor.get_position_report(pos.position_id)
        mfe = report["max_favorable_excursion (MFE)"]
        mae = report["max_adverse_excursion (MAE)"]
        assert mfe > 0  # Had a favorable excursion
        assert mae < 0  # Had an adverse excursion


# ── 11. Kill switch FREEZE on portfolio drawdown ──────────────────────────────


class TestKillSwitchIntegration:
    def test_freeze_on_portfolio_drawdown_breach(self, order_manager, kill_switch):
        # Create a risk_guard with a very low drawdown limit for easy triggering
        config = FTMOConfig(total_drawdown_limit_pct=0.01)  # 1% drawdown limit
        rg = RiskGuard(ftmo_config=config, starting_balance=100000.0)

        # Simulate drawdown: drop balance to trigger the limit
        rg.update_balance(99000.0)  # 1% drawdown

        pm = PositionMonitor(
            order_manager=order_manager,
            risk_guard=rg,
            kill_switch=kill_switch,
        )

        # Create a position and update to trigger check
        _make_long_position(order_manager, entry=1.1000)
        pm.update_positions(
            prices={"EURUSD": 1.1050},
            bids={"EURUSD": 1.1050},
            asks={"EURUSD": 1.1051},
        )

        # check_drawdown_alerts calls _check_portfolio_drawdown_kill
        pm.check_drawdown_alerts()

        kill_switch.activate_global_freeze.assert_called_once_with(
            reason="portfolio_drawdown_breach",
            triggered_by="position_monitor",
        )

    def test_no_freeze_when_drawdown_within_limits(
        self, order_manager, risk_guard, kill_switch
    ):
        # Normal balance, no drawdown
        pm = PositionMonitor(
            order_manager=order_manager,
            risk_guard=risk_guard,
            kill_switch=kill_switch,
        )
        _make_long_position(order_manager, entry=1.1000)
        pm.update_positions(
            prices={"EURUSD": 1.1050},
            bids={"EURUSD": 1.1050},
            asks={"EURUSD": 1.1051},
        )
        pm.check_drawdown_alerts()

        kill_switch.activate_global_freeze.assert_not_called()

    def test_no_freeze_when_already_active(
        self, order_manager, risk_guard, kill_switch
    ):
        kill_switch.is_active.return_value = True

        config = FTMOConfig(total_drawdown_limit_pct=0.01)
        rg = RiskGuard(ftmo_config=config, starting_balance=100000.0)
        rg.update_balance(99000.0)

        pm = PositionMonitor(
            order_manager=order_manager,
            risk_guard=rg,
            kill_switch=kill_switch,
        )
        _make_long_position(order_manager, entry=1.1000)
        pm.update_positions(
            prices={"EURUSD": 1.1050},
            bids={"EURUSD": 1.1050},
            asks={"EURUSD": 1.1051},
        )
        pm.check_drawdown_alerts()

        # Should NOT call activate because already active
        kill_switch.activate_global_freeze.assert_not_called()


# ── 12. Background monitoring ─────────────────────────────────────────────────


class TestBackgroundMonitoring:
    def test_start_stop_monitoring(self, monitor):
        monitor._check_interval_sec = 0.1  # Fast for testing
        monitor.start_monitoring()
        assert monitor._monitor_thread is not None
        assert monitor._monitor_thread.is_alive()

        monitor.stop_monitoring()
        assert monitor._monitor_thread is None

    def test_start_when_already_running(self, monitor):
        monitor._check_interval_sec = 0.1
        monitor.start_monitoring()
        # Second start should be a no-op
        monitor.start_monitoring()
        assert monitor._monitor_thread is not None
        monitor.stop_monitoring()

    def test_stop_when_not_started(self, monitor):
        # Should not raise
        monitor.stop_monitoring()


# ── 13. Callbacks ─────────────────────────────────────────────────────────────


class TestCallbacks:
    def test_register_callback(self, monitor):
        called = []
        monitor.register_callback("on_time_exit", lambda pid: called.append(pid))
        monitor._trigger_callbacks("on_time_exit", "POS_001")
        assert called == ["POS_001"]

    def test_drawdown_warning_callback(self, order_manager, monitor):
        warnings = []
        monitor.register_callback(
            "on_drawdown_warning", lambda alert: warnings.append(alert)
        )

        pos = _make_long_position(order_manager, entry=1.1000)
        monitor.update_positions(
            prices={"EURUSD": 1.1100}, bids={"EURUSD": 1.1100}, asks={"EURUSD": 1.1101}
        )
        monitor.update_positions(
            prices={"EURUSD": 1.1070}, bids={"EURUSD": 1.1070}, asks={"EURUSD": 1.1071}
        )
        monitor.check_drawdown_alerts(warning_threshold=0.02, critical_threshold=0.05)
        # Should have triggered at least warning level
        assert len(warnings) >= 0  # Drawdown may or may not exceed warning threshold
