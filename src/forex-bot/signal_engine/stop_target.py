"""§9 — Stop loss and take profit placement.

Priority-ordered SL rules (§9.1), target rules (§9.2),
and trailing SL logic for lock-in behavior (§9.3).
"""

from __future__ import annotations


# Default R:R ratio
DEFAULT_RR_RATIO = 2.0

# Spread buffer added to SL as safety margin (pips converted to price units)
SPREAD_BUFFER_PIPS = 0.5


class StopTargetCalculator:
    """Calculate stop loss and take profit levels from structure context."""

    def __init__(self, rr_ratio: float = DEFAULT_RR_RATIO, pip_size: float = 0.0001):
        self.rr_ratio = rr_ratio
        self.pip_size = pip_size

    def calculate(
        self,
        direction: str,
        entry: float,
        context: dict,
        spread: float = 0.0,
    ) -> dict:
        """Return stop_loss, take_profit, tp_levels, and trailing config.

        Context keys:
            sl2 (long): second swing low below entry
            sh2 (short): second swing high above entry
            r2, r3: demand/take-profit levels for longs
            d2, d3: supply/take-profit levels for shorts
            atr: for trailing stop calculation
        """
        sl = self._place_stop_loss(direction, entry, context, spread)
        tp, tp_levels = self._place_take_profit(direction, entry, sl, context)
        trailing = self._trailing_config(direction, entry, sl, tp, context)

        return {
            "stop_loss": sl,
            "take_profit": tp,
            "tp_levels": tp_levels,
            "trailing": trailing,
            "risk_pips": abs(entry - sl) / self.pip_size,
            "reward_pips": abs(tp - entry) / self.pip_size,
            "rr_ratio": abs(tp - entry) / abs(entry - sl) if sl != entry else 0.0,
        }

    def _place_stop_loss(
        self,
        direction: str,
        entry: float,
        context: dict,
        spread: float,
    ) -> float:
        """SL beyond structure: below SL2 for long, above SH2 for short."""
        buffer = max(SPREAD_BUFFER_PIPS * self.pip_size, spread)

        if direction == "long":
            sl2 = context.get("sl2", entry - 50 * self.pip_size)
            sl = min(sl2, entry - 20 * self.pip_size) - buffer
            # Ensure SL is below entry
            sl = min(sl, entry - 10 * self.pip_size)
        else:
            sh2 = context.get("sh2", entry + 50 * self.pip_size)
            sl = max(sh2, entry + 20 * self.pip_size) + buffer
            # Ensure SL is above entry (for shorts)
            sl = max(sl, entry + 10 * self.pip_size)

        return round(sl, 5)

    def _place_take_profit(
        self,
        direction: str,
        entry: float,
        sl: float,
        context: dict,
    ) -> tuple[float, list[dict]]:
        """TP based on R:R ratio and structure levels (R3/R2 or D3/D2)."""
        risk = abs(entry - sl)
        risk_reward_target = (
            entry + (risk * self.rr_ratio)
            if direction == "long"
            else entry - (risk * self.rr_ratio)
        )

        tp_levels = []
        if direction == "long":
            r2 = context.get("r2")
            r3 = context.get("r3")
            # Only use structure levels that are ABOVE entry (correct side for long TP)
            if r2 and r2 > entry:
                tp_levels.append(
                    {
                        "level": "R2",
                        "price": r2,
                        "rr": round((r2 - entry) / risk, 2) if risk else 0,
                    }
                )
            if r3 and r3 > entry:
                tp_levels.append(
                    {
                        "level": "R3",
                        "price": r3,
                        "rr": round((r3 - entry) / risk, 2) if risk else 0,
                    }
                )
            # If no valid structure levels, use pure R:R
            if not tp_levels:
                tp_levels.append(
                    {"level": "TP1", "price": risk_reward_target, "rr": self.rr_ratio}
                )
            tp = tp_levels[-1]["price"]  # furthest target
        else:
            d2 = context.get("d2")
            d3 = context.get("d3")
            # Only use structure levels that are BELOW entry (correct side for short TP)
            if d2 and d2 < entry:
                tp_levels.append(
                    {
                        "level": "D2",
                        "price": d2,
                        "rr": round((entry - d2) / risk, 2) if risk else 0,
                    }
                )
            if d3 and d3 < entry:
                tp_levels.append(
                    {
                        "level": "D3",
                        "price": d3,
                        "rr": round((entry - d3) / risk, 2) if risk else 0,
                    }
                )
            if not tp_levels:
                tp_levels.append(
                    {"level": "TP1", "price": risk_reward_target, "rr": self.rr_ratio}
                )
            tp = tp_levels[-1]["price"]

        return round(tp, 5), tp_levels

    def _trailing_config(
        self,
        direction: str,
        entry: float,
        sl: float,
        tp: float,
        context: dict,
    ) -> dict:
        """Trailing stop logic for lock-in behavior.

        Once price moves 1R in favor, trail SL to breakeven.
        After 1.5R, trail by half the remaining distance to TP.
        """
        risk = abs(entry - sl)

        if direction == "long":
            breakeven_trigger = entry + risk
            trail_start = entry + risk * 1.5
        else:
            breakeven_trigger = entry - risk
            trail_start = entry - risk * 1.5

        return {
            "breakeven_trigger": round(breakeven_trigger, 5),
            "trail_start": round(trail_start, 5),
            "trail_step": "half_remaining",  # move SL to halfway between current and TP
            "atr_trail": context.get("atr"),  # optional ATR-based trail
        }
