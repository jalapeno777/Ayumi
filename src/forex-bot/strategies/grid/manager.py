from __future__ import annotations

from datetime import datetime
from typing import Optional

from .config import GridConfig, GridDirectionBias
from .types import (
    GridLevel,
    GridLevelStatus,
    GridSide,
    GridState,
    GridTrade,
)
from .trend_filter import TrendFilter, TrendFilterResult


class GridManager:
    def __init__(self, config: GridConfig):
        self._config = config
        self._trend_filter = TrendFilter(config)
        self._state: Optional[GridState] = None

    @property
    def config(self) -> GridConfig:
        return self._config

    @property
    def state(self) -> Optional[GridState]:
        return self._state

    def initialize(
        self,
        center_price: float,
        equity: float,
        current_time: Optional[datetime] = None,
    ) -> GridState:
        tf = self._get_initial_trend_filter(center_price)

        if not tf.enabled:
            self._state = GridState(
                center_price=center_price,
                equity_at_start=equity,
                is_active=False,
                last_reset_day=current_time.day if current_time else None,
            )
            return self._state

        buy_levels = self._build_levels(
            GridSide.BUY, center_price, tf
        )
        sell_levels = self._build_levels(
            GridSide.SELL, center_price, tf
        )

        self._state = GridState(
            center_price=center_price,
            buy_levels=buy_levels,
            sell_levels=sell_levels,
            equity_at_start=equity,
            adx_value=tf.adx,
            direction_bias=self._side_from_bias(tf.direction_bias),
            is_active=True,
            last_reset_day=current_time.day if current_time else None,
        )
        return self._state

    def on_bar(
        self,
        high: float,
        low: float,
        close: float,
        bars_high: list[float],
        bars_low: list[float],
        bars_close: list[float],
        current_time: Optional[datetime] = None,
        equity: Optional[float] = None,
    ) -> list[GridTrade]:
        if self._state is None or not self._state.is_active:
            return []

        self._check_daily_reset(current_time, equity)
        if self._state is None or not self._state.is_active:
            return []

        if equity is not None:
            if self._check_equity_stop(equity):
                return []
            if self._check_daily_loss(equity, current_time):
                return []

        tf = self._trend_filter.evaluate(bars_high, bars_low, bars_close)
        self._state.adx_value = tf.adx

        if not tf.enabled:
            self._cancel_all_levels()
            self._close_all_trades(close, current_time)
            self._state.is_active = False
            return []

        self._state.direction_bias = self._side_from_bias(tf.direction_bias)

        new_trades = self._check_fills(high, low, close, current_time)
        return new_trades

    def on_trade_close(
        self,
        trade: GridTrade,
        exit_price: float,
        exit_time: Optional[datetime] = None,
    ) -> None:
        if self._state is None:
            return

        trade.exit_price = exit_price
        trade.exit_time = exit_time or datetime.now()
        trade.is_open = False

        if trade.side == GridSide.BUY:
            pips = (exit_price - trade.entry_price) / self._config.pip_value
        else:
            pips = (trade.entry_price - exit_price) / self._config.pip_value

        trade.pips = pips
        pnl = pips * trade.lot_size * self._config.pip_value * self._config.contract_size
        trade.pnl = pnl

        self._state.total_pnl += pnl
        self._state.realized_pips += pips
        self._state.daily_pnl += pnl

        if trade in self._state.open_trades:
            self._state.open_trades.remove(trade)
            self._state.closed_trades.append(trade)

    def reset(self, center_price: float, equity: float) -> GridState:
        closed_trades = []
        total_pnl = 0.0
        realized_pips = 0.0
        if self._state is not None:
            closed_trades = self._state.closed_trades
            total_pnl = self._state.total_pnl
            realized_pips = self._state.realized_pips

        new_state = self.initialize(center_price, equity)
        new_state.closed_trades = closed_trades
        new_state.total_pnl = total_pnl
        new_state.realized_pips = realized_pips
        return new_state

    def _build_levels(
        self,
        side: GridSide,
        center_price: float,
        tf: TrendFilterResult,
    ) -> list[GridLevel]:
        levels: list[GridLevel] = []

        if tf.direction_bias == GridDirectionBias.LONG and side == GridSide.SELL:
            return levels
        if tf.direction_bias == GridDirectionBias.SHORT and side == GridSide.BUY:
            return levels

        if self._config.spread > 0 and self._config.grid_spacing <= self._config.spread:
            return levels

        max_levels = self._config.levels_per_side
        if tf.active_levels_fraction < 1.0:
            max_levels = max(1, int(max_levels * tf.active_levels_fraction))

        for i in range(1, max_levels + 1):
            offset = self._config.grid_spacing * i
            if side == GridSide.BUY:
                price = center_price - offset
            else:
                price = center_price + offset

            lot_size = self._config.lot_for_level(i - 1)
            levels.append(
                GridLevel(
                    index=i,
                    side=side,
                    price=price,
                    lot_size=lot_size,
                )
            )

        return levels

    def _check_fills(
        self,
        high: float,
        low: float,
        close: float,
        current_time: Optional[datetime] = None,
    ) -> list[GridTrade]:
        if self._state is None:
            return []

        new_trades: list[GridTrade] = []
        now = current_time or datetime.now()

        for level in self._state.all_active_levels:
            if self._state.open_trade_count >= self._config.risk.max_open_positions:
                break

            filled = False
            if level.side == GridSide.BUY and low <= level.price:
                filled = True
            elif level.side == GridSide.SELL and high >= level.price:
                filled = True

            if filled:
                level.status = GridLevelStatus.FILLED
                level.filled_at = now
                level.entry_price = level.price

                trade = GridTrade(
                    level=level,
                    entry_price=level.price,
                    lot_size=level.lot_size,
                    side=level.side,
                    entry_time=now,
                    is_open=True,
                )
                self._state.open_trades.append(trade)
                new_trades.append(trade)

        return new_trades

    def _check_equity_stop(self, equity: float) -> bool:
        if self._state is None:
            return False
        equity_loss_pct = (
            (self._state.equity_at_start - equity) / self._state.equity_at_start
            if self._state.equity_at_start > 0
            else 0.0
        )
        if equity_loss_pct >= self._config.risk.equity_stop_pct:
            self._cancel_all_levels()
            self._state.is_active = False
            return True
        return False

    def _check_daily_loss(
        self,
        equity: float,
        current_time: Optional[datetime] = None,
    ) -> bool:
        if self._state is None:
            return False
        if self._config.risk.max_daily_loss_pct <= 0:
            return False
        daily_loss = min(0.0, self._state.daily_pnl)
        current_equity = equity if equity is not None else (self._state.equity_at_start + self._state.total_pnl)
        daily_loss_pct = abs(daily_loss) / current_equity if current_equity > 0 else 0.0
        if daily_loss_pct >= self._config.risk.max_daily_loss_pct:
            self._cancel_all_levels()
            self._state.is_active = False
            return True
        return False

    def _check_daily_reset(
        self,
        current_time: Optional[datetime],
        equity: Optional[float] = None,
    ) -> None:
        if self._state is None or current_time is None:
            return
        if self._state.last_reset_day is not None and current_time.day != self._state.last_reset_day:
            self._state.daily_pnl = 0.0
            self._state.last_reset_day = current_time.day
            if equity is not None:
                self._state.equity_at_start = equity

    def _cancel_all_levels(self) -> None:
        if self._state is None:
            return
        for level in self._state.buy_levels:
            if level.status == GridLevelStatus.ACTIVE:
                level.status = GridLevelStatus.CANCELLED
        for level in self._state.sell_levels:
            if level.status == GridLevelStatus.ACTIVE:
                level.status = GridLevelStatus.CANCELLED

    def _close_all_trades(self, close_price: float, close_time: Optional[datetime] = None) -> None:
        if self._state is None:
            return
        now = close_time or datetime.now()
        for trade in list(self._state.open_trades):
            self.on_trade_close(trade, close_price, now)

    def _get_initial_trend_filter(self, center_price: float) -> TrendFilterResult:
        return TrendFilterResult(
            enabled=True,
            adx=0.0,
            direction_bias=GridDirectionBias.NONE,
            active_levels_fraction=1.0,
            reason="Initial setup (no bars yet)",
        )

    @staticmethod
    def _side_from_bias(bias: GridDirectionBias) -> Optional[GridSide]:
        if bias == GridDirectionBias.LONG:
            return GridSide.BUY
        if bias == GridDirectionBias.SHORT:
            return GridSide.SELL
        return None
