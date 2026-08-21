from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Set

from backtest.engine import (
    Bar,
    MarketState,
    SessionType,
    StrategySignal,
    TradeDirection,
)

_PREFERRED_SESSIONS: Set[SessionType] = {
    SessionType.LONDON,
    SessionType.NY_AM,
}


@dataclass(frozen=True)
class BBReversionConfig:
    bb_period: int = 20
    bb_std_dev: float = 2.0
    rsi_period: int = 14
    rsi_long_threshold: float = 40.0
    rsi_short_threshold: float = 60.0
    atr_period: int = 14
    atr_sma_period: int = 20
    atr_sl_multiplier: float = 1.5
    tp_rr: float = 1.5
    session_filter: bool = True
    min_confidence: float = 0.55


GBPUSD_H1_PRESET = BBReversionConfig(
    bb_period=20,
    bb_std_dev=2.0,
    rsi_period=14,
    rsi_long_threshold=40.0,
    rsi_short_threshold=60.0,
    atr_period=14,
    atr_sma_period=20,
    atr_sl_multiplier=1.5,
    tp_rr=1.5,
    session_filter=True,
)


def _calculate_sma(values: List[float], period: int) -> float:
    if len(values) < period:
        return 0.0
    return sum(values[-period:]) / period


def _calculate_std(values: List[float], period: int) -> float:
    if len(values) < period:
        return 0.0
    subset = values[-period:]
    mean = sum(subset) / period
    variance = sum((v - mean) ** 2 for v in subset) / period
    return variance**0.5


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


def _calculate_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(diff if diff > 0 else 0.0)
        losses.append(-diff if diff < 0 else 0.0)

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _calculate_bollinger_bands(closes: List[float], period: int, std_dev: float) -> tuple[float, float, float]:
    sma = _calculate_sma(closes, period)
    std = _calculate_std(closes, period)
    upper = sma + std * std_dev
    lower = sma - std * std_dev
    return upper, sma, lower


def _is_low_volatility(bars: List[Bar], atr_period: int, atr_sma_period: int) -> bool:
    if len(bars) < atr_period + atr_sma_period + 1:
        return False
    atr_values: list[float] = []
    for i in range(atr_period, len(bars)):
        atr_values.append(_calculate_atr(bars[: i + 1], atr_period))
    if len(atr_values) < atr_sma_period:
        return False
    current_atr = atr_values[-1]
    atr_sma = _calculate_sma(atr_values, atr_sma_period)
    return current_atr < atr_sma


def _passes_session_filter(state: MarketState) -> bool:
    return state.current_session in _PREFERRED_SESSIONS


def _build_signal(
    direction: TradeDirection,
    entry: float,
    atr: float,
    config: BBReversionConfig,
    confidence: float,
    rationale: str,
) -> Optional[StrategySignal]:
    if atr <= 0:
        return None

    risk = atr * config.atr_sl_multiplier
    if direction == TradeDirection.LONG:
        sl = entry - risk
        tp1 = entry + risk * config.tp_rr
        tp2 = tp1
        tp3 = tp1
    else:
        sl = entry + risk
        tp1 = entry - risk * config.tp_rr
        tp2 = tp1
        tp3 = tp1

    if confidence < config.min_confidence:
        return None

    return StrategySignal(
        direction=direction,
        confidence=min(confidence, 0.95),
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
        rationale=rationale,
    )


class BBMeanReversionStrategy:
    def __init__(self, config: Optional[BBReversionConfig] = None):
        self.config = config or BBReversionConfig()

    @property
    def name(self) -> str:
        return "GBPUSD BB Mean Reversion"

    def reset(self) -> None:
        pass

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        min_required = (
            max(self.config.bb_period, self.config.atr_period, self.config.rsi_period) + self.config.atr_sma_period + 5
        )

        if len(state.bars) < min_required:
            return None

        if self.config.session_filter and not _passes_session_filter(state):
            return None

        bars = state.bars
        closes = [b.close for b in bars]
        latest = state.latest_bar

        bb_upper, bb_middle, bb_lower = _calculate_bollinger_bands(
            closes, self.config.bb_period, self.config.bb_std_dev
        )

        rsi = _calculate_rsi(closes, self.config.rsi_period)

        low_vol = _is_low_volatility(bars, self.config.atr_period, self.config.atr_sma_period)

        atr = state.atr if state.atr > 0 else _calculate_atr(bars, self.config.atr_period)

        direction = None
        signal_reason = ""

        long_condition = (
            latest.low <= bb_lower and rsi < self.config.rsi_long_threshold and low_vol and latest.close > bb_lower
        )

        short_condition = (
            latest.high >= bb_upper and rsi > self.config.rsi_short_threshold and low_vol and latest.close < bb_upper
        )

        if long_condition:
            direction = TradeDirection.LONG
            signal_reason = (
                f"Long: close={latest.close:.5f} > lower_BB={bb_lower:.5f}, "
                f"RSI={rsi:.1f}<{self.config.rsi_long_threshold}, "
                f"low_vol={low_vol}"
            )
        elif short_condition:
            direction = TradeDirection.SHORT
            signal_reason = (
                f"Short: close={latest.close:.5f} < upper_BB={bb_upper:.5f}, "
                f"RSI={rsi:.1f}>{self.config.rsi_short_threshold}, "
                f"low_vol={low_vol}"
            )

        if direction is None:
            return None

        confidence = 0.60
        rsi_distance = 0.0
        if direction == TradeDirection.LONG:
            rsi_distance = self.config.rsi_long_threshold - rsi
        else:
            rsi_distance = rsi - self.config.rsi_short_threshold
        confidence += min(rsi_distance / 40.0, 0.15)

        return _build_signal(direction, latest.close, atr, self.config, confidence, signal_reason)
