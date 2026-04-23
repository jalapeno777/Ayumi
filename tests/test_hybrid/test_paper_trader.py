from datetime import datetime, timezone


from hybrid.paper_trader import (
    CloseReason,
    HybridPaperTrader,
    PaperTradingStats,
    SlippageModel,
)
from hybrid.risk_manager import RiskAction
from hybrid.signal import HumanSignal, SignalType
from hybrid.trade_rules import TradeRulesConfig


def _buy_signal(
    pair: str = "EUR/USD",
    entry: float = 1.1000,
    sl: float = 1.0950,
    tp: float = 1.1150,
    hour: int = 8,
) -> HumanSignal:
    return HumanSignal(
        signal_type=SignalType.BUY,
        pair=pair,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        confidence=0.8,
        timestamp=datetime(2026, 4, 23, hour, 0, tzinfo=timezone.utc),
    )


def _sell_signal(
    pair: str = "GBP/USD",
    entry: float = 1.2600,
    sl: float = 1.2650,
    tp: float = 1.2450,
    hour: int = 13,
) -> HumanSignal:
    return HumanSignal(
        signal_type=SignalType.SELL,
        pair=pair,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        confidence=0.7,
        timestamp=datetime(2026, 4, 23, hour, 0, tzinfo=timezone.utc),
    )


class TestSlippageModel:
    def test_apply_long_returns_higher_price(self):
        model = SlippageModel(base_pips=0.0, random_pips=0.0)
        fill, slippage = model.apply(1.1000, is_long=True)
        assert fill == 1.1000
        assert slippage == 0.0

    def test_apply_short_returns_lower_price(self):
        model = SlippageModel(base_pips=0.0, random_pips=0.0)
        fill, slippage = model.apply(1.1000, is_long=False)
        assert fill == 1.1000
        assert slippage == 0.0


class TestHybridPaperTraderInit:
    def test_default_initialization(self):
        trader = HybridPaperTrader()
        assert trader.balance == 100_000.0
        stats = trader.get_stats()
        assert stats.starting_balance == 100_000.0
        assert stats.current_balance == 100_000.0
        assert stats.total_signals_processed == 0
        assert stats.trades_executed == 0

    def test_custom_starting_balance(self):
        trader = HybridPaperTrader(starting_balance=50_000.0)
        assert trader.balance == 50_000.0

    def test_ftmo_config_applied(self):
        config = TradeRulesConfig.ftmo()
        trader = HybridPaperTrader(
            trade_rules_config=config, starting_balance=100_000.0
        )
        assert trader.balance == 100_000.0


class TestProcessSignal:
    def test_valid_buy_signal_succeeds(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        result = trader.process_signal(_buy_signal())
        assert result.success is True
        assert result.position_id != ""
        assert result.lot_size > 0

    def test_valid_sell_signal_succeeds(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        result = trader.process_signal(_sell_signal())
        assert result.success is True
        assert result.position_id != ""

    def test_close_signal_returns_success_no_position(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        result = trader.process_signal(
            HumanSignal(signal_type=SignalType.CLOSE, pair="EUR/USD")
        )
        assert result.success is True
        assert result.position_id == ""

    def test_rejected_signal_increments_rejected_count(self):
        config = TradeRulesConfig.ftmo()
        config.min_risk_reward = 5.0
        trader = HybridPaperTrader(
            trade_rules_config=config, starting_balance=100_000.0
        )
        result = trader.process_signal(_buy_signal())
        assert result.success is False
        assert "risk:reward" in result.rejection_reason.lower()
        stats = trader.get_stats()
        assert stats.signals_rejected >= 1

    def test_signal_increments_stats(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        trader.process_signal(_buy_signal())
        stats = trader.get_stats()
        assert stats.total_signals_processed == 1
        assert stats.signals_accepted == 1


class TestClosePosition:
    def test_close_existing_position(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        open_result = trader.process_signal(_buy_signal())
        assert open_result.success is True

        close_result = trader.close_position(open_result.position_id, exit_price=1.1050)
        assert close_result.success is True
        assert close_result.position_id == open_result.position_id
        assert close_result.exit_price == 1.1050

    def test_close_nonexistent_position(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        result = trader.close_position("nonexistent-id", exit_price=1.1000)
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_close_already_closed_position(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        open_result = trader.process_signal(_buy_signal())
        trader.close_position(open_result.position_id, exit_price=1.1050)
        second_close = trader.close_position(open_result.position_id, exit_price=1.1050)
        assert second_close.success is False
        assert "already closed" in second_close.error.lower()


class TestGetOpenPositions:
    def test_no_positions_initially(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        assert trader.get_open_positions() == []

    def test_one_position_after_signal(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        trader.process_signal(_buy_signal())
        positions = trader.get_open_positions()
        assert len(positions) == 1
        assert positions[0].pair == "EUR/USD"
        assert positions[0].direction == "long"
        assert positions[0].is_open is True

    def test_multiple_positions(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        trader.process_signal(_buy_signal())
        trader.process_signal(
            HumanSignal(
                signal_type=SignalType.SELL,
                pair="GBP/USD",
                entry_price=1.2600,
                stop_loss=1.2650,
                take_profit=1.2450,
                timestamp=datetime(2026, 4, 23, 13, 0, tzinfo=timezone.utc),
            )
        )
        positions = trader.get_open_positions()
        assert len(positions) == 2


class TestCloseAllPositions:
    def test_close_all_closes_everything(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        trader.process_signal(_buy_signal())
        trader.process_signal(
            HumanSignal(
                signal_type=SignalType.SELL,
                pair="GBP/USD",
                entry_price=1.2600,
                stop_loss=1.2650,
                take_profit=1.2450,
                timestamp=datetime(2026, 4, 23, 13, 0, tzinfo=timezone.utc),
            )
        )
        results = trader.close_all_positions(reason=CloseReason.FORCE_CLOSE)
        assert len(results) == 2
        assert len(trader.get_open_positions()) == 0


class TestUpdateMarketPrices:
    def test_update_prices_calculates_unrealized_pnl(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        open_result = trader.process_signal(
            _buy_signal(entry=1.1000, sl=1.0950, tp=1.1150)
        )
        assert open_result.success is True

        trader.update_market_prices({"EUR/USD": 1.1050})
        positions = trader.get_open_positions()
        assert len(positions) == 1
        assert positions[0].unrealized_pnl > 0

    def test_update_prices_triggers_stop_loss(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        open_result = trader.process_signal(
            _buy_signal(entry=1.1000, sl=1.0950, tp=1.1150)
        )
        assert open_result.success is True

        trader.update_market_prices({"EUR/USD": 1.0949})
        positions = trader.get_open_positions()
        assert len(positions) == 0

    def test_update_with_multiple_positions(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        trader.process_signal(_buy_signal())
        trader.process_signal(
            HumanSignal(
                signal_type=SignalType.SELL,
                pair="GBP/USD",
                entry_price=1.2600,
                stop_loss=1.2650,
                take_profit=1.2450,
                timestamp=datetime(2026, 4, 23, 13, 0, tzinfo=timezone.utc),
            )
        )
        trader.update_market_prices({"EUR/USD": 1.1020, "GBP/USD": 1.2550})
        positions = trader.get_open_positions()
        assert len(positions) == 2


class TestGetStats:
    def test_stats_initial_state(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        stats = trader.get_stats()
        assert stats.starting_balance == 100_000.0
        assert stats.current_balance == 100_000.0
        assert stats.total_signals_processed == 0

    def test_stats_after_win(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        open_result = trader.process_signal(_buy_signal())
        trader.close_position(open_result.position_id, exit_price=1.1100)
        stats = trader.get_stats()
        assert stats.trades_closed == 1
        assert stats.wins == 1
        assert stats.current_balance > 100_000.0

    def test_stats_after_loss(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        open_result = trader.process_signal(_buy_signal())
        trader.close_position(open_result.position_id, exit_price=1.0900)
        stats = trader.get_stats()
        assert stats.trades_closed == 1
        assert stats.losses == 1
        assert stats.current_balance < 100_000.0


class TestReset:
    def test_reset_clears_state(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        trader.process_signal(_buy_signal())
        trader.reset()
        stats = trader.get_stats()
        assert stats.total_signals_processed == 0
        assert stats.trades_executed == 0
        assert stats.current_balance == 100_000.0
        assert len(trader.get_open_positions()) == 0


class TestPaperTradingStats:
    def test_default_values(self):
        stats = PaperTradingStats()
        assert stats.total_signals_processed == 0
        assert stats.signals_accepted == 0
        assert stats.signals_rejected == 0
        assert stats.trades_executed == 0
        assert stats.starting_balance == 100_000.0

    def test_win_loss_counting(self):
        stats = PaperTradingStats(wins=5, losses=3)
        assert stats.wins == 5
        assert stats.losses == 3


class TestSimulateTradingDay:
    def test_simulate_full_day_with_multiple_signals(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)

        r1 = trader.process_signal(
            HumanSignal(
                signal_type=SignalType.BUY,
                pair="EUR/USD",
                entry_price=1.1000,
                stop_loss=1.0950,
                take_profit=1.1150,
                confidence=0.8,
                timestamp=datetime(2026, 4, 23, 8, 0, tzinfo=timezone.utc),
            )
        )
        assert r1.success is True

        r2 = trader.process_signal(
            HumanSignal(
                signal_type=SignalType.SELL,
                pair="GBP/USD",
                entry_price=1.2600,
                stop_loss=1.2650,
                take_profit=1.2450,
                confidence=0.7,
                timestamp=datetime(2026, 4, 23, 9, 0, tzinfo=timezone.utc),
            )
        )
        assert r2.success is True

        r3 = trader.process_signal(
            HumanSignal(
                signal_type=SignalType.BUY,
                pair="USD/JPY",
                entry_price=150.00,
                stop_loss=149.50,
                take_profit=151.00,
                confidence=0.75,
                timestamp=datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc),
            )
        )
        assert r3.success is True

        assert len(trader.get_open_positions()) == 3

        trader.update_market_prices(
            {"EUR/USD": 1.1100, "GBP/USD": 1.2500, "USD/JPY": 150.50}
        )

        stats = trader.get_stats()
        assert stats.trades_executed == 3
        assert stats.signals_accepted == 3

        results = trader.close_all_positions(
            exit_prices={"EUR/USD": 1.1100, "GBP/USD": 1.2500, "USD/JPY": 150.50},
            reason=CloseReason.FORCE_CLOSE,
        )
        assert len(results) == 3

        final_stats = trader.get_stats()
        assert final_stats.trades_closed == 3
        assert final_stats.current_balance != 100_000.0


class TestFtmoLimitsEnforced:
    def test_daily_loss_limit_triggers_circuit_breaker(self):
        config = TradeRulesConfig.ftmo()
        config.daily_loss.max_loss_pct = 0.01
        trader = HybridPaperTrader(
            trade_rules_config=config,
            starting_balance=100_000.0,
        )

        r1 = trader.process_signal(_buy_signal(entry=1.1000, sl=1.0950, tp=1.1100))
        assert r1.success is True

        pos1 = trader.get_position(r1.position_id)
        pos1.realized_pnl = -1200.0
        trader.engine.risk_manager.record_trade(pnl=-1200.0)
        trader.rules_engine.record_pnl(-1200.0)
        trader._stats.realized_pnl = -1200.0
        trader._current_balance = 100_000.0 - 1200.0

        r2 = trader.process_signal(_buy_signal())
        assert r2.success is False


class TestProgressiveSLAndPartialClose:
    def test_progressive_sl_moves_stop_loss(self):
        config = TradeRulesConfig.ftmo()
        config.progressive_sl.breakeven_trigger_pips = 10.0
        config.progressive_sl.breakeven_offset_pips = 2.0
        config.progressive_sl.trail_start_pips = 50.0
        config.progressive_sl.trail_step_pips = 10.0
        config.partial_profit.enabled = True
        config.partial_profit.tiers = [(0.50, 1.0, True), (0.75, 2.0, False)]

        trader = HybridPaperTrader(
            trade_rules_config=config,
            starting_balance=100_000.0,
        )

        r = trader.process_signal(_buy_signal(entry=1.1000, sl=1.0950, tp=1.1150))
        assert r.success is True

        trader.update_market_prices({"EUR/USD": 1.1020})


class TestSessionFilterDisabled:
    def test_session_filter_disabled_allows_out_of_session(self):
        trader = HybridPaperTrader(use_session_filter=False)
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1150,
            timestamp=datetime(2026, 4, 23, 22, 0, tzinfo=timezone.utc),
        )
        result = trader.process_signal(signal)
        assert result.success is True


class TestRiskManagerPositionCountDecrement:
    def test_close_position_decrements_risk_manager_count(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        r1 = trader.process_signal(_buy_signal())
        assert r1.success is True
        assert trader.engine.risk_manager.open_position_count == 1

        trader.close_position(r1.position_id, exit_price=1.1050)
        assert trader.engine.risk_manager.open_position_count == 0

    def test_multiple_open_close_cycles(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        for _ in range(3):
            r = trader.process_signal(_buy_signal())
            assert r.success is True
        assert trader.engine.risk_manager.open_position_count == 3

        positions = trader.get_open_positions()
        for pos in positions:
            trader.close_position(pos.position_id, exit_price=1.1050)
        assert trader.engine.risk_manager.open_position_count == 0

    def test_stop_loss_close_decrements_risk_manager_count(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        r = trader.process_signal(_buy_signal(entry=1.1000, sl=1.0950, tp=1.1150))
        assert r.success is True
        assert trader.engine.risk_manager.open_position_count == 1

        trader.update_market_prices({"EUR/USD": 1.0949})
        assert trader.engine.risk_manager.open_position_count == 0


class TestDailyReset:
    def test_reset_daily_clears_risk_manager_daily_tracking(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        trader.engine.risk_manager.record_trade(pnl=0.0, risk_pct=0.5)
        trader.engine.risk_manager.record_trade(pnl=0.0, risk_pct=0.5)
        assert trader.engine.risk_manager.daily_trade_count == 2

        trader.reset_daily()
        assert trader.engine.risk_manager.daily_trade_count == 0

    def test_reset_daily_clears_rules_engine_daily_bucket(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        trader.rules_engine.record_pnl(-500.0)
        now = datetime(2026, 4, 24, 0, 0, tzinfo=timezone.utc)
        trader.reset_daily(now)
        stats = trader.rules_engine.get_stats()
        assert stats["daily_trade_count"] == 0

    def test_reset_daily_allows_trades_after_budget_exhausted(self):
        trader = HybridPaperTrader(
            starting_balance=100_000.0,
        )
        trader.engine.risk_manager.record_trade(pnl=0.0, risk_pct=0.5)
        trader.engine.risk_manager.record_trade(pnl=0.0, risk_pct=0.5)
        trader.engine.risk_manager.record_trade(pnl=0.0, risk_pct=0.5)
        decision = trader.engine.risk_manager.validate_signal(_buy_signal())
        assert decision.action == RiskAction.REJECT

        trader.reset_daily()
        decision = trader.engine.risk_manager.validate_signal(_buy_signal())
        assert decision.action == RiskAction.ALLOW


class TestPaperPositionOpenedAt:
    def test_opened_at_uses_signal_timestamp(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        signal_time = datetime(2026, 2, 10, 8, 30, tzinfo=timezone.utc)
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1150,
            timestamp=signal_time,
        )
        r = trader.process_signal(signal)
        assert r.success is True
        pos = trader.get_position(r.position_id)
        assert pos is not None
        assert pos.opened_at == signal_time

    def test_opened_at_different_from_wall_clock(self):
        trader = HybridPaperTrader(starting_balance=100_000.0)
        historical_time = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1150,
            timestamp=historical_time,
        )
        r = trader.process_signal(signal)
        pos = trader.get_position(r.position_id)
        assert pos.opened_at.year == 2026
        assert pos.opened_at.month == 1
