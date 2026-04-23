from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class SignalType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    CLOSE = "close"


class SignalSource(StrEnum):
    MANUAL = "manual"
    WEB = "web"
    API = "api"


@dataclass
class HumanSignal:
    signal_type: SignalType
    pair: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    entry_price: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    confidence: float | None = None
    source: SignalSource = SignalSource.MANUAL

    def __post_init__(self) -> None:
        if not self.pair:
            raise ValueError("pair must not be empty")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
        if self.signal_type == SignalType.CLOSE:
            return
        if self.entry_price <= 0:
            raise ValueError(
                f"entry_price must be positive for {self.signal_type} signals, "
                f"got {self.entry_price}"
            )
        if self.stop_loss is not None and self.stop_loss <= 0:
            raise ValueError(f"stop_loss must be positive, got {self.stop_loss}")
        if self.take_profit is not None and self.take_profit <= 0:
            raise ValueError(f"take_profit must be positive, got {self.take_profit}")

    @property
    def has_stop_loss(self) -> bool:
        return self.stop_loss is not None

    @property
    def has_take_profit(self) -> bool:
        return self.take_profit is not None

    def to_direction_str(self) -> str:
        if self.signal_type == SignalType.BUY:
            return "long"
        if self.signal_type == SignalType.SELL:
            return "short"
        return "neutral"
