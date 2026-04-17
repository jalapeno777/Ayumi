from __future__ import annotations

from typing import TYPE_CHECKING

from core.config import BacktestConfig, BacktestMetrics
from core.spread import SpreadModel
from core.types import Bar, MarketState, SimulatedTrade, StrategySignal

from engine.base import EngineCore, determine_session
from engine.mixins import CombinedSignalMixin, CombineMethod, ProgressiveSLMixin
from engine.trade_mgmt import TradeManagementMixin

if TYPE_CHECKING:
    from core.protocol import IStrategy

    try:
        from backtest.trade_management import TradeManagementConfig
    except ImportError:
        TradeManagementConfig = None

    try:
        from quant.config import QuantConfig
        from quant.pipeline import QuantPipeline
    except ImportError:
        QuantConfig = None
        QuantPipeline = None


class BacktestEngine(
    EngineCore, ProgressiveSLMixin, TradeManagementMixin, CombinedSignalMixin
):
    def __init__(
        self,
        config: BacktestConfig,
        strategies: list["IStrategy"],
        trade_mgmt_config: "TradeManagementConfig | None" = None,
        quant_config: "QuantConfig | None" = None,
        spread_model: SpreadModel | None = None,
    ):
        EngineCore.__init__(self, config, spread_model)
        ProgressiveSLMixin.__init__(self, config)
        TradeManagementMixin.__init__(self, trade_mgmt_config)
        self.strategies = strategies
        self._quant_pipeline = None
        if quant_config is not None:
            from quant.config import QuantConfig as QC
            from quant.pipeline import QuantPipeline

            if not isinstance(quant_config, QC):
                raise TypeError(
                    f"Expected QuantConfig, got {type(quant_config).__name__}"
                )
            self._quant_pipeline = QuantPipeline(quant_config)

    def run_single(self, strategy: "IStrategy", bars: list[Bar]) -> BacktestMetrics:
        if len(bars) < self.config.min_bars_before_signal:
            raise ValueError(f"Need at least {self.config.min_bars_before_signal} bars")

        self._reset()
        trades: list[SimulatedTrade] = []
        equity_curve = [self.balance]
        open_trades: list[SimulatedTrade] = []

        for i in range(len(bars)):
            bar = bars[i]
            self._update_daily_tracking(bar.time)

            if self.balance <= 0:
                break
            if self._is_max_drawdown_breached():
                break
            if self._is_max_daily_loss_breached():
                continue

            self._check_open_trades(open_trades, bar, i, trades, equity_curve)

            if (
                len(open_trades) < self.config.max_open_trades
                and i >= self.config.min_bars_before_signal
            ):
                state = MarketState(
                    bars=bars[: i + 1],
                    current_session=determine_session(bar.time),
                )
                signal = strategy.evaluate(state)

                if signal is not None and self._passes_filters(signal):
                    trade = self._open_trade(signal, bar, i)
                    if trade is not None:
                        open_trades.append(trade)
                    else:
                        self.rejected_signals += 1

            equity_curve.append(self.balance)

        trades.extend(
            self._close_all_open_trades(
                open_trades, len(bars) - 1, bars[-1].time, bars[-1].close
            )
        )
        return self._calculate_metrics(trades, equity_curve)

    def run_all(self, bars: list[Bar]) -> dict[str, BacktestMetrics]:
        results: dict[str, BacktestMetrics] = {}
        for strategy in self.strategies:
            metrics = self.run_single(strategy, bars)
            results[strategy.name] = metrics
        return results

    def run_combined(
        self,
        bars: list[Bar],
        method: CombineMethod = CombineMethod.WEIGHTED,
    ) -> BacktestMetrics:
        if len(bars) < self.config.min_bars_before_signal:
            raise ValueError(f"Need at least {self.config.min_bars_before_signal} bars")

        self._reset()
        trades: list[SimulatedTrade] = []
        equity_curve = [self.balance]
        open_trades: list[SimulatedTrade] = []

        for i in range(len(bars)):
            bar = bars[i]
            self._update_daily_tracking(bar.time)

            if self.balance <= 0:
                break
            if self._is_max_drawdown_breached():
                break
            if self._is_max_daily_loss_breached():
                continue

            self._check_open_trades(open_trades, bar, i, trades, equity_curve)

            if (
                len(open_trades) < self.config.max_open_trades
                and i >= self.config.min_bars_before_signal
            ):
                state = MarketState(
                    bars=bars[: i + 1],
                    current_session=determine_session(bar.time),
                )

                all_signals: list[StrategySignal] = []
                for strategy in self.strategies:
                    signal = strategy.evaluate(state)
                    if signal is not None:
                        all_signals.append(signal)

                if all_signals:
                    combined = self._combine_signals(
                        all_signals,
                        method=method,
                        min_confidence=self.config.min_confidence,
                    )
                    if combined is not None:
                        trade = self._open_trade(combined, bar, i)
                        if trade is not None:
                            open_trades.append(trade)
                        else:
                            self.rejected_signals += 1
                    else:
                        self.rejected_signals += 1

            equity_curve.append(self.balance)

        trades.extend(
            self._close_all_open_trades(
                open_trades, len(bars) - 1, bars[-1].time, bars[-1].close
            )
        )
        return self._calculate_metrics(trades, equity_curve)

    def _passes_filters(self, signal: StrategySignal) -> bool:
        return signal.confidence >= self.config.min_confidence
