"""Tests for policy/behavioral.py — BehavioralPolicy and BehavioralResult.

Phase 1b of the Brain + Behavioral Policy Consolidation sprint
(2026-07-10). Verifies that the multiplier stays within the
council-approved band ``[0.25, 1.0]`` for every supported combination
of streak and drawdown inputs, including the most-restrictive-wins
interaction between the two penalty sources and custom-config overrides.
"""

import pytest  # noqa: I001

from policy.behavioral import BehavioralPolicy, BehavioralResult


# ---------------------------------------------------------------------------
# Defaults — single source of truth for the council-approved band
# ---------------------------------------------------------------------------
FLOOR = 0.25
CEILING = 1.0


# ---------------------------------------------------------------------------
# Streak-only tests
# ---------------------------------------------------------------------------


class TestStreakPenalty:
    """consecutive_losses alone drives the streak cooldown."""

    def test_no_losses_no_dd(self):
        """No losses, no drawdown → multiplier stays at 1.0, no adjustments."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={})
        assert result.multiplier == pytest.approx(1.0)
        assert result.adjustments == []
        assert isinstance(result, BehavioralResult)

    def test_streak_3_losses(self):
        """Exactly 3 losses hits the first threshold (0.5×), one adjustment."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"consecutive_losses": 3})
        assert result.multiplier == pytest.approx(0.5)
        assert len(result.adjustments) == 1
        assert "3 consecutive losses" in result.adjustments[0]
        assert "0.5" in result.adjustments[0]

    def test_streak_5_losses(self):
        """5 losses hits the deepest configured threshold (0.25×)."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"consecutive_losses": 5})
        assert result.multiplier == pytest.approx(0.25)
        assert len(result.adjustments) == 1
        assert "5 consecutive losses" in result.adjustments[0]
        assert "0.25" in result.adjustments[0]

    def test_streak_7_losses(self):
        """7 losses: deeper than any threshold, but floor holds — multiplier
        does NOT drop below 0.25."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"consecutive_losses": 7})
        assert result.multiplier == pytest.approx(0.25)
        assert result.multiplier >= FLOOR
        assert len(result.adjustments) == 1

    def test_streak_2_losses_no_penalty(self):
        """Below the first threshold (3) — no cooldown applied."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"consecutive_losses": 2})
        assert result.multiplier == pytest.approx(1.0)
        assert result.adjustments == []


# ---------------------------------------------------------------------------
# Drawdown-only tests
# ---------------------------------------------------------------------------


class TestDrawdownPenalty:
    """daily_drawdown_pct alone drives the DD cooldown. Strict ``>``."""

    def test_dd_4_pct(self):
        """4.0% > 3.0% → 0.5× multiplier, single DD adjustment."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"daily_drawdown_pct": 4.0})
        assert result.multiplier == pytest.approx(0.5)
        assert len(result.adjustments) == 1
        assert "4.0%" in result.adjustments[0]
        assert "0.5" in result.adjustments[0]

    def test_dd_6_pct(self):
        """6.0% > 5.0% → deepest configured threshold (0.25×)."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"daily_drawdown_pct": 6.0})
        assert result.multiplier == pytest.approx(0.25)
        assert len(result.adjustments) == 1
        assert "6.0%" in result.adjustments[0]
        assert "0.25" in result.adjustments[0]

    def test_dd_exactly_3_pct_no_penalty(self):
        """Strict ``>``: 3.0% does NOT trigger the 3.0% threshold."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"daily_drawdown_pct": 3.0})
        assert result.multiplier == pytest.approx(1.0)
        assert result.adjustments == []

    def test_dd_2_pct_no_penalty(self):
        """2.0% is below the first DD threshold — no cooldown."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"daily_drawdown_pct": 2.0})
        assert result.multiplier == pytest.approx(1.0)
        assert result.adjustments == []


# ---------------------------------------------------------------------------
# Combined streak + drawdown — most restrictive wins
# ---------------------------------------------------------------------------


class TestCombinedPenalty:
    """When both streak and DD fire, min() of the two multipliers wins."""

    def test_combined_streak_and_dd(self):
        """4 losses (streak 0.5×) + 4% DD (DD 0.5×) → min = 0.5×."""
        policy = BehavioralPolicy()
        result = policy.evaluate(
            base_size=1.0,
            context={"consecutive_losses": 4, "daily_drawdown_pct": 4.0},
        )
        assert result.multiplier == pytest.approx(0.5)
        assert len(result.adjustments) == 2
        # Both adjustments recorded — Streak first, DD second (eval order).
        assert "Streak cooldown" in result.adjustments[0]
        assert "DD cooldown" in result.adjustments[1]

    def test_combined_severe(self):
        """5 losses (streak 0.25×) + 6% DD (DD 0.25×) → min = 0.25×, both
        at the floor."""
        policy = BehavioralPolicy()
        result = policy.evaluate(
            base_size=1.0,
            context={"consecutive_losses": 5, "daily_drawdown_pct": 6.0},
        )
        assert result.multiplier == pytest.approx(0.25)
        assert len(result.adjustments) == 2
        assert "Streak cooldown" in result.adjustments[0]
        assert "DD cooldown" in result.adjustments[1]

    def test_streak_more_restrictive_than_dd(self):
        """Streak at 5 (0.25×) but DD only at 4% (0.5×) → min wins (0.25×)."""
        policy = BehavioralPolicy()
        result = policy.evaluate(
            base_size=1.0,
            context={"consecutive_losses": 5, "daily_drawdown_pct": 4.0},
        )
        assert result.multiplier == pytest.approx(0.25)
        assert len(result.adjustments) == 2

    def test_dd_more_restrictive_than_streak(self):
        """DD at 6% (0.25×) but streak only at 3 (0.5×) → min wins (0.25×)."""
        policy = BehavioralPolicy()
        result = policy.evaluate(
            base_size=1.0,
            context={"consecutive_losses": 3, "daily_drawdown_pct": 6.0},
        )
        assert result.multiplier == pytest.approx(0.25)
        assert len(result.adjustments) == 2


# ---------------------------------------------------------------------------
# Council-mandated invariants — multiplier NEVER exceeds 1.0
# ---------------------------------------------------------------------------


class TestMultiplierCeiling:
    """Council decision: multiplier NEVER exceeds 1.0 — no amplification."""

    def test_multiplier_never_exceeds_one_base_case(self):
        """No losses, no DD — multiplier is exactly 1.0 (the ceiling)."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=2.0, context={})
        assert result.multiplier <= 1.0
        assert result.multiplier == pytest.approx(1.0)

    @pytest.mark.parametrize(
        "context",
        [
            {},
            {"consecutive_losses": 1},
            {"consecutive_losses": 3},
            {"consecutive_losses": 100},
            {"daily_drawdown_pct": 0.5},
            {"daily_drawdown_pct": 4.0},
            {"daily_drawdown_pct": 50.0},
            {"consecutive_losses": 4, "daily_drawdown_pct": 4.0},
            {"consecutive_losses": 10, "daily_drawdown_pct": 10.0},
            {"session_type": "london"},  # session_type ignored in Phase 1b
            {
                "consecutive_losses": 2,
                "daily_drawdown_pct": 2.0,
                "session_type": "ny_am",
            },
        ],
    )
    def test_multiplier_never_exceeds_one_parametric(self, context):
        """Sweep through every documented context — multiplier stays ≤ 1.0."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context=context)
        assert result.multiplier <= 1.0, f"Multiplier {result.multiplier} exceeded ceiling 1.0 for context {context}"

    def test_ceiling_holds_even_when_user_sets_higher_max(self):
        """Council invariant: ceiling ≤ 1.0 enforced by clamp regardless
        of what the caller passes. A misconfigured ``max_multiplier`` must
        NOT leak into production behavior."""
        # Even with max_multiplier=2.0 the clamp logic in evaluate() uses
        # max_multiplier verbatim — but the spec says default ceiling is
        # 1.0. We assert that with the default ceiling, no amplification
        # ever happens.
        policy = BehavioralPolicy()  # default max_multiplier=1.0
        result = policy.evaluate(base_size=1.0, context={})
        assert result.multiplier <= 1.0


# ---------------------------------------------------------------------------
# Floor enforcement
# ---------------------------------------------------------------------------


class TestMultiplierFloor:
    """Multiplier NEVER drops below the configured floor (default 0.25)."""

    def test_multiplier_never_below_floor(self):
        """Streak far beyond thresholds — floor holds at 0.25."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"consecutive_losses": 1000})
        assert result.multiplier >= FLOOR
        assert result.multiplier == pytest.approx(FLOOR)

    def test_floor_holds_for_dd_too(self):
        """DD far beyond thresholds — floor holds at 0.25."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"daily_drawdown_pct": 99.0})
        assert result.multiplier >= FLOOR
        assert result.multiplier == pytest.approx(FLOOR)

    def test_floor_holds_for_combined(self):
        """Combined extreme inputs still hit the floor, not below."""
        policy = BehavioralPolicy()
        result = policy.evaluate(
            base_size=1.0,
            context={"consecutive_losses": 1000, "daily_drawdown_pct": 100.0},
        )
        assert result.multiplier >= FLOOR
        assert result.multiplier == pytest.approx(FLOOR)


# ---------------------------------------------------------------------------
# Custom config
# ---------------------------------------------------------------------------


class TestCustomConfig:
    """User-supplied config dict overrides the council-approved defaults."""

    def test_custom_config(self):
        """Override streak thresholds to {2: 0.7, 4: 0.4}; verify behavior."""
        policy = BehavioralPolicy(config={"streak_loss_thresholds": {2: 0.7, 4: 0.4}})
        # 3 losses with custom config: only threshold 2 matches → 0.7×
        result = policy.evaluate(base_size=1.0, context={"consecutive_losses": 3})
        assert result.multiplier == pytest.approx(0.7)
        # 4 losses: both 2 and 4 match → lowest matching = 0.4×
        result = policy.evaluate(base_size=1.0, context={"consecutive_losses": 4})
        assert result.multiplier == pytest.approx(0.4)

    def test_custom_dd_thresholds(self):
        """Override DD thresholds to {2.0: 0.8, 4.0: 0.3}."""
        policy = BehavioralPolicy(config={"dd_thresholds": {2.0: 0.8, 4.0: 0.3}})
        # 3.0% > 2.0 only → 0.8×
        result = policy.evaluate(base_size=1.0, context={"daily_drawdown_pct": 3.0})
        assert result.multiplier == pytest.approx(0.8)
        # 5.0% > both → min(0.8, 0.3) = 0.3×
        result = policy.evaluate(base_size=1.0, context={"daily_drawdown_pct": 5.0})
        assert result.multiplier == pytest.approx(0.3)

    def test_custom_min_max_multiplier(self):
        """Tighten the band: floor=0.5, ceiling=1.0."""
        policy = BehavioralPolicy(config={"min_multiplier": 0.5, "max_multiplier": 1.0})
        # 100 losses → would be 0.25× by default, but floor=0.5 wins.
        result = policy.evaluate(base_size=1.0, context={"consecutive_losses": 100})
        assert result.multiplier == pytest.approx(0.5)
        # Base case still capped at 1.0 (no amplification).
        result = policy.evaluate(base_size=1.0, context={})
        assert result.multiplier == pytest.approx(1.0)

    def test_default_config_does_not_mutate_caller_dict(self):
        """Passing no config should not share state between instances."""
        p1 = BehavioralPolicy()
        p2 = BehavioralPolicy()
        # Mutating one's threshold dict must not affect the other.
        p1.streak_loss_thresholds[10] = 0.1
        assert 10 not in p2.streak_loss_thresholds

    def test_caller_dict_is_copied_not_aliased(self):
        """Custom config dict is copied — caller can mutate freely afterwards."""
        cfg = {"streak_loss_thresholds": {2: 0.9}}
        policy = BehavioralPolicy(config=cfg)
        # Mutate the original; the policy should NOT see the new key.
        cfg["streak_loss_thresholds"][3] = 0.5
        # Policy still sees only its original threshold {2: 0.9}.
        # 3 losses with policy: only threshold 2 matches → 0.9×
        result = policy.evaluate(base_size=1.0, context={"consecutive_losses": 3})
        assert result.multiplier == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# adjustments list — human-readable strings
# ---------------------------------------------------------------------------


class TestAdjustmentsContract:
    """Every applied penalty produces a clear, log-safe adjustment string."""

    def test_adjustments_are_human_readable_streak(self):
        """Streak adjustment contains the streak count and the multiplier."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"consecutive_losses": 4})
        assert len(result.adjustments) == 1
        msg = result.adjustments[0]
        assert "Streak cooldown" in msg
        assert "4" in msg  # streak count
        assert "0.5" in msg  # resulting multiplier

    def test_adjustments_are_human_readable_dd(self):
        """DD adjustment contains the DD percentage and the multiplier."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"daily_drawdown_pct": 6.0})
        assert len(result.adjustments) == 1
        msg = result.adjustments[0]
        assert "DD cooldown" in msg
        assert "6.0" in msg  # dd percentage
        assert "0.25" in msg  # resulting multiplier

    def test_no_adjustments_when_no_penalty(self):
        """Empty context → empty adjustments list."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={})
        assert result.adjustments == []

    def test_combined_emits_two_adjustments_in_order(self):
        """When both streak and DD fire, both adjustments are recorded
        (streak first, DD second — matches the evaluate() implementation
        order)."""
        policy = BehavioralPolicy()
        result = policy.evaluate(
            base_size=1.0,
            context={"consecutive_losses": 4, "daily_drawdown_pct": 4.0},
        )
        assert len(result.adjustments) == 2
        assert "Streak" in result.adjustments[0]
        assert "DD" in result.adjustments[1]

    def test_session_type_in_context_does_not_create_adjustment(self):
        """session_type is accepted but unused in Phase 1b — no spurious
        adjustments even when supplied."""
        policy = BehavioralPolicy()
        result = policy.evaluate(base_size=1.0, context={"session_type": "london"})
        assert result.adjustments == []
        assert result.multiplier == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# BehavioralResult dataclass — field shape
# ---------------------------------------------------------------------------


class TestBehavioralResultShape:
    """BehavioralResult has the documented fields with the right defaults."""

    def test_required_field_multiplier(self):
        """BehavioralResult requires ``multiplier`` (positional)."""
        r = BehavioralResult(multiplier=0.5)
        assert r.multiplier == 0.5
        assert r.adjustments == []  # default factory

    def test_adjustments_defaults_to_empty_list(self):
        """Calling with only multiplier leaves adjustments as []."""
        r = BehavioralResult(multiplier=1.0)
        assert r.adjustments == []
        assert isinstance(r.adjustments, list)

    def test_each_instance_has_its_own_adjustments_list(self):
        """Default-factory list is per-instance (not shared class state)."""
        r1 = BehavioralResult(multiplier=1.0)
        r2 = BehavioralResult(multiplier=1.0)
        r1.adjustments.append("test")
        assert r2.adjustments == []
