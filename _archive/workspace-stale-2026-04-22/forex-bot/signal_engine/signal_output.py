"""
Signal Output — Structured JSON for strategy engine (§10).

Schema version of the signal object that gets passed to the backtest bridge
and eventually to the paper trader / live execution layer.

Each TradingSignal captures: the setup identification, gate results,
entry/stop/target plan, and a full confidence breakdown for audit.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
import json
import uuid


class SignalVariant(Enum):
    """Market variant — determines which ruleset to apply (§10)."""
    FOREX = "forex"
    CRYPTO = "crypto"


class SetupType(Enum):
    """Recognized setup patterns (§2, §3)."""
    MULTI_SESSION_W = "multi_session_w"
    MULTI_SESSION_M = "multi_session_m"
    SINGLE_SESSION_W = "single_session_w"
    SINGLE_SESSION_M = "single_session_m"
    SVC = "svc"
    TRAP = "trap"
    ASIA_LIQUIDITY_GRAB = "asia_liquidity_grab"
    CONTINUATION_RESET = "continuation_reset"


class EntryType(Enum):
    """Entry execution method (§9)."""
    ZONE = "zone"
    MARKET = "market"
    LIMIT = "limit"
    RETEST = "retest"


class StopBasis(Enum):
    """Stop-loss placement rationale (§9)."""
    COVER_VECTOR = "cover_vector"
    BEYOND_SVC = "beyond_svc"
    BEYOND_FORMATION = "beyond_formation"
    BEYOND_LEVEL = "beyond_level"
    ATR = "atr"


class TargetLevel(Enum):
    """Take-profit target tiers."""
    TP1 = "tp1"
    TP2 = "tp2"
    TP3 = "tp3"
    NATURAL = "natural"


@dataclass
class GateSummary:
    """Results from the gate-checking phase (§5, §6)."""
    passed: bool
    universal: Dict[str, bool]
    pattern_specific: Dict[str, Any]
    strategy_specific: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EntryPlan:
    """Entry execution plan (§9)."""
    type: EntryType
    price_low: float
    price_high: float
    trigger: str
    timeframe: str
    limit_price: Optional[float] = None  # For limit entries


@dataclass
class StopLossPlan:
    """Stop-loss placement plan (§9)."""
    price: float
    basis: StopBasis
    pips: float
    method: str
    atr_value: Optional[float] = None


@dataclass
class TargetPlan:
    """Individual take-profit target (§9)."""
    level: TargetLevel
    price: float
    rr: float  # Risk:Reward ratio at this target
    action: str  # e.g., "close_25pct_move_sl_to_be"
    reached: bool = False


@dataclass
class ConfidenceBreakdown:
    """Full confidence scoring audit trail (§7, §8)."""
    base_confidence: float
    htf_modifier: float
    interaction_bonuses: List[str]
    weekly_offset: float
    final_confidence: float
    factor_weights: Dict[str, float]


@dataclass
class TradingSignal:
    """
    Complete trading signal — the canonical output of the confidence engine (§10).

    Serializes to JSON for the backtest bridge and execution layer.
    """

    signal_id: str
    timestamp: str              # ISO-8601
    instrument: str
    direction: str              # "long" or "short"
    setup_type: SetupType
    setup_subtype: str          # "conservative" or "aggressive"
    confidence: float
    action: str                 # "strong", "moderate", "gray_zone", "no_trade"
    variant: SignalVariant

    # Gate results
    gates: GateSummary

    # Entry / stop / target plan
    entry: EntryPlan
    stop_loss: StopLossPlan
    targets: List[TargetPlan]

    # Confidence breakdown
    confidence_breakdown: ConfidenceBreakdown

    # Additional context
    session_info: Dict[str, Any]
    htf_phase: str
    mtf_alignment_score: float
    quality_score: float
    reversal_score: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        # Convert enum values to strings for clean JSON
        d['setup_type'] = self.setup_type.value
        d['variant'] = self.variant.value
        d['entry']['type'] = self.entry.type.value
        d['stop_loss']['basis'] = self.stop_loss.basis.value
        for t in d['targets']:
            t['level'] = TargetLevel(t['level']).value
        return d

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_signal_id(cls, signal_id: str) -> Optional['TradingSignal']:
        """
        Look up a signal by ID for persistence / audit (§10).

        Placeholder — would typically query a database or file store.
        """
        return None

    @classmethod
    def build(
        cls,
        instrument: str,
        direction: str,
        setup_type: SetupType,
        gates: GateSummary,
        entry: EntryPlan,
        stop_loss: StopLossPlan,
        targets: List[TargetPlan],
        confidence_breakdown: ConfidenceBreakdown,
        session_info: Dict[str, Any],
        htf_phase: str,
        mtf_alignment_score: float,
        quality_score: float,
        reversal_score: float,
        setup_subtype: str = "conservative",
    ) -> 'TradingSignal':
        """
        Build a new trading signal with a generated UUID and current timestamp.

        Convenience factory that auto-populates signal_id, timestamp,
        confidence, action, and variant.
        """
        return cls(
            signal_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat() + "Z",
            instrument=instrument,
            direction=direction,
            setup_type=setup_type,
            setup_subtype=setup_subtype,
            confidence=confidence_breakdown.final_confidence,
            action=cls._action_from_confidence(confidence_breakdown.final_confidence),
            variant=SignalVariant.FOREX,
            gates=gates,
            entry=entry,
            stop_loss=stop_loss,
            targets=targets,
            confidence_breakdown=confidence_breakdown,
            session_info=session_info,
            htf_phase=htf_phase,
            mtf_alignment_score=mtf_alignment_score,
            quality_score=quality_score,
            reversal_score=reversal_score,
        )

    @staticmethod
    def _action_from_confidence(confidence: float) -> str:
        """Map confidence score to action string (§8)."""
        if confidence >= 0.65:
            return "strong"
        elif confidence >= 0.50:
            return "moderate"
        elif confidence >= 0.40:
            return "gray_zone"
        return "no_trade"
