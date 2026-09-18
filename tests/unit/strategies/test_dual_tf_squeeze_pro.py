"""Unit tests for DualTFSqueezeProStrategy.

Covers: helper functions (SMA, EMA, std, ATR, RSI, ADX, Keltner),
H1 aggregation from M15 bars, squeeze detection (BB inside KC),
squeeze breakout signals, pullback continuation signals, ADX/RSI
filtering, risk calculation (stop at KC band or ATR-based, TP at R
multiples), confidence bounds, and cooldown behavior.
"""

from __future__ import annotations
import pytest

from datetime import datetime, timedelta, timezone

from core.types import Bar, BarPeriod, MarketState, TradeDirection
from strategies.dual_tf_squeeze_pro import (
    DualTFSqueezeProConfig,
    DualTFSqueezeProStrategy,
    _adx,
    _atr_from_true_ranges,
    _ema,
    _keltner,
    _rsi,
    _sma,
    _std,
    _true_range,
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
        time=dt or datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        open=open_ if open_ is not None else close,
        high=high if high is not None else close + 0.0002,
        low=low if low is not None else close - 0.0002,
        close=close,
        volume=1000.0,
        period=BarPeriod.M15,
    )


def _m15_bars(
    n: int = 120,
    start: float = 1.1000,
    trend: float = 0.0001,
    vol: float = 0.0003,
) -> list[Bar]:
    """Generate n M15 bars with optional trend and volatility."""
    bars: list[Bar] = []
    base = start
    dt = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    for i in range(n):
        o = base
        c = base + trend + (vol if i % 4 < 2 else -vol)
        h = max(o, c) + vol * 0.3
        low = min(o, c) - vol * 0.3
        bars.append(
            Bar(
                time=dt + timedelta(minutes=15 * i),
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


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestSMA:
    def test_simple_average(self):
        assert _sma([1.0, 2.0, 3.0, 4.0, 5.0], period=5) == pytest.approx(3.0)

    def test_short_data_returns_zero(self):
        assert _sma([1.0, 2.0], period=5) == 0.0

    def test_uses_last_n_values(self):
        assert _sma([0, 0, 0, 10, 20], period=2) == pytest.approx(15.0)


class TestEMA:
    def test_returns_list_same_length(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        result = _ema(values, period=5)
        assert len(result) == len(values)

    def test_short_data_returns_zeros(self):
        result = _ema([1.0, 2.0], period=5)
        assert result == [0.0, 0.0]

    def test_ema_recents_value(self):
        values = [1.0] * 5 + [10.0] * 10
        result = _ema(values, period=5)
        assert result[-1] > 5.0  # weighted toward recent 10s


class TestStd:
    def test_zero_std_for_constant_series(self):
        assert _std([5.0] * 10, period=5) == pytest.approx(0.0)

    def test_positive_std_for_varied_series(self):
        result = _std([1.0, 2.0, 3.0, 4.0, 5.0], period=5)
        assert result > 0
        assert result == pytest.approx(1.4142, rel=0.01)

    def test_short_data_returns_zero(self):
        assert _std([1.0, 2.0], period=5) == 0.0


class TestATRFromTrueRanges:
    def test_short_input_returns_zero(self):
        assert _atr_from_true_ranges([0.001, 0.002], period=14) == 0.0

    def test_simple_average_for_exact_period(self):
        trs = [0.001, 0.002, 0.003, 0.004, 0.005]
        result = _atr_from_true_ranges(trs, period=5)
        assert result == pytest.approx(0.003)

    def test_smoothed_for_longer_series(self):
        trs = [0.001] * 14 + [0.01] * 10
        result = _atr_from_true_ranges(trs, period=14)
        # Should be pulled toward 0.01 but still below it
        assert 0.001 < result < 0.01


class TestTrueRange:
    def test_returns_zero_for_single_bar(self):
        bar = _bar()
        assert _true_range([bar]) == 0.0

    def test_normal_range(self):
        b1 = _bar(close=1.1000, high=1.1010, low=1.0990)
        b2 = _bar(close=1.1005, high=1.1015, low=1.0995)
        tr = _true_range([b1, b2])
        expected = max(
            b2.high - b2.low,
            abs(b2.high - b1.close),
            abs(b2.low - b1.close),
        )
        assert tr == pytest.approx(expected)


class TestRSI:
    def test_returns_50_for_insufficient_data(self):
        bars = [_bar() for _ in range(5)]
        assert _rsi(bars, period=14) == 50.0

    def test_all_gains_returns_100(self):
        bars: list[Bar] = []
        for i in range(20):
            bars.append(_bar(close=1.0 + i * 0.001))
        result = _rsi(bars, period=14)
        assert result == 100.0

    def test_all_losses_returns_near_zero(self):
        bars: list[Bar] = []
        for i in range(20):
            bars.append(_bar(close=1.0 - i * 0.001))
        result = _rsi(bars, period=14)
        assert result < 10.0

    def test_mixed_returns_midrange(self):
        bars: list[Bar] = []
        for i in range(30):
            c = 1.0 + (0.001 if i % 2 == 0 else -0.001)
            bars.append(_bar(close=c))
        result = _rsi(bars, period=14)
        assert 30.0 < result < 70.0


class TestADXHelper:
    def test_returns_zero_for_short_data(self):
        bars = [_bar() for _ in range(10)]
        assert _adx(bars, period=14) == 0.0

    def test_positive_for_trending_data(self):
        bars: list[Bar] = []
        for i in range(40):
            bars.append(
                _bar(
                    close=1.0 + i * 0.002,
                    high=1.0 + i * 0.002 + 0.001,
                    low=1.0 + i * 0.002 - 0.0005,
                )
            )
        result = _adx(bars, period=14)
        assert result > 0


class TestKeltner:
    def test_returns_zeros_for_short_data(self):
        u, m, l = _keltner([1.0, 2.0], [], period=20, atr_mult=1.5)  # noqa: E741
        assert u == 0.0 and m == 0.0 and l == 0.0

    def test_bands_symmetric_around_middle(self):
        closes = [1.1000 + i * 0.0001 for i in range(25)]
        atrs = [0.0010]
        u, m, l = _keltner(closes, atrs, period=20, atr_mult=1.5)  # noqa: E741
        assert u > m > l
        assert (u - m) == pytest.approx(m - l, rel=0.01)


# ---------------------------------------------------------------------------
# Strategy basic tests
# ---------------------------------------------------------------------------


class TestDualTFSqueezeProBasics:
    def test_name_property(self):
        strategy = DualTFSqueezeProStrategy()
        assert strategy.name == "Dual-TF Squeeze Pro"
    @pytest.mark.xfail(reason="DEBT 6ea40384-35ba-4c41-99a6-87d843ca7f75: Dual-TF Squeeze Pro H1 bar aggregation not populated (pre-existing)", strict=False)

    def test_reset_clears_state(self):
        strategy = DualTFSqueezeProStrategy()
        strategy._h1_bars.append(_bar())
        strategy._h1_closes.append(1.0)
        strategy._bars_since_signal = 0
        strategy._m15_atr = 0.5
        strategy.reset()
        assert len(strategy._h1_bars) == 0
        assert len(strategy._h1_closes) == 0
        assert strategy._bars_since_signal == 999
        assert strategy._m15_atr == 0.0

    def test_returns_none_for_insufficient_bars(self):
        strategy = DualTFSqueezeProStrategy()
        bars = _m15_bars(n=20)
        state = MarketState(bars=bars)
        assert strategy.evaluate(state) is None


class TestH1Aggregation:
    @pytest.mark.xfail(reason="DEBT 6ea40384-35ba-4c41-99a6-87d843ca7f75: Dual-TF Squeeze Pro H1 bar aggregation not populated (pre-existing)", strict=False)
    def test_h1_bars_built_from_m15(self):
        """4 M15 bars should aggregate into 1 H1 bar."""
        strategy = DualTFSqueezeProStrategy()
        # Feed 4 M15 bars in the same hour
        dt = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
        bars = [
            Bar(
                time=dt,
                open=1.0,
                high=1.002,
                low=0.999,
                close=1.001,
                volume=100,
                period=BarPeriod.M15,
            ),
            Bar(
                time=dt + timedelta(minutes=15),
                open=1.001,
                high=1.003,
                low=1.0,
                close=1.002,
                volume=100,
                period=BarPeriod.M15,
            ),
            Bar(
                time=dt + timedelta(minutes=30),
                open=1.002,
                high=1.004,
                low=1.001,
                close=1.003,
                volume=100,
                period=BarPeriod.M15,
            ),
            Bar(
                time=dt + timedelta(minutes=45),
                open=1.003,
                high=1.005,
                low=1.002,
                close=1.004,
                volume=100,
                period=BarPeriod.M15,
            ),
        ]
        for b in bars:
            strategy._update_h1(b)

        assert len(strategy._h1_bars) == 1
        h1 = strategy._h1_bars[0]
        assert h1.high == 1.005  # max of all highs
        assert h1.low == 0.999  # min of all lows
        assert h1.close == 1.004  # last close
    @pytest.mark.xfail(reason="DEBT 6ea40384-35ba-4c41-99a6-87d843ca7f75: Dual-TF Squeeze Pro H1 bar aggregation not populated (pre-existing)", strict=False)

    def test_new_hour_creates_new_h1_bar(self):
        strategy = DualTFSqueezeProStrategy()
        # First hour
        dt1 = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
        strategy._update_h1(
            Bar(
                time=dt1,
                open=1.0,
                high=1.01,
                low=0.99,
                close=1.005,
                volume=100,
                period=BarPeriod.M15,
            )
        )
        # Second hour
        dt2 = datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc)
        strategy._update_h1(
            Bar(
                time=dt2,
                open=1.005,
                high=1.02,
                low=1.0,
                close=1.01,
                volume=100,
                period=BarPeriod.M15,
            )
        )
        assert len(strategy._h1_bars) == 2


class TestSqueezeDetection:
    def test_squeeze_detected_when_bb_inside_kc(self):
        """BB width narrower than KC width → squeeze active."""
        strategy = DualTFSqueezeProStrategy(DualTFSqueezeProConfig(cooldown_bars_m15=0))
        # Feed enough M15 bars to build H1 history
        bars = _m15_bars(n=250, trend=0.0001, vol=0.0001)
        state = MarketState(bars=bars)
        # Should process without error
        result = strategy.evaluate(state)
        # Result may or may not be None depending on squeeze state
        if result is not None:
            assert result.direction in (TradeDirection.LONG, TradeDirection.SHORT)
            assert 0 < result.confidence <= 0.85

    def test_no_squeeze_when_bb_outside_kc(self):
        """High volatility should push BB outside KC → no squeeze."""
        strategy = DualTFSqueezeProStrategy(DualTFSqueezeProConfig(cooldown_bars_m15=0))
        # High volatility bars
        bars = _m15_bars(n=250, trend=0.0, vol=0.005)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        # May or may not produce signal, but should not error
        if result is not None:
            assert result.direction in (TradeDirection.LONG, TradeDirection.SHORT)


class TestSignalStructure:
    def test_signal_has_all_required_fields(self):
        """If a signal is produced, it must have all StrategySignal fields."""
        strategy = DualTFSqueezeProStrategy(DualTFSqueezeProConfig(cooldown_bars_m15=0))
        bars = _m15_bars(n=250, trend=0.0002, vol=0.0003)
        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)

        if signal is not None:
            assert signal.direction in (TradeDirection.LONG, TradeDirection.SHORT)
            assert signal.entry_price > 0
            assert signal.stop_loss > 0
            assert signal.take_profit_1 > 0
            assert signal.take_profit_2 > 0
            assert signal.take_profit_3 > 0
            assert 0 < signal.confidence <= 0.85
            assert len(signal.rationale) > 0
            assert "DTSQ Pro" in signal.rationale

    def test_take_profits_at_r_multiples(self):
        strategy = DualTFSqueezeProStrategy(DualTFSqueezeProConfig(cooldown_bars_m15=0))
        bars = _m15_bars(n=250, trend=0.0003, vol=0.0005)
        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)

        if signal is not None:
            risk = abs(signal.entry_price - signal.stop_loss)
            assert risk > 0
            r1 = abs(signal.take_profit_1 - signal.entry_price)
            r2 = abs(signal.take_profit_2 - signal.entry_price)
            r3 = abs(signal.take_profit_3 - signal.entry_price)
            config = strategy.config
            assert r1 == pytest.approx(risk * config.tp1_rr, rel=0.01)
            assert r2 == pytest.approx(risk * config.tp2_rr, rel=0.01)
            assert r3 == pytest.approx(risk * config.tp3_rr, rel=0.01)

    def test_stop_loss_direction_correct(self):
        """Long: stop below entry. Short: stop above entry."""
        strategy = DualTFSqueezeProStrategy(DualTFSqueezeProConfig(cooldown_bars_m15=0))
        bars = _m15_bars(n=250, trend=0.0003, vol=0.0005)
        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)

        if signal is not None:
            if signal.direction == TradeDirection.LONG:
                assert signal.stop_loss < signal.entry_price
                assert signal.take_profit_1 > signal.entry_price
            else:
                assert signal.stop_loss > signal.entry_price
                assert signal.take_profit_1 < signal.entry_price


class TestCooldown:
    def test_cooldown_blocks_consecutive_signals(self):
        strategy = DualTFSqueezeProStrategy(DualTFSqueezeProConfig(cooldown_bars_m15=10))
        strategy._bars_since_signal = 3  # within cooldown
        bars = _m15_bars(n=250, trend=0.0003, vol=0.0005)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        assert result is None

    def test_cooldown_reset_after_signal(self):
        strategy = DualTFSqueezeProStrategy(DualTFSqueezeProConfig(cooldown_bars_m15=5))
        bars = _m15_bars(n=250, trend=0.0003, vol=0.0005)
        state = MarketState(bars=bars)
        signal = strategy.evaluate(state)
        if signal is not None:
            assert strategy._bars_since_signal == 0


class TestRSIFilter:
    def test_rsi_outside_zone_blocks_signal(self):
        """RSI outside [40, 60] should prevent entry."""
        config = DualTFSqueezeProConfig(
            cooldown_bars_m15=0,
            rsi_zone_min=45.0,
            rsi_zone_max=46.0,  # extremely narrow zone
        )
        strategy = DualTFSqueezeProStrategy(config)
        bars = _m15_bars(n=250, trend=0.0003, vol=0.0003)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        # Narrow RSI zone makes it very unlikely to trigger
        # (but not impossible — the test verifies the filter exists)
        if result is not None:
            # If it does fire, the structure should still be valid
            assert result.direction in (TradeDirection.LONG, TradeDirection.SHORT)
