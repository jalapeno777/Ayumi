"""
HTF (Higher Timeframe) Context Analyzer.

Implements §4.4-4.6 of the Signal & Confidence Engine spec.

Outputs:
- htf_phase: categorical ("aligned", "conflicting", "consolidating", "exhaustion", "neutral")
- htf_modifier: numeric (-0.25 to +0.15) used by confluence scorer
- mtf_alignment_score: 0.0-1.0 based on D1/H4/H1/M15 agreement
"""
from dataclasses import dataclass
from typing import Tuple
from enum import Enum
import numpy as np


class HTFPhase(Enum):
    ALIGNED = "aligned"              # HTF direction matches LTF pattern (§4.4)
    CONFLICTING = "conflicting"      # HTF opposes LTF
    CONSOLIDATING = "consolidating"  # HTF is flat/range
    EXHAUSTION = "exhaustion"        # D1 at R3/D3 (§4.4)
    NEUTRAL = "neutral"              # No clear bias


@dataclass
class HTFContext:
    phase: HTFPhase
    modifier: float       # Range: -0.25 to +0.15 per §4.4 Output B
    mtf_alignment: float  # 0.0-1.0 per §4.5 table
    h4_range_pct: float   # H4 range as % of price (for consolidation check)
    is_consolidating: bool
    direction: str        # "bullish", "bearish", or "neutral"


# Modifier mapping per §4.4 Output B
_PHASE_MODIFIERS = {
    HTFPhase.ALIGNED: +0.15,
    HTFPhase.CONFLICTING: -0.25,
    HTFPhase.CONSOLIDATING: -0.15,
    HTFPhase.EXHAUSTION: +0.10,
    HTFPhase.NEUTRAL: -0.05,
}


def _calculate_ema(closes: np.ndarray, period: int = 50) -> np.ndarray:
    """Calculate EMA using standard exponential smoothing."""
    if len(closes) < period:
        # Fall back to SMA if insufficient data
        return np.full_like(closes, np.mean(closes[-min(len(closes), period):]))
    multiplier = 2.0 / (period + 1)
    ema = np.copy(closes[:period].astype(float))
    ema[0] = np.mean(closes[:period])
    for i in range(1, period):
        ema[i] = closes[i] * multiplier + ema[i - 1] * (1 - multiplier)
    for i in range(period, len(closes)):
        ema = np.append(ema, closes[i] * multiplier + ema[-1] * (1 - multiplier))
    return ema


def _detect_direction(bars: np.ndarray, lookback: int = 20) -> str:
    """
    Determine directional bias from OHLC bars.
    
    Uses 50 EMA slope and recent price position relative to EMA.
    Returns "bullish", "bearish", or "neutral".
    """
    if bars is None or len(bars) < 5:
        return "neutral"

    closes = bars[-lookback:, 3]  # Close is column index 3
    ema = _calculate_ema(closes, period=min(50, len(closes)))
    
    # EMA slope: compare current EMA to EMA 5 bars ago
    if len(ema) >= 6:
        slope = (ema[-1] - ema[-6]) / ema[-6]
    else:
        slope = 0.0
    
    # Price position relative to EMA
    price_vs_ema = (closes[-1] - ema[-1]) / ema[-1]
    
    if slope > 0.001 and price_vs_ema > 0:
        return "bullish"
    elif slope < -0.001 and price_vs_ema < 0:
        return "bearish"
    return "neutral"


def _check_d1_exhaustion(d1_bars: np.ndarray) -> bool:
    """
    Check if D1 is at R3/D3 (exhaustion zone) per §4.4.
    
    D3/R3 exhaustion: price within 0.5% of the D1 period low or high
    (LoD/HoD). Uses the last 20 D1 bars as the period.
    """
    if d1_bars is None or len(d1_bars) < 10:
        return False
    
    recent = d1_bars[-20:]
    period_high = np.max(recent[:, 1])  # High is column index 1
    period_low = np.min(recent[:, 2])   # Low is column index 2
    current_close = d1_bars[-1, 3]
    
    threshold = 0.005  # 0.5% per glossary "near"
    
    near_high = (period_high - current_close) / period_high < threshold
    near_low = (current_close - period_low) / period_low < threshold
    
    return near_high or near_low


def _check_h4_consolidation(h4_bars: np.ndarray, lookback: int = 20) -> Tuple[bool, float]:
    """
    Check H4 consolidation per §4.4 Phase 1:
    - Range ≤ 0.5% over 20 bars
    - |50 EMA slope| < 0.0001
    
    Returns (is_consolidating, range_pct).
    """
    if h4_bars is None or len(h4_bars) < 5:
        return False, 0.0
    
    recent = h4_bars[-lookback:]
    high = np.max(recent[:, 1])
    low = np.min(recent[:, 2])
    mid = (high + low) / 2.0
    
    range_pct = (high - low) / mid if mid > 0 else 0.0
    
    closes = recent[:, 3]
    ema = _calculate_ema(closes, period=min(50, len(closes)))
    
    if len(ema) >= 6:
        slope = abs((ema[-1] - ema[-6]) / ema[-6])
    else:
        slope = 0.0
    
    is_consolidating = range_pct <= 0.005 and slope < 0.0001
    return is_consolidating, range_pct


def analyze_htf_context(
    d1_bars: np.ndarray,    # D1 OHLC data (fewer bars, longer timeframe)
    h4_bars: np.ndarray,    # H4 OHLC data
    h1_bars: np.ndarray,    # H1 OHLC data
    m15_bars: np.ndarray,   # M15 OHLC data
    current_bar_idx: int,   # Index of current bar on M15
) -> HTFContext:
    """
    Analyze HTF context before evaluating LTF patterns.
    
    Phase 1 consolidation check (§4.4): H4 range ≤ 0.5% over 20 bars + |50 EMA slope| < 0.0001.
    Full boardroom detection deferred to Phase 3+ (§4.4 note).
    
    OHLC format: numpy array where columns are [open, high, low, close].
    
    Returns HTFContext with phase, modifier, MTF alignment, and direction.
    """
    # Determine direction on each timeframe
    d1_direction = _detect_direction(d1_bars)
    h4_direction = _detect_direction(h4_bars)
    h1_direction = _detect_direction(h1_bars)
    m15_direction = _detect_direction(m15_bars[:current_bar_idx + 1])
    
    # Check H4 consolidation (§4.4 Phase 1)
    is_consolidating, h4_range_pct = _check_h4_consolidation(h4_bars)
    
    # Check D1 exhaustion (§4.4)
    is_exhaustion = _check_d1_exhaustion(d1_bars)
    
    # Determine HTF phase
    if is_consolidating:
        phase = HTFPhase.CONSOLIDATING
        direction = "neutral"
    elif is_exhaustion:
        phase = HTFPhase.EXHAUSTION
        # Direction at exhaustion: near high = bearish (reversal), near low = bullish (reversal)
        direction = h4_direction if h4_direction != "neutral" else d1_direction
    else:
        # Determine if aligned or conflicting based on HTF vs LTF
        htf_dir = h4_direction if h4_direction != "neutral" else d1_direction
        ltf_dir = h1_direction if h1_direction != "neutral" else m15_direction
        
        if htf_dir == "neutral" and ltf_dir == "neutral":
            phase = HTFPhase.NEUTRAL
            direction = "neutral"
        elif htf_dir == ltf_dir:
            phase = HTFPhase.ALIGNED
            direction = htf_dir
        elif htf_dir == "neutral":
            phase = HTFPhase.NEUTRAL
            direction = ltf_dir
        else:
            phase = HTFPhase.CONFLICTING
            direction = htf_dir
    
    # Calculate MTF alignment (§4.5)
    mtf_alignment = calculate_mtf_alignment(
        d1_direction, h4_direction, h1_direction, m15_direction
    )
    
    modifier = _PHASE_MODIFIERS[phase]
    
    return HTFContext(
        phase=phase,
        modifier=modifier,
        mtf_alignment=mtf_alignment,
        h4_range_pct=h4_range_pct,
        is_consolidating=is_consolidating,
        direction=direction,
    )


def calculate_mtf_alignment(
    d1_direction: str,
    h4_direction: str,
    h1_direction: str,
    m15_direction: str,
) -> float:
    """
    Calculate multi-timeframe alignment score per §4.5.
    
    Direction of agreement matters: H1 bullish + H4 bullish + D1 bearish
    counts as 2/4 (0.50), NOT 3/4. Agreement requires same direction.
    
    | TF Agreement                  | Score |
    |-------------------------------|-------|
    | All 4 TFs agree               | 1.0   |
    | 3/4 TFs agree (incl. H4)      | 0.75  |
    | 2/4 TFs agree (incl. H1+H4)  | 0.50  |
    | 2/4 TFs agree (only LTFs)     | 0.25  |
    | 0-1/4 TFs agree               | 0.0   |
    """
    directions = [d1_direction, h4_direction, h1_direction, m15_direction]
    bullish_count = sum(1 for d in directions if d == "bullish")
    bearish_count = sum(1 for d in directions if d == "bearish")
    neutral_count = sum(1 for d in directions if d == "neutral")
    
    # All 4 agree (same non-neutral direction)
    if bullish_count == 4 or bearish_count == 4:
        return 1.0
    
    # 3/4 agree
    if bullish_count == 3 or bearish_count == 3:
        # §4.5 note: "incl. H4" — H4 must be among the agreeing TFs
        if bullish_count == 3 and h4_direction == "bullish":
            return 0.75
        if bearish_count == 3 and h4_direction == "bearish":
            return 0.75
        # H4 is the dissenting voice — degraded
        return 0.50
    
    # 2/4 agree
    if bullish_count == 2 or bearish_count == 2:
        # Check if H1 + H4 agree (§4.5: "incl. H1+H4" = 0.50)
        if h4_direction != "neutral" and h1_direction == h4_direction:
            return 0.50
        # Only LTFs agree (§4.5: 0.25)
        if m15_direction != "neutral" and h1_direction == m15_direction and \
           (h4_direction == "neutral" or h4_direction != h1_direction):
            return 0.25
        # Scattered agreement (HTF disagrees)
        return 0.25
    
    # 0-1 agree
    return 0.0
