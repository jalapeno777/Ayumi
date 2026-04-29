"""
Level counting for rise/drop sequences.

Implements R1/R2/R3 and D1/D2/D3 detection plus cross-TF feeding.

Spec reference: TTC Signal Confidence Engine §4.2–§4.3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

import numpy as np

# Proximity thresholds (§1.2)
AT_THRESHOLD = 0.002  # "at" = ≤0.2%
NEAR_THRESHOLD = 0.005  # "near" = ≤0.5%

# R3/D3 magnitude ratio (§4.3)
LEVEL_3_MIN_RATIO = 0.90  # R3 magnitude must be ≥ 90% of R2


class LevelState(Enum):
    NO_LEVEL = "no_level"
    RISING = "rising"
    DROPPING = "dropping"
    R1 = "r1"
    R2 = "r2"
    R3 = "r3"
    D1 = "d1"
    D2 = "d2"
    D3 = "d3"


@dataclass
class LevelInfo:
    level_type: str  # R1, R2, R3, D1, D2, D3
    start_bar: int
    confirmed_bar: Optional[int] = None
    magnitude: float = 0.0  # Size of the level move in price
    at_ema_50: bool = False
    at_ema_200: bool = False
    at_period_extreme: bool = False  # Near HiW / LoW
    hit_count: int = 1


@dataclass
class LevelCounter:
    """Count rise/drop levels on a single timeframe.

    State machine transitions:
        NO_LEVEL → R1 (first confirmed rise) or D1 (first confirmed drop)
        R1 → R2 (second rise above R1 high)
        R2 → R3 (third rise, magnitude ≥ 90% of R2, near HiW)
        D1 → D2 → D3 (mirror of rise sequence)
    """

    lookback: int = 5

    # Internal state
    current_state: LevelState = LevelState.NO_LEVEL
    current_rise_count: int = 0
    current_drop_count: int = 0
    levels: List[LevelInfo] = field(default_factory=list)

    # EMA values for context
    ema_50: float = 0.0
    ema_200: float = 0.0

    # Reference prices for magnitude checks
    _last_swing_low_price: float = 0.0
    _last_swing_high_price: float = 0.0
    _r2_magnitude: float = 0.0
    _d2_magnitude: float = 0.0

    # ------------------------------------------------------------------
    # EMA helpers
    # ------------------------------------------------------------------

    def compute_emas(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
    ) -> None:
        """Compute EMAs for level context (§4.3 — MM candle / EMA interaction)."""
        self.ema_50 = self._ema(closes, 50)
        self.ema_200 = self._ema(closes, 200)

    @staticmethod
    def _ema(prices: np.ndarray, period: int) -> float:
        """Simple EMA approximation over the full price series."""
        if len(prices) == 0:
            return 0.0
        if len(prices) < period:
            return float(prices[-1])
        multiplier = 2.0 / (period + 1)
        ema = float(prices[:period].mean())
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    # ------------------------------------------------------------------
    # Proximity helpers (§1.2)
    # ------------------------------------------------------------------

    @staticmethod
    def _pct_diff(a: float, b: float) -> float:
        if a == 0.0:
            return float("inf")
        return abs(a - b) / a

    def _at_ema_50(self, price: float) -> bool:
        return self._pct_diff(price, self.ema_50) <= AT_THRESHOLD

    def _at_ema_200(self, price: float) -> bool:
        return self._pct_diff(price, self.ema_200) <= AT_THRESHOLD

    def _near_ema_200(self, price: float) -> bool:
        return self._pct_diff(price, self.ema_200) <= NEAR_THRESHOLD

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update(
        self,
        bar_index: int,
        high: float,
        low: float,
        close: float,
        swing_highs: list,
        swing_lows: list,
        period_high: float = 0.0,
        period_low: float = 0.0,
    ) -> Optional[LevelInfo]:
        """Process a new bar and possibly confirm a level.

        Args:
            bar_index: Current bar index.
            high, low, close: OHLC of the current bar.
            swing_highs: All detected SwingHigh objects (sorted by bar_index).
            swing_lows: All detected SwingLow objects (sorted by bar_index).
            period_high: Current period high-water mark (HiW).
            period_low: Current period low-water mark (LoW).

        Returns:
            LevelInfo if a new level was just confirmed, else None.

        Level validation criteria (§4.3):
            R1: higher high + higher low from swing low, close breaks 50 EMA.
            R2: extends above R1 high, close breaks 200 EMA.
            R3: extends above R2, magnitude ≥ 90% of R2, near HiW.
            D1/D2/D3: mirror of rise sequence.
        """
        # Track latest swing prices
        if swing_lows:
            self._last_swing_low_price = swing_lows[-1].price
        if swing_highs:
            self._last_swing_high_price = swing_highs[-1].price

        # ---- RISE DETECTION ----
        if close > self.ema_50 and self.current_state in (
            LevelState.NO_LEVEL,
            LevelState.RISING,
            LevelState.R1,
            LevelState.R2,
        ):
            self.current_state = LevelState.RISING

        if self.current_state == LevelState.RISING and swing_highs:
            latest_sh = swing_highs[-1]
            if latest_sh.bar_index == bar_index or (
                bar_index - latest_sh.bar_index <= 3  # allow small delay
            ):
                confirmed = self._confirm_rise(bar_index, latest_sh.price, period_high)
                if confirmed:
                    return confirmed

        # ---- DROP DETECTION ----
        if close < self.ema_50 and self.current_state in (
            LevelState.NO_LEVEL,
            LevelState.DROPPING,
            LevelState.D1,
            LevelState.D2,
        ):
            self.current_state = LevelState.DROPPING

        if self.current_state == LevelState.DROPPING and swing_lows:
            latest_sl = swing_lows[-1]
            if latest_sl.bar_index == bar_index or (
                bar_index - latest_sl.bar_index <= 3
            ):
                confirmed = self._confirm_drop(bar_index, latest_sl.price, period_low)
                if confirmed:
                    return confirmed

        return None

    # ------------------------------------------------------------------
    # Rise confirmation helpers
    # ------------------------------------------------------------------

    def _confirm_rise(
        self, bar_index: int, price: float, period_high: float
    ) -> Optional[LevelInfo]:
        self.current_rise_count += 1
        count = self.current_rise_count

        if count == 1:
            # R1: higher high from swing low, close > 50 EMA (§4.3)
            level = LevelInfo(
                level_type="R1",
                start_bar=bar_index,
                confirmed_bar=bar_index,
                magnitude=price - self._last_swing_low_price,
                at_ema_50=self._at_ema_50(price),
                at_ema_200=self._at_ema_200(price),
                at_period_extreme=self._pct_diff(price, period_high) <= NEAR_THRESHOLD,
            )
            self.levels.append(level)
            self.current_state = LevelState.R1
            return level

        if count == 2 and self.levels:
            prev = self.levels[-1]
            if price > prev.confirmed_bar and price > (self._last_swing_low_price if self._last_swing_low_price else 0):
                # R2: extends above R1 high (§4.3)
                magnitude = price - self._last_swing_low_price
                self._r2_magnitude = prev.magnitude
                level = LevelInfo(
                    level_type="R2",
                    start_bar=bar_index,
                    confirmed_bar=bar_index,
                    magnitude=magnitude,
                    at_ema_50=self._at_ema_50(price),
                    at_ema_200=self._at_ema_200(price),
                    at_period_extreme=self._pct_diff(price, period_high) <= NEAR_THRESHOLD,
                )
                self.levels.append(level)
                self.current_state = LevelState.R2
                return level

        if count == 3 and len(self.levels) >= 2:
            prev = self.levels[-1]  # R2
            magnitude = price - self._last_swing_low_price
            if self._r2_magnitude > 0 and magnitude / self._r2_magnitude >= LEVEL_3_MIN_RATIO:
                # R3: extends above R2, magnitude ≥ 90% of R2, near HiW (§4.3)
                level = LevelInfo(
                    level_type="R3",
                    start_bar=bar_index,
                    confirmed_bar=bar_index,
                    magnitude=magnitude,
                    at_ema_50=self._at_ema_50(price),
                    at_ema_200=self._near_ema_200(price),
                    at_period_extreme=self._pct_diff(price, period_high) <= NEAR_THRESHOLD,
                )
                self.levels.append(level)
                self.current_state = LevelState.R3
                return level
            else:
                # Magnitude < 90% → reset (§4.3)
                self._reset_rise()

        return None

    # ------------------------------------------------------------------
    # Drop confirmation helpers
    # ------------------------------------------------------------------

    def _confirm_drop(
        self, bar_index: int, price: float, period_low: float
    ) -> Optional[LevelInfo]:
        self.current_drop_count += 1
        count = self.current_drop_count

        if count == 1:
            level = LevelInfo(
                level_type="D1",
                start_bar=bar_index,
                confirmed_bar=bar_index,
                magnitude=self._last_swing_high_price - price,
                at_ema_50=self._at_ema_50(price),
                at_ema_200=self._at_ema_200(price),
                at_period_extreme=self._pct_diff(price, period_low) <= NEAR_THRESHOLD,
            )
            self.levels.append(level)
            self.current_state = LevelState.D1
            return level

        if count == 2 and self.levels:
            prev = self.levels[-1]
            if price < prev.confirmed_bar:
                magnitude = self._last_swing_high_price - price
                self._d2_magnitude = prev.magnitude
                level = LevelInfo(
                    level_type="D2",
                    start_bar=bar_index,
                    confirmed_bar=bar_index,
                    magnitude=magnitude,
                    at_ema_50=self._at_ema_50(price),
                    at_ema_200=self._at_ema_200(price),
                    at_period_extreme=self._pct_diff(price, period_low) <= NEAR_THRESHOLD,
                )
                self.levels.append(level)
                self.current_state = LevelState.D2
                return level

        if count == 3 and len(self.levels) >= 2:
            prev = self.levels[-1]
            magnitude = self._last_swing_high_price - price
            if self._d2_magnitude > 0 and magnitude / self._d2_magnitude >= LEVEL_3_MIN_RATIO:
                level = LevelInfo(
                    level_type="D3",
                    start_bar=bar_index,
                    confirmed_bar=bar_index,
                    magnitude=magnitude,
                    at_ema_50=self._at_ema_50(price),
                    at_ema_200=self._near_ema_200(price),
                    at_period_extreme=self._pct_diff(price, period_low) <= NEAR_THRESHOLD,
                )
                self.levels.append(level)
                self.current_state = LevelState.D3
                return level
            else:
                self._reset_drop()

        return None

    # ------------------------------------------------------------------
    # Reset helpers
    # ------------------------------------------------------------------

    def _reset_rise(self) -> None:
        """Reset rise sequence (magnitude too small for R3 — §4.3)."""
        self.current_rise_count = 0
        self.current_state = LevelState.NO_LEVEL

    def _reset_drop(self) -> None:
        """Reset drop sequence (magnitude too small for D3 — §4.3)."""
        self.current_drop_count = 0
        self.current_state = LevelState.NO_LEVEL

    def reset(self) -> None:
        """Full reset of the counter."""
        self.current_state = LevelState.NO_LEVEL
        self.current_rise_count = 0
        self.current_drop_count = 0
        self.levels.clear()
        self._r2_magnitude = 0.0
        self._d2_magnitude = 0.0

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_current_levels(self) -> Dict[str, LevelInfo]:
        """Return current active levels (last 3: R1–R3 or D1–D3)."""
        result: Dict[str, LevelInfo] = {}
        for lvl in self.levels[-3:]:
            result[lvl.level_type] = lvl
        return result


def feed_cross_tf(
    lower_tf_levels: Dict[str, LevelInfo],
    lower_tf_count: int = 3,
    upper_tf_levels: Optional[Dict[str, LevelInfo]] = None,
) -> Dict[str, LevelInfo]:
    """Cross-timeframe feeding (§4.2).

    Rule: 3 × M15 levels = 1 × H1 level.
    Counts lower-TF levels and maps them to upper-TF equivalents.
    """
    rise_levels = sorted(
        [v for v in lower_tf_levels.values() if v.level_type.startswith("R")],
        key=lambda x: x.level_type,
    )
    drop_levels = sorted(
        [v for v in lower_tf_levels.values() if v.level_type.startswith("D")],
        key=lambda x: x.level_type,
    )

    result: Dict[str, LevelInfo] = {}
    if upper_tf_levels:
        result.update(upper_tf_levels)

    # Map 3 lower TF rises → 1 upper TF rise
    rise_tf_level = len(rise_levels) // lower_tf_count
    if rise_tf_level >= 1:
        key = f"R{rise_tf_level}"
        if key not in result:
            # Aggregate magnitude
            agg = rise_levels[: rise_tf_level * lower_tf_count]
            total_mag = sum(l.magnitude for l in agg)
            result[key] = LevelInfo(
                level_type=key,
                start_bar=agg[0].start_bar,
                confirmed_bar=agg[-1].confirmed_bar or agg[-1].start_bar,
                magnitude=total_mag,
            )

    # Map 3 lower TF drops → 1 upper TF drop
    drop_tf_level = len(drop_levels) // lower_tf_count
    if drop_tf_level >= 1:
        key = f"D{drop_tf_level}"
        if key not in result:
            agg = drop_levels[: drop_tf_level * lower_tf_count]
            total_mag = sum(l.magnitude for l in agg)
            result[key] = LevelInfo(
                level_type=key,
                start_bar=agg[0].start_bar,
                confirmed_bar=agg[-1].confirmed_bar or agg[-1].start_bar,
                magnitude=total_mag,
            )

    return result
