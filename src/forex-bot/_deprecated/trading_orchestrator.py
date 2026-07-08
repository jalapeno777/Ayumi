"""Unified Trading Orchestrator — single pipeline for multi-strategy portfolio trading.

Replaces the three separate execution paths (forward_test_engine, run_live_paper,
Kai's orchestrator) with one config-driven orchestrator that handles strategy
registry, signal pipeline, risk integration, and order management.

Usable for both paper trading and forward testing — same code, different order
routing (paper vs cTrader FIX).

Usage::

    config = OrchestratorConfig(...)
    orch = TradingOrchestrator(config, paper_trader=paper_trader)
    orch.register_strategy(srmr_plus, symbols=["XAUUSD"], timeframes=["H1"], ...)
    orch.register_strategy(session_mr, symbols=["XAUUSD"], timeframes=["H1"], ...)
    orch.register_strategy(ttc, symbols=["EURUSD"], timeframes=["H1"], ...)

    # Feed bars on bar close:
    orch.on_bar_close("XAUUSD", "H1", bars)

    # Or feed ticks for automatic bar building:
    orch.on_tick("XAUUSD", bid, ask, timestamp)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from backtest.engine import Bar, MarketState, SessionType
from backtest.strategy_legacy import ISignalStrategy
from signal_engine.risk_sizer import ConfidencePositionSizer

if TYPE_CHECKING:
    from adapters.ctrader.models import Position
    from quant.correlation import CorrelationTracker
    from adapters.ctrader.paper_trader import PaperTrader
    from adapters.ctrader.risk_guard import FTMOConfig, RiskGuard

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StrategySlotConfig:
    """Per-strategy configuration within the orchestrator."""
    symbols: list[str]
    timeframes: list[str]  # e.g. ["H1"], ["M5", "H1"]
    min_confidence: float = 0.50
    max_positions_per_symbol: int = 1
    cooldown_sec: float = 300.0  # seconds between signals for same strategy+symbol


@dataclass
class RiskConfig:
    """Portfolio-level risk parameters."""
    max_drawdown_pct: float = 0.10  # FTMO 10% max drawdown limit
    daily_loss_limit_pct: float = 0.05
    max_concurrent_positions: int = 5
    max_trades_per_day: int = 10
    min_risk_reward: float = 1.5
    max_position_size_pct: float = 0.005
    correlation_threshold: float = 0.7
    # Session hours (UTC) — trading only allowed within these windows
    session_start_utc_hour: int = 0  # 0 = no restriction
    session_end_utc_hour: int = 24  # 24 = no restriction


@dataclass
class OrchestratorConfig:
    """Top-level orchestrator configuration."""
    starting_balance: float = 10_000.0
    risk: RiskConfig = field(default_factory=RiskConfig)
    max_bars_per_symbol_tf: int = 500  # max bars kept in memory per (symbol, timeframe)
    min_bars_for_evaluation: int = 50
    bar_close_evaluation_only: bool = True
    use_correlation_filter: bool = True
    log_dir: str = "logs/trades"


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _RegisteredStrategy:
    """Internal representation of a registered strategy slot."""
    instance: ISignalStrategy
    config: StrategySlotConfig
    registration_key: str  # unique key: strategy_name


@dataclass
class _BarTracker:
    """Aggregates ticks into bars for one (symbol, timeframe) pair."""
    symbol: str
    timeframe_minutes: int
    bars: list[Bar] = field(default_factory=list)
    current_bar: Optional[Bar] = None
    current_bar_start: Optional[datetime] = None
    last_evaluated_bar_start: Optional[datetime] = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add_tick(self, bid: float, ask: float, timestamp: datetime) -> Optional[Bar]:
        """Add a tick and return a finalized bar if one just closed."""
        mid = (bid + ask) / 2.0
        bar_start = self._floor_to_period(timestamp)

        closed_bar: Optional[Bar] = None

        with self.lock:
            if self.current_bar_start is None or bar_start > self.current_bar_start:
                # New bar — finalize previous
                if self.current_bar is not None and self.current_bar_start is not None:
                    closed_bar = Bar(
                        time=self.current_bar_start,
                        open=self.current_bar.open,
                        high=self.current_bar.high,
                        low=self.current_bar.low,
                        close=self.current_bar.close,
                        volume=self.current_bar.volume,
                    )
                    self.bars.append(closed_bar)
                    if len(self.bars) > 5000:  # hard cap
                        self.bars = self.bars[-3000:]

                self.current_bar = Bar(
                    time=bar_start,
                    open=mid,
                    high=ask,
                    low=bid,
                    close=mid,
                    volume=1.0,
                )
                self.current_bar_start = bar_start
            else:
                # Update in-progress bar
                self.current_bar = Bar(
                    time=self.current_bar.time,
                    open=self.current_bar.open,
                    high=max(self.current_bar.high, ask),
                    low=min(self.current_bar.low, bid),
                    close=mid,
                    volume=self.current_bar.volume + 1.0,
                )

        return closed_bar

    def add_bar(self, bar: Bar) -> Optional[Bar]:
        """Add a pre-built bar (e.g. from historical data or external source).

        Returns the bar that was displaced from the end of the list if
        trimming occurred, or None.
        """
        with self.lock:
            # If this bar's time matches the current bar's time, update it
            if self.current_bar is not None and bar.time == self.current_bar_start:
                self.current_bar = Bar(
                    time=bar.time,
                    open=self.current_bar.open,
                    high=max(self.current_bar.high, bar.high),
                    low=min(self.current_bar.low, bar.low),
                    close=bar.close,
                    volume=bar.volume,
                )
                return None

            # Finalize current bar if any
            closed: Optional[Bar] = None
            if self.current_bar is not None and self.current_bar_start is not None:
                closed = Bar(
                    time=self.current_bar_start,
                    open=self.current_bar.open,
                    high=self.current_bar.high,
                    low=self.current_bar.low,
                    close=self.current_bar.close,
                    volume=self.current_bar.volume,
                )
                self.bars.append(closed)

            self.current_bar = bar
            self.current_bar_start = bar.time

            # Trim
            if len(self.bars) > 5000:
                self.bars = self.bars[-3000:]

            return closed

    def get_bars(self) -> list[Bar]:
        """Return all finalized bars + the current in-progress bar."""
        with self.lock:
            bars = list(self.bars)
            if self.current_bar is not None:
                bars.append(self.current_bar)
            return bars

    def mark_evaluated(self, bar_start: datetime):
        with self.lock:
            self.last_evaluated_bar_start = bar_start

    def needs_evaluation(self, timestamp: datetime) -> bool:
        """Check if a new bar has closed since last evaluation."""
        bar_start = self._floor_to_period(timestamp)
        with self.lock:
            if self.last_evaluated_bar_start is None:
                return True
            return bar_start > self.last_evaluated_bar_start

    def _floor_to_period(self, ts: datetime) -> datetime:
        """Floor a timestamp to the start of its bar period.

        Uses total-minutes-from-midnight so that timeframes > 60 min
        (H1=60, H4=240, D1=1440) floor correctly.  The old ``ts.minute % minutes``
        only worked for M1–M60 because ``ts.minute`` is always 0–59.
        """
        minutes = self.timeframe_minutes
        total_min = ts.hour * 60 + ts.minute
        floored_min = (total_min // minutes) * minutes
        return ts.replace(
            hour=floored_min // 60,
            minute=floored_min % 60,
            second=0,
            microsecond=0,
        )


@dataclass
class _CooldownTracker:
    """Tracks cooldowns per (strategy_key, symbol)."""
    _last_signal_time: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def is_on_cooldown(self, strategy_key: str, symbol: str, cooldown_sec: float) -> bool:
        key = f"{strategy_key}|{symbol}"
        now = time.monotonic()
        with self._lock:
            last = self._last_signal_time.get(key, 0.0)
            return (now - last) < cooldown_sec

    def record_signal(self, strategy_key: str, symbol: str):
        key = f"{strategy_key}|{symbol}"
        with self._lock:
            self._last_signal_time[key] = time.monotonic()


@dataclass
class _SignalDirectionTracker:
    """Tracks the last signal direction per (strategy_key, symbol) for flip detection."""
    _last_direction: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get_last_direction(self, strategy_key: str, symbol: str) -> Optional[str]:
        key = f"{strategy_key}|{symbol}"
        with self._lock:
            return self._last_direction.get(key)

    def update(self, strategy_key: str, symbol: str, direction: str):
        key = f"{strategy_key}|{symbol}"
        with self._lock:
            self._last_direction[key] = direction

    def clear(self, strategy_key: str, symbol: str):
        key = f"{strategy_key}|{symbol}"
        with self._lock:
            self._last_direction.pop(key, None)


# ---------------------------------------------------------------------------
# Timeframe helper
# ---------------------------------------------------------------------------

_TIMEFRAME_MINUTES: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
}


def _tf_to_minutes(tf: str) -> int:
    return _TIMEFRAME_MINUTES.get(tf.upper(), 60)


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------

def _detect_session(dt_utc: datetime) -> SessionType:
    h = dt_utc.hour
    if 0 <= h < 7:
        return SessionType.ASIAN
    elif 7 <= h < 12:
        return SessionType.LONDON
    elif 12 <= h < 17:
        return SessionType.NY_AM
    elif 17 <= h < 21:
        return SessionType.NY_PM
    return SessionType.OUTSIDE


# ---------------------------------------------------------------------------
# TradingOrchestrator
# ---------------------------------------------------------------------------

class TradingOrchestrator:
    """Unified multi-strategy trading orchestrator.

    Manages the full pipeline: strategy evaluation → signal dedup/cooldown →
    risk checks → order execution → position tracking.
    """

    def __init__(
        self,
        config: OrchestratorConfig,
        paper_trader: Optional[PaperTrader] = None,
        risk_guard: Optional[RiskGuard] = None,
        correlation_tracker: Optional[CorrelationTracker] = None,
        confidence_sizer: Optional[ConfidencePositionSizer] = None,
    ):
        self._config = config
        self._paper_trader = paper_trader
        self._risk_guard = risk_guard
        self._correlation_tracker = correlation_tracker
        self._confidence_sizer = confidence_sizer or ConfidencePositionSizer(
            account_size=config.starting_balance,
        )

        self._strategies: list[_RegisteredStrategy] = []
        self._bar_trackers: dict[tuple[str, str], _BarTracker] = {}  # (symbol, tf) -> tracker
        self._cooldown = _CooldownTracker()
        self._direction_tracker = _SignalDirectionTracker()

        self._lock = threading.RLock()
        self._eval_semaphore = threading.Semaphore(1)

        # Position tracking per strategy_key (strategy+symbol dedup)
        self._position_counts: dict[str, int] = {}  # strategy_key -> open count
        self._strategy_positions: dict[str, str] = {}  # strategy_key -> position_id

        # Stats
        self._signals_generated = 0
        self._signals_rejected = 0
        self._signals_executed = 0
        self._evaluation_errors = 0

        # Callbacks
        self._callbacks: dict[str, list] = {
            "on_signal_generated": [],
            "on_signal_rejected": [],
            "on_signal_executed": [],
            "on_position_closed": [],
        }

        # Wire up PaperTrader callbacks
        if self._paper_trader:
            self._paper_trader.register_callback(
                "on_trade_executed", self._on_paper_trade_executed
            )
            self._paper_trader.register_callback(
                "on_position_closed", self._on_paper_position_closed
            )

    # ------------------------------------------------------------------
    # Strategy registration
    # ------------------------------------------------------------------

    def register_strategy(
        self,
        strategy: ISignalStrategy,
        symbols: list[str],
        timeframes: list[str],
        min_confidence: float = 0.50,
        max_positions_per_symbol: int = 1,
        cooldown_sec: float = 300.0,
    ) -> str:
        """Register a strategy with its target symbols and timeframes.

        Returns a unique registration key (composite: name_symbol_timeframe).
        """
        # Composite key to prevent collisions when the same strategy is
        # registered on multiple symbols or timeframes.
        # When multiple timeframes are given, we pick the first one as the
        # discriminator — each registration call is a separate slot.
        registration_key = f"{strategy.name}_{symbols[0]}_{timeframes[0].upper()}"
        slot_config = StrategySlotConfig(
            symbols=symbols,
            timeframes=timeframes,
            min_confidence=min_confidence,
            max_positions_per_symbol=max_positions_per_symbol,
            cooldown_sec=cooldown_sec,
        )
        reg = _RegisteredStrategy(
            instance=strategy,
            config=slot_config,
            registration_key=registration_key,
        )
        self._strategies.append(reg)

        # Ensure bar trackers exist for all (symbol, tf) pairs
        for symbol in symbols:
            for tf in timeframes:
                key = (symbol, tf.upper())
                if key not in self._bar_trackers:
                    self._bar_trackers[key] = _BarTracker(
                        symbol=symbol,
                        timeframe_minutes=_tf_to_minutes(tf),
                    )

        logger.info(
            "Registered strategy '%s': symbols=%s timeframes=%s min_conf=%.2f",
            strategy.name, symbols, timeframes, min_confidence,
        )
        return reg.registration_key

    def register_strategy_from_config(
        self,
        strategy: ISignalStrategy,
        slot_config: StrategySlotConfig,
    ) -> str:
        """Register a strategy using a StrategySlotConfig."""
        return self.register_strategy(
            strategy=strategy,
            symbols=slot_config.symbols,
            timeframes=slot_config.timeframes,
            min_confidence=slot_config.min_confidence,
            max_positions_per_symbol=slot_config.max_positions_per_symbol,
            cooldown_sec=slot_config.cooldown_sec,
        )

    @property
    def registered_strategies(self) -> list[str]:
        return [s.registration_key for s in self._strategies]

    # ------------------------------------------------------------------
    # Data feeding
    # ------------------------------------------------------------------

    def on_tick(self, symbol: str, bid: float, ask: float, timestamp: Optional[datetime] = None):
        """Feed a tick. Builds bars and triggers evaluation on bar close."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # Update PaperTrader prices for P&L tracking
        if self._paper_trader:
            mid = (bid + ask) / 2.0
            self._paper_trader.update_market_prices(
                {symbol: mid}, bids={symbol: bid}, asks={symbol: ask}
            )

        # Update correlation tracker
        if self._correlation_tracker:
            try:
                self._correlation_tracker.update({symbol: (bid + ask) / 2.0})
            except Exception:
                pass  # correlation tracker is optional

        if not self._config.bar_close_evaluation_only:
            return

        # Feed tick to all bar trackers for this symbol
        for (sym, tf), tracker in self._bar_trackers.items():
            if sym != symbol:
                continue
            closed_bar = tracker.add_tick(bid, ask, timestamp)

            if closed_bar is not None and tracker.needs_evaluation(timestamp):
                tracker.mark_evaluated(
                    tracker._floor_to_period(timestamp)
                )
                self._evaluate_symbol_tf(sym, tf)

    def on_bar_close(self, symbol: str, timeframe: str, bars: list[Bar]):
        """Feed finalized bars externally (e.g. from historical data or another bar builder).

        Triggers evaluation after adding the bar.
        """
        tf = timeframe.upper()
        key = (symbol, tf)

        if key not in self._bar_trackers:
            self._bar_trackers[key] = _BarTracker(
                symbol=symbol,
                timeframe_minutes=_tf_to_minutes(tf),
            )

        # Add all bars
        tracker = self._bar_trackers[key]
        for bar in bars:
            tracker.add_bar(bar)

        # Trigger evaluation
        self._evaluate_symbol_tf(symbol, tf)

    def load_historical_bars(
        self, symbol: str, timeframe: str, bars: list[Bar]
    ):
        """Pre-load historical bars without triggering evaluation."""
        tf = timeframe.upper()
        key = (symbol, tf)

        if key not in self._bar_trackers:
            self._bar_trackers[key] = _BarTracker(
                symbol=symbol,
                timeframe_minutes=_tf_to_minutes(tf),
            )

        tracker = self._bar_trackers[key]
        with tracker.lock:
            tracker.bars.extend(bars)
            if tracker.bars:
                tracker.bars.sort(key=lambda b: b.time)
                if len(tracker.bars) > 5000:
                    tracker.bars = tracker.bars[-3000:]

    # ------------------------------------------------------------------
    # Signal evaluation
    # ------------------------------------------------------------------

    def _evaluate_symbol_tf(self, symbol: str, timeframe: str):
        """Evaluate all strategies registered for this (symbol, timeframe) pair."""
        if not self._eval_semaphore.acquire(blocking=False):
            logger.debug("Evaluation already in progress — skipping")
            return

        try:
            self._do_evaluate_symbol_tf(symbol, timeframe)
        except Exception as exc:
            with self._lock:
                self._evaluation_errors += 1
            logger.error(
                "Strategy evaluation error (total=%d): %s",
                self._evaluation_errors, exc, exc_info=True,
            )
        finally:
            self._eval_semaphore.release()

    def _do_evaluate_symbol_tf(self, symbol: str, timeframe: str):
        tracker = self._bar_trackers.get((symbol, timeframe))
        if tracker is None:
            return

        all_bars = tracker.get_bars()
        if len(all_bars) < self._config.min_bars_for_evaluation:
            return

        # Check session hours
        if not self._is_trading_session():
            return

        session = _detect_session(all_bars[-1].time)
        market_state = MarketState(bars=all_bars, current_session=session)

        for reg in self._strategies:
            if symbol not in reg.config.symbols:
                continue
            if timeframe.upper() not in [t.upper() for t in reg.config.timeframes]:
                continue

            try:
                self._evaluate_single_strategy(reg, symbol, timeframe, market_state)
            except Exception as exc:
                with self._lock:
                    self._evaluation_errors += 1
                logger.error(
                    "Error evaluating %s on %s %s: %s",
                    reg.registration_key, symbol, timeframe, exc,
                )

    def _evaluate_single_strategy(
        self,
        reg: _RegisteredStrategy,
        symbol: str,
        timeframe: str,
        market_state: MarketState,
    ):
        """Evaluate one strategy, handle dedup, cooldown, risk, and execution."""
        strategy = reg.instance
        config = reg.config
        key = reg.registration_key

        signal = strategy.evaluate(market_state)
        current_dir = signal.direction.value if signal else None
        last_dir = self._direction_tracker.get_last_direction(key, symbol)

        # No signal, no position — nothing to do
        if signal is None and last_dir is None:
            return

        # Signal flip or new signal
        if signal is not None and current_dir != last_dir:
            # Confidence filter
            if signal.confidence < config.min_confidence:
                with self._lock:
                    self._signals_rejected += 1
                self._log_rejection(
                    key, symbol, signal.direction.value,
                    signal.confidence,
                    f"confidence {signal.confidence:.2f} < min {config.min_confidence:.2f}",
                )
                return

            # Cooldown check
            if self._cooldown.is_on_cooldown(key, symbol, config.cooldown_sec):
                with self._lock:
                    self._signals_rejected += 1
                self._log_rejection(
                    key, symbol, signal.direction.value,
                    signal.confidence,
                    "cooldown active",
                )
                return

            # Position dedup: check max positions per symbol for this strategy
            if self._has_open_position(key, symbol):
                with self._lock:
                    self._signals_rejected += 1
                self._log_rejection(
                    key, symbol, signal.direction.value,
                    signal.confidence,
                    f"max positions ({config.max_positions_per_symbol}) reached",
                )
                return

            # Correlation filter
            if self._config.use_correlation_filter and self._correlation_tracker:
                if self._is_correlated_rejection(symbol, signal.direction.value):
                    with self._lock:
                        self._signals_rejected += 1
                    self._log_rejection(
                        key, symbol, signal.direction.value,
                        signal.confidence,
                        "correlated exposure too high",
                    )
                    return

            # Close existing position if flipping
            if last_dir is not None:
                self._close_position_for_strategy(key, symbol)

            # Execute new position
            self._execute_signal(key, symbol, signal)

            # Update trackers
            self._direction_tracker.update(key, symbol, current_dir)
            self._cooldown.record_signal(key, symbol)

        elif signal is None and last_dir is not None:
            # Signal disappeared — close position
            self._close_position_for_strategy(key, symbol)
            self._direction_tracker.clear(key, symbol)

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def _execute_signal(
        self,
        strategy_key: str,
        symbol: str,
        signal,
    ):
        """Route a signal through PaperTrader for risk check + execution."""
        if self._paper_trader is None:
            logger.warning("No PaperTrader configured — signal not executed")
            return

        from adapters.ctrader.models import TradeDirection as CTradeDirection, CTraderTradeSignal

        # Convert backtest direction to cTrader direction
        if signal.direction.value == "long":
            c_dir = CTradeDirection.LONG
        elif signal.direction.value == "short":
            c_dir = CTradeDirection.SHORT
        else:
            logger.warning("Unknown direction: %s", signal.direction.value)
            return

        trade_signal = CTraderTradeSignal(
            symbol=symbol,
            direction=c_dir,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            take_profit_3=signal.take_profit_3,
            volume=0.01,  # Will be sized by PaperTrader/RiskGuard
            confidence=signal.confidence,
            rationale=f"[{strategy_key}] {signal.rationale}",
            source=f"strategy:{strategy_key}",
        )

        with self._lock:
            self._signals_generated += 1

        self._trigger_callback("on_signal_generated", {
            "strategy": strategy_key,
            "symbol": symbol,
            "direction": signal.direction.value,
            "confidence": signal.confidence,
        })

        result = self._paper_trader.process_signal(trade_signal)

        if result.success:
            with self._lock:
                self._signals_executed += 1
            logger.info(
                "EXECUTED %s %s %s @ %.5f SL=%.5f TP=%.5f conf=%.2f",
                strategy_key, c_dir.value, symbol,
                signal.entry_price, signal.stop_loss,
                signal.take_profit_1, signal.confidence,
            )
            self._trigger_callback("on_signal_executed", {
                "strategy": strategy_key,
                "symbol": symbol,
                "direction": c_dir.value,
                "confidence": signal.confidence,
                "result": result,
            })
        else:
            with self._lock:
                self._signals_rejected += 1
            self._log_rejection(
                strategy_key, symbol, c_dir.value,
                signal.confidence, result.rejection_reason,
            )

    def _close_position_for_strategy(self, strategy_key: str, symbol: str):
        """Close the specific position opened by this strategy on this symbol."""
        if self._paper_trader is None:
            return

        position_id = self._strategy_positions.get(strategy_key)
        if position_id is None:
            # No tracked position for this strategy — nothing to close
            logger.debug(
                "No tracked position for %s on %s — skipping close",
                strategy_key, symbol,
            )
            return

        # Find the position to get current price for P&L
        positions = self._paper_trader.get_open_positions()
        close_price = None
        for pos in positions:
            if pos.position_id == position_id:
                close_price = pos.current_price or pos.entry_price
                break

        if close_price is None:
            # Position may have been externally closed — clean up and return
            logger.warning(
                "Tracked position %s for %s not found in open positions — cleaning up",
                position_id, strategy_key,
            )
            self._strategy_positions.pop(strategy_key, None)
            self._position_counts[strategy_key] = 0
            return

        self._paper_trader.close_position(
            position_id, close_price,
            reason=f"signal_flip_{strategy_key}",
        )
        logger.info(
            "CLOSED %s %s pos=%s PnL=%.2f",
            strategy_key, symbol, position_id,
            sum(
                p.unrealized_pnl for p in positions
                if p.position_id == position_id
            ),
        )
        self._strategy_positions.pop(strategy_key, None)
        self._position_counts[strategy_key] = 0

    def close_all_positions(self, reason: str = "shutdown"):
        """Close all open positions across all strategies."""
        if self._paper_trader is None:
            return

        positions = self._paper_trader.get_open_positions()
        for pos in positions:
            close_price = pos.current_price or pos.entry_price
            self._paper_trader.close_position(
                pos.position_id, close_price, reason=reason
            )

        # Clear direction trackers
        self._direction_tracker._last_direction.clear()

    # ------------------------------------------------------------------
    # Position queries
    # ------------------------------------------------------------------

    def _has_open_position(self, strategy_key: str, symbol: str) -> bool:
        """Check if THIS strategy already has an open position on this symbol."""
        return self._position_counts.get(strategy_key, 0) > 0

    def get_open_positions(self) -> list:
        """Return all open positions."""
        if self._paper_trader is None:
            return []
        return self._paper_trader.get_open_positions()

    # ------------------------------------------------------------------
    # Correlation check
    # ------------------------------------------------------------------

    def _is_correlated_rejection(self, symbol: str, direction: str) -> bool:
        """Check if opening a position would create excessive correlated exposure."""
        if self._correlation_tracker is None:
            return False

        if not self._correlation_tracker.is_initialized:
            return False  # Not enough data yet — allow

        if self._paper_trader is None:
            return False

        positions = self._paper_trader.get_open_positions()
        if not positions:
            return False

        # Build position list for correlation tracker
        from quant.correlation import Position as CorrPosition
        corr_positions = []
        for pos in positions:
            corr_positions.append(CorrPosition(
                symbol=pos.symbol,
                exposure=pos.volume * 100000,
            ))
        # Add the proposed position
        corr_positions.append(CorrPosition(
            symbol=symbol,
            exposure=0.01 * 100000,  # Will be refined later
        ))

        warnings = self._correlation_tracker.check_exposure(corr_positions)
        return len(warnings) > 0

    # ------------------------------------------------------------------
    # Session check
    # ------------------------------------------------------------------

    def _is_trading_session(self) -> bool:
        """Check if current time is within allowed trading hours."""
        rc = self._config.risk
        if rc.session_start_utc_hour == 0 and rc.session_end_utc_hour == 24:
            return True  # No restriction
        hour = datetime.now(timezone.utc).hour
        return rc.session_start_utc_hour <= hour < rc.session_end_utc_hour

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log_rejection(
        self,
        strategy_key: str,
        symbol: str,
        direction: str,
        confidence: float,
        reason: str,
    ):
        logger.info(
            "REJECTED %s %s %s conf=%.2f reason=%s",
            strategy_key, direction, symbol, confidence, reason,
        )
        self._trigger_callback("on_signal_rejected", {
            "strategy": strategy_key,
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "reason": reason,
        })

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def register_callback(self, event: str, callback):
        """Register a callback for orchestration events.

        Events: on_signal_generated, on_signal_rejected,
                on_signal_executed, on_position_closed
        """
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callback(self, event: str, *args, **kwargs):
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except Exception as e:
                logger.error("Callback error for %s: %s", event, e)

    def _on_paper_trade_executed(self, result):
        """Internal callback from PaperTrader on trade execution.

        Tracks position_id per strategy_key for correct multi-strategy dedup.
        """
        logger.debug("PaperTrader trade executed: %s", result)
        if result.success and result.position:
            # Extract strategy_key from signal source ("strategy:<name>")
            source = getattr(result.signal, 'source', '')
            if source and source.startswith('strategy:'):
                strategy_key = source[len('strategy:'):]
                position_id = result.position.position_id
                self._strategy_positions[strategy_key] = position_id
                self._position_counts[strategy_key] = self._position_counts.get(strategy_key, 0) + 1
                logger.debug(
                    "Tracked position %s for strategy %s (count=%d)",
                    position_id, strategy_key, self._position_counts[strategy_key],
                )

    def _on_paper_position_closed(self, position):
        """Internal callback from PaperTrader on position close.

        Cleans up tracking state when a position is closed externally
        (e.g. stop-loss, take-profit, or manual close).
        """
        position_id = position.position_id
        # Find and clean up any strategy tracking this position
        keys_to_clear = [
            k for k, v in self._strategy_positions.items()
            if v == position_id
        ]
        for key in keys_to_clear:
            self._strategy_positions.pop(key, None)
            self._position_counts[key] = max(0, self._position_counts.get(key, 0) - 1)
            logger.debug(
                "Cleaned up position tracking for %s (position %s closed externally)",
                key, position_id,
            )

        self._trigger_callback("on_position_closed", position)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return orchestrator statistics."""
        with self._lock:
            stats = {
                "signals_generated": self._signals_generated,
                "signals_executed": self._signals_executed,
                "signals_rejected": self._signals_rejected,
                "evaluation_errors": self._evaluation_errors,
                "registered_strategies": self.registered_strategies,
                "bar_trackers": {
                    f"{sym}_{tf}": len(tracker.get_bars())
                    for (sym, tf), tracker in self._bar_trackers.items()
                },
            }

        if self._paper_trader:
            pt_stats = self._paper_trader.get_stats()
            stats["paper_trader"] = {
                "current_balance": pt_stats.current_balance,
                "starting_balance": pt_stats.starting_balance,
                "realized_pnl": pt_stats.realized_pnl,
                "unrealized_pnl": pt_stats.unrealized_pnl,
                "trades_executed": pt_stats.trades_executed,
                "trades_rejected": pt_stats.trades_rejected,
                "signals_blocked_by_risk": pt_stats.signals_blocked_by_risk,
                "open_positions": len(self._paper_trader.get_open_positions()),
            }

        if self._risk_guard:
            stats["risk_guard"] = self._risk_guard.get_stats()

        return stats

    def reset(self):
        """Reset all internal state."""
        with self._lock:
            self._signals_generated = 0
            self._signals_rejected = 0
            self._signals_executed = 0
            self._evaluation_errors = 0
            self._position_counts.clear()
            self._strategy_positions.clear()
            self._cooldown._last_signal_time.clear()
            self._direction_tracker._last_direction.clear()

        if self._paper_trader:
            self._paper_trader.reset()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def paper_trader(self) -> Optional[PaperTrader]:
        return self._paper_trader

    @property
    def risk_guard(self) -> Optional[RiskGuard]:
        return self._risk_guard

    @property
    def config(self) -> OrchestratorConfig:
        return self._config


# ---------------------------------------------------------------------------
# MVP Portfolio builder
# ---------------------------------------------------------------------------

def build_mvp_orchestrator(
    starting_balance: float = 10_000.0,
    paper_trader: Optional[PaperTrader] = None,
    risk_guard: Optional[RiskGuard] = None,
    correlation_tracker: Optional[CorrelationTracker] = None,
    trade_store=None,
) -> TradingOrchestrator:
    """Build the orchestrator with the Blend One MVP portfolio configuration.

    Blend One Portfolio (Quality Anchor):
      1. SRMR+ XAUUSD M5 (Optuna Optimized) — 0.43 trades/day, Sharpe 32.65
      2. SRMR+ XAUUSD H1 (Original)            — 0.9 trades/day,  Sharpe 15.2
      3. SRMR+ XAUUSD H4 (Default)              — 0.2 trades/day,  Sharpe 33.1
      4. Session Range MR XAUUSD H1             — 0.8 trades/day,  Sharpe 21.0
      5. TTC XAUUSD M15                         — 0.2 trades/day,  Sharpe 1.38

    Risk: 20% max DD, 5% daily loss, max 5 concurrent positions.

    Args:
        starting_balance: Starting account balance.
        paper_trader: Optional PaperTrader instance.
        risk_guard: Optional RiskGuard instance.
        correlation_tracker: Optional CorrelationTracker.
        trade_store: Optional TradeStore for persistence. If provided,
            trade open/close callbacks are wired automatically.
    """
    from adapters.ctrader.risk_guard import FTMOConfig, RiskGuard as RG

    config = OrchestratorConfig(
        starting_balance=starting_balance,
        risk=RiskConfig(
            max_drawdown_pct=0.10,  # FTMO 10% max drawdown
            daily_loss_limit_pct=0.05,
            max_concurrent_positions=5,
            max_trades_per_day=10,
            min_risk_reward=0.0,  # strategies manage exits via signal flips
        ),
    )

    if risk_guard is None:
        ftmo = FTMOConfig(
            daily_loss_limit_pct=0.05,
            total_drawdown_limit_pct=0.10,  # FTMO 10% total drawdown
            min_risk_reward=0.0,
            max_trades_per_day=10,
            max_positions=5,
        )
        risk_guard = RG(ftmo, starting_balance=starting_balance)

    if paper_trader is None:
        from adapters.ctrader.paper_trader import PaperTrader
        paper_trader = PaperTrader(
            ftmo_config=risk_guard._config,
            starting_balance=starting_balance,
        )

    orch = TradingOrchestrator(
        config=config,
        paper_trader=paper_trader,
        risk_guard=risk_guard,
        correlation_tracker=correlation_tracker,
    )

    # ----------------------------------------------------------------
    # 1. SRMR+ XAUUSD M5 (Optuna Optimized — BEST RESULT)
    #    0.43 trades/day, Sharpe 32.65, 5/5 WF pass
    # ----------------------------------------------------------------
    try:
        from strategies.srmr_plus import SRMRPlusStrategy, SRMRPlusConfig
        srmr_m5_config = SRMRPlusConfig(
            atr_period=15,
            rsi_period=13,
            rsi_long_level=34.0,
            rsi_short_level=73.0,
            adx_max_threshold=22.0,
            session_range_min_pips=23.0,
            entry_near_extreme_pips=18.0,
            hard_cap_sl_pips=25.0,
            tp1_rr=0.9,
            tp2_rr=1.5,
            ema_trend_period=32,
        )
        srmr_m5 = SRMRPlusStrategy(config=srmr_m5_config)
        orch.register_strategy(
            srmr_m5, symbols=["XAUUSD"], timeframes=["M5"],
            min_confidence=0.55, cooldown_sec=60,
        )
    except ImportError:
        logger.warning("SRMRPlusStrategy not available — skipping SRMR M5")

    # ----------------------------------------------------------------
    # 2. SRMR+ XAUUSD H1 (ORIGINAL config — NOT frequency-optimized)
    #    0.9 trades/day, Sharpe 15.2, 5/5 WF pass
    # ----------------------------------------------------------------
    try:
        from strategies.srmr_plus import SRMRPlusStrategy
        srmr_h1 = SRMRPlusStrategy()  # default params
        orch.register_strategy(
            srmr_h1, symbols=["XAUUSD"], timeframes=["H1"],
            min_confidence=0.55, cooldown_sec=300,
        )
    except ImportError:
        logger.warning("SRMRPlusStrategy not available — skipping SRMR H1")

    # ----------------------------------------------------------------
    # 3. SRMR+ XAUUSD H4 (Default)
    #    0.2 trades/day, Sharpe 33.1, 5/5 WF pass
    # ----------------------------------------------------------------
    try:
        from strategies.srmr_plus import SRMRPlusStrategy
        srmr_h4 = SRMRPlusStrategy()  # default params
        orch.register_strategy(
            srmr_h4, symbols=["XAUUSD"], timeframes=["H4"],
            min_confidence=0.55, cooldown_sec=1800,
        )
    except ImportError:
        logger.warning("SRMRPlusStrategy not available — skipping SRMR H4")

    # ----------------------------------------------------------------
    # 4. Session Range MR XAUUSD H1
    #    0.8 trades/day, Sharpe 21.0
    # ----------------------------------------------------------------
    try:
        from strategies.session_range_mean_reversion import SessionRangeMeanReversionStrategy
        session_mr = SessionRangeMeanReversionStrategy()
        orch.register_strategy(
            session_mr, symbols=["XAUUSD"], timeframes=["H1"],
            min_confidence=0.60, cooldown_sec=300,
        )
    except ImportError:
        logger.warning("SessionRangeMeanReversionStrategy not available — skipping")

    # ----------------------------------------------------------------
    # 5. TTC XAUUSD M15 (lower confidence threshold)
    #    0.2 trades/day, Sharpe 1.38
    # ----------------------------------------------------------------
    try:
        from backtest.strategies.tts_strategy import TTSStrategy
        ttc = TTSStrategy(
            symbol="XAUUSD",
            min_confidence=0.35,
            min_quality_score=0.35,
            timeframe="M15",
        )
        orch.register_strategy(
            ttc, symbols=["XAUUSD"], timeframes=["M15"],
            min_confidence=0.35, cooldown_sec=300,
        )
    except (ImportError, Exception) as e:
        logger.warning("TTC strategy not available: %s — skipping", e)

    # ----------------------------------------------------------------
    # Wire TradeStore callbacks if provided
    # ----------------------------------------------------------------
    if trade_store is not None:
        _wire_trade_store(orch, trade_store)

    logger.info(
        "Blend One MVP orchestrator built: %d strategies registered, balance=$%.2f",
        len(orch.registered_strategies), starting_balance,
    )

    return orch


def _wire_trade_store(
    orch: TradingOrchestrator,
    trade_store,
):
    """Wire TradeStore callbacks into the orchestrator for trade persistence.

    Records every trade open/close to SQLite, equity snapshots on schedule,
    and daily summaries at end of trading day.
    """
    def _on_signal_executed(event_data):
        result = event_data.get("result")
        if result and result.success and result.position:
            trade_store.record_open({
                "trade_id": result.position.position_id,
                "strategy_name": event_data.get("strategy", ""),
                "symbol": event_data.get("symbol", ""),
                "direction": event_data.get("direction", ""),
                "entry_price": result.position.entry_price,
                "lot_size": result.position.volume if hasattr(result.position, 'volume') else 0.01,
                "stop_loss": result.position.stop_loss if hasattr(result.position, 'stop_loss') else None,
                "take_profit": result.position.take_profit if hasattr(result.position, 'take_profit') else None,
                "confidence": event_data.get("confidence", 0),
                "source": f"strategy:{event_data.get('strategy', '')}",
                "metadata": {"rationale": str(event_data.get("result", ""))},
            })

    def _on_position_closed(position):
        try:
            trade_store.record_close(
                position.position_id,
                position.current_price or position.entry_price,
                "signal_flip" if hasattr(position, 'close_reason') else "closed",
            )
        except ValueError:
            pass  # trade not found in store (e.g. opened before store init)

    orch.register_callback("on_signal_executed", _on_signal_executed)
    orch.register_callback("on_position_closed", _on_position_closed)

    logger.info("TradeStore callbacks wired into orchestrator")
