from __future__ import annotations

from dataclasses import dataclass

from backtest.engine import (
    Bar,
    MarketState,
    SessionType,
    StrategySignal,
    TradeDirection,
)

_PREFERRED_SESSIONS: set[SessionType] = {
    SessionType.LONDON,
    SessionType.NY_AM,
}

_DEFAULT_PIP = 0.0001


@dataclass(frozen=True)
class VRBConfig:
    atr_period: int = 14
    atr_lookback: int = 50
    atr_percentile_low: float = 20.0
    range_period: int = 20
    range_position_max: float = 0.50
    trend_ema_period: int = 50
    atr_sl_multiplier: float = 1.0
    tp1_rr: float = 1.5
    tp2_rr: float = 2.0
    tp3_rr: float = 3.0
    hard_cap_sl_pips: float = 25.0
    min_confidence: float = 0.50
    cooldown_bars: int = 10
    pip_value: float | None = None


def _pip_value_for_price(price: float) -> float:
    if price >= 50:
        return 0.01
    return _DEFAULT_PIP


def _passes_session_filter(state: MarketState) -> bool:
    return state.current_session in _PREFERRED_SESSIONS


def _calculate_atr(bars: list[Bar], period: int = 14) -> float:
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


def _calculate_ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = (v - ema) * multiplier + ema
    return ema


def _atr_percentile(bars: list[Bar], period: int, lookback: int) -> float:
    if len(bars) < lookback + period:
        return 50.0

    current_atr = _calculate_atr(bars, period)
    atr_values: list[float] = []
    for i in range(max(period + 1, len(bars) - lookback), len(bars)):
        atr_val = _calculate_atr(bars[: i + 1], period)
        atr_values.append(atr_val)

    if not atr_values:
        return 50.0

    below = sum(1 for a in atr_values if a < current_atr)
    return (below / len(atr_values)) * 100.0


def _range_position(bars: list[Bar], period: int) -> float | None:
    if len(bars) < period:
        return None

    recent = bars[-period:]
    highest = max(b.high for b in recent)
    lowest = min(b.low for b in recent)
    price = bars[-1].close

    if highest == lowest:
        return 0.5

    return (price - lowest) / (highest - lowest)


def _trend_direction(bars: list[Bar], period: int) -> int:
    if len(bars) < period + 1:
        return 0

    closes = [b.close for b in bars]
    ema = _calculate_ema(closes, period)
    if ema is None:
        return 0

    if bars[-1].close > ema:
        return 1
    elif bars[-1].close < ema:
        return -1
    return 0


def _build_signal(
    direction: TradeDirection,
    entry: float,
    atr: float,
    config: VRBConfig,
    confidence: float,
    rationale: str,
    pip: float,
) -> StrategySignal | None:
    if atr <= 0:
        return None

    sl_distance = min(atr * config.atr_sl_multiplier, config.hard_cap_sl_pips * pip)

    if sl_distance <= 0:
        return None

    sl = (
        entry - sl_distance if direction == TradeDirection.LONG else entry + sl_distance
    )
    tp1 = (
        entry + sl_distance * config.tp1_rr
        if direction == TradeDirection.LONG
        else entry - sl_distance * config.tp1_rr
    )
    tp2 = (
        entry + sl_distance * config.tp2_rr
        if direction == TradeDirection.LONG
        else entry - sl_distance * config.tp2_rr
    )
    tp3 = (
        entry + sl_distance * config.tp3_rr
        if direction == TradeDirection.LONG
        else entry - sl_distance * config.tp3_rr
    )

    return StrategySignal(
        direction=direction,
        confidence=confidence,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
        rationale=rationale,
    )


class VolatilityRegimeBreakoutStrategy:
    def __init__(self, config: VRBConfig | None = None):
        self.config = config or VRBConfig()
        self._last_signal_bar_index: int = -1

    @property
    def name(self) -> str:
        return "Volatility Regime Breakout"

    def reset(self) -> None:
        self._last_signal_bar_index = -1

    def evaluate(self, state: MarketState) -> StrategySignal | None:
        min_required = max(
            self.config.atr_period + self.config.atr_lookback + 1,
            self.config.range_period + 1,
            self.config.trend_ema_period + 1,
        )

        if len(state.bars) < min_required:
            return None

        if not _passes_session_filter(state):
            return None

        bars_since_last = len(state.bars) - self._last_signal_bar_index
        if bars_since_last < self.config.cooldown_bars:
            return None

        atr_pct = _atr_percentile(
            state.bars, self.config.atr_period, self.config.atr_lookback
        )

        if atr_pct >= self.config.atr_percentile_low:
            return None

        range_pos = _range_position(state.bars, self.config.range_period)
        if range_pos is None:
            return None

        if range_pos > self.config.range_position_max:
            return None

        trend = _trend_direction(state.bars, self.config.trend_ema_period)
        if trend == 0:
            return None

        direction = TradeDirection.LONG if trend == 1 else TradeDirection.SHORT

        latest = state.latest_bar
        atr = _calculate_atr(state.bars, self.config.atr_period)
        pip = (
            self.config.pip_value
            if self.config.pip_value is not None
            else _pip_value_for_price(latest.close)
        )

        confidence = self.config.min_confidence

        atr_pct_boost = (
            max(
                0.0,
                (self.config.atr_percentile_low - atr_pct)
                / self.config.atr_percentile_low,
            )
            * 0.10
        )
        confidence += atr_pct_boost

        range_pos_boost = (1.0 - range_pos / self.config.range_position_max) * 0.10
        confidence += range_pos_boost

        confidence = min(confidence, 0.95)

        if confidence < self.config.min_confidence:
            return None

        rationale = (
            f"VRB {direction.value}: ATR_pct={atr_pct:.1f}%, "
            f"range_pos={range_pos:.2f}, trend={'bull' if trend == 1 else 'bear'}, "
            f"ATR={atr:.5f}, conf={confidence:.2f}"
        )

        self._last_signal_bar_index = len(state.bars)

        return _build_signal(
            direction, latest.close, atr, self.config, confidence, rationale, pip
        )
