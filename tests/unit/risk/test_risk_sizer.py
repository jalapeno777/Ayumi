"""Tests for risk_sizer: ConfidencePositionSizer, tier mapping, lot sizing."""

from __future__ import annotations

import pytest
from signal_engine.risk_sizer import (
    ConfidencePositionSizer,
    ConfidenceTier,
    parse_tiers,
)

# ── Default Tier Mapping ────────────────────────────────────────────


class TestDefaultTierMapping:
    def setup_method(self):
        self.sizer = ConfidencePositionSizer(account_size=10000.0)

    def test_tier5_highest_confidence(self):
        assert self.sizer.get_risk_pct(0.90) == 0.0150

    def test_tier4(self):
        assert self.sizer.get_risk_pct(0.75) == 0.0075

    def test_tier3(self):
        assert self.sizer.get_risk_pct(0.55) == 0.0050

    def test_tier2(self):
        assert self.sizer.get_risk_pct(0.40) == 0.0025

    def test_tier1(self):
        assert self.sizer.get_risk_pct(0.25) == 0.0010

    def test_confidence_at_zero(self):
        assert self.sizer.get_risk_pct(0.0) == 0.0010

    def test_confidence_at_one(self):
        # confidence=1.0 >= top tier max (0.85), returns top tier
        assert self.sizer.get_risk_pct(1.0) == 0.0150

    def test_confidence_below_range(self):
        assert self.sizer.get_risk_pct(-0.5) == 0.0010

    def test_tier_boundary_low(self):
        # 0.20 is the min of T1 — should return T1
        assert self.sizer.get_risk_pct(0.20) == 0.0010

    def test_tier_boundary_high(self):
        # 0.85 is min of T5
        assert self.sizer.get_risk_pct(0.85) == 0.0150


# ── Risk Amount ─────────────────────────────────────────────────────


class TestRiskAmount:
    def test_risk_amount_calculation(self):
        sizer = ConfidencePositionSizer(account_size=10000.0)
        assert sizer.get_risk_amount(0.90) == pytest.approx(150.0)

    def test_risk_amount_low_confidence(self):
        sizer = ConfidencePositionSizer(account_size=50000.0)
        assert sizer.get_risk_amount(0.25) == pytest.approx(50.0)


# ── Lot Size ────────────────────────────────────────────────────────


class TestLotSize:
    def test_lot_size_basic(self):
        sizer = ConfidencePositionSizer(account_size=10000.0)
        # risk_amount=150, stop=30 pips, pip_size=10 → 150/300=0.5
        assert sizer.get_lot_size(0.90, stop_pips=30, pip_size=10) == pytest.approx(0.5)

    def test_lot_size_zero_stop(self):
        sizer = ConfidencePositionSizer(account_size=10000.0)
        assert sizer.get_lot_size(0.90, stop_pips=0, pip_size=10) == 0.0


# ── Tier Labels ─────────────────────────────────────────────────────


class TestTierLabel:
    def test_label_mid_tier(self):
        sizer = ConfidencePositionSizer()
        label = sizer.get_tier_label(0.55)
        assert "50%" in label or "70%" in label

    def test_label_top(self):
        sizer = ConfidencePositionSizer()
        assert "85%+" in sizer.get_tier_label(1.0)

    def test_label_below_bottom(self):
        sizer = ConfidencePositionSizer()
        assert "<20%" in sizer.get_tier_label(0.0)


# ── Custom Tiers ────────────────────────────────────────────────────


class TestCustomTiers:
    def test_custom_tier_override(self):
        custom = [ConfidenceTier(0.50, 1.00, 0.02)]
        sizer = ConfidencePositionSizer(account_size=1000.0, tiers=custom)
        assert sizer.get_risk_pct(0.75) == 0.02

    def test_parse_tiers(self):
        json_str = "[[0.5, 0.8, 0.01], [0.8, 1.0, 0.02]]"
        tiers = parse_tiers(json_str)
        assert len(tiers) == 2
        assert tiers[0].risk_pct == 0.01
