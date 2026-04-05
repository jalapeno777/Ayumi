import unittest
from dataclasses import dataclass
from datetime import datetime

from quant.config import (
    CorrelationConfig,
    PositionSizingConfig,
    QuantConfig,
    RegimeConfig,
    SizingMode,
    WalkForwardConfig,
)
from quant.pipeline import (
    PortfolioState,
    QuantPipeline,
    TradeAction,
    TradeResult,
    ValidationResult,
)


@dataclass
class FakeBar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class FakeSignal:
    symbol: str = "EURUSD"
    entry_price: float = 1.1000
    stop_loss: float = 1.0950
    take_profit_1: float = 1.1100
    take_profit_2: float = 0.0
    take_profit_3: float = 0.0
    confidence: float = 0.8
    volume: float = 0.1
    rationale: str = "test"


def _make_bars(n: int = 100, base_close: float = 1.1000) -> list[FakeBar]:
    bars = []
    for i in range(n):
        bars.append(
            FakeBar(
                time=datetime(2025, 1, 1, 10, 0) + __import__("datetime").timedelta(hours=i),
                open=base_close,
                high=base_close + 0.001,
                low=base_close - 0.001,
                close=base_close,
            )
        )
    return bars


class TestQuantConfigPresets(unittest.TestCase):
    def test_paper_trading_preset(self):
        cfg = QuantConfig.paper_trading()
        self.assertTrue(cfg.regime_enabled)
        self.assertTrue(cfg.correlation_enabled)
        self.assertTrue(cfg.position_sizing_enabled)
        self.assertFalse(cfg.walk_forward_enabled)
        self.assertEqual(cfg.position_sizing.mode, SizingMode.FIXED_FRACTIONAL)

    def test_ftmo_preset(self):
        cfg = QuantConfig.ftmo()
        self.assertTrue(cfg.regime_enabled)
        self.assertTrue(cfg.correlation_enabled)
        self.assertTrue(cfg.position_sizing_enabled)
        self.assertTrue(cfg.walk_forward_enabled)
        self.assertEqual(cfg.position_sizing.mode, SizingMode.DYNAMIC)
        self.assertEqual(cfg.position_sizing.risk_pct, 0.5)
        self.assertEqual(cfg.regime.min_confidence, 0.6)
        self.assertEqual(cfg.correlation.threshold, 0.6)

    def test_disabled_preset(self):
        cfg = QuantConfig.disabled()
        self.assertFalse(cfg.regime_enabled)
        self.assertFalse(cfg.correlation_enabled)
        self.assertFalse(cfg.position_sizing_enabled)
        self.assertFalse(cfg.walk_forward_enabled)

    def test_default_config(self):
        cfg = QuantConfig()
        self.assertTrue(cfg.regime_enabled)
        self.assertTrue(cfg.correlation_enabled)
        self.assertTrue(cfg.position_sizing_enabled)
        self.assertFalse(cfg.walk_forward_enabled)


class TestQuantPipelineAccept(unittest.TestCase):
    def setUp(self):
        self.cfg = QuantConfig.paper_trading()
        self.pipeline = QuantPipeline(self.cfg)
        self.bars = _make_bars(100)
        self.signal = FakeSignal()
        self.portfolio = PortfolioState(balance=10000.0)

    def test_accept_normal_conditions(self):
        decision = self.pipeline.pre_trade_check(
            self.signal, self.bars, self.portfolio
        )
        self.assertIn(decision.action, (TradeAction.ACCEPT, TradeAction.RESIZE))

    def test_accept_returns_lot_size(self):
        decision = self.pipeline.pre_trade_check(
            self.signal, self.bars, self.portfolio
        )
        self.assertIsNotNone(decision.adjusted_lot_size)
        self.assertGreater(decision.adjusted_lot_size, 0)

    def test_accept_regime_confidence(self):
        decision = self.pipeline.pre_trade_check(
            self.signal, self.bars, self.portfolio
        )
        self.assertGreaterEqual(decision.regime_confidence, 0.0)
        self.assertLessEqual(decision.regime_confidence, 1.0)


class TestQuantPipelineReject(unittest.TestCase):
    def setUp(self):
        self.cfg = QuantConfig.paper_trading()
        self.bars = _make_bars(100)
        self.signal = FakeSignal()
        self.portfolio = PortfolioState(balance=10000.0)

    def test_reject_extreme_volatility(self):
        stable_bars = _make_bars(50)
        for bar in stable_bars:
            bar.high = 1.1001
            bar.low = 1.0999
        extreme_bar = FakeBar(
            time=datetime(2025, 1, 5, 10, 0),
            open=1.1000, high=1.5000, low=0.5000, close=1.1000,
        )
        stable_bars.append(extreme_bar)
        cfg = QuantConfig(
            regime=RegimeConfig(enabled=True, block_extreme_volatility=True),
            correlation=CorrelationConfig(enabled=False),
            position_sizing=PositionSizingConfig(enabled=False),
        )
        pipeline = QuantPipeline(cfg)
        decision = pipeline.pre_trade_check(self.signal, stable_bars, self.portfolio)
        self.assertEqual(decision.action, TradeAction.REJECT)
        self.assertIn("volatility", decision.reason.lower())

    def test_reject_low_regime_confidence(self):
        cfg = QuantConfig(regime=RegimeConfig(enabled=True, min_confidence=0.99))
        pipeline = QuantPipeline(cfg)
        decision = pipeline.pre_trade_check(self.signal, self.bars, self.portfolio)
        self.assertEqual(decision.action, TradeAction.REJECT)
        self.assertIn("confidence", decision.reason.lower())

    def test_reject_correlation_exposure(self):
        cfg = QuantConfig(
            correlation=CorrelationConfig(
                enabled=True,
                pairs=["EURUSD", "GBPUSD"],
                window=5,
                threshold=0.5,
                max_correlated_exposure=0.01,
            ),
            position_sizing=PositionSizingConfig(enabled=False),
        )
        pipeline = QuantPipeline(cfg)
        portfolio = PortfolioState(
            balance=10000.0,
            open_positions=[
                {"symbol": "EURUSD", "exposure": 1.0},
                {"symbol": "GBPUSD", "exposure": 1.0},
            ],
        )
        decision = pipeline.pre_trade_check(self.signal, self.bars, portfolio)
        self.assertEqual(decision.action, TradeAction.REJECT)
        self.assertIn("correlation", decision.reason.lower())


class TestQuantPipelineDisabled(unittest.TestCase):
    def test_all_disabled_accepts(self):
        cfg = QuantConfig.disabled()
        pipeline = QuantPipeline(cfg)
        bars = _make_bars(10)
        signal = FakeSignal()
        portfolio = PortfolioState(balance=10000.0)
        decision = pipeline.pre_trade_check(signal, bars, portfolio)
        self.assertEqual(decision.action, TradeAction.ACCEPT)
        self.assertIsNone(decision.adjusted_lot_size)


class TestQuantPipelinePositionSizing(unittest.TestCase):
    def test_dynamic_sizing_applied(self):
        cfg = QuantConfig(
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.DYNAMIC,
                risk_pct=1.0,
            ),
            regime=RegimeConfig(enabled=False),
            correlation=CorrelationConfig(enabled=False),
        )
        pipeline = QuantPipeline(cfg)
        pipeline.on_trade_closed(TradeResult(pnl=-50, is_win=False))
        pipeline.on_trade_closed(TradeResult(pnl=-30, is_win=False))

        bars = _make_bars(100)
        signal = FakeSignal()
        portfolio = PortfolioState(balance=10000.0)
        decision = pipeline.pre_trade_check(signal, bars, portfolio)
        self.assertEqual(decision.action, TradeAction.RESIZE)
        self.assertIsNotNone(decision.adjusted_lot_size)

    def test_fixed_fractional_sizing(self):
        cfg = QuantConfig(
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.FIXED_FRACTIONAL,
                risk_pct=1.0,
            ),
            regime=RegimeConfig(enabled=False),
            correlation=CorrelationConfig(enabled=False),
        )
        pipeline = QuantPipeline(cfg)
        bars = _make_bars(100)
        signal = FakeSignal()
        portfolio = PortfolioState(balance=10000.0)
        decision = pipeline.pre_trade_check(signal, bars, portfolio)
        self.assertIn(decision.action, (TradeAction.ACCEPT, TradeAction.RESIZE))

    def test_zero_balance_returns_no_lot_size(self):
        cfg = QuantConfig(
            position_sizing=PositionSizingConfig(enabled=True),
            regime=RegimeConfig(enabled=False),
            correlation=CorrelationConfig(enabled=False),
        )
        pipeline = QuantPipeline(cfg)
        bars = _make_bars(100)
        signal = FakeSignal()
        portfolio = PortfolioState(balance=0.0)
        decision = pipeline.pre_trade_check(signal, bars, portfolio)
        self.assertEqual(decision.action, TradeAction.ACCEPT)
        self.assertIsNone(decision.adjusted_lot_size)


class TestQuantPipelineOnTradeClosed(unittest.TestCase):
    def test_win_updates_streak(self):
        pipeline = QuantPipeline(QuantConfig.disabled())
        pipeline.on_trade_closed(TradeResult(pnl=100, is_win=True))
        self.assertEqual(pipeline.portfolio.win_streak, 1)
        self.assertEqual(pipeline.portfolio.loss_streak, 0)

    def test_loss_updates_streak(self):
        pipeline = QuantPipeline(QuantConfig.disabled())
        pipeline.on_trade_closed(TradeResult(pnl=-50, is_win=False))
        self.assertEqual(pipeline.portfolio.win_streak, 0)
        self.assertEqual(pipeline.portfolio.loss_streak, 1)

    def test_consecutive_losses(self):
        pipeline = QuantPipeline(QuantConfig.disabled())
        pipeline.on_trade_closed(TradeResult(pnl=-50, is_win=False))
        pipeline.on_trade_closed(TradeResult(pnl=-30, is_win=False))
        pipeline.on_trade_closed(TradeResult(pnl=-20, is_win=False))
        self.assertEqual(pipeline.portfolio.loss_streak, 3)
        self.assertEqual(pipeline.portfolio.win_streak, 0)

    def test_streak_resets_on_alternating(self):
        pipeline = QuantPipeline(QuantConfig.disabled())
        pipeline.on_trade_closed(TradeResult(pnl=-50, is_win=False))
        pipeline.on_trade_closed(TradeResult(pnl=100, is_win=True))
        self.assertEqual(pipeline.portfolio.loss_streak, 0)
        self.assertEqual(pipeline.portfolio.win_streak, 1)

    def test_total_trades_increments(self):
        pipeline = QuantPipeline(QuantConfig.disabled())
        pipeline.on_trade_closed(TradeResult(pnl=100, is_win=True))
        pipeline.on_trade_closed(TradeResult(pnl=-50, is_win=False))
        self.assertEqual(pipeline.portfolio.total_trades, 2)


class TestQuantPipelineValidateStrategy(unittest.TestCase):
    def test_disabled_returns_pass(self):
        pipeline = QuantPipeline(QuantConfig.disabled())
        result = pipeline.validate_strategy(lambda data: [], [])
        self.assertTrue(result.passed)
        self.assertEqual(result.summary, "Walk-forward validation disabled")

    def test_enabled_runs_walk_forward(self):
        def strategy_fn(train, val, test):
            return [
                {"pnl": 100.0},
                {"pnl": 50.0},
                {"pnl": -20.0},
            ]

        cfg = QuantConfig(
            walk_forward=WalkForwardConfig(
                enabled=True,
                n_windows=3,
                train_ratio=0.6,
                val_ratio=0.2,
            ),
        )
        pipeline = QuantPipeline(cfg)
        data = list(range(300))
        result = pipeline.validate_strategy(strategy_fn, data)
        self.assertIsInstance(result, ValidationResult)
        self.assertIsNotNone(result.results)
        self.assertIn("Walk-forward", result.summary)


class TestQuantPipelinePortfolioState(unittest.TestCase):
    def test_update_portfolio(self):
        pipeline = QuantPipeline(QuantConfig.disabled())
        new_state = PortfolioState(
            balance=50000.0,
            win_streak=3,
            loss_streak=0,
        )
        pipeline.update_portfolio(new_state)
        self.assertEqual(pipeline.portfolio.balance, 50000.0)
        self.assertEqual(pipeline.portfolio.win_streak, 3)

    def test_empty_bars(self):
        pipeline = QuantPipeline(QuantConfig.disabled())
        signal = FakeSignal()
        decision = pipeline.pre_trade_check(signal, [], PortfolioState(balance=10000.0))
        self.assertEqual(decision.action, TradeAction.ACCEPT)


class TestQuantConfigModuleProperties(unittest.TestCase):
    def test_property_flags(self):
        cfg = QuantConfig()
        self.assertTrue(cfg.regime_enabled)
        self.assertTrue(cfg.correlation_enabled)
        self.assertTrue(cfg.position_sizing_enabled)
        self.assertFalse(cfg.walk_forward_enabled)

    def test_property_flags_reflect_subconfig(self):
        cfg = QuantConfig(regime=RegimeConfig(enabled=False))
        self.assertFalse(cfg.regime_enabled)
        self.assertTrue(cfg.correlation_enabled)
