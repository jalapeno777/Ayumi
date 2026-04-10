"""§7 — Confluence scorer. Weights multiple booster factors for signal confidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .thresholds import (
    EMA_TOUCH_THRESHOLD,
    PERIOD_EXTREME_T1,
    PERIOD_EXTREME_T2,
    PERIOD_EXTREME_T3,
)


# Booster weights (from spec §7)
WEIGHT_SESSION_PHASE = 0.15
WEIGHT_LEVEL_PROXIMITY = 0.25
WEIGHT_HTF_ALIGNMENT = 0.20
WEIGHT_EMA_PROXIMITY = 0.10
WEIGHT_BOARDROOM = 0.10
WEIGHT_VOLUME = 0.10
WEIGHT_PATTERN_TYPE = 0.10


@dataclass
class BoosterResult:
    name: str
    score: float  # 0.0 to 1.0
    weight: float
    raw_detail: str = ""


class ConfluenceScorer:
    """Score confluence factors for qualified candidates.

    Only runs after gates pass. Each booster contributes a weighted
    score toward the total confluence confidence.
    """

    def score(
        self,
        candidate: dict,
        htf_state: Optional[dict] = None,
        session_state: Optional[dict] = None,
    ) -> tuple[float, list[BoosterResult]]:
        """Calculate total confluence score and per-booster breakdown.

        Returns (total_score, list of BoosterResult).
        """
        if htf_state is None:
            htf_state = {}
        if session_state is None:
            session_state = {}

        boosters: list[BoosterResult] = []

        boosters.append(self._session_phase_booster(session_state))
        boosters.append(self._level_proximity_booster(candidate))
        boosters.append(self._htf_alignment_booster(candidate, htf_state))
        boosters.append(self._ema_proximity_booster(candidate))
        boosters.append(self._boardroom_booster(candidate))
        boosters.append(self._volume_booster(candidate))
        boosters.append(self._pattern_type_booster(candidate))

        total = sum(b.score * b.weight for b in boosters)
        return total, boosters

    # --- Individual boosters ---

    def _session_phase_booster(self, session_state: dict) -> BoosterResult:
        """Score based on session alignment and kill zone activity."""
        phase_score = session_state.get("phase_score", 0.0)
        kz_active = session_state.get("kill_zone_active", False)
        kz_bonus = 0.3 if kz_active else 0.0
        score = min(1.0, phase_score + kz_bonus)
        return BoosterResult("session_phase", score, WEIGHT_SESSION_PHASE)

    def _level_proximity_booster(self, candidate: dict) -> BoosterResult:
        """Score based on distance to key HiW/LoW levels (§1.2 proximity tiers)."""
        proximity_pct = candidate.get("level_proximity_pct", 1.0)

        # Tiered scoring: closer = higher score
        if proximity_pct <= PERIOD_EXTREME_T1:
            score = 1.0
        elif proximity_pct <= PERIOD_EXTREME_T2:
            score = 0.7
        elif proximity_pct <= PERIOD_EXTREME_T3:
            score = 0.3
        else:
            score = 0.0

        return BoosterResult(
            "level_proximity",
            score,
            WEIGHT_LEVEL_PROXIMITY,
            f"proximity={proximity_pct:.4f}",
        )

    def _htf_alignment_booster(self, candidate: dict, htf_state: dict) -> BoosterResult:
        """Score based on HTF trend direction matching signal direction."""
        direction = candidate.get("direction", "long")
        alignment = htf_state.get("alignment_score", 0.0)

        # Alignment score from HTF analyzer is -1 to 1.
        # For long signals, positive alignment is good; for short, negative.
        if direction == "long":
            score = max(0.0, alignment)
        else:
            score = max(0.0, -alignment)

        return BoosterResult(
            "htf_alignment",
            score,
            WEIGHT_HTF_ALIGNMENT,
            f"alignment={alignment:.2f}, dir={direction}",
        )

    def _ema_proximity_booster(self, candidate: dict) -> BoosterResult:
        """Score based on proximity to EMA (within EMA_TOUCH_THRESHOLD = good)."""
        ema_distance = candidate.get("ema_distance_pct", 1.0)

        if ema_distance <= EMA_TOUCH_THRESHOLD:
            # At the EMA — strongest signal
            score = 1.0
        elif ema_distance <= EMA_TOUCH_THRESHOLD * 3:
            # Near the EMA
            score = 0.5
        else:
            score = 0.0

        return BoosterResult(
            "ema_proximity",
            score,
            WEIGHT_EMA_PROXIMITY,
            f"ema_dist={ema_distance:.4f}",
        )

    def _boardroom_booster(self, candidate: dict) -> BoosterResult:
        """Score based on H1 boardroom range qualification.

        A boardroom is a tight consolidation (≤ BOARDROOM_RANGE) over ≥ 20 H1 bars.
        Being in a boardroom context adds confluence.
        """
        in_boardroom = candidate.get("in_boardroom", False)
        boardroom_bars = candidate.get("boardroom_bars", 0)

        if in_boardroom and boardroom_bars >= 20:
            score = 1.0
        elif in_boardroom:
            score = 0.5
        else:
            score = 0.0

        return BoosterResult(
            "boardroom",
            score,
            WEIGHT_BOARDROOM,
            f"in={in_boardroom}, bars={boardroom_bars}",
        )

    def _volume_booster(self, candidate: dict) -> BoosterResult:
        """Score based on current volume relative to average."""
        volume_ratio = candidate.get("volume_ratio", 0.0)

        # Volume >= 1.5x average is strong confirmation
        if volume_ratio >= 1.5:
            score = 1.0
        elif volume_ratio >= 1.0:
            score = 0.6
        elif volume_ratio >= 0.7:
            score = 0.3
        else:
            score = 0.0

        return BoosterResult(
            "volume",
            score,
            WEIGHT_VOLUME,
            f"ratio={volume_ratio:.2f}",
        )

    def _pattern_type_booster(self, candidate: dict) -> BoosterResult:
        """Score based on pattern type strength."""
        pattern = candidate.get("pattern_type", "").upper()

        # Stronger reversal patterns get higher base scores
        pattern_scores = {
            "M": 0.9,
            "W": 0.9,
            "SVC": 0.7,
            "OB": 0.6,
            "FVG": 0.5,
            "LIQ_SWEEP": 0.6,
        }
        score = pattern_scores.get(pattern, 0.3)

        return BoosterResult(
            "pattern_type",
            score,
            WEIGHT_PATTERN_TYPE,
            f"pattern={pattern}",
        )
