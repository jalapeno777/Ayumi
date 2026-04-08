from typing import Optional, Tuple

from .models import (
    ConfluenceSignal,
    ICTMarketState,
    SignalStrength,
    TradeDirection,
)
from .order_block import OrderBlockDetector
from .fvg import FVGDetector


class ConfluenceEngine:
    def __init__(
        self,
        min_confidence: float = 0.55,
        ob_weight: float = 0.40,
        fvg_weight: float = 0.35,
        structure_weight: float = 0.25,
        default_sl_multiplier: float = 2.0,
        tp1_rr: float = 1.0,
        tp2_rr: float = 2.0,
        tp3_rr: float = 3.0,
    ):
        self._min_confidence = min_confidence
        self._ob_weight = ob_weight
        self._fvg_weight = fvg_weight
        self._structure_weight = structure_weight
        self._default_sl_multiplier = default_sl_multiplier
        self._tp1_rr = tp1_rr
        self._tp2_rr = tp2_rr
        self._tp3_rr = tp3_rr

        self._ob_detector = OrderBlockDetector()
        self._fvg_detector = FVGDetector()

    def evaluate(self, state: ICTMarketState) -> Optional[ConfluenceSignal]:
        self._ob_detector.detect(state)
        self._fvg_detector.detect(state)

        if state.atr == 0:
            state.atr = state.calculate_atr()

        if state.atr == 0:
            return None

        bullish_scores = self._score_direction(state, TradeDirection.LONG)
        bearish_scores = self._score_direction(state, TradeDirection.SHORT)

        bullish_total = bullish_scores["total"]
        bearish_total = bearish_scores["total"]

        if bullish_total > bearish_total and bullish_total >= self._min_confidence:
            direction = TradeDirection.LONG
            confidence = bullish_total
            component_scores = bullish_scores
        elif bearish_total > bullish_total and bearish_total >= self._min_confidence:
            direction = TradeDirection.SHORT
            confidence = bearish_total
            component_scores = bearish_scores
        else:
            return None

        entry, sl, tp1, tp2, tp3 = self._calculate_levels(state, direction)

        risk = abs(entry - sl)
        if risk == 0:
            return None

        rr = abs(tp2 - entry) / risk

        rationale = self._build_rationale(state, direction, confidence)

        ob = self._ob_detector.get_most_relevant(state, direction)
        fvg = self._fvg_detector.get_nearest_unfilled(state, direction, entry)

        return ConfluenceSignal(
            direction=direction,
            strength=self._classify_strength(confidence),
            confidence_score=confidence,
            entry_price=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            signal_time=state.latest_bar.time,
            rationale=rationale,
            has_order_block=ob is not None,
            has_fvg=fvg is not None,
            has_structure_alignment=state.structure_bias == direction,
            confluence_count=self._count_confluences(state, direction),
            risk_reward_ratio=rr,
            ob_score=component_scores["ob"],
            fvg_score=component_scores["fvg"],
            ob=ob,
            fvg=fvg,
        )

    def _score_direction(
        self, state: ICTMarketState, direction: TradeDirection
    ) -> dict:
        ob_score = self._score_order_blocks(state, direction)
        fvg_score = self._score_fvg(state, direction)
        structure_score = 1.0 if state.structure_bias == direction else 0.3

        total = (
            ob_score * self._ob_weight
            + fvg_score * self._fvg_weight
            + structure_score * self._structure_weight
        )

        return {
            "ob": ob_score,
            "fvg": fvg_score,
            "structure": structure_score,
            "total": min(1.0, total),
        }

    def _score_order_blocks(
        self, state: ICTMarketState, direction: TradeDirection
    ) -> float:
        ob = self._ob_detector.get_most_relevant(state, direction)
        if ob is None:
            return 0.0

        score = ob.strength * 0.7
        if ob.age <= 2:
            score += 0.2
        elif ob.age <= 4:
            score += 0.1

        current_price = state.latest_bar.close
        distance = abs(current_price - ob.mid) / state.atr

        if distance <= 1.0:
            score += 0.2
        elif distance <= 2.0:
            score += 0.1

        return min(1.0, score)

    def _score_fvg(self, state: ICTMarketState, direction: TradeDirection) -> float:
        fvg = self._fvg_detector.get_nearest_unfilled(
            state, direction, state.latest_bar.close
        )
        if fvg is None:
            return 0.0

        score = 0.4
        if fvg.age <= 3:
            score += 0.2
        elif fvg.age <= 8:
            score += 0.1

        normalized_size = fvg.size / state.atr
        if normalized_size > 1.5:
            score += 0.2
        elif normalized_size > 0.5:
            score += 0.1

        if fvg.is_filled:
            score *= 0.5

        return min(1.0, score)

    def _calculate_levels(
        self, state: ICTMarketState, direction: TradeDirection
    ) -> Tuple[float, float, float, float, float]:
        atr = state.atr
        current_price = state.latest_bar.close

        if direction == TradeDirection.LONG:
            ob = self._ob_detector.get_nearest(state, direction, current_price)
            if ob is not None and abs(current_price - ob.bottom) / state.atr < 2.0:
                entry = ob.bottom
            else:
                entry = current_price

            sl = entry - atr * self._default_sl_multiplier
            risk = abs(entry - sl)

            tp1 = entry + risk * self._tp1_rr
            tp2 = entry + risk * self._tp2_rr
            tp3 = entry + risk * self._tp3_rr
        else:
            ob = self._ob_detector.get_nearest(state, direction, current_price)
            if ob is not None and abs(current_price - ob.top) / state.atr < 2.0:
                entry = ob.top
            else:
                entry = current_price

            sl = entry + atr * self._default_sl_multiplier
            risk = abs(entry - sl)

            tp1 = entry - risk * self._tp1_rr
            tp2 = entry - risk * self._tp2_rr
            tp3 = entry - risk * self._tp3_rr

        return (entry, sl, tp1, tp2, tp3)

    def _build_rationale(
        self, state: ICTMarketState, direction: TradeDirection, confidence: float
    ) -> str:
        lines = [f"{direction.value.upper()} signal (confidence: {confidence:.2f})"]

        if state.structure_bias == direction:
            lines.append("- Structure aligned")

        ob = self._ob_detector.get_most_relevant(state, direction)
        if ob is not None:
            lines.append(f"- Order block confluence (strength: {ob.strength:.2f})")

        fvg = self._fvg_detector.get_nearest_unfilled(
            state, direction, state.latest_bar.close
        )
        if fvg is not None:
            lines.append(f"- FVG present ({fvg.fvg_type.value})")

        lines.append(f"- Confluence count: {self._count_confluences(state, direction)}")
        return "\n".join(lines)

    def _count_confluences(
        self, state: ICTMarketState, direction: TradeDirection
    ) -> int:
        count = 0
        if state.structure_bias == direction:
            count += 1
        if self._ob_detector.get_most_relevant(state, direction) is not None:
            count += 1
        if (
            self._fvg_detector.get_nearest_unfilled(
                state, direction, state.latest_bar.close
            )
            is not None
        ):
            count += 1
        return count

    @staticmethod
    def _classify_strength(confidence: float) -> SignalStrength:
        if confidence >= 0.85:
            return SignalStrength.VERY_STRONG
        if confidence >= 0.70:
            return SignalStrength.STRONG
        if confidence >= 0.55:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK
