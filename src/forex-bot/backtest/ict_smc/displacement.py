from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..engine import Bar, TradeDirection
from .models import ICTMarketState


@dataclass
class DisplacementMove:
    start_index: int
    end_index: int
    direction: TradeDirection
    size: float
    atr_normalized: float
    volume_ratio: float
    body_ratio: float
    age: int = 0
    broke_order_block: bool = False
    broke_fvg: bool = False


class DisplacementDetector:
    def __init__(
        self,
        atr_multiplier: float = 1.5,
        min_body_ratio: float = 0.75,
        max_wick_ratio: float = 0.25,
        volume_multiplier: float = 1.5,
        lookback: int = 10,
        max_age: int = 20,
    ):
        self._atr_multiplier = atr_multiplier
        self._min_body_ratio = min_body_ratio
        self._max_wick_ratio = max_wick_ratio
        self._volume_multiplier = volume_multiplier
        self._lookback = lookback
        self._max_age = max_age

    def detect(self, state: ICTMarketState) -> List[DisplacementMove]:
        bars = state.bars
        if len(bars) < self._lookback + 5 or state.atr == 0:
            return []

        current_idx = len(bars) - 1
        start_idx = max(0, current_idx - self._lookback)
        moves: List[DisplacementMove] = []

        i = start_idx
        while i <= current_idx - 1:
            bar = bars[i]
            br = ICTMarketState.bar_body_ratio(bar)
            if br < self._min_body_ratio:
                i += 1
                continue

            bar_range = ICTMarketState.bar_range(bar)
            if bar_range == 0:
                i += 1
                continue

            wick_ratio = (
                ICTMarketState.bar_upper_wick(bar)
                + ICTMarketState.bar_lower_wick(bar)
            ) / bar_range
            if wick_ratio > self._max_wick_ratio:
                i += 1
                continue

            direction = (
                TradeDirection.LONG
                if ICTMarketState.bar_is_bullish(bar)
                else TradeDirection.SHORT
            )

            body_size = ICTMarketState.bar_body(bar)
            end_idx = i

            for j in range(i + 1, min(i + 3, current_idx + 1)):
                next_bar = bars[j]
                next_br = ICTMarketState.bar_body_ratio(next_bar)
                if next_br < 0.5:
                    break
                next_direction_matches = (
                    (direction == TradeDirection.LONG and ICTMarketState.bar_is_bullish(next_bar))
                    or (direction == TradeDirection.SHORT and ICTMarketState.bar_is_bearish(next_bar))
                )
                if not next_direction_matches:
                    break
                body_size += ICTMarketState.bar_body(next_bar)
                end_idx = j

            move_size = body_size
            atr_normalized = move_size / state.atr

            if atr_normalized < self._atr_multiplier:
                i += 1
                continue

            avg_volume = self._average_volume(bars, i)
            volume_sum = sum(bars[k].volume for k in range(i, end_idx + 1))
            volume_ratio = volume_sum / avg_volume if avg_volume > 0 else 1.0

            age = current_idx - end_idx
            if age > self._max_age:
                i += 1
                continue

            broke_ob = self._check_ob_break(state, direction, i, end_idx)
            broke_fvg = self._check_fvg_break(state, direction, i, end_idx)

            moves.append(
                DisplacementMove(
                    start_index=i,
                    end_index=end_idx,
                    direction=direction,
                    size=move_size,
                    atr_normalized=atr_normalized,
                    volume_ratio=volume_ratio,
                    body_ratio=br,
                    age=age,
                    broke_order_block=broke_ob,
                    broke_fvg=broke_fvg,
                )
            )

            i = end_idx + 1

        return moves

    def get_recent(
        self, moves: List[DisplacementMove], direction: TradeDirection, max_age: int = 10
    ) -> Optional[DisplacementMove]:
        candidates = [
            m for m in moves
            if m.direction == direction and m.age <= max_age
        ]
        return max(candidates, key=lambda m: m.atr_normalized) if candidates else None

    def _average_volume(self, bars: List[Bar], bar_idx: int) -> float:
        start = max(0, bar_idx - 20)
        sample = bars[start:bar_idx]
        if not sample:
            return 0.0
        return sum(b.volume for b in sample) / len(sample)

    def _check_ob_break(
        self, state: ICTMarketState, direction: TradeDirection, start: int, end: int
    ) -> bool:
        for ob in state.active_order_blocks:
            if ob.direction != direction:
                continue
            if ob.start_index > start:
                continue
            for k in range(start, end + 1):
                bar = state.bars[k]
                if direction == TradeDirection.LONG and bar.close > ob.top:
                    return True
                if direction == TradeDirection.SHORT and bar.close < ob.bottom:
                    return True
        return False

    def _check_fvg_break(
        self, state: ICTMarketState, direction: TradeDirection, start: int, end: int
    ) -> bool:
        for fvg in state.active_fvgs:
            if fvg.direction != direction:
                continue
            if fvg.start_index > start:
                continue
            for k in range(start, end + 1):
                bar = state.bars[k]
                if direction == TradeDirection.LONG and bar.close > fvg.top:
                    return True
                if direction == TradeDirection.SHORT and bar.close < fvg.bottom:
                    return True
        return False
