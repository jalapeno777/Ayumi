from datetime import datetime, timezone


from hybrid.engine import (
    HybridEngine,
    HybridEngineConfig,
)
from hybrid.risk_manager import RiskManager
from hybrid.signal import HumanSignal, SignalType


def _london_buy_signal(
    entry: float = 1.1000,
    sl: float = 1.0950,
    tp: float = 1.1150,
) -> HumanSignal:
    return HumanSignal(
        signal_type=SignalType.BUY,
        pair="EUR/USD",
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        confidence=0.8,
        timestamp=datetime(2026, 4, 23, 8, 0, tzinfo=timezone.utc),
    )


def _sell_signal(
    pair: str = "GBP/USD",
    entry: float = 1.2600,
    sl: float = 1.2650,
    tp: float = 1.2450,
    hour_utc: int = 13,
) -> HumanSignal:
    return HumanSignal(
        signal_type=SignalType.SELL,
        pair=pair,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        confidence=0.7,
        timestamp=datetime(2026, 4, 23, hour_utc, 0, tzinfo=timezone.utc),
    )


class TestSessionFilteringIntegration:
    def test_signal_during_london_session_accepted(self):
        engine = HybridEngine()
        result = engine.submit_signal(_london_buy_signal())
        assert result.success is True

    def test_signal_during_ny_session_accepted(self):
        engine = HybridEngine()
        result = engine.submit_signal(_sell_signal(hour_utc=13))
        assert result.success is True

    def test_signal_outside_all_sessions_rejected(self):
        engine = HybridEngine()
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1150,
            timestamp=datetime(2026, 4, 23, 6, 30, tzinfo=timezone.utc),
        )
        result = engine.submit_signal(signal)
        assert result.success is False
        assert "no active trading session" in result.error

    def test_session_filter_disabled_allows_any_time(self):
        config = HybridEngineConfig(session_filter_enabled=False)
        engine = HybridEngine(config=config)
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1150,
            timestamp=datetime(2026, 4, 23, 22, 0, tzinfo=timezone.utc),
        )
        result = engine.submit_signal(signal)
        assert result.success is True

    def test_custom_allowed_sessions_restricts_entry(self):
        config = HybridEngineConfig(allowed_sessions=["ny_open"])
        engine = HybridEngine(config=config)
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1150,
            timestamp=datetime(2026, 4, 23, 8, 0, tzinfo=timezone.utc),
        )
        result = engine.submit_signal(signal)
        assert result.success is False
        assert "not in allowed set" in result.error

    def test_close_signal_bypasses_session_filter(self):
        engine = HybridEngine()
        signal = HumanSignal(
            signal_type=SignalType.CLOSE,
            pair="EUR/USD",
            timestamp=datetime(2026, 4, 23, 22, 0, tzinfo=timezone.utc),
        )
        result = engine.submit_signal(signal)
        assert result.success is True


class TestFTMOComplianceIntegration:
    def test_signal_accepted_within_risk_limits(self):
        engine = HybridEngine()
        result = engine.submit_signal(_london_buy_signal())
        assert result.success is True
        assert result.lot_size > 0

    def test_signal_rejected_when_daily_drawdown_exceeded(self):
        rm = RiskManager(
            starting_balance=100_000.0,
            max_daily_loss_pct=5.0,
        )
        rm.record_trade(pnl=-6_000.0)
        engine = HybridEngine(risk_manager=rm)
        result = engine.submit_signal(_london_buy_signal())
        assert result.success is False
        assert "Daily drawdown" in result.error

    def test_signal_rejected_when_total_drawdown_exceeded(self):
        rm = RiskManager(
            starting_balance=100_000.0,
            max_total_drawdown_pct=10.0,
        )
        rm.record_trade(pnl=10_000.0)
        rm.reset_daily_tracking()
        rm.record_trade(pnl=-11_000.0)
        engine = HybridEngine(risk_manager=rm)
        result = engine.submit_signal(_london_buy_signal())
        assert result.success is False
        assert "Total drawdown" in result.error

    def test_daily_risk_budget_enforced(self):
        rm = RiskManager(
            risk_per_trade_pct=0.5,
            max_daily_risk_pct=1.0,
        )
        engine = HybridEngine(risk_manager=rm)
        engine.submit_signal(_london_buy_signal())
        engine.submit_signal(_london_buy_signal())
        result = engine.submit_signal(_london_buy_signal())
        assert result.success is False
        assert "risk budget" in result.error.lower()


class TestPositionSizingIntegration:
    def test_position_size_correct_for_given_stop_distance(self):
        engine = HybridEngine()
        signal = _london_buy_signal(entry=1.1000, sl=1.0950, tp=1.1150)
        result = engine.submit_signal(signal)
        assert result.success is True
        stop_distance = 0.005
        risk_amount = 100_000.0 * 0.005
        expected_lots = risk_amount / (stop_distance * 100_000)
        assert abs(result.lot_size - round(expected_lots, 2)) < 0.01

    def test_larger_stop_distance_gives_smaller_position(self):
        engine = HybridEngine()
        tight = _london_buy_signal(entry=1.1000, sl=1.0990, tp=1.1150)
        wide = _london_buy_signal(entry=1.1000, sl=1.0950, tp=1.1150)
        result_tight = engine.submit_signal(tight)
        engine.close_position(result_tight.position_id)
        engine.risk_manager.reset_daily_tracking()
        result_wide = engine.submit_signal(wide)
        assert result_tight.lot_size > result_wide.lot_size

    def test_smaller_balance_gives_smaller_position(self):
        engine_big = HybridEngine(starting_balance=100_000.0)
        engine_small = HybridEngine(starting_balance=50_000.0)
        r1 = engine_big.submit_signal(_london_buy_signal())
        r2 = engine_small.submit_signal(_london_buy_signal())
        assert r1.lot_size > r2.lot_size


class TestEndToEndFlow:
    def test_full_trade_lifecycle(self):
        engine = HybridEngine()
        result = engine.submit_signal(_london_buy_signal())
        assert result.success is True
        assert len(engine.get_open_positions()) == 1

        close_result = engine.close_position(result.position_id)
        assert close_result.success is True
        assert engine.get_open_positions() == []
        assert engine.risk_manager.open_position_count == 0

    def test_multiple_trades_with_position_limit(self):
        rm = RiskManager(max_positions=2)
        engine = HybridEngine(risk_manager=rm)
        r1 = engine.submit_signal(_london_buy_signal())
        assert r1.success is True
        r2 = engine.submit_signal(_sell_signal(pair="GBP/USD"))
        assert r2.success is True
        r3 = engine.submit_signal(
            HumanSignal(
                signal_type=SignalType.BUY,
                pair="USD/JPY",
                entry_price=150.0,
                stop_loss=149.5,
                take_profit=152.0,
                timestamp=datetime(2026, 4, 23, 13, 0, tzinfo=timezone.utc),
            )
        )
        assert r3.success is False
        assert "Max positions" in r3.error

    def test_close_frees_position_for_new_trade(self):
        rm = RiskManager(max_positions=1)
        engine = HybridEngine(risk_manager=rm)
        r1 = engine.submit_signal(_london_buy_signal())
        assert r1.success is True

        engine.close_position(r1.position_id)

        r2 = engine.submit_signal(_sell_signal(pair="GBP/USD"))
        assert r2.success is True


class TestRiskDecisionCapping:
    def test_risk_capped_when_approaching_daily_limit(self):
        rm = RiskManager(
            risk_per_trade_pct=0.5,
            max_daily_risk_pct=0.7,
        )
        rm.record_trade(pnl=0.0, risk_pct=0.5)
        engine = HybridEngine(risk_manager=rm)
        result = engine.submit_signal(_london_buy_signal())
        assert result.success is True
        decision = result.risk_decision
        assert decision is not None
        assert abs(decision.suggested_lot_size - 0.2) < 1e-9
