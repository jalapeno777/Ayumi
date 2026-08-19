"""Tests for core/conviction.py — ConvictionVector and KillCriterion.

Phase 1a of the Brain + Behavioral Policy Consolidation sprint
(2026-07-10). Phase 1b/1c will consume these types, so we cover the
clamping, weighted aggregate, custom-weights override, and string
serialization contracts explicitly here.
"""

import pytest

from core.conviction import ConvictionVector, KillCriterion


# ---------------------------------------------------------------------------
# ConvictionVector — clamping
# ---------------------------------------------------------------------------


class TestConvictionVectorClamping:
    """Values outside [0.0, 1.0] are clamped on construction."""

    def test_values_above_one_are_clamped_down(self):
        """Each component above 1.0 clamps to exactly 1.0."""
        cv = ConvictionVector(
            strategy_score=1.5,
            confluence_score=2.0,
            regime_fit=10.0,
            freshness=1.0001,
        )
        assert cv.strategy_score == 1.0
        assert cv.confluence_score == 1.0
        assert cv.regime_fit == 1.0
        assert cv.freshness == 1.0

    def test_values_below_zero_are_clamped_up(self):
        """Each component below 0.0 clamps to exactly 0.0."""
        cv = ConvictionVector(
            strategy_score=-0.5,
            confluence_score=-1.0,
            regime_fit=-100.0,
            freshness=-0.0001,
        )
        assert cv.strategy_score == 0.0
        assert cv.confluence_score == 0.0
        assert cv.regime_fit == 0.0
        assert cv.freshness == 0.0

    def test_values_in_range_preserved(self):
        """Values already in [0.0, 1.0] are stored unchanged."""
        cv = ConvictionVector(
            strategy_score=0.2,
            confluence_score=0.4,
            regime_fit=0.6,
            freshness=0.8,
        )
        assert cv.strategy_score == 0.2
        assert cv.confluence_score == 0.4
        assert cv.regime_fit == 0.6
        assert cv.freshness == 0.8

    def test_boundary_values_exact(self):
        """Exact 0.0 and 1.0 stay as 0.0 and 1.0 (boundary inclusive)."""
        cv = ConvictionVector(
            strategy_score=0.0,
            confluence_score=1.0,
            regime_fit=0.0,
            freshness=1.0,
        )
        assert cv.strategy_score == 0.0
        assert cv.confluence_score == 1.0
        assert cv.regime_fit == 0.0
        assert cv.freshness == 1.0

    def test_mixed_overflow_and_underflow(self):
        """Some components over, some under — each is clamped independently."""
        cv = ConvictionVector(
            strategy_score=5.0,
            confluence_score=-5.0,
            regime_fit=0.5,
            freshness=2.0,
        )
        assert cv.strategy_score == 1.0
        assert cv.confluence_score == 0.0
        assert cv.regime_fit == 0.5
        assert cv.freshness == 1.0


# ---------------------------------------------------------------------------
# ConvictionVector.final_score — weighted aggregate
# ---------------------------------------------------------------------------


class TestConvictionVectorFinalScore:
    """final_score is the weighted aggregate of the clamped components."""

    def test_known_values_match_weighted_sum(self):
        """Verify the weighted aggregate with explicit known values.

        strategy_score = 0.8 -> 0.8 * 0.40 = 0.32
        confluence_score = 0.6 -> 0.6 * 0.25 = 0.15
        regime_fit = 0.4 -> 0.4 * 0.25 = 0.10
        freshness = 0.2 -> 0.2 * 0.10 = 0.02

        Sum = 0.32 + 0.15 + 0.10 + 0.02 = 0.59
        """
        cv = ConvictionVector(
            strategy_score=0.8,
            confluence_score=0.6,
            regime_fit=0.4,
            freshness=0.2,
        )
        assert cv.final_score == pytest.approx(0.59)

    def test_all_zeros_final_score_is_zero(self):
        """When every component is 0.0, the aggregate is exactly 0.0."""
        cv = ConvictionVector(
            strategy_score=0.0,
            confluence_score=0.0,
            regime_fit=0.0,
            freshness=0.0,
        )
        assert cv.final_score == pytest.approx(0.0)

    def test_all_ones_final_score_is_one(self):
        """When every component is 1.0, the aggregate equals the weight sum.

        With default weights summing to 1.0, all-ones gives 1.0.
        """
        cv = ConvictionVector(
            strategy_score=1.0,
            confluence_score=1.0,
            regime_fit=1.0,
            freshness=1.0,
        )
        assert cv.final_score == pytest.approx(1.0)

    def test_final_score_uses_clamped_values(self):
        """Inputs above 1.0 are clamped before aggregation.

        All ones → 1.0 * (0.40 + 0.25 + 0.25 + 0.10) = 1.0.
        """
        cv = ConvictionVector(
            strategy_score=5.0,
            confluence_score=5.0,
            regime_fit=5.0,
            freshness=5.0,
        )
        assert cv.final_score == pytest.approx(1.0)

    def test_weights_dict_default_values(self):
        """The class-level WEIGHTS dict has the documented defaults."""
        assert ConvictionVector.WEIGHTS == {
            "strategy_score": 0.40,
            "confluence_score": 0.25,
            "regime_fit": 0.25,
            "freshness": 0.10,
        }

    def test_weights_sum_to_one(self):
        """Default weights sum to 1.0 so final_score stays in [0, 1]."""
        assert sum(ConvictionVector.WEIGHTS.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# ConvictionVector — custom weights override
# ---------------------------------------------------------------------------


class TestConvictionVectorCustomWeights:
    """Override the class-level WEIGHTS dict and confirm the aggregate changes."""

    def test_custom_weights_change_final_score(self):
        """Re-weighting strategy_score from 0.40 to 1.0 (others 0.0)
        makes final_score == strategy_score exactly.

        With all weights zeroed except strategy_score (1.0),
        final_score = strategy_score * 1.0 + 0 + 0 + 0 = strategy_score.
        """
        # Save and restore the class dict so we don't pollute other tests.
        original = ConvictionVector.WEIGHTS
        try:
            ConvictionVector.WEIGHTS = {
                "strategy_score": 1.0,
                "confluence_score": 0.0,
                "regime_fit": 0.0,
                "freshness": 0.0,
            }
            cv = ConvictionVector(
                strategy_score=0.7,
                confluence_score=0.9,
                regime_fit=0.9,
                freshness=0.9,
            )
            assert cv.final_score == pytest.approx(0.7)
        finally:
            ConvictionVector.WEIGHTS = original

    def test_equal_weights_give_simple_mean(self):
        """With equal weights (0.25 each), final_score is the arithmetic mean
        of the four components.
        """
        original = ConvictionVector.WEIGHTS
        try:
            ConvictionVector.WEIGHTS = {
                "strategy_score": 0.25,
                "confluence_score": 0.25,
                "regime_fit": 0.25,
                "freshness": 0.25,
            }
            cv = ConvictionVector(
                strategy_score=0.8,
                confluence_score=0.4,
                regime_fit=0.2,
                freshness=0.0,
            )
            # mean of (0.8, 0.4, 0.2, 0.0) = 1.4 / 4 = 0.35
            assert cv.final_score == pytest.approx(0.35)
        finally:
            ConvictionVector.WEIGHTS = original


# ---------------------------------------------------------------------------
# KillCriterion — __str__ serialization
# ---------------------------------------------------------------------------


class TestKillCriterionStr:
    """Verify the PASS / FAIL string format produced by KillCriterion.__str__."""

    def test_str_pass_format(self):
        """triggered=False → 'PASS' status, 4-decimal value/threshold, evidence."""
        kc = KillCriterion(
            name="spread",
            triggered=False,
            value=0.00012,
            threshold=0.00020,
            evidence="EURUSD 0.12 pips within 0.20 limit",
        )
        rendered = str(kc)
        assert "spread" in rendered
        assert "PASS" in rendered
        assert "value=0.0001" in rendered  # 0.00012 rounds to 4dp = 0.0001
        assert "threshold=0.0002" in rendered
        assert "EURUSD 0.12 pips within 0.20 limit" in rendered
        assert "FAIL" not in rendered

    def test_str_fail_format(self):
        """triggered=True → 'FAIL' status, same shape otherwise."""
        kc = KillCriterion(
            name="adx_range",
            triggered=True,
            value=12.3456,
            threshold=18.0,
            evidence="ADX 12.35 below regime threshold 18.00",
        )
        rendered = str(kc)
        assert "adx_range" in rendered
        assert "FAIL" in rendered
        assert "value=12.3456" in rendered
        assert "threshold=18.0000" in rendered
        assert "ADX 12.35 below regime threshold 18.00" in rendered
        assert "PASS" not in rendered

    def test_str_exact_value_passthrough(self):
        """4-decimal precision: integer-valued floats render with .0000 suffix."""
        kc = KillCriterion(
            name="session_window",
            triggered=False,
            value=5.0,
            threshold=10.0,
            evidence="outside london-ny overlap",
        )
        rendered = str(kc)
        assert "value=5.0000" in rendered
        assert "threshold=10.0000" in rendered
        assert "PASS" in rendered

    def test_str_negative_value_rendered(self):
        """Negative values still format with 4 decimals."""
        kc = KillCriterion(
            name="delta",
            triggered=True,
            value=-0.5,
            threshold=0.0,
            evidence="negative delta — momentum lost",
        )
        rendered = str(kc)
        assert "value=-0.5000" in rendered
        assert "threshold=0.0000" in rendered
        assert "FAIL" in rendered


# ---------------------------------------------------------------------------
# KillCriterion — field accessibility
# ---------------------------------------------------------------------------


class TestKillCriterionFields:
    """Verify every field is stored and retrievable."""

    def test_all_fields_accessible(self):
        """All five fields round-trip through the dataclass."""
        kc = KillCriterion(
            name="spread",
            triggered=True,
            value=0.00025,
            threshold=0.00020,
            evidence="spread widened during rollover",
        )
        assert kc.name == "spread"
        assert kc.triggered is True
        assert kc.value == 0.00025
        assert kc.threshold == 0.00020
        assert kc.evidence == "spread widened during rollover"

    def test_default_construction_with_only_required_args(self):
        """All fields are required — building without them raises TypeError."""
        # No defaults are defined; every field is mandatory.
        with pytest.raises(TypeError):
            KillCriterion()  # type: ignore[call-arg]

    def test_triggered_bool_coercion_not_applied(self):
        """triggered stores the value as-given (no implicit bool conversion)."""
        kc = KillCriterion(
            name="x", triggered=False, value=0.0, threshold=0.0, evidence="ok"
        )
        assert isinstance(kc.triggered, bool)
        assert kc.triggered is False
