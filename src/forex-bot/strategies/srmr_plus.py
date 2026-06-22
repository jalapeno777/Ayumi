from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from backtest.engine import (
    Bar,
    MarketState,
    SessionType,
    StrategySignal,
    TradeDirection,
)
from backtest.strategy_legacy import ISignalStrategy
from config.sessions import SessionRangeHours

NO_SIGNAL = None


@dataclass(frozen=True)
class SRMRPlusConfig:
    atr_period: int = 14
    rsi_period: int = 14
    rsi_long_level: float = 35.0
    rsi_short_level: float = 65.0
    adx_period: int = 14
    adx_max_threshold: float = 25.0
    session_range_min_pips: float = 15.0
    entry_near_extreme_pips: float = 15.0
    hard_cap_sl_pips: float = 25.0
    tp1_rr: float = 1.5  # was 1.0; raised to pass min_risk_reward=1.5 gate
    tp2_rr: float = 1.5
    ema_trend_period: int = 50
    use_same_day_range: bool = False
    pip_value: float | None = None


_LONDON_START = SessionRangeHours.LONDON_START
_LONDON_END = SessionRangeHours.LONDON_END
_NY_OPEN_START = SessionRangeHours.NY_OPEN_START
_NY_OPEN_END = SessionRangeHours.NY_OPEN_END
_LONDON_NY_OVERLAP_START = SessionRangeHours.LONDON_NY_OVERLAP_START
_LONDON_NY_OVERLAP_END = SessionRangeHours.LONDON_NY_OVERLAP_END
_NY_CLOSE_START = SessionRangeHours.NY_CLOSE_START
_NY_CLOSE_END = SessionRangeHours.NY_CLOSE_END

logger = logging.getLogger(__name__)

_DEFAULT_PIP = 0.0001
_JPY_PIP = 0.01
_MIN_SL_PIPS = 5.0  # Minimum SL distance in pips


def _pip_value_for_price(price: float) -> float:
    if price >= 50:
        return _JPY_PIP
    return _DEFAULT_PIP


def _is_trading_session(bar_time: datetime) -> bool:
    utc_hour = bar_time.hour
    return (
        _LONDON_START.hour <= utc_hour < _LONDON_END.hour
        or _NY_OPEN_START.hour <= utc_hour < _NY_OPEN_END.hour
        or _LONDON_NY_OVERLAP_START.hour <= utc_hour < _LONDON_NY_OVERLAP_END.hour
    )


def _get_bar_session_type(bar_time: datetime) -> SessionType:
    utc_hour = bar_time.hour
    if _LONDON_START.hour <= utc_hour < _LONDON_END.hour:
        return SessionType.LONDON
    if _NY_OPEN_START.hour <= utc_hour < _NY_OPEN_END.hour:
        return SessionType.NY_AM
    if _LONDON_NY_OVERLAP_START.hour <= utc_hour < _LONDON_NY_OVERLAP_END.hour:
        return SessionType.NY_AM
    if _NY_CLOSE_START.hour <= utc_hour < _NY_CLOSE_END.hour:
        return SessionType.NY_PM
    return SessionType.OUTSIDE


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


def _calculate_rsi(bars: list[Bar], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
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


def _calculate_adx(bars: list[Bar], period: int = 14) -> float:
    if len(bars) < period * 2 + 1:
        return 0.0

    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]

    plus_dm_list: list[float] = []
    minus_dm_list: list[float] = []
    tr_list: list[float] = []

    for i in range(1, len(bars)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)

        high_diff = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]

        plus_dm = high_diff if (high_diff > low_diff and high_diff > 0) else 0.0
        minus_dm = low_diff if (low_diff > high_diff and low_diff > 0) else 0.0
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    if len(tr_list) < period:
        return 0.0

    tr_sum = sum(tr_list[:period])
    plus_dm_sum = sum(plus_dm_list[:period])
    minus_dm_sum = sum(minus_dm_list[:period])

    if tr_sum == 0:
        return 0.0

    plus_di = (plus_dm_sum / tr_sum) * 100
    minus_di = (minus_dm_sum / tr_sum) * 100

    if plus_di + minus_di == 0:
        dx = 0.0
    else:
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100

    dx_list: list[float] = [dx]
    for i in range(period, len(tr_list)):
        tr_sum = tr_sum - tr_sum / period + tr_list[i]
        plus_dm_sum = plus_dm_sum - plus_dm_sum / period + plus_dm_list[i]
        minus_dm_sum = minus_dm_sum - minus_dm_sum / period + minus_dm_list[i]

        if tr_sum == 0:
            dx_list.append(0.0)
            continue

        plus_di = (plus_dm_sum / tr_sum) * 100
        minus_di = (minus_dm_sum / tr_sum) * 100
        if plus_di + minus_di == 0:
            dx_list.append(0.0)
        else:
            dx_list.append(100.0 * (abs(plus_di - minus_di) / (plus_di + minus_di)))

    if len(dx_list) < period:
        return 0.0

    adx = sum(dx_list[:period]) / period
    for dx in dx_list[period:]:
        adx = (adx * (period - 1) + dx) / period

    return adx


def _calculate_session_range(
    bars: list[Bar], session_type: SessionType, reference_day: date
) -> tuple[float, float, float]:
    if not bars:
        return 0.0, 0.0, 0.0

    session_bars: list[Bar] = []
    for b in bars:
        if b.time.date() != reference_day:
            continue
        if _get_bar_session_type(b.time) == session_type:
            session_bars.append(b)

    if not session_bars:
        return 0.0, 0.0, 0.0

    high = max(b.high for b in session_bars)
    low = min(b.low for b in session_bars)
    mean = sum(b.close for b in session_bars) / len(session_bars)
    return high, low, mean


def _get_previous_session_range(
    bars: list[Bar], current_day: date, current_session: SessionType
) -> tuple[float, float, float]:
    if current_session == SessionType.LONDON:
        prev_day = _find_previous_trading_day(bars, current_day)
        if prev_day is None:
            return 0.0, 0.0, 0.0
        high, low, mean = _calculate_session_range(bars, SessionType.LONDON, prev_day)
        if high == 0:
            high, low, mean = _calculate_session_range(
                bars, SessionType.NY_AM, prev_day
            )
        return high, low, mean

    if current_session == SessionType.NY_AM:
        high, low, mean = _calculate_session_range(
            bars, SessionType.LONDON, current_day
        )
        if high == 0:
            prev_day = _find_previous_trading_day(bars, current_day)
            if prev_day is None:
                return 0.0, 0.0, 0.0
            high, low, mean = _calculate_session_range(
                bars, SessionType.LONDON, prev_day
            )
        return high, low, mean

    prev_day = _find_previous_trading_day(bars, current_day)
    if prev_day is None:
        return 0.0, 0.0, 0.0
    high, low, mean = _calculate_session_range(bars, SessionType.LONDON, prev_day)
    if high == 0:
        high, low, mean = _calculate_session_range(bars, SessionType.NY_AM, prev_day)
    return high, low, mean


def _find_previous_trading_day(bars: list[Bar], current_day: date) -> date | None:
    seen_days: set[date] = set()
    for b in bars:
        d = b.time.date()
        if d < current_day:
            seen_days.add(d)
    if not seen_days:
        return None
    return max(seen_days)


def _build_signal(
    direction: TradeDirection,
    entry: float,
    atr: float,
    config: SRMRPlusConfig,
    session_range_price: float,
    adx: float,
    rsi: float,
    rationale: str,
    pip: float,
) -> StrategySignal | None:
    if atr <= 0:
        logger.debug("SRMR+ _build_signal: ATR is zero or negative")
        return None

    sl_distance = min(
        session_range_price * 0.6,
        config.hard_cap_sl_pips * pip,
    )

    # Enforce minimum SL distance (5 pips) to prevent tiny stops
    min_sl = _MIN_SL_PIPS * pip
    if sl_distance < min_sl:
        sl_distance = min_sl

    if sl_distance <= 0:
        logger.debug("SRMR+ _build_signal: SL distance is zero or negative")
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

    confidence = 0.55 + (0.15 * (1.0 - adx / config.adx_max_threshold))
    confidence = min(0.80, max(0.40, confidence))

    return StrategySignal(
        direction=direction,
        confidence=confidence,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp2,
        rationale=rationale,
    )


class SRMRPlusStrategy(ISignalStrategy):
    def __init__(self, config: SRMRPlusConfig | None = None) -> None:
        super().__init__()
        self.config = config or SRMRPlusConfig()

    @property
    def name(self) -> str:
        return "SRMR+"

    def initialize(self, config: dict | None = None) -> None:
        """Initialize the SRMR+ strategy."""
        super().initialize(config)
        logger.info(
            "SRMRPlusStrategy initialized: rsi_long=%.1f rsi_short=%.1f adx_max=%.1f",
            self.config.rsi_long_level,
            self.config.rsi_short_level,
            self.config.adx_max_threshold,
        )

    def shutdown(self) -> None:
        """Clean up after SRMR+ run."""
        logger.info(
            "SRMRPlusStrategy shutdown (processed %d bars)",
            self._bars_processed,
        )
        super().shutdown()

    def evaluate(self, state: MarketState) -> StrategySignal | None:
        min_required = max(
            self.config.atr_period + self.config.rsi_period + 2,
            self.config.adx_period * 2 + 1,
            self.config.ema_trend_period + 1,
        )
        if len(state.bars) < min_required:
            logger.info("SRMR+ %s: insufficient bars (have=%d, need=%d)", getattr(state.bars[-1], 'symbol', '?') if state.bars else '?', len(state.bars), min_required)
            return None

        latest = state.latest_bar
        if not _is_trading_session(latest.time):
            logger.info("SRMR+ %s: outside trading hours (hour=%d)", getattr(latest, 'symbol', '?'), latest.time.hour)
            return None

        current_session = _get_bar_session_type(latest.time)
        current_day = latest.time.date()

        session_high, session_low, session_mean = _get_previous_session_range(
            state.bars, current_day, current_session
        )
        if session_high == 0:
            logger.debug("SRMR+ %s: no previous session range (day=%s session=%s)", getattr(latest, 'symbol', '?'), current_day, current_session)
            return None

        session_range_price = session_high - session_low
        pip = (
            self.config.pip_value
            if self.config.pip_value is not None
            else _pip_value_for_price(latest.close)
        )
        session_range_width = session_range_price / pip
        if session_range_width < self.config.session_range_min_pips:
            logger.debug("SRMR+ %s: session range too narrow (%.1f pips < %.1f min)", getattr(latest, 'symbol', '?'), session_range_width, self.config.session_range_min_pips)
            return None

        adx = _calculate_adx(state.bars, self.config.adx_period)
        if adx > self.config.adx_max_threshold:
            logger.debug("SRMR+ %s: ADX too high (%.1f > %.1f)", getattr(latest, 'symbol', '?'), adx, self.config.adx_max_threshold)
            return None

        atr = _calculate_atr(state.bars, self.config.atr_period)
        if atr <= 0:
            logger.debug("SRMR+ %s: ATR is zero or negative (%.6f)", getattr(latest, 'symbol', '?'), atr)
            return None

        rsi = _calculate_rsi(state.bars, self.config.rsi_period)
        if rsi is None:
            logger.debug("SRMR+ %s: RSI calculation returned None (bars=%d, period=%d)", getattr(latest, 'symbol', '?'), len(state.bars), self.config.rsi_period)
            return None

        price = latest.close
        entry_near_extreme_pips = self.config.entry_near_extreme_pips * pip

        if (
            price <= session_low + entry_near_extreme_pips
            and rsi < self.config.rsi_long_level
        ):
            direction = TradeDirection.LONG
            rationale = (
                f"SRMR+ long: price={price:.5f} near range low={session_low:.5f}, "
                f"RSI={rsi:.1f}, ADX={adx:.1f}, range={session_range_width:.1f} pips"
            )
            return _build_signal(
                direction,
                price,
                atr,
                self.config,
                session_range_price,
                adx,
                rsi,
                rationale,
                pip,
            )

        if (
            price >= session_high - entry_near_extreme_pips
            and rsi > self.config.rsi_short_level
        ):
            direction = TradeDirection.SHORT
            rationale = (
                f"SRMR+ short: price={price:.5f} near range high={session_high:.5f}, "
                f"RSI={rsi:.1f}, ADX={adx:.1f}, range={session_range_width:.1f} pips"
            )
            return _build_signal(
                direction,
                price,
                atr,
                self.config,
                session_range_price,
                adx,
                rsi,
                rationale,
                pip,
            )

        logger.debug("SRMR+ %s: no signal condition met (price=%.5f session_low=%.5f session_high=%.5f rsi=%.1f)", getattr(latest, 'symbol', '?'), price, session_low, session_high, rsi)
        return None
