from typing import Optional, List

from .models import (
    Bar,
    FairValueGap,
    FVGType,
    ICTMarketState,
    TradeDirection,
)


class FVGDetector:
    def __init__(self, max_age: int = 20, mini_threshold: float = 0.0003):
        self._max_age = max_age
        self._mini_threshold = mini_threshold

    def detect(self, state: ICTMarketState) -> List[FairValueGap]:
        bars = state.bars
        if len(bars) < 5:
            return []

        state.active_fvgs.clear()
        start_idx = max(2, len(bars) - self._max_age - 5)
        current_idx = len(bars) - 1

        for i in range(start_idx, current_idx - 1):
            candle1 = bars[i]
            candle3 = bars[i + 2]

            if candle3.high < candle1.low or candle3.low > candle1.high:
                continue

            gap = 0.0
            direction = TradeDirection.NEUTRAL
            fvg_type = FVGType.BULLISH_FVG

            if candle1.high < candle3.low:
                gap = candle3.low - candle1.high
                direction = TradeDirection.LONG
                fvg_type = self._classify_fvg(bars, i, direction)
            elif candle3.high > candle1.low:
                gap = candle3.high - candle1.low
                direction = TradeDirection.SHORT
                fvg_type = self._classify_fvg(bars, i, direction)
            else:
                continue

            normalized_gap = gap / bars[i + 1].close
            if normalized_gap < self._mini_threshold:
                continue

            age = current_idx - (i + 1)

            filled, mitigated = self._check_mitigation(
                bars, i, direction, gap, candle1, candle3
            )

            if mitigated:
                continue

            top = candle3.low if direction == TradeDirection.LONG else candle3.high
            bottom = candle1.high if direction == TradeDirection.LONG else candle1.low
            if bottom > top:
                top, bottom = bottom, top

            fvg = FairValueGap(
                start_index=i,
                top=top,
                bottom=bottom,
                direction=direction,
                fvg_type=fvg_type,
                size=gap,
                age=age,
                is_filled=filled,
                is_mitigated=mitigated,
                created_time=candle1.time,
            )
            state.active_fvgs.append(fvg)

        self._cleanup_stale(state)
        return state.active_fvgs

    def _classify_fvg(
        self, bars: List[Bar], i: int, direction: TradeDirection
    ) -> FVGType:
        if len(bars) < i + 3:
            return (
                FVGType.BULLISH_FVG
                if direction == TradeDirection.LONG
                else FVGType.BEARISH_FVG
            )

        candle1 = bars[i]
        candle2 = bars[i + 1]
        candle3 = bars[i + 2]

        if direction == TradeDirection.LONG:
            if candle2.close > candle1.high and candle2.close > candle3.close:
                return FVGType.BISI
            return FVGType.BULLISH_FVG
        else:
            if candle2.close < candle1.low and candle2.close < candle3.close:
                return FVGType.SIBI
            return FVGType.BEARISH_FVG

    def _check_mitigation(
        self,
        bars: List[Bar],
        i: int,
        direction: TradeDirection,
        gap: float,
        candle1: Bar,
        candle3: Bar,
    ) -> tuple[bool, bool]:
        current_idx = len(bars) - 1
        filled = False
        mitigated = False

        for j in range(i + 3, current_idx + 1):
            if direction == TradeDirection.LONG:
                if bars[j].low <= candle1.high:
                    mitigated = True
                    break
                fill_denom = candle1.high - candle3.low + gap
                if fill_denom > 0:
                    fill_pct = max(0, (candle3.low - bars[j].low) / gap)
                    if fill_pct >= 0.5:
                        filled = True
            else:
                if bars[j].high >= candle3.high:
                    mitigated = True
                    break
                fill_denom = candle3.high - candle1.low + gap
                if fill_denom > 0:
                    fill_pct = max(0, (bars[j].high - candle3.high) / gap)
                    if fill_pct >= 0.5:
                        filled = True

        return filled, mitigated

    def _cleanup_stale(self, state: ICTMarketState):
        state.active_fvgs = [
            fvg
            for fvg in state.active_fvgs
            if not fvg.is_mitigated and fvg.age <= self._max_age
        ]

    def get_nearest_unfilled(
        self, state: ICTMarketState, direction: TradeDirection, current_price: float
    ) -> Optional[FairValueGap]:
        candidates = [
            fvg
            for fvg in state.active_fvgs
            if fvg.direction == direction and not fvg.is_mitigated
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda fvg: abs(current_price - fvg.mid))

    def get_all_unfilled(
        self, state: ICTMarketState, direction: TradeDirection
    ) -> List[FairValueGap]:
        return [
            fvg
            for fvg in state.active_fvgs
            if fvg.direction == direction and not fvg.is_mitigated
        ]
