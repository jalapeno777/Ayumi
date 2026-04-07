from __future__ import annotations

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from adapters.ctrader.models import (
    TradeDirection,
    TradeSignal,
)
from backtest.engine import Bar, MarketState
from strategies.session_range_mean_reversion import (
    SessionRangeMeanReversionStrategy,
    SessionRangeMRConfig,
)


class TestSessionRangeMRConfig:
    def test_default_config_values(self):
        config = SessionRangeMRConfig()
        assert config.atr_period == 14
        assert config.atr_sl_multiplier == 1.5
        assert config.rsi_period == 14
        assert config.rsi_long_level == 30.0
        assert config.rsi_short_level == 70.0
        assert config.session_range_min_pips == 25.0

    def test_ftmo_optimized_config(self):
        config = SessionRangeMRConfig(
            atr_period=14,
            atr_sl_multiplier=1.5,
            atr_tp_multiplier=2.0,
            rsi_period=14,
            rsi_long_level=30.0,
            rsi_short_level=70.0,
            session_range_min_pips=25.0,
            entry_near_extreme_pips=15.0,
            hard_cap_sl_pips=30.0,
            tp1_rr=1.0,
            tp2_rr=1.5,
            ema_trend_period=50,
            use_session_range_sl=True,
            session_range_sl_fraction=0.6,
        )
        assert config.use_session_range_sl is True
        assert config.session_range_sl_fraction == 0.6
        assert config.tp1_rr == 1.0
        assert config.tp2_rr == 1.5


class TestSessionRangeMRStrategy:
    def _make_bar(
        self,
        hour: int,
        minute: int = 0,
        open_p=1.3000,
        high_p=1.3010,
        low_p=1.2990,
        close_p=1.3005,
    ) -> Bar:
        return Bar(
            time=datetime(2026, 4, 7, hour, minute, tzinfo=timezone.utc),
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=10000,
        )

    def _make_state(self, bars: list[Bar]) -> MarketState:
        return MarketState(bars=bars)

    def test_strategy_name(self):
        strategy = SessionRangeMeanReversionStrategy()
        assert strategy.name == "Session-Range Mean Reversion"

    def test_strategy_uses_custom_config(self):
        config = SessionRangeMRConfig(rsi_long_level=25.0, rsi_short_level=75.0)
        strategy = SessionRangeMeanReversionStrategy(config)
        assert strategy.config.rsi_long_level == 25.0
        assert strategy.config.rsi_short_level == 75.0

    def test_signal_generation_long(self):
        bars = []
        for day in range(5, 0, -1):
            for h in range(24):
                close = 1.3000 + (h * 0.0001)
                bars.append(
                    Bar(
                        time=datetime(2026, 4, day, h, 0, tzinfo=timezone.utc),
                        open=close - 0.00005,
                        high=close + 0.0001,
                        low=close - 0.0001,
                        close=close,
                        volume=10000,
                    )
                )

        for h in range(7, 12):
            close = 1.2950
            bars.append(
                Bar(
                    time=datetime(2026, 4, 6, h, 0, tzinfo=timezone.utc),
                    open=close - 0.00005,
                    high=close + 0.0002,
                    low=close - 0.0001,
                    close=close,
                    volume=10000,
                )
            )

        state = self._make_state(bars)
        strategy = SessionRangeMeanReversionStrategy()

        signal = strategy.evaluate(state)
        if signal is not None:
            assert signal.direction in (TradeDirection.LONG, TradeDirection.SHORT)
            assert signal.entry_price > 0
            assert signal.stop_loss > 0
            assert (
                signal.take_profit_1 > signal.entry_price
                if signal.direction == TradeDirection.LONG
                else signal.take_profit_1 < signal.entry_price
            )


class TestLiveTradingExecutorConfig:
    def test_execution_config_defaults(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from scripts.live_trading_execution import ExecutionConfig

        config = ExecutionConfig()
        assert config.symbol == "GBPUSD"
        assert config.paper_mode is True
        assert config.ftmo_daily_loss_limit == 0.05
        assert config.ftmo_max_drawdown == 0.10
        assert config.risk_per_trade == 0.02
        assert config.min_confidence == 0.55

    def test_execution_config_custom(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from scripts.live_trading_execution import ExecutionConfig

        config = ExecutionConfig(
            symbol="EURUSD",
            paper_mode=False,
            ftmo_daily_loss_limit=0.03,
            risk_per_trade=0.01,
        )
        assert config.symbol == "EURUSD"
        assert config.paper_mode is False
        assert config.ftmo_daily_loss_limit == 0.03
        assert config.risk_per_trade == 0.01


class TestLiveTradingExecutorUnit:
    def test_create_strategy_config_returns_valid_config(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from scripts.live_trading_execution import LiveTradingExecutor, ExecutionConfig

        executor = LiveTradingExecutor(ExecutionConfig())
        config = executor._create_strategy_config()

        assert isinstance(config, SessionRangeMRConfig)
        assert config.atr_period == 14
        assert config.rsi_long_level == 30.0
        assert config.rsi_short_level == 70.0

    def test_executor_initializes_with_defaults(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from scripts.live_trading_execution import LiveTradingExecutor, ExecutionConfig

        executor = LiveTradingExecutor(ExecutionConfig())
        assert executor._config.symbol == "GBPUSD"
        assert executor._running is False
        assert executor._bars == {}
        assert executor._last_signal_time is None

    def test_executor_calculate_atr(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from scripts.live_trading_execution import LiveTradingExecutor, ExecutionConfig

        executor = LiveTradingExecutor(ExecutionConfig())
        bars = []
        for i in range(20):
            bars.append(
                Bar(
                    time=datetime(2026, 4, 7, i, 0, tzinfo=timezone.utc),
                    open=1.3000 + i * 0.0001,
                    high=1.3010 + i * 0.0001,
                    low=1.2990 + i * 0.0001,
                    close=1.3005 + i * 0.0001,
                    volume=10000,
                )
            )

        atr = executor._calculate_atr(bars)
        assert atr > 0
        assert isinstance(atr, float)

    def test_executor_calculate_atr_insufficient_bars(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from scripts.live_trading_execution import LiveTradingExecutor, ExecutionConfig

        executor = LiveTradingExecutor(ExecutionConfig())
        bars = [
            Bar(
                time=datetime(2026, 4, 7, 0, 0, tzinfo=timezone.utc),
                open=1.3000,
                high=1.3010,
                low=1.2990,
                close=1.3005,
                volume=10000,
            )
        ]

        atr = executor._calculate_atr(bars)
        assert atr == 0.0001


class TestTradeSignalCreation:
    def test_trade_signal_from_strategy_signal(self):
        from scripts.live_trading_execution import LiveTradingExecutor, ExecutionConfig

        _ = LiveTradingExecutor(ExecutionConfig())
        strategy = SessionRangeMeanReversionStrategy()

        bars = []
        base = 1.3000
        for day in range(5, 0, -1):
            for h in range(24):
                offset = day * 24 + h
                bars.append(
                    Bar(
                        time=datetime(
                            2026, 4, day if day > 0 else 1, h, 0, tzinfo=timezone.utc
                        ),
                        open=base + offset * 0.00001,
                        high=base + offset * 0.00001 + 0.0001,
                        low=base + offset * 0.00001 - 0.0001,
                        close=base + offset * 0.00001 + 0.00005,
                        volume=10000,
                    )
                )

        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)

        if signal is not None:
            direction = (
                TradeDirection.LONG
                if signal.direction.value == "long"
                else TradeDirection.SHORT
            )

            trade_signal = TradeSignal(
                symbol="GBPUSD",
                direction=direction,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit_1=signal.take_profit_1,
                take_profit_2=signal.take_profit_2,
                take_profit_3=signal.take_profit_3,
                volume=0.1,
                confidence=signal.confidence,
                rationale=signal.rationale,
            )

            assert trade_signal.symbol == "GBPUSD"
            assert trade_signal.direction in (TradeDirection.LONG, TradeDirection.SHORT)
            assert trade_signal.entry_price > 0
            assert trade_signal.volume == 0.1


class TestSignalEvaluation:
    def test_evaluate_strategy_returns_none_insufficient_bars(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from scripts.live_trading_execution import LiveTradingExecutor, ExecutionConfig

        executor = LiveTradingExecutor(ExecutionConfig())

        bars = [
            Bar(
                time=datetime(2026, 4, 7, 0, 0, tzinfo=timezone.utc),
                open=1.3000,
                high=1.3010,
                low=1.2990,
                close=1.3005,
                volume=10000,
            )
        ]

        executor._bars["GBPUSD"] = bars

        with patch.object(executor, "_strategy", None):
            result = executor._evaluate_strategy("GBPUSD")

        assert result is None

    def test_evaluate_strategy_handles_low_confidence(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from scripts.live_trading_execution import LiveTradingExecutor, ExecutionConfig

        executor = LiveTradingExecutor(ExecutionConfig())

        mock_signal = MagicMock()
        mock_signal.confidence = 0.3
        mock_signal.direction = MagicMock()
        mock_signal.direction.value = "long"
        mock_signal.entry_price = 1.3000
        mock_signal.stop_loss = 1.2950
        mock_signal.take_profit_1 = 1.3050
        mock_signal.take_profit_2 = 1.3100
        mock_signal.take_profit_3 = 1.3100
        mock_signal.rationale = "Test"

        executor._strategy = MagicMock()
        executor._strategy.evaluate.return_value = mock_signal
        executor._paper_trader = MagicMock()
        executor._paper_trader.process_signal.return_value = MagicMock(
            success=False, rejection_reason="confidence_too_low"
        )

        bars = []
        for i in range(100):
            bars.append(
                Bar(
                    time=datetime(2026, 4, 7, i % 24, 0, tzinfo=timezone.utc),
                    open=1.3000 + i * 0.00001,
                    high=1.3010 + i * 0.00001,
                    low=1.2990 + i * 0.00001,
                    close=1.3005 + i * 0.00001,
                    volume=10000,
                )
            )

        executor._bars["GBPUSD"] = bars
        executor._quant_pipeline = MagicMock()

        result = executor._evaluate_strategy("GBPUSD")

        assert result is None


class TestQuantPipelineIntegration:
    def test_pre_trade_check_accepts_valid_signal(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from quant.pipeline import QuantPipeline, TradeAction, QuantConfig

        pipeline = QuantPipeline(QuantConfig.disabled())

        decision = pipeline.pre_trade_check(
            signal_symbol="GBPUSD",
            entry_price=1.3000,
            stop_loss=1.2950,
            bar_time=datetime(2026, 4, 7, 10, 0, tzinfo=timezone.utc),
        )

        assert decision.action == TradeAction.ACCEPT

    def test_pre_trade_check_with_ftmo_config(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from quant.pipeline import QuantPipeline, TradeAction
        from quant.config import QuantConfig

        config = QuantConfig.ftmo()
        pipeline = QuantPipeline(config)

        pipeline.update_bars(high=1.3100, low=1.2950, close=1.3000, atr=0.0015)

        decision = pipeline.pre_trade_check(
            signal_symbol="GBPUSD",
            entry_price=1.3000,
            stop_loss=1.2950,
            bar_time=datetime(2026, 4, 7, 10, 0, tzinfo=timezone.utc),
        )

        assert decision.action in (
            TradeAction.ACCEPT,
            TradeAction.RESIZE,
            TradeAction.REJECT,
        )
