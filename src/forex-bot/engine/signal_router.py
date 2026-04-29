from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from .protocol import CanonicalSignal

if TYPE_CHECKING:
    from adapters.ctrader.order_manager import OrderManager
    from adapters.ctrader.portfolio_risk_guard import PortfolioRiskGuard

logger = logging.getLogger(__name__)


@dataclass
class RouteResult:
    action: str
    signal: CanonicalSignal
    reason: str = ""
    order: Optional[object] = None
    position: Optional[object] = None


class SignalRouter:
    def __init__(
        self,
        portfolio_risk: PortfolioRiskGuard,
        order_manager: OrderManager,
        cooldown_sec: float = 60.0,
    ):
        self._portfolio_risk = portfolio_risk
        self._order_manager = order_manager
        self._cooldown_sec = cooldown_sec
        self._strategy_last_routed: dict[str, float] = {}
        self._callbacks: list[tuple[str, callable]] = []

    def route(self, signal: CanonicalSignal, spread: float = 0.0) -> RouteResult:
        if spread == 0.0:
            logger.warning(
                "SignalRouter.route() called with spread=0.0, spread validation bypassed"
            )
        if signal.confidence < 0.0:
            return RouteResult(
                action="rejected",
                signal=signal,
                reason="Negative confidence",
            )

        if signal.take_profit_1 is None or signal.take_profit_1 <= 0:
            logger.warning(
                "Signal %s has no valid take_profit_1, rejecting", signal.strategy_id
            )
            return RouteResult(
                action="invalid_signal",
                signal=signal,
                reason="take_profit_1 is zero or None",
            )

        for pos in self._order_manager.get_open_positions():
            if pos.symbol == signal.symbol and pos.status.value == "open":
                return RouteResult(
                    action="deduped",
                    signal=signal,
                    reason=f"Position already open on {signal.symbol}",
                )

        now = _time.monotonic()
        last = self._strategy_last_routed.get(signal.strategy_id, 0.0)
        elapsed = now - last
        if elapsed < self._cooldown_sec:
            remaining = self._cooldown_sec - elapsed
            return RouteResult(
                action="cooldown",
                signal=signal,
                reason=f"Strategy {signal.strategy_id} cooldown ({remaining:.0f}s remaining)",
            )

        risk_result = self._portfolio_risk.check_signal(signal)
        if not risk_result.allowed:
            return RouteResult(
                action="risk_blocked",
                signal=signal,
                reason=risk_result.message,
            )

        volume = self._order_manager.calculate_position_size(
            self._portfolio_risk.current_balance,
            signal.entry_price,
            signal.stop_loss,
            signal.symbol,
        )

        tp = signal.take_profit_1
        trade_check = self._portfolio_risk.check_trade_allowed(signal, volume)
        if not trade_check.allowed:
            return RouteResult(
                action="risk_blocked",
                signal=signal,
                reason=trade_check.message,
            )

        exec_result = self._execute_order(signal, volume, spread)

        if exec_result.success:
            self._strategy_last_routed[signal.strategy_id] = _time.monotonic()
            logger.info(
                "Routed: %s %s %s @ %.5f vol=%.2f conf=%.2f",
                signal.direction.value,
                signal.symbol,
                signal.strategy_id,
                signal.entry_price,
                volume,
                signal.confidence,
            )
            self._trigger_callback(
                "on_signal_routed",
                RouteResult(
                    action="executed",
                    signal=signal,
                    reason="",
                    order=exec_result.order,
                    position=exec_result.position,
                ),
            )
            return RouteResult(
                action="executed",
                signal=signal,
                order=exec_result.order,
                position=exec_result.position,
            )
        else:
            return RouteResult(
                action="rejected",
                signal=signal,
                reason=f"Order execution failed: {getattr(exec_result, 'error_message', 'unknown')}",
            )

    def _execute_order(
        self, signal: CanonicalSignal, volume: float, spread: float = 0.0
    ):
        from adapters.ctrader.models import TradeDirection

        direction = TradeDirection(signal.direction.value)
        return self._order_manager.execute_paper_order(
            symbol=signal.symbol,
            direction=direction,
            volume=volume,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit_1,
            comment=f"[{signal.strategy_id}] {signal.rationale}",
            spread=spread,
        )

    def register_callback(self, event: str, callback: callable):
        self._callbacks.append((event, callback))

    def _trigger_callback(self, event: str, *args, **kwargs):
        for evt, callback in self._callbacks:
            if evt == event:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    logger.error("SignalRouter callback error for %s: %s", event, e)
