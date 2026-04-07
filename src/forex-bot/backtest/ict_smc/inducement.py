from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..engine import Bar, TradeDirection
from .models import ICTMarketState


@dataclass
class Inducement:
    bar_index: int
    direction: TradeDirection
    break_level: float
    spike_high: float
    spike_low: float
    wick_ratio: float
    volume_ratio: float
    reversal_bars: int
    continuation_direction: TradeDirection
    age: int = 0


class InducementDetector:
    def __init__(
        self,
        min_wick_ratio: float = 0.6,
        volume_multiplier: float = 1.5,
        reversal_window: int = 5,
        min_reversal_body_ratio: float = 0.4,
        lookback: int = 20,
        max_age: int = 15,
    ):
        self._min_wick_ratio = min_wick_ratio
        self._volume_multiplier = volume_multiplier
        self._reversal_window = reversal_window
        self._min_reversal_body_ratio = min_reversal_body_ratio
        self._lookback = lookback
        self._max_age = max_age

    def detect(self, state: ICTMarketState) -> List[Inducement]:
        bars = state.bars
        if len(bars) < self._lookback + self._reversal_window + 2 or state.atr == 0:
            return []

        current_idx = len(bars) - 1
        start_idx = max(0, current_idx - self._lookback)
        results: List[Inducement] = []

        for i in range(start_idx, current_idx - self._reversal_window):
            age = current_idx - i
            if age > self._max_age:
                continue

            inducement = self._check_bar(state, bars, i, current_idx)
            if inducement is not None:
                results.append(inducement)

        return results

    def get_recent(
        self, inducements: List[Inducement], direction: Optional[TradeDirection] = None, max_age: int = 10
    ) -> Optional[Inducement]:
        candidates = [ind for ind in inducements if ind.age <= max_age]
        if direction is not None:
            candidates = [ind for ind in candidates if ind.continuation_direction == direction]
        return max(candidates, key=lambda ind: ind.volume_ratio * ind.wick_ratio) if candidates else None

    def has_inducement_at_index(
        self, inducements: List[Inducement], bar_index: int
    ) -> bool:
        return any(ind.bar_index == bar_index for ind in inducements)

    def _check_bar(
        self,
        state: ICTMarketState,
        bars: List[Bar],
        idx: int,
        current_idx: int,
    ) -> Optional[Inducement]:
        bar = bars[idx]
        bar_range = ICTMarketState.bar_range(bar)
        if bar_range == 0:
            return None

        wick_total = ICTMarketState.bar_upper_wick(bar) + ICTMarketState.bar_lower_wick(bar)
        wick_ratio = wick_total / bar_range
        if wick_ratio < self._min_wick_ratio:
            return None

        avg_volume = self._average_volume(bars, idx)
        if avg_volume <= 0:
            return None
        volume_ratio = bar.volume / avg_volume
        if volume_ratio < self._volume_multiplier:
            return None

        is_bullish_break = bar.close > bar.open
        break_level = bar.low if is_bullish_break else bar.high

        if not self._is_obvious_break(state, bars, idx, break_level, is_bullish_break):
            return None

        reversal_info = self._find_reversal(bars, idx, current_idx, is_bullish_break)
        if reversal_info is None:
            return None

        reversal_bars, continuation_direction = reversal_info

        if is_bullish_break:
            spike_direction = TradeDirection.LONG
        else:
            spike_direction = TradeDirection.SHORT

        return Inducement(
            bar_index=idx,
            direction=spike_direction,
            break_level=break_level,
            spike_high=bar.high,
            spike_low=bar.low,
            wick_ratio=wick_ratio,
            volume_ratio=volume_ratio,
            reversal_bars=reversal_bars,
            continuation_direction=continuation_direction,
        )

    def _is_obvious_break(
        self,
        state: ICTMarketState,
        bars: List[Bar],
        idx: int,
        break_level: float,
        is_bullish_break: bool,
    ) -> bool:
        lookback_start = max(0, idx - 10)
        recent_highs = [bars[k].high for k in range(lookback_start, idx)]
        recent_lows = [bars[k].low for k in range(lookback_start, idx)]

        if not recent_highs or not recent_lows:
            return False

        if is_bullish_break:
            prior_resistance = max(recent_highs)
            return break_level < prior_resistance and bars[idx].high > prior_resistance
        else:
            prior_support = min(recent_lows)
            return break_level > prior_support and bars[idx].low < prior_support

    def _find_reversal(
        self,
        bars: List[Bar],
        spike_idx: int,
        current_idx: int,
        is_bullish_break: bool,
    ) -> Optional[tuple]:
        spike_close = bars[spike_idx].close
        end = min(spike_idx + self._reversal_window + 1, current_idx + 1)

        for j in range(spike_idx + 1, end):
            next_bar = bars[j]
            br = ICTMarketState.bar_body_ratio(next_bar)
            if br < self._min_reversal_body_ratio:
                continue

            if is_bullish_break:
                if next_bar.close < spike_close - (spike_close * 0.0001):
                    reversal_bars = j - spike_idx
                    continuation_direction = TradeDirection.SHORT
                    return reversal_bars, continuation_direction
            else:
                if next_bar.close > spike_close + (spike_close * 0.0001):
                    reversal_bars = j - spike_idx
                    continuation_direction = TradeDirection.LONG
                    return reversal_bars, continuation_direction

        return None

    def _average_volume(self, bars: List[Bar], bar_idx: int) -> float:
        start = max(0, bar_idx - 20)
        sample = bars[start:bar_idx]
        if not sample:
            return 0.0
        return sum(b.volume for b in sample) / len(sample)
