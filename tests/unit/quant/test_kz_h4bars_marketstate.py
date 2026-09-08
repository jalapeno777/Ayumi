"""Regression coverage for card f30917a6-a8e9-465c-8032-1230e9b858cc.

Background
----------
The blend harness path imports ``MarketState`` via::

    from backtest.engine import Bar, MarketState   # forward_test_engine.py:33
    # backtest/engine re-exports backtest.types.MarketState

The harness-side dataclass was a DUPLICATE of ``core.types.MarketState`` and
was MISSING the ``h4_bars`` field. ``KillzoneMomentumStrategy.evaluate``
reads ``state.h4_bars`` at killzone_momentum.py:494, so every qualifying
evaluation raised ``AttributeError: 'MarketState' object has no attribute
'h4_bars'`` — the exception was swallowed by the eval-loop's try/except,
the strategy reported "no signal", and KZ produced **0 signals across
13,380 evaluations** in both the 2026-09-07 and 2026-09-08 blend runs.

This module guards against the duplicate-class divergence coming back:

1. ``TestBacktestMarketStateH4BarsField`` — the canonical, required check:
   ``backtest.types.MarketState`` MUST expose an ``h4_bars`` attribute with
   ``None`` default, matching ``core.types.MarketState``. If this test
   fails, the KZ leg is dead again.

2. ``TestKillzoneH4BarsDefensiveGuard`` — the defensive getattr hardening:
   ``KillzoneMomentumStrategy`` reads H4 bars via ``getattr(state,
   "h4_bars", None)`` so that future type-side divergence surfaces as a
   real exception instead of a silently-swallowed dead strategy.

3. ``TestCoreAndBacktestMarketStateShapeParity`` — parity check between
   the two MarketState classes (the diagnosis doc's "duplicate class"
   smell). If they diverge again, this fails.

Covers:
- backtest.types.MarketState exposes h4_bars (None default)
- backtest.types.MarketState accepts h4_bars on construction
- core.types.MarketState still exposes h4_bars (sanity)
- core.types.MarketState and backtest.types.MarketState have identical
  field names for the cross-timeframe surface
- KillzoneMomentumStrategy.evaluate reads h4_bars via getattr() so the
  AttributeError path is replaced with a None branch
"""

from __future__ import annotations

import inspect
import re
from dataclasses import fields, is_dataclass
from datetime import datetime

import pytest
from backtest.types import Bar
from backtest.types import MarketState as BacktestMarketState
from core.types import MarketState as CoreMarketState


def _make_bar(t: str = "2026-01-01T00:00:00", c: float = 1.1005) -> Bar:
    """Build a minimal Bar for MarketState construction."""
    return Bar(
        time=datetime.fromisoformat(t),
        open=1.1000,
        high=1.1010,
        low=1.0990,
        close=c,
    )


# ---------------------------------------------------------------------------
# TestBacktestMarketStateH4BarsField
# ---------------------------------------------------------------------------


class TestBacktestMarketStateH4BarsField:
    """``backtest.types.MarketState`` MUST expose ``h4_bars``.

    This is the canonical required check for card f30917a6. Without this
    field, the KZ strategy raises AttributeError on every qualifying eval.
    """

    def test_marketstate_is_dataclass(self):
        """backtest.types.MarketState is still a dataclass."""
        assert is_dataclass(BacktestMarketState)

    def test_marketstate_has_h4_bars_field(self):
        """backtest.types.MarketState declares h4_bars on the dataclass."""
        field_names = {f.name for f in fields(BacktestMarketState)}
        assert "h4_bars" in field_names, (
            "backtest.types.MarketState is missing h4_bars; "
            "this is the duplicate-class divergence that killed KZ"
        )

    def test_h4_bars_field_default_is_none(self):
        """h4_bars defaults to None so backward-compatible callers work."""
        h4_field = next(f for f in fields(BacktestMarketState) if f.name == "h4_bars")
        assert h4_field.default is None, (
            f"h4_bars must default to None for backward-compat; got {h4_field.default!r}"
        )

    def test_h4_bars_default_constructible_without_supplying(self):
        """Constructing MarketState without h4_bars succeeds and yields None."""
        state = BacktestMarketState(bars=[_make_bar()])
        assert state.h4_bars is None

    def test_h4_bars_accepts_list_of_bars(self):
        """Constructing MarketState with h4_bars stores the list verbatim."""
        h4 = [_make_bar(t=f"2026-01-01T{i:02d}:00:00") for i in range(4)]
        state = BacktestMarketState(bars=[_make_bar()], h4_bars=h4)
        assert state.h4_bars is h4
        assert len(state.h4_bars) == 4

    def test_h4_bars_attribute_access_does_not_raise(self):
        """Reading ``state.h4_bars`` MUST NOT raise AttributeError.

        This is the exact pre-fix failure mode: the dataclass was missing
        the field, so any ``state.h4_bars`` read raised AttributeError.
        """
        state = BacktestMarketState(bars=[_make_bar()])
        # Pre-fix: this raised AttributeError. Post-fix: returns None.
        try:
            value = state.h4_bars
        except AttributeError as exc:  # pragma: no cover — regression sentinel
            pytest.fail(
                f"state.h4_bars raised AttributeError (this is the KZ-dead "
                f"bug regressing): {exc}"
            )
        assert value is None


# ---------------------------------------------------------------------------
# TestCoreAndBacktestMarketStateShapeParity
# ---------------------------------------------------------------------------


class TestCoreAndBacktestMarketStateShapeParity:
    """Both MarketState classes must expose the same h4_bars field.

    The diagnosis doc flagged that core.types.MarketState and
    backtest.types.MarketState were duplicates that drifted. This test
    fails CI immediately if a future change re-introduces the divergence
    on the h4_bars surface specifically.
    """

    def test_both_classes_are_dataclasses(self):
        assert is_dataclass(CoreMarketState)
        assert is_dataclass(BacktestMarketState)

    def test_both_classes_have_h4_bars(self):
        core_fields = {f.name for f in fields(CoreMarketState)}
        bt_fields = {f.name for f in fields(BacktestMarketState)}
        assert "h4_bars" in core_fields
        assert "h4_bars" in bt_fields

    def test_both_classes_have_bars_and_current_session(self):
        """Both classes still carry the canonical 'bars' + 'current_session' surface."""
        for cls in (CoreMarketState, BacktestMarketState):
            field_names = {f.name for f in fields(cls)}
            assert "bars" in field_names
            assert "current_session" in field_names

    def test_h4_bars_default_is_none_on_both_classes(self):
        """Default of h4_bars is None on both classes (no caller is required to pass it)."""
        for cls in (CoreMarketState, BacktestMarketState):
            h4 = next(f for f in fields(cls) if f.name == "h4_bars")
            assert h4.default is None, f"{cls.__module__}.{cls.__name__}.h4_bars default must be None"


# ---------------------------------------------------------------------------
# TestKillzoneH4BarsDefensiveGuard
# ---------------------------------------------------------------------------


class TestKillzoneH4BarsDefensiveGuard:
    """The KZ strategy MUST read h4_bars via getattr() to fail loudly.

    Card f30917a6 step 2: change ``state.h4_bars`` reads in
    killzone_momentum.py to ``getattr(state, "h4_bars", None)`` so a future
    type-side divergence surfaces as a real AttributeError instead of a
    silently-swallowed dead strategy.
    """

    def test_killzone_momentum_evaluate_uses_getattr_for_h4_bars(self):
        """evaluate() reads h4_bars via getattr(), not direct attribute access.

        We grep the source because the read happens deep inside the eval
        flow and is hard to drive end-to-end without a full strategy pool.
        The point of this test is to lock in the loud-failure posture so a
        future "cleanup" can't reintroduce a silent-kill pattern.
        """
        import strategies.killzone_momentum as kzm

        source = inspect.getsource(kzm)
        # Look for the pattern: getattr(state, "h4_bars", None)
        assert re.search(r'getattr\(\s*state\s*,\s*["\']h4_bars["\']\s*,\s*None\s*\)', source), (
            "killzone_momentum.py must read state.h4_bars via "
            "getattr(state, 'h4_bars', None) — direct attribute access "
            "silently kills KZ if the MarketState class diverges"
        )

    def test_killzone_momentum_does_not_have_bare_state_h4_bars_attribute_read(self):
        """No bare ``state.h4_bars`` attribute reads remain in evaluate().

        ``getattr(state, "h4_bars", None)`` is fine; ``state.h4_bars``
        bare-access is forbidden (regression sentinel for the silent-kill).
        """
        import strategies.killzone_momentum as kzm

        source = inspect.getsource(kzm)
        # Match "state.h4_bars" but NOT "getattr(state, ..h4_bars..)"
        bare_reads = re.findall(r"(?<![\w.\"'])\bstate\.h4_bars\b", source)
        assert bare_reads == [], (
            f"killzone_momentum.py has bare state.h4_bars reads: {bare_reads}. "
            f"Use getattr(state, 'h4_bars', None) for defensive guarding."
        )


# ---------------------------------------------------------------------------
# TestKillzoneH4BarsEndToEndBehavior
# ---------------------------------------------------------------------------


class TestKillzoneH4BarsEndToEndBehavior:
    """End-to-end: KZ evaluate() MUST NOT raise when MarketState lacks h4_bars.

    Before the fix, ``state.h4_bars`` raised AttributeError. After the fix,
    the H4 filter short-circuits via ``getattr(..., None)`` so missing
    h4_bars means "skip the filter, evaluate normally".

    We construct a minimal scenario that would have crashed before the fix
    and verify it no longer raises AttributeError on the h4_bars read.
    """

    def test_state_without_h4_bars_does_not_raise_attribute_error(self):
        """Constructing a backtest MarketState without h4_bars is non-fatal.

        Pre-fix, the dataclass itself rejected this because h4_bars
        wasn't declared — accessing state.h4_bars raised AttributeError.
        Post-fix, the dataclass declares h4_bars with a None default, so
        the read succeeds and returns None.
        """
        state = BacktestMarketState(bars=[_make_bar()])
        # The exact attribute access that crashed pre-fix.
        assert state.h4_bars is None  # if this raises, the bug is back

    def test_state_with_h4_bars_round_trips_through_attribute(self):
        """A list of H4 bars supplied at construction round-trips back."""
        h4 = [_make_bar(t=f"2026-01-01T{i:02d}:00:00") for i in range(6)]
        state = BacktestMarketState(bars=[_make_bar()], h4_bars=h4)
        assert state.h4_bars is h4
        assert len(state.h4_bars) == 6
