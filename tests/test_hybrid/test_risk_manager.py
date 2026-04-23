from hybrid.risk_manager import RiskAction, RiskDecision, RiskManager
from hybrid.signal import HumanSignal, SignalType


def _buy_signal(
    entry: float = 1.1000,
    sl: float = 1.0950,
    tp: float = 1.1150,
    confidence: float = 0.8,
) -> HumanSignal:
    return HumanSignal(
        signal_type=SignalType.BUY,
        pair="EUR/USD",
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        confidence=confidence,
    )


class TestRiskManagerInit:
    def test_default_params(self):
        rm = RiskManager()
        assert rm.current_balance == 100_000.0
        assert rm.daily_trade_count == 0

    def test_custom_balance(self):
        rm = RiskManager(starting_balance=50_000.0)
        assert rm.current_balance == 50_000.0


class TestValidateSignal:
    def test_close_signal_always_allowed(self):
        rm = RiskManager()
        signal = HumanSignal(signal_type=SignalType.CLOSE, pair="EUR/USD")
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.ALLOW
        assert "Close" in decision.reason

    def test_valid_buy_signal_allowed(self):
        rm = RiskManager()
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.ALLOW
        assert decision.risk_reward is not None
        assert decision.risk_reward >= 1.5

    def test_signal_without_stop_loss_rejected(self):
        rm = RiskManager()
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1,
        )
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.REJECT
        assert "stop loss" in decision.reason.lower()

    def test_poor_risk_reward_rejected(self):
        rm = RiskManager()
        signal = _buy_signal(sl=1.0990, tp=1.1010)
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.REJECT
        assert "Risk:Reward" in decision.reason

    def test_daily_trade_limit_rejection(self):
        rm = RiskManager(max_trades_per_day=1)
        rm.record_trade(pnl=0.0)
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.REJECT
        assert "Daily trade limit" in decision.reason

    def test_sell_signal_allowed(self):
        rm = RiskManager()
        signal = HumanSignal(
            signal_type=SignalType.SELL,
            pair="GBP/USD",
            entry_price=1.2600,
            stop_loss=1.2650,
            take_profit=1.2450,
            confidence=0.7,
        )
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.ALLOW


class TestCalculatePositionSize:
    def test_basic_position_size(self):
        rm = RiskManager(starting_balance=100_000.0, risk_per_trade_pct=0.5)
        signal = _buy_signal(entry=1.1000, sl=1.0950)
        size = rm.calculate_position_size(signal)
        assert size > 0

    def test_close_signal_returns_zero(self):
        rm = RiskManager()
        signal = HumanSignal(signal_type=SignalType.CLOSE, pair="EUR/USD")
        assert rm.calculate_position_size(signal) == 0.0

    def test_no_stop_loss_returns_zero(self):
        rm = RiskManager()
        signal = HumanSignal(
            signal_type=SignalType.BUY, pair="EUR/USD", entry_price=1.1
        )
        assert rm.calculate_position_size(signal) == 0.0

    def test_custom_account_balance(self):
        rm = RiskManager(starting_balance=100_000.0)
        signal = _buy_signal()
        default_size = rm.calculate_position_size(signal)
        custom_size = rm.calculate_position_size(signal, account_balance=50_000.0)
        assert custom_size < default_size


class TestRecordTrade:
    def test_record_win_increments_balance(self):
        rm = RiskManager(starting_balance=100_000.0)
        rm.record_trade(pnl=500.0)
        assert rm.current_balance == 100_500.0
        assert rm.daily_trade_count == 1

    def test_record_loss_decrements_balance(self):
        rm = RiskManager(starting_balance=100_000.0)
        rm.record_trade(pnl=-300.0)
        assert rm.current_balance == 99_700.0
        assert rm.daily_trade_count == 1

    def test_multiple_trades_accumulate(self):
        rm = RiskManager()
        rm.record_trade(100.0)
        rm.record_trade(-50.0)
        rm.record_trade(200.0)
        assert rm.current_balance == 100_250.0
        assert rm.daily_trade_count == 3


class TestResetDailyTracking:
    def test_reset_clears_trade_count(self):
        rm = RiskManager()
        rm.record_trade(100.0)
        rm.record_trade(200.0)
        assert rm.daily_trade_count == 2
        rm.reset_daily_tracking()
        assert rm.daily_trade_count == 0


class TestRiskDecision:
    def test_decision_fields(self):
        d = RiskDecision(
            action=RiskAction.ALLOW,
            reason="OK",
            risk_reward=2.0,
            suggested_lot_size=0.1,
        )
        assert d.action == RiskAction.ALLOW
        assert d.reason == "OK"
        assert d.risk_reward == 2.0
        assert d.suggested_lot_size == 0.1
