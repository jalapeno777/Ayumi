from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from hybrid.risk_manager import RiskAction, RiskDecision, RiskManager
from hybrid.signal import HumanSignal, SignalType


class OrderStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass
class OrderResult:
    success: bool
    order_id: str = ""
    position_id: str = ""
    signal: HumanSignal | None = None
    risk_decision: RiskDecision | None = None
    lot_size: float = 0.0
    error: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HybridEngine:
    def __init__(
        self,
        risk_manager: RiskManager | None = None,
        starting_balance: float = 100_000.0,
    ) -> None:
        self._risk_manager = risk_manager or RiskManager(
            starting_balance=starting_balance,
        )
        self._starting_balance = starting_balance
        self._positions: dict[str, _TrackedPosition] = {}
        self._order_count = 0

    def submit_signal(self, signal: HumanSignal) -> OrderResult:
        decision = self._risk_manager.validate_signal(signal)

        if decision.action != RiskAction.ALLOW:
            return OrderResult(
                success=False,
                signal=signal,
                risk_decision=decision,
                error=decision.reason,
            )

        lot_size = self._risk_manager.calculate_position_size(signal)

        if signal.signal_type == SignalType.CLOSE:
            return OrderResult(
                success=True,
                signal=signal,
                risk_decision=decision,
            )

        self._order_count += 1
        order_id = f"hybrid-{self._order_count:06d}"
        position_id = f"pos-{self._order_count:06d}"

        self._positions[position_id] = _TrackedPosition(
            position_id=position_id,
            pair=signal.pair,
            direction=signal.to_direction_str(),
            lot_size=lot_size,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            signal=signal,
        )

        self._risk_manager.record_trade(pnl=0.0)

        return OrderResult(
            success=True,
            order_id=order_id,
            position_id=position_id,
            signal=signal,
            risk_decision=decision,
            lot_size=lot_size,
        )

    def get_open_positions(self) -> list[dict]:
        return [pos.to_dict() for pos in self._positions.values() if pos.is_open]

    def close_position(self, position_id: str) -> OrderResult:
        tracked = self._positions.get(position_id)
        if tracked is None:
            return OrderResult(
                success=False,
                error=f"Position {position_id} not found",
            )
        if not tracked.is_open:
            return OrderResult(
                success=False,
                error=f"Position {position_id} is already closed",
            )

        tracked.close()
        return OrderResult(
            success=True,
            position_id=position_id,
        )

    @property
    def risk_manager(self) -> RiskManager:
        return self._risk_manager


@dataclass
class _TrackedPosition:
    position_id: str
    pair: str
    direction: str
    lot_size: float
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    signal: HumanSignal | None = None
    is_open: bool = True
    closed_pnl: float = 0.0

    def close(self) -> None:
        self.is_open = False

    def to_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "pair": self.pair,
            "direction": self.direction,
            "lot_size": self.lot_size,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "is_open": self.is_open,
        }
