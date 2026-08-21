"""Tests for VolatilitySqueezeStrategy entry-logic fix (card 453dac89).

The original code required `adx >= 20` *while in a squeeze* — impossible by
definition, so the strategy produced zero trades across all 9 SRF cells
(verified via `data/research/research.duckdb`).

These tests verify the fixed entry logic:
- A squeeze followed by a BB-outside-KC release reaches the entry branch
  (the ADX gate no longer blocks it).
- The signal direction matches the breakout direction.
- The signal structure (SL/TP/confidence) is well-formed.
- The RSI overbought/oversold filter still blocks (regression).
- The session filter still blocks (regression).

The test data is built so that the squeeze forms deterministically (BB
inside KC) and the breakout bar pushes the latest close above the upper
Keltner band. The squeeze is so flat that the breakout drives RSI to
overbought — that is the *correct* behavior of the (independent,
pre-existing) RSI filter. We isolate the bug fix by monkey-patching
``_calculate_rsi`` in those tests so the entry branch is verifiable
without the RSI filter masking the fix.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from core.types import Bar, BarPeriod, MarketState, SessionType, TradeDirection
from strategies.volatility_squeeze import (
    VolatilitySqueezeConfig,
    VolatilitySqueezeStrategy,
    _calculate_bollinger_bands,
    _calculate_keltner_channels,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_squeeze_bars(
    n: int,
    base_price: float = 1.10000,
) -> list[Bar]:
    """Build n bars at a constant price → guaranteed squeeze. With
    identical closes, BB and KC collapse to a single line, so
    ``bb_upper <= kc_upper and bb_lower >= kc_lower`` holds for every
    bar from bar ``bb_period`` onward. The breakout bar is appended
    separately so the strategy sees a clear release transition.
    """
    bars: list[Bar] = []
    base_time = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    for i in range(n):
        bars.append(
            Bar(
                time=base_time + timedelta(hours=i),
                open=base_price,
                high=base_price,
                low=base_price,
                close=base_price,
                volume=1000.0,
                period=BarPeriod.H1(),
                spread_pips=0.0,
            )
        )
    return bars


def _append_breakout_bar(
    bars: list[Bar],
    magnitude: float = 0.0050,
    direction: str = "up",
) -> Bar:
    """Append a single breakout bar in `direction` ('up' or 'down'). The
    bar has a wide intra-bar range so BB re-expands outside KC on this
    bar (release transition)."""
    last = bars[-1]
    if direction == "up":
        open_ = last.close
        close = last.close + magnitude
        high = close + magnitude * 0.20
        low = open_ - magnitude * 0.05
    else:
        open_ = last.close
        close = last.close - magnitude
        high = open_ + magnitude * 0.05
        low = close - magnitude * 0.20
    breakout = Bar(
        time=last.time + timedelta(hours=1),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1500.0,
        period=BarPeriod.H1(),
        spread_pips=0.0,
    )
    bars.append(breakout)
    return breakout


def _make_state(bars: list[Bar], session: SessionType = SessionType.LONDON) -> MarketState:
    return MarketState(bars=bars, current_session=session)


def _drive_then_evaluate(
    strategy: VolatilitySqueezeStrategy,
    bars: list[Bar],
    session: SessionType = SessionType.LONDON,
) -> tuple[list[Bar], object | None]:
    """Feed bars incrementally so the strategy's internal state
    (``_squeeze_bar_count`` / ``_was_in_squeeze``) tracks the squeeze
    correctly. Returns the final running bars and the *last* non-None
    signal emitted during the drive (or None if no signal ever fired).

    Critical: the strategy mutates internal state on each call, so it
    must be driven bar-by-bar — a single ``evaluate(full_list)`` call
    never accumulates squeeze bars and never fires a release signal.
    Evaluating the last bar twice would reset ``_was_in_squeeze`` and
    ``_squeeze_bar_count`` and erase the signal, so we only evaluate
    once per bar.
    """
    running: list[Bar] = []
    last_signal = None
    for bar in bars:
        running.append(bar)
        sig = strategy.evaluate(_make_state(running, session=session))
        if sig is not None:
            last_signal = sig
    return running, last_signal


# ---------------------------------------------------------------------------
# Bug-fix tests
# ---------------------------------------------------------------------------


class TestVolatilitySqueezeBugfix:
    """The card 453dac89 fix: the entry branch must be reachable on a
    squeeze release. The original `adx >= 20` gate made it unreachable."""

    def test_entry_branch_reachable_on_squeeze_release_long(self):
        """A squeeze release to the upside must reach the LONG entry branch.

        The pre-fix code gated entry on `adx >= 20` while in a squeeze,
        which is impossible by definition. With the gate removed, a
        release bar whose close exceeds kc_upper and ema should produce
        a LONG signal. We neutralise the RSI overbought filter here so
        the test isolates the ADX-gate bug fix.
        """
        config = VolatilitySqueezeConfig(
            session_filter=False,  # remove session gate for determinism
            min_squeeze_bars=3,
        )
        strategy = VolatilitySqueezeStrategy(config)

        flat = _make_squeeze_bars(80)
        _append_breakout_bar(flat, magnitude=0.0050, direction="up")

        # Sanity: prior bar was in a squeeze (so the release transition is
        # observable on the breakout bar).
        running, _ = _drive_then_evaluate(strategy, flat[:-1])
        assert strategy._was_in_squeeze, (
            "Pre-breakout bar must show the strategy in a squeeze so the release transition is observable."
        )
        assert strategy._squeeze_bar_count >= config.min_squeeze_bars

        # Sanity: the breakout bar pushes BB outside KC.
        bb_u, _, bb_l = _calculate_bollinger_bands(flat, 20, 2.0)
        kc_u, _, kc_l = _calculate_keltner_channels(flat, 20, 2.0)
        assert not (bb_u <= kc_u and bb_l >= kc_l), (
            "Post-breakout bar must be outside the squeeze (BB > KC width) so squeeze_just_released is True."
        )

        # Drive the strategy bar-by-bar through the entire series.
        # Mock RSI so the (correct, separate) overbought filter does not
        # mask the ADX-gate fix being verified here.
        with patch("strategies.volatility_squeeze._calculate_rsi", return_value=50.0):
            _, signal = _drive_then_evaluate(strategy, flat)

        assert signal is not None, (
            "Squeeze release must produce a signal after the ADX gate was "
            "removed (card 453dac89 fix). Pre-fix this was impossible: the "
            "`adx >= 20` condition could not be satisfied during a squeeze."
        )
        assert signal.direction == TradeDirection.LONG
        assert signal.entry_price > 0
        assert signal.stop_loss < signal.entry_price
        assert signal.take_profit_1 > signal.entry_price
        assert signal.confidence >= config.min_confidence
        assert signal.rationale

    def test_entry_branch_reachable_on_squeeze_release_short(self):
        """A squeeze release to the downside must reach the SHORT entry branch."""
        config = VolatilitySqueezeConfig(session_filter=False, min_squeeze_bars=3)
        strategy = VolatilitySqueezeStrategy(config)

        flat = _make_squeeze_bars(80, base_price=1.30000)
        _append_breakout_bar(flat, magnitude=0.0050, direction="down")

        with patch("strategies.volatility_squeeze._calculate_rsi", return_value=50.0):
            _, signal = _drive_then_evaluate(strategy, flat)

        assert signal is not None
        assert signal.direction == TradeDirection.SHORT
        assert signal.stop_loss > signal.entry_price
        assert signal.take_profit_1 < signal.entry_price

    def test_no_signal_during_continued_squeeze(self):
        """A squeeze that is *not* released must not signal."""
        config = VolatilitySqueezeConfig(session_filter=False, min_squeeze_bars=3)
        strategy = VolatilitySqueezeStrategy(config)

        flat = _make_squeeze_bars(80)
        # Add one more flat (squeezed) bar — no release transition.
        last = flat[-1]
        flat.append(
            Bar(
                time=last.time + timedelta(hours=1),
                open=last.close,
                high=last.close + 0.00005,
                low=last.close - 0.00005,
                close=last.close,
                volume=1000.0,
                period=BarPeriod.H1(),
                spread_pips=0.0,
            )
        )

        with patch("strategies.volatility_squeeze._calculate_rsi", return_value=50.0):
            _, signal = _drive_then_evaluate(strategy, flat)

        assert signal is None, "Continued squeeze must not signal"

    def test_signal_structure_is_well_formed(self):
        """SL/TP distances, confidence, and rationale are well-formed."""
        config = VolatilitySqueezeConfig(
            session_filter=False,
            min_squeeze_bars=2,
            atr_sl_multiplier=1.5,
        )
        strategy = VolatilitySqueezeStrategy(config)

        flat = _make_squeeze_bars(80)
        _append_breakout_bar(flat, magnitude=0.0050, direction="up")

        with patch("strategies.volatility_squeeze._calculate_rsi", return_value=50.0):
            _, signal = _drive_then_evaluate(strategy, flat)

        assert signal is not None
        risk = signal.entry_price - signal.stop_loss
        assert risk > 0
        assert signal.take_profit_1 == pytest.approx(signal.entry_price + risk * config.tp1_rr, rel=1e-3)
        assert signal.take_profit_2 == pytest.approx(signal.entry_price + risk * config.tp2_rr, rel=1e-3)
        assert signal.take_profit_3 == pytest.approx(signal.entry_price + risk * config.tp3_rr, rel=1e-3)
        assert 0.0 < signal.confidence <= 0.95


# ---------------------------------------------------------------------------
# Regression: filters that must still work
# ---------------------------------------------------------------------------


class TestVolatilitySqueezeFilters:
    """Filters that exist independently of the bug fix must still work."""

    def test_rsi_overbought_blocks_long(self):
        """An RSI >= 70 must block a long signal (pre-existing filter)."""
        config = VolatilitySqueezeConfig(session_filter=False, min_squeeze_bars=2)
        strategy = VolatilitySqueezeStrategy(config)

        flat = _make_squeeze_bars(80)
        _append_breakout_bar(flat, magnitude=0.0050, direction="up")

        with patch("strategies.volatility_squeeze._calculate_rsi", return_value=85.0):
            _, signal = _drive_then_evaluate(strategy, flat)

        # Either no signal, or a non-long signal — long is forbidden here.
        if signal is not None:
            assert signal.direction != TradeDirection.LONG

    def test_rsi_oversold_blocks_short(self):
        """An RSI <= 30 must block a short signal (pre-existing filter)."""
        config = VolatilitySqueezeConfig(session_filter=False, min_squeeze_bars=2)
        strategy = VolatilitySqueezeStrategy(config)

        flat = _make_squeeze_bars(80, base_price=1.30000)
        _append_breakout_bar(flat, magnitude=0.0050, direction="down")

        with patch("strategies.volatility_squeeze._calculate_rsi", return_value=15.0):
            _, signal = _drive_then_evaluate(strategy, flat)

        if signal is not None:
            assert signal.direction != TradeDirection.SHORT

    def test_session_filter_blocks_outside_session(self):
        """With session_filter=True, an OUTSIDE session must not signal."""
        config = VolatilitySqueezeConfig(session_filter=True, min_squeeze_bars=2)
        strategy = VolatilitySqueezeStrategy(config)

        flat = _make_squeeze_bars(80)
        _append_breakout_bar(flat, magnitude=0.0050, direction="up")

        with patch("strategies.volatility_squeeze._calculate_rsi", return_value=50.0):
            _, signal = _drive_then_evaluate(strategy, flat, session=SessionType.OUTSIDE)
        assert signal is None, "Session filter must still reject OUTSIDE session"

    def test_session_filter_passes_london(self):
        """With session_filter=True, LONDON session is allowed to signal."""
        config = VolatilitySqueezeConfig(session_filter=True, min_squeeze_bars=2)
        strategy = VolatilitySqueezeStrategy(config)

        flat = _make_squeeze_bars(80)
        _append_breakout_bar(flat, magnitude=0.0050, direction="up")

        with patch("strategies.volatility_squeeze._calculate_rsi", return_value=50.0):
            _, signal = _drive_then_evaluate(strategy, flat, session=SessionType.LONDON)
        assert signal is not None, "LONDON session must allow the signal"


# ---------------------------------------------------------------------------
# Smoke + invariants
# ---------------------------------------------------------------------------


class TestVolatilitySqueezeInvariants:
    def test_reset_clears_internal_state(self):
        config = VolatilitySqueezeConfig(session_filter=False)
        strategy = VolatilitySqueezeStrategy(config)
        strategy._squeeze_bar_count = 9
        strategy._was_in_squeeze = True
        strategy.reset()
        assert strategy._squeeze_bar_count == 0
        assert strategy._was_in_squeeze is False

    def test_strategy_name_preserved(self):
        assert VolatilitySqueezeStrategy().name == "Volatility Squeeze Breakout"

    def test_insufficient_bars_returns_none(self):
        config = VolatilitySqueezeConfig(session_filter=False)
        strategy = VolatilitySqueezeStrategy(config)
        # Way below min_required (bb + kc + ema + adx + 5).
        bars = _make_squeeze_bars(20)
        assert strategy.evaluate(_make_state(bars)) is None
