"""TradeManagementMixin — delegates SL/TP checking to the engine core.

This mixin wraps the basic stop-loss / take-profit logic that the legacy
BacktestEngine performs inline. It is designed to be mixed into BacktestEngine
alongside EngineCore so the engine can delegate exit checks cleanly.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


class TradeManagementMixin:
    """Basic stop-loss / take-profit trade management.

    Host engine must provide ``positions``, ``_close_trade``, and
    ``_has_open_position`` (all from EngineCore).
    """

    def check_sl_tp(
        self,
        current_bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> list[dict]:
        positions_to_close = []
        for i, pos in enumerate(self.positions):
            hit_sl = False
            hit_tp = False
            exit_price: Optional[float] = None

            if pos.direction == "long":
                if (
                    pos.stop_loss is not None
                    and float(current_bar["low"]) <= pos.stop_loss
                ):
                    hit_sl = True
                    exit_price = pos.stop_loss
                elif (
                    pos.take_profit is not None
                    and float(current_bar["high"]) >= pos.take_profit
                ):
                    hit_tp = True
                    exit_price = pos.take_profit
            else:
                if (
                    pos.stop_loss is not None
                    and float(current_bar["high"]) >= pos.stop_loss
                ):
                    hit_sl = True
                    exit_price = pos.stop_loss
                elif (
                    pos.take_profit is not None
                    and float(current_bar["low"]) <= pos.take_profit
                ):
                    hit_tp = True
                    exit_price = pos.take_profit

            if hit_sl or hit_tp and exit_price is not None:
                positions_to_close.append(
                    (i, exit_price, "stop_loss" if hit_sl else "take_profit")
                )

        closed_trades = []
        for i, exit_price, reason in reversed(positions_to_close):
            pos = self.positions[i]
            pnl = self._close_trade(pos, i, timestamp, exit_price, reason)
            closed_trades.append({"position_index": i, "pnl": pnl, "reason": reason})

        return closed_trades
