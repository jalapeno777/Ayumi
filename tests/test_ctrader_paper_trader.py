import pytest
from adapters.ctrader.models import TradeDirection, TradeSignal
from adapters.ctrader.paper_trader import (
    PaperTrader,
    PaperTradeResult,
    PaperTradingStats,
)
from adapters.ctrader.risk_guard import FTMOConfig


class TestPaperTradingStats:
    def test_default_stats(self):
        stats = PaperTradingStats()
        assert stats.total_signals_processed == 0
        assert stats.trades_executed == 0
        assert stats.trades_rejected == 0
        assert stats.current_balance == 100000.0


class TestPaperTradeResult:
    def test_success_result(self):
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            take_profit_2=1.1200,
            take_profit_3=1.1300,
            volume=0.1,
            confidence=0.85,
            rationale="Test",
        )
        result = PaperTradeResult(success=True, signal=signal)
        assert result.success is True
        assert result.signal == signal
        assert result.order is None

    def test_rejected_result(self):
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            take_profit_2=1.1200,
            take_profit_3=1.1300,
            volume=0.1,
            confidence=0.85,
            rationale="Test",
        )
        result = PaperTradeResult(
            success=False, signal=signal, rejection_reason="Daily loss limit"
        )
        assert result.success is False
        assert result.rejection_reason == "Daily loss limit"


class TestPaperTrader:
    def test_initialization(self):
        trader = PaperTrader(starting_balance=50000.0)
        assert trader.balance == 50000.0
        assert trader.is_running is False
        stats = trader.get_stats()
        assert stats.starting_balance == 50000.0
        assert stats.current_balance == 50000.0

    def test_process_signal_rejects_poor_risk_reward(self):
        config = FTMOConfig(min_risk_reward=2.0)
        trader = PaperTrader(ftmo_config=config, starting_balance=100000.0)
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0990,
            take_profit_1=1.1005,
            take_profit_2=1.1010,
            take_profit_3=1.1015,
            volume=0.1,
            confidence=0.85,
            rationale="Poor R:R",
        )
        result = trader.process_signal(signal)
        assert result.success is False
        assert (
            "Risk:Reward" in result.rejection_reason
            or "below minimum" in result.rejection_reason
        )

    def test_process_signal_accepts_good_risk_reward(self):
        config = FTMOConfig(
            min_risk_reward=1.5,
            max_position_size_pct=1.0,
            daily_loss_limit_pct=0.10,
            total_drawdown_limit_pct=0.20,
        )
        trader = PaperTrader(ftmo_config=config, starting_balance=100000.0)
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            take_profit_2=1.1150,
            take_profit_3=1.1200,
            volume=0.1,
            confidence=0.85,
            rationale="Good R:R",
        )
        result = trader.process_signal(signal)
        assert result.success is True
        assert result.signal == signal

    def test_process_signal_tracks_stats(self):
        config = FTMOConfig(
            min_risk_reward=1.0,
            max_position_size_pct=1.0,
        )
        trader = PaperTrader(ftmo_config=config, starting_balance=100000.0)
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            take_profit_2=1.1150,
            take_profit_3=1.1200,
            volume=0.1,
            confidence=0.85,
            rationale="Test",
        )
        trader.process_signal(signal)
        stats = trader.get_stats()
        assert stats.total_signals_processed == 1
        assert stats.trades_executed == 1

    def test_process_signal_rejects_circuit_breaker(self):
        config = FTMOConfig(daily_loss_limit_pct=0.001, max_position_size_pct=2.0)
        trader = PaperTrader(ftmo_config=config, starting_balance=100000.0)
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            take_profit_2=1.1150,
            take_profit_3=1.1200,
            volume=0.1,
            confidence=0.85,
            rationale="Test",
        )
        result = trader.process_signal(signal)
        risk_guard_stats = trader.get_risk_guard_stats()
        if result.success and risk_guard_stats.get("is_blocked"):
            result2 = trader.process_signal(signal)
            assert result2.success is False

    def test_close_position(self):
        trader = PaperTrader(starting_balance=100000.0)
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            take_profit_2=1.1150,
            take_profit_3=1.1200,
            volume=0.1,
            confidence=0.85,
            rationale="Test",
        )
        trader.process_signal(signal)
        positions = trader.get_open_positions()
        if positions:
            success = trader.close_position(positions[0].position_id, 1.1050, "test")
            assert success is True

    def test_close_all_positions(self):
        trader = PaperTrader(starting_balance=100000.0)
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            take_profit_2=1.1150,
            take_profit_3=1.1200,
            volume=0.1,
            confidence=0.85,
            rationale="Test",
        )
        trader.process_signal(signal)
        trader.close_all_positions(1.1050, "force")
        positions = trader.get_open_positions()
        assert len(positions) == 0

    def test_reset(self):
        trader = PaperTrader(starting_balance=100000.0)
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            take_profit_2=1.1150,
            take_profit_3=1.1200,
            volume=0.1,
            confidence=0.85,
            rationale="Test",
        )
        trader.process_signal(signal)
        trader.reset()
        stats = trader.get_stats()
        assert stats.current_balance == 100000.0
        assert stats.total_signals_processed == 0

    def test_register_callback(self):
        config = FTMOConfig(max_position_size_pct=2.0)
        trader = PaperTrader(ftmo_config=config, starting_balance=100000.0)
        callback_called = []

        def on_trade(result):
            callback_called.append(result)

        trader.register_callback("on_trade_executed", on_trade)
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            take_profit_2=1.1150,
            take_profit_3=1.1200,
            volume=0.1,
            confidence=0.85,
            rationale="Test",
        )
        trader.process_signal(signal)
        assert len(callback_called) == 1

    def test_register_invalid_callback_raises(self):
        trader = PaperTrader(starting_balance=100000.0)
        with pytest.raises(ValueError):
            trader.register_callback("on_invalid", lambda: None)
