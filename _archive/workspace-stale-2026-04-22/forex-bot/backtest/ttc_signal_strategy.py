"""
TTC Signal Strategy — wraps the TTC signal engine as an ISignalStrategy.

This strategy is fed bar-by-bar MarketState updates from the backtest engine.
On each evaluate() call it:
1. Feeds the latest bar + lookback bars to the SignalEngine
2. Gets back a TradingSignal (or None)
3. Converts it to a StrategySignal with entry, stop, targets

The backtest engine calls evaluate() on every bar to check for new signals.
"""
from typing import Optional, Dict
import numpy as np

from backtest.engine import Bar, MarketState, StrategySignal, TradeDirection
from backtest.strategies import ISignalStrategy
from signal_engine.backtest_bridge import SignalEngine, BacktestSignalConfig
from signal_engine.signal_output import TradingSignal


class TTCSignalStrategy(ISignalStrategy):
    """
    Wraps the TTC signal engine as a drop-in backtest strategy.

    The backtest engine calls evaluate(state) on each bar.
    When a TradingSignal is produced, convert it to a StrategySignal.
    """

    def __init__(self,
                 instrument: str = "EURUSD",
                 timeframe: str = "H1",
                 min_confidence: float = 0.40):
        self.instrument = instrument
        self.timeframe = timeframe
        self.min_confidence = min_confidence

        config = BacktestSignalConfig(
            instruments=[instrument],
            timeframes=[timeframe],
            min_confidence=min_confidence,
            allow_gray_zone=True,
        )
        self.signal_engine = SignalEngine(config)

        # Buffer of recent bars for swing detection
        self.bar_buffer: list = []
        self.max_buffer = 200  # Enough for swing detection lookback

        # Rough level context for reversal scoring
        # Computed from swing highs/lows of the bar buffer
        self.rough_levels: Dict[str, float] = {}

    @property
    def name(self) -> str:
        return f"TTC ({self.instrument} {self.timeframe})"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        """
        Called by backtest engine on every bar.
        Feed bars to signal engine, return StrategySignal if signal found.
        """
        # Add bar to buffer
        self.bar_buffer.append(state.latest_bar)
        if len(self.bar_buffer) > self.max_buffer:
            self.bar_buffer.pop(0)

        if len(self.bar_buffer) < 20:  # Need lookback for EMAs, swings
            return None

        # Compute rough levels from recent swing highs/lows for reversal scoring
        self._compute_rough_levels()

        # Extract arrays for signal engine
        highs = np.array([b.high for b in self.bar_buffer], dtype=np.float64)
        lows = np.array([b.low for b in self.bar_buffer], dtype=np.float64)
        closes = np.array([b.close for b in self.bar_buffer], dtype=np.float64)
        volumes = np.array([b.volume for b in self.bar_buffer], dtype=np.float64)

        # Generate signal with rough levels for reversal scoring
        signal = self.signal_engine.generate_signal(
            instrument=self.instrument,
            timeframe=self.timeframe,
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
            current_bar_idx=len(closes) - 1,
            rough_levels=self.rough_levels,
        )

        if signal is None or signal.action == "no_trade":
            return None

        if signal.confidence < self.min_confidence:
            return None

        # Convert TradingSignal → StrategySignal
        return self._to_strategy_signal(signal, state)

    def _compute_rough_levels(self) -> None:
        """
        Compute rough support/resistance levels from swing highs/lows.
        Used for reversal scoring when proper level counting isn't available.
        Sets mid-range levels (R2/D2 proxies) so formations can score above 0.15.
        """
        if len(self.bar_buffer) < 50:
            return

        highs_arr = np.array([b.high for b in self.bar_buffer], dtype=np.float64)
        lows_arr = np.array([b.low for b in self.bar_buffer], dtype=np.float64)
        closes_arr = np.array([b.close for b in self.bar_buffer], dtype=np.float64)

        # Find swing highs and lows
        lookback = 5
        swing_highs = []
        swing_lows = []
        for i in range(lookback, len(highs_arr) - lookback):
            is_high = True
            is_low = True
            for j in range(1, lookback + 1):
                if highs_arr[i] <= highs_arr[i-j] or highs_arr[i] <= highs_arr[i+j]:
                    is_high = False
                if lows_arr[i] >= lows_arr[i-j] or lows_arr[i] >= lows_arr[i+j]:
                    is_low = False
            if is_high:
                swing_highs.append(highs_arr[i])
            if is_low:
                swing_lows.append(lows_arr[i])

        if not swing_highs or not swing_lows:
            return

        self.rough_levels = {}
        price = closes_arr[-1]

        # Use percentile-based levels so formations can get reversal_score >= 0.15
        # R3: recent high (top 20% of swings)
        # R2: upper-mid (60th percentile of swings)
        # D3: recent low (bottom 20% of swings)
        # D2: lower-mid (40th percentile of swings)
        if len(swing_highs) >= 3:
            sorted_h = sorted(swing_highs)
            self.rough_levels["R3"] = sorted_h[-1]  # Highest = R3
            self.rough_levels["R2"] = sorted_h[int(len(sorted_h) * 0.6)]  # Upper-mid
        if len(swing_lows) >= 3:
            sorted_l = sorted(swing_lows)
            self.rough_levels["D3"] = sorted_l[0]  # Lowest = D3
            self.rough_levels["D2"] = sorted_l[int(len(sorted_l) * 0.4)]  # Lower-mid

    def _to_strategy_signal(
        self, signal: TradingSignal, state: MarketState
    ) -> StrategySignal:
        """Convert a TradingSignal into a StrategySignal for the backtest engine."""
        direction = TradeDirection.LONG if signal.direction == "long" else TradeDirection.SHORT

        entry_price = (signal.entry.price_low + signal.entry.price_high) / 2

        tp1 = signal.targets[0].price if len(signal.targets) > 0 else signal.stop_loss.price * 1.01
        tp2 = signal.targets[1].price if len(signal.targets) > 1 else tp1
        return StrategySignal(
            direction=direction,
            entry_price=entry_price,
            stop_loss=signal.stop_loss.price,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=signal.targets[2].price if len(signal.targets) > 2 else tp2,
            confidence=signal.confidence,
            rationale=f"TTC signal: {signal.setup_type.value if hasattr(signal, 'setup_type') else 'unknown'}",
        )
