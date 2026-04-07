from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..engine import TradeDirection
from .displacement import DisplacementMove
from .models import ICTMarketState, OrderBlock, PremiumDiscountZone


@dataclass
class OTEZone:
    level_382: float
    level_500: float
    level_618: float
    level_786: float
    direction: TradeDirection
    origin_start: int
    origin_end: int
    impulse_high: float
    impulse_low: float
    best_level: float = 0.0
    in_order_block: bool = False

    def level_for_direction(self, direction: TradeDirection) -> float:
        if direction == TradeDirection.LONG:
            return self.level_618
        return self.level_382


class PremiumDiscountClassifier:
    def __init__(self, lookback_period: int = 20, equilibrium_buffer: float = 0.0002):
        self._lookback_period = lookback_period
        self._equilibrium_buffer = equilibrium_buffer

    def classify(self, state: ICTMarketState):
        bars = state.bars
        if len(bars) < self._lookback_period:
            return

        recent_bars = bars[-self._lookback_period :]
        range_high = max(b.high for b in recent_bars)
        range_low = min(b.low for b in recent_bars)
        range_size = range_high - range_low

        if range_size == 0:
            state.pd_zone = None
            return

        equilibrium = range_low + range_size * 0.5
        premium_boundary = equilibrium + range_size * 0.25
        discount_boundary = equilibrium - range_size * 0.25

        current_price = bars[-1].close

        is_premium = current_price > premium_boundary
        is_discount = current_price < discount_boundary
        is_equilibrium = not is_premium and not is_discount

        if is_premium:
            zone = TradeDirection.SHORT
        elif is_discount:
            zone = TradeDirection.LONG
        else:
            zone = TradeDirection.NEUTRAL

        distance_from_eq = (current_price - equilibrium) / equilibrium
        normalized_buffer = self._equilibrium_buffer / equilibrium
        near_equilibrium = abs(distance_from_eq) < normalized_buffer * 10

        zone_strength = 0.5
        if is_premium:
            denom = range_high - premium_boundary
            zone_strength = (
                min(1.0, 0.5 + (current_price - premium_boundary) / denom * 0.5)
                if denom > 0
                else 0.5
            )
        elif is_discount:
            denom = discount_boundary - range_low
            zone_strength = (
                min(1.0, 0.5 + (discount_boundary - current_price) / denom * 0.5)
                if denom > 0
                else 0.5
            )

        if near_equilibrium:
            zone_strength = max(zone_strength, 0.7)

        state.pd_zone = PremiumDiscountZone(
            equilibrium=equilibrium,
            premium_boundary=premium_boundary,
            discount_boundary=discount_boundary,
            current_price=current_price,
            current_zone=zone,
            distance_from_equilibrium=distance_from_eq,
            zone_strength=zone_strength,
            is_in_premium=is_premium,
            is_in_discount=is_discount,
            is_in_equilibrium=is_equilibrium,
        )

    def is_discount_entry(
        self, state: ICTMarketState, trade_direction: TradeDirection
    ) -> bool:
        if state.pd_zone is None:
            return False
        return trade_direction == TradeDirection.LONG and state.pd_zone.is_in_discount

    def is_premium_entry(
        self, state: ICTMarketState, trade_direction: TradeDirection
    ) -> bool:
        if state.pd_zone is None:
            return False
        return trade_direction == TradeDirection.SHORT and state.pd_zone.is_in_premium


class OTEZoneDetector:
    def __init__(self, atr_tolerance: float = 0.5, max_zones: int = 5):
        self._atr_tolerance = atr_tolerance
        self._max_zones = max_zones

    def detect(
        self,
        state: ICTMarketState,
        displacement_moves: List[DisplacementMove],
    ) -> List[OTEZone]:
        if not displacement_moves or state.atr == 0:
            return []

        zones: List[OTEZone] = []
        bars = state.bars

        for move in displacement_moves:
            start_bar = bars[move.start_index]
            end_bar = bars[move.end_index]

            if move.direction == TradeDirection.LONG:
                impulse_low = start_bar.low
                impulse_high = end_bar.high
            else:
                impulse_low = end_bar.low
                impulse_high = start_bar.high

            impulse_size = impulse_high - impulse_low
            if impulse_size <= 0:
                continue

            level_382 = impulse_high - impulse_size * 0.382
            level_500 = impulse_high - impulse_size * 0.500
            level_618 = impulse_high - impulse_size * 0.618
            level_786 = impulse_high - impulse_size * 0.786

            zone = OTEZone(
                level_382=level_382,
                level_500=level_500,
                level_618=level_618,
                level_786=level_786,
                direction=move.direction,
                origin_start=move.start_index,
                origin_end=move.end_index,
                impulse_high=impulse_high,
                impulse_low=impulse_low,
                best_level=level_618,
                in_order_block=False,
            )

            zone.in_order_block = self._check_ob_overlap(
                state.active_order_blocks, zone
            )
            zones.append(zone)

        zones.sort(key=lambda z: z.origin_end, reverse=True)
        return zones[: self._max_zones]

    def get_best_zone_for_price(
        self,
        zones: List[OTEZone],
        current_price: float,
        direction: TradeDirection,
        atr: float,
    ) -> Optional[OTEZone]:
        candidates = []
        for zone in zones:
            if zone.direction != direction:
                continue
            target = zone.level_for_direction(direction)
            distance = abs(current_price - target)
            if distance <= atr * self._atr_tolerance:
                candidates.append((zone, distance))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def score_ote_proximity(
        self,
        zones: List[OTEZone],
        current_price: float,
        direction: TradeDirection,
        atr: float,
    ) -> float:
        zone = self.get_best_zone_for_price(zones, current_price, direction, atr)
        if zone is None:
            return 0.0

        target = zone.level_for_direction(direction)
        distance = abs(current_price - target)
        proximity = 1.0 - min(1.0, distance / (atr * self._atr_tolerance))

        score = 0.4 + proximity * 0.3

        if zone.in_order_block:
            score += 0.3

        return min(1.0, score)

    def _check_ob_overlap(
        self, order_blocks: List[OrderBlock], zone: OTEZone
    ) -> bool:
        for ob in order_blocks:
            if ob.direction != zone.direction:
                continue
            ob_top = max(ob.top, ob.bottom)
            ob_bottom = min(ob.top, ob.bottom)
            levels = [zone.level_382, zone.level_500, zone.level_618, zone.level_786]
            for level in levels:
                if ob_bottom <= level <= ob_top:
                    return True
        return False
