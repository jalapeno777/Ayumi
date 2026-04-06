from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import List, Optional

from backtest.engine import (
    Bar,
    MarketState,
    SessionType,
    StrategySignal,
    TradeDirection,
)


@dataclass(frozen=True)
class SessionRangeMRConfig:
    atr_period: int = 14
    atr_sl_multiplier: float = 1.5
    atr_tp_multiplier: float = 2.0
    rsi_period: int = 14
    rsi_long_level: float = 30.0
    rsi_short_level: float = 70.0
    session_range_min_pips: float = 25.0
    entry_near_extreme_pips: float = 15.0
    hard_cap_sl_pips: float = 30.0
    tp1_rr: float = 1.0
    tp2_rr: float = 1.5
    ema_trend_period: int = 50
    use_session_range_sl: bool = True
    session_range_sl_fraction: float = 0.6


_ASIAN_START = time(0, 0)
_ASIAN_END = time(7, 0)
_EARLY_LONDON_END = time(9, 0)
_LONDON_START = time(7, 0)
_LONDON_END = time(11, 0)
_NY_OPEN_START = time(12, 0)
_NY_OPEN_END = time(15, 0)
_LONDON_NY_OVERLAP_START = time(12, 0)
_LONDON_NY_OVERLAP_END = time(16, 0)
_NY_CLOSE_START = time(16, 0)
_NY_CLOSE_END = time(20, 0)

_PIP = 0.0001


def _get_bar_session(bar_time: datetime) -> SessionType:
    utc_hour = bar_time.hour
    if _ASIAN_START.hour <= utc_hour < _ASIAN_END.hour:
        return SessionType.ASIAN
    if _LONDON_START.hour <= utc_hour < _LONDON_END.hour:
        return SessionType.LONDON
    if _NY_OPEN_START.hour <= utc_hour < _NY_OPEN_END.hour:
        return SessionType.NY_AM
    if _LONDON_NY_OVERLAP_START.hour <= utc_hour < _LONDON_NY_OVERLAP_END.hour:
        return SessionType.NY_AM
    if _NY_CLOSE_START.hour <= utc_hour < _NY_CLOSE_END.hour:
        return SessionType.NY_PM
    return SessionType.OUTSIDE


def _is_in_asian_or_early_london(state: MarketState) -> bool:
    utc_hour = state.latest_bar.time.hour
    return (
        _ASIAN_START.hour <= utc_hour <= _ASIAN_END.hour
        or _LONDON_START.hour <= utc_hour <= _EARLY_LONDON_END.hour
    )


def _is_in_london_ny_overlap(state: MarketState) -> bool:
    utc_hour = state.latest_bar.time.hour
    return _LONDON_NY_OVERLAP_START.hour <= utc_hour < _LONDON_NY_OVERLAP_END.hour


def _calculate_atr(bars: List[Bar], period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0001
    tr_sum = 0.0
    count = 0
    for i in range(len(bars) - period, len(bars)):
        if i > 0:
            tr = max(
                bars[i].high - bars[i].low,
                abs(bars[i].high - bars[i - 1].close),
                abs(bars[i].low - bars[i - 1].close),
            )
            tr_sum += tr
            count += 1
    return tr_sum / count if count > 0 else 0.0001


def _calculate_ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    multiplier = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = (v - ema) * multiplier + ema
    return ema


def _get_trend_bias(bars: List[Bar], period: int = 50) -> Optional[str]:
    if len(bars) < period + 1:
        return None
    closes = [b.close for b in bars]
    ema = _calculate_ema(closes, period)
    if ema is None:
        return None
    price = closes[-1]
    if price > ema:
        return "long"
    return "short"


def _calculate_rsi(bars: List[Bar], period: int = 14) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    gains: List[float] = []
    losses: List[float] = []
    for i in range(len(bars) - period, len(bars)):
        change = bars[i].close - bars[i - 1].close
        gains.append(change if change > 0 else 0.0)
        losses.append(abs(change) if change < 0 else 0.0)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _calculate_session_range(
    bars: List[Bar], session_type: SessionType, reference_day: Optional[date] = None
) -> tuple[float, float, float]:
    if not bars:
        return 0.0, 0.0, 0.0

    if reference_day is None:
        reference_day = bars[-1].time.date()

    session_bars: List[Bar] = []
    for b in bars:
        if b.time.date() != reference_day:
            continue
        if _get_bar_session(b.time) == session_type:
            session_bars.append(b)

    if not session_bars:
        return 0.0, 0.0, 0.0

    high = max(b.high for b in session_bars)
    low = min(b.low for b in session_bars)
    mean = sum(b.close for b in session_bars) / len(session_bars)
    return high, low, mean


def _build_signal(
    direction: TradeDirection,
    entry: float,
    atr: float,
    config: SessionRangeMRConfig,
    session_range_price: float,
    rationale: str,
) -> Optional[StrategySignal]:
    if atr <= 0:
        return None

    if config.use_session_range_sl and session_range_price > 0:
        sl_distance = min(
            session_range_price * config.session_range_sl_fraction,
            config.hard_cap_sl_pips * _PIP,
        )
    else:
        sl_distance = min(
            atr * config.atr_sl_multiplier, config.hard_cap_sl_pips * _PIP
        )

    if sl_distance <= 0:
        return None

    sl = (
        entry - sl_distance if direction == TradeDirection.LONG else entry + sl_distance
    )

    risk = sl_distance
    tp1 = (
        entry + risk * config.tp1_rr
        if direction == TradeDirection.LONG
        else entry - risk * config.tp1_rr
    )
    tp2 = (
        entry + risk * config.tp2_rr
        if direction == TradeDirection.LONG
        else entry - risk * config.tp2_rr
    )

    return StrategySignal(
        direction=direction,
        confidence=0.70,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp2,
        rationale=rationale,
    )


class SessionRangeMeanReversionStrategy:
    def __init__(self, config: Optional[SessionRangeMRConfig] = None):
        self.config = config or SessionRangeMRConfig()

    @property
    def name(self) -> str:
        return "Session-Range Mean Reversion"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        min_required = max(
            self.config.atr_period + self.config.rsi_period + 2,
            self.config.ema_trend_period + 1,
        )
        if len(state.bars) < min_required:
            return None

        if not _is_in_asian_or_early_london(state):
            return None

        if _is_in_london_ny_overlap(state):
            return None

        atr = _calculate_atr(state.bars, self.config.atr_period)
        if atr <= 0:
            return None

        latest = state.latest_bar
        current_day = latest.time.date()

        prev_day = self._find_previous_trading_day(state.bars, current_day)

        session_high, session_low, session_mean = _calculate_session_range(
            state.bars, SessionType.LONDON, reference_day=prev_day
        )
        if session_high == 0:
            session_high, session_low, session_mean = _calculate_session_range(
                state.bars, SessionType.NY_AM, reference_day=prev_day
            )

        session_range_price = session_high - session_low
        session_range_width = session_range_price / _PIP
        if session_range_width < self.config.session_range_min_pips:
            return None

        price = latest.close

        rsi = _calculate_rsi(state.bars, self.config.rsi_period)
        if rsi is None:
            return None

        entry_near_extreme_pips = self.config.entry_near_extreme_pips * _PIP

        if (
            price <= session_low + entry_near_extreme_pips
            and rsi < self.config.rsi_long_level
        ):
            direction = TradeDirection.LONG
            rationale = (
                f"Session range MR long: price={price:.5f} near session low={session_low:.5f}, "
                f"RSI={rsi:.1f}, range={session_range_width:.1f} pips"
            )
            return _build_signal(
                direction, price, atr, self.config, session_range_price, rationale
            )

        if (
            price >= session_high - entry_near_extreme_pips
            and rsi > self.config.rsi_short_level
        ):
            direction = TradeDirection.SHORT
            rationale = (
                f"Session range MR short: price={price:.5f} near session high={session_high:.5f}, "
                f"RSI={rsi:.1f}, range={session_range_width:.1f} pips"
            )
            return _build_signal(
                direction, price, atr, self.config, session_range_price, rationale
            )

        return None

    @staticmethod
    def _find_previous_trading_day(
        bars: List[Bar], current_day: date
    ) -> Optional[date]:
        seen_days: set[date] = set()
        for b in bars:
            d = b.time.date()
            if d < current_day:
                seen_days.add(d)
        if not seen_days:
            return None
        return max(seen_days)
