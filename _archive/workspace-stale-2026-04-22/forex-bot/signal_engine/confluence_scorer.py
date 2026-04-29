"""
Confluence Scorer — Booster weight table for forex (§7.1).

Only scored if ALL gates pass AND quality_score ≥ 0.50.
This is applied AFTER gates, scoring confluence factors that boost confidence.

Weight table (§7.1):
| Factor                | Weight | Scoring Logic                                           |
|-----------------------|--------|---------------------------------------------------------|
| mtf_alignment         | 0.14   | §4.5 table (0.0-1.0)                                   |
| multi_session         | 0.10   | 3+ sessions = 1.0, 2 = 0.7, 1 = 0.2                    |
| svc_present           | 0.10   | True = 1.0, False = 0.0                                 |
| hits_to_level         | 0.08   | 0 = 0.0, 1 = 0.4, 2 = 0.7, 3+ = 1.0                    |
| hits_with_volume      | 0.05   | Increasing vol = 1.0, flat = 0.3, decreasing = 0.1      |
| near_period_extreme   | 0.08   | §1.2 proximity table                                    |
| htf_not_consolidating | 0.08   | H4 NOT consolidating = 1.0, consolidating = 0.0         |
| kill_zone             | 0.06   | In kill zone = 1.0, otherwise = 0.0                     |
| session_overlap       | 0.04   | In session overlap = 1.0, otherwise = 0.0               |
| session_phase         | 0.04   | Opening = 1.0, mid = 0.5, closing = 0.2                 |
| day_of_week           | 0.04   | Additive offset: Mon -0.10, Tue +0.05, Wed +0.05, Thu 0.0, Fri -0.10 |
| asia_control          | 0.03   | Tight range+consolidating = 1.0, trending = 0.0, neutral = 0.5 |
| ema_bounce            | 0.05   | Touch 50 EMA + rejection candle = 1.0, no touch = 0.0   |
| dxy_correlation       | 0.06   | DXY agrees = 1.0, opposes = 0.0, flat = 0.5             |
| Total                 | 0.95   | (5% slack for future factors)                           |

HTF modifier (§4.4): applied BEFORE interaction bonuses.
    aligned +0.15, conflicting -0.25, consolidating -0.15, exhaustion +0.10, neutral -0.05

Interaction bonuses (on floored raw, before cap):
    - mtf_alignment >= 0.75 AND multi_session >= 0.7: raw *= 1.08
    - svc_present AND hits_to_level >= 0.7: raw *= 1.05

Action thresholds (§8):
    - ≥ 0.65 → STRONG (full position)
    - 0.50–0.64 → MODERATE (half position)
    - 0.40–0.49 → GRAY ZONE (quarter position)
    - < 0.40 → NO TRADE
"""

from dataclasses import dataclass
from typing import Dict
from enum import Enum


class ActionThreshold(Enum):
    """Position sizing tier based on confidence score (§8)."""
    STRONG = "strong"        # ≥ 0.65 — full position
    MODERATE = "moderate"    # 0.50–0.64 — half position
    GRAY_ZONE = "gray_zone"  # 0.40–0.49 — quarter position
    NO_TRADE = "no_trade"    # < 0.40


@dataclass
class ConfluenceInput:
    """All inputs required to compute the confluence score."""
    mtf_alignment: float            # 0.0-1.0 from HTF analyzer (§4.5)
    multi_session_count: int        # 1, 2, or 3+
    svc_present: bool               # Smart volume cluster detected
    hits_to_level: int              # 0, 1, 2, 3+ touches on key level
    hits_volume_trend: str          # "increasing", "flat", "decreasing"
    near_period_extreme_pct: float  # Distance to HiW/LoW as decimal % (§1.2)
    htf_consolidating: bool         # True if H4 is consolidating
    in_kill_zone: bool              # Within session kill zone window
    in_session_overlap: bool        # Within session overlap period
    session_phase: str              # "opening", "mid", "closing"
    day_of_week: int                # 0=Monday … 4=Friday (§8.3)
    asia_control: str               # "tight_consolidating", "trending", "neutral"
    ema_bounce: bool                # Price touched 50 EMA and rejected
    dxy_direction: str              # "agrees", "opposes", "flat_unknown"
    htf_modifier: float             # From HTF analyzer (§4.4): -0.25 to +0.15


class ConfluenceScorer:
    """
    Calculate confluence score from booster weight table (§7.1).

    Returns confidence score + recommended action threshold.
    """

    WEIGHTS: Dict[str, float] = {
        'mtf_alignment': 0.14,
        'multi_session': 0.10,
        'svc_present': 0.10,
        'hits_to_level': 0.08,
        'hits_with_volume': 0.05,
        'near_period_extreme': 0.08,
        'htf_not_consolidating': 0.08,
        'kill_zone': 0.06,
        'session_overlap': 0.04,
        'session_phase': 0.04,
        'day_of_week': 0.04,
        'asia_control': 0.03,
        'ema_bounce': 0.05,
        'dxy_correlation': 0.06,
    }

    # Day-of-week additive offsets (§8.3) — applied to FINAL score, not weighted
    WEEKLY_OFFSETS: Dict[int, float] = {
        0: -0.10,   # Monday
        1: 0.05,    # Tuesday
        2: 0.05,    # Wednesday
        3: 0.0,     # Thursday
        4: -0.10,   # Friday
    }

    # Near period extreme scoring — proximity to HiW/LoW (§1.2)
    PERIOD_EXTREME_SCORING = [
        (0.003, 1.0),          # ≤ 0.3% → score 1.0
        (0.010, 0.7),          # ≤ 1.0% → score 0.7
        (0.020, 0.3),          # ≤ 2.0% → score 0.3
        (float('inf'), 0.0),   # > 2.0% → score 0.0
    ]

    def score(
        self, input: ConfluenceInput
    ) -> tuple[float, ActionThreshold, Dict[str, float]]:
        """
        Calculate confidence score from confluence factors.

        Returns:
            (confidence, action_threshold, factor_breakdown)
            where factor_breakdown maps factor name → weighted contribution.
        """
        factors: Dict[str, float] = {}

        # --- Weighted factors ---

        # mtf_alignment (§4.5) — pass through 0.0–1.0
        factors['mtf_alignment'] = (
            input.mtf_alignment * self.WEIGHTS['mtf_alignment']
        )

        # multi_session
        if input.multi_session_count >= 3:
            ms_score = 1.0
        elif input.multi_session_count == 2:
            ms_score = 0.7
        else:
            ms_score = 0.2
        factors['multi_session'] = ms_score * self.WEIGHTS['multi_session']

        # svc_present
        factors['svc_present'] = (
            (1.0 if input.svc_present else 0.0) * self.WEIGHTS['svc_present']
        )

        # hits_to_level
        if input.hits_to_level >= 3:
            hl_score = 1.0
        elif input.hits_to_level == 2:
            hl_score = 0.7
        elif input.hits_to_level == 1:
            hl_score = 0.4
        else:
            hl_score = 0.0
        factors['hits_to_level'] = hl_score * self.WEIGHTS['hits_to_level']

        # hits_with_volume
        hv_map = {"increasing": 1.0, "flat": 0.3, "decreasing": 0.1}
        factors['hits_with_volume'] = (
            hv_map.get(input.hits_volume_trend, 0.0) * self.WEIGHTS['hits_with_volume']
        )

        # near_period_extreme (§1.2)
        for threshold, score_val in self.PERIOD_EXTREME_SCORING:
            if input.near_period_extreme_pct <= threshold:
                factors['near_period_extreme'] = (
                    score_val * self.WEIGHTS['near_period_extreme']
                )
                break

        # htf_not_consolidating
        factors['htf_not_consolidating'] = (
            (0.0 if input.htf_consolidating else 1.0)
            * self.WEIGHTS['htf_not_consolidating']
        )

        # kill_zone
        factors['kill_zone'] = (
            (1.0 if input.in_kill_zone else 0.0) * self.WEIGHTS['kill_zone']
        )

        # session_overlap
        factors['session_overlap'] = (
            (1.0 if input.in_session_overlap else 0.0)
            * self.WEIGHTS['session_overlap']
        )

        # session_phase
        sp_map = {"opening": 1.0, "mid": 0.5, "closing": 0.2}
        factors['session_phase'] = (
            sp_map.get(input.session_phase, 0.5) * self.WEIGHTS['session_phase']
        )

        # day_of_week — additive offset (not weighted), stored for later
        weekly_offset = self.WEEKLY_OFFSETS.get(input.day_of_week, 0.0)

        # asia_control
        ac_map = {"tight_consolidating": 1.0, "trending": 0.0, "neutral": 0.5}
        factors['asia_control'] = (
            ac_map.get(input.asia_control, 0.5) * self.WEIGHTS['asia_control']
        )

        # ema_bounce
        factors['ema_bounce'] = (
            (1.0 if input.ema_bounce else 0.0) * self.WEIGHTS['ema_bounce']
        )

        # dxy_correlation
        dx_map = {"agrees": 1.0, "opposes": 0.0, "flat_unknown": 0.5}
        factors['dxy_correlation'] = (
            dx_map.get(input.dxy_direction, 0.5) * self.WEIGHTS['dxy_correlation']
        )

        # --- Aggregate ---

        # Sum base weighted factors
        raw = sum(factors.values())

        # Apply HTF modifier (§4.4 Output B) — before interaction bonuses
        raw += input.htf_modifier

        # Floor at 0.0
        raw = max(0.0, raw)

        # Interaction bonuses (on floored raw, before cap)
        if input.mtf_alignment >= 0.75 and input.multi_session_count >= 2:
            raw *= 1.08
        if input.svc_present and input.hits_to_level >= 2:
            raw *= 1.05

        # Apply weekly offset (§8.3) — additive to final score, not weighted
        raw += weekly_offset

        # Cap at 1.0
        confidence = min(raw, 1.0)

        # Determine action threshold (§8)
        if confidence >= 0.65:
            action = ActionThreshold.STRONG
        elif confidence >= 0.50:
            action = ActionThreshold.MODERATE
        elif confidence >= 0.40:
            action = ActionThreshold.GRAY_ZONE
        else:
            action = ActionThreshold.NO_TRADE

        return confidence, action, factors
