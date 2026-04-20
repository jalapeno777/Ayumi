"""Mixin classes for BacktestEngine composition.

ProgressiveSLMixin — multi-TP exit with progressive stop-loss management.
CombinedSignalMixin — signal combination across multiple strategies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd


class SignalCombineMethod(Enum):
    WEIGHTED = "weighted"
    VOTED = "voted"
    BEST = "best"


@dataclass
class ProgressiveSLConfig:
    tp1_ratio: float = 0.33
    tp2_ratio: float = 0.66
    tp3_ratio: float = 1.0
    tp1_sl_move: float = 0.0
    tp2_sl_move: float = 0.5
    tp3_trailing: bool = True
    trailing_atr_mult: float = 1.0
    atr_period: int = 14


class ProgressiveSLMixin:
    """Multi-TP exit with progressive stop-loss management.

    Expects the host engine to have ``positions``, ``_close_trade``, and
    ``_get_open_position`` attributes/methods (provided by EngineCore).
    """

    def __init__(self, sl_config: Optional[ProgressiveSLConfig] = None):
        self._sl_config = sl_config or ProgressiveSLConfig()
        self._tp_stage: dict[int, int] = {}

    def _check_progressive_sl_tp(
        self,
        current_bar: pd.Series,
        timestamp: pd.Timestamp,
        pair: str,
    ) -> Optional[float]:
        pos = self._get_open_position(pair)
        if pos is None or pos.take_profit is None or pos.stop_loss is None:
            return None

        entry = pos.entry_price
        sl = pos.stop_loss
        tp = pos.take_profit
        risk = abs(tp - entry)
        direction = pos.direction

        if direction == "long":
            tp1 = entry + risk * self._sl_config.tp1_ratio
            tp2 = entry + risk * self._sl_config.tp2_ratio
            tp3 = entry + risk * self._sl_config.tp3_ratio
            bar_low = float(current_bar["low"])
            bar_high = float(current_bar["high"])

            if bar_low <= sl:
                return sl

            stage = self._tp_stage.get(id(pos), 0)
            if stage == 0 and bar_high >= tp1:
                self._tp_stage[id(pos)] = 1
                new_sl = entry + self._sl_config.tp1_sl_move * risk
                self._update_sl(pos, new_sl)
                if bar_low <= new_sl:
                    return new_sl
            elif stage == 1 and bar_high >= tp2:
                self._tp_stage[id(pos)] = 2
                new_sl = entry + self._sl_config.tp2_sl_move * risk
                self._update_sl(pos, new_sl)
                if bar_low <= new_sl:
                    return new_sl
            elif stage == 2 and bar_high >= tp3:
                return tp3

            if stage >= 2 and self._sl_config.tp3_trailing:
                atr = self._calculate_atr(current_bar)
                if atr and atr > 0:
                    trail_sl = bar_high - atr * self._sl_config.trailing_atr_mult
                    if trail_sl > pos.stop_loss:
                        self._update_sl(pos, trail_sl)
                        if bar_low <= trail_sl:
                            return trail_sl

        else:
            tp1 = entry - risk * self._sl_config.tp1_ratio
            tp2 = entry - risk * self._sl_config.tp2_ratio
            tp3 = entry - risk * self._sl_config.tp3_ratio
            bar_low = float(current_bar["low"])
            bar_high = float(current_bar["high"])

            if bar_high >= sl:
                return sl

            stage = self._tp_stage.get(id(pos), 0)
            if stage == 0 and bar_low <= tp1:
                self._tp_stage[id(pos)] = 1
                new_sl = entry - self._sl_config.tp1_sl_move * risk
                self._update_sl(pos, new_sl)
                if bar_high >= new_sl:
                    return new_sl
            elif stage == 1 and bar_low <= tp2:
                self._tp_stage[id(pos)] = 2
                new_sl = entry - self._sl_config.tp2_sl_move * risk
                self._update_sl(pos, new_sl)
                if bar_high >= new_sl:
                    return new_sl
            elif stage == 2 and bar_low <= tp3:
                return tp3

            if stage >= 2 and self._sl_config.tp3_trailing:
                atr = self._calculate_atr(current_bar)
                if atr and atr > 0:
                    trail_sl = bar_low + atr * self._sl_config.trailing_atr_mult
                    if trail_sl < pos.stop_loss:
                        self._update_sl(pos, trail_sl)
                        if bar_high >= trail_sl:
                            return trail_sl

        return None

    def _update_sl(self, pos, new_sl: float) -> None:
        pos.stop_loss = new_sl

    def _calculate_atr(self, current_bar: pd.Series) -> Optional[float]:
        return None

    def _clear_tp_stage(self, pos_id: int) -> None:
        self._tp_stage.pop(pos_id, None)


class CombinedSignalMixin:
    """Signal combination across multiple strategies.

    Supports WEIGHTED (confluence scoring), VOTED (majority rules),
    and BEST (strongest signal wins) methods.
    """

    def __init__(
        self,
        method: SignalCombineMethod = SignalCombineMethod.WEIGHTED,
        weights: Optional[dict[str, float]] = None,
        min_threshold: float = 0.3,
    ):
        self._combine_method = method
        self._weights = weights or {}
        self._min_threshold = min_threshold

    def combine_signals(
        self,
        signals: dict[str, pd.Series],
    ) -> pd.Series:
        if not signals:
            raise ValueError("No signals provided")

        lengths = {name: len(s) for name, s in signals.items()}
        if len(set(lengths.values())) > 1:
            min_len = min(lengths.values())
            signals = {name: s.iloc[:min_len] for name, s in signals.items()}

        index = next(iter(signals.values())).index
        strategy_names = list(signals.keys())

        if self._combine_method == SignalCombineMethod.WEIGHTED:
            return self._weighted_combine(signals, strategy_names, index)
        elif self._combine_method == SignalCombineMethod.VOTED:
            return self._voted_combine(signals, strategy_names, index)
        elif self._combine_method == SignalCombineMethod.BEST:
            return self._best_combine(signals, strategy_names, index)
        else:
            raise ValueError(f"Unknown method: {self._combine_method}")

    def _weighted_combine(
        self,
        signals: dict[str, pd.Series],
        names: list[str],
        index,
    ) -> pd.Series:
        weights = self._normalize_weights(names)

        combined = pd.Series(0.0, index=index)
        for name, sig in signals.items():
            combined += weights[name] * sig

        combined = combined.where(combined.abs() >= self._min_threshold, 0.0)
        return combined

    def _voted_combine(
        self,
        signals: dict[str, pd.Series],
        names: list[str],
        index,
    ) -> pd.Series:
        n = len(names)
        majority = n / 2

        votes = pd.DataFrame(signals)
        longs = (votes > 0).sum(axis=1)
        shorts = (votes < 0).sum(axis=1)

        result = pd.Series(0.0, index=index)
        result[longs > majority] = 1.0
        result[shorts > majority] = -1.0

        return result

    def _best_combine(
        self,
        signals: dict[str, pd.Series],
        names: list[str],
        index,
    ) -> pd.Series:
        stacked = pd.DataFrame(signals)
        abs_max = stacked.abs().max(axis=1)

        result = pd.Series(0.0, index=index)
        for name in names:
            mask = stacked[name].abs() == abs_max
            result[mask] = stacked[name][mask]

        return result.where(result.abs() >= self._min_threshold, 0.0)

    def _normalize_weights(self, names: list[str]) -> dict[str, float]:
        weights = {}
        for name in names:
            weights[name] = self._weights.get(name, 1.0)

        total = sum(weights.values())
        if total == 0:
            equal = 1.0 / len(names)
            return {name: equal for name in names}

        return {name: w / total for name, w in weights.items()}
