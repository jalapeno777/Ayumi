import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import TYPE_CHECKING, Optional

from .models import (
    Order,
    OrderStatus,
    OrderType,
    Position,
    PositionStatus,
    TradeDirection,
)

if TYPE_CHECKING:
    from .api_client import cTraderAPIClient


logger = logging.getLogger(__name__)


@dataclass
class PositionSizeConfig:
    risk_per_trade_pct: float = 0.005
    max_lot_size: float = 1.0
    min_lot_size: float = 0.01
    default_lot_size: float = 0.1


@dataclass
class SlippageModel:
    base_pips: float = 0.1
    random_pips: float = 0.2
    pip_value: float = 0.0001

    def apply(self, price: float, direction: TradeDirection) -> float:
        slippage_pips = self.base_pips + random.random() * self.random_pips
        slippage = slippage_pips * self.pip_value
        if direction == TradeDirection.LONG:
            return price + slippage
        return price - slippage

    def apply_with_spread(
        self, price: float, direction: TradeDirection, spread: float = 0.0
    ) -> float:
        if spread > 0:
            if direction == TradeDirection.LONG:
                price = price + spread / 2
            else:
                price = price - spread / 2
        return self.apply(price, direction)


@dataclass
class OrderExecutionResult:
    success: bool
    order: Order | None = None
    position: Position | None = None
    error_message: str = ""
    rejection_reason: str = ""
    slippage_applied: float = 0.0


class OrderManager:
    def __init__(
        self,
        position_config: PositionSizeConfig | None = None,
        api_client: Optional["cTraderAPIClient"] = None,
    ):
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._position_config = position_config or PositionSizeConfig()
        self._api_client = api_client
        self._slippage_model = SlippageModel()
        self._lock = Lock()
        self._locally_filled_order_ids: set = set()
        self._callbacks: dict[str, list[Callable]] = {
            "on_order_placed": [],
            "on_order_filled": [],
            "on_order_cancelled": [],
            "on_order_rejected": [],
            "on_position_opened": [],
            "on_position_closed": [],
            "on_order_new": [],
            "on_order_partial_fill": [],
        }
        if self._api_client and not self._api_client.is_paper_mode:
            self._wire_live_callbacks()

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

        is_jpy_pair = symbol.upper().endswith("JPY") or symbol.upper().startswith("JPY")
        pip_value = 100.0 if is_jpy_pair else 10000.0
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
        stop_loss: float | None = None,
        take_profit: float | None = None,
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
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str = "",
        spread: float = 0.0,
    ) -> OrderExecutionResult:
        fill_price = self._slippage_model.apply_with_spread(
            entry_price, direction, spread
        )
        slippage_amount = abs(fill_price - entry_price)

        logger.info(
            f"[PAPER] Executing order: {direction.value} {volume} {symbol} "
            f"@ signal={entry_price:.5f} fill={fill_price:.5f} "
            f"(spread={spread:.5f} slippage={slippage_amount:.5f}), "
            f"SL: {stop_loss}, TP: {take_profit}"
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
            filled_price=fill_price,
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
            slippage_applied=slippage_amount,
        )

    def execute_live_order(
        self,
        symbol: str,
        direction: TradeDirection,
        volume: float,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str = "",
    ) -> OrderExecutionResult:
        if not symbol or not symbol.strip():
            return OrderExecutionResult(
                success=False,
                error_message="Symbol is required",
                rejection_reason="validation_error",
            )

        if not volume or volume <= 0:
            return OrderExecutionResult(
                success=False,
                error_message=f"Volume must be positive, got {volume}",
                rejection_reason="validation_error",
            )

        if order_type in (OrderType.LIMIT, OrderType.STOP) and not price:
            return OrderExecutionResult(
                success=False,
                error_message=f"Price is required for {order_type.value} orders",
                rejection_reason="validation_error",
            )

        if not self._api_client or self._api_client.is_paper_mode:
            return OrderExecutionResult(
                success=False,
                error_message="No live API client connected or paper mode is active",
                rejection_reason="no_live_client",
            )

        if not self._api_client.is_connected:
            return OrderExecutionResult(
                success=False,
                error_message="FIX connection not established",
                rejection_reason="not_connected",
            )

        order = self._api_client.send_order(
            symbol=symbol,
            direction=direction,
            order_type=order_type,
            volume=volume,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment=comment,
        )

        if order is None:
            return OrderExecutionResult(
                success=False,
                error_message="Failed to send order via FIX",
                rejection_reason="send_failed",
            )

        with self._lock:
            self._orders[order.order_id] = order

        self._trigger_callback("on_order_placed", order)

        if order.status == OrderStatus.FILLED:
            position = self._create_position_from_order(order)
            if position:
                with self._lock:
                    self._positions[position.position_id] = position
                self._trigger_callback("on_position_opened", position)
            self._trigger_callback("on_order_filled", order)
            with self._lock:
                self._locally_filled_order_ids.add(order.order_id)
            return OrderExecutionResult(
                success=True,
                order=order,
                position=position,
            )

        if order.status == OrderStatus.REJECTED:
            self._trigger_callback("on_order_rejected", order)
            return OrderExecutionResult(
                success=False,
                order=order,
                error_message=order.comment or "Order rejected by broker",
                rejection_reason="broker_rejected",
            )

        return OrderExecutionResult(
            success=True,
            order=order,
            error_message="Order sent, awaiting execution report",
        )

    def set_api_client(self, api_client: Optional["cTraderAPIClient"]):
        self._api_client = api_client
        if self._api_client and not self._api_client.is_paper_mode:
            if not self._api_client.is_connected:
                logger.warning(
                    "cTraderAPIClient not connected — live callbacks will be "
                    "wired on connect. Call connect() before trading."
                )
            self._wire_live_callbacks()

    def _wire_live_callbacks(self):
        if not self._api_client:
            return

        if not self._api_client.is_connected:
            logger.warning("Cannot wire live callbacks: FIX client not connected")
            return

        api = self._api_client

        def on_filled(order, msg, *args):
            if not order:
                return
            with self._lock:
                if order.order_id in self._locally_filled_order_ids:
                    self._locally_filled_order_ids.discard(order.order_id)
                    return
            if order.order_id in self._orders:
                with self._lock:
                    self._orders[order.order_id] = order
                position = self._create_position_from_order(order)
                if position:
                    with self._lock:
                        self._positions[position.position_id] = position
                    self._trigger_callback("on_position_opened", position)
                self._trigger_callback("on_order_filled", order)

        def on_rejected(order, msg, reject_msg, *args):
            if order and order.order_id in self._orders:
                with self._lock:
                    self._orders[order.order_id] = order
                self._trigger_callback("on_order_rejected", order)

        def on_cancelled(order, msg, *args):
            if order and order.order_id in self._orders:
                with self._lock:
                    self._orders[order.order_id] = order
                self._trigger_callback("on_order_cancelled", order)

        api.register_callback("on_order_filled", on_filled)
        api.register_callback("on_order_rejected", on_rejected)
        api.register_callback("on_order_cancelled", on_cancelled)

    def _create_position_from_order(self, order: Order) -> Position | None:
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

    def update_position_id(self, old_id: str, new_id: str):
        """Update a position's ID (e.g., to set broker position_id after fill)."""
        with self._lock:
            if old_id in self._positions:
                pos = self._positions.pop(old_id)
                pos.position_id = new_id
                self._positions[new_id] = pos

    def update_position(
        self,
        position_id: str,
        current_price: float,
        bid: float = 0,
        ask: float = 0,
    ) -> Position | None:
        with self._lock:
            if position_id not in self._positions:
                return None

            position = self._positions[position_id]
            position.current_price = current_price

            if position.direction == TradeDirection.LONG:
                exit_price = bid if bid > 0 else current_price
                position.unrealized_pnl = (
                    (exit_price - position.entry_price) * position.volume * 100000
                )
            else:
                exit_price = ask if ask > 0 else current_price
                position.unrealized_pnl = (
                    (position.entry_price - exit_price) * position.volume * 100000
                )

            if self._check_stop_loss_hit(position, current_price, bid, ask):
                sl_fill = bid if position.direction == TradeDirection.LONG else ask
                self._close_position(
                    position, sl_fill if sl_fill > 0 else position.stop_loss
                )
            elif self._check_take_profit_hit(position, current_price, bid, ask):
                tp_fill = ask if position.direction == TradeDirection.LONG else bid
                self._close_position(
                    position, tp_fill if tp_fill > 0 else position.take_profit
                )

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
        exit_price: float | None = None,
        reason: str = "manual",
    ) -> Position | None:
        with self._lock:
            if position_id not in self._positions:
                return None

            position = self._positions[position_id]
            return self._close_position(position, exit_price, reason)

    def _close_position(
        self,
        position: Position,
        exit_price: float | None = None,
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

    def get_open_positions(self) -> list[Position]:
        with self._lock:
            return [
                p for p in self._positions.values() if p.status == PositionStatus.OPEN
            ]

    def get_position(self, position_id: str) -> Position | None:
        with self._lock:
            return self._positions.get(position_id)

    def get_total_unrealized_pnl(self) -> float:
        with self._lock:
            return sum(
                p.unrealized_pnl
                for p in self._positions.values()
                if p.status == PositionStatus.OPEN
            )

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
