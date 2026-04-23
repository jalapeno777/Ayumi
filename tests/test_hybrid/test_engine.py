
from hybrid.engine import HybridEngine, OrderResult, OrderStatus
from hybrid.risk_manager import RiskAction, RiskManager
from hybrid.signal import HumanSignal, SignalType


def _buy_signal(
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
    )


class TestHybridEngineInit:
    def test_default_init(self):
        engine = HybridEngine()
        assert engine.risk_manager is not None
        assert engine.risk_manager.current_balance == 100_000.0

    def test_custom_risk_manager(self):
        rm = RiskManager(starting_balance=50_000.0)
        engine = HybridEngine(risk_manager=rm)
        assert engine.risk_manager is rm
        assert engine.risk_manager.current_balance == 50_000.0


class TestSubmitSignal:
    def test_valid_buy_signal_succeeds(self):
        engine = HybridEngine()
        result = engine.submit_signal(_buy_signal())
        assert result.success is True
        assert result.order_id.startswith("hybrid-")
        assert result.position_id.startswith("pos-")
        assert result.lot_size > 0
        assert result.error == ""

    def test_rejected_signal_returns_failure(self):
        rm = RiskManager(min_risk_reward=5.0)
        engine = HybridEngine(risk_manager=rm)
        result = engine.submit_signal(_buy_signal())
        assert result.success is False
        assert result.error != ""

    def test_close_signal_allowed(self):
        engine = HybridEngine()
        signal = HumanSignal(signal_type=SignalType.CLOSE, pair="EUR/USD")
        result = engine.submit_signal(signal)
        assert result.success is True

    def test_order_ids_are_unique(self):
        engine = HybridEngine()
        r1 = engine.submit_signal(_buy_signal())
        r2 = engine.submit_signal(_buy_signal())
        assert r1.order_id != r2.order_id
        assert r1.position_id != r2.position_id

    def test_result_contains_signal(self):
        engine = HybridEngine()
        signal = _buy_signal()
        result = engine.submit_signal(signal)
        assert result.signal is signal

    def test_result_contains_risk_decision(self):
        engine = HybridEngine()
        result = engine.submit_signal(_buy_signal())
        assert result.risk_decision is not None
        assert result.risk_decision.action == RiskAction.ALLOW


class TestGetOpenPositions:
    def test_no_positions_initially(self):
        engine = HybridEngine()
        assert engine.get_open_positions() == []

    def test_open_position_after_signal(self):
        engine = HybridEngine()
        engine.submit_signal(_buy_signal())
        positions = engine.get_open_positions()
        assert len(positions) == 1
        assert positions[0]["pair"] == "EUR/USD"
        assert positions[0]["direction"] == "long"
        assert positions[0]["is_open"] is True

    def test_multiple_positions(self):
        engine = HybridEngine()
        engine.submit_signal(_buy_signal())
        engine.submit_signal(
            HumanSignal(
                signal_type=SignalType.SELL,
                pair="GBP/USD",
                entry_price=1.2600,
                stop_loss=1.2650,
                take_profit=1.2450,
            )
        )
        positions = engine.get_open_positions()
        assert len(positions) == 2


class TestClosePosition:
    def test_close_existing_position(self):
        engine = HybridEngine()
        result = engine.submit_signal(_buy_signal())
        close_result = engine.close_position(result.position_id)
        assert close_result.success is True
        assert close_result.position_id == result.position_id

    def test_close_nonexistent_position(self):
        engine = HybridEngine()
        result = engine.close_position("pos-999999")
        assert result.success is False
        assert "not found" in result.error

    def test_close_already_closed_position(self):
        engine = HybridEngine()
        result = engine.submit_signal(_buy_signal())
        engine.close_position(result.position_id)
        result2 = engine.close_position(result.position_id)
        assert result2.success is False
        assert "already closed" in result2.error

    def test_closed_position_not_in_open_positions(self):
        engine = HybridEngine()
        result = engine.submit_signal(_buy_signal())
        engine.close_position(result.position_id)
        assert engine.get_open_positions() == []


class TestOrderResult:
    def test_success_result(self):
        r = OrderResult(success=True, order_id="test-1", position_id="pos-1")
        assert r.success is True
        assert r.order_id == "test-1"
        assert r.error == ""

    def test_failure_result(self):
        r = OrderResult(success=False, error="risk rejected")
        assert r.success is False
        assert r.error == "risk rejected"


class TestOrderStatus:
    def test_all_statuses(self):
        assert OrderStatus.PENDING == "pending"
        assert OrderStatus.FILLED == "filled"
        assert OrderStatus.REJECTED == "rejected"
        assert OrderStatus.CANCELLED == "cancelled"
