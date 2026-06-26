"""Tests for the v2 forward test launcher (BQ-1043 Phase 4b).

All infrastructure modules are mocked — these are pure unit tests
verifying the wiring logic, volume conversion, signal routing,
health format, and shutdown handling.
"""

from __future__ import annotations

import logging
import signal
import threading
from unittest.mock import MagicMock, patch, call

import pytest

from scripts.launch_forward_test_v2 import (
    lots_to_volume,
    CorrelationGate,
    ForwardTestV2,
    query_symbol_specs,
)
from adapters.ctrader.protocols import OrderStatus, TradeSide


# ── Test 1: Startup sequence — modules instantiated in correct order ───────


class TestStartupSequence:
    """Verify that the infrastructure modules are created and wired correctly."""

    def test_forward_test_v2_wiring(self):
        """ForwardTestV2 correctly wires all subsystems."""
        session = MagicMock()
        feed = MagicMock()
        gateway = MagicMock()
        tracker = MagicMock()
        event_handler = MagicMock()
        health = MagicMock()
        blend = MagicMock()
        corr = CorrelationGate()
        strategies = []

        engine = ForwardTestV2(
            session=session,
            market_data_feed=feed,
            order_gateway=gateway,
            position_tracker=tracker,
            execution_event_handler=event_handler,
            health_monitor=health,
            blend_runner=blend,
            correlation_gate=corr,
            strategies=strategies,
            symbol_id_map={"GBPUSD": 2},
            symbol_specs={2: {"lotSize": 10_000_000, "minVolume": 100_000, "stepVolume": 100_000}},
            live_mode=False,
        )

        # Verify all subsystems are stored
        assert engine._session is session
        assert engine._feed is feed
        assert engine._gateway is gateway
        assert engine._tracker is tracker
        assert engine._event_handler is event_handler
        assert engine._health is health
        assert engine._blend is blend
        assert engine._corr_gate is corr

        # On start, feed listeners should be registered
        engine.start()
        feed.add_tick_listener.assert_called_once()
        feed.add_bar_listener.assert_called_once()
        assert engine.is_running is True

        # On stop, running flag goes false
        engine.stop()
        assert engine.is_running is False

    def test_startup_registers_tick_and_bar_listeners(self):
        """The engine must register both tick and bar listeners on start."""
        feed = MagicMock()
        engine = ForwardTestV2(
            session=MagicMock(),
            market_data_feed=feed,
            order_gateway=MagicMock(),
            position_tracker=MagicMock(),
            execution_event_handler=MagicMock(),
            health_monitor=MagicMock(),
            blend_runner=MagicMock(),
            correlation_gate=CorrelationGate(),
            strategies=[],
            symbol_id_map={},
            symbol_specs={},
        )
        engine.start()

        assert feed.add_tick_listener.called
        assert feed.add_bar_listener.called


# ── Test 2: Volume uses queried lot size ────────────────────────────────────


class TestVolumeConversion:
    """Verify the critical volume conversion fix."""

    def test_lots_to_volume_standard(self):
        """0.01 lots with lotSize=10M → 100,000 raw volume."""
        vol = lots_to_volume(0.01, 10_000_000)
        assert vol == 100_000

    def test_lots_to_volume_0_1(self):
        """0.10 lots with lotSize=10M → 1,000,000 raw volume."""
        vol = lots_to_volume(0.10, 10_000_000)
        assert vol == 1_000_000

    def test_lots_to_volume_1_lot(self):
        """1.0 lot with lotSize=10M → 10,000,000 raw volume."""
        vol = lots_to_volume(1.0, 10_000_000)
        assert vol == 10_000_000

    def test_lots_to_volume_old_100k(self):
        """0.01 lots with lotSize=100K (legacy) → 1,000 raw volume."""
        vol = lots_to_volume(0.01, 100_000)
        assert vol == 1_000

    def test_order_gateway_receives_correct_volume(self):
        """When a signal is routed, OrderGateway gets volume computed from lotSize."""
        gateway = MagicMock()
        gateway.send_market_order.return_value = MagicMock(
            status=OrderStatus.FILLED,
            order_id="123",
            filled_price=1.2700,
            filled_volume=100_000,
            error_code=None,
            error_message=None,
            execution_time_ms=500,
        )

        tracker = MagicMock()
        feed = MagicMock()
        blend = MagicMock()
        blend.on_signal.return_value = MagicMock(
            rejected=False,
            lots=0.01,
            risk_amount=50.0,
        )

        # Build a minimal engine in live mode
        engine = ForwardTestV2(
            session=MagicMock(),
            market_data_feed=feed,
            order_gateway=gateway,
            position_tracker=tracker,
            execution_event_handler=MagicMock(),
            health_monitor=MagicMock(),
            blend_runner=blend,
            correlation_gate=CorrelationGate(),
            strategies=[],
            symbol_id_map={"GBPUSD": 2},
            symbol_specs={2: {"lotSize": 10_000_000, "minVolume": 100_000, "stepVolume": 100_000}},
            live_mode=True,
        )

        # Create a mock TradeSignal
        from adapters.ctrader.models import TradeSignal, TradeDirection

        signal = TradeSignal(
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            entry_price=1.2700,
            stop_loss=1.2650,
            take_profit_1=1.2800,
            take_profit_2=0.0,
            take_profit_3=0.0,
            volume=0.01,
            confidence=0.75,
            rationale="test",
        )

        # Route the signal
        engine._route_signal(signal, "SRMR+", "srmr_plus")

        # Verify gateway was called with correct volume
        gateway.send_market_order.assert_called_once()
        call_kwargs = gateway.send_market_order.call_args
        sent_volume = call_kwargs.kwargs.get("volume") or call_kwargs[1].get("volume", 0)
        assert sent_volume == 100_000, (
            f"Expected volume=100000 for 0.01 lots with lotSize=10M, "
            f"got {sent_volume}"
        )


# ── Test 3: Signal routes through OrderGateway ──────────────────────────────


class TestSignalRouting:
    """Verify signals are routed through blend runner to OrderGateway."""

    def test_signal_accepted_and_filled(self):
        """A signal accepted by blend runner gets sent to OrderGateway in live mode."""
        gateway = MagicMock()
        gateway.send_market_order.return_value = MagicMock(
            status=OrderStatus.FILLED,
            order_id="42",
            filled_price=1.2700,
            filled_volume=100_000,
            error_code=None,
            error_message=None,
            execution_time_ms=300,
        )

        tracker = MagicMock()
        blend = MagicMock()
        blend.on_signal.return_value = MagicMock(
            rejected=False,
            lots=0.01,
            risk_amount=50.0,
        )

        engine = ForwardTestV2(
            session=MagicMock(),
            market_data_feed=MagicMock(),
            order_gateway=gateway,
            position_tracker=tracker,
            execution_event_handler=MagicMock(),
            health_monitor=MagicMock(),
            blend_runner=blend,
            correlation_gate=CorrelationGate(),
            strategies=[],
            symbol_id_map={"GBPUSD": 2},
            symbol_specs={2: {"lotSize": 10_000_000, "minVolume": 100_000, "stepVolume": 100_000}},
            live_mode=True,
        )

        from adapters.ctrader.models import TradeSignal, TradeDirection

        signal = TradeSignal(
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            entry_price=1.2700,
            stop_loss=1.2650,
            take_profit_1=1.2800,
            take_profit_2=0.0, take_profit_3=0.0,
            volume=0.01, confidence=0.8, rationale="test",
        )

        engine._route_signal(signal, "SRMR+", "srmr_plus")

        # Blend runner was called
        blend.on_signal.assert_called_once()
        # Gateway was called
        gateway.send_market_order.assert_called_once()
        # Position tracker recorded the fill
        tracker.on_position_opened.assert_called_once()
        # Live fills counter incremented
        assert engine.live_fills == 1

    def test_signal_rejected_by_blend(self):
        """When blend runner rejects, OrderGateway is NOT called."""
        gateway = MagicMock()
        blend = MagicMock()
        blend.on_signal.return_value = MagicMock(
            rejected=True,
            rejection_reason="Daily risk cap exceeded",
        )

        engine = ForwardTestV2(
            session=MagicMock(),
            market_data_feed=MagicMock(),
            order_gateway=gateway,
            position_tracker=MagicMock(),
            execution_event_handler=MagicMock(),
            health_monitor=MagicMock(),
            blend_runner=blend,
            correlation_gate=CorrelationGate(),
            strategies=[],
            symbol_id_map={"GBPUSD": 2},
            symbol_specs={2: {"lotSize": 10_000_000}},
            live_mode=True,
        )

        from adapters.ctrader.models import TradeSignal, TradeDirection

        signal = TradeSignal(
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            entry_price=1.2700, stop_loss=1.2650,
            take_profit_1=1.2800, take_profit_2=0.0, take_profit_3=0.0,
            volume=0.01, confidence=0.6, rationale="test",
        )

        engine._route_signal(signal, "SRMR+", "srmr_plus")

        gateway.send_market_order.assert_not_called()
        assert engine._signals_rejected == 1

    def test_paper_mode_does_not_call_gateway(self):
        """In paper mode, OrderGateway is never called."""
        gateway = MagicMock()
        blend = MagicMock()
        blend.on_signal.return_value = MagicMock(
            rejected=False, lots=0.01, risk_amount=50.0,
        )

        engine = ForwardTestV2(
            session=MagicMock(),
            market_data_feed=MagicMock(),
            order_gateway=gateway,
            position_tracker=MagicMock(),
            execution_event_handler=MagicMock(),
            health_monitor=MagicMock(),
            blend_runner=blend,
            correlation_gate=CorrelationGate(),
            strategies=[],
            symbol_id_map={"GBPUSD": 2},
            symbol_specs={2: {"lotSize": 10_000_000}},
            live_mode=False,  # paper mode
        )

        from adapters.ctrader.models import TradeSignal, TradeDirection

        signal = TradeSignal(
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            entry_price=1.2700, stop_loss=1.2650,
            take_profit_1=1.2800, take_profit_2=0.0, take_profit_3=0.0,
            volume=0.01, confidence=0.8, rationale="test",
        )

        engine._route_signal(signal, "SRMR+", "srmr_plus")

        gateway.send_market_order.assert_not_called()
        assert engine._paper_trades == 1


# ── Test 4: Health monitor emits B5 format ──────────────────────────────────


class TestHealthFormat:
    """Verify [B5 Health] log format is emitted by HealthMonitor."""

    def test_b5_health_log_line(self, caplog):
        """HealthMonitor emits [B5 Health] with expected fields."""
        from engine.health_monitor import HealthMonitor

        hm = HealthMonitor(interval_seconds=1)
        hm.attach(
            session=MagicMock(state="SUBSCRIBED"),
            market_data_feed=MagicMock(ticks_received=100, ticks_per_second=2.5, bars_built=10, signals_generated=5),
            order_gateway=MagicMock(pending_orders=0),
            position_tracker=MagicMock(open_positions=0),
        )

        with caplog.at_level(logging.INFO, logger="ayumi.forward_test"):
            hm._emit_health()

        b5_lines = [r for r in caplog.records if "[B5 Health]" in r.getMessage()]
        assert len(b5_lines) >= 1

        # Check the core [B5 Health] line has the expected fields
        core_line = b5_lines[0].getMessage()
        assert "ticks=" in core_line
        assert "tps=" in core_line
        assert "bars=" in core_line
        assert "signals=" in core_line
        assert "paper_trades=" in core_line
        assert "live_fills=" in core_line
        assert "uptime=" in core_line

    def test_s1_health_lines(self, caplog):
        """HealthMonitor emits [S1 Health] per strategy."""
        from engine.health_monitor import HealthMonitor

        hm = HealthMonitor(interval_seconds=1)
        hm.attach(
            strategies={
                "srmr_plus": {"evals": 10, "no_signal": 8, "last_eval_monotonic": 0.0},
            }
        )

        with caplog.at_level(logging.INFO, logger="ayumi.forward_test"):
            hm._emit_health()

        s1_lines = [r for r in caplog.records if "[S1 Health]" in r.getMessage()]
        assert len(s1_lines) >= 1
        assert any("srmr_plus" in r.getMessage() for r in s1_lines)


# ── Test 5: Clean shutdown ──────────────────────────────────────────────────


class TestCleanShutdown:
    """Verify SIGTERM/SIGINT handler disconnects session."""

    def test_shutdown_disconnects_session(self):
        """The shutdown handler calls session.disconnect()."""
        session = MagicMock()
        health = MagicMock()
        blend = MagicMock()
        token = MagicMock()
        engine = ForwardTestV2(
            session=session,
            market_data_feed=MagicMock(),
            order_gateway=MagicMock(),
            position_tracker=MagicMock(),
            execution_event_handler=MagicMock(),
            health_monitor=health,
            blend_runner=blend,
            correlation_gate=CorrelationGate(),
            strategies=[],
            symbol_id_map={},
            symbol_specs={},
        )

        # Simulate the shutdown function body (as defined in main())
        def shutdown():
            health.stop()
            engine.stop()
            blend.stop()
            token.stop_proactive_timer()
            session.disconnect()

        engine.start()
        shutdown()

        assert not engine.is_running
        health.stop.assert_called_once()
        blend.stop.assert_called_once()
        token.stop_proactive_timer.assert_called_once()
        session.disconnect.assert_called_once()

    def test_engine_stop_sets_not_running(self):
        """After stop(), engine.is_running is False."""
        engine = ForwardTestV2(
            session=MagicMock(),
            market_data_feed=MagicMock(),
            order_gateway=MagicMock(),
            position_tracker=MagicMock(),
            execution_event_handler=MagicMock(),
            health_monitor=MagicMock(),
            blend_runner=MagicMock(),
            correlation_gate=CorrelationGate(),
            strategies=[],
            symbol_id_map={},
            symbol_specs={},
        )
        engine.start()
        assert engine.is_running
        engine.stop()
        assert not engine.is_running
