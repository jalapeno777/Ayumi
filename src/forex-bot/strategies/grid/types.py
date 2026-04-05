from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


class GridSide(Enum):
    BUY = "buy"
    SELL = "sell"


class GridOrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"


class GridLevelStatus(Enum):
    ACTIVE = "active"
    FILLED = "filled"
    CANCELLED = "cancelled"


@dataclass
class GridLevel:
    index: int
    side: GridSide
    price: float
    lot_size: float
    status: GridLevelStatus = GridLevelStatus.ACTIVE
    filled_at: Optional[datetime] = None
    entry_price: Optional[float] = None
    order_id: Optional[str] = None


@dataclass
class GridTrade:
    level: GridLevel
    entry_price: float
    lot_size: float
    side: GridSide
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    pips: float = 0.0
    is_open: bool = True


@dataclass
class GridState:
    center_price: float
    buy_levels: list[GridLevel] = field(default_factory=list)
    sell_levels: list[GridLevel] = field(default_factory=list)
    open_trades: list[GridTrade] = field(default_factory=list)
    closed_trades: list[GridTrade] = field(default_factory=list)
    total_pnl: float = 0.0
    realized_pips: float = 0.0
    direction_bias: Optional[GridSide] = None
    adx_value: float = 0.0
    is_active: bool = True
    equity_at_start: float = 0.0
    daily_pnl: float = 0.0
    last_reset_day: Optional[int] = None

    @property
    def open_trade_count(self) -> int:
        return len(self.open_trades)

    @property
    def closed_trade_count(self) -> int:
        return len(self.closed_trades)

    @property
    def active_buy_levels(self) -> list[GridLevel]:
        return [lv for lv in self.buy_levels if lv.status == GridLevelStatus.ACTIVE]

    @property
    def active_sell_levels(self) -> list[GridLevel]:
        return [lv for lv in self.sell_levels if lv.status == GridLevelStatus.ACTIVE]

    @property
    def all_active_levels(self) -> list[GridLevel]:
        return self.active_buy_levels + self.active_sell_levels

    @property
    def win_rate(self) -> float:
        if not self.closed_trades:
            return 0.0
        wins = sum(1 for t in self.closed_trades if t.pnl > 0)
        return wins / len(self.closed_trades)

    @property
    def win_rate_including_breakeven(self) -> float:
        if not self.closed_trades:
            return 0.0
        wins = sum(1 for t in self.closed_trades if t.pnl >= 0)
        return wins / len(self.closed_trades)
