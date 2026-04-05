import numpy as np
from typing import List, Optional
from .engine import Bar, MarketState, StrategySignal, TradeDirection
from .strategies import ISignalStrategy
from quant.cointegration import PairsSignalGenerator


class StatArbStrategy(ISignalStrategy):
    def __init__(
        self,
        lookback: int = 60,
        entry_threshold: float = 2.0,
        exit_threshold: float = 0.0,
        stop_loss_threshold: float = 3.0,
        atr_multiplier: float = 2.0,
        pair_b_bars: Optional[List[Bar]] = None,
    ):
        self.lookback = lookback
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.stop_loss_threshold = stop_loss_threshold
        self.atr_multiplier = atr_multiplier
        self._signal_generator = PairsSignalGenerator(
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            stop_loss_threshold=stop_loss_threshold,
            lookback=lookback,
        )
        self._pair_b_bars = pair_b_bars or []
        self._last_signal: Optional[str] = None
        self._position_open: bool = False

    @property
    def name(self) -> str:
        return "Statistical Arbitrage"

    def set_pair_b_bars(self, bars: List[Bar]):
        self._pair_b_bars = bars

    def reset(self):
        self._signal_generator.reset()
        self._last_signal = None
        self._position_open = False

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        if len(state.bars) < self.lookback + 1:
            return None

        if len(self._pair_b_bars) < len(state.bars):
            return None

        prices_a = np.array([b.close for b in state.bars])
        prices_b = np.array([b.close for b in self._pair_b_bars[: len(state.bars)]])

        if not self._signal_generator.update_cointegration(prices_a, prices_b):
            return None

        signal, reason = self._signal_generator.generate_signal(prices_a, prices_b)

        if signal is None:
            self._last_signal = None
            self._position_open = False
            return None

        if reason is None:
            reason = "unknown"

        if signal.startswith("entry"):
            self._last_signal = signal
            self._position_open = True
            return self._create_signal(state, signal, reason)

        if signal == "exit" or signal == "stop_loss":
            self._last_signal = None
            self._position_open = False
            return None

        if signal.startswith("hold"):
            if not self._position_open or self._last_signal is None:
                return None
            return self._create_signal(state, self._last_signal, reason)

        return None

    def _create_signal(
        self, state: MarketState, direction_signal: str, reason: str
    ) -> Optional[StrategySignal]:
        latest = state.latest_bar
        atr = state.atr if state.atr > 0 else self._calculate_atr(state.bars)

        if atr < 1e-10:
            atr = 0.0001

        if direction_signal == "entry_long" or (
            direction_signal.startswith("hold") and self._last_signal == "entry_long"
        ):
            direction = TradeDirection.LONG
            entry = latest.close
            sl = entry - atr * self.atr_multiplier
            risk = abs(entry - sl)
            tp1 = entry + risk * 1.0
            tp2 = entry + risk * 2.0
            tp3 = entry + risk * 3.0
            z_score = self._signal_generator.compute_z_score(
                np.array([b.close for b in state.bars]),
                np.array([b.close for b in self._pair_b_bars[: len(state.bars)]]),
            )
            confidence = min(0.85, 0.55 + abs(z_score) * 0.10) if z_score else 0.60
            rationale = f"StatArb long spread: z={z_score:.2f}, {reason}"
        elif direction_signal == "entry_short" or (
            direction_signal.startswith("hold") and self._last_signal == "entry_short"
        ):
            direction = TradeDirection.SHORT
            entry = latest.close
            sl = entry + atr * self.atr_multiplier
            risk = abs(entry - sl)
            tp1 = entry - risk * 1.0
            tp2 = entry - risk * 2.0
            tp3 = entry - risk * 3.0
            z_score = self._signal_generator.compute_z_score(
                np.array([b.close for b in state.bars]),
                np.array([b.close for b in self._pair_b_bars[: len(state.bars)]]),
            )
            confidence = min(0.85, 0.55 + abs(z_score) * 0.10) if z_score else 0.60
            rationale = f"StatArb short spread: z={z_score:.2f}, {reason}"
        else:
            return None

        return StrategySignal(
            direction=direction,
            confidence=confidence,
            entry_price=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            rationale=rationale,
        )

    def _calculate_atr(self, bars: List[Bar]) -> float:
        if len(bars) < 15:
            return 0.0001
        tr_sum = 0.0
        for i in range(len(bars) - 14, len(bars)):
            if i > 0:
                tr = max(
                    bars[i].high - bars[i].low,
                    max(
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close),
                    ),
                )
                tr_sum += tr
        return tr_sum / 14

    def get_current_z_score(self, state: MarketState) -> Optional[float]:
        if len(state.bars) < self.lookback + 1:
            return None
        if len(self._pair_b_bars) < len(state.bars):
            return None

        prices_a = np.array([b.close for b in state.bars])
        prices_b = np.array([b.close for b in self._pair_b_bars[: len(state.bars)]])

        if self._signal_generator._hedge_ratio is None:
            if not self._signal_generator.update_cointegration(prices_a, prices_b):
                return None

        return self._signal_generator.compute_z_score(prices_a, prices_b)


class StatArbBacktestResult:
    def __init__(self):
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.losing_trades: int = 0
        self.total_pnl: float = 0.0
        self.max_drawdown: float = 0.0
        self.z_scores: List[float] = []
        self.signals: List[str] = []

    def add_signal(self, signal_type: str, z_score: Optional[float]):
        self.signals.append(signal_type)
        if z_score is not None:
            self.z_scores.append(z_score)
