"""Market regime detector based on ATR percentile and ADX.

Classifies each bar into one of four regimes and provides conditional
allocation guidance for strategy selection and risk sizing.

Regimes
-------
- **Trending**  — ADX > 25, market is directional.
- **Choppy**    — ADX < 20, market is range-bound.
- **Volatile**  — ATR percentile > 80, risk is elevated.
- **Quiet**     — ATR percentile < 20, opportunity is limited.

Priority when regimes overlap (e.g. high ADX + high ATR):

    VOLATILE > QUIET > TRENDING > CHOPPY

This ensures risk management takes precedence over opportunity.

Public API
----------
- :class ``Regime`` — enum of the four regimes
- :class ``RegimeConfig`` — tunable thresholds
- :class ``RegimeAllocation`` — allocation guidance per regime
- :data ``DEFAULT_ALLOCATIONS`` — mapping of regime → allocation
- :class ``RegimeDetector`` — main detector class

Usage
-----
::

    from regime.detector import RegimeDetector, Regime

    detector = RegimeDetector()
    regimes = detector.detect(highs, lows, closes)   # pd.Series of Regime
    current = detector.detect_current(highs, lows, closes)  # last Regime
    alloc = detector.get_allocation(current)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

import numpy as np
import pandas as pd

from indicators import adx, atr_percentile


# ── Regime enum ────────────────────────────────────────────────────────────


class Regime(str, Enum):
    """Market regime classification."""

    TRENDING = "trending"
    CHOPPY = "choppy"
    VOLATILE = "volatile"
    QUIET = "quiet"


# ── Configuration ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RegimeConfig:
    """Tunable thresholds for regime detection.

    Parameters
    ----------
    adx_period : int
        Lookback for ADX calculation.  Default 14.
    atr_period : int
        Lookback for ATR calculation.  Default 14.
    atr_lookback : int
        Rolling window for ATR percentile ranking.  Default 50.
    trending_adx : float
        ADX above this signals a trending regime.  Default 25.0.
    choppy_adx : float
        ADX below this signals a choppy regime.  Default 20.0.
    volatile_atr_pct : float
        ATR percentile (0–1 scale) above this signals volatile.  Default 0.80.
    quiet_atr_pct : float
        ATR percentile (0–1 scale) below this signals quiet.  Default 0.20.
    """

    adx_period: int = 14
    atr_period: int = 14
    atr_lookback: int = 50
    trending_adx: float = 25.0
    choppy_adx: float = 20.0
    volatile_atr_pct: float = 0.80
    quiet_atr_pct: float = 0.20


# ── Allocation guidance ────────────────────────────────────────────────────


@dataclass(frozen=True)
class RegimeAllocation:
    """Conditional allocation rules for a given regime.

    Attributes
    ----------
    regime : Regime
        The regime this allocation applies to.
    size_multiplier : float
        Fraction of base position size to use (0–1).
    max_concurrent_positions : int
        Maximum simultaneous positions allowed.
    stop_multiplier : float
        Multiplier on base stop distance (e.g. 1.5 = wider stops).
    preferred_strategy_types : list[str]
        Strategy archetypes that perform best in this regime.
    """

    regime: Regime
    size_multiplier: float
    max_concurrent_positions: int
    stop_multiplier: float
    preferred_strategy_types: list[str] = field(default_factory=list)


DEFAULT_ALLOCATIONS: dict[Regime, RegimeAllocation] = {
    Regime.TRENDING: RegimeAllocation(
        regime=Regime.TRENDING,
        size_multiplier=1.0,
        max_concurrent_positions=3,
        stop_multiplier=1.0,
        preferred_strategy_types=["donchian", "breakout", "momentum"],
    ),
    Regime.CHOPPY: RegimeAllocation(
        regime=Regime.CHOPPY,
        size_multiplier=0.75,
        max_concurrent_positions=2,
        stop_multiplier=0.75,
        preferred_strategy_types=["mean_reversion", "bb_rsi", "range"],
    ),
    Regime.VOLATILE: RegimeAllocation(
        regime=Regime.VOLATILE,
        size_multiplier=0.5,
        max_concurrent_positions=1,
        stop_multiplier=1.5,
        preferred_strategy_types=[],
    ),
    Regime.QUIET: RegimeAllocation(
        regime=Regime.QUIET,
        size_multiplier=0.5,
        max_concurrent_positions=1,
        stop_multiplier=1.0,
        preferred_strategy_types=[],
    ),
}


# ── Detector ───────────────────────────────────────────────────────────────


class RegimeDetector:
    """Classify market bars into regimes using ADX and ATR percentile.

    The detector is stateless beyond its configuration — call
    :meth:`detect` with OHLC sequences and receive a ``pd.Series``
    of :class:`Regime` values aligned to the input index.

    Parameters
    ----------
    config : RegimeConfig | None
        Tunable thresholds.  Uses :class:`RegimeConfig` defaults if None.
    allocations : dict[Regime, RegimeAllocation] | None
        Override the default allocation table.
    """

    def __init__(
        self,
        config: RegimeConfig | None = None,
        allocations: dict[Regime, RegimeAllocation] | None = None,
    ) -> None:
        self.config = config or RegimeConfig()
        self._allocations = allocations or DEFAULT_ALLOCATIONS

    # ── Core detection ──────────────────────────────────────────────────

    def detect(
        self,
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
    ) -> pd.Series:
        """Classify each bar into a :class:`Regime`.

        Parameters
        ----------
        highs, lows, closes : Sequence[float]
            OHLC price series of equal length.

        Returns
        -------
        pd.Series
            Series of :class:`Regime` values, same index/length as input.
            Leading bars will be ``NaN`` until indicators warm up.
        """
        cfg = self.config

        adx_series = adx(highs, lows, closes, cfg.adx_period)
        atr_pct = atr_percentile(
            highs, lows, closes, cfg.atr_period, cfg.atr_lookback,
        )

        n = len(closes)
        result = pd.Series([np.nan] * n, index=pd.RangeIndex(n), dtype=object)

        if n == 0:
            return result

        c = pd.Series(closes, dtype=float)
        result.index = c.index

        # Priority 1: Volatile (ATR percentile above threshold)
        volatile_mask = atr_pct > cfg.volatile_atr_pct

        # Priority 2: Quiet (ATR percentile below threshold)
        quiet_mask = atr_pct < cfg.quiet_atr_pct

        # Priority 3: Trending (ADX above threshold, not volatile/quiet)
        trending_mask = (
            (adx_series > cfg.trending_adx) & ~volatile_mask & ~quiet_mask
        )

        # Priority 4: Choppy (ADX below threshold, not volatile/quiet/trending)
        choppy_mask = (
            (adx_series < cfg.choppy_adx)
            & ~volatile_mask
            & ~quiet_mask
            & ~trending_mask
        )

        # Neutral zone (choppy_adx ≤ ADX ≤ trending_adx, normal ATR):
        # lean trending if ADX is rising, choppy if falling.
        adx_slope = adx_series.diff()
        neutral_trending = (
            (adx_series >= cfg.choppy_adx)
            & (adx_series <= cfg.trending_adx)
            & ~volatile_mask
            & ~quiet_mask
            & (adx_slope > 0)
        )
        neutral_choppy = (
            (adx_series >= cfg.choppy_adx)
            & (adx_series <= cfg.trending_adx)
            & ~volatile_mask
            & ~quiet_mask
            & (adx_slope <= 0)
        )

        result[volatile_mask] = Regime.VOLATILE
        result[quiet_mask] = Regime.QUIET
        result[trending_mask] = Regime.TRENDING
        result[choppy_mask] = Regime.CHOPPY
        result[neutral_trending] = Regime.TRENDING
        result[neutral_choppy] = Regime.CHOPPY

        return result

    def detect_current(
        self,
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
    ) -> Regime:
        """Return the regime of the most recent completed bar.

        Falls back to :attr:`Regime.QUIET` if no bars have enough
        data for indicator warm-up.
        """
        series = self.detect(highs, lows, closes)
        valid = series.dropna()
        if valid.empty:
            return Regime.QUIET
        return Regime(valid.iloc[-1])

    # ── Allocation ──────────────────────────────────────────────────────

    def get_allocation(self, regime: Regime) -> RegimeAllocation:
        """Return the allocation guidance for *regime*.

        Falls back to the QUIET allocation if *regime* is unknown.
        """
        return self._allocations.get(regime, DEFAULT_ALLOCATIONS[Regime.QUIET])

    def get_current_allocation(
        self,
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
    ) -> RegimeAllocation:
        """Detect the current regime and return its allocation guidance."""
        return self.get_allocation(self.detect_current(highs, lows, closes))


__all__ = [
    "Regime",
    "RegimeConfig",
    "RegimeAllocation",
    "DEFAULT_ALLOCATIONS",
    "RegimeDetector",
]
