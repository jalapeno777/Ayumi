"""§5 — Pattern detection: M/W formations, SVCs, traps, liquidity grabs, FL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .data_types import Level, LevelType, Swing, SwingType
from .thresholds import (
    MW_SYMMETRY_MAX,
    MW_EQUAL_THRESHOLD,
    TRAP_BREAK_LONDON_NY,
    TRAP_BREAK_ASIA,
    NEAR_THRESHOLD,
)


@dataclass
class DetectedPattern:
    """A detected pattern with metadata."""

    pattern_type: str  # "M", "W", "SVC_SPRING", "SVC_VACATION", "SVC_CONTINUATION",
    # "TRAP", "LIQUIDITY_GRAB", "FL"
    direction: str  # "long" or "short"
    confidence: float  # 0.0 - 1.0
    key_levels: dict = field(default_factory=dict)
    checklist_score: float = 0.0  # for M/W: fraction of 11 points passed
    checklist_details: dict = field(default_factory=dict)
    notes: str = ""


class PatternDetector:
    """Detect M/W formations, SVCs, traps, liquidity grabs, and FL patterns."""

    def __init__(
        self,
        symmetry_max: float = MW_SYMMETRY_MAX,
        equal_threshold: float = MW_EQUAL_THRESHOLD,
        trap_break_london_ny: float = TRAP_BREAK_LONDON_NY,
        trap_break_asia: float = TRAP_BREAK_ASIA,
        near_threshold: float = NEAR_THRESHOLD,
    ):
        self.symmetry_max = symmetry_max
        self.equal_threshold = equal_threshold
        self.trap_break_london_ny = trap_break_london_ny
        self.trap_break_asia = trap_break_asia
        self.near_threshold = near_threshold

    # ── M/W 11-Point Checklist ──────────────────────────────────────

    def detect_mw_formation(
        self,
        swings: list[Swing],
        levels: list[Level],
        current_price: float = 0.0,
    ) -> Optional[DetectedPattern]:
        """Detect M (bearish reversal) or W (bullish reversal) using 11-point checklist.

        M structure: SH1 → SL1 → SH2 → SL2 → SH3 (breaks SH1)
        W structure: SL1 → SH1 → SL2 → SH2 → SL3 (breaks SL1)

        Returns the best-matching pattern or None.
        """
        m_result = self._evaluate_m_pattern(swings, levels, current_price)
        w_result = self._evaluate_w_pattern(swings, levels, current_price)

        best = None
        for candidate in (m_result, w_result):
            if candidate and candidate.confidence > 0.3:
                if best is None or candidate.confidence > best.confidence:
                    best = candidate

        return best

    def _evaluate_m_pattern(
        self,
        swings: list[Swing],
        levels: list[Level],
        current_price: float,
    ) -> Optional[DetectedPattern]:
        """Evaluate M formation (bearish reversal) against 11-point checklist."""
        # Need at least 5 swings: H, L, H, L, H
        pattern_swings = self._extract_alternating(swings, SwingType.HIGH)
        if len(pattern_swings) < 5:
            return None

        sh1, sl1, sh2, sl2, sh3 = pattern_swings[:5]

        # Basic structure: SH3 > SH1 (break), SL2 < SL1 (lower low)
        if sh3.price <= sh1.price or sl2.price >= sl1.price:
            return None

        checklist = self._mw_checklist(
            sh1=sh1.price,
            sl1=sl1.price,
            sh2=sh2.price,
            sl2=sl2.price,
            sh3=sh3.price,
            is_bearish=True,
            levels=levels,
            current_price=current_price,
        )

        score = sum(checklist.values()) / 11.0
        if score < 0.4:
            return None

        return DetectedPattern(
            pattern_type="M",
            direction="short",
            confidence=score,
            key_levels={
                "SH1": sh1.price,
                "SL1": sl1.price,
                "SH2": sh2.price,
                "SL2": sl2.price,
                "SH3": sh3.price,
            },
            checklist_score=score,
            checklist_details=checklist,
        )

    def _evaluate_w_pattern(
        self,
        swings: list[Swing],
        levels: list[Level],
        current_price: float,
    ) -> Optional[DetectedPattern]:
        """Evaluate W formation (bullish reversal) against 11-point checklist."""
        pattern_swings = self._extract_alternating(swings, SwingType.LOW)
        if len(pattern_swings) < 5:
            return None

        sl1, sh1, sl2, sh2, sl3 = pattern_swings[:5]

        # Basic structure: SL3 < SL1 (break), SH2 > SH1 (higher high)
        if sl3.price >= sl1.price or sh2.price <= sh1.price:
            return None

        checklist = self._mw_checklist(
            sh1=sh1.price,
            sl1=sl1.price,
            sh2=sh2.price,
            sl2=sl2.price,
            sh3=sl3.price,  # reuse field for SL3
            is_bearish=False,
            levels=levels,
            current_price=current_price,
        )

        score = sum(checklist.values()) / 11.0
        if score < 0.4:
            return None

        return DetectedPattern(
            pattern_type="W",
            direction="long",
            confidence=score,
            key_levels={
                "SL1": sl1.price,
                "SH1": sh1.price,
                "SL2": sl2.price,
                "SH2": sh2.price,
                "SL3": sl3.price,
            },
            checklist_score=score,
            checklist_details=checklist,
        )

    def _extract_alternating(
        self, swings: list[Swing], start_type: SwingType
    ) -> list[Swing]:
        """Extract alternating H-L-H-L... or L-H-L-H... sequence from swings."""
        sorted_swings = sorted(swings, key=lambda s: s.bar_index)
        result: list[Swing] = []
        expected = start_type
        for s in sorted_swings:
            if s.swing_type == expected:
                result.append(s)
                expected = (
                    SwingType.LOW if expected == SwingType.HIGH else SwingType.HIGH
                )
        return result

    def _mw_checklist(
        self,
        sh1: float,
        sl1: float,
        sh2: float,
        sl2: float,
        sh3: float,
        is_bearish: bool,
        levels: list[Level],
        current_price: float,
    ) -> dict[str, bool]:
        """Evaluate the 11-point M/W checklist.

        Points (adapted for both M and W):
        1. Break of first extreme (SH1 for M, SL1 for W)
        2. Lower low (SL2 < SL1 for M) / Higher high (SH2 > SH1 for W)
        3. Equality of first extremes (SH1≈SH3 for M, SL1≈SL3 for W)
        4. Second extreme not exceeded (SH2 < SH1 for M, SL2 > SL1 for W)
        5. SL1/SL2 symmetry ≤ 1.5%
        6. SH1/SH2 symmetry ≤ 1.5% (for M; mirrored for W)
        7. Clear rejection at first extreme
        8. Structure completion (all 5 points present)
        9. Time symmetry (roughly equal legs)
        10. Volume climax at turning points (simplified: checked via levels)
        11. No level overlap violations
        """
        checks: dict[str, bool] = {}

        if is_bearish:
            # 1. SH3 breaks SH1
            checks["break_first_extreme"] = sh3 > sh1
            # 2. SL2 < SL1 (lower low)
            checks["second_low_lower"] = sl2 < sl1
            # 3. SH1 ≈ SH3 (equality within tolerance)
            checks["equality_first_extremes"] = (
                abs(sh3 - sh1) / sh1 <= self.equal_threshold * 10
            )
            # 4. SH2 < SH1 (second high doesn't exceed first)
            checks["second_high_below_first"] = sh2 < sh1
            # 5. SL symmetry
            sl_mid = (sh1 + sh2) / 2
            sl1_dist = abs(sl1 - sl_mid)
            sl2_dist = abs(sl2 - sl_mid)
            sl_avg = (sl1_dist + sl2_dist) / 2
            checks["sl_symmetry"] = (
                sl_avg > 0 and abs(sl1_dist - sl2_dist) / sl_avg <= self.symmetry_max
            )
            # 6. SH symmetry
            sh1_dist = abs(sh1 - sl_mid)
            sh2_dist = abs(sh2 - sl_mid)
            sh_avg = (sh1_dist + sh2_dist) / 2
            checks["sh_symmetry"] = (
                sh_avg > 0 and abs(sh1_dist - sh2_dist) / sh_avg <= self.symmetry_max
            )
            # 7. Clear rejection (SH2 significantly below SH1)
            checks["clear_rejection"] = (sh1 - sh2) / sh1 > self.near_threshold
        else:
            # W (bullish) — mirror logic
            sl3 = sh3  # reuse
            checks["break_first_extreme"] = sl3 < sl1
            checks["second_high_higher"] = sh2 > sh1
            checks["equality_first_extremes"] = (
                abs(sl3 - sl1) / sl1 <= self.equal_threshold * 10
            )
            checks["second_low_above_first"] = sl2 > sl1
            # SH symmetry (now SH1/SH2 are the symmetric pair)
            sh_mid = (sl1 + sl2) / 2
            sh1_dist = abs(sh1 - sh_mid)
            sh2_dist = abs(sh2 - sh_mid)
            sh_avg = (sh1_dist + sh2_dist) / 2
            checks["sh_symmetry"] = (
                sh_avg > 0 and abs(sh1_dist - sh2_dist) / sh_avg <= self.symmetry_max
            )
            # SL symmetry
            sl1_dist = abs(sl1 - sh_mid)
            sl2_dist = abs(sl2 - sh_mid)
            sl_avg = (sl1_dist + sl2_dist) / 2
            checks["sl_symmetry"] = (
                sl_avg > 0 and abs(sl1_dist - sl2_dist) / sl_avg <= self.symmetry_max
            )
            checks["clear_rejection"] = (sl2 - sl1) / sl1 > self.near_threshold

        # 8. Structure completion (always true if we got here — 5 swings found)
        checks["structure_complete"] = True

        # 9. Time symmetry — skip without bar_index timing data in this check

        # 10. Volume climax — simplified: accept if levels are present
        checks["volume_confirmation"] = len(levels) > 0

        # 11. No level overlap — simplified: pass by default
        checks["no_level_violation"] = True

        return checks

    # ── SVC Detection ───────────────────────────────────────────────

    def detect_svc(
        self,
        bar: dict,
        levels: list[Level],
        session: str = "LONDON",
    ) -> Optional[DetectedPattern]:
        """Detect Stopping Volume Candle (SVC) patterns.

        Spring: price sweeps below support then reverses (bullish).
        Vacation: price sweeps above resistance then reverses (bearish).
        Continuation: momentum candle in trend direction.
        """
        high = bar.get("high", 0)
        low = bar.get("low", 0)
        close = bar.get("close", 0)
        open_ = bar.get("open", 0)
        body = abs(close - open_)
        total_range = high - low
        if total_range <= 0:
            return None

        # Body must be significant (≥50% of range for an SVC)
        body_ratio = body / total_range
        if body_ratio < 0.50:
            return None

        is_bullish = close > open_

        for lv in levels:
            if lv.level_type in (LevelType.D1, LevelType.D2, LevelType.D3):
                # Check for spring: wick sweeps below level, body closes above
                if low < lv.price < close and is_bullish:
                    proximity = abs(low - lv.price) / lv.price
                    if proximity < self.near_threshold:
                        return DetectedPattern(
                            pattern_type="SVC_SPRING",
                            direction="long",
                            confidence=min(body_ratio, 0.9),
                            key_levels={"level": lv.price, "type": lv.level_type.value},
                            notes=f"Spring at {lv.level_type.value} ({lv.price:.5f})",
                        )
            elif lv.level_type in (LevelType.R1, LevelType.R2, LevelType.R3):
                # Check for vacation: wick sweeps above level, body closes below
                if high > lv.price > close and not is_bullish:
                    proximity = abs(high - lv.price) / lv.price
                    if proximity < self.near_threshold:
                        return DetectedPattern(
                            pattern_type="SVC_VACATION",
                            direction="short",
                            confidence=min(body_ratio, 0.9),
                            key_levels={"level": lv.price, "type": lv.level_type.value},
                            notes=f"Vacation at {lv.level_type.value} ({lv.price:.5f})",
                        )

        # Continuation: strong momentum candle with no level interaction
        if body_ratio >= 0.70:
            direction = "long" if is_bullish else "short"
            return DetectedPattern(
                pattern_type="SVC_CONTINUATION",
                direction=direction,
                confidence=body_ratio * 0.8,
                notes=f"Continuation candle (body ratio {body_ratio:.2f})",
            )

        return None

    # ── Trap Detection ──────────────────────────────────────────────

    def detect_trap(
        self,
        bars: list[dict],
        level_price: float,
        session: str = "LONDON",
    ) -> Optional[DetectedPattern]:
        """Detect trap setups where price breaks a level then reverses.

        Uses minimum break distance per session:
        - London/NY: 0.2%
        - Asia: 0.4%
        """
        if not bars:
            return None

        min_break = (
            self.trap_break_london_ny
            if session in ("LONDON", "NY", "LONDON_NY")
            else self.trap_break_asia
        )

        # Find the maximum excursion beyond the level
        max_above = max(b.get("high", 0) for b in bars)
        max_below = min(b.get("low", 0) for b in bars)
        last_close = bars[-1].get("close", 0)

        # Bullish trap: price broke above level then closed below
        if max_above > level_price * (1 + min_break) and last_close < level_price:
            break_pct = (max_above - level_price) / level_price
            return DetectedPattern(
                pattern_type="TRAP",
                direction="short",
                confidence=min(break_pct * 2, 0.9),
                key_levels={
                    "trap_level": level_price,
                    "max_excursion": max_above,
                    "break_pct": break_pct,
                },
                notes=f"Bullish trap in {session} (broke {break_pct:.3%})",
            )

        # Bearish trap: price broke below level then closed above
        if max_below < level_price * (1 - min_break) and last_close > level_price:
            break_pct = (level_price - max_below) / level_price
            return DetectedPattern(
                pattern_type="TRAP",
                direction="long",
                confidence=min(break_pct * 2, 0.9),
                key_levels={
                    "trap_level": level_price,
                    "max_excursion": max_below,
                    "break_pct": break_pct,
                },
                notes=f"Bearish trap in {session} (broke {break_pct:.3%})",
            )

        return None

    # ── ILOD / IHOD Detection ───────────────────────────────────────

    def detect_ilod_ihod(
        self,
        bars: list[dict],
        session: str = "LONDON",
    ) -> list[DetectedPattern]:
        """Detect Intraday Low of Day (ILOD) and High of Day (IHOD) breaks.

        ILOD break (bearish): price breaks below session low.
        IHOD break (bullish): price breaks above session high.
        """
        if not bars:
            return []

        session_high = max(b.get("high", 0) for b in bars)
        session_low = min(b.get("low", 0) for b in bars)
        last_bar = bars[-1]
        patterns: list[DetectedPattern] = []

        # ILOD break — price breaks below session low then shows rejection
        if last_bar["close"] < session_low:
            patterns.append(
                DetectedPattern(
                    pattern_type="ILOD_BREAK",
                    direction="short",
                    confidence=0.6,
                    key_levels={"ilod": session_low},
                    notes=f"ILOD break in {session}",
                )
            )

        # IHOD break — price breaks above session high then shows rejection
        if last_bar["close"] > session_high:
            patterns.append(
                DetectedPattern(
                    pattern_type="IHOD_BREAK",
                    direction="long",
                    confidence=0.6,
                    key_levels={"ihod": session_high},
                    notes=f"IHOD break in {session}",
                )
            )

        return patterns

    # ── Liquidity Grab ──────────────────────────────────────────────

    def detect_liquidity_grab(
        self,
        bar: dict,
        levels: list[Level],
    ) -> Optional[DetectedPattern]:
        """Detect liquidity grab: wick sweeps through a level, body rejects.

        A liquidity grab has a long wick through a level with the body
        closing on the opposite side, indicating stops were taken.
        """
        high = bar.get("high", 0)
        low = bar.get("low", 0)
        close = bar.get("close", 0)
        open_ = bar.get("open", 0)
        total_range = high - low
        if total_range <= 0:
            return None

        for lv in levels:
            wick_below = low < lv.price
            wick_above = high > lv.price

            # Bullish liquidity grab: wick below level, body closes above
            if wick_below and close > lv.price and open_ > lv.price:
                wick_size = lv.price - low
                wick_ratio = wick_size / total_range
                if wick_ratio > 0.3:
                    return DetectedPattern(
                        pattern_type="LIQUIDITY_GRAB",
                        direction="long",
                        confidence=min(wick_ratio, 0.9),
                        key_levels={
                            "grab_level": lv.price,
                            "wick_ratio": wick_ratio,
                            "type": lv.level_type.value,
                        },
                        notes=f"Bullish liq grab at {lv.level_type.value}",
                    )

            # Bearish liquidity grab: wick above level, body closes below
            if wick_above and close < lv.price and open_ < lv.price:
                wick_size = high - lv.price
                wick_ratio = wick_size / total_range
                if wick_ratio > 0.3:
                    return DetectedPattern(
                        pattern_type="LIQUIDITY_GRAB",
                        direction="short",
                        confidence=min(wick_ratio, 0.9),
                        key_levels={
                            "grab_level": lv.price,
                            "wick_ratio": wick_ratio,
                            "type": lv.level_type.value,
                        },
                        notes=f"Bearish liq grab at {lv.level_type.value}",
                    )

        return None

    # ── FL (Flight Log) Strategy ────────────────────────────────────

    def detect_fl_pattern(
        self,
        swings: list[Swing],
        levels: list[Level],
        current_price: float = 0.0,
    ) -> Optional[DetectedPattern]:
        """Detect FL (Flight Log) strategy patterns.

        FL strategy looks for a series of higher highs and higher lows (or
        inverse) forming a staircase pattern with clear impulse/correction
        legs. At least 3 impulse legs required.
        """
        sorted_swings = sorted(swings, key=lambda s: s.bar_index)
        if len(sorted_swings) < 6:
            return None

        # Extract alternating swings starting from the most common type
        starts_high = sum(
            1 for s in sorted_swings[:3] if s.swing_type == SwingType.HIGH
        )
        start_type = SwingType.HIGH if starts_high >= 2 else SwingType.LOW
        alt = self._extract_alternating(sorted_swings, start_type)

        if len(alt) < 6:
            return None

        # Check for bullish FL: HL1, HH1, HL2, HH2, HL3, HH3
        is_bullish = self._check_staircase(alt, bullish=True)
        is_bearish = not is_bullish and self._check_staircase(alt, bullish=False)

        if not is_bullish and not is_bearish:
            return None

        direction = "long" if is_bullish else "short"
        # Confidence scales with number of impulse legs
        impulse_count = len(alt) // 2
        confidence = min(0.5 + impulse_count * 0.1, 0.9)

        last_swing = alt[-1]
        return DetectedPattern(
            pattern_type="FL",
            direction=direction,
            confidence=confidence,
            key_levels={
                "last_swing_price": last_swing.price,
                "impulse_legs": impulse_count,
            },
            notes=f"FL {direction} with {impulse_count} impulse legs",
        )

    def _check_staircase(self, swings: list[Swing], bullish: bool) -> bool:
        """Check if swings form a staircase pattern (HH/HL or LH/LL)."""
        if len(swings) < 4:
            return False

        if bullish:
            # For L-H-L-H... starting with L: check HL, HH, HL, HH...
            for i in range(2, len(swings)):
                if i % 2 == 0:  # Even = lows: should be higher low
                    if swings[i].price <= swings[i - 2].price:
                        return False
                else:  # Odd = highs: should be higher high
                    if swings[i].price <= swings[i - 2].price:
                        return False
        else:
            # For H-L-H-L... starting with H: check LH, LL, LH, LL...
            for i in range(2, len(swings)):
                if i % 2 == 0:  # Even = highs: should be lower high
                    if swings[i].price >= swings[i - 2].price:
                        return False
                else:  # Odd = lows: should be lower low
                    if swings[i].price >= swings[i - 2].price:
                        return False

        return True

    # ── Composite Detection ─────────────────────────────────────────

    def detect_all(
        self,
        swings: list[Swing],
        levels: list[Level],
        bars: list[dict],
        current_price: float = 0.0,
        session: str = "LONDON",
    ) -> list[DetectedPattern]:
        """Run all pattern detectors and return combined results."""
        patterns: list[DetectedPattern] = []

        # M/W formation
        mw = self.detect_mw_formation(swings, levels, current_price)
        if mw:
            patterns.append(mw)

        # SVC (on last bar)
        if bars:
            svc = self.detect_svc(bars[-1], levels, session)
            if svc:
                patterns.append(svc)

        # Traps (check each level)
        for lv in levels:
            trap = self.detect_trap(
                bars[-5:] if len(bars) >= 5 else bars, lv.price, session
            )
            if trap:
                patterns.append(trap)

        # ILOD/IHOD
        patterns.extend(self.detect_ilod_ihod(bars, session))

        # Liquidity grab (on last bar)
        if bars:
            liq = self.detect_liquidity_grab(bars[-1], levels)
            if liq:
                patterns.append(liq)

        # FL pattern
        fl = self.detect_fl_pattern(swings, levels, current_price)
        if fl:
            patterns.append(fl)

        return patterns
