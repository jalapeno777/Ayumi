"""EngineCore — shared backtest engine logic extracted into a reusable base class.

All backtest engine variants inherit from this to avoid duplicating
reset, metrics, trade lifecycle, drawdown, and daily-tracking logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from ..execution import ExecutionSimulator, ExecutionConfig
from ..prop_firm_rules import PropFirmRuleEngine, PropFirmConfig
from ..strategies import Strategy, StopLossTakeProfit
from ...risk.position_sizing import SizingMethod, FixedFractional


@dataclass
class BacktestMetrics:
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    avg_trade_duration: float = 0.0


@dataclass
class Position:
    entry_time: pd.Timestamp
    entry_price: float
    direction: str
    lots: float
    pair: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class EngineCore:
    """Reusable base class for backtest engines.

    Subclasses override ``run()`` but delegate all shared operations
    (reset, metrics, trade open/close, drawdown checks, daily tracking)
    to this class.
    """

    def __init__(
        self,
        starting_balance: float = 10_000.0,
        prop_firm_config: Optional[PropFirmConfig] = None,
        execution_config: Optional[ExecutionConfig] = None,
        risk_free_rate: float = 0.0,
        risk_pct: float = 0.02,
        sizing_method: Optional[SizingMethod] = None,
        sl_atr_multiplier: float = 1.5,
        tp_atr_multiplier: float = 2.0,
        sharpe_annualization_factor: float = np.sqrt(252),
    ):
        self.starting_balance = starting_balance
        self.risk_free_rate = risk_free_rate
        self.risk_pct = risk_pct
        self.sl_atr_multiplier = sl_atr_multiplier
        self.tp_atr_multiplier = tp_atr_multiplier
        self.sharpe_annualization_factor = sharpe_annualization_factor

        self.prop_firm = PropFirmRuleEngine(
            prop_firm_config or PropFirmConfig(),
            starting_balance,
        )
        self.executor = ExecutionSimulator(execution_config or ExecutionConfig())
        self.sizing_method = sizing_method or FixedFractional()

        self._reset()

    def _reset(self) -> None:
        self.positions: list[Position] = []
        self.equity_curve: list[float] = [self.starting_balance]
        self.realized_pnl: float = 0.0
        self.trades: list[dict] = []
        self._current_daily_pnl: float = 0.0
        self._current_day: Optional[pd.Timestamp] = None

    def _calculate_metrics(
        self, trades: list[dict], equity_curve: list[float]
    ) -> BacktestMetrics:
        equity_series = pd.Series(equity_curve, index=pd.RangeIndex(len(equity_curve)))
        daily_returns = equity_series.pct_change().dropna()

        total_return = (
            (equity_curve[-1] - self.starting_balance) / self.starting_balance
            if self.starting_balance != 0
            else 0.0
        )

        sharpe_ratio = self._calculate_sharpe_ratio(daily_returns)
        max_dd, max_dd_duration = self._calculate_max_drawdown(equity_series)

        wins = [t["pnl"] for t in trades if t["pnl"] > 0]
        losses = [abs(t["pnl"]) for t in trades if t["pnl"] < 0]
        win_rate = len(wins) / len(trades) if trades else 0.0
        if losses:
            profit_factor = sum(wins) / sum(losses)
        elif wins:
            profit_factor = 10.0
        else:
            profit_factor = 0.0

        avg_duration = (
            float(np.mean([t["holding_hours"] for t in trades])) if trades else 0.0
        )

        return BacktestMetrics(
            total_return=total_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_dd,
            max_drawdown_duration=max_dd_duration,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=len(trades),
            avg_trade_duration=avg_duration,
        )

    def _calculate_sharpe_ratio(self, equity_curve: list[float] | pd.Series) -> float:
        if isinstance(equity_curve, list):
            equity_curve = pd.Series(equity_curve)
        returns = equity_curve.pct_change().dropna()
        if len(returns) < 2:
            return 0.0
        excess_returns = returns - self.risk_free_rate / 252
        std = excess_returns.std()
        if std == 0:
            return 0.0
        return float(self.sharpe_annualization_factor * excess_returns.mean() / std)

    def _get_pip_value(self, price: float, pair: str = "EURUSD") -> float:
        return self.executor.calculate_pip_value(pair, lot_size=1.0)

    def _update_daily_tracking(self, bar_time: pd.Timestamp) -> None:
        day = bar_time.normalize()
        if self._current_day is not None and day != self._current_day:
            self._current_daily_pnl = 0.0
        self._current_day = day

    def _is_max_drawdown_breached(self) -> bool:
        return self.prop_firm.check_drawdown_violation()

    def _is_max_daily_loss_breached(self) -> bool:
        return (
            self.prop_firm.state.daily_drawdown
            > self.prop_firm.state.config.max_daily_drawdown_pct
        )

    def _close_trade(
        self,
        trade: Position,
        bar_index: int,
        exit_time: pd.Timestamp,
        exit_price: float,
        reason: str = "close",
    ) -> float:
        if trade.direction == "long":
            pnl = (exit_price - trade.entry_price) * trade.lots * 100_000
        else:
            pnl = (trade.entry_price - exit_price) * trade.lots * 100_000

        spread_cost = self.executor._calculate_spread(trade.pair)
        if trade.direction == "long":
            pnl -= spread_cost * trade.lots * 100_000
        else:
            pnl -= spread_cost * trade.lots * 100_000

        self.trades.append(
            {
                "entry_time": trade.entry_time,
                "exit_time": exit_time,
                "pair": trade.pair,
                "direction": trade.direction,
                "lots": trade.lots,
                "entry_price": trade.entry_price,
                "exit_price": exit_price,
                "pnl": float(pnl),
                "holding_hours": (exit_time - trade.entry_time).total_seconds() / 3600,
                "exit_reason": reason,
            }
        )

        self.prop_firm.state.record_trade(
            trade.pair,
            trade.direction,
            trade.lots,
            trade.entry_price,
            exit_price,
            float(pnl),
            trade.entry_time,
            exit_time,
        )

        self.realized_pnl += float(pnl)
        if trade in self.positions:
            self.positions.remove(trade)
        return float(pnl)

    def _close_all_open_trades(
        self,
        current_bar: pd.Series,
        timestamp: pd.Timestamp,
        force: bool = False,
    ) -> list[float]:
        pnls: list[float] = []
        for pos in self.positions[:]:
            close_price = float(current_bar["close"])
            pnl = self._close_trade(
                pos,
                bar_index=0,
                exit_time=timestamp,
                exit_price=close_price,
                reason="force_close" if force else "close_all",
            )
            pnls.append(pnl)
        return pnls

    def _open_trade(
        self,
        signal: float,
        bar: pd.Series,
        bar_index: int,
        lot_size: Optional[float] = None,
        pair: str = "EURUSD",
    ) -> Optional[Position]:
        signal_price = float(bar["close"])
        direction = "long" if signal > 0 else "short"

        if direction == "long":
            exec_result = self.executor.execute_long(
                signal_price, bar.name, lot_size, pair
            )
        else:
            exec_result = self.executor.execute_short(
                signal_price, bar.name, lot_size, pair
            )

        position = Position(
            entry_time=bar.name,
            entry_price=exec_result.executed_price,
            direction=direction,
            lots=lot_size if lot_size else exec_result.total_cost,
            pair=pair,
        )
        self.positions.append(position)
        return position

    def _calculate_open_trade_lot_size(
        self,
        signal_price: float,
        stop_loss: float,
        equity: float,
        pair: str = "EURUSD",
    ) -> float:
        lot_size = self.sizing_method.calculate_size(
            account_balance=equity,
            entry_price=signal_price,
            stop_loss=stop_loss,
            risk_pct=self.risk_pct,
        )
        pfc = self.prop_firm.state.config
        lot_size = max(pfc.min_lot_size, min(lot_size, pfc.max_lot_size))
        return lot_size

    def _calculate_unrealized_pnl(self, current_bar: pd.Series) -> float:
        pnl = 0.0
        for pos in self.positions:
            close = float(current_bar["close"])
            if pos.direction == "long":
                pnl += (close - pos.entry_price) * pos.lots * 100_000
            else:
                pnl += (pos.entry_price - close) * pos.lots * 100_000
        return float(pnl)

    def _current_equity(self, current_bar: pd.Series) -> float:
        unrealized = self._calculate_unrealized_pnl(current_bar)
        return self.starting_balance + self.realized_pnl + unrealized

    def _has_open_position(self, pair: str) -> bool:
        return any(p.pair == pair for p in self.positions)

    def _get_open_position(self, pair: str) -> Optional[Position]:
        for p in self.positions:
            if p.pair == pair:
                return p
        return None

    def _calculate_max_drawdown(self, equity: pd.Series) -> tuple[float, int]:
        running_max = equity.expanding().max()
        drawdown = (equity - running_max) / running_max
        max_dd = float(abs(drawdown.min()))

        in_drawdown = False
        max_duration = 0
        current_duration = 0

        for dd in drawdown:
            if dd < -0.001:
                if not in_drawdown:
                    in_drawdown = True
                    current_duration = 1
                else:
                    current_duration += 1
            else:
                if in_drawdown:
                    max_duration = max(max_duration, current_duration)
                    in_drawdown = False
                    current_duration = 0

        if in_drawdown:
            max_duration = max(max_duration, current_duration)

        return max_dd, max_duration
