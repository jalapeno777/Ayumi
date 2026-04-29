"""TTC Forward Strategy — wraps SignalEngineBridge as an ISignalStrategy for live forward testing.

Adapts the TTC signal engine (swing detection → level counting → signal generation)
into the ForwardTestEngine's strategy evaluation pipeline. Designed for XAUUSD H1
but configurable for any symbol/timeframe.

The forward test engine calls evaluate(state) on each tick aggregation.
We convert the Bar list to a pandas DataFrame, run the signal engine bridge,
and convert any resulting Signal back to a StrategySignal.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from backtest.engine import Bar, MarketState, StrategySignal, TradeDirection
from backtest.strategy_legacy import ISignalStrategy
from signal_engine.backtest_bridge import SignalEngineBridge

logger = logging.getLogger(__name__)


def _bars_to_dataframe(bars: list[Bar]) -> pd.DataFrame:
    """Convert a list of Bar objects to the DataFrame format expected by SignalEngineBridge."""
    if not bars:
        return pd.DataFrame()

    return pd.DataFrame(
        [
            {
                "time": b.time,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ]
    )


def _pip_value_for(price: float) -> float:
    """Return the pip value for a given price level."""
    if price >= 50:
        return 0.01  # Gold, JPY pairs
    elif price >= 1:
        return 0.0001  # Most forex pairs
    else:
        return 0.00000001


class TTCSignalForwardStrategy(ISignalStrategy):
    """TTC signal engine wrapped for the ForwardTestEngine pipeline.

    On each evaluate() call:
    1. Convert accumulated bars to a pandas DataFrame
    2. Run SignalEngineBridge.run() to detect swings, count levels, find signals
    3. Convert any Signal to a StrategySignal with appropriate SL/TP for the symbol

    The bridge maintains internal state (swings, levels) across calls.
    We feed the full bar history each time so state stays consistent.
    """

    def __init__(
        self,
        instrument: str = "XAUUSD",
        timeframe: str = "H1",
        min_confidence: float = 0.40,
        rr_ratio: float = 3.0,
    ):
        self.instrument = instrument
        self.timeframe = timeframe
        self.min_confidence = min_confidence
        self.rr_ratio = rr_ratio

        self._bridge = SignalEngineBridge(
            config={
                "symbol": instrument,
                "min_confidence": min_confidence,
                "lookback": 5,
            }
        )

        self._last_signal_time: Optional[datetime] = None
        self._cooldown_bars = 5  # Minimum bars between signals to avoid spam

    @property
    def name(self) -> str:
        return f"TTC ({self.instrument} {self.timeframe})"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        """Called by ForwardTestEngine on each evaluation cycle.

        Args:
            state: MarketState with accumulated bars from live tick data.

        Returns:
            StrategySignal if the TTC engine finds a qualifying setup, else None.
        """
        bars = state.bars
        if len(bars) < 50:
            # Need enough bars for swing detection and level counting
            return None

        latest_bar = state.latest_bar

        # Cooldown check — don't signal on every bar
        if self._last_signal_time is not None:
            # Count bars since last signal
            bars_since = sum(
                1 for b in bars if b.time > self._last_signal_time
            )
            if bars_since < self._cooldown_bars:
                return None

        try:
            df = _bars_to_dataframe(bars)

            # Run the full signal engine pipeline
            signals = self._bridge.run(df)

            if not signals:
                return None

            # Take the most recent signal (last in list = most recent bar)
            signal = signals[-1]

            if signal.confidence < self.min_confidence:
                return None

            # Convert to StrategySignal
            return self._to_strategy_signal(signal, latest_bar)

        except Exception as e:
            logger.error(
                "TTC strategy evaluation error: %s", e, exc_info=True
            )
            return None

    def _to_strategy_signal(
        self, signal, latest_bar: Bar
    ) -> Optional[StrategySignal]:
        """Convert a signal_engine Signal to a backtest StrategySignal."""
        entry = signal.entry_price
        sl = signal.stop_loss
        tp = signal.take_profit

        if sl == 0 or entry == 0:
            return None

        # Validate R:R
        risk = abs(entry - sl)
        reward = abs(tp - entry)

        if risk <= 0:
            return None

        actual_rr = reward / risk
        if actual_rr < self.rr_ratio:
            # Adjust TP to meet minimum R:R
            if signal.direction == "long":
                tp = entry + risk * self.rr_ratio
            else:
                tp = entry - risk * self.rr_ratio

        direction = (
            TradeDirection.LONG
            if signal.direction == "long"
            else TradeDirection.SHORT
        )

        pip = _pip_value_for(entry)

        self._last_signal_time = latest_bar.time

        return StrategySignal(
            direction=direction,
            confidence=signal.confidence,
            entry_price=entry,
            stop_loss=sl,
            take_profit_1=tp if signal.direction == "long" else tp,
            take_profit_2=entry + (tp - entry) * 1.5 if signal.direction == "long" else entry - (entry - tp) * 1.5,
            take_profit_3=entry + (tp - entry) * 2.0 if signal.direction == "long" else entry - (entry - tp) * 2.0,
            rationale=(
                f"TTC {signal.setup_type}: conf={signal.confidence:.2f}, "
                f"gates={signal.gates_passed}, "
                f"SL={abs(entry - sl) / pip:.0f}pips, "
                f"RR={abs(tp - entry) / abs(entry - sl):.1f}"
            ),
        )
