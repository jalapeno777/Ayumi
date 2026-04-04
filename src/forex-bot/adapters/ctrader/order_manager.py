import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Callable
from threading import Lock

from .models import (
    Order,
    Position,
    TradeDirection,
    OrderType,
    OrderStatus,
    PositionStatus,
)


logger = logging.getLogger(__name__)


@dataclass
class PositionSizeConfig:
    risk_per_trade_pct: float = 0.005
    max_lot_size: float = 1.0
    min_lot_size: float = 0.01
    default_lot_size: float = 0.1


@dataclass
class OrderExecutionResult:
    success: bool
    order: Optional[Order] = None
    position: Optional[Position] = None
    error_message: str = ""
    rejection_reason: str = ""


class OrderManager:
    def __init__(self, position_config: Optional[PositionSizeConfig] = None):
        self._positions: Dict[str, Position] = {}
        self._orders: Dict[str, Order] = {}
        self._position_config = position_config or PositionSizeConfig()
        self._lock = Lock()
        self._callbacks: Dict[str, List[Callable]] = {
            "on_order_placed": [],
            "on_order_filled": [],
            "on_order_cancelled": [],
            "on_order_rejected": [],
            "on_position_opened": [],
            "on_position_closed": [],
        }

    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        symbol: str = "EURUSD",
    ) -> float:
        risk_amount = account_balance * self._position_config.risk_per_trade_pct
        sl_distance = abs(entry_price - stop_loss)

        if sl_distance == 0:
            logger.warning("Stop loss distance is zero, using default lot size")
            return self._position_config.default_lot_size

        pip_value = 10.0 if entry_price < 1 else 10.0
        sl_pips = sl_distance * pip_value

        if sl_pips == 0:
            return self._position_config.default_lot_size

        lot_size = risk_amount / (sl_pips * 10)

        lot_size = max(
            self._position_config.min_lot_size,
            min(lot_size, self._position_config.max_lot_size),
        )

        return round(lot_size, 2)

    def execute_market_order(
        self,
        symbol: str,
        direction: TradeDirection,
        volume: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "",
    ) -> OrderExecutionResult:
        order = Order(
            order_id=f"ORD_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
            symbol=symbol,
            direction=direction,
            order_type=OrderType.MARKET,
            volume=volume,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status=OrderStatus.PENDING,
            comment=comment,
        )

        with self._lock:
            self._orders[order.order_id] = order

        self._trigger_callback("on_order_placed", order)

        order.status = OrderStatus.FILLED
        order.filled_at = datetime.utcnow()
        order.filled_price = 0

        position = self._create_position_from_order(order)
        if position:
            with self._lock:
                self._positions[position.position_id] = position
            self._trigger_callback("on_position_opened", position)

        self._trigger_callback("on_order_filled", order)

        return OrderExecutionResult(
            success=True,
            order=order,
            position=position,
        )

    def execute_paper_order(
        self,
        symbol: str,
        direction: TradeDirection,
        volume: float,
        entry_price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "",
    ) -> OrderExecutionResult:
        logger.info(
            f"[PAPER] Executing order: {direction.value} {volume} {symbol} @ {entry_price}, SL: {stop_loss}, TP: {take_profit}"
        )

        order = Order(
            order_id=f"PAPER_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
            symbol=symbol,
            direction=direction,
            order_type=OrderType.MARKET,
            volume=volume,
            price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status=OrderStatus.FILLED,
            filled_at=datetime.utcnow(),
            filled_price=entry_price,
            comment=f"[PAPER MODE] {comment}",
        )

        with self._lock:
            self._orders[order.order_id] = order

        position = self._create_position_from_order(order)
        if position:
            with self._lock:
                self._positions[position.position_id] = position

        self._trigger_callback("on_order_filled", order)
        if position:
            self._trigger_callback("on_position_opened", position)

        return OrderExecutionResult(
            success=True,
            order=order,
            position=position,
        )

    def _create_position_from_order(self, order: Order) -> Optional[Position]:
        if order.status != OrderStatus.FILLED:
            return None

        position_id = f"POS_{order.order_id}"
        position = Position(
            position_id=position_id,
            symbol=order.symbol,
            direction=order.direction,
            volume=order.volume,
            entry_price=order.filled_price or order.price or 0,
            current_price=order.filled_price or order.price or 0,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            opened_at=order.filled_at or datetime.utcnow(),
            comment=order.comment,
        )
        return position

    def update_position(
        self,
        position_id: str,
        current_price: float,
        bid: float = 0,
        ask: float = 0,
    ) -> Optional[Position]:
        with self._lock:
            if position_id not in self._positions:
                return None

            position = self._positions[position_id]
            position.current_price = current_price

            if position.direction == TradeDirection.LONG:
                position.unrealized_pnl = (
                    (current_price - position.entry_price) * position.volume * 100000
                )
            else:
                position.unrealized_pnl = (
                    (position.entry_price - current_price) * position.volume * 100000
                )

            if self._check_stop_loss_hit(position, current_price, bid, ask):
                self._close_position(position, position.stop_loss or current_price)
            elif self._check_take_profit_hit(position, current_price, bid, ask):
                self._close_position(position, position.take_profit or current_price)

            return position

    def _check_stop_loss_hit(
        self, position: Position, current_price: float, bid: float, ask: float
    ) -> bool:
        if position.stop_loss is None:
            return False

        if position.direction == TradeDirection.LONG:
            return bid > 0 and bid <= position.stop_loss
        else:
            return ask > 0 and ask >= position.stop_loss

    def _check_take_profit_hit(
        self, position: Position, current_price: float, bid: float, ask: float
    ) -> bool:
        if position.take_profit is None:
            return False

        if position.direction == TradeDirection.LONG:
            return ask > 0 and ask >= position.take_profit
        else:
            return bid > 0 and bid <= position.take_profit

    def close_position(
        self,
        position_id: str,
        exit_price: Optional[float] = None,
        reason: str = "manual",
    ) -> Optional[Position]:
        with self._lock:
            if position_id not in self._positions:
                return None

            position = self._positions[position_id]
            return self._close_position(position, exit_price, reason)

    def _close_position(
        self,
        position: Position,
        exit_price: Optional[float] = None,
        reason: str = "unknown",
    ) -> Position:
        exit_price = exit_price or position.current_price

        if position.direction == TradeDirection.LONG:
            pnl = (exit_price - position.entry_price) * position.volume * 100000
        else:
            pnl = (position.entry_price - exit_price) * position.volume * 100000

        position.status = PositionStatus.CLOSED
        position.closed_at = datetime.utcnow()
        position.closed_price = exit_price
        position.closed_pnl = pnl

        logger.info(
            f"Position {position.position_id} closed: {reason} @ {exit_price}, PnL: {pnl:.2f}"
        )

        self._trigger_callback("on_position_closed", position)
        return position

    def get_open_positions(self) -> List[Position]:
        with self._lock:
            return [
                p for p in self._positions.values() if p.status == PositionStatus.OPEN
            ]

    def get_position(self, position_id: str) -> Optional[Position]:
        with self._lock:
            return self._positions.get(position_id)

    def get_total_unrealized_pnl(self) -> float:
        with self._lock:
            return sum(p.unrealized_pnl for p in self.get_open_positions())

    def get_total_realized_pnl(self) -> float:
        with self._lock:
            return sum(
                p.closed_pnl
                for p in self._positions.values()
                if p.status == PositionStatus.CLOSED
            )

    def register_callback(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callback(self, event: str, *args, **kwargs):
        if event in self._callbacks:
            for callback in self._callbacks[event]:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Callback error for {event}: {e}")

    @property
    def position_count(self) -> int:
        return len(self.get_open_positions())
