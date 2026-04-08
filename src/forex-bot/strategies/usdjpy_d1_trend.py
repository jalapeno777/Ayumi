from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from backtest.engine import Bar, MarketState, StrategySignal, TradeDirection
from backtest.strategies import ISignalStrategy


class USDJPYD1TrendStrategy(ISignalStrategy):
    """USDJPY D1 Trend-Following with EMA Cross + ADX Filter.

    Entry rules:
        - EMA(50) > EMA(200) for longs, EMA(50) < EMA(200) for shorts
        - ADX(14) > 25
        - RSI(14) > 50 for longs, < 50 for shorts
        - No trades on Friday D1 bars

    Exit rules:
        - SL: 2.0 x ATR(14)
        - TP: 2.0 x RR
        - Trail stop: 1.5 x ATR after 1R gain

    Risk management:
        - 1% risk per trade
        - Max 1 concurrent trade
    """

    def __init__(
        self,
        fast_ema_period: int = 50,
        slow_ema_period: int = 200,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        rsi_period: int = 14,
        atr_period: int = 14,
        sl_atr_multiplier: float = 2.0,
        tp_rr_ratio: float = 2.0,
        trail_atr_multiplier: float = 1.5,
        trail_trigger_rr: float = 1.0,
    ):
        self.fast_ema_period = fast_ema_period
        self.slow_ema_period = slow_ema_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.sl_atr_multiplier = sl_atr_multiplier
        self.tp_rr_ratio = tp_rr_ratio
        self.trail_atr_multiplier = trail_atr_multiplier
        self.trail_trigger_rr = trail_trigger_rr

    @property
    def name(self) -> str:
        return "USDJPY D1 Trend-Following"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        min_bars = self.slow_ema_period + self.adx_period + 1
        if len(state.bars) < min_bars:
            return None

        if self._is_friday(state.latest_bar.time):
            return None

        fast_ema = self._calculate_ema(state.bars, self.fast_ema_period)
        slow_ema = self._calculate_ema(state.bars, self.slow_ema_period)
        prev_fast_ema = self._calculate_ema(state.bars[:-1], self.fast_ema_period)
        prev_slow_ema = self._calculate_ema(state.bars[:-1], self.slow_ema_period)

        if fast_ema == 0 or slow_ema == 0 or prev_fast_ema == 0 or prev_slow_ema == 0:
            return None

        adx = self._calculate_adx(state.bars)
        if adx is None or adx < self.adx_threshold:
            return None

        rsi = self._calculate_rsi(state.bars)
        if rsi is None:
            return None

        bullish_cross = (
            prev_fast_ema <= prev_slow_ema and fast_ema > slow_ema and rsi > 50
        )
        bearish_cross = (
            prev_fast_ema >= prev_slow_ema and fast_ema < slow_ema and rsi < 50
        )

        if not bullish_cross and not bearish_cross:
            return None

        direction = TradeDirection.LONG if bullish_cross else TradeDirection.SHORT
        atr = self._calculate_atr(state.bars)
        entry = state.latest_bar.close

        if direction == TradeDirection.LONG:
            sl = entry - atr * self.sl_atr_multiplier
            risk = abs(entry - sl)
            tp1 = entry + risk * self.tp_rr_ratio
            tp2 = entry + risk * self.tp_rr_ratio * 1.5
            tp3 = entry + risk * self.tp_rr_ratio * 2.0
        else:
            sl = entry + atr * self.sl_atr_multiplier
            risk = abs(entry - sl)
            tp1 = entry - risk * self.tp_rr_ratio
            tp2 = entry - risk * self.tp_rr_ratio * 1.5
            tp3 = entry - risk * self.tp_rr_ratio * 2.0

        confidence = min(0.90, 0.55 + (adx - self.adx_threshold) / 100 * 0.35)

        rationale = (
            f"Long: EMA{self.fast_ema_period}={fast_ema:.3f} > EMA{self.slow_ema_period}={slow_ema:.3f}, "
            f"ADX={adx:.1f} > {self.adx_threshold}, RSI={rsi:.1f} > 50"
            if bullish_cross
            else f"Short: EMA{self.fast_ema_period}={fast_ema:.3f} < EMA{self.slow_ema_period}={slow_ema:.3f}, "
            f"ADX={adx:.1f} > {self.adx_threshold}, RSI={rsi:.1f} < 50"
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

    def _calculate_ema(self, bars: List[Bar], period: int) -> float:
        if len(bars) < period:
            return 0.0
        multiplier = 2.0 / (period + 1)
        sma = sum(b.close for b in bars[:period]) / period
        ema = sma
        for bar in bars[period:]:
            ema = (bar.close - ema) * multiplier + ema
        return ema

    def _calculate_adx(self, bars: List[Bar]) -> Optional[float]:
        if len(bars) < self.adx_period + 1:
            return None

        tr_list: List[float] = []
        plus_dm_list: List[float] = []
        minus_dm_list: List[float] = []

        for i in range(1, len(bars)):
            tr = max(
                bars[i].high - bars[i].low,
                abs(bars[i].high - bars[i - 1].close),
                abs(bars[i].low - bars[i - 1].close),
            )
            tr_list.append(tr)

            high_diff = bars[i].high - bars[i - 1].high
            low_diff = bars[i - 1].low - bars[i].low

            if high_diff > low_diff and high_diff > 0:
                plus_dm_list.append(high_diff)
            else:
                plus_dm_list.append(0.0)
            if low_diff > high_diff and low_diff > 0:
                minus_dm_list.append(low_diff)
            else:
                minus_dm_list.append(0.0)

        if len(tr_list) < self.adx_period:
            return None

        smoothed_tr = sum(tr_list[: self.adx_period])
        smoothed_plus_dm = sum(plus_dm_list[: self.adx_period])
        smoothed_minus_dm = sum(minus_dm_list[: self.adx_period])

        if smoothed_tr == 0:
            return 0.0

        plus_di = (smoothed_plus_dm / smoothed_tr) * 100
        minus_di = (smoothed_minus_dm / smoothed_tr) * 100

        if plus_di + minus_di == 0:
            return 0.0

        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100

        adx = dx
        for i in range(self.adx_period, len(tr_list)):
            if smoothed_tr == 0:
                continue

            smoothed_tr = smoothed_tr - smoothed_tr / self.adx_period + tr_list[i]
            smoothed_plus_dm = (
                smoothed_plus_dm - smoothed_plus_dm / self.adx_period + plus_dm_list[i]
            )
            smoothed_minus_dm = (
                smoothed_minus_dm
                - smoothed_minus_dm / self.adx_period
                + minus_dm_list[i]
            )

            if smoothed_tr == 0:
                continue

            plus_di = (smoothed_plus_dm / smoothed_tr) * 100
            minus_di = (smoothed_minus_dm / smoothed_tr) * 100

            if plus_di + minus_di == 0:
                dx = 0.0
            else:
                dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100

            adx = (adx * (self.adx_period - 1) + dx) / self.adx_period

        return adx

    def _calculate_rsi(self, bars: List[Bar]) -> Optional[float]:
        if len(bars) < self.rsi_period + 1:
            return None

        gains: List[float] = []
        losses: List[float] = []
        for i in range(len(bars) - self.rsi_period, len(bars)):
            change = bars[i].close - bars[i - 1].close
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))

        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_atr(self, bars: List[Bar]) -> float:
        if len(bars) < self.atr_period + 1:
            return 0.01
        tr_sum = 0.0
        for i in range(len(bars) - self.atr_period, len(bars)):
            if i > 0:
                tr = max(
                    bars[i].high - bars[i].low,
                    max(
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / self.atr_period

    @staticmethod
    def _is_friday(dt: datetime) -> bool:
        return dt.weekday() == 4
