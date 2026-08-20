import unittest  # noqa: I001
from datetime import datetime

from core.types import (
    Bar,
    BarPeriod,
    ExitReason,
    MarketState,
    SessionType,
    SimulatedTrade,
    StrategySignal,
    TradeDirection,
    TradeOutcome,
)
from core.config import BacktestConfig, BacktestMetrics
from core.protocol import IStrategy


class TestTradeDirection(unittest.TestCase):
    def test_values(self):
        self.assertEqual(TradeDirection.LONG, "long")
        self.assertEqual(TradeDirection.SHORT, "short")
        self.assertEqual(TradeDirection.NEUTRAL, "neutral")

    def test_is_str_enum(self):
        self.assertIsInstance(TradeDirection.LONG, str)


class TestSessionType(unittest.TestCase):
    def test_values(self):
        self.assertEqual(SessionType.ASIAN, "asian")
        self.assertEqual(SessionType.LONDON, "london")
        self.assertEqual(SessionType.NY_AM, "ny_am")
        self.assertEqual(SessionType.NY_PM, "ny_pm")
        self.assertEqual(SessionType.OUTSIDE, "outside")


class TestTradeOutcome(unittest.TestCase):
    def test_values(self):
        self.assertEqual(TradeOutcome.WIN, "win")
        self.assertEqual(TradeOutcome.LOSS, "loss")
        self.assertEqual(TradeOutcome.BREAKEVEN, "breakeven")
        self.assertEqual(TradeOutcome.OPEN, "open")


class TestExitReason(unittest.TestCase):
    def test_take_profit_values(self):
        self.assertEqual(ExitReason.TAKE_PROFIT_1, "take_profit_1")
        self.assertEqual(ExitReason.TAKE_PROFIT_2, "take_profit_2")
        self.assertEqual(ExitReason.TAKE_PROFIT_3, "take_profit_3")

    def test_stop_loss(self):
        self.assertEqual(ExitReason.STOP_LOSS, "stop_loss")

    def test_signal_flip(self):
        self.assertEqual(ExitReason.SIGNAL_FLIP, "signal_flip")

    def test_new_exit_reasons(self):
        self.assertEqual(ExitReason.TIME_STOP, "time_stop")
        self.assertEqual(ExitReason.MOMENTUM_REVERSAL, "momentum_reversal")
        self.assertEqual(ExitReason.WEEKEND_CLOSE, "weekend_close")
        self.assertEqual(ExitReason.TRAILING_STOP, "trailing_stop")


class TestBarPeriod(unittest.TestCase):
    def test_is_frozen(self):
        bp = BarPeriod(60)
        with self.assertRaises(AttributeError):
            bp.minutes = 30

    def test_factory_methods(self):
        self.assertEqual(BarPeriod.M15().minutes, 15)
        self.assertEqual(BarPeriod.H1().minutes, 60)
        self.assertEqual(BarPeriod.H4().minutes, 240)
        self.assertEqual(BarPeriod.D1().minutes, 1440)

    def test_factory_returns_new_instances(self):
        a = BarPeriod.H1()
        b = BarPeriod.H1()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)

    def test_custom_period(self):
        bp = BarPeriod(30)
        self.assertEqual(bp.minutes, 30)


class TestBar(unittest.TestCase):
    def test_basic_bar(self):
        bar = Bar(
            time=datetime(2024, 1, 1, 10, 0),
            open=1.0,
            high=1.01,
            low=0.99,
            close=1.005,
        )
        self.assertEqual(bar.open, 1.0)
        self.assertEqual(bar.high, 1.01)
        self.assertEqual(bar.low, 0.99)
        self.assertEqual(bar.close, 1.005)

    def test_defaults(self):
        bar = Bar(
            time=datetime(2024, 1, 1),
            open=1.0,
            high=1.01,
            low=0.99,
            close=1.005,
        )
        self.assertEqual(bar.volume, 0.0)
        self.assertEqual(bar.period, BarPeriod.H1())


class TestMarketState(unittest.TestCase):
    def _make_bars(self, n=20):
        bars = []
        for i in range(n):
            bars.append(
                Bar(
                    time=datetime(2024, 1, 1 + i),
                    open=1.0 + i * 0.001,
                    high=1.0 + i * 0.001 + 0.001,
                    low=1.0 + i * 0.001 - 0.001,
                    close=1.0 + i * 0.0005,
                )
            )
        return bars

    def test_latest_bar(self):
        bars = self._make_bars(5)
        state = MarketState(bars=bars)
        self.assertEqual(state.latest_bar, bars[-1])

    def test_default_session(self):
        state = MarketState(bars=self._make_bars())
        self.assertEqual(state.current_session, SessionType.OUTSIDE)

    def test_atr_with_few_bars(self):
        state = MarketState(bars=self._make_bars(5))
        self.assertEqual(state.atr, 0.0001)

    def test_atr_with_enough_bars(self):
        state = MarketState(bars=self._make_bars(20))
        atr = state.atr
        self.assertGreater(atr, 0.0)


class TestStrategySignal(unittest.TestCase):
    def test_basic_signal(self):
        signal = StrategySignal(
            direction=TradeDirection.LONG,
            confidence=0.8,
            entry_price=1.0,
            stop_loss=0.99,
            take_profit_1=1.01,
            take_profit_2=1.02,
            take_profit_3=1.03,
            rationale="test",
        )
        self.assertEqual(signal.direction, TradeDirection.LONG)
        self.assertEqual(signal.confidence, 0.8)
        self.assertFalse(signal.is_volatile)

    def test_volatile_flag(self):
        signal = StrategySignal(
            direction=TradeDirection.SHORT,
            confidence=0.6,
            entry_price=1.0,
            stop_loss=1.01,
            take_profit_1=0.99,
            take_profit_2=0.98,
            take_profit_3=0.97,
            rationale="volatile",
            is_volatile=True,
        )
        self.assertTrue(signal.is_volatile)


class TestSimulatedTrade(unittest.TestCase):
    def test_defaults(self):
        trade = SimulatedTrade(entry_bar_index=0)
        self.assertEqual(trade.direction, TradeDirection.NEUTRAL)
        self.assertEqual(trade.outcome, TradeOutcome.OPEN)
        self.assertIsNone(trade.exit_reason)

    def test_fully_specified(self):
        trade = SimulatedTrade(
            entry_bar_index=10,
            exit_bar_index=20,
            direction=TradeDirection.LONG,
            entry_price=1.0,
            stop_loss=0.99,
            take_profit_1=1.01,
            take_profit_2=1.02,
            take_profit_3=1.03,
            exit_price=1.015,
            lot_size=0.1,
            risk_amount=100.0,
            pips=150.0,
            profit_loss=150.0,
            outcome=TradeOutcome.WIN,
            exit_reason=ExitReason.TAKE_PROFIT_2,
            entry_time=datetime(2024, 1, 1, 10, 0),
            exit_time=datetime(2024, 1, 1, 12, 0),
            confidence_score=0.8,
            confluence_count=3,
            rationale="test trade",
        )
        self.assertEqual(trade.pips, 150.0)
        self.assertEqual(trade.exit_reason, ExitReason.TAKE_PROFIT_2)


class TestBacktestConfig(unittest.TestCase):
    def test_defaults(self):
        config = BacktestConfig()
        self.assertEqual(config.starting_balance, 100_000.0)
        self.assertEqual(config.pair, "EURUSD")
        self.assertEqual(config.spread_pips, 1.5)
        self.assertEqual(config.sharpe_annualization_factor, 252.0)

    def test_custom(self):
        config = BacktestConfig(starting_balance=50_000.0, pair="GBPUSD")
        self.assertEqual(config.starting_balance, 50_000.0)
        self.assertEqual(config.pair, "GBPUSD")


class TestBacktestMetrics(unittest.TestCase):
    def test_defaults(self):
        metrics = BacktestMetrics(
            starting_balance=100_000.0,
            ending_balance=101_000.0,
            total_pnl=1000.0,
            total_pnl_pct=0.01,
            win_rate=50.0,
            total_trades=10,
            winning_trades=5,
            losing_trades=4,
            breakeven_trades=1,
            avg_win=200.0,
            avg_loss=100.0,
            largest_win=500.0,
            largest_loss=200.0,
            profit_factor=2.0,
            max_drawdown_pct=2.0,
            max_drawdown_dollar=2000.0,
            max_daily_loss_dollar=500.0,
            sharpe_ratio=1.5,
            avg_risk_reward=2.0,
            expectancy=50.0,
            avg_holding_bars=12.0,
        )
        self.assertEqual(metrics.total_pnl, 1000.0)
        self.assertEqual(metrics.equity_curve, [])
        self.assertEqual(metrics.trades, [])


class TestIStrategyProtocol(unittest.TestCase):
    def test_concrete_class_satisfies_protocol(self):
        class MyStrategy:
            @property
            def name(self) -> str:
                return "my_strategy"

            def evaluate(self, state: MarketState) -> StrategySignal | None:
                return None

        strategy = MyStrategy()
        self.assertIsInstance(strategy, IStrategy)

    def test_class_without_name_does_not_satisfy(self):
        class BadStrategy:
            def evaluate(self, state: MarketState) -> StrategySignal | None:
                return None

        strategy = BadStrategy()
        self.assertNotIsInstance(strategy, IStrategy)

    def test_class_without_evaluate_does_not_satisfy(self):
        class BadStrategy:
            @property
            def name(self) -> str:
                return "bad"

        strategy = BadStrategy()
        self.assertNotIsInstance(strategy, IStrategy)
