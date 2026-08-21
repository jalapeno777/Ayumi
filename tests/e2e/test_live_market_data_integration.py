import pytest
from adapters.ctrader.models import (
    CTraderTradeSignal,
    TradeDirection,
)
from adapters.ctrader.order_manager import (
    OrderManager,
    PositionSizeConfig,
    SlippageModel,
)
from adapters.ctrader.paper_trader import PaperTrader
from adapters.ctrader.risk_guard import FTMOConfig


# BQ-822-C API drift: Phase 5 P5A (commit 183a996) wired the kill switch into
# PaperTrader.process_signal. The kill-switch state file
# (data/kill_switches/global.state) is shared with the live forward-test
# pipeline and may be in KILL mode from previous sessions — which blocks these
# paper-trader unit tests that pre-date the enforcement. Stub the kill-switch
# check at the class level so these tests reflect the pre-P5A API contract.
@pytest.fixture(autouse=True)
def _disable_global_kill_switch(monkeypatch):
    from adapters.ctrader.kill_switch import KillSwitchManager

    monkeypatch.setattr(KillSwitchManager, "is_globally_killed", lambda self: False)
    yield


def _make_signal(
    symbol="GBPUSD",
    direction=TradeDirection.LONG,
    entry=1.26000,
    sl=1.25700,
    tp=1.26600,
    confidence=0.75,
):
    return CTraderTradeSignal(
        symbol=symbol,
        direction=direction,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp,
        take_profit_2=tp + 0.001,
        take_profit_3=tp + 0.001,
        volume=0.1,
        confidence=confidence,
        rationale="test",
    )


class TestSlippageModel:
    def test_long_order_adds_slippage(self):
        model = SlippageModel(base_pips=0.1, random_pips=0.0, pip_value=0.0001)
        fill = model.apply(1.26000, TradeDirection.LONG)
        assert fill > 1.26000
        assert fill == pytest.approx(1.26001, abs=1e-8)

    def test_short_order_subtracts_slippage(self):
        model = SlippageModel(base_pips=0.1, random_pips=0.0, pip_value=0.0001)
        fill = model.apply(1.26000, TradeDirection.SHORT)
        assert fill < 1.26000
        assert fill == pytest.approx(1.25999, abs=1e-8)

    def test_spread_long_pays_half(self):
        model = SlippageModel(base_pips=0.0, random_pips=0.0, pip_value=0.0001)
        fill = model.apply_with_spread(1.26000, TradeDirection.LONG, spread=0.0002)
        assert fill == 1.26010

    def test_spread_short_pays_half(self):
        model = SlippageModel(base_pips=0.0, random_pips=0.0, pip_value=0.0001)
        fill = model.apply_with_spread(1.26000, TradeDirection.SHORT, spread=0.0002)
        assert fill == 1.25990

    def test_spread_plus_slippage(self):
        model = SlippageModel(base_pips=0.1, random_pips=0.0, pip_value=0.0001)
        fill = model.apply_with_spread(1.26000, TradeDirection.LONG, spread=0.0002)
        assert fill == pytest.approx(1.26011, abs=1e-8)

    def test_zero_spread_no_effect(self):
        model = SlippageModel(base_pips=0.1, random_pips=0.0, pip_value=0.0001)
        fill_no_spread = model.apply(1.26000, TradeDirection.LONG)
        fill_zero_spread = model.apply_with_spread(1.26000, TradeDirection.LONG, spread=0.0)
        assert fill_no_spread == fill_zero_spread


class TestPaperOrderSlippage:
    def test_paper_fill_includes_slippage(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.26000,
            stop_loss=1.25800,
            take_profit=1.26200,
            spread=0.0002,
        )
        assert result.success
        assert result.slippage_applied > 0
        assert result.order.filled_price != result.order.price

    def test_paper_fill_with_no_spread_still_has_slippage(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.26000,
            stop_loss=1.25800,
            take_profit=1.26200,
        )
        assert result.success
        assert result.slippage_applied >= 0

    def test_short_paper_fill_worse_than_signal(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="GBPUSD",
            direction=TradeDirection.SHORT,
            volume=0.1,
            entry_price=1.26000,
            stop_loss=1.26200,
            take_profit=1.25800,
            spread=0.0002,
        )
        assert result.success
        assert result.order.filled_price < 1.26000

    def test_position_entry_uses_fill_price(self):
        manager = OrderManager()
        result = manager.execute_paper_order(
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.26000,
            stop_loss=1.25800,
            take_profit=1.26200,
            spread=0.0002,
        )
        assert result.success
        assert result.position.entry_price == result.order.filled_price


class TestPaperTraderSpreadPassthrough:
    def _make_trader(self):
        return PaperTrader(
            ftmo_config=FTMOConfig(
                daily_loss_limit_pct=0.05,
                total_drawdown_limit_pct=0.10,
                max_trades_per_day=10,
                max_positions=5,
                max_position_size_pct=1.0,
            ),
            position_config=PositionSizeConfig(),
            starting_balance=100000.0,
        )

    def test_process_signal_with_spread(self):
        trader = self._make_trader()
        signal = _make_signal()
        result = trader.process_signal(signal, spread=0.0002)
        assert result.success
        assert result.slippage_applied > 0

    def test_process_signal_no_spread(self):
        trader = self._make_trader()
        signal = _make_signal()
        result = trader.process_signal(signal)
        assert result.success
        assert result.slippage_applied >= 0

    def test_slippage_recorded_in_result(self):
        trader = self._make_trader()
        signal = _make_signal()
        result = trader.process_signal(signal, spread=0.0003)
        assert result.success
        assert isinstance(result.slippage_applied, float)

    def test_process_signal_with_real_bid_ask_uses_ask_for_long(self):
        trader = self._make_trader()
        signal = _make_signal(entry=1.26000)
        result = trader.process_signal(signal, bid=1.26100, ask=1.26120)
        assert result.success
        assert result.position is not None
        assert result.position.entry_price >= 1.26120

    def test_process_signal_with_real_bid_ask_uses_bid_for_short(self):
        trader = self._make_trader()
        signal = _make_signal(direction=TradeDirection.SHORT, entry=1.26000, sl=1.26450, tp=1.25100)
        result = trader.process_signal(signal, bid=1.25980, ask=1.26000)
        assert result.success
        assert result.position is not None
        assert result.position.entry_price <= 1.25980

    def test_process_signal_without_bid_ask_falls_back(self):
        trader = self._make_trader()
        signal = _make_signal(entry=1.26000)
        result = trader.process_signal(signal)
        assert result.success
        assert result.position is not None
        assert result.position.entry_price >= 1.26000


class TestClearStuckPositions:
    def _make_trader_with_positions(self, count=3):
        trader = PaperTrader(
            ftmo_config=FTMOConfig(
                daily_loss_limit_pct=0.05,
                total_drawdown_limit_pct=0.10,
                max_trades_per_day=10,
                max_positions=10,
                max_position_size_pct=1.0,
            ),
            position_config=PositionSizeConfig(),
            starting_balance=100000.0,
        )
        for _ in range(count):
            signal = _make_signal()
            trader.process_signal(signal)
        assert len(trader.get_open_positions()) == count
        return trader

    def test_clear_all_stuck_positions(self):
        trader = self._make_trader_with_positions(3)
        cleared = trader.clear_stuck_positions()
        assert cleared == 3
        assert len(trader.get_open_positions()) == 0

    def test_clear_when_no_positions(self):
        trader = PaperTrader(
            ftmo_config=FTMOConfig(),
            position_config=PositionSizeConfig(),
            starting_balance=100000.0,
        )
        cleared = trader.clear_stuck_positions()
        assert cleared == 0

    def test_balance_after_clear(self):
        trader = self._make_trader_with_positions(1)
        trader.update_market_prices({"GBPUSD": 1.26100})
        trader.clear_stuck_positions()
        stats = trader.get_stats()
        assert stats.realized_pnl != 0.0 or stats.current_balance == 100000.0


class TestResetFunctionality:
    def test_reset_clears_history(self):
        trader = PaperTrader(
            ftmo_config=FTMOConfig(
                daily_loss_limit_pct=0.05,
                total_drawdown_limit_pct=0.10,
                max_trades_per_day=10,
                max_positions=10,
                max_position_size_pct=1.0,
            ),
            position_config=PositionSizeConfig(),
            starting_balance=100000.0,
        )
        signal = _make_signal()
        trader.process_signal(signal)
        assert trader.get_stats().trades_executed == 1

        trader.reset()
        assert trader.get_stats().trades_executed == 0
        assert trader.get_stats().current_balance == 100000.0

    def test_reset_after_clear(self):
        trader = PaperTrader(
            ftmo_config=FTMOConfig(
                daily_loss_limit_pct=0.05,
                total_drawdown_limit_pct=0.10,
                max_trades_per_day=10,
                max_positions=10,
                max_position_size_pct=1.0,
            ),
            position_config=PositionSizeConfig(),
            starting_balance=100000.0,
        )
        for _ in range(5):
            signal = _make_signal()
            trader.process_signal(signal)

        trader.clear_stuck_positions()
        trader.reset()

        stats = trader.get_stats()
        assert stats.trades_executed == 0
        assert stats.current_balance == 100000.0
        assert stats.realized_pnl == 0.0
