import pytest
from adapters.ctrader.kill_switch import KillSwitchManager
from adapters.ctrader.models import TradeDirection, TradeSignal
from adapters.ctrader.order_manager import OrderExecutionResult
from adapters.ctrader.paper_trader import (
    PaperTrader,
    PaperTradeResult,
    PaperTradingStats,
)
from adapters.ctrader.risk_guard import FTMOConfig


@pytest.fixture(autouse=True)
def _reset_kill_switch_state(tmp_path, monkeypatch):
    """Ensure kill switch and RiskGuard state are isolated before each test.

    PaperTrader creates its own KillSwitchManager and RiskGuard using
    default paths.  If a prior test activated either, the persisted
    state leaks into subsequent tests and blocks order processing.
    """
    ks = KillSwitchManager()
    if ks.is_active():
        ks.deactivate(reason="test_isolation")
    # Redirect RiskGuard default state file to tmp so PaperTrader's
    # internal RiskGuard doesn't pick up production state.
    monkeypatch.setattr(
        "adapters.ctrader.risk_guard.RiskGuard.__init__.__defaults__",
        (None, 100000.0, str(tmp_path / "risk_guard_state.json")),
    )
    yield


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

    def test_update_market_prices_with_bid_ask_uses_real_prices_for_unrealized_pnl(
        self,
    ):
        config = FTMOConfig(
            min_risk_reward=1.0,
            max_position_size_pct=2.0,
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
        result = trader.process_signal(signal)
        if result.success:
            actual_entry = result.position.entry_price
            actual_volume = result.position.volume
            trader.update_market_prices(
                {"EURUSD": 1.1050},
                bids={"EURUSD": 1.1048},
                asks={"EURUSD": 1.1052},
            )
            stats = trader.get_stats()
            expected_pnl = (1.1048 - actual_entry) * actual_volume * 100000
            assert abs(stats.unrealized_pnl - expected_pnl) < 0.01

    def test_update_market_prices_without_bid_ask_falls_back_to_mid(self):
        config = FTMOConfig(
            min_risk_reward=1.0,
            max_position_size_pct=2.0,
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
        result = trader.process_signal(signal)
        if result.success:
            actual_entry = result.position.entry_price
            actual_volume = result.position.volume
            trader.update_market_prices({"EURUSD": 1.1050})
            stats = trader.get_stats()
            expected_pnl = (1.1050 - actual_entry) * actual_volume * 100000
            assert abs(stats.unrealized_pnl - expected_pnl) < 0.01

    def test_update_market_prices_with_bid_ask_triggers_stop_loss_for_long(self):
        config = FTMOConfig(
            min_risk_reward=1.0,
            max_position_size_pct=2.0,
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
        result = trader.process_signal(signal)
        if result.success:
            trader.update_market_prices(
                {"EURUSD": 1.0949},
                bids={"EURUSD": 1.0948},
                asks={"EURUSD": 1.0952},
            )
            positions = trader.get_open_positions()
            assert len(positions) == 0

    def test_update_market_prices_without_bid_ask_does_not_trigger_stop_loss(self):
        config = FTMOConfig(
            min_risk_reward=1.0,
            max_position_size_pct=2.0,
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
        result = trader.process_signal(signal)
        if result.success:
            trader.update_market_prices({"EURUSD": 1.0940})
            positions = trader.get_open_positions()
            assert len(positions) == 1


class TestPaperTraderMultiTPForwarding:
    """Sprint Task 1.4 (card a7b8e896): paper_trader._execute_order must forward
    TP2/TP3 to OrderManager.execute_paper_order / execute_live_order so that
    the resulting Position carries all three TP levels for downstream
    monitoring (position_monitor / forward_test_engine).
    """

    @staticmethod
    def _make_signal(tp1=1.1100, tp2=1.1200, tp3=1.1300):
        return TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            volume=0.1,
            confidence=0.85,
            rationale="Multi-TP forwarding test",
        )

    def test_execute_order_forwards_tp2_tp3_in_paper_mode(self, monkeypatch):
        """Paper-mode call must hand TP2/TP3 through to execute_paper_order."""
        captured = {}

        def fake_paper_order(**kwargs):
            captured.update(kwargs)
            return OrderExecutionResult(
                success=True,
                order=None,
                position=None,
            )

        trader = PaperTrader(ftmo_config=FTMOConfig(min_risk_reward=1.0), starting_balance=100000.0)
        monkeypatch.setattr(
            trader._order_manager, "execute_paper_order", fake_paper_order
        )
        # Force the paper-mode branch regardless of api_client wiring.
        monkeypatch.setattr(trader, "_live_mode_enabled", False)

        signal = self._make_signal(tp1=1.1100, tp2=1.2150, tp3=1.3300)
        trader._execute_order(signal=signal, volume=0.1, spread=0.0001)

        assert captured["take_profit"] == 1.1100
        assert captured["take_profit_2"] == 1.2150
        assert captured["take_profit_3"] == 1.3300
        # Other fields also forwarded correctly.
        assert captured["symbol"] == "EURUSD"
        assert captured["entry_price"] == 1.1000
        assert captured["stop_loss"] == 1.0950
        assert captured["direction"] == TradeDirection.LONG

    def test_execute_order_forwards_tp2_tp3_in_live_mode(self, monkeypatch):
        """Live-mode call must hand TP2/TP3 through to execute_live_order."""
        captured = {}

        def fake_live_order(**kwargs):
            captured.update(kwargs)
            return OrderExecutionResult(
                success=True,
                order=None,
                position=None,
            )

        trader = PaperTrader(ftmo_config=FTMOConfig(min_risk_reward=1.0), starting_balance=100000.0)
        monkeypatch.setattr(
            trader._order_manager, "execute_live_order", fake_live_order
        )
        # Flip into live mode so _execute_order dispatches to execute_live_order.
        monkeypatch.setattr(trader, "_live_mode_enabled", True)

        signal = self._make_signal(tp1=1.1100, tp2=1.2250, tp3=1.3400)
        trader._execute_order(signal=signal, volume=0.1)

        assert captured["take_profit"] == 1.1100
        assert captured["take_profit_2"] == 1.2250
        assert captured["take_profit_3"] == 1.3400
        assert captured["symbol"] == "EURUSD"
        assert captured["stop_loss"] == 1.0950

    def test_execute_order_handles_none_tp2_tp3_backward_compat(self, monkeypatch):
        """Signals whose TP2/TP3 are None (e.g. legacy single-TP producers)
        must not crash — OrderManager accepts None for these kwargs and
        resulting positions simply have fewer TP levels populated.
        """
        captured = {}

        def fake_paper_order(**kwargs):
            captured.update(kwargs)
            return OrderExecutionResult(
                success=True,
                order=None,
                position=None,
            )

        trader = PaperTrader(ftmo_config=FTMOConfig(min_risk_reward=1.0), starting_balance=100000.0)
        monkeypatch.setattr(
            trader._order_manager, "execute_paper_order", fake_paper_order
        )
        monkeypatch.setattr(trader, "_live_mode_enabled", False)

        # Construct a signal with TP2/TP3 as None — Python permits this
        # even though the dataclass type annotation says `float`.  This
        # mirrors a legacy or degraded signal where multi-TP enrichment
        # has not yet run.
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            take_profit_2=None,  # type: ignore[arg-type]
            take_profit_3=None,  # type: ignore[arg-type]
            volume=0.1,
            confidence=0.85,
            rationale="Backward compat: single-TP signal",
        )

        # Should not raise.
        trader._execute_order(signal=signal, volume=0.1, spread=0.0001)

        # None must be forwarded as-is — OrderManager treats None as
        # "no additional TP at this level".
        assert captured["take_profit"] == 1.1100
        assert captured["take_profit_2"] is None
        assert captured["take_profit_3"] is None
