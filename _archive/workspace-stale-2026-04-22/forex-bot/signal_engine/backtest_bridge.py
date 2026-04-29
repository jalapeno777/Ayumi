"""
Backtest Bridge — Wire signal engine into existing backtest/engine.py.

This module connects the TTC signal engine (swing_detector, level_counter,
htf_analyzer, pattern_detector, gate_validator, confluence_scorer,
signal_output, stop_target) to the existing backtest runner.

The existing backtest engine is at: src/forex-bot/backtest/engine.py
The data loader is at: src/forex-bot/backtest/data_loader.py

Integration points:
1. On each new bar → run full signal pipeline → get TradingSignal or None
2. If signal.confidence >= 0.40 and action != "no_trade" → generate entry
3. Use stop_target.py for SL/TP from the signal
4. Feed backtest results back for calibration
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime
import numpy as np

from .swing_detector import detect_swings, SwingHigh, SwingLow
from .level_counter import LevelCounter, LevelState
from .htf_analyzer import analyze_htf_context, HTFPhase
from .session_logic import get_session_info, get_weekly_modifier
from .pattern_detector import PatternDetector, MWFormation, PatternType
from .gate_validator import GateValidator, GateValidationResult
from .confluence_scorer import ConfluenceScorer, ConfluenceInput, ActionThreshold
from .signal_output import (
    TradingSignal, GateSummary, EntryPlan, StopLossPlan,
    TargetPlan, TargetLevel, ConfidenceBreakdown, SetupType
)
from .stop_target import (
    calculate_stop_loss, calculate_targets,
    validate_rr_minimum, calculate_partial_exits,
    StopBasis,
)


@dataclass
class BacktestSignalConfig:
    """Configuration for signal generation during backtest."""
    instruments: List[str] = field(default_factory=lambda: ["EURUSD"])
    timeframes: List[str] = field(default_factory=lambda: ["H1", "M15"])
    min_confidence: float = 0.40  # Gray zone threshold
    allow_gray_zone: bool = True  # If False, only MODERATE+ (≥0.50)
    allow_strong_only: bool = False  # If True, only STRONG (≥0.65)
    min_quality_score: float = 0.50
    min_reversal_score: float = 0.30
    min_rr: float = 3.0


class SignalEngine:
    """
    Main signal generation engine — wires all TTC components together.

    Pipeline (per bar):
    1. Detect swings on current TF
    2. Count levels
    3. Analyze HTF context
    4. Detect patterns (M/W, SVC, trap)
    5. Validate gates
    6. Score confluence
    7. Generate stop/target
    8. Build signal output

    Usage:
        engine = SignalEngine(config=BacktestSignalConfig())
        signal = engine.generate_signal(bar_data, instrument="EURUSD")
        if signal:
            backtest_order = signal_to_order(signal)
    """

    def __init__(self, config: BacktestSignalConfig):
        self.config = config
        self.pattern_detector = PatternDetector()
        self.gate_validator = GateValidator(min_rr=config.min_rr)
        self.confluence_scorer = ConfluenceScorer()

        # Per-instrument, per-timeframe state
        self.swing_state: Dict[str, Dict[str, tuple]] = {}
        self.level_state: Dict[str, Dict[str, LevelCounter]] = {}

    def generate_signal(
        self,
        instrument: str,
        timeframe: str,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: Optional[np.ndarray] = None,
        timestamps: Optional[np.ndarray] = None,
        current_bar_idx: Optional[int] = None,
        htf_bars: Optional[Dict[str, np.ndarray]] = None,
        rough_levels: Optional[Dict[str, float]] = None,
    ) -> Optional[TradingSignal]:
        """
        Generate a trading signal from bar data.

        Returns TradingSignal if all gates pass and confidence meets threshold,
        or None if no valid setup is found.
        """
        if current_bar_idx is None:
            current_bar_idx = len(closes) - 1

        # 1. Swing detection
        swing_highs, swing_lows = detect_swings(highs, lows, lookback=5)
        if not (swing_highs and swing_lows):
            return None

        # 2. Level counting (maintain state per instrument/TF)
        if instrument not in self.level_state:
            self.level_state[instrument] = {}
        if timeframe not in self.level_state[instrument]:
            self.level_state[instrument][timeframe] = LevelCounter()

        level_counter = self.level_state[instrument][timeframe]
        level_counter.compute_emas(highs[-100:], lows[-100:], closes[-100:])  # Last 100 bars for EMA
        current_levels = level_counter.get_current_levels()

        # 3. HTF context
        htf_context = None
        if htf_bars:
            d1 = htf_bars.get("D1")
            h4 = htf_bars.get("H4")
            h1 = htf_bars.get("H1")
            if d1 is not None and h4 is not None and h1 is not None:
                htf_context = analyze_htf_context(d1, h4, h1, highs, current_bar_idx)

        # 4. Pattern detection
        formations = []

        sh_tuples = [(s.bar_index, s.price) for s in swing_highs]
        sl_tuples = [(s.bar_index, s.price) for s in swing_lows]

        # W formations (bullish)
        w_formations = self.pattern_detector.detect_w_formation(
            swing_highs=sh_tuples, swing_lows=sl_tuples,
            highs=highs, lows=lows, closes=closes,
            volumes=volumes,
            ema_50=level_counter.ema_50,
            ema_200=level_counter.ema_200,
            levels=rough_levels if rough_levels else current_levels,
        )
        formations.extend(w_formations)

        # M formations (bearish)
        m_formations = self.pattern_detector.detect_m_formation(
            swing_highs=sh_tuples, swing_lows=sl_tuples,
            highs=highs, lows=lows, closes=closes,
            volumes=volumes,
            ema_50=level_counter.ema_50,
            ema_200=level_counter.ema_200,
            levels=rough_levels if rough_levels else current_levels,
        )
        formations.extend(m_formations)

        if not formations:
            return None

        # Pick the formation with highest quality score
        best_formation = max(formations, key=lambda f: f.quality_score)

        # 5. Gate validation — use formation-aware stop/target for R:R check.
        # For M (bearish): SL above second peak, TP below middle swing.
        # For W (bullish): SL below second peak, TP above middle swing.
        entry_price = closes[current_bar_idx]
        if best_formation.pattern_type.value == "m":
            # Bearish: entry below second peak high, SL above second peak
            sl_price = highs[best_formation.second_peak_idx] + 0.0003
            tp_price = lows[best_formation.middle_swing_idx] - 0.0003
        else:
            # Bullish: entry above second peak low, SL below second peak
            sl_price = lows[best_formation.second_peak_idx] - 0.0003
            tp_price = highs[best_formation.middle_swing_idx] + 0.0003

        gate_result = self.gate_validator.validate(
            formation=best_formation,
            entry_price=entry_price,
            stop_loss=sl_price,
            target_price=tp_price,
            levels_complete=len(current_levels) >= 3 if current_levels else True,
            quality_score=best_formation.quality_score,
            reversal_score=best_formation.reversal_score,
        )

        if not gate_result.proceed_to_confluence:
            return None

        # 6. Confluence scoring — use quality_score as confidence proxy for backtest.
        # Full confluence inputs (MTF alignment, session info, etc.) require
        # generate_full_signal() which needs htf_bars + session context.
        confidence = best_formation.quality_score
        direction = "long" if best_formation.pattern_type.value == "w" else "short"
        
        # Build minimal TradingSignal
        from .signal_output import (
            TradingSignal, GateSummary, EntryPlan, StopLossPlan,
            TargetPlan, TargetLevel, ConfidenceBreakdown, SetupType, SignalVariant, EntryType
        )
        from .stop_target import StopBasis
        
        # Map PatternType to SetupType
        pt = best_formation.pattern_type
        if pt == PatternType.W:
            setup_type = SetupType.MULTI_SESSION_W
        elif pt == PatternType.M:
            setup_type = SetupType.MULTI_SESSION_M
        elif pt == PatternType.SVC_BULLISH:
            setup_type = SetupType.SVC
        else:
            setup_type = SetupType.MULTI_SESSION_W
        
        gate_summary = GateSummary(
            passed=True,
            universal={k: v.outcome.value == "pass" for k, v in gate_result.universal_gates.items()},
            pattern_specific={k: v.outcome.value == "pass" for k, v in gate_result.pattern_specific_gates.items()},
        )
        
        confidence_breakdown = ConfidenceBreakdown(
            base_confidence=confidence,
            htf_modifier=0.0,
            interaction_bonuses=[],
            weekly_offset=0.0,
            final_confidence=confidence,
            factor_weights={},
        )
        
        return TradingSignal(
            signal_id="backtest-signal",
            timestamp=datetime.utcnow().isoformat() + "Z",
            instrument=instrument,
            direction=direction,
            setup_type=setup_type,
            setup_subtype="conservative",
            confidence=confidence,
            action="moderate" if confidence >= 0.50 else "gray_zone",
            variant=SignalVariant.FOREX,
            gates=gate_summary,
            entry=EntryPlan(
                type=EntryType.ZONE,
                price_low=entry_price - 0.0005,
                price_high=entry_price + 0.0005,
                trigger="formation_confirmed",
                timeframe=timeframe,
            ),
            stop_loss=StopLossPlan(
                price=sl_price,
                basis=StopBasis.BEYOND_FORMATION,
                pips=abs(entry_price - sl_price) * 10000,
                method="beyond_formation",
            ),
            targets=[
                TargetPlan(level=TargetLevel.TP1, price=entry_price + 0.001 * (1 if direction == "long" else -1), rr=1.0, action="no_action"),
            ],
            confidence_breakdown=confidence_breakdown,
            session_info={},
            htf_phase="neutral",
            mtf_alignment_score=0.0,
            quality_score=confidence,
            reversal_score=best_formation.reversal_score,
        )

    def generate_full_signal(
        self,
        instrument: str,
        direction: str,
        formation: MWFormation,
        entry_price: float,
        stop_price: float,
        target_price: float,
        session_dt: datetime,
        confluence_input: ConfluenceInput,
        htf_context,
        levels: Dict[str, float],
        setup_type: SetupType = SetupType.MULTI_SESSION_W,
    ) -> TradingSignal:
        """
        Full signal generation with all required data.

        This is the complete version used by the backtest runner when all
        intermediate data (formation, confluence, HTF context) is available.
        """
        # Calculate stop loss — §9.1
        atr_14 = None  # Would be computed from bar data

        stop_loss_plan = calculate_stop_loss(
            entry_price=entry_price,
            direction=direction,
            formation=formation,
            svc_present=False,  # From formation data
            atr_14=atr_14,
        )

        # Calculate targets — §9.2
        targets = calculate_targets(
            entry_price=entry_price,
            direction=direction,
            stop_loss=stop_loss_plan,
            levels=levels,
            ema_50=confluence_input.mtf_alignment,  # Placeholder
            ema_200=0.0,
            setup_type=setup_type.value,
        )

        # Validate R:R — §9.4
        valid, reason = validate_rr_minimum(targets, stop_loss_plan, self.config.min_rr)
        if not valid:
            raise ValueError(f"Signal rejected: {reason}")

        # Score confluence
        confidence, action, factor_breakdown = self.confluence_scorer.score(confluence_input)

        # Build gate summary
        gate_summary = GateSummary(
            passed=True,
            universal={k: True for k in [
                "pattern_valid", "pattern_at_level", "rr_minimum",
                "levels_complete", "quality_threshold", "reversal_threshold"
            ]},
            pattern_specific=(
                {k: True for k in formation.gate_results}
                if hasattr(formation, 'gate_results') else {}
            ),
        )

        # Build confidence breakdown
        confidence_breakdown = ConfidenceBreakdown(
            base_confidence=confidence,
            htf_modifier=confluence_input.htf_modifier,
            interaction_bonuses=[],
            weekly_offset=get_weekly_modifier(session_dt),
            final_confidence=min(confidence + get_weekly_modifier(session_dt), 1.0),
            factor_weights=factor_breakdown,
        )

        session_info = get_session_info(session_dt)

        return TradingSignal.build(
            instrument=instrument,
            direction=direction,
            setup_type=setup_type,
            gates=gate_summary,
            entry=EntryPlan(
                type=EntryPlan.ZONE if "zone" in setup_type.value else EntryPlan.MARKET,
                price_low=entry_price - 0.0005,
                price_high=entry_price + 0.0005,
                trigger="conservative_retest",
                timeframe="H1",
            ),
            stop_loss=StopLossPlan(
                price=stop_price,
                basis=StopBasis.BEYOND_FORMATION,
                pips=abs(entry_price - stop_price) * 10000,
                method="beyond_formation",
            ),
            targets=[
                TargetPlan(
                    level=t.level,
                    price=t.price,
                    rr=t.rr,
                    basis=t.basis,
                    basis_description=t.basis_description,
                ) for t in targets
            ],
            confidence_breakdown=confidence_breakdown,
            session_info={
                "session": session_info.session.value,
                "phase": session_info.phase.value,
            },
            htf_phase=htf_context.phase.value if htf_context else "neutral",
            mtf_alignment_score=confluence_input.mtf_alignment,
            quality_score=formation.quality_score,
            reversal_score=formation.reversal_score,
        )
