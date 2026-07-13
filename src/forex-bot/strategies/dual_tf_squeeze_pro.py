"""Dual-timeframe Squeeze Pro strategy.

Two-stage squeeze with HTF (H1) confirmation. M15 bars drive entry; H1
context is maintained incrementally inside the strategy so the strategy can
be evaluated bar-by-bar without O(N^2) re-aggregation.

Reference: docs/research/strategy-optimization-research.md §B.2.

Stage 1 (H1 context):
  - H1 BB inside H1 KC  = squeeze active
  - H1 EMA(50) slope    = trend direction
  - H1 ADX              >= 18

Stage 2 (M15 entry trigger):
  - Squeeze active      -> M15 close breaks H1 KC boundary
  - Squeeze not active  -> H1 trend direction + M15 close near H1 Keltner
                            middle (pullback continuation)

Confirmation:
  - H1 ADX >= 18
  - M15 RSI in [40, 60]

Risk:
  - Stop = opposite H1 Keltner band OR 1.5*ATR(M15), whichever is closer
  - TP1/TP2/TP3 = 1R / 2R / 3R
  - Time exit handled by backtest engine
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from core.types import (
    Bar,
    MarketState,
    StrategySignal,
    TradeDirection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sma(values: List[float], period: int) -> float:
    if len(values) < period:
        return 0.0
    return sum(values[-period:]) / period


def _ema(values: List[float], period: int) -> List[float]:
    """Return full EMA series (same length as values)."""
    if len(values) < period:
        return [0.0] * len(values)
    multiplier = 2.0 / (period + 1)
    ema = [0.0] * len(values)
    s = sum(values[:period]) / period
    for i in range(period):
        ema[i] = s
    for i in range(period, len(values)):
        ema[i] = (values[i] - ema[i - 1]) * multiplier + ema[i - 1]
    return ema


def _std(values: List[float], period: int) -> float:
    if len(values) < period:
        return 0.0
    subset = values[-period:]
    mean = sum(subset) / period
    var = sum((v - mean) ** 2 for v in subset) / period
    return var ** 0.5


def _atr_from_true_ranges(trs: List[float], period: int) -> float:
    if len(trs) < period:
        return 0.0
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


def _true_range(bars: List[Bar]) -> float:
    if len(bars) < 2:
        return 0.0
    b = bars[-1]
    p = bars[-2]
    return max(
        b.high - b.low,
        abs(b.high - p.close),
        abs(b.low - p.close),
    )


def _rsi(bars: List[Bar], period: int) -> float:
    if len(bars) < period + 1:
        return 50.0
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(bars)):
        delta = bars[i].close - bars[i - 1].close
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    if len(gains) < period:
        return 50.0
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


def _adx(h1_bars: List[Bar], period: int = 14) -> float:
    """Wilder ADX from a list of H1 bars."""
    if len(h1_bars) < period * 2 + 1:
        return 0.0
    trs: List[float] = []
    plus_dms: List[float] = []
    minus_dms: List[float] = []
    for i in range(1, len(h1_bars)):
        b = h1_bars[i]
        p = h1_bars[i - 1]
        tr = max(
            b.high - b.low,
            abs(b.high - p.close),
            abs(b.low - p.close),
        )
        trs.append(tr)
        up = b.high - p.high
        down = p.low - b.low
        plus_dms.append(up if (up > down and up > 0) else 0.0)
        minus_dms.append(down if (down > up and down > 0) else 0.0)

    s_tr = sum(trs[:period])
    s_plus = sum(plus_dms[:period])
    s_minus = sum(minus_dms[:period])
    dxs: List[float] = []
    for i in range(period, len(trs)):
        s_tr = s_tr - (s_tr / period) + trs[i]
        s_plus = s_plus - (s_plus / period) + plus_dms[i]
        s_minus = s_minus - (s_minus / period) + minus_dms[i]
        if s_tr == 0:
            dxs.append(0.0)
            continue
        pdi = 100.0 * (s_plus / s_tr)
        mdi = 100.0 * (s_minus / s_tr)
        denom = pdi + mdi
        if denom == 0:
            dxs.append(0.0)
        else:
            dxs.append(100.0 * (abs(pdi - mdi) / denom))
    if len(dxs) < period:
        return 0.0
    adx = sum(dxs[:period]) / period
    for i in range(period, len(dxs)):
        adx = (adx * (period - 1) + dxs[i]) / period
    return adx


def _keltner(closes: List[float], atrs: List[float], period: int, atr_mult: float) -> Tuple[float, float, float]:
    """Return (upper, middle, lower) on latest bar using pre-computed EMAs and ATRs."""
    if len(closes) < period or len(atrs) < 1:
        return (0.0, 0.0, 0.0)
    mid = _ema(closes, period)[-1]
    a = atrs[-1]
    return (mid + a * atr_mult, mid, mid - a * atr_mult)


# ---------------------------------------------------------------------------
# Config & Strategy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DualTFSqueezeProConfig:
    # H1 context
    h1_bb_period: int = 20
    h1_bb_std: float = 2.0
    h1_kc_atr_mult: float = 1.5
    h1_ema_period: int = 50
    h1_adx_period: int = 14
    adx_min_h1: float = 18.0

    # M15 entry context
    m15_rsi_period: int = 14
    m15_atr_period: int = 14
    rsi_zone_min: float = 40.0
    rsi_zone_max: float = 60.0

    # Risk
    atr_sl_multiplier: float = 1.5
    tp1_rr: float = 1.0
    tp2_rr: float = 2.0
    tp3_rr: float = 3.0
    min_confidence: float = 0.40

    # Behavior
    cooldown_bars_m15: int = 10


XAUUSD_DTSQ_PRO = DualTFSqueezeProConfig()
GBPUSD_DTSQ_PRO = DualTFSqueezeProConfig()


class DualTFSqueezeProStrategy:
    """Dual-timeframe Squeeze Pro. Feed M15 bars; H1 is rebuilt incrementally."""

    def __init__(self, config: DualTFSqueezeProConfig | None = None):
        self.config = config or DualTFSqueezeProConfig()
        self._h1_bars: List[Bar] = []
        self._h1_hour: Optional[datetime] = None
        self._h1_trs: List[float] = []
        self._h1_closes: List[float] = []
        self._h1_atrs: List[float] = []
        self._h1_emas: List[float] = []
        self._m15_bars: List[Bar] = []
        self._bars_since_signal: int = 999

        # Incremental M15 ATR state
        self._m15_atr: float = 0.0
        self._m15_prev_close: Optional[float] = None
        # Incremental M15 RSI state
        self._m15_avg_gain: float = 0.0
        self._m15_avg_loss: float = 0.0
        self._m15_gain_history: List[float] = []
        self._m15_loss_history: List[float] = []

    @property
    def name(self) -> str:
        return "Dual-TF Squeeze Pro"

    def reset(self) -> None:
        self._h1_bars.clear()
        self._h1_hour = None
        self._h1_trs.clear()
        self._h1_closes.clear()
        self._h1_atrs.clear()
        self._h1_emas.clear()
        self._m15_bars.clear()
        self._bars_since_signal = 999
        self._m15_atr = 0.0
        self._m15_prev_close = None
        self._m15_avg_gain = 0.0
        self._m15_avg_loss = 0.0
        self._m15_gain_history.clear()
        self._m15_loss_history.clear()

    def _min_required(self) -> int:
        h1_lookback = max(
            self.config.h1_bb_period,
            self.config.h1_ema_period,
            self.config.h1_adx_period * 2,
        )
        return h1_lookback * 4 + self.config.m15_atr_period + 4

    def _update_h1(self, bar: Bar) -> None:
        """Ingest one M15 bar and update the synthetic H1 series."""
        hour = bar.time.replace(minute=0, second=0, microsecond=0)
        if self._h1_hour is None or hour != self._h1_hour:
            # Finalize previous hour if any
            if self._h1_bars:
                self._h1_closes.append(self._h1_bars[-1].close)
                tr = _true_range(self._h1_bars)
                self._h1_trs.append(tr)
                atr_period = self.config.h1_ema_period
                if len(self._h1_trs) >= atr_period:
                    if len(self._h1_trs) == atr_period:
                        atr = sum(self._h1_trs) / atr_period
                    else:
                        atr = (self._h1_atrs[-1] * (atr_period - 1) + tr) / atr_period
                    self._h1_atrs.append(atr)
                else:
                    self._h1_atrs.append(0.0)
                self._h1_emas.append(_ema(self._h1_closes, self.config.h1_ema_period)[-1])
            # Start new hour
            self._h1_hour = hour
            self._h1_bars.append(
                Bar(
                    time=hour,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
            )
        else:
            cur = self._h1_bars[-1]
            cur.high = max(cur.high, bar.high)
            cur.low = min(cur.low, bar.low)
            cur.close = bar.close
            cur.volume += bar.volume

    def _update_m15_indicators(self, bar: Bar) -> None:
        """Update incremental M15 ATR and RSI state."""
        if self._m15_prev_close is None:
            self._m15_prev_close = bar.close
            return

        tr = max(
            bar.high - bar.low,
            abs(bar.high - self._m15_prev_close),
            abs(bar.low - self._m15_prev_close),
        )
        n = len(self._m15_bars)
        period = self.config.m15_atr_period
        if n < period:
            # Simple average during warm-up
            self._m15_atr = (self._m15_atr * n + tr) / (n + 1)
        else:
            self._m15_atr = (self._m15_atr * (period - 1) + tr) / period

        delta = bar.close - self._m15_prev_close
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        self._m15_gain_history.append(gain)
        self._m15_loss_history.append(loss)
        rsi_period = self.config.m15_rsi_period
        if len(self._m15_gain_history) >= rsi_period:
            if len(self._m15_gain_history) == rsi_period:
                self._m15_avg_gain = sum(self._m15_gain_history) / rsi_period
                self._m15_avg_loss = sum(self._m15_loss_history) / rsi_period
            else:
                self._m15_avg_gain = (self._m15_avg_gain * (rsi_period - 1) + gain) / rsi_period
                self._m15_avg_loss = (self._m15_avg_loss * (rsi_period - 1) + loss) / rsi_period
        self._m15_prev_close = bar.close

    def _m15_rsi(self) -> float:
        if self._m15_avg_loss == 0:
            return 100.0
        rs = self._m15_avg_gain / self._m15_avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def evaluate(self, state: MarketState) -> StrategySignal | None:
        m15_bars = state.bars
        if len(m15_bars) < self._min_required():
            return None

        # Cooldown
        if self._bars_since_signal < self.config.cooldown_bars_m15:
            self._bars_since_signal += 1
            return None
        self._bars_since_signal += 1

        latest_m15 = m15_bars[-1]

        # Incremental rebuild only if we moved forward
        if len(self._m15_bars) != len(m15_bars):
            # Update from where we left off
            start = len(self._m15_bars)
            for b in m15_bars[start:]:
                self._update_m15_indicators(b)
                self._update_h1(b)
            self._m15_bars = list(m15_bars)

        h1_bars = self._h1_bars
        h1_closes = self._h1_closes
        h1_atrs = self._h1_atrs
        h1_emas = self._h1_emas

        if len(h1_bars) < max(
            self.config.h1_bb_period,
            self.config.h1_ema_period,
            self.config.h1_adx_period * 2,
        ):
            return None

        # Squeeze: latest H1 BB inside KC
        closes_window = [b.close for b in h1_bars[-self.config.h1_bb_period :]]
        if len(closes_window) < self.config.h1_bb_period:
            return None
        sma = _sma(closes_window, self.config.h1_bb_period)
        sd = _std(closes_window, self.config.h1_bb_period)
        bb_u = sma + sd * self.config.h1_bb_std
        bb_l = sma - sd * self.config.h1_bb_std
        kc_u, kc_m, kc_l = _keltner(h1_closes, h1_atrs, self.config.h1_ema_period, self.config.h1_kc_atr_mult)
        h1_in_squeeze = bb_u <= kc_u and bb_l >= kc_l

        h1_adx = _adx(h1_bars, self.config.h1_adx_period)
        if h1_adx < self.config.adx_min_h1:
            return None

        # H1 trend direction: compare EMA now vs 5 H1 bars ago
        if len(h1_emas) < self.config.h1_ema_period + 5:
            return None
        ema_now = h1_emas[-1]
        ema_prev = h1_emas[-6] if len(h1_emas) >= 6 else h1_emas[-2]
        if ema_now > ema_prev:
            h1_direction = 1
        elif ema_now < ema_prev:
            h1_direction = -1
        else:
            return None

        # M15 confirmation (incremental)
        if len(self._m15_bars) < self.config.m15_atr_period + 1:
            return None
        m15_rsi = self._m15_rsi()
        if not (self.config.rsi_zone_min <= m15_rsi <= self.config.rsi_zone_max):
            return None
        m15_atr = self._m15_atr
        if m15_atr <= 0:
            return None

        direction: Optional[TradeDirection] = None
        signal_type = ""
        squeeze_break = False

        if h1_in_squeeze:
            if latest_m15.close > kc_u:
                direction = TradeDirection.LONG
                signal_type = "squeeze_break_long"
                squeeze_break = True
            elif latest_m15.close < kc_l:
                direction = TradeDirection.SHORT
                signal_type = "squeeze_break_short"
                squeeze_break = True
        else:
            pullback_tol = m15_atr * 0.5
            if h1_direction == 1 and abs(latest_m15.close - kc_m) <= pullback_tol:
                direction = TradeDirection.LONG
                signal_type = "pullback_long"
            elif h1_direction == -1 and abs(latest_m15.close - kc_m) <= pullback_tol:
                direction = TradeDirection.SHORT
                signal_type = "pullback_short"

        if direction is None:
            return None

        entry = latest_m15.close
        if direction == TradeDirection.LONG:
            sl_kc = kc_l
            sl_atr = entry - m15_atr * self.config.atr_sl_multiplier
            sl = max(sl_kc, sl_atr)
        else:
            sl_kc = kc_u
            sl_atr = entry + m15_atr * self.config.atr_sl_multiplier
            sl = min(sl_kc, sl_atr)

        risk = abs(entry - sl)
        if risk <= 0:
            return None

        if direction == TradeDirection.LONG:
            tp1 = entry + risk * self.config.tp1_rr
            tp2 = entry + risk * self.config.tp2_rr
            tp3 = entry + risk * self.config.tp3_rr
        else:
            tp1 = entry - risk * self.config.tp1_rr
            tp2 = entry - risk * self.config.tp2_rr
            tp3 = entry - risk * self.config.tp3_rr

        confidence = self.config.min_confidence
        if squeeze_break:
            confidence += 0.10
        adx_excess = (h1_adx - self.config.adx_min_h1) / self.config.adx_min_h1
        confidence += min(adx_excess * 0.10, 0.15)
        rsi_mid_dist = abs(m15_rsi - 50.0) / 10.0
        confidence += max(0.0, 0.10 - rsi_mid_dist * 0.05)
        confidence = min(confidence, 0.85)

        if confidence < self.config.min_confidence:
            return None

        rationale = (
            f"DTSQ Pro {signal_type}: H1 squeeze={h1_in_squeeze} dir={h1_direction} "
            f"ADX={h1_adx:.1f} KC=({kc_l:.5f}/{kc_m:.5f}/{kc_u:.5f}); "
            f"M15 RSI={m15_rsi:.1f} close={entry:.5f} stop={sl:.5f} risk={risk:.5f}"
        )

        self._bars_since_signal = 0
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
