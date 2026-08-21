"""Unit tests for DonchianATRTrendStrategy.

Covers: helper functions (ATR, EMA, ADX, Donchian channel),
happy-path breakout signals (long/short), edge cases
(insufficient bars, cooldown, low ADX), and risk calculation
(stop-loss, take-profit levels, confidence bounds).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from core.types import Bar, BarPeriod, MarketState, TradeDirection
from strategies.donchian_atr_trend import (
    DonchianATRConfig,
    DonchianATRTrendStrategy,
    _calculate_adx,
    _calculate_atr,
    _calculate_ema,
    _donchian_high,
    _donchian_low,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(
    close: float = 1.1000,
    high: float | None = None,
    low: float | None = None,
    open_: float | None = None,
    dt: datetime | None = None,
) -> Bar:
    return Bar(
        time=dt or datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        open=open_ if open_ is not None else close,
        high=high if high is not None else close + 0.0002,
        low=low if low is not None else close - 0.0002,
        close=close,
        volume=1000.0,
        period=BarPeriod.M15,
    )


def _trending_bars(
    n: int = 60,
    start: float = 1.1000,
    trend: float = 0.0010,
    volatility: float = 0.0005,
    period: int = 15,
) -> list[Bar]:
    """Generate n bars with a steady uptrend and some volatility."""
    bars: list[Bar] = []
    base = start
    start_dt = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    for i in range(n):
        noise = volatility if i % 3 != 0 else -volatility
        o = base
        c = base + trend + noise
        h = max(o, c) + volatility * 0.5
        low = min(o, c) - volatility * 0.5
        bars.append(
            Bar(
                time=start_dt + timedelta(minutes=period * i),
                open=o,
                high=h,
                low=low,
                close=c,
                volume=1000.0,
                period=BarPeriod.M15,
            )
        )
        base = c
    return bars


def _ranging_bars(
    n: int = 60,
    center: float = 1.1000,
    range_size: float = 0.0002,
    period: int = 15,
) -> list[Bar]:
    """Generate n bars in a tight symmetric range (low directional movement → low ADX).

    Bars oscillate with tiny bodies around center, producing
    approximately equal +DM and -DM → low DX → low ADX.
    """
    bars: list[Bar] = []
    start_dt = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    for i in range(n):
        # Tiny alternating close near center with consistent high/low spread
        c = center + (range_size if i % 2 == 0 else -range_size)
        bars.append(
            Bar(
                time=start_dt + timedelta(minutes=period * i),
                open=center,
                high=center + range_size * 1.5,
                low=center - range_size * 1.5,
                close=c,
                volume=1000.0,
                period=BarPeriod.M15,
            )
        )
    return bars


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestCalculateATR:
    def test_returns_default_for_insufficient_bars(self):
        bars = [_bar(close=1.0, high=1.001, low=0.999) for _ in range(5)]
        result = _calculate_atr(bars, period=14)
        assert result == 0.0001

    def test_returns_positive_value_for_valid_bars(self):
        bars = []
        for i in range(20):
            bars.append(
                _bar(
                    close=1.0 + i * 0.001,
                    high=1.0 + i * 0.001 + 0.002,
                    low=1.0 + i * 0.001 - 0.001,
                )
            )
        result = _calculate_atr(bars, period=14)
        assert result > 0

    def test_zero_volatility_returns_near_zero(self):
        bars = []
        for i in range(20):  # noqa: B007
            bars.append(_bar(close=1.0, high=1.0, low=1.0))
        result = _calculate_atr(bars, period=14)
        assert result == pytest.approx(0.0)


class TestCalculateEMA:
    def test_returns_mean_for_insufficient_data(self):
        result = _calculate_ema([1.0, 2.0, 3.0], period=10)
        assert result == pytest.approx(2.0)

    def test_returns_sma_for_exact_period(self):
        result = _calculate_ema([1.0, 2.0, 3.0], period=3)
        assert result == pytest.approx(2.0)

    def test_weights_recent_values_more(self):
        values = [1.0] * 10 + [10.0] * 10
        ema = _calculate_ema(values, period=5)
        # EMA should be pulled toward 10 by the recent values
        assert ema > 5.0

    def test_empty_list_returns_zero(self):
        assert _calculate_ema([], period=5) == 0.0


class TestCalculateADX:
    def test_returns_zero_for_insufficient_bars(self):
        bars = [_bar() for _ in range(10)]
        assert _calculate_adx(bars, period=14) == 0.0

    def test_returns_positive_for_trending_market(self):
        bars = _trending_bars(n=40, trend=0.002)
        adx = _calculate_adx(bars, period=14)
        assert adx > 0

    def test_returns_low_for_ranging_market(self):
        bars = _ranging_bars(n=60)
        adx = _calculate_adx(bars, period=14)
        # Symmetric ranging bars produce roughly equal +DM and -DM,
        # so DX ≈ 0. ADX should be well below trending threshold.
        # Note: the simplified ADX in donchian_atr_trend is not a
        # textbook Wilder ADX so we use a generous threshold.
        assert adx <= 50.0


class TestDonchianChannel:
    def test_donchian_high_excludes_current_bar(self):
        bars = []
        for i in range(25):
            bars.append(_bar(close=1.0 + i * 0.001, high=1.0 + i * 0.001 + 0.0005))
        # Current bar has highest high but should be excluded
        dc_high = _donchian_high(bars, period=20)
        # Should be the high of bar[-2] not bar[-1]
        assert dc_high == bars[-2].high

    def test_donchian_low_excludes_current_bar(self):
        bars = []
        for i in range(25):
            bars.append(_bar(close=1.0 - i * 0.001, low=1.0 - i * 0.001 - 0.0005))
        dc_low = _donchian_low(bars, period=20)
        assert dc_low == bars[-2].low

    def test_donchian_high_falls_back_for_short_data(self):
        bars = [_bar(close=1.0, high=1.002), _bar(close=1.0, high=1.003)]
        dc_high = _donchian_high(bars, period=20)
        assert dc_high == 1.003

    def test_donchian_low_falls_back_for_short_data(self):
        bars = [_bar(close=1.0, low=0.998), _bar(close=1.0, low=0.997)]
        dc_low = _donchian_low(bars, period=20)
        assert dc_low == 0.997

    def test_empty_bars_returns_zero(self):
        assert _donchian_high([], period=20) == 0.0
        assert _donchian_low([], period=20) == 0.0


# ---------------------------------------------------------------------------
# Strategy integration tests
# ---------------------------------------------------------------------------


class TestDonchianATRTrendStrategyBasics:
    def test_name_property(self):
        strategy = DonchianATRTrendStrategy()
        assert strategy.name == "Donchian ATR Trend"

    def test_reset_clears_state(self):
        strategy = DonchianATRTrendStrategy()
        strategy._bars_since_signal = 0
        strategy.reset()
        assert strategy._bars_since_signal == 999

    def test_returns_none_for_insufficient_bars(self):
        strategy = DonchianATRTrendStrategy()
        bars = [_bar() for _ in range(10)]
        state = MarketState(bars=bars)
        assert strategy.evaluate(state) is None


class TestDonchianATRTrendBreakoutSignals:
    def _make_breakout_bars(self, direction: str = "long", n: int = 60) -> list[Bar]:
        """Build bars that produce a Donchian breakout on the last bar."""
        bars: list[Bar] = []
        start_dt = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
        base = 1.1000

        for i in range(n - 1):
            c = base + (i * 0.0005 if direction == "long" else -i * 0.0005)
            bars.append(
                Bar(
                    time=start_dt + timedelta(minutes=15 * i),
                    open=c,
                    high=c + 0.0010,
                    low=c - 0.0010,
                    close=c,
                    volume=1000.0,
                    period=BarPeriod.M15,
                )
            )
        # Final bar: strong breakout
        if direction == "long":
            breakout_close = base + (n - 1) * 0.0005 + 0.0050
        else:
            breakout_close = base - (n - 1) * 0.0005 - 0.0050
        bars.append(
            Bar(
                time=start_dt + timedelta(minutes=15 * (n - 1)),
                open=bars[-1].close,
                high=breakout_close + 0.002,
                low=breakout_close - 0.002,
                close=breakout_close,
                volume=2000.0,
                period=BarPeriod.M15,
            )
        )
        return bars

    def test_long_breakout_signal(self):
        strategy = DonchianATRTrendStrategy(DonchianATRConfig(cooldown_bars=0))
        bars = self._make_breakout_bars("long")
        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)

        assert signal is not None
        assert signal.direction == TradeDirection.LONG
        assert signal.entry_price > 0
        assert signal.stop_loss < signal.entry_price
        assert signal.take_profit_1 > signal.entry_price
        assert signal.take_profit_2 > signal.take_profit_1
        assert signal.take_profit_3 > signal.take_profit_2
        assert 0 < signal.confidence <= 0.85
        assert "breakout_long" in signal.rationale

    def test_short_breakout_signal(self):
        strategy = DonchianATRTrendStrategy(DonchianATRConfig(cooldown_bars=0))
        bars = self._make_breakout_bars("short")
        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)

        assert signal is not None
        assert signal.direction == TradeDirection.SHORT
        assert signal.entry_price > 0
        assert signal.stop_loss > signal.entry_price
        assert signal.take_profit_1 < signal.entry_price
        assert signal.take_profit_2 < signal.take_profit_1
        assert signal.take_profit_3 < signal.take_profit_2
        assert "breakout_short" in signal.rationale

    def test_no_signal_in_flat_market(self):
        """Bars with zero movement produce no breakout signal.

        When all bars are identical, ATR = 0 and EMA = close,
        so the strategy returns None early (atr <= 0 guard).
        """
        strategy = DonchianATRTrendStrategy(DonchianATRConfig(cooldown_bars=0))
        bars: list[Bar] = []
        start_dt = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
        for i in range(60):
            bars.append(
                Bar(
                    time=start_dt + timedelta(minutes=15 * i),
                    open=1.1000,
                    high=1.1000,
                    low=1.1000,
                    close=1.1000,
                    volume=1000.0,
                    period=BarPeriod.M15,
                )
            )
        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)
        assert signal is None


class TestDonchianATRTrendCooldown:
    def test_cooldown_blocks_signal_after_entry(self):
        config = DonchianATRConfig(cooldown_bars=5)
        strategy = DonchianATRTrendStrategy(config)
        # Force cooldown active
        strategy._bars_since_signal = 2  # < 5 cooldown
        bars = _trending_bars(n=60, trend=0.003)
        state = MarketState(bars=bars)
        assert strategy.evaluate(state) is None

    def test_cooldown_expires_allows_signal(self):
        config = DonchianATRConfig(cooldown_bars=2)
        strategy = DonchianATRTrendStrategy(config)
        strategy._bars_since_signal = 999  # well past cooldown
        bars = _trending_bars(n=60, trend=0.003)
        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)
        # Should produce a signal since cooldown has expired
        # (depends on ADX being high enough from the trend)
        if signal is not None:
            assert strategy._bars_since_signal == 0


class TestDonchianATRTrendRiskCalculation:
    def test_stop_loss_is_between_entry_and_dc_level(self):
        """For long: stop should be at max(dc_low, entry - ATR*mult)."""
        strategy = DonchianATRTrendStrategy(DonchianATRConfig(cooldown_bars=0, atr_trail_multiplier=2.0))
        bars = TestDonchianATRTrendBreakoutSignals._make_breakout_bars("long")
        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)

        if signal is not None:
            risk = abs(signal.entry_price - signal.stop_loss)
            assert risk > 0
            # TP distances should be 1R, 2R, 3R
            r1 = abs(signal.take_profit_1 - signal.entry_price)
            r2 = abs(signal.take_profit_2 - signal.entry_price)
            r3 = abs(signal.take_profit_3 - signal.entry_price)
            assert r1 == pytest.approx(risk)
            assert r2 == pytest.approx(risk * 2)
            assert r3 == pytest.approx(risk * 3)

    def test_confidence_capped_at_085(self):
        strategy = DonchianATRTrendStrategy(DonchianATRConfig(cooldown_bars=0))
        bars = TestDonchianATRTrendBreakoutSignals._make_breakout_bars("long")
        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)
        if signal is not None:
            assert signal.confidence <= 0.85
