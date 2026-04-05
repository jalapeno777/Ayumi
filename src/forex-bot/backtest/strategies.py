from typing import List, Optional
from .engine import Bar, MarketState, StrategySignal, TradeDirection


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
        tr_sum = 0
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
        tr_sum = 0
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

        gains = []
        losses = []
        for i in range(len(bars) - self.period, len(bars)):
            change = bars[i].close - bars[i - 1].close
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
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
        tr_sum = 0
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
        tr_sum = 0
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
        tr_sum = 0
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
        """Initialize CommodityTrendStrategy.

        Args:
            fast_ema_period: Period for fast EMA (default 20).
            slow_ema_period: Period for slow EMA (default 50).
            adx_period: Period for ADX calculation (default 14).
            adx_threshold: Minimum ADX value to confirm trend (default 25.0).
            atr_multiplier: ATR multiplier for stop loss (default 1.75).
            risk_reward_ratio: Risk/reward ratio for take profit (default 2.0).
        """
        self.fast_ema_period = fast_ema_period
        self.slow_ema_period = slow_ema_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.atr_multiplier = atr_multiplier
        self.risk_reward_ratio = risk_reward_ratio

    @property
    def name(self) -> str:
        """Return strategy display name."""
        return "Commodity Trend Following"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        """Evaluate market state and generate trading signal if conditions are met.

        Args:
            state: Current market state including bars and indicators.

        Returns:
            StrategySignal with direction, entry/exit prices, and confidence,
            or None if entry criteria are not satisfied.
        """
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
        """Calculate exponential moving average for given period."""
        if len(bars) < period:
            return 0.0
        multiplier = 2.0 / (period + 1)
        sma = sum(b.close for b in bars[:period]) / period
        ema = sma
        for bar in bars[period:]:
            ema = (bar.close - ema) * multiplier + ema
        return ema

    def _calculate_adx(self, bars: List[Bar]) -> Optional[float]:
        """Calculate Average Directional Index (ADX) using Wilder smoothing.

        ADX measures trend strength by smoothing DX (Directional Index) over
        the lookback period using Wilder's method:
        ADX_today = (ADX_yesterday * (period - 1) + DX_today) / period

        Requires at least 2 * adx_period bars for meaningful values.
        Returns smoothed ADX value, or None if insufficient data.
        """
        period = self.adx_period
        min_bars = 2 * period + 1
        if len(bars) < min_bars:
            return None

        tr_list: list[float] = []
        plus_dm_list: list[float] = []
        minus_dm_list: list[float] = []

        for i in range(1, len(bars)):
            high = bars[i].high
            low = bars[i].low
            prev_high = bars[i - 1].high
            prev_low = bars[i - 1].low
            prev_close = bars[i - 1].close

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            tr_list.append(tr)

            plus_dm = max(high - prev_high, 0) - max(prev_low - low, 0)
            minus_dm = max(prev_low - low, 0) - max(high - prev_high, 0)

            if plus_dm < 0:
                plus_dm = 0.0
            if minus_dm < 0:
                minus_dm = 0.0

            if plus_dm > minus_dm:
                minus_dm = 0.0
            elif minus_dm > plus_dm:
                plus_dm = 0.0
            else:
                plus_dm = 0.0
                minus_dm = 0.0

            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        smoothed_tr = sum(tr_list[:period])
        smoothed_plus_dm = sum(plus_dm_list[:period])
        smoothed_minus_dm = sum(minus_dm_list[:period])

        dx_list: list[float] = []
        for i in range(period, len(tr_list)):
            if i == period:
                if smoothed_tr == 0:
                    plus_di = 0.0
                    minus_di = 0.0
                else:
                    plus_di = (smoothed_plus_dm / smoothed_tr) * 100
                    minus_di = (smoothed_minus_dm / smoothed_tr) * 100
            else:
                smoothed_tr = smoothed_tr - smoothed_tr / period + tr_list[i]
                smoothed_plus_dm = smoothed_plus_dm - smoothed_plus_dm / period + plus_dm_list[i]
                smoothed_minus_dm = smoothed_minus_dm - smoothed_minus_dm / period + minus_dm_list[i]
                if smoothed_tr == 0:
                    plus_di = 0.0
                    minus_di = 0.0
                else:
                    plus_di = (smoothed_plus_dm / smoothed_tr) * 100
                    minus_di = (smoothed_minus_dm / smoothed_tr) * 100

            if plus_di + minus_di == 0:
                dx_list.append(0.0)
            else:
                dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100
                dx_list.append(dx)

        if len(dx_list) < period:
            return None

        adx = sum(dx_list[:period]) / period
        for i in range(period, len(dx_list)):
            adx = adx * (period - 1) / period + dx_list[i] / period

        return adx

    def _calculate_atr(self, bars: List[Bar]) -> float:
        """Calculate Average True Range over 14 periods."""
        if len(bars) < 15:
            return bars[-1].close * 0.0005
        tr_sum = 0
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


class CommodityMeanReversionStrategy(ISignalStrategy):
    """Mean reversion strategy for commodities using Bollinger Bands and RSI.

    Entry rules:
        - Long: Price below lower Bollinger Band + RSI < 30 (oversold) + bullish reversal candle
        - Short: Price above upper Bollinger Band + RSI > 70 (overbought) + bearish reversal candle

    Exit rules:
        - Stop loss: Beyond outer Bollinger Band by 0.5x ATR
        - Take profit: tp1 = Middle Band (mean reversion target), tp2/tp3 = 2x/3x risk for scaling
        - Confidence based on RSI deviation from thresholds

    Note on TP ordering: tp1 targets the middle band (SMA) as the primary mean reversion objective.
    The middle band represents fair value where price is expected to revert. tp2 and tp3 at 2x/3x
    risk are secondary targets for scaling out if the move extends beyond initial entry. This
    ordering differs from trend-following strategies but reflects the mean reversion thesis where
    the primary target is always the moving average.

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
        """Initialize CommodityMeanReversionStrategy.

        Args:
            bb_period: Period for Bollinger Bands SMA (default 20).
            bb_std_dev: Standard deviations for band width (default 2.0).
            rsi_period: Period for RSI calculation (default 14).
            rsi_oversold: RSI threshold for oversold long entries (default 30.0).
            rsi_overbought: RSI threshold for overbought short entries (default 70.0).
            atr_multiplier: ATR multiplier for stop loss (default 2.0).
        """
        self.bb_period = bb_period
        self.bb_std_dev = bb_std_dev
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_multiplier = atr_multiplier

    @property
    def name(self) -> str:
        """Return strategy display name."""
        return "Commodity Mean Reversion"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        """Evaluate market state and generate trading signal if conditions are met.

        Args:
            state: Current market state including bars and indicators.

        Returns:
            StrategySignal with direction, entry/exit prices, and confidence,
            or None if entry criteria are not satisfied.
        """
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
            risk = abs(entry - sl)
            tp1 = middle_band
            tp2 = entry + risk * 2.0
            tp3 = entry + risk * 3.0
            confidence = min(
                0.90, 0.55 + (self.rsi_oversold - rsi) / self.rsi_oversold * 0.35
            )
            rationale = (
                f"BB oversold + RSI oversold + bullish reversal: close={latest.close:.5f} < lower={lower_band:.5f}, RSI={rsi:.1f}"
            )
        elif latest.close > upper_band and rsi > self.rsi_overbought:
            if not self._is_bearish_reversal(latest):
                return None
            direction = TradeDirection.SHORT
            entry = latest.close
            sl = upper_band + atr * 0.5
            risk = abs(entry - sl)
            tp1 = middle_band
            tp2 = entry - risk * 2.0
            tp3 = entry - risk * 3.0
            confidence = min(
                0.90, 0.55 + (rsi - self.rsi_overbought) / (100 - self.rsi_overbought) * 0.35
            )
            rationale = (
                f"BB overbought + RSI overbought: close={latest.close:.5f} > upper={upper_band:.5f}, RSI={rsi:.1f}"
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
        """Calculate simple moving average for Bollinger Bands middle line."""
        if len(bars) < self.bb_period:
            return 0.0
        return sum(b.close for b in bars[-self.bb_period:]) / self.bb_period

    def _calculate_std(self, bars: List[Bar], sma: float) -> float:
        """Calculate standard deviation for Bollinger Bands band width."""
        if len(bars) < self.bb_period:
            return 0.0
        variance = sum((b.close - sma) ** 2 for b in bars[-self.bb_period:]) / self.bb_period
        return variance**0.5

    def _calculate_rsi(self, bars: List[Bar]) -> Optional[float]:
        """Calculate Relative Strength Index for momentum confirmation."""
        if len(bars) < self.rsi_period + 1:
            return None

        gains = []
        losses = []
        for i in range(len(bars) - self.rsi_period, len(bars)):
            change = bars[i].close - bars[i - 1].close
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_atr(self, bars: List[Bar]) -> float:
        """Calculate Average True Range over 14 periods."""
        if len(bars) < 15:
            return bars[-1].close * 0.0005
        tr_sum = 0
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

    def _is_bullish_reversal(self, bar: Bar) -> bool:
        """Detect bullish reversal candle for mean reversion entry confirmation.

        A bullish reversal candle has its close in the upper half of the
        candle's range, indicating buying pressure and potential reversal.
        """
        candle_range = bar.high - bar.low
        if candle_range == 0:
            return False
        midpoint = bar.low + candle_range * 0.5
        return bar.close > midpoint

    def _is_bearish_reversal(self, bar: Bar) -> bool:
        """Detect bearish reversal candle for mean reversion entry confirmation.

        A bearish reversal candle has its close in the lower half of the
        candle's range, indicating selling pressure and potential reversal.
        """
        candle_range = bar.high - bar.low
        if candle_range == 0:
            return False
        midpoint = bar.low + candle_range * 0.5
        return bar.close < midpoint
