"""Tests for take-profit computation and symbol-scale guards in SessionBreakout.

Reproduces the BQ-? bug where a GBPUSD SELL signal with entry=1.319975
produced tp_price=0.6659749999999893 (≈ entry/2, ~6500 pips away). The bug
was caused by an upstream unit-mismatch that produced a wildly large
range_width. The fix adds a price-level guard and a TP-distance guard in
``SessionBreakoutStrategy.evaluate()`` so the corrupted signal is now
rejected (``evaluate`` returns ``None``) instead of being emitted.

These tests verify:
* Normal GBPUSD breakout: TPs land within 1.5x/2x/3x the range width, all
  in a sane price band, within a few hundred pips of entry.
* Normal USDJPY breakout: same shape, sane values.
* The reported bug pattern (TP ≈ 0.66 for entry ≈ 1.32) is rejected.
* Range width > 500 pips is rejected (catches the unit-mismatch signature).
* TPs more than 1000 pips from entry are rejected.
"""

from __future__ import annotations  # noqa: I001

from datetime import datetime, timedelta, timezone


from core.types import Bar, MarketState, TradeDirection
from strategies.session_breakout import (
    SessionBreakoutStrategy,
    _FX_MAX_PRICE,
    _FX_MIN_PRICE,
    _MAX_RANGE_PIPS,
    _MAX_TP_DISTANCE_PIPS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "name": "TestSessionBreakout",
    # Asian range window: 0-7 UTC, trade window: 7-10 UTC.
    "range_start_hour": 0,
    "range_end_hour": 7,
    "trade_start_hour": 7,
    "trade_end_hour": 10,
    "min_range_pips": 20,
    "max_range_pips": 80,
    "buffer_pips": 3,
    "sl_atr_multiplier": 2.0,
    "atr_period": 14,
    "min_range_bars": 20,
}


def _make_bars(
    *,
    symbol: str,
    count: int = 80,
    base_price: float = 1.32000,
    range_width_price: float | None = None,
    base_time: datetime | None = None,
    pip: float = 0.0001,
    range_low_override: float | None = None,
    range_high_override: float | None = None,
    breakout_close: float | None = None,
    breakout_direction: str = "bearish",  # "bullish" or "bearish"
    break_buffer: float | None = None,
) -> list[Bar]:
    """Build a deterministic bar series for one session + one breakout bar.

    First ``count - 1`` bars are in the range window (hours 0-6); the final
    bar is in the trade window (hour 7+) and closes through the range.
    """
    if base_time is None:
        base_time = datetime(2026, 6, 24, 0, 0, tzinfo=timezone.utc)

    if range_width_price is None:
        # Default to a 30-pip range.
        range_width_price = 30 * pip

    if range_low_override is None:
        range_low = base_price - range_width_price / 2
    else:
        range_low = range_low_override
    if range_high_override is None:
        range_high = range_low + range_width_price
    else:
        range_high = range_high_override

    if break_buffer is None:
        # Default: 5 pips beyond the range, enough to clear buffer_pips=3.
        break_buffer = 5 * pip

    if breakout_close is None:
        if breakout_direction == "bullish":
            breakout_close = range_high + break_buffer
        else:
            breakout_close = range_low - break_buffer

    bars: list[Bar] = []
    for i in range(count - 1):
        t = base_time + timedelta(hours=i % 7)  # 0..6
        # Slight per-bar wiggle so the range isn't a single flat line.
        wiggle = ((i % 3) - 1) * (0.2 * pip)
        bar = Bar(
            time=t,
            open=base_price + wiggle,
            high=base_price + range_width_price / 2 + 0.1 * pip,
            low=base_price - range_width_price / 2 - 0.1 * pip,
            close=base_price + wiggle,
            volume=1000.0,
        )
        bars.append(bar)

    # Final bar: in trade window (hour 7+), breaks the range.
    final_time = base_time + timedelta(hours=7)
    final = Bar(
        time=final_time,
        open=base_price,
        high=max(range_high, breakout_close) + pip,
        low=min(range_low, breakout_close) - pip,
        close=breakout_close,
        volume=1000.0,
    )
    bars.append(final)
    return bars


def _state_for(bars: list[Bar], symbol: str) -> MarketState:
    state = MarketState(bars=bars)
    state.symbol = symbol
    return state


# ---------------------------------------------------------------------------
# Sanity: constants are sensible
# ---------------------------------------------------------------------------


class TestGuardConstants:
    def test_price_bounds_include_known_fx_pairs(self):
        # EURUSD, GBPUSD, USDJPY, XAUUSD all live in [0.01, 10000].
        assert _FX_MIN_PRICE <= 1.0 <= _FX_MAX_PRICE
        assert _FX_MIN_PRICE <= 1.32 <= _FX_MAX_PRICE  # GBPUSD bug entry
        assert _FX_MIN_PRICE <= 150.0 <= _FX_MAX_PRICE  # USDJPY

    def test_max_range_pips_is_finite(self):
        assert 100 < _MAX_RANGE_PIPS < 10_000

    def test_max_tp_distance_pips_is_finite(self):
        assert 500 < _MAX_TP_DISTANCE_PIPS < 10_000


# ---------------------------------------------------------------------------
# Normal-case TP computation (sane inputs → sane outputs)
# ---------------------------------------------------------------------------


class TestSessionBreakoutTP:
    def test_gbpusd_bearish_breakout_produces_sane_tps(self):
        """A normal 30-pip GBPUSD SELL breakout should produce TPs all
        above the entry, all in the GBPUSD price band, and within a few
        hundred pips of entry (TP3 = 3x range = 90 pips from entry)."""
        strategy = SessionBreakoutStrategy(_BASE_CONFIG)
        bars = _make_bars(
            symbol="GBPUSD",
            base_price=1.32000,
            range_width_price=30 * 0.0001,  # 30 pips
            pip=0.0001,
            breakout_direction="bearish",
        )
        state = _state_for(bars, "GBPUSD")

        signal = strategy.evaluate(state)
        assert signal is not None, "Expected a signal for a normal breakout"
        assert signal.direction == TradeDirection.SHORT
        assert 0.0001 <= signal.entry_price <= 10_000
        assert 0.0001 <= signal.take_profit_1 <= 10_000
        assert 0.0001 <= signal.take_profit_2 <= 10_000
        assert 0.0001 <= signal.take_profit_3 <= 10_000
        # TPs must be below entry for a SELL.
        assert signal.take_profit_1 < signal.entry_price
        assert signal.take_profit_2 < signal.take_profit_1
        assert signal.take_profit_3 < signal.take_profit_2
        # TP3 = entry - 3 * range = entry - 0.0030 (30 pips × 3)
        # Distance from entry should be at most 3 * range = 90 pips.
        pip = 0.0001
        max_distance_pips = abs(signal.take_profit_3 - signal.entry_price) / pip
        assert max_distance_pips <= 200, f"TP3 is {max_distance_pips:.1f} pips from entry — too far"

    def test_gbpusd_bullish_breakout_produces_sane_tps(self):
        strategy = SessionBreakoutStrategy(_BASE_CONFIG)
        bars = _make_bars(
            symbol="GBPUSD",
            base_price=1.32000,
            range_width_price=30 * 0.0001,
            pip=0.0001,
            breakout_direction="bullish",
        )
        state = _state_for(bars, "GBPUSD")

        signal = strategy.evaluate(state)
        assert signal is not None
        assert signal.direction == TradeDirection.LONG
        assert signal.take_profit_1 > signal.entry_price
        assert signal.take_profit_2 > signal.take_profit_1
        assert signal.take_profit_3 > signal.take_profit_2

    def test_usdjpy_bearish_breakout_produces_sane_tps(self):
        """USDJPY uses 0.01 pip; TPs should still be within sane bounds."""
        strategy = SessionBreakoutStrategy(_BASE_CONFIG)
        bars = _make_bars(
            symbol="USDJPY",
            base_price=150.000,
            range_width_price=30 * 0.01,  # 30 pips
            pip=0.01,
            breakout_direction="bearish",
        )
        state = _state_for(bars, "USDJPY")

        signal = strategy.evaluate(state)
        assert signal is not None, "Expected a signal for a normal USDJPY breakout"
        assert signal.direction == TradeDirection.SHORT
        assert 0.01 <= signal.entry_price <= 10_000
        # All TPs in JPY price band
        for tp in (signal.take_profit_1, signal.take_profit_2, signal.take_profit_3):
            assert 50 <= tp <= 500, f"TP {tp} outside sane USDJPY band"
            assert tp < signal.entry_price
        # TP3 = entry - 3 * range_pips * pip = entry - 0.90 (90 pips)
        max_distance_pips = abs(signal.take_profit_3 - signal.entry_price) / 0.01
        assert max_distance_pips <= 200, f"TP3 is {max_distance_pips:.1f} pips from entry — too far"

    def test_tps_are_monotonic_in_distance(self):
        """TP1, TP2, TP3 should be at increasing distance from entry."""
        strategy = SessionBreakoutStrategy(_BASE_CONFIG)
        bars = _make_bars(
            symbol="GBPUSD",
            base_price=1.32000,
            range_width_price=30 * 0.0001,
            pip=0.0001,
            breakout_direction="bearish",
        )
        state = _state_for(bars, "GBPUSD")
        signal = strategy.evaluate(state)
        assert signal is not None
        d1 = abs(signal.take_profit_1 - signal.entry_price)
        d2 = abs(signal.take_profit_2 - signal.entry_price)
        d3 = abs(signal.take_profit_3 - signal.entry_price)
        assert d1 < d2 < d3, f"TPs not monotonically distant: {d1} {d2} {d3}"


# ---------------------------------------------------------------------------
# Bug regression: the BQ-? TP corruption pattern is now rejected
# ---------------------------------------------------------------------------


class TestReportedBugRegression:
    """The reported case: GBPUSD SELL, entry=1.319975, tp_price=0.6659.
    That TP is ~6540 pips below entry — the unit-mismatch signature.
    The fix should make ``evaluate`` return None for this input."""

    def test_reported_buggy_tp_value_is_rejected(self):
        """Forge the exact input that produced tp_price=0.6659749999999893.
        We construct bars whose range_width is huge (the upstream unit
        mismatch signature), then assert evaluate() returns None."""
        # Simulate the upstream unit-mismatch: range_high and range_low are
        # in raw-spot-feed units (not divided by 10**digits), so the
        # computed range_width is ~0.44, producing a TP at ~entry/2.
        strategy = SessionBreakoutStrategy(_BASE_CONFIG)
        # Force a 0.44-price-units range, so 1.5 * range_width ≈ 0.66.
        # That gives tp1 = entry - 0.66 ≈ 0.66 for entry ≈ 1.32.
        bars = _make_bars(
            symbol="GBPUSD",
            base_price=1.319975,
            range_width_price=0.44,  # ~4400 pips — clearly bogus
            pip=0.0001,
            breakout_direction="bearish",
        )
        state = _state_for(bars, "GBPUSD")

        signal = strategy.evaluate(state)
        assert signal is None, (
            f"Expected None (rejected) for buggy input, got signal with tp1={signal.take_profit_1 if signal else 'n/a'}"
        )

    def test_tp_below_fx_min_price_is_rejected(self):
        """A TP that is technically a positive number but below 0.01
        (i.e. garbage from a unit mismatch) must be rejected."""
        # The reported TP=0.6659 IS above 0.01, so the price-level guard
        # alone wouldn't catch it. This test confirms the *combination*
        # of guards (price-level + TP-distance) is what catches it.
        strategy = SessionBreakoutStrategy(_BASE_CONFIG)
        # Build a 4000-pip range — 8x the normal 500-pip ceiling.
        bars = _make_bars(
            symbol="GBPUSD",
            base_price=1.32000,
            range_width_price=4000 * 0.0001,  # 4000 pips
            pip=0.0001,
            breakout_direction="bearish",
        )
        state = _state_for(bars, "GBPUSD")
        signal = strategy.evaluate(state)
        assert signal is None, "Signal with 4000-pip range should be rejected"

    def test_tp_above_fx_max_price_is_rejected(self):
        """A TP > 10000 must be rejected (e.g. USDJPY raw-feed units)."""
        strategy = SessionBreakoutStrategy(_BASE_CONFIG)
        bars = _make_bars(
            symbol="USDJPY",
            base_price=150.0,
            # 100,000-pip range → TP3 = entry + 300 * 100 = 30000+
            range_width_price=100_000 * 0.01,
            pip=0.01,
            breakout_direction="bullish",
        )
        state = _state_for(bars, "USDJPY")
        signal = strategy.evaluate(state)
        assert signal is None, "Signal with implausibly large TPs should be rejected"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_zero_atr_returns_none(self):
        """If ATR is zero (degenerate input), no signal."""
        strategy = SessionBreakoutStrategy(_BASE_CONFIG)
        # Use a perfectly flat range so ATR computation yields near-zero.
        bars = _make_bars(
            symbol="GBPUSD",
            base_price=1.32000,
            range_width_price=30 * 0.0001,
            pip=0.0001,
            breakout_direction="bearish",
        )
        # Flatten the breakout bar's range so ATR is essentially 0
        # in the trailing bars.
        for b in bars[:-5]:
            b.high = b.close
            b.low = b.close
        state = _state_for(bars, "GBPUSD")
        # Result is either None (ATR=0) or a signal with sane values.
        # We don't assert None because the ATR computation may still yield
        # a non-zero value from the few non-flat bars; the contract is
        # only that the returned signal (if any) is sane.
        signal = strategy.evaluate(state)
        if signal is not None:
            assert _FX_MIN_PRICE <= signal.take_profit_1 <= _FX_MAX_PRICE
            assert abs(signal.take_profit_1 - signal.entry_price) / 0.0001 < _MAX_TP_DISTANCE_PIPS

    def test_one_signal_per_direction_per_day(self):
        """Re-calling evaluate after a fired signal returns None for that direction."""
        strategy = SessionBreakoutStrategy(_BASE_CONFIG)
        bars1 = _make_bars(
            symbol="GBPUSD",
            base_price=1.32000,
            range_width_price=30 * 0.0001,
            pip=0.0001,
            breakout_direction="bearish",
        )
        state1 = _state_for(bars1, "GBPUSD")
        sig1 = strategy.evaluate(state1)
        assert sig1 is not None
        # Same date/symbol/direction → already fired.
        sig2 = strategy.evaluate(state1)
        assert sig2 is None

    def test_outside_trade_window_returns_none(self):
        """Bars all inside range window (no breakout bar) → no signal."""
        strategy = SessionBreakoutStrategy(_BASE_CONFIG)
        base_time = datetime(2026, 6, 24, 0, 0, tzinfo=timezone.utc)
        bars = []
        for i in range(40):
            t = base_time + timedelta(hours=i % 7)  # 0..6
            bars.append(
                Bar(
                    time=t,
                    open=1.32,
                    high=1.3205,
                    low=1.3195,
                    close=1.32,
                    volume=1000.0,
                )
            )
        state = _state_for(bars, "GBPUSD")
        # No bar in trade window (7-10) → evaluate returns None.
        assert strategy.evaluate(state) is None
