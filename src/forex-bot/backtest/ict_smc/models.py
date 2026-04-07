from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from ..engine import Bar, SessionType, TradeDirection

if TYPE_CHECKING:
    from .displacement import DisplacementMove
    from .premium_discount import OTEZone


class StructureType(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGING = "ranging"


class SignalStrength(Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


@dataclass
class SwingPoint:
    index: int
    price: float
    is_high: bool
    time: datetime


@dataclass
class StructureBreak:
    time: datetime
    direction: TradeDirection
    break_level: float
    is_choch: bool = False
    break_strength: float = 0.0


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


@dataclass
class FairValueGap:
    start_index: int
    top: float
    bottom: float
    direction: TradeDirection
    size: float = 0.0
    age: int = 0
    is_filled: bool = False
    is_mitigated: bool = False
    created_time: datetime = field(default_factory=datetime.now)


@dataclass
class LiquidityPool:
    level: float
    touches: float = 1.0
    is_high: bool = True
    is_day_high: bool = False
    is_day_low: bool = False
    last_sweep_time: Optional[datetime] = None
    bar_index: int = 0


@dataclass
class LiquiditySweep:
    time: datetime
    sweep_level: float
    sweep_high: float
    sweep_low: float
    rejection_body: float = 0.0
    swept_high: bool = False
    session: SessionType = SessionType.OUTSIDE
    strength: float = 0.0
    implied_direction: TradeDirection = TradeDirection.NEUTRAL


@dataclass
class PremiumDiscountZone:
    equilibrium: float
    premium_boundary: float
    discount_boundary: float
    current_price: float
    current_zone: TradeDirection = TradeDirection.NEUTRAL
    distance_from_equilibrium: float = 0.0
    zone_strength: float = 0.5
    is_in_premium: bool = False
    is_in_discount: bool = False
    is_in_equilibrium: bool = True


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
    has_liquidity_sweep: bool = False
    has_premium_discount_confluence: bool = False
    has_displacement: bool = False
    has_ote_confluence: bool = False
    has_structure_alignment: bool = False
    confluence_count: int = 0
    risk_reward_ratio: float = 0.0
    structure_score: float = 0.0
    ob_score: float = 0.0
    fvg_score: float = 0.0
    liq_sweep_score: float = 0.0
    pd_zone_score: float = 0.0
    session_score: float = 0.0
    displacement_score: float = 0.0
    ote_score: float = 0.0


class ICTMarketState:
    def __init__(self, bars: List[Bar]):
        self.bars = bars
        self.structure_bias: TradeDirection = TradeDirection.NEUTRAL
        self.structure_breaks: List[StructureBreak] = []
        self.swing_highs: List[SwingPoint] = []
        self.swing_lows: List[SwingPoint] = []
        self.active_order_blocks: List[OrderBlock] = []
        self.active_fvgs: List[FairValueGap] = []
        self.recent_sweeps: List[LiquiditySweep] = []
        self.liquidity_pools: List[LiquidityPool] = []
        self.pd_zone: Optional[PremiumDiscountZone] = None
        self.current_session: SessionType = SessionType.OUTSIDE
        self.day_high: float = 0.0
        self.day_low: float = 0.0
        self.atr: float = 0.0
        self.displacement_moves: List[DisplacementMove] = []
        self.ote_zones: List[OTEZone] = []

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
