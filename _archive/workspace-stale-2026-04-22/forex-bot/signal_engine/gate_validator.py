"""
Gate Validator — Hard requirements check before confluence scoring.

If ANY hard gate fails -> NO TRADE immediately.
Quality and reversal thresholds must also be met.

Gate outcomes (§6.4):
- All gates pass + quality >= 0.50 + reversal >= 0.30 -> proceed to confluence
- All gates pass + quality < 0.50 -> NO TRADE (formation too weak)
- All gates pass + reversal < 0.30 -> NO TRADE (continuation reset, not reversal)
- Any hard gate fails -> NO TRADE

Spec reference: docs/forex/signal_confidence_engine.md §6
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class GateOutcome(Enum):
    PASS = "pass"
    FAIL = "fail"
    SOFT_FAIL = "soft_fail"  # For soft gates like G4 — reduces quality but doesn't block


@dataclass
class GateResult:
    """Result of a single gate check."""
    gate_name: str
    outcome: GateOutcome
    reason: Optional[str] = None

    def __repr__(self) -> str:
        suffix = f" ({self.reason})" if self.reason else ""
        return f"GateResult({self.gate_name}: {self.outcome.value}{suffix})"


@dataclass
class GateValidationResult:
    """Complete result of all gate validations."""
    proceed_to_confluence: bool
    universal_gates: Dict[str, "GateResult"]
    pattern_specific_gates: Dict[str, "GateResult"]
    strategy_specific_gates: Dict[str, "GateResult"]
    fail_reason: Optional[str] = None

    @property
    def failed_gates(self) -> List[str]:
        """Return names of all failed gates."""
        failed = []
        for gate_dict in [
            self.universal_gates,
            self.pattern_specific_gates,
            self.strategy_specific_gates,
        ]:
            for name, result in gate_dict.items():
                if result.outcome == GateOutcome.FAIL:
                    failed.append(name)
        return failed

    @property
    def soft_failed_gates(self) -> List[str]:
        """Return names of soft-failed gates."""
        soft = []
        for gate_dict in [
            self.universal_gates,
            self.pattern_specific_gates,
            self.strategy_specific_gates,
        ]:
            for name, result in gate_dict.items():
                if result.outcome == GateOutcome.SOFT_FAIL:
                    soft.append(name)
        return soft

    def summary(self) -> str:
        """Human-readable summary of gate validation."""
        if self.proceed_to_confluence:
            return "ALL GATES PASS -> proceed to confluence scoring"

        parts = []
        if self.failed_gates:
            parts.append(f"FAILED: {', '.join(self.failed_gates)}")
        if self.soft_failed_gates:
            parts.append(f"SOFT FAIL: {', '.join(self.soft_failed_gates)}")
        if self.fail_reason:
            parts.append(self.fail_reason)
        return " | ".join(parts) if parts else "NO TRADE"

    def to_dict(self) -> dict:
        return {
            "proceed_to_confluence": self.proceed_to_confluence,
            "fail_reason": self.fail_reason,
            "universal_gates": {
                k: {"outcome": v.outcome.value, "reason": v.reason}
                for k, v in self.universal_gates.items()
            },
            "pattern_specific_gates": {
                k: {"outcome": v.outcome.value, "reason": v.reason}
                for k, v in self.pattern_specific_gates.items()
            },
            "strategy_specific_gates": {
                k: {"outcome": v.outcome.value, "reason": v.reason}
                for k, v in self.strategy_specific_gates.items()
            },
        }


class GateValidator:
    """
    Validate all gate requirements before proceeding to confluence scoring.

    Universal gates (§6.1):
        - pattern_valid: passes structural detection rules
        - pattern_at_level: formation at a counted level (G2)
        - rr_minimum: natural target >= 3:1 from entry to stop
        - no_major_event: no high-impact event within 2 hours of entry
        - levels_complete: 3+ levels counted on trading TF (G0)
        - quality_threshold: quality_score >= 0.50 (Q0)
        - reversal_threshold: reversal_score >= 0.30 (Q1) — skip for continuation

    M/W-specific gates (§6.2):
        - g1_structure, g2_level_context, g3_first_peak_rejection,
          g4_middle_peak_ema (SOFT), g5_post_peak_confirm, g6_ema_break_retest

    Strategy-specific gates (§6.3):
        - asia_range_qualified, asia_range_intact, asia_compressed,
          uk_no_sweep, ny_time_window, pre_us_exit, flat_ema_no_trade
    """

    def __init__(self, min_rr: float = 3.0):
        self.min_rr = min_rr

    def validate(
        self,
        formation: Any,
        entry_price: float,
        stop_loss: float,
        target_price: float,
        levels_complete: bool = False,
        quality_score: float = 0.0,
        reversal_score: float = 0.0,
        no_major_event: bool = True,
        strategy_gates: Optional[Dict[str, bool]] = None,
        is_continuation: bool = False,
    ) -> GateValidationResult:
        """
        Run all gate validations.

        Args:
            formation: A pattern object with `gates_passed`, `at_level`,
                       and optionally `gate_results` attributes.
            entry_price: planned entry price
            stop_loss: planned stop loss
            target_price: planned target
            levels_complete: whether 3+ levels are counted on trading TF (G0)
            quality_score: formation quality score (must be >= 0.50)
            reversal_score: formation reversal score (must be >= 0.30 for reversals)
            no_major_event: no high-impact event within 2 hours
            strategy_gates: optional dict of strategy-specific gate name -> pass/fail
            is_continuation: if True, skip reversal_threshold gate (continuation reset)

        Returns:
            GateValidationResult with proceed_to_confluence flag.
        """
        universal: Dict[str, GateResult] = {}

        # pattern_valid (§6.1)
        gates_passed = getattr(formation, "gates_passed", False)
        universal["pattern_valid"] = GateResult(
            "pattern_valid",
            GateOutcome.PASS if gates_passed else GateOutcome.FAIL,
            "Formation passed all structural gates" if gates_passed else "Formation failed structural gates",
        )

        # pattern_at_level (G2, §6.1)
        at_level = getattr(formation, "at_level", None)
        universal["pattern_at_level"] = GateResult(
            "pattern_at_level",
            GateOutcome.PASS if at_level else GateOutcome.FAIL,
            f"Formation at level: {at_level}" if at_level else "No level context for formation",
        )

        # levels_complete (G0, §6.1)
        universal["levels_complete"] = GateResult(
            "levels_complete",
            GateOutcome.PASS if levels_complete else GateOutcome.FAIL,
            "3+ levels counted on trading TF" if levels_complete else "Fewer than 3 levels counted",
        )

        # quality_threshold (Q0, §5.1)
        universal["quality_threshold"] = GateResult(
            "quality_threshold",
            GateOutcome.PASS if quality_score >= 0.50 else GateOutcome.FAIL,
            f"Quality score: {quality_score:.4f}" if quality_score >= 0.50 else f"Quality score too low: {quality_score:.4f} < 0.50",
        )

        # reversal_threshold (Q1, §5.7) — skip for continuation entries
        if is_continuation:
            universal["reversal_threshold"] = GateResult(
                "reversal_threshold",
                GateOutcome.PASS,
                "Skipped (continuation entry)",
            )
        else:
            universal["reversal_threshold"] = GateResult(
                "reversal_threshold",
                GateOutcome.PASS if reversal_score >= 0.30 else GateOutcome.FAIL,
                f"Reversal score: {reversal_score:.4f}" if reversal_score >= 0.30 else f"Reversal score too low: {reversal_score:.4f} < 0.30 (continuation reset, not reversal)",
            )

        # no_major_event (§6.1)
        universal["no_major_event"] = GateResult(
            "no_major_event",
            GateOutcome.PASS if no_major_event else GateOutcome.FAIL,
            "No high-impact event within 2h" if no_major_event else "High-impact event within 2h of entry",
        )

        # rr_minimum (§6.1)
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance > 0:
            rr = abs(target_price - entry_price) / sl_distance
        else:
            rr = 0.0

        universal["rr_minimum"] = GateResult(
            "rr_minimum",
            GateOutcome.PASS if rr >= self.min_rr else GateOutcome.FAIL,
            f"R:R = {rr:.2f}:1" if rr >= self.min_rr else f"R:R too low: {rr:.2f}:1 < {self.min_rr}:1",
        )

        # Build pattern-specific gates from formation
        pattern_gates: Dict[str, GateResult] = {}
        if hasattr(formation, "gate_results") and formation.gate_results:
            gate_descriptions = {
                "G0": "3 completed levels prerequisite",
                "G1": "Two swing extremes with swing between (symmetry <= 1.5%)",
                "G2": "Formation at a counted level",
                "G3": "First peak shows rejection characteristics",
                "G4": "Middle peak proximity to 50 EMA (SOFT GATE)",
                "G5": "Lower high / higher low after second peak",
                "G6": "50 EMA broken AND retested",
            }
            for gate_name, passed in formation.gate_results.items():
                desc = gate_descriptions.get(gate_name, gate_name)
                # G4 is a soft gate
                if gate_name == "G4":
                    outcome = GateOutcome.SOFT_FAIL if not passed else GateOutcome.PASS
                else:
                    outcome = GateOutcome.PASS if passed else GateOutcome.FAIL
                pattern_gates[gate_name] = GateResult(
                    gate_name, outcome, desc
                )

        # Build strategy-specific gates
        strategy_gate_results: Dict[str, GateResult] = {}
        if strategy_gates:
            for gate_name, passed in strategy_gates.items():
                strategy_gate_results[gate_name] = GateResult(
                    gate_name,
                    GateOutcome.PASS if passed else GateOutcome.FAIL,
                )

        # Determine overall result
        # Only HARD fails block — soft fails don't
        hard_failures = [
            name for name, result in universal.items()
            if result.outcome == GateOutcome.FAIL
        ]
        hard_pattern_failures = [
            name for name, result in pattern_gates.items()
            if result.outcome == GateOutcome.FAIL
        ]
        hard_strategy_failures = [
            name for name, result in strategy_gate_results.items()
            if result.outcome == GateOutcome.FAIL
        ]

        all_hard_failures = hard_failures + hard_pattern_failures + hard_strategy_failures
        all_pass = len(all_hard_failures) == 0

        # Build fail reason
        fail_reason = None
        if not all_pass:
            if hard_failures:
                fail_reason = f"Universal gate(s) failed: {', '.join(hard_failures)}"
            elif hard_pattern_failures:
                fail_reason = f"Pattern gate(s) failed: {', '.join(hard_pattern_failures)}"
            elif hard_strategy_failures:
                fail_reason = f"Strategy gate(s) failed: {', '.join(hard_strategy_failures)}"

        result = GateValidationResult(
            proceed_to_confluence=all_pass,
            universal_gates=universal,
            pattern_specific_gates=pattern_gates,
            strategy_specific_gates=strategy_gate_results,
            fail_reason=fail_reason,
        )

        logger.info("Gate validation: %s", result.summary())
        return result

    def validate_quick(
        self,
        gates_passed: bool,
        at_level: bool,
        quality_score: float,
        reversal_score: float,
        rr: float,
        levels_complete: bool = False,
        is_continuation: bool = False,
    ) -> bool:
        """
        Quick boolean check without full result object.
        Useful for filtering in loops.
        """
        if not gates_passed:
            return False
        if not at_level:
            return False
        if not levels_complete:
            return False
        if quality_score < 0.50:
            return False
        if not is_continuation and reversal_score < 0.30:
            return False
        if rr < self.min_rr:
            return False
        return True
