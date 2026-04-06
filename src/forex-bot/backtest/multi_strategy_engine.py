from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import math
from .engine import (
    Bar,
    BacktestConfig,
    BacktestMetrics,
    MarketState,
    SimulatedTrade,
    StrategySignal,
    TradeDirection,
    TradeOutcome,
    ExitReason,
    determine_session,
)
from .strategies import ISignalStrategy


@dataclass
class MultiStrategyConfig:
    weights: Optional[List[float]] = None
    min_combined_confidence: float = 0.50
    use_confluence_scoring: bool = True

    def __post_init__(self):
        if self.weights is None:
            self.weights = [1.0, 1.0, 1.0, 1.0, 1.0]


@dataclass
class StrategyBacktestResult:
    strategy_name: str
    metrics: BacktestMetrics
    last_signal: Optional[StrategySignal]


class MultiStrategyBacktestEngine:
    def __init__(
        self,
        config: BacktestConfig,
        strategies: List[ISignalStrategy],
        multi_config: Optional[MultiStrategyConfig] = None,
    ):
        self.config = config
        self.strategies = strategies
        self.multi_config = multi_config or MultiStrategyConfig()
        self.balance = config.starting_balance
        self.peak_balance = config.starting_balance
        self.max_drawdown = 0.0
        self.current_day = None
        self.daily_start_balance = config.starting_balance
        self.max_daily_loss = 0.0
        self.total_spread_cost = 0.0
        self.total_commission_cost = 0.0

    def run_all_strategies(self, bars: List[Bar]) -> Dict[str, StrategyBacktestResult]:
        results = {}
        for strategy in self.strategies:
            result = self._run_single_strategy(strategy, bars)
            results[strategy.name] = result
        return results

    def _run_single_strategy(
        self, strategy: ISignalStrategy, bars: List[Bar]
    ) -> StrategyBacktestResult:
        if len(bars) < self.config.min_bars_before_signal:
            raise ValueError(f"Need at least {self.config.min_bars_before_signal} bars")

        self._reset()
        trades: List[SimulatedTrade] = []
        equity_curve = [self.balance]
        open_trades: List[SimulatedTrade] = []
        last_signal: Optional[StrategySignal] = None

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
                    bars=bars[: i + 1], current_session=determine_session(bars[i].time)
                )

                signal = strategy.evaluate(state)
                if signal is not None and self._passes_filters(signal):
                    trade = self._open_trade(signal, bar, i)
                    if trade is not None:
                        open_trades.append(trade)
                        last_signal = signal

            equity_curve.append(self.balance)

        self._close_all_open_trades(open_trades, len(bars) - 1, bars[-1].time, trades)
        metrics = self._calculate_metrics(trades, equity_curve, 0)

        return StrategyBacktestResult(
            strategy_name=strategy.name, metrics=metrics, last_signal=last_signal
        )

    def run_combined_strategies(
        self, strategies: List[ISignalStrategy], bars: List[Bar]
    ) -> Tuple[Dict[str, StrategyBacktestResult], BacktestMetrics]:
        individual = {}
        all_signals: List[StrategySignal] = []

        self._reset()
        trades: List[SimulatedTrade] = []
        equity_curve = [self.balance]
        open_trades: List[SimulatedTrade] = []

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
                    bars=bars[: i + 1], current_session=determine_session(bars[i].time)
                )

                all_signals.clear()
                for strategy in strategies:
                    signal = strategy.evaluate(state)
                    if signal is not None:
                        all_signals.append(signal)

                if len(all_signals) > 0:
                    combined = self._combine_signals(all_signals)
                    if (
                        combined is not None
                        and combined.confidence
                        >= self.multi_config.min_combined_confidence
                    ):
                        trade = self._open_trade(combined, bar, i)
                        if trade is not None:
                            open_trades.append(trade)

            equity_curve.append(self.balance)

        for strategy in strategies:
            individual[strategy.name] = self._run_single_strategy(strategy, bars)

        self._close_all_open_trades(open_trades, len(bars) - 1, bars[-1].time, trades)
        combined_metrics = self._calculate_metrics(trades, equity_curve, 0)

        return (individual, combined_metrics)

    def _combine_signals(
        self, signals: List[StrategySignal]
    ) -> Optional[StrategySignal]:
        if len(signals) == 0:
            return None

        long_signals = [s for s in signals if s.direction == TradeDirection.LONG]
        short_signals = [s for s in signals if s.direction == TradeDirection.SHORT]

        long_conf = sum(s.confidence for s in long_signals) / max(1, len(long_signals))
        short_conf = sum(s.confidence for s in short_signals) / max(
            1, len(short_signals)
        )

        if (
            long_conf > short_conf
            and long_conf >= self.multi_config.min_combined_confidence
        ):
            direction = TradeDirection.LONG
            confidence = long_conf
            entry = sum(s.entry_price for s in long_signals) / len(long_signals)
            sl = max(s.stop_loss for s in long_signals)
            tp1 = sum(s.take_profit_1 for s in long_signals) / len(long_signals)
            tp2 = sum(s.take_profit_2 for s in long_signals) / len(long_signals)
            tp3 = sum(s.take_profit_3 for s in long_signals) / len(long_signals)
        elif (
            short_conf > long_conf
            and short_conf >= self.multi_config.min_combined_confidence
        ):
            direction = TradeDirection.SHORT
            confidence = short_conf
            entry = sum(s.entry_price for s in short_signals) / len(short_signals)
            sl = min(s.stop_loss for s in short_signals)
            tp1 = sum(s.take_profit_1 for s in short_signals) / len(short_signals)
            tp2 = sum(s.take_profit_2 for s in short_signals) / len(short_signals)
            tp3 = sum(s.take_profit_3 for s in short_signals) / len(short_signals)
        else:
            return None

        rationale = f"Combined {len(signals)} signals: {len(long_signals)} long, {len(short_signals)} short"

        return StrategySignal(
            direction=direction,
            confidence=confidence,
            entry_price=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            rationale=rationale,
        )

    def _reset(self):
        self.balance = self.config.starting_balance
        self.peak_balance = self.config.starting_balance
        self.max_drawdown = 0.0
        self.max_daily_loss = 0.0
        self.current_day = None
        self.daily_start_balance = self.config.starting_balance
        self.total_spread_cost = 0.0
        self.total_commission_cost = 0.0

    def _update_daily_tracking(self, bar_time):
        day = bar_time.date()
        if self.current_day is None:
            self.current_day = day
            self.daily_start_balance = self.balance
        elif day != self.current_day:
            daily_loss = self.daily_start_balance - self.balance
            if daily_loss > self.max_daily_loss:
                self.max_daily_loss = daily_loss
            self.current_day = day
            self.daily_start_balance = self.balance

    def _is_max_drawdown_breached(self) -> bool:
        drawdown_pct = (self.peak_balance - self.balance) / self.peak_balance
        return drawdown_pct >= self.config.max_total_drawdown_pct

    def _is_max_daily_loss_breached(self) -> bool:
        daily_loss_pct = (
            self.daily_start_balance - self.balance
        ) / self.daily_start_balance
        return daily_loss_pct >= self.config.max_daily_drawdown_pct

    def _check_open_trades(
        self,
        open_trades: List[SimulatedTrade],
        bar: Bar,
        bar_index: int,
        closed_trades: List[SimulatedTrade],
        equity_curve: List[float],
    ):
        to_close = []
        for trade in open_trades:
            hit, exit_price, reason = self._check_trade_exit(trade, bar)
            if hit:
                self._close_trade(trade, bar_index, bar.time, exit_price, reason)
                closed_trades.append(trade)
                to_close.append(trade)
                equity_curve.append(self.balance)
        for t in to_close:
            open_trades.remove(t)

    def _check_trade_exit(self, trade: SimulatedTrade, bar: Bar):
        if trade.direction == TradeDirection.LONG:
            if bar.low <= trade.stop_loss:
                return (True, trade.stop_loss, ExitReason.STOP_LOSS)
            if bar.high >= trade.take_profit_1:
                return (True, trade.take_profit_1, ExitReason.TAKE_PROFIT_1)
            if bar.high >= trade.take_profit_2:
                return (True, trade.take_profit_2, ExitReason.TAKE_PROFIT_2)
            if bar.high >= trade.take_profit_3:
                return (True, trade.take_profit_3, ExitReason.TAKE_PROFIT_3)
        else:
            if bar.high >= trade.stop_loss:
                return (True, trade.stop_loss, ExitReason.STOP_LOSS)
            if bar.low <= trade.take_profit_1:
                return (True, trade.take_profit_1, ExitReason.TAKE_PROFIT_1)
            if bar.low <= trade.take_profit_2:
                return (True, trade.take_profit_2, ExitReason.TAKE_PROFIT_2)
            if bar.low <= trade.take_profit_3:
                return (True, trade.take_profit_3, ExitReason.TAKE_PROFIT_3)
        return (False, 0, ExitReason.STOP_LOSS)

    def _close_trade(
        self,
        trade: SimulatedTrade,
        bar_index: int,
        exit_time,
        exit_price: float,
        reason: ExitReason,
    ):
        trade.exit_bar_index = bar_index
        trade.exit_time = exit_time
        trade.exit_reason = reason

        pip_value = self._get_pip_value(trade.entry_price)
        standard_lots = trade.lot_size / self.config.units_per_lot
        spread_pips = self.config.effective_spread_pips
        commission_cost = standard_lots * self.config.commission_per_lot
        self.total_commission_cost += commission_cost

        if self.config.round_trip_spread:
            spread_price = spread_pips * pip_value
            if trade.direction == TradeDirection.LONG:
                exit_price -= spread_price
            else:
                exit_price += spread_price
            spread_dollars = spread_pips * pip_value * trade.lot_size
            self.total_spread_cost += spread_dollars
        else:
            spread_dollars = spread_pips * pip_value * trade.lot_size
            self.total_spread_cost += spread_dollars

        slippage_price = self.config.slippage_pips * pip_value
        if trade.direction == TradeDirection.LONG:
            exit_price -= slippage_price
        else:
            exit_price += slippage_price

        trade.exit_price = exit_price

        holding_days = (exit_time.date() - trade.entry_time.date()).days
        if holding_days > 0 and self.config.swap_per_lot_per_day != 0.0:
            swap_cost = standard_lots * self.config.swap_per_lot_per_day * holding_days
        else:
            swap_cost = 0.0

        if trade.direction == TradeDirection.LONG:
            trade.pips = (exit_price - trade.entry_price) / pip_value
        else:
            trade.pips = (trade.entry_price - exit_price) / pip_value

        trade.profit_loss = (
            trade.pips * standard_lots * pip_value * self.config.units_per_lot
            - commission_cost
            + swap_cost
        )
        self.balance = max(0.0, self.balance + trade.profit_loss)

        trade.outcome = (
            TradeOutcome.WIN
            if trade.profit_loss > 0.01
            else TradeOutcome.LOSS
            if trade.profit_loss < -0.01
            else TradeOutcome.BREAKEVEN
        )

        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        drawdown = (
            (self.peak_balance - self.balance) / self.peak_balance
            if self.peak_balance > 0
            else 0.0
        )
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def _close_all_open_trades(
        self,
        open_trades: List[SimulatedTrade],
        bar_index: int,
        exit_time,
        closed_trades: List[SimulatedTrade],
    ):
        for trade in open_trades:
            self._close_trade(
                trade,
                bar_index,
                exit_time,
                closed_trades[-1].exit_price if closed_trades else trade.entry_price,
                ExitReason.END_OF_DATA,
            )
            closed_trades.append(trade)
        open_trades.clear()

    def _passes_filters(self, signal: StrategySignal) -> bool:
        return signal.confidence >= self.config.min_confidence

    def _open_trade(
        self, signal: StrategySignal, bar: Bar, bar_index: int
    ) -> Optional[SimulatedTrade]:
        risk_amount = self.balance * self.config.risk_per_trade_pct
        risk = abs(signal.entry_price - signal.stop_loss)
        if risk == 0:
            return None

        pip_value = self._get_pip_value(signal.entry_price)

        if self.config.round_trip_spread:
            effective_entry = signal.entry_price
            adjusted_risk = risk
        else:
            spread_cost = self.config.spread_pips * pip_value
            slippage_cost = self.config.slippage_pips * pip_value
            total_cost = spread_cost + slippage_cost
            effective_entry = (
                signal.entry_price + total_cost
                if signal.direction == TradeDirection.LONG
                else signal.entry_price - total_cost
            )
            adjusted_risk = abs(effective_entry - signal.stop_loss)

        if adjusted_risk == 0:
            return None

        lot_size = risk_amount / adjusted_risk
        margin_required = lot_size * effective_entry / self.config.leverage
        if margin_required > self.balance:
            return None

        max_lot_size = self.balance * self.config.leverage / effective_entry
        lot_size = min(lot_size, max_lot_size)

        return SimulatedTrade(
            entry_bar_index=bar_index,
            exit_bar_index=-1,
            direction=signal.direction,
            entry_price=effective_entry,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            take_profit_3=signal.take_profit_3,
            exit_price=0.0,
            lot_size=lot_size,
            risk_amount=risk_amount,
            pips=0.0,
            profit_loss=0.0,
            outcome=TradeOutcome.OPEN,
            exit_reason=ExitReason.STOP_LOSS,
            entry_time=bar.time,
            exit_time=bar.time,
            confidence_score=signal.confidence,
            confluence_count=1,
            rationale=signal.rationale,
        )

    def _calculate_metrics(
        self,
        trades: List[SimulatedTrade],
        equity_curve: List[float],
        rejected_signals: int,
    ) -> BacktestMetrics:
        metrics = BacktestMetrics(
            starting_balance=self.config.starting_balance,
            ending_balance=self.balance,
            total_pnl=self.balance - self.config.starting_balance,
            total_pnl_pct=(self.balance - self.config.starting_balance)
            / self.config.starting_balance,
            win_rate=0.0,
            total_trades=len(trades),
            winning_trades=sum(1 for t in trades if t.outcome == TradeOutcome.WIN),
            losing_trades=sum(1 for t in trades if t.outcome == TradeOutcome.LOSS),
            breakeven_trades=sum(
                1 for t in trades if t.outcome == TradeOutcome.BREAKEVEN
            ),
            avg_win=0.0,
            avg_loss=0.0,
            largest_win=0.0,
            largest_loss=0.0,
            profit_factor=0.0,
            max_drawdown_pct=self.max_drawdown * 100,
            max_drawdown_dollar=self.max_drawdown * self.peak_balance,
            max_daily_loss_dollar=self.max_daily_loss,
            sharpe_ratio=0.0,
            avg_risk_reward=0.0,
            expectancy=0.0,
            avg_holding_bars=0.0,
            equity_curve=equity_curve,
            trades=trades,
            total_spread_cost=self.total_spread_cost,
            total_commission_cost=self.total_commission_cost,
            rejected_signals=rejected_signals,
        )

        if len(trades) > 0:
            wins = [t for t in trades if t.outcome == TradeOutcome.WIN]
            losses = [t for t in trades if t.outcome == TradeOutcome.LOSS]

            metrics.win_rate = metrics.winning_trades / len(trades) * 100
            metrics.avg_win = (
                sum(t.profit_loss for t in wins) / len(wins) if wins else 0
            )
            metrics.avg_loss = (
                sum(t.profit_loss for t in losses) / len(losses) if losses else 0
            )
            metrics.largest_win = max(t.profit_loss for t in wins) if wins else 0
            metrics.largest_loss = min(t.profit_loss for t in losses) if losses else 0

            total_wins = sum(t.profit_loss for t in wins)
            total_losses = abs(sum(t.profit_loss for t in losses))
            metrics.profit_factor = (
                total_wins / total_losses
                if total_losses > 0
                else total_wins
                if total_wins > 0
                else 0
            )

            metrics.avg_risk_reward = (
                abs(metrics.avg_win / metrics.avg_loss) if metrics.avg_loss != 0 else 0
            )
            metrics.expectancy = (metrics.win_rate / 100 * metrics.avg_win) - (
                (1 - metrics.win_rate / 100) * abs(metrics.avg_loss)
            )
            metrics.avg_holding_bars = sum(
                t.exit_bar_index - t.entry_bar_index for t in trades
            ) / len(trades)

        metrics.sharpe_ratio = self._calculate_sharpe_ratio(equity_curve)
        return metrics

    def _calculate_sharpe_ratio(self, equity_curve: List[float]) -> float:
        if len(equity_curve) < 2:
            return 0.0
        returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i - 1] != 0:
                returns.append(
                    (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
                )
        if not returns:
            return 0.0
        mean_return = sum(returns) / len(returns)
        std_dev = math.sqrt(sum((r - mean_return) ** 2 for r in returns) / len(returns))
        if std_dev == 0:
            return 999.0 if mean_return > 0 else 0.0
        return (mean_return / std_dev) * math.sqrt(252)

    @staticmethod
    def _get_pip_value(price: float) -> float:
        if price >= 50:
            return 0.01
        elif price >= 1:
            return 0.0001
        else:
            return 0.00000001
