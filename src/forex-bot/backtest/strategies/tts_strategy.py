"""TTSStrategy — ISignalStrategy adapter for the Ayumi TTC signal engine.

Wires the full signal engine pipeline (Phase 1-4) into the backtest engine
via the ISignalStrategy interface, producing StrategySignal objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


from ..engine import Bar, MarketState, StrategySignal, TradeDirection
from ..strategy_legacy import ISignalStrategy
from signal_engine import (
    PatternDetector,
    GateValidator,
    ConfluenceScorer,
    StopTargetCalculator,
    SessionAnalyzer,
)
from signal_engine.data_types import HTFState, SessionState, Swing, Level
from signal_engine.swing_detector import SwingDetector
from signal_engine.level_counter import LevelCounter
from signal_engine.htf_analyzer import HTFAnalyzer

import numpy as np


class TTSStrategy(ISignalStrategy):
    """Multi-timeframe TTC/TBD signal strategy.

    Uses direct incremental swing/level detection for accurate per-bar
    state, then runs Phase 2-4 pattern → gate → confluence → SL/TP pipeline.

    Pipeline per bar:
        1. Session context (SessionAnalyzer)
        2. Incremental swing detection + level counting (SwingDetector + LevelCounter)
        3. Pattern detection (PatternDetector) — M/W 11-pt, SVC, traps, FL
        4. Gate validation (GateValidator) — hard gates
        5. Confluence scoring (ConfluenceScorer) — boosters
        6. SL/TP calculation (StopTargetCalculator)
        7. Output as StrategySignal
    """

    SWING_LOOKBACK = 5  # N-bar swing detection
    HISTORY_BARS = 50  # how many bars to feed into swing detection (M15)

    def __init__(
        self,
        symbol: str = "EURUSD",
        min_confidence: float = 0.25,
        min_quality_score: float = 0.25,
    ):
        self.symbol = symbol
        self.min_confidence = min_confidence
        self.min_quality_score = min_quality_score

        # Phase 2 components
        self._pattern_detector = PatternDetector()
        self._gate_validator = GateValidator(quality_threshold=min_quality_score)
        # Phase 3 components
        self._confluence_scorer = ConfluenceScorer()
        self._stop_target = StopTargetCalculator()
        # Session
        self._session_analyzer = SessionAnalyzer()
        # HTF
        self._htf_analyzer = HTFAnalyzer()

        # Incremental swing detector (accumulates swings across bars)
        self._swing_detector = SwingDetector(lookback=self.SWING_LOOKBACK)
        self._level_counter = LevelCounter()

        # Mutable state — rebuilt each evaluate() call with full history
        self._swing_highs: list[Swing] = []
        self._swing_lows: list[Swing] = []
        self._levels: list[Level] = []
        self._last_bar_idx = -1

    @property
    def name(self) -> str:
        return f"TTC/TBD {self.symbol}"

    def reset(self) -> None:
        """Reset cached state between backtest runs."""
        self._swing_highs = []
        self._swing_lows = []
        self._levels = []
        self._last_bar_idx = -1
        self._swing_detector = SwingDetector(lookback=self.SWING_LOOKBACK)
        self._level_counter = LevelCounter()

    def evaluate(self, state: MarketState) -> StrategySignal | None:
        """Evaluate current bar for a trading signal.

        Args:
            state: MarketState with bars up to and including the current bar.

        Returns:
            StrategySignal if all gate conditions pass and quality >= threshold,
            None otherwise.
        """
        bars = state.bars
        if len(bars) < self.HISTORY_BARS + 1:
            return None

        latest = bars[-1]
        bar_idx = len(bars) - 1

        # Skip if already evaluated (batch mode dedup)
        if bar_idx == self._last_bar_idx:
            return None
        self._last_bar_idx = bar_idx

        # ── Step 1: Session context + HTF analysis ────────────────────
        session_state = self._get_session_state(latest.time)

        # Require active session (not OUTSIDE)
        if session_state.session_name == "OUTSIDE":
            return None

        htf_state = self._compute_htf_state(bars)

        # ── Step 2: Swing + level detection (incremental full history) ──
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        self._swing_highs, self._swing_lows = self._swing_detector.detect_swings(
            highs, lows
        )
        self._levels = self._level_counter.detect_levels_with_tracking(
            self._swing_highs, self._swing_lows
        )

        if not self._levels:
            return None

        # ── Step 3: Pattern detection ──────────────────────────────────
        bars_dict = [
            {
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "open": b.open,
                "volume": b.volume,
            }
            for b in bars
        ]
        patterns = self._pattern_detector.detect_all(
            swings=self._swing_highs,
            levels=self._levels,
            bars=bars_dict,
            current_price=latest.close,
            session=session_state.session_name,
        )
        if not patterns:
            return None

        best_pattern = max(patterns, key=lambda p: p.confidence)

        # ── Step 3b: Quality gates ────────────────────────────────────
        # Require minimum confidence
        if best_pattern.confidence < 0.35:
            return None

        # For M/W patterns, require reasonable checklist
        if best_pattern.pattern_type in ("M", "W"):
            checklist = getattr(best_pattern, "checklist_score", 0.0)
            if checklist < 0.4:
                return None

        # Require active session
        if not session_state.kill_zone_active:
            return None

        # Require HTF alignment (not conflicting, preferably aligned)
        if htf_state and htf_state.phase.value == "conflicting":
            return None
        if htf_state and htf_state.phase.value == "consolidating":
            return None

        # ── Step 4: Gate validation ───────────────────────────────────
        candidate = self._build_candidate(best_pattern, latest, bars)
        gate_result = self._gate_validator.validate(
            candidate=candidate,
            htf_state=htf_state,
            session_state=session_state,
            levels=self._levels,
        )
        if not gate_result.passed:
            return None

        quality_score = gate_result.quality_score
        if quality_score < self.min_quality_score:
            return None

        # ── Step 5: Confluence scoring ─────────────────────────────────
        session_dict = {
            "phase_score": session_state.phase_score,
            "kill_zone_active": session_state.kill_zone_active,
        }
        htf_dict = {"alignment_score": htf_state.alignment_score} if htf_state else {}
        confluence_score, confluence_boosters = self._confluence_scorer.score(
            candidate=candidate,
            htf_state=htf_dict,
            session_state=session_dict,
        )
        total_confidence = min(
            quality_score * 0.4 + confluence_score * 0.6,
            1.0,
        )

        if total_confidence < self.min_confidence:
            return None

        # ── Step 6: SL/TP calculation ─────────────────────────────────
        # Build context dict — only include keys with non-None values
        context: dict = {"atr": state.atr if state.atr > 0 else 0.0001}
        for lv in self._levels:
            if lv.level_type.value in ("R2", "R3", "D2", "D3"):
                context[lv.level_type.value.lower()] = lv.price
        for s in self._swing_lows[-3:]:
            if s.price < latest.close:
                context["sl2"] = s.price
                break
        for s in self._swing_highs[-3:]:
            if s.price > latest.close:
                context["sh2"] = s.price
                break

        st_result = self._stop_target.calculate(
            direction=best_pattern.direction,
            entry=latest.close,
            context=context,
            spread=1.5 * 0.0001,
        )
        stop_price = st_result["stop_loss"]
        tp_price = st_result["take_profit"]

        if stop_price is None or tp_price is None:
            return None

        risk = abs(latest.close - stop_price)
        direction = (
            TradeDirection.LONG
            if best_pattern.direction == "long"
            else TradeDirection.SHORT
        )
        tp1 = tp_price
        tp2 = (
            tp_price + risk * 2.0
            if best_pattern.direction == "long"
            else tp_price - risk * 2.0
        )
        tp3 = (
            tp_price + risk * 3.0
            if best_pattern.direction == "long"
            else tp_price - risk * 3.0
        )

        rationale = (
            f"{self.name}: {best_pattern.pattern_type} "
            f"{best_pattern.direction} @ {latest.close:.5f}, "
            f"conf={total_confidence:.2f}, "
            f"gates_fail={gate_result.failed_gates}, "
            f"boosters={[b.name for b in confluence_boosters]}"
        )

        return StrategySignal(
            direction=direction,
            confidence=total_confidence,
            entry_price=latest.close,
            stop_loss=stop_price,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            rationale=rationale,
        )

    def _get_session_state(self, ts: datetime) -> SessionState:
        session_name = self._session_analyzer.get_current_session(ts)
        _ = self._session_analyzer.is_kill_zone(ts)
        session_result = self._session_analyzer.score_session_phase_with_time(
            session_name, ts
        )
        return SessionState(
            session_name=session_name,
            kill_zone_active=session_result["kill_zone_active"],
            phase_score=session_result["phase_score"],
            directional_bias=session_result.get("directional_bias"),
        )

    def _compute_htf_state(self, bars: list[Bar]) -> HTFState:
        """Compute pseudo-HTF state from M15 bars.

        Uses the last 672 bars (~7 days of M15) as D1-equivalent
        for trend detection and phase classification.
        """
        from signal_engine.data_types import HTFPhase

        lookback = min(672, len(bars))
        if lookback < 20:
            return HTFState(HTFPhase.NEUTRAL, 0.0, 0.0, 0.0)

        recent = bars[-lookback:]
        closes = np.array([b.close for b in recent])
        highs = np.array([b.high for b in recent])
        lows = np.array([b.low for b in recent])

        ema_50 = self._ema(closes, min(50, len(closes)))

        # For M15 data: 80 bars = 20 hours for range
        range_bars = min(80, len(highs))
        range_high = float(np.max(highs[-range_bars:]))
        range_low = float(np.min(lows[-range_bars:]))
        range_size = (range_high - range_low) / range_low if range_low > 0 else 0.0

        # EMA slope over 80 bars
        ema_slope = 0.0
        if len(ema_50) >= 80:
            valid = ema_50[-80:]
            valid = valid[~np.isnan(valid)]
            if len(valid) >= 2:
                slope_raw = valid[-1] - valid[0]
                ema_slope = (
                    slope_raw / (len(valid) * valid[-1]) if valid[-1] > 0 else 0.0
                )

        # Phase: use M15-appropriate thresholds
        # Boardroom: range < 0.3% over 20h is very tight
        # Trend: ema_slope > 0.00003 per bar is meaningful on M15
        phase = self._classify_htf_phase(range_size, ema_slope, highs, lows, closes)

        # Alignment score
        htf_dir = (
            "bullish"
            if ema_slope > 0.00003
            else ("bearish" if ema_slope < -0.00003 else None)
        )
        alignment = self._htf_analyzer.analyze_htf_alignment(
            {"D1": htf_dir} if htf_dir else {}
        )

        return HTFState(phase, alignment, ema_slope, range_size)

    @staticmethod
    def _classify_htf_phase(range_size, ema_slope, highs, lows, closes):
        """Classify HTF phase with M15-appropriate thresholds."""
        from signal_engine.data_types import HTFPhase

        # Consolidating: tight range + flat EMA
        if range_size <= 0.003 and abs(ema_slope) < 0.00003:
            return HTFPhase.CONSOLIDATING

        # Exhaustion: price near period extremes
        if len(highs) >= 200:
            period_high = float(np.max(highs))
            period_low = float(np.min(lows))
            current_price = float(closes[-1])
            total_range = period_high - period_low
            if total_range > 0:
                near_high = (period_high - current_price) / total_range < 0.05
                near_low = (current_price - period_low) / total_range < 0.05
                if near_high or near_low:
                    return HTFPhase.EXHAUSTION

        # Aligned: trending with EMA slope
        if abs(ema_slope) >= 0.00003:
            return HTFPhase.ALIGNED

        return HTFPhase.NEUTRAL

    def _compute_session_bias(self, bars: list[Bar], latest: Bar) -> Optional[str]:
        """Compute session directional bias from recent price action.

        Compares the open of the current session to the current price.
        Returns 'bullish', 'bearish', or None.
        """
        if len(bars) < 5:
            return None

        # Look at last 16 bars (~4 hours) for session direction
        lookback = min(16, len(bars))
        session_open = bars[-lookback].open
        current = latest.close
        move_pct = (current - session_open) / session_open

        if move_pct > 0.001:  # > 10 pips up
            return "bullish"
        elif move_pct < -0.001:  # > 10 pips down
            return "bearish"
        return None

    @staticmethod
    def _ema(data: np.ndarray, period: int) -> np.ndarray:
        """Compute EMA."""
        if len(data) < period:
            # Not enough data — return NaN-filled array
            return np.full_like(data, np.nan)
        alpha = 2.0 / (period + 1)
        ema = np.copy(data)
        ema[:period] = np.nan
        ema[period] = np.mean(data[: period + 1])
        for i in range(period + 1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        return ema

    def _build_candidate(self, pattern, latest: Bar, bars: list[Bar]) -> dict:
        return {
            "symbol": self.symbol,
            "direction": pattern.direction,
            "entry_price": latest.close,
            "confidence": pattern.confidence,
            "pattern_type": pattern.pattern_type,
            "checklist_score": getattr(pattern, "checklist_score", 0.0),
            "key_levels": getattr(pattern, "key_levels", {}),
            "timestamp": latest.time,
            "timeframe": "M15",
        }
