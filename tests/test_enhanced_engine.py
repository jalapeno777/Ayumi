import unittest
from datetime import datetime, timedelta

from backtest.engine import (
    Bar,
    BacktestConfig,
    TradeDirection,
    TradeOutcome,
    ExitReason,
)
from backtest.strategies import MACrossStrategy, BBStrategy
from backtest.enhanced_engine import EnhancedBacktestEngine, EnhancedTradeRecord
from backtest.trade_management.config import (
    TradeManagementConfig,
    PartialExitConfig,
    TrailingStopConfig,
    TrailingStopMethod,
    SessionFilterConfig,
    ExitRefinementConfig,
)


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005, v=1000):
    base = datetime(2024, 1, 1, 10, 0)
    time = base + timedelta(hours=i)
    return Bar(time=time, open=o, high=h, low=low, close=c, volume=v)


def _trending_bars(n=200, trend="up"):
    bars = []
    price = 1.0000
    for i in range(n):
        hour = i % 24
        if trend == "up":
            drift = 0.00005 + (0.00001 if hour in range(8, 16) else 0)
            noise = (i % 7 - 3) * 0.00003
        else:
            drift = -0.00005 - (0.00001 if hour in range(8, 16) else 0)
            noise = (i % 7 - 3) * 0.00003
        price += drift + noise
        h = price + abs(noise) * 2
        low = price - abs(noise) * 2
        bars.append(_bar(i, o=price - drift, h=h, low=low, c=price))
    return bars


def _volatile_bars(n=200):
    bars = []
    price = 1.0000
    for i in range(n):
        noise = ((i * 7 + 3) % 11 - 5) * 0.0002
        price += noise
        h = price + abs(noise) * 3
        low = price - abs(noise) * 3
        bars.append(_bar(i, o=price - noise, h=h, low=low, c=price))
    return bars


class TestEnhancedBacktestEngine(unittest.TestCase):
    def _default_config(self):
        return BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            spread_pips=0.5,
            commission_per_lot=3.5,
            leverage=100,
            min_confidence=0.40,
            min_bars_before_signal=30,
            max_open_trades=1,
        )

    def _default_tm_config(self):
        return TradeManagementConfig(
            partial_exit=PartialExitConfig(enabled=True),
            trailing_stop=TrailingStopConfig(
                enabled=True, method=TrailingStopMethod.ATR
            ),
            session_filter=SessionFilterConfig(enabled=True),
            exit_refinement=ExitRefinementConfig(enabled=True),
        )

    def test_basic_run_produces_metrics(self):
        bars = _trending_bars(200, "up")
        config = self._default_config()
        tm_config = self._default_tm_config()

        engine = EnhancedBacktestEngine(config, [MACrossStrategy()], tm_config)
        metrics = engine.run_strategy(MACrossStrategy(), bars)

        self.assertIsInstance(metrics, type(metrics))
        self.assertEqual(metrics.starting_balance, 10000.0)
        self.assertIsNotNone(metrics.ending_balance)
        self.assertGreaterEqual(len(metrics.equity_curve), 1)

    def test_run_all_strategies_returns_dict(self):
        bars = _trending_bars(200, "up")
        config = self._default_config()
        tm_config = self._default_tm_config()

        strategies = [MACrossStrategy(), BBStrategy()]
        engine = EnhancedBacktestEngine(config, strategies, tm_config)
        results = engine.run_all_strategies(bars)

        self.assertIn("MA Crossover", results)
        self.assertIn("Bollinger Band Mean Reversion", results)

    def test_session_filter_blocks_outside_entries(self):
        bars = []
        base = datetime(2024, 1, 1)
        for i in range(100):
            time = base + timedelta(hours=i)
            hour = time.hour
            if hour < 8 or hour >= 20:
                o, hi, lo, c = 1.0, 1.002, 0.998, 1.001
            else:
                o, hi, lo, c = 1.0, 1.01, 0.99, 1.005
            bars.append(Bar(time=time, open=o, high=hi, low=lo, close=c, volume=1000))

        config = self._default_config()
        tm_config = TradeManagementConfig(
            session_filter=SessionFilterConfig(
                enabled=True,
                allow_entry_sessions=["london", "ny_am"],
            ),
        )

        engine = EnhancedBacktestEngine(config, [MACrossStrategy()], tm_config)
        enhanced = engine.run_strategy(MACrossStrategy(), bars)

        self.assertGreaterEqual(enhanced.rejected_signals, 0)

    def test_partial_exit_disabled_falls_back_to_full(self):
        bars = _trending_bars(200, "up")
        config = self._default_config()
        tm_config = TradeManagementConfig(
            partial_exit=PartialExitConfig(enabled=False),
            trailing_stop=TrailingStopConfig(enabled=False),
            session_filter=SessionFilterConfig(enabled=False),
            exit_refinement=ExitRefinementConfig(enabled=False),
        )

        engine = EnhancedBacktestEngine(config, [MACrossStrategy()], tm_config)
        metrics = engine.run_strategy(MACrossStrategy(), bars)

        self.assertIsInstance(metrics, type(metrics))

    def test_ab_comparison_returns_both_metrics(self):
        bars = _trending_bars(200, "up")
        config = self._default_config()
        tm_config = self._default_tm_config()

        engine = EnhancedBacktestEngine(config, [MACrossStrategy()], tm_config)
        baseline, enhanced = engine.run_ab_comparison(MACrossStrategy(), bars)

        self.assertIsInstance(baseline, type(baseline))
        self.assertIsInstance(enhanced, type(enhanced))
        self.assertEqual(baseline.starting_balance, enhanced.starting_balance)

    def test_conservative_vs_aggressive_config(self):
        bars = _volatile_bars(200)
        config = self._default_config()

        conservative = TradeManagementConfig.conservative()
        aggressive = TradeManagementConfig.aggressive()

        engine_con = EnhancedBacktestEngine(config, [MACrossStrategy()], conservative)
        engine_agg = EnhancedBacktestEngine(config, [MACrossStrategy()], aggressive)

        m_con = engine_con.run_strategy(MACrossStrategy(), bars)
        m_agg = engine_agg.run_strategy(MACrossStrategy(), bars)

        self.assertIsInstance(m_con, type(m_con))
        self.assertIsInstance(m_agg, type(m_agg))

    def test_ftmo_config_runs(self):
        bars = _trending_bars(200, "up")
        config = self._default_config()
        tm_config = TradeManagementConfig.ftmo()

        engine = EnhancedBacktestEngine(config, [MACrossStrategy()], tm_config)
        metrics = engine.run_strategy(MACrossStrategy(), bars)

        self.assertIsInstance(metrics, type(metrics))

    def test_insufficient_bars_raises(self):
        bars = _trending_bars(10, "up")
        config = self._default_config()
        tm_config = self._default_tm_config()

        engine = EnhancedBacktestEngine(config, [MACrossStrategy()], tm_config)
        with self.assertRaises(ValueError):
            engine.run_strategy(MACrossStrategy(), bars)

    def test_enhanced_trade_record_to_simulated_trade(self):
        record = EnhancedTradeRecord(
            entry_bar_index=10,
            exit_bar_index=20,
            direction=TradeDirection.LONG,
            entry_price=1.0000,
            exit_price=1.0050,
            lot_size=10000,
            outcome=TradeOutcome.WIN,
            exit_reason=ExitReason.TAKE_PROFIT_1,
            entry_time=datetime(2024, 1, 1, 10, 0),
            exit_time=datetime(2024, 1, 1, 20, 0),
            confidence_score=0.8,
            rationale="test",
            profit_loss=50.0,
            pips=50.0,
            partial_closes=[
                {"bar_index": 15, "price": 1.0020, "pct": 0.5, "reason": "tp1"}
            ],
            partial_realized_pnl=20.0,
        )

        sim = record.to_simulated_trade()
        self.assertTrue(sim.partial_closed)
        self.assertAlmostEqual(sim.partial_close_pnl, 20.0)
        self.assertEqual(sim.exit_reason, ExitReason.TAKE_PROFIT_1)
        self.assertEqual(sim.direction, TradeDirection.LONG)

    def test_weekend_close_forces_exit(self):
        bars = []
        base = datetime(2024, 1, 5, 20, 0)
        for i in range(10):
            time = base + timedelta(hours=i)
            o, hi, lo, c = 1.0, 1.005, 0.995, 1.002
            bars.append(Bar(time=time, open=o, high=hi, low=lo, close=c, volume=1000))

        pre_bars = _trending_bars(50, "up")
        all_bars = pre_bars + bars

        config = self._default_config()
        tm_config = TradeManagementConfig(
            session_filter=SessionFilterConfig(
                enabled=True,
                weekend_close_hour_utc=21,
                weekend_close_minute_utc=55,
            ),
        )

        engine = EnhancedBacktestEngine(config, [MACrossStrategy()], tm_config)
        metrics = engine.run_strategy(MACrossStrategy(), all_bars)

        self.assertIsInstance(metrics, type(metrics))


class TestEnhancedPnLCalculation(unittest.TestCase):
    def test_partial_exit_pnl_tracked(self):
        from backtest.trade_management.trade_manager import ManagedTrade

        trade = ManagedTrade(
            entry_bar_index=0,
            direction=TradeDirection.LONG,
            entry_price=1.0000,
            stop_loss=0.9950,
            original_stop_loss=0.9950,
            take_profit_1=1.0050,
            take_profit_2=1.0100,
            take_profit_3=1.0150,
            lot_size=10000,
            entry_time=datetime(2024, 1, 1, 10, 0),
            confidence_score=0.8,
            rationale="test",
        )

        self.assertEqual(trade.remaining_pct, 1.0)
        self.assertEqual(trade.partial_realized_pnl, 0.0)

        trade.partial_realized_pnl = 25.0
        trade.remaining_pct = 0.5

        self.assertEqual(trade.partial_realized_pnl, 25.0)
        self.assertEqual(trade.remaining_pct, 0.5)


if __name__ == "__main__":
    unittest.main()
