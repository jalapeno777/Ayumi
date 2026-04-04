from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


import pandas as pd

from ml.features import BiasDirection, ICTSignal


class CSharpTradeDirection(Enum):
    Long = 0
    Short = 1
    Neutral = 2


class CSharpSignalStrength(Enum):
    Weak = 0
    Moderate = 1
    Strong = 2
    VeryStrong = 3


class CSharpSessionType(Enum):
    London = 0
    NYAM = 1
    NYPM = 2
    Outside = 3


@dataclass
class CSharpConfluenceSignal:
    Direction: int
    Strength: int
    ConfidenceScore: float
    EntryPrice: float
    StopLoss: float
    TakeProfit1: float
    TakeProfit2: float
    TakeProfit3: float
    SignalTime: str
    EntryTimeFrame: int
    Rationale: str
    HasOrderBlock: bool
    HasFVG: bool
    HasLiquiditySweep: bool
    HasPremiumDiscountConfluence: bool
    HasStructureAlignment: bool
    ConfluenceCount: int
    RiskRewardRatio: float


def _direction_from_csharp(csharp_dir: int) -> BiasDirection:
    if csharp_dir == 0:
        return BiasDirection.BULLISH
    elif csharp_dir == 1:
        return BiasDirection.BEARISH
    else:
        return BiasDirection.NEUTRAL


def _session_quality_from_csharp(session: int) -> float:
    return {
        0: 0.8,
        1: 0.9,
        2: 0.6,
        3: 0.1,
    }.get(session, 0.1)


def csharp_signal_to_ict_signal(csharp_signal: CSharpConfluenceSignal) -> ICTSignal:
    return ICTSignal(
        timestamp=datetime.fromisoformat(csharp_signal.SignalTime.replace("Z", "+00:00")),
        bias=_direction_from_csharp(csharp_signal.Direction),
        confidence_score=csharp_signal.ConfidenceScore,
        structure_alignment=csharp_signal.HasStructureAlignment,
        order_block=csharp_signal.HasOrderBlock,
        fvg=csharp_signal.HasFVG,
        liquidity_sweep=csharp_signal.HasLiquiditySweep,
        premium_discount=csharp_signal.HasPremiumDiscountConfluence,
        session_quality=_session_quality_from_csharp(0),
        confluence_count=csharp_signal.ConfluenceCount,
        risk_reward_ratio=csharp_signal.RiskRewardRatio,
    )


def dataframe_to_ict_signals(df: pd.DataFrame) -> list[ICTSignal]:
    if df.empty:
        return []

    signals = []
    for _, row in df.iterrows():
        try:
            direction_map = {"long": 0, "short": 1, "neutral": 2}
            direction = direction_map.get(str(row.get("direction", "neutral")).lower(), 2)

            signals.append(ICTSignal(
                timestamp=row.get("timestamp", datetime.now()),
                bias=_direction_from_csharp(direction),
                confidence_score=float(row.get("confidence_score", 0.0)),
                structure_alignment=bool(row.get("has_structure_alignment", False)),
                order_block=bool(row.get("has_order_block", False)),
                fvg=bool(row.get("has_fvg", False)),
                liquidity_sweep=bool(row.get("has_liquidity_sweep", False)),
                premium_discount=bool(row.get("has_premium_discount", False)),
                session_quality=float(row.get("session_quality", 0.1)),
                confluence_count=int(row.get("confluence_count", 0)),
                risk_reward_ratio=float(row.get("risk_reward_ratio", 0.0)),
            ))
        except (ValueError, TypeError):
            continue

    return signals