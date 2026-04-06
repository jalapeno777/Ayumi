from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, List

from .config import (
    QuantConfig,
    SizingMode,
)
from .correlation import CorrelationTracker, Position as CorrelationPosition
from .position_sizing import (
    DynamicSizingConfig,
    fixed_fractional,
    kelly_criterion,
    dynamic_sizing,
)
from .regime import (
    volatility_regime as calc_volatility_regime,
    trend_regime as calc_trend_regime,
    combined_regime as calc_combined_regime,
)
from .walk_forward import run_strategy as run_walk_forward
from backtest.engine import Bar
from backtest.strategies import ISignalStrategy


class TradeAction(Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    RESIZE = "resize"


@dataclass(frozen=True)
class TradeDecision:
    action: TradeAction
    lot_size: Optional[float] = None
    regime_confidence: float = 0.0
    correlation_warnings: tuple[str, ...] = ()
    sizing_mode: str = ""
    reject_reason: str = ""


@dataclass(frozen=True)
class ValidationResult:
    go_nogo: bool
    walk_forward_passed: bool
    aggregated_metrics: Any = None
    per_window_metrics: tuple = ()
    details: str = ""


@dataclass
class PortfolioState:
    balance: float = 100_000.0
    open_positions: dict[str, float] = field(default_factory=dict)
    win_streak: int = 0
    loss_streak: int = 0
    recent_pnl: float = 0.0
    total_wins: int = 0
    total_losses: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0


class QuantPipeline:
    def __init__(self, config: QuantConfig):
        self._config = config
        self._portfolio = PortfolioState()

        self._corr_tracker: Optional[CorrelationTracker] = None
        if config.correlation.enabled:
            self._corr_tracker = CorrelationTracker(
                pairs=list(config.correlation.pairs),
                window=config.correlation.window,
                threshold=config.correlation.threshold,
            )

        self._atr_history: list[float] = []
        self._high_history: list[float] = []
        self._low_history: list[float] = []
        self._close_history: list[float] = []

    def pre_trade_check(
        self,
        signal_symbol: str,
        entry_price: float,
        stop_loss: float,
        bar_time: Optional[datetime] = None,
    ) -> TradeDecision:
        regime_confidence = 1.0
        correlation_warnings: list[str] = []
        reject_reason = ""

        if self._config.regime.enabled:
            regime_confidence = self._check_regime(bar_time)
            if regime_confidence < self._config.regime.min_confidence:
                reject_reason = (
                    f"Regime confidence {regime_confidence:.2f} below "
                    f"minimum {self._config.regime.min_confidence:.2f}"
                )
                return TradeDecision(
                    action=TradeAction.REJECT,
                    regime_confidence=regime_confidence,
                    reject_reason=reject_reason,
                )

        if (
            self._config.correlation.enabled
            and self._corr_tracker is not None
            and self._corr_tracker.is_initialized
        ):
            positions = [
                CorrelationPosition(
                    symbol=sym,
                    exposure=lot,
                )
                for sym, lot in self._portfolio.open_positions.items()
            ]
            if positions:
                correlation_warnings = self._corr_tracker.check_exposure(positions)

        lot_size: Optional[float] = None
        sizing_mode = ""
        if self._config.position_sizing.enabled and stop_loss != 0.0:
            base_lot = self._calculate_base_lot(entry_price, stop_loss)
            if base_lot <= 0:
                reject_reason = "Position sizing returned zero lots"
                return TradeDecision(
                    action=TradeAction.REJECT,
                    regime_confidence=regime_confidence,
                    correlation_warnings=tuple(correlation_warnings),
                    reject_reason=reject_reason,
                )

            lot_size = self._apply_sizing_mode(base_lot)
            sizing_mode = self._config.position_sizing.mode.value

        if lot_size is not None and lot_size != self._calculate_base_lot(
            entry_price, stop_loss
        ):
            action = TradeAction.RESIZE
        else:
            action = TradeAction.ACCEPT

        return TradeDecision(
            action=action,
            lot_size=lot_size,
            regime_confidence=regime_confidence,
            correlation_warnings=tuple(correlation_warnings),
            sizing_mode=sizing_mode,
        )

    def validate_strategy(
        self,
        strategy: ISignalStrategy,
        bars: List[Bar],
    ) -> ValidationResult:
        if not self._config.walk_forward.enabled:
            return ValidationResult(
                go_nogo=True,
                walk_forward_passed=True,
                details="Walk-forward validation disabled in config",
            )

        results = run_walk_forward(
            strategy=strategy,
            bars=bars,
            n_windows=self._config.walk_forward.n_windows,
            train_ratio=self._config.walk_forward.train_ratio,
            val_ratio=self._config.walk_forward.val_ratio,
            overlap_ratio=self._config.walk_forward.overlap_ratio,
        )

        return ValidationResult(
            go_nogo=results.go_nogo,
            walk_forward_passed=results.go_nogo,
            aggregated_metrics=results.aggregated,
            per_window_metrics=tuple(results.per_window),
            details=f"Walk-forward: {sum(1 for m in results.per_window if m.passed_go_nogo)}/{len(results.per_window)} windows passed",
        )

    def on_trade_closed(
        self,
        pnl: float,
    ) -> None:
        if pnl > 0:
            self._portfolio.win_streak += 1
            self._portfolio.loss_streak = 0
            self._portfolio.total_wins += 1
            self._portfolio.avg_win = (
                self._portfolio.avg_win * (self._portfolio.total_wins - 1) + pnl
            ) / self._portfolio.total_wins
        elif pnl < 0:
            self._portfolio.loss_streak += 1
            self._portfolio.win_streak = 0
            self._portfolio.total_losses += 1
            self._portfolio.avg_loss = (
                self._portfolio.avg_loss * (self._portfolio.total_losses - 1) + abs(pnl)
            ) / self._portfolio.total_losses

        self._portfolio.recent_pnl = pnl

    def update_bars(
        self,
        high: float,
        low: float,
        close: float,
        atr: float,
    ) -> None:
        self._atr_history.append(atr)
        self._high_history.append(high)
        self._low_history.append(low)
        self._close_history.append(close)

    def update_correlation_prices(self, prices: dict[str, float]) -> None:
        if self._corr_tracker is not None:
            self._corr_tracker.update(prices)

    @property
    def portfolio(self) -> PortfolioState:
        return self._portfolio

    @portfolio.setter
    def portfolio(self, value: PortfolioState) -> None:
        self._portfolio = value

    def _check_regime(self, bar_time: Optional[datetime] = None) -> float:
        vol_result = calc_volatility_regime(
            self._atr_history,
            lookback=self._config.regime.atr_lookback,
        )
        trend_result = calc_trend_regime(
            self._high_history,
            self._low_history,
            self._close_history,
            adx_period=self._config.regime.adx_period,
        )

        from .regime import session_regime as calc_session_regime

        hour = bar_time.hour if bar_time else 12
        day_of_week = bar_time.weekday() if bar_time else 0
        session_result = calc_session_regime(hour, day_of_week)

        combined = calc_combined_regime(vol_result, trend_result, session_result)
        return combined.confidence

    def _calculate_base_lot(self, entry_price: float, stop_loss: float) -> float:
        sizing_cfg = self._config.position_sizing
        if (
            sizing_cfg.mode == SizingMode.KELLY
            and self._portfolio.total_wins + self._portfolio.total_losses > 0
        ):
            total_trades = self._portfolio.total_wins + self._portfolio.total_losses
            win_rate = self._portfolio.total_wins / total_trades
            avg_win = self._portfolio.avg_win if self._portfolio.avg_win > 0 else 1.0
            avg_loss = self._portfolio.avg_loss if self._portfolio.avg_loss > 0 else 1.0
            kelly_frac = kelly_criterion(win_rate, avg_win, avg_loss)
            if kelly_frac <= 0:
                return fixed_fractional(
                    self._portfolio.balance,
                    sizing_cfg.risk_pct,
                    entry_price,
                    stop_loss,
                )
            risk_amount = self._portfolio.balance * kelly_frac
            stop_distance = abs(entry_price - stop_loss)
            if stop_distance == 0:
                return 0.0
            return risk_amount / (stop_distance * 100_000)

        return fixed_fractional(
            self._portfolio.balance,
            sizing_cfg.risk_pct,
            entry_price,
            stop_loss,
        )

    def _apply_sizing_mode(self, base_lot: float) -> float:
        sizing_cfg = self._config.position_sizing

        if sizing_cfg.mode == SizingMode.DYNAMIC:
            dyn_config = DynamicSizingConfig(
                min_multiplier=sizing_cfg.dynamic_min_multiplier,
                max_multiplier=sizing_cfg.dynamic_max_multiplier,
                loss_reduction=sizing_cfg.dynamic_loss_reduction,
                win_increase=sizing_cfg.dynamic_win_increase,
                max_streak_impact=sizing_cfg.dynamic_max_streak_impact,
            )
            return dynamic_sizing(
                base_size=base_lot,
                recent_pnl=self._portfolio.recent_pnl,
                win_streak=self._portfolio.win_streak,
                loss_streak=self._portfolio.loss_streak,
                config=dyn_config,
            )

        return base_lot
