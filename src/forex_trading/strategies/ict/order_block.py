from typing import Optional, List

from .models import (
    Bar,
    ICTMarketState,
    OrderBlock,
    TradeDirection,
    SwingPoint,
)


class OrderBlockDetector:
    def __init__(
        self,
        freshness_window: int = 5,
        min_body_ratio: float = 0.5,
        overlap_threshold: float = 0.7,
        lookback: int = 50,
    ):
        self._freshness_window = freshness_window
        self._min_body_ratio = min_body_ratio
        self._overlap_threshold = overlap_threshold
        self._lookback = lookback

    def detect(self, state: ICTMarketState) -> List[OrderBlock]:
        bars = state.bars
        if len(bars) < 10:
            return []

        state.active_order_blocks.clear()
        start_idx = max(0, len(bars) - self._lookback)
        current_idx = len(bars) - 1

        for i in range(start_idx, current_idx - 1):
            bar = bars[i]
            body_ratio = ICTMarketState.bar_body_ratio(bar)
            if body_ratio < self._min_body_ratio:
                continue
            bar_range = ICTMarketState.bar_range(bar)
            if bar_range == 0:
                continue

            age = current_idx - i
            if age > self._freshness_window:
                continue

            direction = (
                TradeDirection.LONG
                if ICTMarketState.bar_is_bullish(bar)
                else TradeDirection.SHORT
            )
            top = max(bar.open, bar.close)
            bottom = min(bar.open, bar.close)

            avg_body_start = max(0, len(bars) - 21)
            recent_bodies = [
                ICTMarketState.bar_body(b)
                for b in bars[avg_body_start : avg_body_start + 20]
                if ICTMarketState.bar_range(b) > 0
            ]
            avg_body = sum(recent_bodies) / len(recent_bodies) if recent_bodies else 0

            body_size = ICTMarketState.bar_body(bar)
            strength = 0.5
            if avg_body > 0:
                strength = min(1.0, 0.5 + (body_size / avg_body - 1.0) * 0.25)

            min_wick = min(
                ICTMarketState.bar_upper_wick(bar), ICTMarketState.bar_lower_wick(bar)
            )
            wick_ratio = min_wick / bar_range
            if wick_ratio < 0.2:
                strength += 0.1

            if state.structure_bias == direction:
                strength += 0.15

            strength = min(1.0, strength)

            overlaps = self._has_overlapping_ob(
                state.active_order_blocks, direction, top, bottom
            )
            if overlaps:
                continue

            mitigated = self._is_mitigated(bars, i, direction, top, bottom)
            if not mitigated:
                ob = OrderBlock(
                    start_index=i,
                    end_index=i,
                    top=top,
                    bottom=bottom,
                    direction=direction,
                    strength=strength,
                    is_mitigated=False,
                    age=age,
                    created_time=bar.time,
                    body_size=body_size,
                )
                state.active_order_blocks.append(ob)

        self._cleanup_mitigated(state)
        return state.active_order_blocks

    def _has_overlapping_ob(
        self,
        existing_obs: List[OrderBlock],
        direction: TradeDirection,
        top: float,
        bottom: float,
    ) -> bool:
        for ob in existing_obs:
            if ob.direction != direction:
                continue
            if (ob.top - ob.bottom) <= 0 or (top - bottom) <= 0:
                continue
            overlap = max(0, min(top, ob.top) - max(bottom, ob.bottom))
            smaller_range = min(ob.top - ob.bottom, top - bottom)
            if smaller_range > 0 and overlap / smaller_range > self._overlap_threshold:
                return True
        return False

    def _is_mitigated(
        self, bars: List[Bar], ob_index: int, direction: TradeDirection, top: float, bottom: float
    ) -> bool:
        current_idx = len(bars) - 1
        for j in range(ob_index + 1, current_idx + 1):
            if direction == TradeDirection.LONG and bars[j].low < bottom:
                return True
            if direction == TradeDirection.SHORT and bars[j].high > top:
                return True
        return False

    def _cleanup_mitigated(self, state: ICTMarketState):
        bars = state.bars
        to_remove = []
        for ob in state.active_order_blocks:
            found = False
            for i in range(ob.end_index + 1, len(bars)):
                if ob.direction == TradeDirection.LONG and bars[i].low < ob.bottom:
                    found = True
                    break
                if ob.direction == TradeDirection.SHORT and bars[i].high > ob.top:
                    found = True
                    break
            if found or ob.age > self._freshness_window * 3:
                to_remove.append(ob)
        for ob in to_remove:
            state.active_order_blocks.remove(ob)

    def get_most_relevant(
        self, state: ICTMarketState, direction: TradeDirection
    ) -> Optional[OrderBlock]:
        candidates = [
            ob
            for ob in state.active_order_blocks
            if ob.direction == direction and not ob.is_mitigated
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda ob: (ob.strength, -ob.age))

    def get_nearest(
        self, state: ICTMarketState, direction: TradeDirection, current_price: float
    ) -> Optional[OrderBlock]:
        candidates = [
            ob
            for ob in state.active_order_blocks
            if ob.direction == direction and not ob.is_mitigated
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda ob: abs(current_price - ob.mid))