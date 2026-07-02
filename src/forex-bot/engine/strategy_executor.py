from __future__ import annotations

import csv
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from backtest.engine import Bar, BarPeriod, MarketState, TradeDirection, determine_session
from backtest.strategies import ISignalStrategy

from .protocol import CanonicalSignal
from .strategy_registry import StrategySlot

logger = logging.getLogger(__name__)

_DEFAULT_MAX_BARS = 500
_DEFAULT_MIN_BARS = 50


class StrategyExecutor:
    def __init__(
        self,
        slot: StrategySlot,
        strategy: ISignalStrategy,
        max_bars: int = _DEFAULT_MAX_BARS,
        min_bars: int = _DEFAULT_MIN_BARS,
        historical_bars_csv: Optional[str] = None,
    ):
        self._slot = slot
        self._strategy = strategy
        self._max_bars = max_bars
        self._min_bars = min_bars
        self._lock = threading.RLock()

        self._bars: list[Bar] = []
        self._current_bar: Optional[Bar] = None
        self._bar_period = self._parse_bar_period(slot.timeframe)
        self._bar_closed = False

        if historical_bars_csv:
            self._load_historical_bars(historical_bars_csv)

    @property
    def slot_id(self) -> str:
        return self._slot.id

    @property
    def slot(self) -> StrategySlot:
        return self._slot

    @property
    def symbol(self) -> str:
        return self._slot.symbol

    @property
    def bar_count(self) -> int:
        with self._lock:
            return len(self._bars)

    @property
    def ready(self) -> bool:
        with self._lock:
            total = len(self._bars) + (1 if self._current_bar else 0)
            return total >= self._min_bars

    def on_tick(
        self,
        tick_price: float,
        tick_bid: float,
        tick_ask: float,
        tick_timestamp: datetime,
    ):
        with self._lock:
            self._bar_closed = False
            bar_time = self._bar_period_start(tick_timestamp)
            self._update_current_bar(tick_price, tick_bid, tick_ask, bar_time)

    def try_evaluate(self) -> Optional[CanonicalSignal]:
        with self._lock:
            if not self._bar_closed:
                return None
            if not self.ready:
                return None

            bars = list(self._bars)
            if self._current_bar is not None:
                bars.append(self._current_bar)

        if not bars:
            return None

        try:
            state = MarketState(
                bars=bars,
                current_session=determine_session(bars[-1].time),
            )
            result = self._strategy.evaluate(state)
            if result is None:
                return None
            return self._to_canonical_signal(result)
        except Exception as exc:
            logger.error(
                "Strategy evaluation error [%s]: %s", self._slot.id, exc, exc_info=True
            )
            return None

    def _to_canonical_signal(self, result) -> CanonicalSignal:
        direction = result.direction
        if isinstance(direction, TradeDirection):
            pass
        elif hasattr(direction, "value"):
            direction = TradeDirection(direction.value)
        else:
            direction = TradeDirection.NEUTRAL

        return CanonicalSignal(
            strategy_id=self._slot.id,
            symbol=self._slot.symbol,
            direction=direction,
            confidence=result.confidence,
            entry_price=result.entry_price,
            stop_loss=result.stop_loss,
            take_profit_1=result.take_profit_1,
            take_profit_2=result.take_profit_2 if result.take_profit_2 != 0.0 else None,
            take_profit_3=result.take_profit_3 if result.take_profit_3 != 0.0 else None,
            rationale=result.rationale,
            metadata={"is_volatile": getattr(result, "is_volatile", False)},
        )

    def _bar_period_start(self, ts: datetime) -> datetime:
        minutes = self._bar_period.minutes
        return ts.replace(second=0, microsecond=0) - timedelta(
            minutes=ts.minute % minutes
        )

    def _update_current_bar(
        self, price: float, bid: float, ask: float, bar_time: datetime
    ):
        current = self._current_bar

        if current is not None and current.time == bar_time:
            updated = Bar(
                time=current.time,
                open=current.open,
                high=max(current.high, ask),
                low=min(current.low, bid),
                close=price,
                volume=current.volume + 1,
            )
            self._current_bar = updated
            return

        self._finalize_and_store_bar()

        self._current_bar = Bar(
            time=bar_time,
            open=price,
            high=ask,
            low=bid,
            close=price,
            volume=1,
        )
        self._bar_closed = True

    def _finalize_and_store_bar(self):
        if self._current_bar is None:
            return
        finalized = Bar(
            time=self._current_bar.time,
            open=self._current_bar.open,
            high=self._current_bar.high,
            low=self._current_bar.low,
            close=self._current_bar.close,
            volume=self._current_bar.volume,
        )
        self._bars.append(finalized)
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars :]
        self._current_bar = None

    def _load_historical_bars(self, csv_path: str):
        path = Path(csv_path)
        if not path.exists():
            logger.warning("Historical bars CSV not found: %s", csv_path)
            return

        bars: list[Bar] = []
        try:
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        bar_time = datetime.strptime(
                            row["Date"], "%Y-%m-%d %H:%M"
                        ).replace(tzinfo=timezone.utc)
                    except (ValueError, KeyError):
                        continue
                    bars.append(
                        Bar(
                            time=bar_time,
                            open=float(row["Open"]),
                            high=float(row["High"]),
                            low=float(row["Low"]),
                            close=float(row["Close"]),
                            volume=int(float(row.get("Volume", 0))),
                        )
                    )
        except Exception as exc:
            logger.error("Failed to load historical bars: %s", exc)
            return

        if bars:
            self._bars = bars[-self._max_bars :]
            logger.info(
                "Loaded %d historical bars for %s (%s to %s)",
                len(self._bars),
                self._slot.id,
                self._bars[0].time.strftime("%Y-%m-%d %H:%M"),
                self._bars[-1].time.strftime("%Y-%m-%d %H:%M"),
            )

    @staticmethod
    def _parse_bar_period(timeframe: str) -> BarPeriod:
        tf = timeframe.upper()
        period_map = {
            "M1": 1,
            "M5": 5,
            "M15": 15,
            "M30": 30,
            "H1": 60,
            "H4": 240,
            "D1": 1440,
        }
        minutes = period_map.get(tf, 60)
        return BarPeriod(minutes)
