"""Tests for stop_target.py"""

import pytest
from signal_engine.stop_target import StopTargetCalculator


@pytest.fixture
def calc():
    return StopTargetCalculator(rr_ratio=2.0, pip_size=0.0001)


def _long_context(**overrides):
    c = {"sl2": 1.08300, "r2": 1.08800, "r3": 1.09000, "atr": 0.00080}
    c.update(overrides)
    return c


def _short_context(**overrides):
    c = {"sh2": 1.08700, "d2": 1.08200, "d3": 1.08000, "atr": 0.00080}
    c.update(overrides)
    return c


def test_long_sl_below_sl2(calc):
    result = calc.calculate("long", 1.08500, _long_context())
    assert result["stop_loss"] < 1.08300  # below SL2 + buffer


def test_long_tp_uses_structure(calc):
    result = calc.calculate("long", 1.08500, _long_context())
    assert result["take_profit"] >= 1.08800  # at least R2
    assert result["stop_loss"] < 1.08500


def test_long_rr_ratio(calc):
    result = calc.calculate("long", 1.08500, _long_context())
    assert result["rr_ratio"] > 1.0


def test_short_sl_above_sh2(calc):
    result = calc.calculate("short", 1.08500, _short_context())
    assert result["stop_loss"] > 1.08700  # above SH2 + buffer


def test_short_tp_uses_structure(calc):
    result = calc.calculate("short", 1.08500, _short_context())
    assert result["take_profit"] <= 1.08200
    assert result["stop_loss"] > 1.08500


def test_no_structure_levels_uses_rr(calc):
    """When no R2/R3 given, fall back to pure R:R target."""
    result = calc.calculate("long", 1.08500, {"sl2": 1.08300})
    assert result["take_profit"] > 1.08500
    assert len(result["tp_levels"]) >= 1


def test_tp_levels_have_names(calc):
    result = calc.calculate("long", 1.08500, _long_context())
    names = [t["level"] for t in result["tp_levels"]]
    assert "R2" in names or "R3" in names


def test_trailing_config_breakeven(calc):
    result = calc.calculate("long", 1.08500, _long_context())
    trail = result["trailing"]
    risk = 1.08500 - result["stop_loss"]
    assert trail["breakeven_trigger"] == pytest.approx(1.08500 + risk, abs=0.0001)


def test_spread_buffer_included(calc):
    """Spread should widen the SL further from entry."""
    no_spread = calc.calculate("long", 1.08500, _long_context(), spread=0.0)
    with_spread = calc.calculate("long", 1.08500, _long_context(), spread=0.00020)
    assert with_spread["stop_loss"] <= no_spread["stop_loss"]


def test_risk_reward_fields(calc):
    result = calc.calculate("long", 1.08500, _long_context())
    assert result["risk_pips"] > 0
    assert result["reward_pips"] > 0
    assert result["reward_pips"] > result["risk_pips"]  # RR > 1
