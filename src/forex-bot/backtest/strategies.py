from typing import List, Optional, Tuple
from .engine import Bar, MarketState, StrategySignal, TradeDirection
from strategies.volatility_squeeze import VolatilitySqueezeStrategy as _VolatilitySqueezeStrategyImpl


class ISignalStrategy:
    @property
    def name(self) -> str:
        raise NotImplementedError

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        raise NotImplementedError


class MACrossStrategy(ISignalStrategy):
    def __init__(
        self, fast_period: int = 5, slow_period: int = 13, atr_multiplier: float = 2.0
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_multiplier = atr_multiplier

    @property
    def name(self) -> str:
        return "MA Crossover"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        if len(state.bars) < self.slow_period + 1:
            return None

        fast_ma = self._calculate_sma(state.bars, self.fast_period)
        slow_ma = self._calculate_sma(state.bars, self.slow_period)
        prev_fast_ma = self._calculate_sma(state.bars[:-1], self.fast_period)
        prev_slow_ma = self._calculate_sma(state.bars[:-1], self.slow_period)

        if fast_ma == 0 or slow_ma == 0 or prev_fast_ma == 0 or prev_slow_ma == 0:
            return None

        bullish_cross = prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma
        bearish_cross = prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma

        if not bullish_cross and not bearish_cross:
            return None

        direction = TradeDirection.LONG if bullish_cross else TradeDirection.SHORT
        atr = state.atr if state.atr > 0 else self._calculate_atr(state.bars)
        entry = state.latest_bar.close
        sl = (
            entry - atr * self.atr_multiplier
            if direction == TradeDirection.LONG
            else entry + atr * self.atr_multiplier
        )
        risk = abs(entry - sl)
        tp1 = (
            entry + risk * 1.0
            if direction == TradeDirection.LONG
            else entry - risk * 1.0
        )
        tp2 = (
            entry + risk * 2.0
            if direction == TradeDirection.LONG
            else entry - risk * 2.0
        )
        tp3 = (
            entry + risk * 3.0
            if direction == TradeDirection.LONG
            else entry - risk * 3.0
        )

        trend_strength = self._calculate_trend_strength(fast_ma, slow_ma)
        confidence = min(0.95, 0.50 + trend_strength * 0.45)

        rationale = (
            f"Bullish MA cross: fast={fast_ma:.5f} > slow={slow_ma:.5f}"
            if bullish_cross
            else f"Bearish MA cross: fast={fast_ma:.5f} < slow={slow_ma:.5f}"
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

    def _calculate_sma(self, bars: List[Bar], period: int) -> float:
        if len(bars) < period:
            return 0.0
        return sum(b.close for b in bars[-period:]) / period

    def _calculate_trend_strength(self, fast_ma: float, slow_ma: float) -> float:
        if slow_ma == 0:
            return 0.0
        return min(1.0, abs(fast_ma - slow_ma) / slow_ma * 10)

    def _calculate_atr(self, bars: List[Bar]) -> float:
        if len(bars) < 15:
            return 0.0001
        tr_sum = 0.0
        for i in range(len(bars) - 14, len(bars)):
            if i > 0:
                tr = max(
                    bars[i].high - bars[i].low,
                    max(
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / 14


class BBStrategy(ISignalStrategy):
    def __init__(
        self, period: int = 20, std_dev: float = 2.0, atr_multiplier: float = 2.0
    ):
        self.period = period
        self.std_dev = std_dev
        self.atr_multiplier = atr_multiplier

    @property
    def name(self) -> str:
        return "Bollinger Band Mean Reversion"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        if len(state.bars) < self.period + 1:
            return None

        sma = self._calculate_sma(state.bars)
        std = self._calculate_std(state.bars, sma)
        if std == 0:
            return None

        upper_band = sma + std * self.std_dev
        lower_band = sma - std * self.std_dev
        latest = state.latest_bar

        if latest.close < lower_band:
            direction = TradeDirection.LONG
            entry = latest.close
            atr = state.atr if state.atr > 0 else self._calculate_atr(state.bars)
            sl = entry - atr * self.atr_multiplier
            risk = abs(entry - sl)
            tp1 = entry + risk * 1.0
            tp2 = entry + risk * 2.0
            tp3 = entry + risk * 3.0
            confidence = min(
                0.90, 0.60 + (lower_band - latest.close) / lower_band * 0.30
            )
            rationale = (
                f"BB oversold: close={latest.close:.5f} < lower={lower_band:.5f}"
            )
        elif latest.close > upper_band:
            direction = TradeDirection.SHORT
            entry = latest.close
            atr = state.atr if state.atr > 0 else self._calculate_atr(state.bars)
            sl = entry + atr * self.atr_multiplier
            risk = abs(entry - sl)
            tp1 = entry - risk * 1.0
            tp2 = entry - risk * 2.0
            tp3 = entry - risk * 3.0
            confidence = min(
                0.90, 0.60 + (latest.close - upper_band) / upper_band * 0.30
            )
            rationale = (
                f"BB overbought: close={latest.close:.5f} > upper={upper_band:.5f}"
            )
        else:
            return None

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

    def _calculate_sma(self, bars: List[Bar]) -> float:
        if len(bars) < self.period:
            return 0.0
        return sum(b.close for b in bars[-self.period :]) / self.period

    def _calculate_std(self, bars: List[Bar], sma: float) -> float:
        if len(bars) < self.period:
            return 0.0
        variance = sum((b.close - sma) ** 2 for b in bars[-self.period :]) / self.period
        return variance**0.5

    def _calculate_atr(self, bars: List[Bar]) -> float:
        if len(bars) < 15:
            return 0.0001
        tr_sum = 0.0
        for i in range(len(bars) - 14, len(bars)):
            if i > 0:
                tr = max(
                    bars[i].high - bars[i].low,
                    max(
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / 14


class RSIStrategy(ISignalStrategy):
    def __init__(
        self,
        period: int = 14,
        oversold: float = 35.0,
        overbought: float = 65.0,
        mid: float = 50.0,
        atr_multiplier: float = 2.0,
    ):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.mid = mid
        self.atr_multiplier = atr_multiplier

    @property
    def name(self) -> str:
        return "RSI Divergence"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        if len(state.bars) < self.period + 2:
            return None

        rsi = self._calculate_rsi(state.bars)
        if rsi is None:
            return None

        latest = state.latest_bar

        if rsi < self.oversold:
            direction = TradeDirection.LONG
            atr = state.atr if state.atr > 0 else self._calculate_atr(state.bars)
            entry = latest.close
            sl = entry - atr * self.atr_multiplier
            risk = abs(entry - sl)
            tp1 = entry + risk * 1.0
            tp2 = entry + risk * 2.0
            tp3 = entry + risk * 3.0
            confidence = min(0.85, 0.55 + (self.oversold - rsi) / self.oversold * 0.30)
            rationale = f"RSI oversold: rsi={rsi:.1f} < {self.oversold}"
        elif rsi > self.overbought:
            direction = TradeDirection.SHORT
            atr = state.atr if state.atr > 0 else self._calculate_atr(state.bars)
            entry = latest.close
            sl = entry + atr * self.atr_multiplier
            risk = abs(entry - sl)
            tp1 = entry - risk * 1.0
            tp2 = entry - risk * 2.0
            tp3 = entry - risk * 3.0
            confidence = min(
                0.85, 0.55 + (rsi - self.overbought) / (100 - self.overbought) * 0.30
            )
            rationale = f"RSI overbought: rsi={rsi:.1f} > {self.overbought}"
        else:
            return None

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

    def _calculate_rsi(self, bars: List[Bar]) -> Optional[float]:
        if len(bars) < self.period + 1:
            return None

        gains: List[float] = []
        losses: List[float] = []
        for i in range(len(bars) - self.period, len(bars)):
            change = bars[i].close - bars[i - 1].close
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))

        avg_gain = sum(gains) / self.period
        avg_loss = sum(losses) / self.period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_atr(self, bars: List[Bar]) -> float:
        if len(bars) < 15:
            return 0.0001
        tr_sum = 0.0
        for i in range(len(bars) - 14, len(bars)):
            if i > 0:
                tr = max(
                    bars[i].high - bars[i].low,
                    max(
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / 14


class SRBreakoutStrategy(ISignalStrategy):
    def __init__(
        self,
        lookback: int = 50,
        confirmation_bars: int = 1,
        breakout_threshold: float = 0.0001,
        atr_multiplier: float = 2.0,
    ):
        self.lookback = lookback
        self.confirmation_bars = confirmation_bars
        self.breakout_threshold = breakout_threshold
        self.atr_multiplier = atr_multiplier

    @property
    def name(self) -> str:
        return "S/R Breakout"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        if len(state.bars) < self.lookback + self.confirmation_bars:
            return None

        lookback_bars = state.bars[-self.lookback - 1 : -1]
        resistance = max(b.high for b in lookback_bars)
        support = min(b.low for b in lookback_bars)
        latest = state.latest_bar

        bullish_breakout = False
        bearish_breakout = False

        if latest.close > resistance + self.breakout_threshold:
            confirm_count = 0
            for i in range(len(state.bars) - self.confirmation_bars, len(state.bars)):
                if state.bars[i].close > resistance:
                    confirm_count += 1
            if confirm_count >= self.confirmation_bars:
                bullish_breakout = True

        if latest.close < support - self.breakout_threshold:
            confirm_count = 0
            for i in range(len(state.bars) - self.confirmation_bars, len(state.bars)):
                if state.bars[i].close < support:
                    confirm_count += 1
            if confirm_count >= self.confirmation_bars:
                bearish_breakout = True

        if not bullish_breakout and not bearish_breakout:
            return None

        if bullish_breakout:
            direction = TradeDirection.LONG
            entry = latest.close
            sl = support
            risk = abs(entry - sl)
            tp1 = entry + risk * 1.0
            tp2 = entry + risk * 2.0
            tp3 = entry + risk * 3.0
            confidence = min(
                0.85, 0.50 + (latest.close - resistance) / resistance * 0.35
            )
            rationale = f"Bullish S/R breakout: close={latest.close:.5f} > resistance={resistance:.5f}"
        else:
            direction = TradeDirection.SHORT
            entry = latest.close
            sl = resistance
            risk = abs(entry - sl)
            tp1 = entry - risk * 1.0
            tp2 = entry - risk * 2.0
            tp3 = entry - risk * 3.0
            confidence = min(0.85, 0.50 + (support - latest.close) / support * 0.35)
            rationale = f"Bearish S/R breakout: close={latest.close:.5f} < support={support:.5f}"

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

    def _calculate_atr(self, bars: List[Bar]) -> float:
        if len(bars) < 15:
            return 0.0001
        tr_sum = 0.0
        for i in range(len(bars) - 14, len(bars)):
            if i > 0:
                tr = max(
                    bars[i].high - bars[i].low,
                    max(
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / 14


class ROCMStrategy(ISignalStrategy):
    def __init__(
        self, period: int = 12, roc_threshold: float = 0.3, atr_multiplier: float = 2.0
    ):
        self.period = period
        self.roc_threshold = roc_threshold
        self.atr_multiplier = atr_multiplier

    @property
    def name(self) -> str:
        return "Momentum ROC"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        if len(state.bars) < self.period + 1:
            return None

        roc = self._calculate_roc(state.bars)
        if roc is None:
            return None

        latest = state.latest_bar
        atr = state.atr if state.atr > 0 else self._calculate_atr(state.bars)

        if roc > self.roc_threshold:
            direction = TradeDirection.LONG
            entry = latest.close
            sl = entry - atr * self.atr_multiplier
            risk = abs(entry - sl)
            tp1 = entry + risk * 1.0
            tp2 = entry + risk * 2.0
            tp3 = entry + risk * 3.0
            confidence = min(0.85, 0.50 + min(roc, 2.0) / 2.0 * 0.35)
            rationale = f"Positive momentum ROC: roc={roc:.3f}% > {self.roc_threshold}%"
        elif roc < -self.roc_threshold:
            direction = TradeDirection.SHORT
            entry = latest.close
            sl = entry + atr * self.atr_multiplier
            risk = abs(entry - sl)
            tp1 = entry - risk * 1.0
            tp2 = entry - risk * 2.0
            tp3 = entry - risk * 3.0
            confidence = min(0.85, 0.50 + min(abs(roc), 2.0) / 2.0 * 0.35)
            rationale = (
                f"Negative momentum ROC: roc={roc:.3f}% < -{self.roc_threshold}%"
            )
        else:
            return None

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

    def _calculate_roc(self, bars: List[Bar]) -> Optional[float]:
        if len(bars) < self.period + 1:
            return None
        current_close = bars[-1].close
        past_close = bars[-self.period - 1].close
        if past_close == 0:
            return None
        return ((current_close - past_close) / past_close) * 100

    def _calculate_atr(self, bars: List[Bar]) -> float:
        if len(bars) < 15:
            return 0.0001
        tr_sum = 0.0
        for i in range(len(bars) - 14, len(bars)):
            if i > 0:
                tr = max(
                    bars[i].high - bars[i].low,
                    max(
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / 14


class MomentumBreakoutStrategy(ISignalStrategy):
    """Momentum/Breakout strategy using EMA crossover with ADX trend confirmation.

    Entry signals are generated when the fast EMA crosses the slow EMA
    AND the ADX indicator is above the threshold (indicating a strong trend).
    Stop loss is calculated using ATR multiplier. Take profit levels are
    set at 1R, 2R, and 3R risk multiples.

    Args:
        fast_period: Period for fast EMA (default 9).
        slow_period: Period for slow EMA (default 21).
        adx_period: Period for ADX calculation (default 14).
        adx_threshold: Minimum ADX value to confirm trend (default 25.0).
        atr_multiplier: ATR multiplier for stop loss (default 2.0).
    """

    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        atr_multiplier: float = 2.0,
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.atr_multiplier = atr_multiplier

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "Momentum Breakout"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        """Evaluate market state and generate trading signal if conditions are met.

        Args:
            state: Current market state containing OHLC bars and session info.

        Returns:
            StrategySignal if entry conditions are met (EMA crossover + ADX > threshold),
            None otherwise.
        """
        if len(state.bars) < self.slow_period + self.adx_period + 1:
            return None

        fast_ema = self._calculate_ema(state.bars, self.fast_period)
        slow_ema = self._calculate_ema(state.bars, self.slow_period)
        prev_fast_ema = self._calculate_ema(state.bars[:-1], self.fast_period)
        prev_slow_ema = self._calculate_ema(state.bars[:-1], self.slow_period)

        if fast_ema == 0 or slow_ema == 0 or prev_fast_ema == 0 or prev_slow_ema == 0:
            return None

        adx = self._calculate_adx(state.bars)
        if adx is None or adx < self.adx_threshold:
            return None

        bullish_cross = prev_fast_ema <= prev_slow_ema and fast_ema > slow_ema
        bearish_cross = prev_fast_ema >= prev_slow_ema and fast_ema < slow_ema

        if not bullish_cross and not bearish_cross:
            return None

        direction = TradeDirection.LONG if bullish_cross else TradeDirection.SHORT
        atr = state.atr if state.atr > 0 else self._calculate_atr(state.bars)
        entry = state.latest_bar.close
        sl = (
            entry - atr * self.atr_multiplier
            if direction == TradeDirection.LONG
            else entry + atr * self.atr_multiplier
        )
        risk = abs(entry - sl)
        tp1 = (
            entry + risk * 1.0
            if direction == TradeDirection.LONG
            else entry - risk * 1.0
        )
        tp2 = (
            entry + risk * 2.0
            if direction == TradeDirection.LONG
            else entry - risk * 2.0
        )
        tp3 = (
            entry + risk * 3.0
            if direction == TradeDirection.LONG
            else entry - risk * 3.0
        )

        if adx >= 40:
            confidence = 0.8
        else:
            confidence = 0.6

        rationale = (
            f"Bullish EMA cross + ADX confirm: fast={fast_ema:.5f} > slow={slow_ema:.5f}, ADX={adx:.1f} > {self.adx_threshold}"
            if bullish_cross
            else f"Bearish EMA cross + ADX confirm: fast={fast_ema:.5f} < slow={slow_ema:.5f}, ADX={adx:.1f} > {self.adx_threshold}"
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
        ema = sum(b.close for b in bars[:period]) / period
        for bar in bars[period:]:
            ema = (bar.close - ema) * multiplier + ema
        return ema

    def _calculate_adx(self, bars: List[Bar]) -> Optional[float]:
        if len(bars) < self.adx_period + 1:
            return None

        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]

        plus_dm_list = []
        minus_dm_list = []
        tr_list = []

        for i in range(1, len(bars)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_list.append(tr)

            high_diff = highs[i] - highs[i - 1]
            low_diff = lows[i - 1] - lows[i]

            if high_diff > low_diff and high_diff > 0:
                plus_dm_list.append(high_diff)
            else:
                plus_dm_list.append(0)
            if low_diff > high_diff and low_diff > 0:
                minus_dm_list.append(low_diff)
            else:
                minus_dm_list.append(0)

        if len(tr_list) < self.adx_period:
            return None

        tr_sum = sum(tr_list[: self.adx_period])
        plus_dm_sum = sum(plus_dm_list[: self.adx_period])
        minus_dm_sum = sum(minus_dm_list[: self.adx_period])

        if tr_sum == 0:
            return None

        plus_di = (plus_dm_sum / tr_sum) * 100
        minus_di = (minus_dm_sum / tr_sum) * 100

        if plus_di + minus_di == 0:
            return 0.0

        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100

        adx = dx
        for i in range(self.adx_period, len(tr_list)):
            tr_sum = tr_sum - tr_sum / self.adx_period + tr_list[i]
            plus_dm_sum = plus_dm_sum - plus_dm_sum / self.adx_period + plus_dm_list[i]
            minus_dm_sum = (
                minus_dm_sum - minus_dm_sum / self.adx_period + minus_dm_list[i]
            )

            if tr_sum == 0:
                continue

            plus_di = (plus_dm_sum / tr_sum) * 100
            minus_di = (minus_dm_sum / tr_sum) * 100

            if plus_di + minus_di == 0:
                dx = 0
            else:
                dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100

            adx = (adx * (self.adx_period - 1) + dx) / self.adx_period

        return adx

    def _calculate_atr(self, bars: List[Bar]) -> float:
        if len(bars) < 15:
            return 0.0001
        tr_sum = 0.0
        for i in range(len(bars) - 14, len(bars)):
            if i > 0:
                tr = max(
                    bars[i].high - bars[i].low,
                    max(
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / 14


class CommodityTrendStrategy(ISignalStrategy):
    """Trend following strategy for commodity markets using EMA crossover and ADX confirmation.

    Entry rules:
        - EMA 20/50 bullish crossover (fast EMA crosses above slow EMA)
        - ADX > threshold (default 25) confirms trend strength

    Exit rules:
        - Stop loss: 1.75x ATR (gold ATR is higher than forex)
        - Take profit: 2-3x risk
        - Confidence scales with ADX value

    Designed for XAUUSD H1 with gold's higher ATR characteristics.
    """

    def __init__(
        self,
        fast_ema_period: int = 20,
        slow_ema_period: int = 50,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        atr_multiplier: float = 1.75,
        risk_reward_ratio: float = 2.0,
    ):
        self.fast_ema_period = fast_ema_period
        self.slow_ema_period = slow_ema_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.atr_multiplier = atr_multiplier
        self.risk_reward_ratio = risk_reward_ratio

    def _calculate_atr(self, bars: List[Bar]) -> float:
        if len(bars) < 15:
            return 0.0001
        tr_sum = 0.0
        for i in range(len(bars) - 14, len(bars)):
            if i > 0:
                tr = max(
                    bars[i].high - bars[i].low,
                    max(
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / 14

    @property
    def name(self) -> str:
        return "Commodity Trend Following"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        if len(state.bars) < self.slow_ema_period + self.adx_period + 1:
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

        bullish_cross = prev_fast_ema <= prev_slow_ema and fast_ema > slow_ema
        bearish_cross = prev_fast_ema >= prev_slow_ema and fast_ema < slow_ema

        if not bullish_cross and not bearish_cross:
            return None

        direction = TradeDirection.LONG if bullish_cross else TradeDirection.SHORT
        atr = state.atr if state.atr > 0 else self._calculate_atr(state.bars)
        entry = state.latest_bar.close
        sl = (
            entry - atr * self.atr_multiplier
            if direction == TradeDirection.LONG
            else entry + atr * self.atr_multiplier
        )
        risk = abs(entry - sl)
        tp1 = (
            entry + risk * self.risk_reward_ratio
            if direction == TradeDirection.LONG
            else entry - risk * self.risk_reward_ratio
        )
        tp2 = (
            entry + risk * self.risk_reward_ratio * 2.0
            if direction == TradeDirection.LONG
            else entry - risk * self.risk_reward_ratio * 2.0
        )
        tp3 = (
            entry + risk * self.risk_reward_ratio * 3.0
            if direction == TradeDirection.LONG
            else entry - risk * self.risk_reward_ratio * 3.0
        )

        confidence = min(0.90, 0.50 + (adx - self.adx_threshold) / 100 * 0.40)
        rationale = (
            f"Bullish EMA cross + ADX confirmed: fast={fast_ema:.5f} > slow={slow_ema:.5f}, ADX={adx:.1f}"
            if bullish_cross
            else f"Bearish EMA cross + ADX confirmed: fast={fast_ema:.5f} < slow={slow_ema:.5f}, ADX={adx:.1f}"
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
            smoothed_plus_dm = smoothed_plus_dm - smoothed_plus_dm / self.adx_period + plus_dm_list[i]
            smoothed_minus_dm = smoothed_minus_dm - smoothed_minus_dm / self.adx_period + minus_dm_list[i]

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


class CommodityMeanReversionStrategy(ISignalStrategy):
    """Mean reversion strategy for commodities using Bollinger Bands and RSI.

    Entry rules:
        - Long: Price below lower Bollinger Band + RSI < 30 (oversold) + bullish reversal candle
        - Short: Price above upper Bollinger Band + RSI > 70 (overbought) + bearish reversal candle

    Exit rules:
        - Stop loss: Beyond outer Bollinger Band by 0.5x ATR
        - Take profit: tp1 = Middle Band (mean reversion target), tp2/tp3 = 2x/3x risk for scaling
        - Confidence based on RSI deviation from thresholds

    Designed for XAUUSD H1 with gold's higher ATR characteristics.
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std_dev: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        atr_multiplier: float = 2.0,
    ):
        self.bb_period = bb_period
        self.bb_std_dev = bb_std_dev
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_multiplier = atr_multiplier

    def _calculate_atr(self, bars: List[Bar]) -> float:
        if len(bars) < 15:
            return 0.0001
        tr_sum = 0.0
        for i in range(len(bars) - 14, len(bars)):
            if i > 0:
                tr = max(
                    bars[i].high - bars[i].low,
                    max(
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / 14

    @property
    def name(self) -> str:
        return "Commodity Mean Reversion"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        if len(state.bars) < self.bb_period + 1:
            return None

        sma = self._calculate_sma(state.bars)
        std = self._calculate_std(state.bars, sma)
        if std == 0:
            return None

        upper_band = sma + std * self.bb_std_dev
        lower_band = sma - std * self.bb_std_dev
        middle_band = sma
        latest = state.latest_bar

        rsi = self._calculate_rsi(state.bars)
        if rsi is None:
            return None

        atr = state.atr if state.atr > 0 else self._calculate_atr(state.bars)

        if latest.close < lower_band and rsi < self.rsi_oversold:
            if not self._is_bullish_reversal(latest):
                return None
            direction = TradeDirection.LONG
            entry = latest.close
            sl = lower_band - atr * 0.5
            band_distance = lower_band - entry
            risk = max(abs(entry - sl), band_distance * 0.5)
            tp1 = min(middle_band, entry + risk * 1.0)
            tp2 = entry + risk * 2.0
            tp3 = entry + risk * 3.0
            confidence = min(
                0.90, 0.55 + (self.rsi_oversold - rsi) / self.rsi_oversold * 0.35
            )
            rationale = f"BB oversold + RSI oversold + bullish reversal: close={latest.close:.5f} < lower={lower_band:.5f}, RSI={rsi:.1f}"
        elif latest.close > upper_band and rsi > self.rsi_overbought:
            if not self._is_bearish_reversal(latest):
                return None
            direction = TradeDirection.SHORT
            entry = latest.close
            sl = upper_band + atr * 0.5
            band_distance = entry - upper_band
            risk = max(abs(entry - sl), band_distance * 0.5)
            tp1 = max(middle_band, entry - risk * 1.0)
            tp2 = entry - risk * 2.0
            tp3 = entry - risk * 3.0
            confidence = min(
                0.90,
                0.55 + (rsi - self.rsi_overbought) / (100 - self.rsi_overbought) * 0.35,
            )
            rationale = f"BB overbought + RSI overbought: close={latest.close:.5f} > upper={upper_band:.5f}, RSI={rsi:.1f}"
        else:
            return None

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

    def _calculate_sma(self, bars: List[Bar]) -> float:
        if len(bars) < self.bb_period:
            return 0.0
        return sum(b.close for b in bars[-self.bb_period :]) / self.bb_period

    def _calculate_std(self, bars: List[Bar], sma: float) -> float:
        if len(bars) < self.bb_period:
            return 0.0
        variance = (
            sum((b.close - sma) ** 2 for b in bars[-self.bb_period :]) / self.bb_period
        )
        return variance**0.5

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

    def _is_bullish_reversal(self, bar: Bar) -> bool:
        candle_range = bar.high - bar.low
        if candle_range == 0:
            return False
        midpoint = bar.low + candle_range * 0.5
        return bar.close > midpoint

    def _is_bearish_reversal(self, bar: Bar) -> bool:
        candle_range = bar.high - bar.low
        if candle_range == 0:
            return False
        midpoint = bar.low + candle_range * 0.5
        return bar.close < midpoint


class SupertrendRSIBlendStrategy(ISignalStrategy):
    def __init__(
        self,
        supertrend_period: int = 14,
        supertrend_multiplier: float = 2.5,
        rsi_period: int = 14,
        rsi_threshold: float = 50.0,
        atr_min_pips: float = 10.0,
        atr_period: int = 14,
        adx_period: int = 14,
        adx_min: float = 20.0,
        atr_min_chop: float = 8.0,
        sl_atr_multiplier: float = 1.5,
        hard_cap_pips: float = 40.0,
        tp1_atr: float = 1.5,
        tp2_atr: float = 2.5,
        time_exit_bars: int = 20,
    ):
        self.supertrend_period = supertrend_period
        self.supertrend_multiplier = supertrend_multiplier
        self.rsi_period = rsi_period
        self.rsi_threshold = rsi_threshold
        self.atr_min_pips = atr_min_pips
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.adx_min = adx_min
        self.atr_min_chop = atr_min_chop
        self.sl_atr_multiplier = sl_atr_multiplier
        self.hard_cap_pips = hard_cap_pips
        self.tp1_atr = tp1_atr
        self.tp2_atr = tp2_atr
        self.time_exit_bars = time_exit_bars

    @property
    def name(self) -> str:
        return "Supertrend RSI Blend"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        min_bars = max(self.supertrend_period, self.rsi_period, self.adx_period) + 5
        if len(state.bars) < min_bars:
            return None

        atr = self._calculate_atr(state.bars)
        atr_pips = atr * 10000

        if atr_pips < self.atr_min_chop:
            return None

        adx = self._calculate_adx(state.bars)
        if adx is not None and adx < self.adx_min:
            consecutive_low_adx = 0
            for i in range(len(state.bars) - 3, len(state.bars)):
                check_adx = self._calculate_adx(state.bars[: i + 1])
                if check_adx is not None and check_adx < self.adx_min:
                    consecutive_low_adx += 1
            if consecutive_low_adx >= 3:
                return None

        bar_time = state.latest_bar.time
        hour = bar_time.hour
        minute = bar_time.minute
        if hour == 0 and minute < 30:
            return None

        if atr_pips < self.atr_min_pips:
            return None

        supertrend_value, prev_supertrend_value = self._calculate_supertrend(state.bars)
        if supertrend_value is None or prev_supertrend_value is None:
            return None

        rsi = self._calculate_rsi(state.bars)
        if rsi is None:
            return None

        prev_rsi_values = self._get_prev_rsi_values(state.bars)

        latest = state.latest_bar

        long_conditions = (
            prev_supertrend_value < 0
            and supertrend_value > 0
            and rsi > self.rsi_threshold
            and any(r < self.rsi_threshold for r in prev_rsi_values)
        )

        short_conditions = (
            prev_supertrend_value > 0
            and supertrend_value < 0
            and rsi < self.rsi_threshold
            and any(r > self.rsi_threshold for r in prev_rsi_values)
        )

        if not long_conditions and not short_conditions:
            return None

        direction = TradeDirection.LONG if long_conditions else TradeDirection.SHORT
        entry = latest.close

        sl_distance = atr * self.sl_atr_multiplier
        sl_distance_pips = sl_distance * 10000
        if sl_distance_pips > self.hard_cap_pips:
            sl_distance = self.hard_cap_pips / 10000

        sl = entry - sl_distance if direction == TradeDirection.LONG else entry + sl_distance
        risk = abs(entry - sl)

        tp1 = entry + risk * self.tp1_atr if direction == TradeDirection.LONG else entry - risk * self.tp1_atr
        tp2 = entry + risk * self.tp2_atr if direction == TradeDirection.LONG else entry - risk * self.tp2_atr
        tp3 = entry + risk * 3.0 if direction == TradeDirection.LONG else entry - risk * 3.0

        confidence = min(0.85, 0.55 + abs(rsi - self.rsi_threshold) / 50 * 0.30)

        if long_conditions:
            rationale = (
                f"Supertrend Long flip + RSI confirm: ST={supertrend_value:.5f}, RSI={rsi:.1f} > {self.rsi_threshold}"
            )
        else:
            rationale = (
                f"Supertrend Short flip + RSI confirm: ST={supertrend_value:.5f}, RSI={rsi:.1f} < {self.rsi_threshold}"
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

    def _calculate_supertrend(self, bars: List[Bar]) -> Tuple[Optional[float], Optional[float]]:
        if len(bars) < self.supertrend_period + 1:
            return None, None

        atr = self._calculate_atr(bars)
        if atr == 0:
            return None, None

        hl2_list = [(b.high + b.low) / 2 for b in bars]
        upper_band_list = [0.0] * len(bars)
        lower_band_list = [0.0] * len(bars)
        supertrend_list = [0.0] * len(bars)

        for i in range(len(bars)):
            if i < self.supertrend_period:
                upper_band_list[i] = hl2_list[i] + atr * self.supertrend_multiplier
                lower_band_list[i] = hl2_list[i] - atr * self.supertrend_multiplier
                supertrend_list[i] = 1.0
                continue

            hl2 = hl2_list[i]
            upper_band_list[i] = hl2 + atr * self.supertrend_multiplier
            lower_band_list[i] = hl2 - atr * self.supertrend_multiplier

            prev_upper = upper_band_list[i - 1]
            prev_lower = lower_band_list[i - 1]
            prev_close = bars[i - 1].close

            if upper_band_list[i] > prev_upper or prev_close > prev_upper:
                upper_band_list[i] = upper_band_list[i]
            else:
                upper_band_list[i] = prev_upper

            if lower_band_list[i] < prev_lower or prev_close < prev_lower:
                lower_band_list[i] = lower_band_list[i]
            else:
                lower_band_list[i] = prev_lower

            prev_supertrend = supertrend_list[i - 1]

            if prev_supertrend == 1.0:
                if bars[i].close < lower_band_list[i]:
                    supertrend_list[i] = -1.0
                else:
                    supertrend_list[i] = 1.0
            else:
                if bars[i].close > upper_band_list[i]:
                    supertrend_list[i] = 1.0
                else:
                    supertrend_list[i] = -1.0

        if len(bars) < 2:
            return supertrend_list[-1], None

        atr_current = self._calculate_atr(bars)
        atr_prev = self._calculate_atr(bars[:-1]) if len(bars) > 1 else atr_current

        if abs(atr_current - atr_prev) < 0.0000001:
            hl2_current = (bars[-1].high + bars[-1].low) / 2
            hl2_prev = (bars[-2].high + bars[-2].low) / 2

            upper_current = hl2_current + atr_current * self.supertrend_multiplier
            upper_prev = hl2_prev + atr_prev * self.supertrend_multiplier
            lower_current = hl2_current - atr_current * self.supertrend_multiplier
            lower_prev = hl2_prev - atr_prev * self.supertrend_multiplier

            if supertrend_list[-1] == 1.0:
                if bars[-1].close < lower_current:
                    current_st = -1.0
                else:
                    current_st = 1.0
            else:
                if bars[-1].close > upper_current:
                    current_st = 1.0
                else:
                    current_st = -1.0

            if supertrend_list[-2] == 1.0:
                if bars[-2].close < lower_prev:
                    prev_st = -1.0
                else:
                    prev_st = 1.0
            else:
                if bars[-2].close > upper_prev:
                    prev_st = 1.0
                else:
                    prev_st = -1.0

            return current_st, prev_st

        return supertrend_list[-1], supertrend_list[-2]

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

    def _get_prev_rsi_values(self, bars: List[Bar]) -> List[float]:
        prev_rsi_values = []
        for offset in range(1, min(4, len(bars))):
            window_bars = bars[:-offset]
            if len(window_bars) >= self.rsi_period + 1:
                rsi = self._calculate_rsi(window_bars)
                if rsi is not None:
                    prev_rsi_values.append(rsi)
        return prev_rsi_values

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
            smoothed_plus_dm = smoothed_plus_dm - smoothed_plus_dm / self.adx_period + plus_dm_list[i]
            smoothed_minus_dm = smoothed_minus_dm - smoothed_minus_dm / self.adx_period + minus_dm_list[i]

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

    def _calculate_atr(self, bars: List[Bar]) -> float:
        if len(bars) < self.atr_period + 1:
            return 0.0001
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
        return tr_sum / 14


class KeltnerChannelBreakoutStrategy(ISignalStrategy):
    """Keltner Channel Breakout strategy using EMA-based channels with ATR bands.

    Entry signals are generated when price closes outside the Keltner Channel
    (above upper band for long, below lower band for short) with confirmation
    from ADX trend strength, EMA slope direction, ATR volatility threshold,
    and volume confirmation.

    Stop loss is 1.5x ATR with a hard cap of 40 pips. Take profit levels
    are set at 2.0x ATR (TP1, 33%), 3.0x ATR (TP2, 33%), with the remaining
    34% trailing via channel re-entry.

    Args:
        ema_period: Period for EMA middle line (default 20).
        atr_period: Period for ATR calculation (default 14).
        atr_multiplier: ATR multiplier for channel bands (default 1.5).
        atr_min_pips: Minimum ATR in pips for volatility filter (default 8).
        adx_period: Period for ADX calculation (default 14).
        adx_threshold: Minimum ADX value to confirm trend (default 25.0).
        volume_ma_period: Period for volume moving average (default 20).
        sl_atr_multiplier: ATR multiplier for stop loss (default 1.5).
        sl_max_pips: Hard cap on stop loss in pips (default 40.0).
        tp1_atr_multiplier: ATR multiplier for TP1 (default 2.0).
        tp2_atr_multiplier: ATR multiplier for TP2 (default 3.0).
    """

    def __init__(
        self,
        ema_period: int = 20,
        atr_period: int = 14,
        atr_multiplier: float = 1.5,
        atr_min_pips: float = 8.0,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        volume_ma_period: int = 20,
        sl_atr_multiplier: float = 1.5,
        sl_max_pips: float = 40.0,
        tp1_atr_multiplier: float = 2.0,
        tp2_atr_multiplier: float = 3.0,
    ):
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.atr_min_pips = atr_min_pips
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.volume_ma_period = volume_ma_period
        self.sl_atr_multiplier = sl_atr_multiplier
        self.sl_max_pips = sl_max_pips
        self.tp1_atr_multiplier = tp1_atr_multiplier
        self.tp2_atr_multiplier = tp2_atr_multiplier

    @property
    def name(self) -> str:
        return "Keltner Channel Breakout"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        min_bars = max(
            self.ema_period,
            self.atr_period,
            self.adx_period * 2 + 1,
            self.volume_ma_period,
        ) + 2
        if len(state.bars) < min_bars:
            return None

        close = state.latest_bar.close
        prev_close = state.bars[-2].close

        middle = self._calculate_ema(state.bars, self.ema_period)
        prev_middle = self._calculate_ema(state.bars[:-1], self.ema_period)
        if middle == 0 or prev_middle == 0:
            return None

        atr = self._calculate_atr(state.bars, self.atr_period)
        if atr <= 0:
            return None

        pip_value = self._get_pip_value(close)
        atr_pips = atr / pip_value
        if atr_pips < self.atr_min_pips:
            return None

        upper = middle + self.atr_multiplier * atr
        lower = middle - self.atr_multiplier * atr
        prev_atr = self._calculate_atr(state.bars[:-1], self.atr_period)
        prev_upper = prev_middle + self.atr_multiplier * prev_atr
        prev_lower = prev_middle - self.atr_multiplier * prev_atr

        adx = self._calculate_adx(state.bars)
        if adx is None or adx < self.adx_threshold:
            return None

        volume = state.latest_bar.volume
        if volume <= 0:
            return None
        vol_ma = self._calculate_volume_ma(state.bars)
        if vol_ma <= 0 or volume < vol_ma:
            return None

        ema_rising = middle > prev_middle
        ema_falling = middle < prev_middle

        long_breakout = prev_close <= prev_upper and close > upper and ema_rising
        short_breakout = prev_close >= prev_lower and close < lower and ema_falling

        if not long_breakout and not short_breakout:
            return None

        direction = TradeDirection.LONG if long_breakout else TradeDirection.SHORT

        sl_distance = self.sl_atr_multiplier * atr
        sl_pips = sl_distance / pip_value
        if sl_pips > self.sl_max_pips:
            sl_distance = self.sl_max_pips * pip_value

        entry = close
        if direction == TradeDirection.LONG:
            sl = entry - sl_distance
            tp1 = entry + self.tp1_atr_multiplier * atr
            tp2 = entry + self.tp2_atr_multiplier * atr
        else:
            sl = entry + sl_distance
            tp1 = entry - self.tp1_atr_multiplier * atr
            tp2 = entry - self.tp2_atr_multiplier * atr

        risk = abs(entry - sl)
        if direction == TradeDirection.LONG:
            tp3 = entry + risk * 3.0
        else:
            tp3 = entry - risk * 3.0

        confidence = 0.6
        if adx >= 40:
            confidence = 0.8
        elif adx >= 30:
            confidence = 0.7

        rationale = (
            f"Long KC breakout: close={close:.5f} > upper={upper:.5f}, "
            f"EMA={middle:.5f} rising, ADX={adx:.1f}, ATR(pips)={atr_pips:.1f}"
            if long_breakout
            else f"Short KC breakout: close={close:.5f} < lower={lower:.5f}, "
            f"EMA={middle:.5f} falling, ADX={adx:.1f}, ATR(pips)={atr_pips:.1f}"
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
        ema = sum(b.close for b in bars[:period]) / period
        for bar in bars[period:]:
            ema = (bar.close - ema) * multiplier + ema
        return ema

    def _calculate_atr(self, bars: List[Bar], period: int) -> float:
        if len(bars) < period + 1:
            return 0.0
        tr_sum = 0.0
        for i in range(len(bars) - period, len(bars)):
            if i > 0:
                tr = max(
                    bars[i].high - bars[i].low,
                    max(
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / period

    def _calculate_adx(self, bars: List[Bar]) -> Optional[float]:
        if len(bars) < self.adx_period * 2 + 1:
            return None

        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]

        plus_dm_list = []
        minus_dm_list = []
        tr_list = []

        for i in range(1, len(bars)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_list.append(tr)

            high_diff = highs[i] - highs[i - 1]
            low_diff = lows[i - 1] - lows[i]

            if high_diff > low_diff and high_diff > 0:
                plus_dm_list.append(high_diff)
            else:
                plus_dm_list.append(0)
            if low_diff > high_diff and low_diff > 0:
                minus_dm_list.append(low_diff)
            else:
                minus_dm_list.append(0)

        if len(tr_list) < self.adx_period:
            return None

        tr_sum = sum(tr_list[: self.adx_period])
        plus_dm_sum = sum(plus_dm_list[: self.adx_period])
        minus_dm_sum = sum(minus_dm_list[: self.adx_period])

        if tr_sum == 0:
            return None

        plus_di = (plus_dm_sum / tr_sum) * 100
        minus_di = (minus_dm_sum / tr_sum) * 100

        if plus_di + minus_di == 0:
            return 0.0

        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100

        adx = dx
        for i in range(self.adx_period, len(tr_list)):
            tr_sum = tr_sum - tr_sum / self.adx_period + tr_list[i]
            plus_dm_sum = plus_dm_sum - plus_dm_sum / self.adx_period + plus_dm_list[i]
            minus_dm_sum = (
                minus_dm_sum - minus_dm_sum / self.adx_period + minus_dm_list[i]
            )

            if tr_sum == 0:
                continue

            plus_di = (plus_dm_sum / tr_sum) * 100
            minus_di = (minus_dm_sum / tr_sum) * 100

            if plus_di + minus_di == 0:
                dx = 0
            else:
                dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100

            adx = (adx * (self.adx_period - 1) + dx) / self.adx_period

        return adx

    def _calculate_volume_ma(self, bars: List[Bar]) -> float:
        if len(bars) < self.volume_ma_period:
            return 0.0
        recent = bars[-self.volume_ma_period:]
        return sum(b.volume for b in recent) / len(recent)

    @staticmethod
    def _get_pip_value(price: float) -> float:
        if price >= 50:
            return 0.01
        elif price >= 1:
            return 0.0001
        else:
            return 0.00000001
