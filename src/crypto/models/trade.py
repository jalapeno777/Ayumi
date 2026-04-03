from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"


class TradeStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass
class TradeSignal:
    provider_id: str
    symbol: str
    direction: TradeDirection
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float = 0.0
    signal_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    strategy_name: str = ""
    confluence_count: int = 0
    strength: str = "moderate"

    @property
    def risk_reward(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        if risk == 0:
            return 0.0
        return reward / risk

    @property
    def sl_tp_ratio(self) -> float:
        rr = self.risk_reward
        return 1.0 / rr if rr > 0 else 0.0


@dataclass
class CopyTrade:
    signal: TradeSignal
    follower_account_id: str
    allocation_usd: float = 0.0
    status: TradeStatus = TradeStatus.OPEN
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    close_price: float = 0.0
    profit_loss: float = 0.0

    def close(self, price: float) -> None:
        self.status = TradeStatus.CLOSED
        self.close_price = price
        self.closed_at = datetime.now(timezone.utc)
        if self.signal.direction == TradeDirection.LONG:
            self.profit_loss = (price - self.signal.entry_price) * self.signal.lot_size * 100000
        else:
            self.profit_loss = (self.signal.entry_price - price) * self.signal.lot_size * 100000


@dataclass
class ProviderStats:
    provider_id: str
    provider_name: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_profit: float = 0.0
    max_drawdown: float = 0.0
    avg_risk_reward: float = 0.0
    win_rate: float = 0.0
    followers_count: int = 0

    def update(self, profit: float, risk_reward: float) -> None:
        self.total_trades += 1
        self.total_profit += profit
        if profit > 0:
            self.wins += 1
        else:
            self.losses += 1
        self.avg_risk_reward = (
            (self.avg_risk_reward * (self.total_trades - 1) + risk_reward)
            / self.total_trades
        )
        self.win_rate = self.wins / self.total_trades * 100 if self.total_trades > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "total_profit": round(self.total_profit, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "avg_risk_reward": round(self.avg_risk_reward, 2),
            "win_rate": round(self.win_rate, 1),
            "followers_count": self.followers_count,
        }
