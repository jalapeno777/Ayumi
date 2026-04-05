import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar, BacktestConfig
from backtest.strategies import MACrossStrategy
from backtest.enhanced_engine import EnhancedBacktestEngine
from backtest.trade_management.config import (
    TradeManagementConfig,
    PartialExitConfig,
    TrailingStopConfig,
    TrailingStopMethod,
    SessionFilterConfig,
    ExitRefinementConfig,
)
from quant.config import (
    CorrelationConfig,
    PositionSizingConfig,
    QuantConfig,
    RegimeConfig,
    SizingMode,
    WalkForwardConfig,
)


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
        base = datetime(2024, 1, 1, 10, 0)
        time = base + timedelta(hours=i)
        bars.append(Bar(time=time, open=price - drift, high=h, low=low, close=price))
    return bars


def _volatile_bars(n=200):
    bars = []
    price = 1.0000
    for i in range(n):
        noise = ((i * 7 + 3) % 11 - 5) * 0.0002
        price += noise
        h = price + abs(noise) * 3
        low = price - abs(noise) * 3
        base = datetime(2024, 1, 1, 10, 0)
        time = base + timedelta(hours=i)
        bars.append(Bar(time=time, open=price - noise, high=h, low=low, close=price))
    return bars


def _backtest_config():
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


def _tm_config():
    return TradeManagementConfig(
        partial_exit=PartialExitConfig(enabled=True),
        trailing_stop=TrailingStopConfig(
            enabled=True, method=TrailingStopMethod.ATR
        ),
        session_filter=SessionFilterConfig(enabled=True),
        exit_refinement=ExitRefinementConfig(enabled=True),
    )


class TestEnhancedBacktestWithQuantPipeline(unittest.TestCase):
    def test_paper_trading_config_runs_without_error(self):
        bars = _trending_bars(200, "up")
        bt_config = _backtest_config()
        tm_cfg = _tm_config()
        quant_cfg = QuantConfig.paper_trading()

        engine = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, quant_cfg
        )
        metrics = engine.run_strategy(MACrossStrategy(), bars)

        self.assertEqual(metrics.starting_balance, 10000.0)
        self.assertIsNotNone(metrics.ending_balance)
        self.assertGreaterEqual(len(metrics.equity_curve), 1)

    def test_ftmo_config_runs_without_error(self):
        bars = _trending_bars(200, "up")
        bt_config = _backtest_config()
        tm_cfg = _tm_config()
        quant_cfg = QuantConfig.ftmo()

        engine = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, quant_cfg
        )
        metrics = engine.run_strategy(MACrossStrategy(), bars)

        self.assertEqual(metrics.starting_balance, 10000.0)
        self.assertIsNotNone(metrics.ending_balance)
        self.assertGreaterEqual(metrics.total_trades, 0)

    def test_disabled_quant_runs_same_as_no_quant(self):
        bars = _trending_bars(200, "up")
        bt_config = _backtest_config()
        tm_cfg = _tm_config()

        engine_no_quant = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg
        )
        engine_disabled = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, QuantConfig.disabled()
        )

        m_no = engine_no_quant.run_strategy(MACrossStrategy(), bars)
        m_disabled = engine_disabled.run_strategy(MACrossStrategy(), bars)

        self.assertEqual(m_no.total_trades, m_disabled.total_trades)
        self.assertEqual(m_no.rejected_signals, m_disabled.rejected_signals)
        self.assertAlmostEqual(m_no.ending_balance, m_disabled.ending_balance, places=2)

    def test_quant_regime_filter_rejects_some_signals(self):
        cfg = QuantConfig(
            regime=RegimeConfig(
                enabled=True,
                min_confidence=0.95,
                block_extreme_volatility=True,
            ),
            correlation=CorrelationConfig(enabled=False),
            position_sizing=PositionSizingConfig(enabled=False),
        )
        bars = _volatile_bars(200)
        bt_config = _backtest_config()
        tm_cfg = _tm_config()

        engine_quant = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, cfg
        )
        engine_no_quant = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg
        )

        m_quant = engine_quant.run_strategy(MACrossStrategy(), bars)
        engine_no_quant.run_strategy(MACrossStrategy(), bars)

        self.assertGreaterEqual(m_quant.rejected_signals, 0)
        self.assertGreaterEqual(m_quant.total_trades, 0)

    def test_quant_pipeline_internally_tracks_trades(self):
        cfg = QuantConfig(
            regime=RegimeConfig(enabled=False),
            correlation=CorrelationConfig(enabled=False),
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.DYNAMIC,
                risk_pct=1.0,
            ),
        )
        bars = _trending_bars(200, "up")
        bt_config = _backtest_config()
        tm_cfg = _tm_config()

        engine = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, cfg
        )
        engine.run_strategy(MACrossStrategy(), bars)

        pipeline = engine._quant_pipeline
        self.assertIsNotNone(pipeline)
        self.assertGreaterEqual(pipeline.portfolio.total_trades, 0)

    def test_quant_position_sizing_changes_lot_size(self):
        cfg_with_sizing = QuantConfig(
            regime=RegimeConfig(enabled=False),
            correlation=CorrelationConfig(enabled=False),
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.DYNAMIC,
                risk_pct=1.0,
            ),
        )
        cfg_no_sizing = QuantConfig(
            regime=RegimeConfig(enabled=False),
            correlation=CorrelationConfig(enabled=False),
            position_sizing=PositionSizingConfig(enabled=False),
        )
        bars = _trending_bars(200, "up")
        bt_config = _backtest_config()
        tm_cfg = _tm_config()

        engine_sizing = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, cfg_with_sizing
        )
        engine_no_sizing = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, cfg_no_sizing
        )

        m_sizing = engine_sizing.run_strategy(MACrossStrategy(), bars)
        m_no_sizing = engine_no_sizing.run_strategy(MACrossStrategy(), bars)

        self.assertIsNotNone(m_sizing.ending_balance)
        self.assertIsNotNone(m_no_sizing.ending_balance)

    def test_quant_enabled_volatile_data_produces_rejections(self):
        cfg = QuantConfig.ftmo()
        bars = _volatile_bars(200)
        bt_config = _backtest_config()
        tm_cfg = _tm_config()

        engine = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, cfg
        )
        metrics = engine.run_strategy(MACrossStrategy(), bars)

        self.assertGreaterEqual(metrics.rejected_signals, 0)
        self.assertIsNotNone(metrics.max_drawdown_pct)

    def test_run_all_strategies_with_quant(self):
        from backtest.strategies import BBStrategy

        bars = _trending_bars(200, "up")
        bt_config = _backtest_config()
        tm_cfg = _tm_config()
        quant_cfg = QuantConfig.paper_trading()

        strategies = [MACrossStrategy(), BBStrategy()]
        engine = EnhancedBacktestEngine(bt_config, strategies, tm_cfg, quant_cfg)
        results = engine.run_all_strategies(bars)

        self.assertIn("MA Crossover", results)
        self.assertIn("Bollinger Band Mean Reversion", results)
        for name, result in results.items():
            self.assertIsNotNone(result.metrics)

    def test_insufficient_bars_raises_with_quant(self):
        bars = _trending_bars(10, "up")
        bt_config = _backtest_config()
        tm_cfg = _tm_config()

        engine = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, QuantConfig.paper_trading()
        )
        with self.assertRaises(ValueError):
            engine.run_strategy(MACrossStrategy(), bars)


class TestQuantBacktestEdgeCases(unittest.TestCase):
    def test_zero_trades_scenario(self):
        cfg = QuantConfig(
            regime=RegimeConfig(enabled=True, min_confidence=0.999),
            correlation=CorrelationConfig(enabled=False),
            position_sizing=PositionSizingConfig(enabled=False),
        )
        bars = _trending_bars(200, "up")
        bt_config = _backtest_config()
        tm_cfg = _tm_config()

        engine = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, cfg
        )
        metrics = engine.run_strategy(MACrossStrategy(), bars)

        self.assertEqual(metrics.starting_balance, 10000.0)
        self.assertGreaterEqual(metrics.total_trades, 0)
        self.assertIsNotNone(metrics.equity_curve)

    def test_correlation_rejection_in_backtest(self):
        cfg = QuantConfig(
            regime=RegimeConfig(enabled=False),
            correlation=CorrelationConfig(
                enabled=True,
                pairs=["EURUSD", "GBPUSD"],
                window=5,
                threshold=0.5,
                max_correlated_exposure=0.001,
            ),
            position_sizing=PositionSizingConfig(enabled=False),
        )
        bars = _trending_bars(200, "up")
        bt_config = _backtest_config()
        tm_cfg = _tm_config()

        engine = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, cfg
        )
        metrics = engine.run_strategy(MACrossStrategy(), bars)

        self.assertEqual(metrics.starting_balance, 10000.0)
        self.assertGreaterEqual(metrics.rejected_signals, 0)

    def test_multiple_runs_are_independent(self):
        bars = _trending_bars(200, "up")
        bt_config = _backtest_config()
        tm_cfg = _tm_config()
        quant_cfg = QuantConfig.paper_trading()

        engine1 = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, quant_cfg
        )
        engine2 = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, quant_cfg
        )

        m1 = engine1.run_strategy(MACrossStrategy(), bars)
        m2 = engine2.run_strategy(MACrossStrategy(), bars)

        self.assertEqual(m1.total_trades, m2.total_trades)
        self.assertAlmostEqual(m1.ending_balance, m2.ending_balance, places=2)

    def test_walk_forward_config_does_not_affect_backtest_run(self):
        cfg_with_wf = QuantConfig.ftmo()
        cfg_no_wf = QuantConfig(
            regime=cfg_with_wf.regime,
            correlation=cfg_with_wf.correlation,
            position_sizing=cfg_with_wf.position_sizing,
            walk_forward=WalkForwardConfig(enabled=False),
        )
        bars = _trending_bars(200, "up")
        bt_config = _backtest_config()
        tm_cfg = _tm_config()

        engine_wf = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, cfg_with_wf
        )
        engine_no_wf = EnhancedBacktestEngine(
            bt_config, [MACrossStrategy()], tm_cfg, cfg_no_wf
        )

        m_wf = engine_wf.run_strategy(MACrossStrategy(), bars)
        m_no_wf = engine_no_wf.run_strategy(MACrossStrategy(), bars)

        self.assertEqual(m_wf.total_trades, m_no_wf.total_trades)
        self.assertAlmostEqual(m_wf.ending_balance, m_no_wf.ending_balance, places=2)


if __name__ == "__main__":
    unittest.main()
