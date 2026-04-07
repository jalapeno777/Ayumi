from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..engine import Bar, SessionType, TradeDirection
from .models import ICTMarketState


@dataclass
class JudasSwing:
    bar_index: int
    session: SessionType
    spike_direction: TradeDirection
    spike_high: float
    spike_low: float
    wick_ratio: float
    reversal_confirmed: bool
    reversal_bars: int


class JudasSwingTimer:
    LONDON_OPEN_HOUR_UTC = 3
    LONDON_CLOSE_HOUR_UTC = 4
    NY_OPEN_HOUR_UTC = 8
    NY_CLOSE_HOUR_UTC = 9

    def __init__(
        self,
        min_wick_ratio: float = 0.6,
        reversal_window: int = 5,
        min_body_ratio: float = 0.4,
        spike_atr_multiplier: float = 0.8,
    ):
        self._min_wick_ratio = min_wick_ratio
        self._reversal_window = reversal_window
        self._min_body_ratio = min_body_ratio
        self._spike_atr_multiplier = spike_atr_multiplier

    def detect(self, state: ICTMarketState) -> List[JudasSwing]:
        bars = state.bars
        if len(bars) < self._reversal_window + 2 or state.atr == 0:
            return []

        current_idx = len(bars) - 1
        results: List[JudasSwing] = []

        lookback_start = max(0, current_idx - 30)
        for i in range(lookback_start, current_idx):
            swing = self._check_session_spike(bars, i, current_idx, state.atr)
            if swing is not None:
                results.append(swing)

        return results

    def has_judas_swing(self, swings: List[JudasSwing], session: Optional[SessionType] = None) -> bool:
        if session is not None:
            return any(s.session == session for s in swings)
        return len(swings) > 0

    def get_recent(
        self, swings: List[JudasSwing], max_age: int = 10, current_idx: int = 0
    ) -> Optional[JudasSwing]:
        recent = [s for s in swings if (current_idx - s.bar_index) <= max_age]
        return max(recent, key=lambda s: s.wick_ratio) if recent else None

    def spike_direction_suppressed(
        self, swings: List[JudasSwing], direction: TradeDirection, max_age: int = 10, current_idx: int = 0
    ) -> bool:
        recent = [s for s in swings if (current_idx - s.bar_index) <= max_age]
        return any(s.spike_direction == direction for s in recent)

    def _check_session_spike(
        self,
        bars: List[Bar],
        idx: int,
        current_idx: int,
        atr: float,
    ) -> Optional[JudasSwing]:
        bar = bars[idx]
        session = self._classify_session_hour(bar.time.hour)
        if session not in (SessionType.LONDON, SessionType.NY_AM):
            return None

        bar_range = ICTMarketState.bar_range(bar)
        if bar_range == 0:
            return None

        if bar_range < atr * self._spike_atr_multiplier:
            return None

        wick_total = ICTMarketState.bar_upper_wick(bar) + ICTMarketState.bar_lower_wick(bar)
        wick_ratio = wick_total / bar_range
        if wick_ratio < self._min_wick_ratio:
            return None

        is_bullish = ICTMarketState.bar_is_bullish(bar)
        spike_direction = TradeDirection.LONG if is_bullish else TradeDirection.SHORT

        reversal_info = self._check_reversal(bars, idx, current_idx, is_bullish)
        reversal_confirmed = reversal_info is not None
        reversal_bars = reversal_info if reversal_info is not None else self._reversal_window

        return JudasSwing(
            bar_index=idx,
            session=session,
            spike_direction=spike_direction,
            spike_high=bar.high,
            spike_low=bar.low,
            wick_ratio=wick_ratio,
            reversal_confirmed=reversal_confirmed,
            reversal_bars=reversal_bars,
        )

    def _check_reversal(
        self,
        bars: List[Bar],
        spike_idx: int,
        current_idx: int,
        is_bullish_spike: bool,
    ) -> Optional[int]:
        spike_close = bars[spike_idx].close
        end = min(spike_idx + self._reversal_window + 1, current_idx + 1)

        for j in range(spike_idx + 1, end):
            next_bar = bars[j]
            br = ICTMarketState.bar_body_ratio(next_bar)
            if br < self._min_body_ratio:
                continue

            if is_bullish_spike:
                if next_bar.close < spike_close:
                    return j - spike_idx
            else:
                if next_bar.close > spike_close:
                    return j - spike_idx

        return None

    @classmethod
    def _classify_session_hour(cls, hour_utc: int) -> SessionType:
        if cls.LONDON_OPEN_HOUR_UTC <= hour_utc < cls.LONDON_CLOSE_HOUR_UTC:
            return SessionType.LONDON
        if cls.NY_OPEN_HOUR_UTC <= hour_utc < cls.NY_CLOSE_HOUR_UTC:
            return SessionType.NY_AM
        return SessionType.OUTSIDE
