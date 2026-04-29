from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
from .engine import (
    Bar,
    BacktestConfig,
    BacktestMetrics,
    MarketState,
    SessionType,
    SimulatedTrade,
    StrategySignal,
    TradeDirection,
    TradeOutcome,
    ExitReason,
    determine_session,
)
from .strategies import ISignalStrategy


class VotingMethod(Enum):
    VOTE = "vote"
    WEIGHTED = "weighted"
    CONFLUENCE = "confluence"


class ConfidenceMethod(Enum):
    MEAN = "mean"
    WEIGHTED = "weighted"
    CONFLUENCE = "confluence"


ICT_SMC_COMPONENT_TYPES = [
    "order_block",
    "fair_value_gap",
    "liquidity_sweep",
    "market_structure",
    "premium_discount",
    "h4_context",
]

INDICATOR_STRATEGY_PATTERNS = [
    "MA Crossover",
    "RSI Divergence",
    "Momentum ROC",
    "Bollinger Band",
    "S/R Breakout",
]


@dataclass
class AmalgamationConfig:
    voting_method: VotingMethod = VotingMethod.WEIGHTED
    confidence_method: ConfidenceMethod = ConfidenceMethod.WEIGHTED
    min_combined_confidence: float = 0.50
    min_confluence: int = 2
    strategy_weights: Dict[str, float] = field(default_factory=dict)
    confluence_bonus: float = 0.10
    session_filter_enabled: bool = True
    regime_filter_enabled: bool = False
    allowed_sessions: List[SessionType] = field(
        default_factory=lambda: [
            SessionType.LONDON,
            SessionType.NY_AM,
            SessionType.NY_PM,
        ]
    )
    ict_smc_only: bool = True

    def get_weight(self, strategy_name: str) -> float:
        return self.strategy_weights.get(strategy_name, 1.0)

    def is_indicator_strategy(self, strategy_name: str) -> bool:
        for pattern in INDICATOR_STRATEGY_PATTERNS:
            if pattern.lower() in strategy_name.lower():
                return True
        return False


@dataclass
class ComponentProfile:
    name: str
    component_type: str
    sub_components: List[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    strategy_name: str
    direction: Optional[TradeDirection]
    confidence: float
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: float
    rationale: str
    weight: float = 1.0


class ComponentExtractor:
    COMPONENT_TYPES = [
        "signal_generator",
        "exit_condition",
        "confidence_modifier",
        "risk_adjustment",
    ]

    def extract(
        self, strategy: ISignalStrategy, state: MarketState
    ) -> Optional[ExtractionResult]:
        signal = strategy.evaluate(state)
        if signal is None:
            return None

        return ExtractionResult(
            strategy_name=strategy.name,
            direction=signal.direction,
            confidence=signal.confidence,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            take_profit_3=signal.take_profit_3,
            rationale=signal.rationale,
        )

    def profile_strategy(self, strategy: ISignalStrategy) -> ComponentProfile:
        name = strategy.name
        if "ICT" in name or "SMC" in name or "Confluence" in name:
            return ComponentProfile(
                name=name,
                component_type="ict_smc_confluence",
                sub_components=ICT_SMC_COMPONENT_TYPES,
            )
        return ComponentProfile(name=name, component_type="unknown")


class AmalgamationEngine:
    def __init__(self, config: AmalgamationConfig):
        self.config = config

    def combine(
        self, signals: List[StrategySignal], state: MarketState
    ) -> Optional[StrategySignal]:
        if not signals:
            return None

        filtered = self._apply_meta_filters(signals, state)
        if len(filtered) < self.config.min_confluence:
            return None

        direction = self._vote_direction(filtered)
        if direction is None or direction == TradeDirection.NEUTRAL:
            return None

        confidence = self._compute_confidence(filtered, direction)
        if confidence < self.config.min_combined_confidence:
            return None

        direction_signals = [s for s in filtered if s.direction == direction]
        if not direction_signals:
            return None

        entry, sl, tp1, tp2, tp3 = self._aggregate_levels(direction_signals, direction)
        rationale = self._build_rationale(direction_signals, direction, confidence)

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

    def _apply_meta_filters(
        self, signals: List[StrategySignal], state: MarketState
    ) -> List[StrategySignal]:
        filtered = signals

        if self.config.session_filter_enabled:
            filtered = [
                s
                for s in filtered
                if state.current_session in self.config.allowed_sessions
            ]

        return filtered

    def _vote_direction(self, signals: List[StrategySignal]) -> TradeDirection:
        long_signals = [s for s in signals if s.direction == TradeDirection.LONG]
        short_signals = [s for s in signals if s.direction == TradeDirection.SHORT]

        if not long_signals and not short_signals:
            return TradeDirection.NEUTRAL

        if self.config.voting_method == VotingMethod.VOTE:
            long_count = len(long_signals)
            short_count = len(short_signals)
            if long_count > short_count:
                return TradeDirection.LONG
            elif short_count > long_count:
                return TradeDirection.SHORT
            return TradeDirection.NEUTRAL

        elif self.config.voting_method == VotingMethod.WEIGHTED:
            long_weight = sum(
                self.config.get_weight(
                    s.rationale.split(":")[0].strip() if ":" in s.rationale else ""
                )
                * s.confidence
                for s in long_signals
            )
            short_weight = sum(
                self.config.get_weight(
                    s.rationale.split(":")[0].strip() if ":" in s.rationale else ""
                )
                * s.confidence
                for s in short_signals
            )
            if long_weight > short_weight:
                return TradeDirection.LONG
            elif short_weight > long_weight:
                return TradeDirection.SHORT
            return TradeDirection.NEUTRAL

        else:
            long_conf = sum(s.confidence for s in long_signals) / max(
                1, len(long_signals)
            )
            short_conf = sum(s.confidence for s in short_signals) / max(
                1, len(short_signals)
            )
            if long_conf > short_conf:
                return TradeDirection.LONG
            elif short_conf > long_conf:
                return TradeDirection.SHORT
            return TradeDirection.NEUTRAL

    def _compute_confidence(
        self, signals: List[StrategySignal], direction: TradeDirection
    ) -> float:
        direction_signals = [s for s in signals if s.direction == direction]

        if self.config.confidence_method == ConfidenceMethod.MEAN:
            return sum(s.confidence for s in direction_signals) / len(direction_signals)

        elif self.config.confidence_method == ConfidenceMethod.WEIGHTED:
            total_weight = sum(
                self.config.get_weight("default") for _ in direction_signals
            )
            weighted_sum = sum(
                s.confidence * self.config.get_weight("default")
                for s in direction_signals
            )
            return weighted_sum / total_weight if total_weight > 0 else 0.0

        else:
            base = sum(s.confidence for s in direction_signals) / len(direction_signals)
            bonus = 1.0 + self.config.confluence_bonus * (len(direction_signals) - 1)
            return min(0.99, base * bonus)

    def _aggregate_levels(
        self, signals: List[StrategySignal], direction: TradeDirection
    ) -> Tuple[float, float, float, float, float]:
        if not signals:
            return (0, 0, 0, 0, 0)

        entry = sum(s.entry_price for s in signals) / len(signals)

        if direction == TradeDirection.LONG:
            sl = max(s.stop_loss for s in signals)
        else:
            sl = min(s.stop_loss for s in signals)

        tp1 = sum(s.take_profit_1 for s in signals) / len(signals)
        tp2 = sum(s.take_profit_2 for s in signals) / len(signals)
        tp3 = sum(s.take_profit_3 for s in signals) / len(signals)

        return (entry, sl, tp1, tp2, tp3)

    def _build_rationale(
        self,
        signals: List[StrategySignal],
        direction: TradeDirection,
        confidence: float,
    ) -> str:
        names = []
        for s in signals:
            parts = s.rationale.split(":")
            name = parts[0].strip() if parts else "Unknown"
            names.append(name)

        dir_label = "LONG" if direction == TradeDirection.LONG else "SHORT"
        return f"Amalgamated {dir_label} (conf={confidence:.2f}): {', '.join(names)}"


class AmalgamatedBacktestEngine:
    def __init__(
        self,
        config: BacktestConfig,
        strategies: List[ISignalStrategy],
        amalgamation_config: Optional[AmalgamationConfig] = None,
    ):
        self.config = config
        self.amalgamation = (
            amalgamation_config if amalgamation_config else AmalgamationConfig()
        )
        self.extractor = ComponentExtractor()
        if self.amalgamation.ict_smc_only:
            filtered = [
                s
                for s in strategies
                if not self.amalgamation.is_indicator_strategy(s.name)
            ]
            if filtered:
                self.strategies = filtered
            else:
                from .ict_smc.strategy_adapter import ICTSMCStrategy

                self.strategies = [ICTSMCStrategy()]
                if self.amalgamation.min_confluence > 1:
                    self.amalgamation.min_confluence = 1
        else:
            self.strategies = strategies

    def run(self, bars: List[Bar]) -> BacktestMetrics:
        if len(bars) < self.config.min_bars_before_signal:
            raise ValueError(f"Need at least {self.config.min_bars_before_signal} bars")

        self._reset()
        trades: List[SimulatedTrade] = []
        equity_curve = [self.balance]
        open_trades: List[SimulatedTrade] = []
        rejected_signals = 0

        engine = AmalgamationEngine(self.amalgamation)

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

                all_signals: List[StrategySignal] = []
                for strategy in self.strategies:
                    extraction = self.extractor.extract(strategy, state)
                    if (
                        extraction is not None
                        and extraction.direction is not None
                        and extraction.direction != TradeDirection.NEUTRAL
                    ):
                        dir_val: TradeDirection = extraction.direction
                        all_signals.append(
                            StrategySignal(
                                direction=dir_val,
                                confidence=extraction.confidence,
                                entry_price=extraction.entry_price,
                                stop_loss=extraction.stop_loss,
                                take_profit_1=extraction.take_profit_1,
                                take_profit_2=extraction.take_profit_2,
                                take_profit_3=extraction.take_profit_3,
                                rationale=extraction.rationale,
                            )
                        )

                if all_signals:
                    combined = engine.combine(all_signals, state)
                    if combined is not None:
                        trade = self._open_trade(combined, bar, i)
                        if trade is not None:
                            open_trades.append(trade)
                        else:
                            rejected_signals += 1
                    else:
                        rejected_signals += 1

            equity_curve.append(self.balance)

        self._close_all_open_trades(open_trades, len(bars) - 1, bars[-1].time, trades)
        return self._calculate_metrics(trades, equity_curve, rejected_signals)

    def run_individual_and_combined(
        self, bars: List[Bar]
    ) -> Tuple[Dict[str, BacktestMetrics], BacktestMetrics]:
        from .multi_strategy_engine import MultiStrategyBacktestEngine

        multi_engine = MultiStrategyBacktestEngine(self.config, self.strategies)
        individual_results = multi_engine.run_all_strategies(bars)
        individual_metrics = {
            name: result.metrics for name, result in individual_results.items()
        }

        combined_metrics = self.run(bars)

        return individual_metrics, combined_metrics

    def _reset(self):
        self.balance = self.config.starting_balance
        self.peak_balance = self.config.starting_balance
        self.max_drawdown = 0.0
        self.max_daily_loss = 0.0
        self.current_day = None
        self.daily_start_balance = self.config.starting_balance

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
            if bar.high >= trade.take_profit_3:
                return (True, trade.take_profit_3, ExitReason.TAKE_PROFIT_3)
            if bar.high >= trade.take_profit_2:
                return (True, trade.take_profit_2, ExitReason.TAKE_PROFIT_2)
        else:
            if bar.high >= trade.stop_loss:
                return (True, trade.stop_loss, ExitReason.STOP_LOSS)
            if bar.low <= trade.take_profit_3:
                return (True, trade.take_profit_3, ExitReason.TAKE_PROFIT_3)
            if bar.low <= trade.take_profit_2:
                return (True, trade.take_profit_2, ExitReason.TAKE_PROFIT_2)
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
        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.exit_reason = reason

        pip_value = self._get_pip_value(trade.entry_price)
        standard_lots = trade.lot_size / self.config.units_per_lot
        commission_cost = standard_lots * self.config.commission_per_lot

        if trade.direction == TradeDirection.LONG:
            trade.pips = (exit_price - trade.entry_price) / pip_value
        else:
            trade.pips = (trade.entry_price - exit_price) / pip_value

        trade.profit_loss = (
            trade.pips * standard_lots * pip_value * self.config.units_per_lot
            - commission_cost
        )
        self.balance += trade.profit_loss

        trade.outcome = (
            TradeOutcome.WIN
            if trade.profit_loss > 0.01
            else TradeOutcome.LOSS
            if trade.profit_loss < -0.01
            else TradeOutcome.BREAKEVEN
        )

        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        drawdown = (self.peak_balance - self.balance) / self.peak_balance
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

    def _open_trade(
        self, signal: StrategySignal, bar: Bar, bar_index: int
    ) -> Optional[SimulatedTrade]:
        risk_amount = self.balance * self.config.risk_per_trade_pct
        risk = abs(signal.entry_price - signal.stop_loss)
        if risk == 0:
            return None

        pip_value = self._get_pip_value(signal.entry_price)
        spread_cost = self.config.spread_pips * pip_value
        effective_entry = (
            signal.entry_price + spread_cost
            if signal.direction == TradeDirection.LONG
            else signal.entry_price - spread_cost
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
            total_spread_cost=0.0,
            total_commission_cost=0.0,
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
        import math

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
