from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass
class Order:
    order_id: str
    symbol: str
    direction: TradeDirection
    order_type: OrderType
    volume: float
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    filled_at: Optional[datetime] = None
    filled_price: Optional[float] = None
    comment: str = ""


@dataclass
class Position:
    position_id: str
    symbol: str
    direction: TradeDirection
    volume: float
    entry_price: float
    current_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    unrealized_pnl: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    opened_at: datetime = field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    closed_price: Optional[float] = None
    closed_pnl: float = 0.0
    comment: str = ""


@dataclass
class TradeSignal:
    symbol: str
    direction: TradeDirection
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: float
    volume: float
    confidence: float
    rationale: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class cTraderCredentials:
    host: str
    port: int
    use_ssl: bool = True
    verify_ssl: bool = True
    sender_comp_id: str = ""
    target_comp_id: str = "cServer"
    sender_sub_id: str = "TRADE"
    username: str = ""  # Account number for FIX logon (tag 553)
    password: str = ""


@dataclass
class AccountInfo:
    account_id: str
    balance: float
    equity: float
    margin_used: float
    margin_available: float
    unrealized_pnl: float = 0.0
    daily_pnl: float = 0.0
    is_demo: bool = True


@dataclass
class MarketDataSnapshot:
    symbol: str
    bid: float
    ask: float
    last: float
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2
