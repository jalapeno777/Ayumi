import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import TYPE_CHECKING, Any, List, Optional

from .models import Order, Position, TradeSignal
from .order_manager import OrderExecutionResult, OrderManager, PositionSizeConfig
from .risk_guard import FTMOConfig, RiskGuard

if TYPE_CHECKING:
    from .api_client import cTraderAPIClient


logger = logging.getLogger(__name__)


@dataclass
class PaperTradeResult:
    success: bool
    signal: TradeSignal
    order: Order | None = None
    position: Position | None = None
    rejection_reason: str = ""
    risk_guard_result: Any | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PaperTradingStats:
    total_signals_processed: int = 0
    trades_executed: int = 0
    trades_rejected: int = 0
    signals_blocked_by_risk: int = 0
    current_balance: float = 100000.0
    starting_balance: float = 100000.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


class PaperTrader:
    def __init__(
        self,
        ftmo_config: FTMOConfig | None = None,
        position_config: PositionSizeConfig | None = None,
        starting_balance: float = 100000.0,
        api_client: Optional["cTraderAPIClient"] = None,
    ):
        self._ftmo_config = ftmo_config or FTMOConfig()
        self._position_config = position_config or PositionSizeConfig()
        self._api_client = api_client
        self._live_mode_enabled = (
            api_client is not None and not api_client.is_paper_mode
        )
        self._order_manager = OrderManager(self._position_config, api_client=api_client)
        self._risk_guard = RiskGuard(self._ftmo_config, starting_balance)
        self._starting_balance = starting_balance
        self._current_balance = starting_balance
        self._lock = RLock()
        self._stats = PaperTradingStats(
            starting_balance=starting_balance, current_balance=starting_balance
        )
        self._trade_history: list[PaperTradeResult] = []
        self._callbacks: list[tuple[str, Callable]] = []
        self._running = False
        self._last_update: datetime | None = None

    @property
    def is_live_mode(self) -> bool:
        return self._live_mode_enabled

    def process_signal(self, signal: TradeSignal) -> PaperTradeResult:
        with self._lock:
            self._stats.total_signals_processed += 1

            risk_result = self._risk_guard.check_signal(signal)
            if not risk_result.allowed:
                self._stats.signals_blocked_by_risk += 1
                logger.warning(f"Signal blocked by risk guard: {risk_result.message}")
                return PaperTradeResult(
                    success=False,
                    signal=signal,
                    rejection_reason=risk_result.message,
                    risk_guard_result=risk_result,
                )

            volume = self._order_manager.calculate_position_size(
                self._current_balance,
                signal.entry_price,
                signal.stop_loss,
                signal.symbol,
            )

            trade_check = self._risk_guard.check_trade_allowed(
                direction=signal.direction,
                volume=volume,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit_1,
                account_balance=self._current_balance,
            )
            if not trade_check.allowed:
                self._stats.signals_blocked_by_risk += 1
                logger.warning(f"Trade blocked by risk: {trade_check.message}")
                return PaperTradeResult(
                    success=False,
                    signal=signal,
                    rejection_reason=trade_check.message,
                    risk_guard_result=trade_check,
                )

            trade_result = self._execute_order(
                signal=signal,
                volume=volume,
            )

            if trade_result.success:
                self._stats.trades_executed += 1
                position = trade_result.position
                if position:
                    self._current_balance += position.unrealized_pnl
                    self._stats.current_balance = self._current_balance
                    self._risk_guard.update_balance(self._current_balance)

                result = PaperTradeResult(
                    success=True,
                    signal=signal,
                    order=trade_result.order,
                    position=position,
                    risk_guard_result=risk_result,
                )
                self._trade_history.append(result)
                logger.info(
                    f"[PAPER] Executed: {signal.direction.value} {volume} {signal.symbol} @ {signal.entry_price}"
                )
                self._trigger_callback("on_trade_executed", result)
            else:
                self._stats.trades_rejected += 1
                result = PaperTradeResult(
                    success=False,
                    signal=signal,
                    rejection_reason="Order execution failed",
                    risk_guard_result=risk_result,
                )
                self._trade_history.append(result)

            return result

    def _execute_order(
        self, signal: TradeSignal, volume: float
    ) -> OrderExecutionResult:
        if self.is_live_mode:
            return self._order_manager.execute_live_order(
                symbol=signal.symbol,
                direction=signal.direction,
                volume=volume,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit_1,
                comment=signal.rationale,
            )
        return self._order_manager.execute_paper_order(
            symbol=signal.symbol,
            direction=signal.direction,
            volume=volume,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit_1,
            comment=signal.rationale,
        )

    def set_api_client(self, api_client: Optional["cTraderAPIClient"]):
        self._api_client = api_client
        self._live_mode_enabled = (
            api_client is not None and not api_client.is_paper_mode
        )
        self._order_manager.set_api_client(api_client)

    def update_market_prices(self, prices: dict):
        with self._lock:
            total_unrealized = 0.0
            for position in self._order_manager.get_open_positions():
                if position.symbol in prices:
                    current_price = prices[position.symbol]
                    self._order_manager.update_position(
                        position.position_id, current_price
                    )
                    updated_pos = self._order_manager.get_position(position.position_id)
                    if updated_pos:
                        total_unrealized += updated_pos.unrealized_pnl

            self._stats.unrealized_pnl = total_unrealized
            self._current_balance = (
                self._starting_balance + self._stats.realized_pnl + total_unrealized
            )
            self._stats.current_balance = self._current_balance
            self._risk_guard.update_balance(self._current_balance)
            self._last_update = datetime.utcnow()

    def close_position(
        self, position_id: str, exit_price: float, reason: str = "manual"
    ) -> bool:
        with self._lock:
            position = self._order_manager.close_position(
                position_id, exit_price, reason
            )
            if position:
                self._stats.realized_pnl += position.closed_pnl
                self._current_balance += position.closed_pnl
                self._stats.current_balance = self._current_balance

                is_win = position.closed_pnl > 0
                self._risk_guard.record_trade(position.closed_pnl, is_win)

                self._trigger_callback("on_position_closed", position)
                logger.info(
                    f"[PAPER] Closed: {position.symbol} @ {exit_price}, PnL: {position.closed_pnl:.2f}"
                )
                return True
            return False

    def close_all_positions(self, exit_price: float, reason: str = "force_close"):
        with self._lock:
            positions = self._order_manager.get_open_positions()
            for position in positions:
                self.close_position(position.position_id, exit_price, reason)

    def get_open_positions(self) -> list[Position]:
        return self._order_manager.get_open_positions()

    def get_stats(self) -> PaperTradingStats:
        with self._lock:
            return PaperTradingStats(
                total_signals_processed=self._stats.total_signals_processed,
                trades_executed=self._stats.trades_executed,
                trades_rejected=self._stats.trades_rejected,
                signals_blocked_by_risk=self._stats.signals_blocked_by_risk,
                current_balance=self._current_balance,
                starting_balance=self._starting_balance,
                realized_pnl=self._stats.realized_pnl,
                unrealized_pnl=self._stats.unrealized_pnl,
            )

    def get_risk_guard_stats(self) -> dict:
        return self._risk_guard.get_stats()

    def reset(self):
        with self._lock:
            self._current_balance = self._starting_balance
            self._stats = PaperTradingStats(
                starting_balance=self._starting_balance,
                current_balance=self._starting_balance,
            )
            self._trade_history.clear()
            self._risk_guard.reset_circuit_breaker()
            self._risk_guard.reset_daily_tracking()
            logger.info("[PAPER] Trading reset")

    def register_callback(self, event: str, callback: Callable):
        if event not in ["on_trade_executed", "on_position_closed"]:
            raise ValueError(f"Unknown event: {event}")
        self._callbacks.append((event, callback))

    def _trigger_callback(self, event: str, *args, **kwargs):
        for evt, callback in self._callbacks:
            if evt == event:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Callback error for {event}: {e}")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def balance(self) -> float:
        return self._current_balance
