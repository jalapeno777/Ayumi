from __future__ import annotations

import pytest
from backtest.engine import Bar
from backtest.strategies import ISignalStrategy
from quant.config import (
    CorrelationConfig,
    PositionSizingConfig,
    QuantConfig,
    RegimeConfig,
    RegimeFilterMode,
    SizingMode,
    WalkForwardConfig,
)
from quant.pipeline import (
    PortfolioState,
    QuantPipeline,
    TradeAction,
    TradeDecision,
    ValidationResult,
)


class TestQuantConfig:
    def test_default_config_has_all_modules_enabled(self):
        config = QuantConfig()
        assert config.regime.enabled is True
        assert config.correlation.enabled is True
        assert config.position_sizing.enabled is True
        assert config.walk_forward.enabled is True

    def test_disabled_config(self):
        config = QuantConfig.disabled()
        assert config.regime.enabled is False
        assert config.correlation.enabled is False
        assert config.position_sizing.enabled is False
        assert config.walk_forward.enabled is False

    def test_paper_trading_preset(self):
        config = QuantConfig.paper_trading()
        assert config.regime.enabled is True
        assert config.regime.filter_mode == RegimeFilterMode.FILTER_HIGH_AND_EXTREME
        assert config.walk_forward.enabled is False
        assert config.position_sizing.mode == SizingMode.FIXED_FRACTIONAL
        assert config.position_sizing.risk_pct == 0.5

    def test_ftmo_preset(self):
        config = QuantConfig.ftmo()
        assert config.regime.enabled is True
        assert config.regime.filter_mode == RegimeFilterMode.FILTER_EXTREME
        assert config.position_sizing.mode == SizingMode.DYNAMIC
        assert config.walk_forward.enabled is True
        assert config.walk_forward.n_windows == 5

    def test_frozen_dataclass(self):
        config = QuantConfig()
        with pytest.raises(AttributeError):
            config.regime = RegimeConfig(enabled=False)

    def test_regime_config_defaults(self):
        cfg = RegimeConfig()
        assert cfg.filter_mode == RegimeFilterMode.FILTER_EXTREME
        assert cfg.min_confidence == 0.4
        assert cfg.atr_lookback == 50

    def test_correlation_config_defaults(self):
        cfg = CorrelationConfig()
        assert cfg.window == 50
        assert cfg.threshold == 0.7
        assert len(cfg.pairs) == 7

    def test_position_sizing_config_defaults(self):
        cfg = PositionSizingConfig()
        assert cfg.mode == SizingMode.FIXED_FRACTIONAL
        assert cfg.risk_pct == 1.0
        assert cfg.dynamic_min_multiplier == 0.5
        assert cfg.dynamic_max_multiplier == 1.5

    def test_walk_forward_config_defaults(self):
        cfg = WalkForwardConfig()
        assert cfg.n_windows == 3
        assert cfg.train_ratio == 0.7


class TestQuantPipeline:
    def _make_pipeline(self, config: QuantConfig | None = None) -> QuantPipeline:
        return QuantPipeline(config or QuantConfig())

    def test_accepts_trade_with_good_regime(self):
        pipeline = self._make_pipeline()
        for i in range(60):
            pipeline.update_bars(
                high=1.1 + i * 0.001,
                low=1.09 + i * 0.001,
                close=1.095 + i * 0.001,
                atr=0.005 + (i % 10) * 0.0001,
            )
        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.action in (TradeAction.ACCEPT, TradeAction.RESIZE)
        assert decision.lot_size is not None
        assert decision.lot_size > 0

    def test_rejects_trade_when_regime_confidence_low(self):
        config = QuantConfig(
            regime=RegimeConfig(
                enabled=True,
                filter_mode=RegimeFilterMode.FILTER_EXTREME,
                min_confidence=0.99,
            ),
        )
        pipeline = self._make_pipeline(config)
        for i in range(60):
            pipeline.update_bars(
                high=1.1,
                low=1.09,
                close=1.095,
                atr=0.001,
            )
        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.action == TradeAction.REJECT
        assert "Regime confidence" in decision.reject_reason

    def test_rejects_when_stop_loss_equals_entry(self):
        pipeline = self._make_pipeline()
        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.1000,
        )
        assert decision.action == TradeAction.REJECT

    def test_returns_lot_size_with_fixed_fractional(self):
        pipeline = self._make_pipeline()
        pipeline.portfolio.balance = 100_000.0
        for i in range(60):
            pipeline.update_bars(
                high=1.1 + i * 0.001,
                low=1.09 + i * 0.001,
                close=1.095 + i * 0.001,
                atr=0.005,
            )
        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.lot_size is not None
        assert decision.lot_size > 0

    def test_on_trade_closed_updates_streaks(self):
        pipeline = self._make_pipeline()
        pipeline.on_trade_closed(100.0)
        assert pipeline.portfolio.win_streak == 1
        assert pipeline.portfolio.loss_streak == 0
        assert pipeline.portfolio.total_wins == 1

        pipeline.on_trade_closed(-50.0)
        assert pipeline.portfolio.win_streak == 0
        assert pipeline.portfolio.loss_streak == 1
        assert pipeline.portfolio.total_losses == 1

    def test_on_trade_closed_updates_avg_win_loss(self):
        pipeline = self._make_pipeline()
        pipeline.on_trade_closed(100.0)
        assert pipeline.portfolio.avg_win == 100.0

        pipeline.on_trade_closed(200.0)
        assert pipeline.portfolio.avg_win == 150.0

        pipeline.on_trade_closed(-50.0)
        assert pipeline.portfolio.avg_loss == 50.0

    def test_validate_strategy_disabled(self):
        config = QuantConfig(walk_forward=WalkForwardConfig(enabled=False))
        pipeline = self._make_pipeline(config)

        class NoSignalsStrategy(ISignalStrategy):
            @property
            def name(self) -> str:
                return "No Signals Strategy"

            def evaluate(self, state):
                return None

        from datetime import datetime, timedelta

        strategy = NoSignalsStrategy()
        base_time = datetime(2024, 1, 1, 10, 0, 0)
        bars = [
            Bar(
                time=base_time + timedelta(hours=i),
                open=1.0 + i * 0.001,
                high=1.0 + i * 0.001 + 0.001,
                low=1.0 + i * 0.001,
                close=1.0 + i * 0.001,
                volume=1000.0,
            )
            for i in range(100)
        ]
        result = pipeline.validate_strategy(strategy=strategy, bars=bars)
        assert result.go_nogo is True
        assert result.walk_forward_passed is True
        assert len(result.per_window_metrics) == 0

    def test_portfolio_state_defaults(self):
        state = PortfolioState()
        assert state.balance == 100_000.0
        assert state.open_positions == {}
        assert state.win_streak == 0

    def test_disabled_config_accepts_all_trades(self):
        config = QuantConfig.disabled()
        pipeline = self._make_pipeline(config)
        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.action == TradeAction.ACCEPT
        assert decision.lot_size is None

    def test_dynamic_sizing_applies_multiplier(self):
        config = QuantConfig(
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.DYNAMIC,
                risk_pct=1.0,
            ),
        )
        pipeline = self._make_pipeline(config)
        pipeline.portfolio.balance = 100_000.0

        for i in range(60):
            pipeline.update_bars(
                high=1.1 + i * 0.001,
                low=1.09 + i * 0.001,
                close=1.095 + i * 0.001,
                atr=0.005,
            )

        pipeline.on_trade_closed(100.0)
        pipeline.on_trade_closed(100.0)

        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.action == TradeAction.RESIZE
        assert decision.lot_size is not None
        assert decision.sizing_mode == "dynamic"


class TestTradeDecision:
    def test_frozen(self):
        decision = TradeDecision(
            action=TradeAction.ACCEPT,
            lot_size=0.1,
        )
        with pytest.raises(AttributeError):
            decision.lot_size = 0.2

    def test_reject_decision(self):
        decision = TradeDecision(
            action=TradeAction.REJECT,
            reject_reason="test reason",
        )
        assert decision.action == TradeAction.REJECT
        assert decision.reject_reason == "test reason"


class TestValidationResult:
    def test_frozen(self):
        result = ValidationResult(go_nogo=True, walk_forward_passed=True)
        with pytest.raises(AttributeError):
            result.go_nogo = False
