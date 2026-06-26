"""Tests for GateValidator: hard gates and quality threshold."""

from __future__ import annotations


from signal_engine.gate_validator import GateValidator
from signal_engine.data_types import (
    HTFState,
    HTFPhase,
    Level,
    LevelType,
    SessionState,
    Signal,
)


class TestGateValidator:
    def setup_method(self):
        self.validator = GateValidator(quality_threshold=0.6)

    def _make_candidate(
        self,
        direction: str = "long",
        symbol: str = "EURUSD",
        confidence: float = 0.8,
        pattern_type: str = "W",
        key_levels: dict | None = None,
    ) -> dict:
        return {
            "direction": direction,
            "symbol": symbol,
            "confidence": confidence,
            "pattern_type": pattern_type,
            "key_levels": key_levels or {},
        }

    # ── G1: Symmetry ───────────────────────────────────────────────

    def test_g1_passes_no_mw_levels(self):
        """Non-M/W patterns (no SH/SL levels) should pass G1."""
        result = self.validator.validate(self._make_candidate())
        assert result.gate_details["G1_symmetry"] is True

    def test_g1_passes_good_symmetry(self):
        """Good symmetry should pass."""
        # Perfectly symmetric M: SH1=SH2 at top, SL1=SL2 at bottom
        levels = {
            "SH1": 1.1000,
            "SH2": 1.1000,
            "SL1": 1.0950,
            "SL2": 1.0950,
        }
        result = self.validator.validate(self._make_candidate(key_levels=levels))
        assert result.gate_details["G1_symmetry"] is True

    def test_g1_fails_bad_symmetry(self):
        """Asymmetric structure should fail G1."""
        levels = {
            "SH1": 1.1000,
            "SH2": 1.1001,
            "SL1": 1.0900,
            "SL2": 1.0980,  # wildly asymmetric
        }
        result = self.validator.validate(self._make_candidate(key_levels=levels))
        assert result.gate_details["G1_symmetry"] is False
        assert "G1_symmetry" in result.failed_gates

    # ── G2: Level Completion ───────────────────────────────────────

    def test_g2_passes_no_r3_d3(self):
        """No R3/D3 levels → pass."""
        levels = [Level(1.1, LevelType.R1, 0.005, 0)]
        result = self.validator.validate(self._make_candidate(), levels=levels)
        assert result.gate_details["G2_level_completion"] is True

    def test_g2_passes_good_completion(self):
        """R3 ≥ 90% of R2 → pass."""
        levels = [
            Level(1.1, LevelType.R2, 0.0100, 0),
            Level(1.11, LevelType.R3, 0.0095, 1),  # 95% of R2
        ]
        result = self.validator.validate(self._make_candidate(), levels=levels)
        assert result.gate_details["G2_level_completion"] is True

    def test_g2_fails_bad_completion(self):
        """R3 < 90% of R2 → fail."""
        levels = [
            Level(1.1, LevelType.R2, 0.0100, 0),
            Level(1.11, LevelType.R3, 0.0080, 1),  # 80% of R2
        ]
        result = self.validator.validate(self._make_candidate(), levels=levels)
        assert result.gate_details["G2_level_completion"] is False
        assert "G2_level_completion" in result.failed_gates

    # ── G3: Session Alignment ──────────────────────────────────────

    def test_g3_passes_no_session(self):
        """No session state → pass."""
        result = self.validator.validate(self._make_candidate())
        assert result.gate_details["G3_session_alignment"] is True

    def test_g3_passes_matching_bias(self):
        """Long signal with bullish session bias → pass."""
        session = SessionState("LONDON", True, 0.8, "bullish")
        result = self.validator.validate(
            self._make_candidate(direction="long"), session_state=session
        )
        assert result.gate_details["G3_session_alignment"] is True

    def test_g3_fails_opposing_bias(self):
        """Long signal with bearish session bias → fail."""
        session = SessionState("LONDON", True, 0.8, "bearish")
        result = self.validator.validate(
            self._make_candidate(direction="long"), session_state=session
        )
        assert result.gate_details["G3_session_alignment"] is False
        assert "G3_session_alignment" in result.failed_gates

    # ── G4: HTF Alignment ──────────────────────────────────────────

    def test_g4_passes_no_htf(self):
        result = self.validator.validate(self._make_candidate())
        assert result.gate_details["G4_htf_alignment"] is True

    def test_g4_passes_aligned_trend(self):
        """Long signal with positive EMA slope → pass."""
        htf = HTFState(HTFPhase.ALIGNED, 0.8, 0.001, 0.01)
        result = self.validator.validate(
            self._make_candidate(direction="long"), htf_state=htf
        )
        assert result.gate_details["G4_htf_alignment"] is True

    def test_g4_fails_conflicting_trend(self):
        """Long signal with negative EMA slope → fail."""
        htf = HTFState(HTFPhase.ALIGNED, 0.8, -0.001, 0.01)
        result = self.validator.validate(
            self._make_candidate(direction="long"), htf_state=htf
        )
        assert result.gate_details["G4_htf_alignment"] is False

    def test_g4_fails_conflicting_phase(self):
        """CONFLICTING phase always fails."""
        htf = HTFState(HTFPhase.CONFLICTING, 0.0, 0.0, 0.01)
        result = self.validator.validate(self._make_candidate(), htf_state=htf)
        assert result.gate_details["G4_htf_alignment"] is False

    def test_g4_passes_consolidating(self):
        """CONSOLIDATING phase should pass (degraded, not blocked)."""
        htf = HTFState(HTFPhase.CONSOLIDATING, 0.0, 0.0, 0.001)
        result = self.validator.validate(self._make_candidate(), htf_state=htf)
        assert result.gate_details["G4_htf_alignment"] is True

    # ── G5: No Conflict ────────────────────────────────────────────

    def test_g5_passes_no_active_signal(self):
        result = self.validator.validate(self._make_candidate())
        assert result.gate_details["G5_no_conflict"] is True

    def test_g5_fails_opposing_signal(self):
        """Register a short signal, then try long → fail."""
        signal = Signal("EURUSD", "short", 1.1, 1.09, 1.11, 0.7)
        self.validator.register_signal(signal)
        result = self.validator.validate(self._make_candidate(direction="long"))
        assert result.gate_details["G5_no_conflict"] is False
        assert "G5_no_conflict" in result.failed_gates

    def test_g5_passes_same_direction(self):
        signal = Signal("EURUSD", "long", 1.1, 1.09, 1.11, 0.7)
        self.validator.register_signal(signal)
        result = self.validator.validate(self._make_candidate(direction="long"))
        assert result.gate_details["G5_no_conflict"] is True

    def test_g5_passes_after_clear(self):
        signal = Signal("EURUSD", "short", 1.1, 1.09, 1.11, 0.7)
        self.validator.register_signal(signal)
        self.validator.clear_signal("EURUSD")
        result = self.validator.validate(self._make_candidate(direction="long"))
        assert result.gate_details["G5_no_conflict"] is True

    # ── Quality Threshold ──────────────────────────────────────────

    def test_quality_threshold_rejects_low_confidence(self):
        """Below 0.6 confidence → overall pass=False even if gates pass."""
        result = self.validator.validate(self._make_candidate(confidence=0.5))
        # All gates should pass individually
        assert len(result.failed_gates) == 0
        # But overall quality fails
        assert result.passed is False

    def test_quality_threshold_accepts_high_confidence(self):
        result = self.validator.validate(self._make_candidate(confidence=0.8))
        assert result.passed is True

    # ── All Gates Pass ─────────────────────────────────────────────

    def test_all_gates_pass_clean_candidate(self):
        """Clean candidate with aligned HTF and session should pass all."""
        htf = HTFState(HTFPhase.ALIGNED, 0.8, 0.001, 0.01)
        session = SessionState("LONDON", True, 0.8, "bullish")
        levels = [
            Level(1.1, LevelType.R2, 0.0100, 0),
            Level(1.11, LevelType.R3, 0.0095, 1),
        ]
        result = self.validator.validate(
            self._make_candidate(direction="long", confidence=0.8),
            htf_state=htf,
            session_state=session,
            levels=levels,
        )
        assert result.passed is True
        assert len(result.failed_gates) == 0

    def test_multiple_gate_failures(self):
        """Multiple failing gates should all be reported."""
        htf = HTFState(HTFPhase.CONFLICTING, 0.0, 0.0, 0.01)
        session = SessionState("LONDON", True, 0.8, "bearish")
        result = self.validator.validate(
            self._make_candidate(direction="long"),
            htf_state=htf,
            session_state=session,
        )
        assert "G3_session_alignment" in result.failed_gates
        assert "G4_htf_alignment" in result.failed_gates
        assert result.passed is False
