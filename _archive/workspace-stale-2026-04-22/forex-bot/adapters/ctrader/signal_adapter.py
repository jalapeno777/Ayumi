import logging
from datetime import datetime
from typing import Optional, List, Callable

from ...backtest.engine import MarketState
from ...backtest.strategies import ISignalStrategy
from .models import TradeSignal, TradeDirection
from .paper_trader import PaperTrader


logger = logging.getLogger(__name__)


class cTraderSignalAdapter:
    def __init__(
        self,
        paper_trader: PaperTrader,
        strategy: ISignalStrategy,
        symbol: str = "EURUSD",
    ):
        self._paper_trader = paper_trader
        self._strategy = strategy
        self._symbol = symbol
        self._min_confidence: float = 0.50
        self._last_signal_time: Optional[datetime] = None
        self._callbacks: List[tuple[str, Callable]] = []

    def set_min_confidence(self, confidence: float):
        self._min_confidence = confidence

    def evaluate_and_trade(self, market_state: MarketState) -> Optional[TradeSignal]:
        signal = self._strategy.evaluate(market_state)

        if signal is None:
            return None

        if signal.confidence < self._min_confidence:
            logger.debug(
                f"Signal confidence {signal.confidence:.2f} below minimum {self._min_confidence:.2f}"
            )
            return None

        trade_direction = self._convert_direction(signal.direction)

        trade_signal = TradeSignal(
            symbol=self._symbol,
            direction=trade_direction,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            take_profit_3=signal.take_profit_3,
            volume=0.1,
            confidence=signal.confidence,
            rationale=signal.rationale,
        )

        result = self._paper_trader.process_signal(trade_signal)

        if result.success:
            self._last_signal_time = datetime.utcnow()
            logger.info(
                f"Signal traded: {self._strategy.name} {trade_direction.value} {self._symbol} @ {signal.entry_price}"
            )
            self._trigger_callback("on_signal_traded", result)
        else:
            logger.warning(f"Signal rejected: {result.rejection_reason}")
            self._trigger_callback("on_signal_rejected", result)

        return trade_signal

    def _convert_direction(self, direction) -> TradeDirection:
        from ...backtest.engine import TradeDirection as BacktestTradeDirection

        if isinstance(direction, BacktestTradeDirection):
            if direction == BacktestTradeDirection.LONG:
                return TradeDirection.LONG
            elif direction == BacktestTradeDirection.SHORT:
                return TradeDirection.SHORT
        return TradeDirection.NEUTRAL

    def register_callback(self, event: str, callback: Callable):
        if event not in ["on_signal_traded", "on_signal_rejected"]:
            raise ValueError(f"Unknown event: {event}")
        self._callbacks.append((event, callback))

    def _trigger_callback(self, event: str, *args, **kwargs):
        for evt, callback in self._callbacks:
            if evt == event:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Callback error for {event}: {e}")

    @property
    def strategy_name(self) -> str:
        return self._strategy.name

    @property
    def last_signal_time(self) -> Optional[datetime]:
        return self._last_signal_time


class cTraderLiveAdapter:
    def __init__(
        self,
        paper_trader: PaperTrader,
        strategies: List[ISignalStrategy],
        symbols: List[str],
    ):
        self._paper_trader = paper_trader
        self._strategies = {s.name: s for s in strategies}
        self._symbols = symbols
        self._adapters: dict = {}
        self._running = False

        for symbol in symbols:
            for strategy in strategies:
                key = f"{strategy.name}_{symbol}"
                self._adapters[key] = cTraderSignalAdapter(
                    paper_trader=paper_trader,
                    strategy=strategy,
                    symbol=symbol,
                )

    def evaluate_all_strategies(
        self, market_states: dict[str, MarketState]
    ) -> List[TradeSignal]:
        results = []
        for symbol, state in market_states.items():
            for strategy_name, strategy in self._strategies.items():
                key = f"{strategy_name}_{symbol}"
                adapter = self._adapters.get(key)
                if adapter:
                    result = adapter.evaluate_and_trade(state)
                    if result:
                        results.append(result)
        return results

    def get_adapter(
        self, strategy_name: str, symbol: str
    ) -> Optional[cTraderSignalAdapter]:
        return self._adapters.get(f"{strategy_name}_{symbol}")

    @property
    def paper_trader(self) -> PaperTrader:
        return self._paper_trader

    @property
    def is_running(self) -> bool:
        return self._running
