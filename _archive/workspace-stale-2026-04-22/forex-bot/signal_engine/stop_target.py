"""
Stop Loss & Target Placement — §9.

Stop Rules (priority order):
1. Cover the vector — beyond the most recent vector candle body extreme (not wick)
2. Beyond the SVC candle — if SVC present at entry, beyond SVC body extreme
3. Beyond the formation extreme — SL2 for W, SH2 for M (FL-001 exception: first peak)
4. Beyond the counted level — the level the pattern is at
5. ATR-based (last resort) — 1.5 × ATR(14) from entry

Target Rules (priority order):
1. Unrecovered vector candle — first vector candle in trade direction not yet recovered
2. Next counted level — R1→50 EMA, R2→200 EMA
3. Liquidity pool — prior highs/lows where trapped positions exist
4. Mean reversion — middle of daily range (NYC reversal setups)
5. Fib confluence level — 50% fib aligns with TBD level

3:1 minimum R:R filter (gate requirement).
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum
import numpy as np


class StopBasis(Enum):
    COVER_VECTOR = "cover_vector"
    BEYOND_SVC = "beyond_svc"
    BEYOND_FORMATION = "beyond_formation"
    BEYOND_LEVEL = "beyond_level"
    ATR = "atr"


class TargetBasis(Enum):
    UNRECOVERED_VECTOR = "unrecovered_vector"
    NEXT_LEVEL = "next_level"
    LIQUIDITY_POOL = "liquidity_pool"
    MEAN_REVERSION = "mean_reversion"
    FIB_CONFLUENCE = "fib_confluence"


@dataclass
class StopLossPlan:
    """Stop loss placement plan — see §9.1 for priority rules."""
    price: float
    basis: StopBasis
    pips: float
    method: str
    atr_14: Optional[float] = None  # For ATR-based stops
    vector_candle_idx: Optional[int] = None  # For cover-vector method


@dataclass
class TargetPlan:
    """Target placement plan — see §9.2 for priority rules."""
    level: str  # "tp1", "tp2", "tp3", "natural"
    price: float
    rr: float  # R:R from stop to this target
    basis: TargetBasis
    basis_description: str
    pct_of_range: Optional[float] = None  # For mean reversion


@dataclass
class StopTargetResult:
    """Combined stop/target result with validation — see §9.4."""
    entry_price: float
    stop_loss: StopLossPlan
    targets: List[TargetPlan]
    rr_natural: float  # Natural R:R (stop to first target)
    rr_to_stop: float  # Stop distance in pips
    valid: bool
    invalid_reason: Optional[str] = None


def _avoid_round_number(price: float, direction: str) -> float:
    """Avoid placing stops at exact round numbers (§9.1 safety rule)."""
    # Round to 2 decimals (pip level for JPY pairs) or 4 decimals
    rounded = round(price, 4)
    remainder = rounded % 0.005
    if remainder == 0 and direction == "long":
        return rounded - 0.0002
    elif remainder == 0 and direction == "short":
        return rounded + 0.0002
    return rounded


def calculate_stop_loss(
    entry_price: float,
    direction: str,  # "long" or "short"
    formation,  # MWFormation object
    svc_present: bool,
    svc_candle: Optional[dict] = None,  # SVC candle data if present
    vector_candle: Optional[dict] = None,  # Most recent vector candle
    level_at_formation: Optional[str] = None,  # R1/R2/R3/D1/D2/D3
    level_price: Optional[float] = None,
    atr_14: Optional[float] = None,
    highs: Optional[np.ndarray] = None,
    lows: Optional[np.ndarray] = None,
    closes: Optional[np.ndarray] = None,
) -> StopLossPlan:
    """
    Calculate stop loss using priority order from §9.1.

    Priority: cover_vector > beyond_svc > beyond_formation > beyond_level > atr

    Never place stops at:
    - Exact round numbers
    - Exact prior highs/lows without vector buffer
    - Inside the formation
    - Bright heat map clusters
    """
    if direction == "long":
        # 1. Cover the vector — §9.1 rule 1
        if vector_candle is not None:
            vector_low = vector_candle.get('low', vector_candle.get('body_low'))
            stop_price = _avoid_round_number(vector_low - 0.0001, direction)
            pips = (entry_price - stop_price) * 10000
            return StopLossPlan(
                price=stop_price, basis=StopBasis.COVER_VECTOR,
                pips=pips, method="cover_vector",
                vector_candle_idx=vector_candle.get('bar_idx')
            )

        # 2. Beyond SVC candle — §9.1 rule 2
        if svc_present and svc_candle is not None:
            svc_low = svc_candle.get('low')
            stop_price = _avoid_round_number(svc_low - 0.0001, direction)
            pips = (entry_price - stop_price) * 10000
            return StopLossPlan(
                price=stop_price, basis=StopBasis.BEYOND_SVC,
                pips=pips, method="beyond_svc_candle"
            )

        # 3. Beyond formation extreme (SL2 for W) — §9.1 rule 3
        if formation and hasattr(formation, 'second_peak_idx'):
            sl2_price = formation.swing_low_2_price
            stop_price = _avoid_round_number(sl2_price - 0.0002, direction)
            pips = (entry_price - stop_price) * 10000
            return StopLossPlan(
                price=stop_price, basis=StopBasis.BEYOND_FORMATION,
                pips=pips, method="beyond_sl2"
            )

        # 4. Beyond counted level — §9.1 rule 4
        if level_price is not None:
            stop_price = _avoid_round_number(level_price - 0.0002, direction)
            pips = (entry_price - stop_price) * 10000
            return StopLossPlan(
                price=stop_price, basis=StopBasis.BEYOND_LEVEL,
                pips=pips, method="beyond_level"
            )

        # 5. ATR-based last resort — §9.1 rule 5
        if atr_14 is not None:
            stop_price = _avoid_round_number(entry_price - 1.5 * atr_14, direction)
            pips = 1.5 * atr_14 * 10000
            return StopLossPlan(
                price=stop_price, basis=StopBasis.ATR,
                pips=pips, method="1.5x_ATR14",
                atr_14=atr_14
            )

    else:  # short
        # 1. Cover the vector — §9.1 rule 1
        if vector_candle is not None:
            vector_high = vector_candle.get('high', vector_candle.get('body_high'))
            stop_price = _avoid_round_number(vector_high + 0.0001, direction)
            pips = (stop_price - entry_price) * 10000
            return StopLossPlan(
                price=stop_price, basis=StopBasis.COVER_VECTOR,
                pips=pips, method="cover_vector",
                vector_candle_idx=vector_candle.get('bar_idx')
            )

        # 2. Beyond SVC candle — §9.1 rule 2
        if svc_present and svc_candle is not None:
            svc_high = svc_candle.get('high')
            stop_price = _avoid_round_number(svc_high + 0.0001, direction)
            pips = (stop_price - entry_price) * 10000
            return StopLossPlan(
                price=stop_price, basis=StopBasis.BEYOND_SVC,
                pips=pips, method="beyond_svc_candle"
            )

        # 3. Beyond formation extreme (SH2 for M) — §9.1 rule 3
        if formation and hasattr(formation, 'second_peak_idx'):
            sh2_price = formation.swing_high_2_price
            stop_price = _avoid_round_number(sh2_price + 0.0002, direction)
            pips = (stop_price - entry_price) * 10000
            return StopLossPlan(
                price=stop_price, basis=StopBasis.BEYOND_FORMATION,
                pips=pips, method="beyond_sh2"
            )

        # 4. Beyond counted level — §9.1 rule 4
        if level_price is not None:
            stop_price = _avoid_round_number(level_price + 0.0002, direction)
            pips = (stop_price - entry_price) * 10000
            return StopLossPlan(
                price=stop_price, basis=StopBasis.BEYOND_LEVEL,
                pips=pips, method="beyond_level"
            )

        # 5. ATR-based last resort — §9.1 rule 5
        if atr_14 is not None:
            stop_price = _avoid_round_number(entry_price + 1.5 * atr_14, direction)
            pips = 1.5 * atr_14 * 10000
            return StopLossPlan(
                price=stop_price, basis=StopBasis.ATR,
                pips=pips, method="1.5x_ATR14",
                atr_14=atr_14
            )

    raise ValueError("Could not calculate stop loss — no data provided")


def calculate_targets(
    entry_price: float,
    direction: str,
    stop_loss: StopLossPlan,
    levels: Dict[str, float],  # {"R1": price, "R2": price, "R3": price, "D1": price, ...}
    ema_50: float,
    ema_200: float,
    atr_14: Optional[float] = None,
    setup_type: str = "multi_session",  # "multi_session" or "scalp"
) -> List[TargetPlan]:
    """
    Calculate target levels per §9.2.

    Multi-session trades (§9.3):
    - 1:1 R:R → close 25%, move stop to BE
    - 3:1 R:R → close 25%, trail remaining
    - Natural target → close remaining 50%

    Scalp trades (§9.3):
    - 1:1 R:R → close 50%, move stop to BE
    - 2:1 R:R → close 25%, trail remaining
    - Natural target → close remaining 25%
    """
    targets = []
    stop_distance = stop_loss.pips / 10000  # Convert pips to price

    if direction == "long":
        # TP1: R1 / 50 EMA — §9.2 rule 2
        tp1_price = levels["R1"] if "R1" in levels else ema_50
        tp1_rr = (tp1_price - entry_price) / stop_distance
        targets.append(TargetPlan(
            level="tp1", price=tp1_price, rr=tp1_rr,
            basis=TargetBasis.NEXT_LEVEL,
            basis_description="first target at R1/50 EMA"
        ))

        # TP2: R2 / 200 EMA — §9.2 rule 2
        tp2_price = levels["R2"] if "R2" in levels else ema_200
        tp2_rr = (tp2_price - entry_price) / stop_distance
        targets.append(TargetPlan(
            level="tp2", price=tp2_price, rr=tp2_rr,
            basis=TargetBasis.NEXT_LEVEL,
            basis_description="second target at R2/200 EMA"
        ))

        # TP3: R3 / period extreme — §9.2 rule 2
        tp3_price = levels["R3"] if "R3" in levels else entry_price + 3 * stop_distance
        tp3_rr = (tp3_price - entry_price) / stop_distance
        targets.append(TargetPlan(
            level="tp3", price=tp3_price, rr=tp3_rr,
            basis=TargetBasis.NEXT_LEVEL,
            basis_description="third target at R3/period extreme"
        ))

    else:  # short
        # TP1: D1 / 50 EMA — §9.2 rule 2
        tp1_price = levels["D1"] if "D1" in levels else ema_50
        tp1_rr = (entry_price - tp1_price) / stop_distance
        targets.append(TargetPlan(
            level="tp1", price=tp1_price, rr=tp1_rr,
            basis=TargetBasis.NEXT_LEVEL,
            basis_description="first target at D1/50 EMA"
        ))

        # TP2: D2 / 200 EMA — §9.2 rule 2
        tp2_price = levels["D2"] if "D2" in levels else ema_200
        tp2_rr = (entry_price - tp2_price) / stop_distance
        targets.append(TargetPlan(
            level="tp2", price=tp2_price, rr=tp2_rr,
            basis=TargetBasis.NEXT_LEVEL,
            basis_description="second target at D2/200 EMA"
        ))

        # TP3: D3 / period extreme — §9.2 rule 2
        tp3_price = levels["D3"] if "D3" in levels else entry_price - 3 * stop_distance
        tp3_rr = (entry_price - tp3_price) / stop_distance
        targets.append(TargetPlan(
            level="tp3", price=tp3_price, rr=tp3_rr,
            basis=TargetBasis.NEXT_LEVEL,
            basis_description="third target at D3/period extreme"
        ))

    return targets


def validate_rr_minimum(
    targets: List[TargetPlan],
    stop_loss: StopLossPlan,
    min_rr: float = 3.0,
) -> Tuple[bool, Optional[str]]:
    """
    Gate check: natural target must be ≥ 3:1 R:R — §9.4.

    Returns (valid, reason_if_invalid).
    """
    if not targets:
        return False, "No targets defined"

    natural_rr = max(t.rr for t in targets)
    if natural_rr < min_rr:
        return False, f"Natural R:R {natural_rr:.2f} < minimum {min_rr}"

    return True, None


def calculate_partial_exits(
    targets: List[TargetPlan],
    stop_loss: StopLossPlan,
    setup_type: str = "multi_session",
    position_size: float = 1.0,  # Full position size (normalized)
) -> List[dict]:
    """
    Generate partial exit plan per §9.3.

    Multi-session:
    - TP1 (1:1) → close 25%, move stop to BE
    - TP2 (3:1) → close 25%, trail
    - TP3 (natural) → close remaining 50%

    Scalp:
    - TP1 (1:1) → close 50%, move stop to BE
    - TP2 (2:1) → close 25%, trail
    - TP3 (natural) → close remaining 25%
    """
    exits = []
    is_scalp = setup_type in ("single_session", "scalp", "asia_liquidity_grab")

    if is_scalp:
        if len(targets) >= 1:
            exits.append({
                "at": "tp1", "rr": targets[0].rr,
                "close_pct": 0.50, "action": "close_50pct_move_sl_to_be",
                "trail": False,
            })
        if len(targets) >= 2:
            exits.append({
                "at": "tp2", "rr": targets[1].rr,
                "close_pct": 0.25, "action": "close_25pct_trail",
                "trail": True,
            })
        if len(targets) >= 3:
            exits.append({
                "at": "tp3", "rr": targets[2].rr,
                "close_pct": 0.25, "action": "close_remaining",
                "trail": False,
            })
    else:
        if len(targets) >= 1:
            exits.append({
                "at": "tp1", "rr": targets[0].rr,
                "close_pct": 0.25, "action": "close_25pct_move_sl_to_be",
                "trail": False,
            })
        if len(targets) >= 2:
            exits.append({
                "at": "tp2", "rr": targets[1].rr,
                "close_pct": 0.25, "action": "close_25pct_trail",
                "trail": True,
            })
        if len(targets) >= 3:
            exits.append({
                "at": "tp3", "rr": targets[2].rr,
                "close_pct": 0.50, "action": "close_remaining",
                "trail": False,
            })

    return exits
