"""Tests for ATR-based stop_target.py redesign."""

import pytest
from signal_engine.stop_target import (
    StopTargetCalculator,
    ATR_SL_MULTIPLIERS,
    ATR_TP_MULTIPLIERS,
    MIN_RR_BY_TF,
    MAX_SL_ATR_MULT,
)


@pytest.fixture
def m15_calc():
    return StopTargetCalculator(rr_ratio=2.0, pip_size=0.0001, timeframe="M15")


@pytest.fixture
def h1_calc():
    return StopTargetCalculator(rr_ratio=2.0, pip_size=0.0001, timeframe="H1")


@pytest.fixture
def d1_calc():
    return StopTargetCalculator(rr_ratio=2.0, pip_size=0.0001, timeframe="D1")


def _long_context(**overrides):
    c = {"sl2": 1.08300, "r2": 1.08800, "r3": 1.09000, "atr": 0.00080}
    c.update(overrides)
    return c


def _short_context(**overrides):
    c = {"sh2": 1.08700, "d2": 1.08200, "d3": 1.08000, "atr": 0.00080}
    c.update(overrides)
    return c


class TestATRStopLoss:
    def test_long_sl_atr_based(self, m15_calc):
        result = m15_calc.calculate("long", 1.08500, _long_context())
        atr = 0.00080
        expected_max_sl = 1.08500 - atr * ATR_SL_MULTIPLIERS["M15"]
        assert result["stop_loss"] <= expected_max_sl

    def test_short_sl_atr_based(self, m15_calc):
        result = m15_calc.calculate("short", 1.08500, _short_context())
        atr = 0.00080
        expected_min_sl = 1.08500 + atr * ATR_SL_MULTIPLIERS["M15"]
        assert result["stop_loss"] >= expected_min_sl

    def test_sl_capped_at_max_atr_mult(self, m15_calc):
        context = _long_context(atr=0.00080)
        result = m15_calc.calculate("long", 1.08500, context)
        risk = 1.08500 - result["stop_loss"]
        assert risk <= 0.00080 * MAX_SL_ATR_MULT + 0.001

    def test_h1_sl_wider_than_m15(self, m15_calc, h1_calc):
        ctx = _long_context()
        m15_result = m15_calc.calculate("long", 1.08500, ctx)
        h1_result = h1_calc.calculate("long", 1.08500, ctx)
        m15_risk = 1.08500 - m15_result["stop_loss"]
        h1_risk = 1.08500 - h1_result["stop_loss"]
        assert h1_risk >= m15_risk

    def test_d1_sl_wider_than_m15(self, m15_calc, d1_calc):
        ctx = _long_context()
        m15_result = m15_calc.calculate("long", 1.08500, ctx)
        d1_result = d1_calc.calculate("long", 1.08500, ctx)
        m15_risk = 1.08500 - m15_result["stop_loss"]
        d1_risk = 1.08500 - d1_result["stop_loss"]
        assert d1_risk >= m15_risk


class TestMinRR:
    def test_m15_min_rr_1_5(self, m15_calc):
        ctx = _long_context()
        result = m15_calc.calculate("long", 1.08500, ctx)
        assert result["rr_ratio"] >= MIN_RR_BY_TF["M15"]

    def test_h1_min_rr_1_5(self, h1_calc):
        ctx = _long_context()
        result = h1_calc.calculate("long", 1.08500, ctx)
        assert result["rr_ratio"] >= MIN_RR_BY_TF["H1"]

    def test_short_min_rr(self, m15_calc):
        ctx = _short_context()
        result = m15_calc.calculate("short", 1.08500, ctx)
        assert result["rr_ratio"] >= MIN_RR_BY_TF["M15"]


class TestATRTakeProfit:
    def test_tp_levels_use_atr_multiples(self, m15_calc):
        ctx = _long_context()
        result = m15_calc.calculate("long", 1.08500, ctx)
        non_structure = [t for t in result["tp_levels"] if not t.get("structure")]
        assert len(non_structure) >= 3
        assert non_structure[0]["level"] == "TP1"
        assert non_structure[1]["level"] == "TP2"
        assert non_structure[2]["level"] == "TP3"

    def test_tp1_is_1_5_atr_for_m15(self, m15_calc):
        ctx = _long_context(atr=0.00100)
        result = m15_calc.calculate("long", 1.08500, ctx)
        non_structure = [t for t in result["tp_levels"] if not t.get("structure")]
        tp1_dist = non_structure[0]["price"] - 1.08500
        min_rr = MIN_RR_BY_TF["M15"]
        risk = 1.08500 - result["stop_loss"]
        expected = max(0.00100 * ATR_TP_MULTIPLIERS["M15"]["tp1"], risk * min_rr)
        assert tp1_dist == pytest.approx(expected, abs=0.00005)

    def test_tp3_is_furthest(self, m15_calc):
        ctx = _long_context()
        result = m15_calc.calculate("long", 1.08500, ctx)
        non_structure = [t for t in result["tp_levels"] if not t.get("structure")]
        assert non_structure[2]["price"] > non_structure[1]["price"]
        assert non_structure[1]["price"] > non_structure[0]["price"]

    def test_short_tps_below_entry(self, m15_calc):
        ctx = _short_context()
        result = m15_calc.calculate("short", 1.08500, ctx)
        non_structure = [t for t in result["tp_levels"] if not t.get("structure")]
        for tp in non_structure:
            assert tp["price"] < 1.08500


class TestStructureLevels:
    def test_structure_levels_included(self, m15_calc):
        ctx = _long_context()
        result = m15_calc.calculate("long", 1.08500, ctx)
        names = [t["level"] for t in result["tp_levels"]]
        assert "R2" in names
        assert "R3" in names

    def test_structure_levels_marked(self, m15_calc):
        ctx = _long_context()
        result = m15_calc.calculate("long", 1.08500, ctx)
        for tp in result["tp_levels"]:
            if tp["level"] in ("R2", "R3"):
                assert tp.get("structure") is True

    def test_wrong_side_structure_excluded(self, m15_calc):
        ctx = {"sl2": 1.08300, "r2": 1.08200, "atr": 0.00080}
        result = m15_calc.calculate("long", 1.08500, ctx)
        names = [t["level"] for t in result["tp_levels"]]
        assert "R2" not in names


class TestFallback:
    def test_no_atr_falls_back_to_structure(self, m15_calc):
        ctx = {"sl2": 1.08300, "r2": 1.08800}
        result = m15_calc.calculate("long", 1.08500, ctx)
        assert result["stop_loss"] < 1.08500
        assert result["take_profit"] > 1.08500

    def test_no_atr_min_rr_still_enforced(self, m15_calc):
        ctx = {"sl2": 1.08300}
        result = m15_calc.calculate("long", 1.08500, ctx)
        assert result["rr_ratio"] >= MIN_RR_BY_TF["M15"]


class TestTrailingConfig:
    def test_breakeven_trigger(self, m15_calc):
        result = m15_calc.calculate("long", 1.08500, _long_context())
        trail = result["trailing"]
        risk = 1.08500 - result["stop_loss"]
        assert trail["breakeven_trigger"] == pytest.approx(1.08500 + risk, abs=0.0001)

    def test_atr_trail_step(self, m15_calc):
        result = m15_calc.calculate("long", 1.08500, _long_context())
        trail = result["trailing"]
        assert trail["trail_step"] == "atr_half"

    def test_no_atr_trail_step(self, m15_calc):
        ctx = {"sl2": 1.08300, "atr": 0.0}
        result = m15_calc.calculate("long", 1.08500, ctx)
        trail = result["trailing"]
        assert trail["trail_step"] == "half_remaining"


class TestSpreadBuffer:
    def test_spread_widens_sl(self, m15_calc):
        no_spread = m15_calc.calculate("long", 1.08500, _long_context(), spread=0.0)
        with_spread = m15_calc.calculate(
            "long", 1.08500, _long_context(), spread=0.00020
        )
        assert with_spread["stop_loss"] <= no_spread["stop_loss"]


class TestRiskRewardFields:
    def test_fields_present(self, m15_calc):
        result = m15_calc.calculate("long", 1.08500, _long_context())
        assert result["risk_pips"] > 0
        assert result["reward_pips"] > 0
        assert result["reward_pips"] > result["risk_pips"]

    def test_rr_ratio_consistent(self, m15_calc):
        result = m15_calc.calculate("long", 1.08500, _long_context())
        computed_rr = result["reward_pips"] / result["risk_pips"]
        assert result["rr_ratio"] == pytest.approx(computed_rr, abs=0.01)


class TestJPYPairs:
    def test_jpy_atr_sl(self):
        calc = StopTargetCalculator(pip_size=0.01, timeframe="M15")
        ctx = {"sl2": 148.30, "r2": 148.80, "atr": 0.08}
        result = calc.calculate("long", 148.50, ctx)
        assert result["stop_loss"] < 148.50
        assert result["take_profit"] > 148.50
        assert result["rr_ratio"] >= 1.5


class TestTimeframeConfigs:
    def test_all_tfs_have_sl_mult(self):
        for tf in ["M5", "M15", "H1", "H4", "D1"]:
            assert tf in ATR_SL_MULTIPLIERS

    def test_all_tfs_have_tp_mults(self):
        for tf in ["M5", "M15", "H1", "H4", "D1"]:
            assert tf in ATR_TP_MULTIPLIERS
            for level in ("tp1", "tp2", "tp3"):
                assert level in ATR_TP_MULTIPLIERS[tf]

    def test_all_tfs_have_min_rr(self):
        for tf in ["M5", "M15", "H1", "H4", "D1"]:
            assert tf in MIN_RR_BY_TF

    def test_tp_mults_increase(self):
        for tf in ["M5", "M15", "H1", "H4", "D1"]:
            m = ATR_TP_MULTIPLIERS[tf]
            assert m["tp1"] < m["tp2"] < m["tp3"]
