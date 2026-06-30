"""TestCanaryStrategy — execution-path validation strategy.

Fires on every new 15m bar close to guarantee the full signal-to-fill
pipeline is exercised. NOT for profit — purely diagnostic.

Logic:
    - On each bar close, emit a LONG signal.
    - Entry = bar close price.
    - SL = entry * (1 - tp_sl_pct)   [-5% by default]
    - TP = entry * (1 + tp_sl_pct)   [+5% by default]
    - Confidence = 0.60 (above the 0.50 min_confidence gate)
    - Alternates direction each bar to avoid building up net exposure

If this strategy's signals don't result in live fills, the problem is
in the order chain, not the signal layer.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from backtest.strategy_legacy import ISignalStrategy
from backtest.types import Bar, MarketState, StrategySignal, TradeDirection

logger = logging.getLogger("ayumi.test_canary")


class TestCanaryStrategy(ISignalStrategy):
    """Fire a signal on every bar close to validate the execution pipeline.

    DISABLED as of 2026-06-29 22:20 EDT — see blended-strategies sprint.
    Kept registered for re-enable later. Set tp_sl_pct=0.0 below to fully
    disable without removing from the launcher.
    """

    def __init__(self, tp_sl_pct: float = 0.0):  # 0.0 = disabled (no signals)
        self.tp_sl_pct = tp_sl_pct
        self._bar_count = 0

    @classmethod
    def from_env(cls, default_tp_sl_pct: float = 0.005) -> "TestCanaryStrategy":
        """Construct from environment gating.

        Re-enable requires explicit AYUMI_ENABLE_CANARY=1.
        tp_sl_pct=0.0 by default unless env var is set.
        """
        enabled = os.getenv("AYUMI_ENABLE_CANARY", "0").strip() == "1"
        if enabled:
            return cls(tp_sl_pct=default_tp_sl_pct)
        return cls(tp_sl_pct=0.0)

    @property
    def name(self) -> str:
        return "Test Canary"

    @property
    def enabled(self) -> bool:
        return self.tp_sl_pct > 0

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        if not self.enabled:
            return None
        if not state.bars:
            return None

        if self.enabled:
            logger.warning(
                "Test Canary is ENABLED (tp_sl_pct=%.4f) — emitting diagnostic signals",
                self.tp_sl_pct,
            )

        bar: Bar = state.bars[-1]
        entry = bar.close
        if entry <= 0:
            return None

        self._bar_count += 1

        # Alternate LONG/SHORT each bar to avoid directional bias
        direction = TradeDirection.LONG if self._bar_count % 2 == 1 else TradeDirection.SHORT

        sl_distance = entry * self.tp_sl_pct
        if direction == TradeDirection.LONG:
            stop_loss = entry - sl_distance
            take_profit = entry + sl_distance
        else:
            stop_loss = entry + sl_distance
            take_profit = entry - sl_distance

        return StrategySignal(
            direction=direction,
            confidence=0.60,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit_1=take_profit,
            take_profit_2=take_profit,
            take_profit_3=take_profit,
            rationale=f"canary_{self._bar_count}",
            is_volatile=False,
        )
