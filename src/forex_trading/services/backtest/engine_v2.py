"""Composed BacktestEngine using mixin-based architecture.

BacktestEngine(EngineCore, ProgressiveSLMixin, CombinedSignalMixin, TradeManagementMixin)

Provides:
  run_single(strategy, bars, pair) -> BacktestMetrics
  run_all(strategies, bars, pair) -> dict[str, BacktestMetrics]
  run_combined(strategies, bars, pair, method) -> BacktestMetrics
  run_walk_forward(strategy, bars, pair, wf_config) -> WalkForwardResults
"""

from __future__ import annotations

import inspect
import warnings
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .engine_core.base import BacktestMetrics, EngineCore, Position
from .execution import ExecutionConfig
from .mixins import (
    CombinedSignalMixin,
    ProgressiveSLMixin,
    ProgressiveSLConfig,
    SignalCombineMethod,
)
from .strategies import Strategy
from .trade_mgmt import TradeManagementMixin


@dataclass
class WalkForwardConfig:
    train_bars: int = 63
    test_bars: int = 126
    step_bars: int = 21


@dataclass
class WalkForwardWindow:
    window_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    is_metrics: Optional[BacktestMetrics] = None
    oos_metrics: Optional[BacktestMetrics] = None


@dataclass
class WalkForwardResults:
    windows: list[WalkForwardWindow] = field(default_factory=list)
    combined_oos_metrics: Optional[BacktestMetrics] = None

    @property
    def oos_results(self) -> list[Optional[BacktestMetrics]]:
        return [w.oos_metrics for w in self.windows]


class BacktestEngine(
    EngineCore, ProgressiveSLMixin, CombinedSignalMixin, TradeManagementMixin
):
    def __init__(
        self,
        starting_balance: float = 10_000.0,
        prop_firm_config=None,
        execution_config: Optional[ExecutionConfig] = None,
        risk_free_rate: float = 0.0,
        risk_pct: float = 0.02,
        sizing_method=None,
        sl_atr_multiplier: float = 1.5,
        tp_atr_multiplier: float = 2.0,
        sharpe_annualization_factor: float = 252**0.5,
        sl_config: Optional[ProgressiveSLConfig] = None,
        signal_method: SignalCombineMethod = SignalCombineMethod.WEIGHTED,
        signal_weights: Optional[dict[str, float]] = None,
        use_progressive_sl: bool = False,
    ):
        EngineCore.__init__(
            self,
            starting_balance=starting_balance,
            prop_firm_config=prop_firm_config,
            execution_config=execution_config,
            risk_free_rate=risk_free_rate,
            risk_pct=risk_pct,
            sizing_method=sizing_method,
            sl_atr_multiplier=sl_atr_multiplier,
            tp_atr_multiplier=tp_atr_multiplier,
            sharpe_annualization_factor=sharpe_annualization_factor,
        )
        ProgressiveSLMixin.__init__(self, sl_config=sl_config)
        CombinedSignalMixin.__init__(self, method=signal_method, weights=signal_weights)
        TradeManagementMixin.__init__(self)
        self._use_progressive_sl = use_progressive_sl

    def run_single(
        self,
        strategy: Strategy,
        bars: pd.DataFrame,
        pair: str = "EURUSD",
    ) -> BacktestMetrics:
        self._reset()

        if not strategy.validate_data(bars):
            raise ValueError("Data missing required columns")

        signals = self._generate_signals(strategy, bars, pair)
        if len(signals) != len(bars):
            warnings.warn(
                f"Signal length ({len(signals)}) != data length ({len(bars)}). Truncating."
            )

        for i in range(1, len(bars)):
            current_bar = bars.iloc[i]
            timestamp = pd.Timestamp(current_bar.name)

            unrealized = self._calculate_unrealized_pnl(current_bar)
            equity = self.starting_balance + self.realized_pnl + unrealized

            self.prop_firm.update_daily_drawdown(equity, timestamp)

            if self._is_max_drawdown_breached():
                self._close_all_open_trades(current_bar, timestamp, force=True)
                self.equity_curve.append(self.starting_balance + self.realized_pnl)
                break

            self._update_daily_tracking(timestamp)

            if self._use_progressive_sl:
                exit_price = self._check_progressive_sl_tp(current_bar, timestamp, pair)
                if exit_price is not None:
                    pos = self._get_open_position(pair)
                    if pos is not None:
                        self._close_trade(
                            pos, i, timestamp, exit_price, reason="progressive_sl_tp"
                        )
                        self._clear_tp_stage(id(pos))
            else:
                self.check_sl_tp(current_bar, timestamp)

            if pd.notna(signals.iloc[i]) and signals.iloc[i] != 0:
                signal = float(signals.iloc[i])

                open_pos = self._get_open_position(pair)
                if open_pos is not None:
                    if (open_pos.direction == "long" and signal < 0) or (
                        open_pos.direction == "short" and signal > 0
                    ):
                        self._close_trade(
                            open_pos,
                            i,
                            timestamp,
                            float(current_bar["close"]),
                            reason="signal_reversal",
                        )

                if not self._has_open_position(pair):
                    self._try_open_position(
                        strategy, bars, current_bar, i, signal, pair, equity
                    )

            unrealized = self._calculate_unrealized_pnl(current_bar)
            equity = self.starting_balance + self.realized_pnl + unrealized
            self.equity_curve.append(equity)

        if self.positions:
            last_bar = bars.iloc[-1]
            last_ts = pd.Timestamp(bars.index[-1])
            self._close_all_open_trades(last_bar, last_ts, force=True)
            self.equity_curve.append(self.starting_balance + self.realized_pnl)

        return self._calculate_metrics(self.trades, self.equity_curve)

    def run_all(
        self,
        strategies: list[Strategy],
        bars: pd.DataFrame,
        pair: str = "EURUSD",
    ) -> dict[str, BacktestMetrics]:
        results: dict[str, BacktestMetrics] = {}
        for strategy in strategies:
            results[strategy.name] = self.run_single(strategy, bars, pair)
        return results

    def run_combined(
        self,
        strategies: list[Strategy],
        bars: pd.DataFrame,
        pair: str = "EURUSD",
        method: Optional[SignalCombineMethod] = None,
    ) -> BacktestMetrics:
        if method is not None:
            self._combine_method = method

        signal_map: dict[str, pd.Series] = {}
        for strategy in strategies:
            signal_map[strategy.name] = self._generate_signals(strategy, bars, pair)

        combined_signal = self.combine_signals(signal_map)

        return self._run_with_combined_signal(combined_signal, bars, pair)

    def run_walk_forward(
        self,
        strategy: Strategy,
        bars: pd.DataFrame,
        pair: str = "EURUSD",
        wf_config: Optional[WalkForwardConfig] = None,
    ) -> WalkForwardResults:
        config = wf_config or WalkForwardConfig()
        windows: list[WalkForwardWindow] = []
        all_oos_trades: list[dict] = []
        all_oos_equity: list[float] = [self.starting_balance]

        train_start = 0
        window_idx = 0

        while train_start + config.train_bars + config.test_bars <= len(bars):
            train_end = train_start + config.train_bars
            test_start = train_end
            test_end = test_start + config.test_bars

            train_data = bars.iloc[train_start:train_end]
            test_data = bars.iloc[test_start:test_end]

            self._reset()
            self.run_single(strategy, train_data, pair)
            is_metrics = self._calculate_metrics(self.trades, self.equity_curve)

            saved_pnl = self.realized_pnl
            self._reset()
            self.realized_pnl = saved_pnl
            oos_metrics = self.run_single(strategy, test_data, pair)

            all_oos_trades.extend(self.trades)
            if len(self.equity_curve) > 1:
                all_oos_equity.extend(self.equity_curve[1:])

            windows.append(
                WalkForwardWindow(
                    window_index=window_idx,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    is_metrics=is_metrics,
                    oos_metrics=oos_metrics,
                )
            )

            train_start += config.step_bars
            window_idx += 1

        combined_oos = self._calculate_metrics(all_oos_trades, all_oos_equity)
        combined_oos.profit_factor = min(combined_oos.profit_factor, 10.0)

        return WalkForwardResults(
            windows=windows,
            combined_oos_metrics=combined_oos,
        )

    def _generate_signals(
        self, strategy: Strategy, bars: pd.DataFrame, pair: str
    ) -> pd.Series:
        sig = inspect.signature(strategy.generate_signals)
        params = list(sig.parameters.keys())
        if len(params) > 1 and params[1] in ("pair", "instrument"):
            return strategy.generate_signals(bars, pair)
        return strategy.generate_signals(bars)

    def _try_open_position(
        self,
        strategy: Strategy,
        bars: pd.DataFrame,
        current_bar: pd.Series,
        bar_index: int,
        signal: float,
        pair: str,
        equity: float,
    ) -> None:
        signal_price = float(current_bar["close"])
        sl_tp = strategy.generate_sl_tp(
            bars.iloc[: bar_index + 1],
            signal,
            signal_price,
            atr_period=14,
            sl_atr_multiplier=self.sl_atr_multiplier,
            tp_atr_multiplier=self.tp_atr_multiplier,
        )

        stop_loss = sl_tp.stop_loss if sl_tp else None
        take_profit = sl_tp.take_profit if sl_tp else None

        if sl_tp and stop_loss is not None:
            lot_size = self._calculate_open_trade_lot_size(
                signal_price, stop_loss, equity, pair
            )
        else:
            lot_size = (
                self.executor.config.default_lot_size if self.executor.config else 0.1
            )

        timestamp = pd.Timestamp(current_bar.name)
        can_open, _reason = self.prop_firm.state.can_open_position(
            lot_size=lot_size, pair=pair, timestamp=timestamp
        )

        if can_open:
            pos = self._open_trade(signal, current_bar, bar_index, lot_size, pair)
            if pos is not None:
                pos.stop_loss = stop_loss
                pos.take_profit = take_profit

    def _run_with_combined_signal(
        self,
        combined_signal: pd.Series,
        bars: pd.DataFrame,
        pair: str,
    ) -> BacktestMetrics:
        self._reset()

        for i in range(1, len(bars)):
            current_bar = bars.iloc[i]
            timestamp = pd.Timestamp(current_bar.name)

            unrealized = self._calculate_unrealized_pnl(current_bar)
            equity = self.starting_balance + self.realized_pnl + unrealized

            self.prop_firm.update_daily_drawdown(equity, timestamp)

            if self._is_max_drawdown_breached():
                self._close_all_open_trades(current_bar, timestamp, force=True)
                self.equity_curve.append(self.starting_balance + self.realized_pnl)
                break

            self._update_daily_tracking(timestamp)
            self.check_sl_tp(current_bar, timestamp)

            if pd.notna(combined_signal.iloc[i]) and combined_signal.iloc[i] != 0:
                signal = float(combined_signal.iloc[i])

                open_pos = self._get_open_position(pair)
                if open_pos is not None:
                    if (open_pos.direction == "long" and signal < 0) or (
                        open_pos.direction == "short" and signal > 0
                    ):
                        self._close_trade(
                            open_pos,
                            i,
                            timestamp,
                            float(current_bar["close"]),
                            reason="signal_reversal",
                        )

                if not self._has_open_position(pair):
                    signal_price = float(current_bar["close"])
                    timestamp = pd.Timestamp(current_bar.name)
                    lot_size = (
                        self.executor.config.default_lot_size
                        if self.executor.config
                        else 0.1
                    )

                    can_open, _reason = self.prop_firm.state.can_open_position(
                        lot_size=lot_size, pair=pair, timestamp=timestamp
                    )

                    if can_open:
                        pos = self._open_trade(signal, current_bar, i, lot_size, pair)

            unrealized = self._calculate_unrealized_pnl(current_bar)
            equity = self.starting_balance + self.realized_pnl + unrealized
            self.equity_curve.append(equity)

        if self.positions:
            last_bar = bars.iloc[-1]
            last_ts = pd.Timestamp(bars.index[-1])
            self._close_all_open_trades(last_bar, last_ts, force=True)
            self.equity_curve.append(self.starting_balance + self.realized_pnl)

        return self._calculate_metrics(self.trades, self.equity_curve)
