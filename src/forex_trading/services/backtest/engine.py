"""Backtesting engine with realistic execution assumptions.

No look-ahead bias - all signals use only available data at generation time.
"""
from dataclasses import dataclass, field
from typing import Optional, Union
import warnings
import pandas as pd
import numpy as np
from .prop_firm_rules import PropFirmRuleEngine, PropFirmConfig
from .execution import ExecutionSimulator, ExecutionConfig
from .strategies import Strategy, StopLossTakeProfit
from ..risk.position_sizing import SizingMethod, FixedFractional, FixedLotSize
import inspect


def _takes_pair_arg(strategy) -> bool:
    sig = inspect.signature(strategy.generate_signals)
    params = list(sig.parameters.keys())
    return len(params) > 1 and params[1] in ("pair", "instrument")


@dataclass
class BacktestConfig:
    starting_balance: float = 10000.0
    prop_firm_config: Optional[PropFirmConfig] = None
    execution_config: Optional[ExecutionConfig] = None
    risk_free_rate: float = 0.0
    risk_pct: float = 0.02
    sizing_method: Optional[SizingMethod] = None
    sl_atr_multiplier: float = 1.5
    tp_atr_multiplier: float = 2.0


@dataclass
class Position:
    entry_time: pd.Timestamp
    entry_price: float
    direction: str
    lots: float
    pair: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list
    daily_returns: pd.Series
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_duration: int
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_trade_duration: float
    compliance_report: dict


class BacktestEngine:
    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config if config is not None else BacktestConfig()
        self.prop_firm = PropFirmRuleEngine(
            self.config.prop_firm_config or PropFirmConfig(),
            self.config.starting_balance
        )
        self.executor = ExecutionSimulator(self.config.execution_config or ExecutionConfig())
        self.sizing_method = self.config.sizing_method if self.config.sizing_method else FixedFractional()
        self.positions: list[Position] = []
        self.equity_curve = []
        self.realized_pnl: float = 0.0

    def run(self, data: pd.DataFrame, strategy, pair: str = "EURUSD") -> BacktestResult:
        if not strategy.validate_data(data):
            raise ValueError("Data missing required columns")

        signals = strategy.generate_signals(data, pair) if _takes_pair_arg(strategy) else strategy.generate_signals(data)
        self._ensure_signal_alignment(data, signals)

        self.equity_curve = [self.config.starting_balance]
        self.realized_pnl = 0.0
        trades = []

        for i in range(1, len(data)):
            current_bar = data.iloc[i]
            timestamp = current_bar.name

            unrealized = float(self._calculate_unrealized_pnl(current_bar))
            equity = self.config.starting_balance + self.realized_pnl + unrealized

            self.prop_firm.update_daily_drawdown(equity, timestamp)

            if self.prop_firm.check_drawdown_violation():
                self._close_all_positions(current_bar, timestamp, trades, force=True)
                self.equity_curve.append(self.config.starting_balance + self.realized_pnl)
                break

            self._check_stop_loss_take_profit(current_bar, timestamp, trades)

            if pd.notna(signals.iloc[i]) and signals.iloc[i] != 0:
                signal = signals.iloc[i]

                open_pos = self._get_open_position(pair)
                if open_pos is not None:
                    if (open_pos.direction == "long" and signal < 0) or \
                       (open_pos.direction == "short" and signal > 0):
                        pnl = self._close_position(open_pos, current_bar, timestamp, trades)
                        self.realized_pnl += pnl

                if not self._has_open_position(pair):
                    signal_price = float(current_bar['close'])
                    sl_tp = strategy.generate_sl_tp(
                        data.iloc[:i+1], signal, signal_price,
                        atr_period=14,
                        sl_atr_multiplier=self.config.sl_atr_multiplier,
                        tp_atr_multiplier=self.config.tp_atr_multiplier
                    )

                    stop_loss = sl_tp.stop_loss if sl_tp else None
                    take_profit = sl_tp.take_profit if sl_tp else None

                    if sl_tp and stop_loss is not None:
                        lot_size = self.sizing_method.calculate_size(
                            account_balance=equity,
                            entry_price=signal_price,
                            stop_loss=stop_loss,
                            risk_pct=self.config.risk_pct
                        )
                        if self.config.prop_firm_config:
                            lot_size = max(self.config.prop_firm_config.min_lot_size,
                                          min(lot_size, self.config.prop_firm_config.max_lot_size))
                    else:
                        lot_size = self.config.execution_config.default_lot_size if self.config.execution_config else 0.1

                    can_open, reason = self.prop_firm.state.can_open_position(
                        lot_size=lot_size, pair=pair, timestamp=timestamp
                    )

                    if can_open:
                        exec_result = self.executor.execute_long(
                            signal_price, timestamp, lot_size, pair
                        ) if signal > 0 else self.executor.execute_short(
                            signal_price, timestamp, lot_size, pair
                        )

                        position = Position(
                            entry_time=timestamp,
                            entry_price=exec_result.executed_price,
                            direction="long" if signal > 0 else "short",
                            lots=lot_size,
                            pair=pair,
                            stop_loss=stop_loss,
                            take_profit=take_profit
                        )
                        self.positions.append(position)

            unrealized = float(self._calculate_unrealized_pnl(current_bar))
            equity = self.config.starting_balance + self.realized_pnl + unrealized
            self.equity_curve.append(equity)

        if self.positions:
            last_bar = data.iloc[-1]
            last_ts = data.index[-1]
            self._close_all_positions(last_bar, last_ts, trades, force=True)
            self.equity_curve.append(self.config.starting_balance + self.realized_pnl)

        return self._generate_results(trades)

    def _ensure_signal_alignment(self, data: pd.DataFrame, signals: pd.Series):
        if len(signals) != len(data):
            warnings.warn(f"Signal length ({len(signals)}) != data length ({len(data)}). Truncating.")

    def _has_open_position(self, pair: str) -> bool:
        return any(p.pair == pair for p in self.positions)

    def _get_open_position(self, pair: str) -> Optional[Position]:
        for p in self.positions:
            if p.pair == pair:
                return p
        return None

    def _close_position(self, pos: Position, current_bar: pd.Series,
                        timestamp: pd.Timestamp, trades: list) -> float:
        close_price = current_bar['close']
        if pos.direction == "long":
            pnl = (close_price - pos.entry_price) * pos.lots * 100000
        else:
            pnl = (pos.entry_price - close_price) * pos.lots * 100000

        trades.append({
            'entry_time': pos.entry_time,
            'exit_time': timestamp,
            'pair': pos.pair,
            'direction': pos.direction,
            'lots': pos.lots,
            'entry_price': pos.entry_price,
            'exit_price': close_price,
            'pnl': pnl,
            'holding_hours': (timestamp - pos.entry_time).total_seconds() / 3600
        })
        self.prop_firm.state.record_trade(
            pos.pair, pos.direction, pos.lots, pos.entry_price,
            float(close_price), float(pnl), pos.entry_time, timestamp
        )
        self.positions.remove(pos)
        return float(pnl)

    def _calculate_unrealized_pnl(self, current_bar: pd.Series) -> float:
        pnl = 0.0
        for pos in self.positions:
            if pos.direction == "long":
                pnl += (current_bar['close'] - pos.entry_price) * pos.lots * 100000
            else:
                pnl += (pos.entry_price - current_bar['close']) * pos.lots * 100000
        return float(pnl)

    def _check_stop_loss_take_profit(self, current_bar: pd.Series, timestamp: pd.Timestamp, trades: list):
        positions_to_close = []
        for i, pos in enumerate(self.positions):
            hit_sl = False
            hit_tp = False
            exit_price = None

            if pos.direction == "long":
                if pos.stop_loss and current_bar['low'] <= pos.stop_loss:
                    hit_sl = True
                    exit_price = pos.stop_loss
                elif pos.take_profit and current_bar['high'] >= pos.take_profit:
                    hit_tp = True
                    exit_price = pos.take_profit
            else:
                if pos.stop_loss and current_bar['high'] >= pos.stop_loss:
                    hit_sl = True
                    exit_price = pos.stop_loss
                elif pos.take_profit and current_bar['low'] <= pos.take_profit:
                    hit_tp = True
                    exit_price = pos.take_profit

            if hit_sl or hit_tp:
                positions_to_close.append(i)
                closed_pnl = (exit_price - pos.entry_price) * pos.lots * 100000 if pos.direction == "long" else (pos.entry_price - exit_price) * pos.lots * 100000
                trades.append({
                    'entry_time': pos.entry_time,
                    'exit_time': timestamp,
                    'pair': pos.pair,
                    'direction': pos.direction,
                    'lots': pos.lots,
                    'entry_price': pos.entry_price,
                    'exit_price': exit_price,
                    'pnl': closed_pnl,
                    'holding_hours': (timestamp - pos.entry_time).total_seconds() / 3600,
                    'exit_reason': 'stop_loss' if hit_sl else 'take_profit'
                })
                self.prop_firm.state.record_trade(pos.pair, pos.direction, pos.lots, pos.entry_price, exit_price, closed_pnl, pos.entry_time, timestamp)
                self.realized_pnl += float(closed_pnl)

        for i in reversed(positions_to_close):
            self.positions.pop(i)

    def _close_all_positions(self, current_bar: pd.Series, timestamp: pd.Timestamp, trades: list, force: bool = False):
        for pos in self.positions[:]:
            close_price: float = current_bar['close']  # type: ignore
            if pos.direction == "long":
                exit_price = close_price
                pnl = (exit_price - pos.entry_price) * pos.lots * 100000
            else:
                exit_price = close_price
                pnl = (pos.entry_price - exit_price) * pos.lots * 100000

            trades.append({
                'entry_time': pos.entry_time,
                'exit_time': timestamp,
                'pair': pos.pair,
                'direction': pos.direction,
                'lots': pos.lots,
                'entry_price': pos.entry_price,
                'exit_price': exit_price,
                'pnl': pnl,
                'holding_hours': (timestamp - pos.entry_time).total_seconds() / 3600,
                'force_close': force
            })
            self.prop_firm.state.record_trade(pos.pair, pos.direction, pos.lots, pos.entry_price, float(exit_price), float(pnl), pos.entry_time, timestamp)
            self.realized_pnl += float(pnl)
            self.positions.remove(pos)

    def _generate_results(self, trades: list) -> BacktestResult:
        equity_series = pd.Series(self.equity_curve)
        equity_series.index = pd.RangeIndex(start=0, stop=len(self.equity_curve), step=1)

        daily_returns = equity_series.pct_change().dropna()

        total_return = (self.equity_curve[-1] - self.config.starting_balance) / self.config.starting_balance

        sharpe_ratio = self._calculate_sharpe(daily_returns)
        max_dd, max_dd_duration = self._calculate_max_drawdown(equity_series)

        wins = [t['pnl'] for t in trades if t['pnl'] > 0]
        losses = [abs(t['pnl']) for t in trades if t['pnl'] < 0]
        win_rate = len(wins) / len(trades) if trades else 0.0
        profit_factor = sum(wins) / sum(losses) if losses else (99.99 if wins else 0.0)

        avg_duration = float(np.mean([t['holding_hours'] for t in trades])) if trades else 0.0

        return BacktestResult(
            equity_curve=equity_series,
            trades=trades,
            daily_returns=daily_returns,
            total_return=total_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_dd,
            max_drawdown_duration=max_dd_duration,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=len(trades),
            avg_trade_duration=avg_duration,
            compliance_report=self.prop_firm.get_compliance_report()
        )

    def _calculate_sharpe(self, returns: pd.Series) -> float:
        if len(returns) < 2:
            return 0.0
        excess_returns = returns - self.config.risk_free_rate / 252
        return float(np.sqrt(252) * excess_returns.mean() / excess_returns.std()) if excess_returns.std() > 0 else 0.0

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

        return max_dd, max_duration


def walk_forward_analysis(
    data: pd.DataFrame,
    strategy,
    config: Optional[BacktestConfig] = None,
    train_bars: int = 63,
    test_bars: int = 126,
    step_bars: int = 21,
    pair: str = "EURUSD"
) -> list[BacktestResult]:
    results = []
    train_start = 0

    while train_start + train_bars + test_bars <= len(data):
        train_end = train_start + train_bars
        test_start = train_end
        test_end = test_start + test_bars

        train_data = data.iloc[train_start:train_end]
        test_data = data.iloc[test_start:test_end]

        engine = BacktestEngine(config)
        engine.run(train_data, strategy, pair)

        test_engine = BacktestEngine(config)
        test_result = test_engine.run(test_data, strategy, pair)
        results.append(test_result)

        train_start += step_bars

    return results
