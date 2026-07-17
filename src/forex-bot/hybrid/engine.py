from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import StrEnum

from hybrid.risk_manager import RiskAction, RiskDecision, RiskManager
from hybrid.signal import HumanSignal, SignalType
from risk.correlation_sizer import CorrelationAwareSizer


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


@dataclass(frozen=True)
class SessionWindow:
    name: str
    start_utc: time
    end_utc: time


DEFAULT_SESSION_WINDOWS = [
    SessionWindow("london_open", time(7, 0), time(9, 0)),
    SessionWindow("london", time(8, 0), time(12, 0)),
    SessionWindow("ny_open", time(12, 0), time(14, 0)),
    SessionWindow("ny_am", time(12, 0), time(16, 0)),
    SessionWindow("ny_pm", time(16, 0), time(20, 0)),
    SessionWindow("asian", time(0, 0), time(6, 0)),
]


@dataclass
class HybridEngineConfig:
    session_filter_enabled: bool = True
    allowed_sessions: list[str] | None = None
    use_kelly_sizing: bool = False


class HybridEngine:
    def __init__(
        self,
        risk_manager: RiskManager | None = None,
        starting_balance: float = 100_000.0,
        config: HybridEngineConfig | None = None,
        session_windows: list[SessionWindow] | None = None,
        correlation_sizer: CorrelationAwareSizer | None = None,
    ) -> None:
        self._risk_manager = risk_manager or RiskManager(
            starting_balance=starting_balance,
            correlation_sizer=correlation_sizer,
        )
        self._config = config or HybridEngineConfig()
        self._session_windows = session_windows or DEFAULT_SESSION_WINDOWS
        self._starting_balance = starting_balance
        self._positions: dict[str, _TrackedPosition] = {}
        self._order_count = 0

    def submit_signal(self, signal: HumanSignal) -> OrderResult:
        session_check = self._check_session(signal)
        if session_check is not None:
            return OrderResult(
                success=False,
                signal=signal,
                error=session_check,
            )

        decision = self._risk_manager.validate_signal(signal)

        if decision.action != RiskAction.REJECT:
            risk_pct = (
                decision.suggested_lot_size or self._risk_manager._risk_per_trade_pct
            )
            lot_size = self._risk_manager.calculate_position_size(
                signal,
                risk_pct_override=risk_pct,
            )
        else:
            lot_size = 0.0

        if decision.action != RiskAction.ALLOW:
            return OrderResult(
                success=False,
                signal=signal,
                risk_decision=decision,
                error=decision.reason,
            )

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

        self._risk_manager.open_position()
        self._risk_manager.record_trade(pnl=0.0, risk_pct=risk_pct)

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
        self._risk_manager.close_position()
        return OrderResult(
            success=True,
            position_id=position_id,
        )

    @property
    def risk_manager(self) -> RiskManager:
        return self._risk_manager

    def _check_session(self, signal: HumanSignal) -> str | None:
        if not self._config.session_filter_enabled:
            return None
        if signal.signal_type == SignalType.CLOSE:
            return None

        allowed = set(
            self._config.allowed_sessions
            or ["london", "london_open", "ny_open", "ny_am", "ny_pm", "asian"]
        )

        signal_time = signal.timestamp.astimezone(timezone.utc)
        active_sessions = self._get_active_sessions(signal_time)

        if not active_sessions:
            return (
                f"Signal rejected: no active trading session at "
                f"{signal_time.strftime('%H:%M')} UTC"
            )

        if not active_sessions.intersection(allowed):
            names = ", ".join(sorted(active_sessions))
            return f"Signal rejected: active sessions [{names}] not in allowed set"

        return None

    def _get_active_sessions(self, utc_dt: datetime) -> set[str]:
        t = utc_dt.time()
        active: set[str] = set()
        for sw in self._session_windows:
            if sw.start_utc <= t < sw.end_utc:
                active.add(sw.name)
        return active


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
