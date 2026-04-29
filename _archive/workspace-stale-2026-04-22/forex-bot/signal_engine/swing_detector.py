"""
Swing detection using N-bar lookback.

A swing high is a bar whose high exceeds all highs within `lookback` bars on either side.
A swing low is a bar whose low is below all lows within `lookback` bars on either side.

Spec reference: TTC Signal Confidence Engine §3
"""

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np


@dataclass
class SwingHigh:
    bar_index: int
    price: float


@dataclass
class SwingLow:
    bar_index: int
    price: float


def detect_swings(
    highs: np.ndarray,
    lows: np.ndarray,
    lookback: int = 5,
) -> Tuple[List[SwingHigh], List[SwingLow]]:
    """Identify swing highs and lows using N-bar lookback (§3.1).

    Args:
        highs: Array of bar high prices.
        lows: Array of bar low prices.
        lookback: Number of bars on each side to check (default 5).

    Returns:
        Tuple of (swing_highs, swing_lows).

    Edge cases (§3.2):
        - Equal highs/lows within 0.05% → treat as single swing (skip duplicate).
        - Peaks 0.05%-1.5% apart → two distinct swings (valid G1 symmetry).
        - Inside bar → cannot be a swing (high ≤ prev high and low ≥ prev low).
        - Outside bar → evaluated normally.
    """
    swing_highs: List[SwingHigh] = []
    swing_lows: List[SwingLow] = []

    n = len(highs)
    for i in range(lookback, n - lookback):
        # Inside bar check — inside bars cannot be swings (§3.2)
        if highs[i] <= highs[i - 1] and lows[i] >= lows[i - 1]:
            continue

        # --- Swing high ---
        is_swing_high = True
        for j in range(1, lookback + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_swing_high = False
                break

        if is_swing_high:
            # Equal highs within 0.05% → single swing (§3.2)
            if swing_highs and abs(highs[i] - swing_highs[-1].price) / highs[i] < 0.0005:
                continue
            swing_highs.append(SwingHigh(bar_index=i, price=float(highs[i])))

        # --- Swing low ---
        is_swing_low = True
        for j in range(1, lookback + 1):
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_swing_low = False
                break

        if is_swing_low:
            # Equal lows within 0.05% → single swing (§3.2)
            if swing_lows and abs(lows[i] - swing_lows[-1].price) / lows[i] < 0.0005:
                continue
            swing_lows.append(SwingLow(bar_index=i, price=float(lows[i])))

    return swing_highs, swing_lows


def get_last_n_swings(
    swing_highs: List[SwingHigh],
    swing_lows: List[SwingLow],
    n: int = 5,
) -> dict:
    """Get the last N swing highs and lows for pattern detection."""
    return {
        "swing_highs": swing_highs[-n:] if swing_highs else [],
        "swing_lows": swing_lows[-n:] if swing_lows else [],
    }
