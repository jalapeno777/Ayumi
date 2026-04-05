from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .config import QuantConfig, SizingMode
from .correlation import CorrelationTracker, Position as CorrelationPosition
from .position_sizing import (
    DynamicSizingConfig,
    fixed_fractional,
    kelly_criterion,
    dynamic_sizing,
)
from .regime import (
    VolatilityRegime,
    volatility_regime,
    trend_regime,
    session_regime,
    combined_regime,
)
from .walk_forward import run_strategy as run_walk_forward, WalkForwardResults


class TradeAction(Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    RESIZE = "resize"


@dataclass
class TradeDecision:
    action: TradeAction
    reason: str = ""
    adjusted_lot_size: Optional[float] = None
    regime_confidence: float = 1.0
    correlation_warnings: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    passed: bool
    results: Optional[WalkForwardResults] = None
    summary: str = ""


@dataclass
class PortfolioState:
    balance: float = 0.0
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    win_streak: int = 0
    loss_streak: int = 0
    recent_pnl: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    total_trades: int = 0


@dataclass
class TradeResult:
    pnl: float = 0.0
    is_win: bool = False
    pair: str = ""


class QuantPipeline:
    def __init__(self, config: QuantConfig):
        self._config = config
        self._correlation_tracker: Optional[CorrelationTracker] = None
        self._portfolio = PortfolioState()

        if config.correlation_enabled and config.correlation.pairs:
            self._correlation_tracker = CorrelationTracker(
                pairs=config.correlation.pairs,
                window=config.correlation.window,
                threshold=config.correlation.threshold,
            )

    @property
    def config(self) -> QuantConfig:
        return self._config

    @property
    def portfolio(self) -> PortfolioState:
        return self._portfolio

    def pre_trade_check(
        self,
        signal: Any,
        bars: list[Any],
        portfolio_state: Optional[PortfolioState] = None,
    ) -> TradeDecision:
        if portfolio_state is not None:
            self._portfolio = portfolio_state

        atr_series = self._extract_atr_series(bars)
        high_series = self._extract_high_series(bars)
        low_series = self._extract_low_series(bars)
        close_series = self._extract_close_series(bars)
        hour, day_of_week = self._extract_time(bars)

        if self._config.regime_enabled:
            vol_result = volatility_regime(
                atr_series,
                lookback=50,
                thresholds=self._config.regime.volatility_thresholds,
            )
            trend_result = trend_regime(high_series, low_series, close_series)
            session_result = session_regime(hour, day_of_week)
            combined = combined_regime(vol_result, trend_result, session_result)

            if self._config.regime.block_extreme_volatility:
                if vol_result.regime == VolatilityRegime.EXTREME:
                    return TradeDecision(
                        action=TradeAction.REJECT,
                        reason=f"Extreme volatility detected (percentile={vol_result.percentile:.1f})",
                        regime_confidence=combined.confidence,
                    )

            if combined.confidence < self._config.regime.min_confidence:
                return TradeDecision(
                    action=TradeAction.REJECT,
                    reason=f"Low regime confidence ({combined.confidence:.2f} < {self._config.regime.min_confidence})",
                    regime_confidence=combined.confidence,
                )
        else:
            combined = None

        correlation_warnings: list[str] = []
        if self._config.correlation_enabled and self._correlation_tracker is not None:
            symbol = self._get_signal_symbol(signal)
            if symbol:
                prices = self._extract_latest_prices(bars, symbol)
                if prices:
                    self._correlation_tracker.update(prices)

            positions = [
                CorrelationPosition(
                    symbol=p.get("symbol", ""),
                    exposure=p.get("exposure", 0.0),
                )
                for p in self._portfolio.open_positions
            ]
            warnings = self._correlation_tracker.check_exposure(positions)
            correlation_warnings = warnings

            total_exposure = self._correlation_tracker.get_portfolio_exposure(positions)
            if (
                self._config.correlation.max_correlated_exposure > 0
                and total_exposure > self._config.correlation.max_correlated_exposure
            ):
                return TradeDecision(
                    action=TradeAction.REJECT,
                    reason=f"Portfolio correlation exposure too high ({total_exposure:.2f})",
                    correlation_warnings=correlation_warnings,
                    regime_confidence=combined.confidence if combined else 1.0,
                )

        entry_price = self._get_signal_entry(signal)
        stop_loss = self._get_signal_stop_loss(signal)
        balance = self._portfolio.balance

        lot_size: Optional[float] = None
        if self._config.position_sizing_enabled and entry_price and stop_loss:
            sizing_cfg = self._config.position_sizing
            base_lot = fixed_fractional(
                balance, sizing_cfg.risk_pct, entry_price, stop_loss
            )

            if sizing_cfg.mode == SizingMode.KELLY and self._portfolio.total_trades > 10:
                kelly_frac = kelly_criterion(
                    self._portfolio.win_rate,
                    self._portfolio.avg_win,
                    self._portfolio.avg_loss,
                )
                if kelly_frac > 0:
                    base_lot = fixed_fractional(
                        balance, kelly_frac * 100, entry_price, stop_loss
                    )

            if sizing_cfg.mode == SizingMode.DYNAMIC:
                dyn_cfg = DynamicSizingConfig(
                    min_multiplier=sizing_cfg.min_multiplier,
                    max_multiplier=sizing_cfg.max_multiplier,
                    loss_reduction=sizing_cfg.loss_reduction,
                    win_increase=sizing_cfg.win_increase,
                    max_streak_impact=sizing_cfg.max_streak_impact,
                )
                base_lot = dynamic_sizing(
                    base_lot,
                    self._portfolio.recent_pnl,
                    self._portfolio.win_streak,
                    self._portfolio.loss_streak,
                    dyn_cfg,
                )

            if base_lot > 0:
                lot_size = base_lot

        if lot_size is not None and lot_size != self._get_signal_volume(signal):
            return TradeDecision(
                action=TradeAction.RESIZE,
                reason="Position size adjusted by quant pipeline",
                adjusted_lot_size=lot_size,
                regime_confidence=combined.confidence if combined else 1.0,
                correlation_warnings=correlation_warnings,
            )

        return TradeDecision(
            action=TradeAction.ACCEPT,
            adjusted_lot_size=lot_size,
            regime_confidence=combined.confidence if combined else 1.0,
            correlation_warnings=correlation_warnings,
        )

    def validate_strategy(
        self,
        strategy_fn: Callable[..., list[dict[str, Any]]],
        data: list[Any],
    ) -> ValidationResult:
        if not self._config.walk_forward_enabled:
            return ValidationResult(
                passed=True,
                summary="Walk-forward validation disabled",
            )

        wf_cfg = self._config.walk_forward
        results = run_walk_forward(
            strategy_fn,
            data,
            n_windows=wf_cfg.n_windows,
            train_ratio=wf_cfg.train_ratio,
            val_ratio=wf_cfg.val_ratio,
            overlap_ratio=wf_cfg.overlap_ratio,
        )

        summary_parts = [
            f"Walk-forward: {results.per_window.__len__()} windows",
            f"GO/NO-GO: {'PASS' if results.go_nogo else 'FAIL'}",
        ]
        if results.aggregated:
            agg = results.aggregated
            summary_parts.append(
                f"Mean WR: {agg.mean_win_rate:.2%}, PF: {agg.mean_profit_factor:.2f}"
            )

        return ValidationResult(
            passed=results.go_nogo,
            results=results,
            summary=" | ".join(summary_parts),
        )

    def on_trade_closed(self, trade_result: TradeResult) -> None:
        if trade_result.is_win:
            self._portfolio.win_streak += 1
            self._portfolio.loss_streak = 0
        else:
            self._portfolio.loss_streak += 1
            self._portfolio.win_streak = 0

        self._portfolio.recent_pnl = trade_result.pnl
        self._portfolio.total_trades += 1

        wins = max(self._portfolio.total_trades * self._portfolio.win_rate, 0)
        if trade_result.is_win:
            wins += 1
        total = self._portfolio.total_trades
        if total > 0:
            self._portfolio.win_rate = wins / total

    def update_portfolio(self, portfolio_state: PortfolioState) -> None:
        self._portfolio = portfolio_state

    @staticmethod
    def _extract_atr_series(bars: list[Any]) -> list[float]:
        if not bars:
            return []
        atr_values: list[float] = []
        for i in range(1, len(bars)):
            bar = bars[i]
            prev = bars[i - 1]
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev.close),
                abs(bar.low - prev.close),
            )
            atr_values.append(tr)
        return atr_values

    @staticmethod
    def _extract_high_series(bars: list[Any]) -> list[float]:
        return [b.high for b in bars]

    @staticmethod
    def _extract_low_series(bars: list[Any]) -> list[float]:
        return [b.low for b in bars]

    @staticmethod
    def _extract_close_series(bars: list[Any]) -> list[float]:
        return [b.close for b in bars]

    @staticmethod
    def _extract_time(bars: list[Any]) -> tuple[int, int]:
        if not bars:
            return 12, 0
        last = bars[-1]
        t = getattr(last, "time", None)
        if t is None:
            return 12, 0
        return t.hour, t.weekday()

    @staticmethod
    def _get_signal_symbol(signal: Any) -> str:
        return getattr(signal, "symbol", "")

    @staticmethod
    def _get_signal_entry(signal: Any) -> Optional[float]:
        entry = getattr(signal, "entry_price", None)
        return entry

    @staticmethod
    def _get_signal_stop_loss(signal: Any) -> Optional[float]:
        sl = getattr(signal, "stop_loss", None)
        return sl

    @staticmethod
    def _get_signal_volume(signal: Any) -> Optional[float]:
        return getattr(signal, "volume", None)

    @staticmethod
    def _extract_latest_prices(bars: list[Any], symbol: str) -> Optional[dict[str, float]]:
        if not bars:
            return None
        last = bars[-1]
        return {symbol: last.close}
