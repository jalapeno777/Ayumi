from __future__ import annotations

from backtest.engine import MarketState, StrategySignal, TradeDirection
from backtest.strategies import ISignalStrategy

from .config import GridConfig
from .manager import GridManager
from .types import GridSide, GridTrade


class GridStrategyAdapter(ISignalStrategy):
    def __init__(self, config: GridConfig | None = None):
        self._config = config or GridConfig.eurusd()
        self._manager = GridManager(self._config)
        self._initialized = False
        self._balance = 10000.0
        self._pending_trades: list[GridTrade] = []
        self._grid_active = False

    @property
    def name(self) -> str:
        return f"Grid Trading ({self._config.symbol})"

    @property
    def manager(self) -> GridManager:
        return self._manager

    @property
    def grid_config(self) -> GridConfig:
        return self._config

    def set_balance(self, balance: float) -> None:
        self._balance = balance

    def evaluate(self, state: MarketState) -> StrategySignal | None:
        if not state.bars:
            return None

        bars = state.bars
        close = bars[-1].close
        high = bars[-1].high
        low = bars[-1].low

        bars_high = [b.high for b in bars]
        bars_low = [b.low for b in bars]
        bars_close = [b.close for b in bars]

        if not self._initialized:
            self._manager.initialize(close, self._balance, bars[-1].time)
            self._initialized = True
            self._grid_active = self._manager.state is not None and self._manager.state.is_active
            return None

        grid_state = self._manager.state
        if grid_state is not None and not grid_state.is_active:
            self._manager.reset(close, self._balance)
            self._grid_active = self._manager.state is not None and self._manager.state.is_active
            return None

        new_trades = self._manager.on_bar(
            high=high,
            low=low,
            close=close,
            bars_high=bars_high,
            bars_low=bars_low,
            bars_close=bars_close,
            current_time=bars[-1].time,
            equity=self._balance,
        )

        if new_trades:
            self._pending_trades.extend(new_trades)
            return self._trade_to_signal(new_trades[-1], state)
        elif self._pending_trades:
            trade = self._pending_trades[-1]
            return self._trade_to_signal(trade, state)

        if self._manager.state is not None and self._manager.state.open_trades:
            latest_open = self._manager.state.open_trades[-1]
            return self._trade_to_signal(latest_open, state)

        return None

    def update_balance(self, balance: float) -> None:
        self._balance = balance

    def _trade_to_signal(self, trade: GridTrade, state: MarketState) -> StrategySignal:
        if trade.side == GridSide.BUY:
            direction = TradeDirection.LONG
        else:
            direction = TradeDirection.SHORT

        atr = state.atr if state.atr > 0 else self._config.grid_spacing
        tp_distance = self._config.take_profit_pips * self._config.pip_value

        if direction == TradeDirection.LONG:
            sl = trade.entry_price - atr * 2.0
            tp1 = trade.entry_price + tp_distance
            tp2 = trade.entry_price + tp_distance * 2.0
            tp3 = trade.entry_price + tp_distance * 3.0
        else:
            sl = trade.entry_price + atr * 2.0
            tp1 = trade.entry_price - tp_distance
            tp2 = trade.entry_price - tp_distance * 2.0
            tp3 = trade.entry_price - tp_distance * 3.0

        grid_state = self._manager.state
        rationale = f"Grid {trade.side.value} level {trade.level.index}"
        if grid_state is not None:
            rationale += f" (ADX={grid_state.adx_value:.1f})"

        return StrategySignal(
            direction=direction,
            confidence=0.6,
            entry_price=trade.entry_price,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            rationale=rationale,
        )
