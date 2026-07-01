"""Smoke tests for TTCXAUUSDStrategy — BQ-1121 wire-it card.

Verifies the strategy module can be imported, instantiated, and evaluated
against a synthetic XAUUSD M15 bar stream. Also verifies the strategy is
registered in strategies/registry.py and surfaces for XAUUSD symbol
selection (i.e. walk_forward / blend selection can find it).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backtest.types import Bar, MarketState, TradeDirection


XAUUSD_BASE = 2400.00
BAR_COUNT = 60  # > min_bars_for_evaluation=50


def _make_xauusd_m15_bars(n: int = BAR_COUNT) -> list[Bar]:
    """Generate a synthetic XAUUSD M15 bar stream with a mild uptrend.

    Prices oscillate around XAUUSD_BASE with a small positive drift so
    the underlying TTSStrategy has enough structure (swings, ATR) to
    produce or withhold a signal without obviously forcing one.
    """
    bars: list[Bar] = []
    base_time = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    price = XAUUSD_BASE
    for i in range(n):
        # Drift +0.05/period, sine oscillation amplitude 1.0
        import math

        drift = 0.05 * i
        osc = 1.0 * math.sin(i / 3.0)
        close = price + drift + osc
        open_ = close - 0.2
        high = max(open_, close) + 0.4
        low = min(open_, close) - 0.4
        bars.append(
            Bar(
                time=base_time + timedelta(minutes=15 * i),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=200,
            )
        )
    return bars


def _make_state(bars: list[Bar] | None = None) -> MarketState:
    return MarketState(bars=bars or _make_xauusd_m15_bars())


# ---------- Module / class surface tests ----------


def test_module_imports():
    from strategies.ttc_xauusd import TTCXAUUSDStrategy

    assert TTCXAUUSDStrategy is not None
    assert TTCXAUUSDStrategy.name == "TTC XAUUSD M15"


def test_strategy_instantiation():
    from strategies.ttc_xauusd import TTCXAUUSDStrategy

    strat = TTCXAUUSDStrategy()
    assert strat is not None
    # Inner strategy must be wired
    assert hasattr(strat, "_strategy")
    assert strat._strategy is not None


# ---------- Smoke test: mock tick → signal pipeline ----------


def test_evaluate_with_sufficient_bars_returns_signal_or_none():
    """Mock tick stream → strategy evaluates without raising.

    TTSStrategy may legitimately return None on quiet bars; what we need
    to verify here is the wiring works (the monkeypatch dance inside
    __init__ restores the original module-level constants) and the
    evaluate call returns either None or a StrategySignal — never an
    exception, never a malformed value.
    """
    from strategies.ttc_xauusd import TTCXAUUSDStrategy

    strat = TTCXAUUSDStrategy()
    state = _make_state()

    result = strat.evaluate(state)

    if result is not None:
        assert hasattr(result, "direction")
        assert result.direction in (
            TradeDirection.LONG,
            TradeDirection.SHORT,
            TradeDirection.NEUTRAL,
        )
        assert 0.0 <= result.confidence <= 1.0
        assert result.entry_price > 0
    # else: None is acceptable (strategy filtering it out)


def test_evaluate_with_insufficient_bars_returns_none():
    """Too few bars → strategy should not crash, should not signal."""
    from strategies.ttc_xauusd import TTCXAUUSDStrategy

    strat = TTCXAUUSDStrategy()
    state = _make_state(bars=[])  # empty bars

    # Should not raise
    result = strat.evaluate(state)
    # No signal expected with no bars
    assert result is None


def test_evaluate_does_not_leak_tts_module_state():
    """The monkeypatched TTS module constants must be restored after init.

    This guards against a regression where TTCXAUUSDStrategy forgets to
    restore originals in the finally block — that would silently corrupt
    the shared tts_strategy module for every other caller.
    """
    from strategies.ttc_xauusd import TTCXAUUSDStrategy
    import backtest.strategies.tts_strategy as tts_mod

    # Snapshot one of the monkeypatched constants
    original_value = getattr(tts_mod, "MW_BASE_CONFIDENCE", None)
    assert original_value is not None, "MW_BASE_CONFIDENCE should exist in TTS module"

    # Construct two strategies back-to-back
    TTCXAUUSDStrategy()
    mid_value = getattr(tts_mod, "MW_BASE_CONFIDENCE", None)
    TTCXAUUSDStrategy()

    final_value = getattr(tts_mod, "MW_BASE_CONFIDENCE", None)
    assert final_value == original_value, (
        f"TTS module constant leaked: was {original_value}, "
        f"mid-init {mid_value}, after {final_value}"
    )


# ---------- Registry tests: "walk_forward selection" wiring ----------


def test_ttc_xauusd_in_default_registry():
    """Acceptance: ttc_xauusd registered in strategies/registry.py."""
    from strategies.registry import default_registry

    reg = default_registry()
    ttc = reg.get("ttc_xauusd")
    assert ttc is not None, "ttc_xauusd missing from default registry"
    assert ttc.strategy_id == "ttc_xauusd"
    assert ttc.name == "TTC XAUUSD M15"
    assert ttc.strategy_type == "momentum"
    assert "XAUUSD" in [s.upper() for s in ttc.symbols]
    assert "M15" in ttc.timeframes
    assert ttc.active is True


def test_ttc_xauusd_selectable_for_xauusd():
    """Acceptance: strategy appears in walk_forward / blend selection for XAUUSD."""
    from strategies.registry import default_registry

    reg = default_registry()
    xauusd_strategies = reg.get_for_symbol("XAUUSD")
    strategy_ids = [s.strategy_id for s in xauusd_strategies]
    assert "ttc_xauusd" in strategy_ids, (
        f"ttc_xauusd not selectable for XAUUSD. "
        f"Currently selectable: {strategy_ids}"
    )


def test_ttc_xauusd_listed_in_active_strategies():
    """Make sure it shows up in get_all_active() — required for any
    pipeline that iterates the full registry (signal_provider, etc.)."""
    from strategies.registry import default_registry

    reg = default_registry()
    all_active_ids = [s.strategy_id for s in reg.get_all_active()]
    assert "ttc_xauusd" in all_active_ids


# ---------- Realistic input sanity checks ----------


def test_xauusd_bars_have_realistic_prices():
    """Sanity check: synthetic XAUUSD bar stream is in the right ballpark."""
    bars = _make_xauusd_m15_bars()
    assert len(bars) == BAR_COUNT
    for bar in bars:
        # XAUUSD is gold — should be in the $1000-$5000 range for synthetic data
        assert 1000.0 < bar.close < 5000.0, f"Unrealistic XAUUSD price: {bar.close}"
        assert bar.high >= bar.low
        assert bar.high >= bar.open
        assert bar.high >= bar.close
        assert bar.low <= bar.open
        assert bar.low <= bar.close


def test_bars_are_chronologically_ordered():
    bars = _make_xauusd_m15_bars()
    for i in range(1, len(bars)):
        assert bars[i].time > bars[i - 1].time, (
            f"Bar {i} time {bars[i].time} not after bar {i-1} time {bars[i-1].time}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
