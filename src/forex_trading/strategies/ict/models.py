from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class SessionType(Enum):
    ASIAN = "asian"
    LONDON = "london"
    NY_AM = "ny_am"
    NY_PM = "ny_pm"
    OUTSIDE = "outside"


class SignalStrength(Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


class FVGType(Enum):
    BULLISH_FVG = "bullish_fvg"
    BEARISH_FVG = "bearish_fvg"
    BISI = "bisi"
    SIBI = "sibi"


@dataclass
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class SwingPoint:
    index: int
    price: float
    is_high: bool
    time: datetime


@dataclass
class OrderBlock:
    start_index: int
    end_index: int
    top: float
    bottom: float
    direction: TradeDirection
    strength: float = 0.0
    is_mitigated: bool = False
    age: int = 0
    created_time: datetime = field(default_factory=datetime.now)
    body_size: float = 0.0
    block_type: str = "order_block"

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class FairValueGap:
    start_index: int
    top: float
    bottom: float
    direction: TradeDirection
    fvg_type: FVGType = FVGType.BULLISH_FVG
    size: float = 0.0
    age: int = 0
    is_filled: bool = False
    is_mitigated: bool = False
    created_time: datetime = field(default_factory=datetime.now)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def is_bullish(self) -> bool:
        return self.direction == TradeDirection.LONG

    @property
    def is_bearish(self) -> bool:
        return self.direction == TradeDirection.SHORT


@dataclass
class ConfluenceSignal:
    direction: TradeDirection
    strength: SignalStrength
    confidence_score: float
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: float
    signal_time: datetime
    rationale: str
    has_order_block: bool = False
    has_fvg: bool = False
    has_structure_alignment: bool = False
    confluence_count: int = 0
    risk_reward_ratio: float = 0.0
    ob_score: float = 0.0
    fvg_score: float = 0.0
    ob: Optional[OrderBlock] = None
    fvg: Optional[FairValueGap] = None


class ICTMarketState:
    def __init__(self, bars: List[Bar]):
        self.bars = bars
        self.structure_bias: TradeDirection = TradeDirection.NEUTRAL
        self.swing_highs: List[SwingPoint] = []
        self.swing_lows: List[SwingPoint] = []
        self.active_order_blocks: List[OrderBlock] = []
        self.active_fvgs: List[FairValueGap] = []
        self.current_session: SessionType = SessionType.OUTSIDE
        self.atr: float = 0.0

    @property
    def latest_bar(self) -> Bar:
        return self.bars[-1]

    @property
    def previous_bar(self) -> Optional[Bar]:
        return self.bars[-2] if len(self.bars) > 1 else None

    @staticmethod
    def bar_body(bar: Bar) -> float:
        return abs(bar.close - bar.open)

    @staticmethod
    def bar_range(bar: Bar) -> float:
        return bar.high - bar.low

    @staticmethod
    def bar_upper_wick(bar: Bar) -> float:
        return bar.high - max(bar.open, bar.close)

    @staticmethod
    def bar_lower_wick(bar: Bar) -> float:
        return min(bar.open, bar.close) - bar.low

    @staticmethod
    def bar_body_ratio(bar: Bar) -> float:
        r = bar.high - bar.low
        return abs(bar.close - bar.open) / r if r > 0 else 0.0

    @staticmethod
    def bar_is_bullish(bar: Bar) -> bool:
        return bar.close > bar.open

    @staticmethod
    def bar_is_bearish(bar: Bar) -> bool:
        return bar.close < bar.open

    def calculate_atr(self, period: int = 14) -> float:
        if len(self.bars) < period + 1:
            return 0.0001
        tr_sum = 0.0
        for i in range(len(self.bars) - period, len(self.bars)):
            if i > 0:
                tr = max(
                    self.bars[i].high - self.bars[i].low,
                    max(
                        abs(self.bars[i].high - self.bars[i - 1].close),
                        abs(self.bars[i].low - self.bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / period
