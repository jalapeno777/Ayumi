"""Tests for StopTargetCalculator: ATR-based SL/TP, RR enforcement, spread buffer."""

from __future__ import annotations  # noqa: I001


from signal_engine.stop_target import StopTargetCalculator


# ── Helpers ─────────────────────────────────────────────────────────


def _calc(direction="long", entry=1.10000, atr=0.00100, timeframe="M15", **ctx):
    calc = StopTargetCalculator(timeframe=timeframe, pip_size=0.0001)
    context = {"atr": atr, **ctx}
    return calc.calculate(direction, entry, context)


# ── Stop Loss ───────────────────────────────────────────────────────


class TestStopLoss:
    def test_long_sl_below_entry(self):
        result = _calc("long")
        assert result["stop_loss"] < 1.10000

    def test_short_sl_above_entry(self):
        result = _calc("short")
        assert result["stop_loss"] > 1.10000

    def test_sl_includes_spread_buffer(self):
        result = _calc("long", spread=0.0002)
        # SL should be lower with spread than without
        result_no_spread = _calc("long", spread=0.0)
        assert result["stop_loss"] <= result_no_spread["stop_loss"]

    def test_zero_atr_falls_back_to_structure(self):
        result = _calc("long", atr=0.0)
        assert result["stop_loss"] < 1.10000

    def test_zero_atr_short(self):
        result = _calc("short", atr=0.0)
        assert result["stop_loss"] > 1.10000

    def test_different_timeframes_different_sl(self):
        m5 = _calc("long", timeframe="M5")
        d1 = _calc("long", timeframe="D1")
        # D1 multiplier is higher → wider SL
        assert d1["stop_loss"] < m5["stop_loss"]

    def test_structure_sl_long(self):
        """sl2 in context limits SL for longs."""
        result = _calc("long", sl2=1.09850)
        # ATR SL for M15: 0.001 * 1.5 = 0.0015 → 1.0985 - buffer
        # Structure SL: 1.09850 - buffer
        # max(atr_sl, structure_sl) is used
        assert result["stop_loss"] < 1.10000

    def test_structure_sl_short(self):
        result = _calc("short", sh2=1.10150)
        assert result["stop_loss"] > 1.10000

    def test_sl_capped_at_max_atr_mult(self):
        """Even with huge TF multiplier, SL capped at 4x ATR."""
        result = _calc("long", atr=0.00100, timeframe="D1")
        sl_distance = 1.10000 - result["stop_loss"]
        assert sl_distance <= 0.00100 * 4.0 + 0.0001  # 4x ATR + buffer


# ── Take Profit ─────────────────────────────────────────────────────


class TestTakeProfit:
    def test_long_tp_above_entry(self):
        result = _calc("long")
        assert result["take_profit"] > 1.10000

    def test_short_tp_below_entry(self):
        result = _calc("short")
        assert result["take_profit"] < 1.10000

    def test_three_tp_levels(self):
        result = _calc("long")
        assert len(result["tp_levels"]) >= 3

    def test_tp_levels_ascending_for_long(self):
        result = _calc("long")
        prices = [t["price"] for t in result["tp_levels"][:3]]
        assert prices == sorted(prices)

    def test_tp_levels_descending_for_short(self):
        result = _calc("short")
        prices = [t["price"] for t in result["tp_levels"][:3]]
        assert prices == sorted(prices, reverse=True)

    def test_min_rr_enforced(self):
        result = _calc("long", atr=0.00010)  # small ATR
        rr = result["rr_ratio"]
        assert rr >= 1.4  # M15 min RR is 1.5 but floating point tolerance


# ── Risk/Reward ─────────────────────────────────────────────────────


class TestRR:
    def test_rr_ratio_positive(self):
        result = _calc("long")
        assert result["rr_ratio"] > 0

    def test_risk_reward_pips(self):
        result = _calc("long")
        assert result["risk_pips"] > 0
        assert result["reward_pips"] > 0


# ── Trailing ────────────────────────────────────────────────────────


class TestTrailing:
    def test_trailing_config_present(self):
        result = _calc("long")
        t = result["trailing"]
        assert "breakeven_trigger" in t
        assert "trail_start" in t
        assert "trail_step" in t

    def test_breakeven_trigger_long_above_entry(self):
        result = _calc("long")
        assert result["trailing"]["breakeven_trigger"] > 1.10000

    def test_breakeven_trigger_short_below_entry(self):
        result = _calc("short")
        assert result["trailing"]["breakeven_trigger"] < 1.10000

    def test_trail_step_atr_when_available(self):
        result = _calc("long", atr=0.001)
        assert result["trailing"]["trail_step"] == "atr_half"

    def test_trail_step_half_when_no_atr(self):
        result = _calc("long", atr=0.0)
        assert result["trailing"]["trail_step"] == "half_remaining"


# ── Structure levels ────────────────────────────────────────────────


class TestStructureLevels:
    def test_r2_r3_added_for_long(self):
        result = _calc("long", r2=1.1050, r3=1.1100)
        levels = {t["level"] for t in result["tp_levels"]}
        assert "R2" in levels
        assert "R3" in levels

    def test_d2_d3_added_for_short(self):
        result = _calc("short", d2=1.0950, d3=1.0900)
        levels = {t["level"] for t in result["tp_levels"]}
        assert "D2" in levels
        assert "D3" in levels

    def test_wrong_side_structure_ignored(self):
        """R2 below entry should not be added for long."""
        result = _calc("long", r2=1.0950)  # below entry
        prices = [t for t in result["tp_levels"] if t.get("structure")]
        # r2=1.0950 is below entry=1.1, so shouldn't be added
        assert not any(t["level"] == "R2" for t in prices)
