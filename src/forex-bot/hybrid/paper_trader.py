from __future__ import annotations

import logging
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from threading import RLock

from hybrid.engine import HybridEngine, HybridEngineConfig
from hybrid.risk_manager import RiskManager
from hybrid.signal import HumanSignal, SignalType
from hybrid.trade_rules import (
    RuleAction,
    RuleResult,
    TradeRulesConfig,
    TradeRulesEngine,
)


logger = logging.getLogger(__name__)


class CloseReason(StrEnum):
    MANUAL = "manual"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    PARTIAL_CLOSE = "partial_close"
    CIRCUIT_BREAKER = "circuit_breaker"
    SIGNAL_FLIP = "signal_flip"
    FORCE_CLOSE = "force_close"


class SlippageModel:
    def __init__(self, base_pips: float = 0.1, random_pips: float = 0.2) -> None:
        self.base_pips = base_pips
        self.random_pips = random_pips

    def apply(self, price: float, is_long: bool) -> tuple[float, float]:
        slippage_pips = self.base_pips + random.random() * self.random_pips
        pip_value = 0.0001
        slippage_amount = slippage_pips * pip_value
        if is_long:
            fill_price = price + slippage_amount
        else:
            fill_price = price - slippage_amount
        return fill_price, slippage_amount


@dataclass
class PaperPosition:
    position_id: str
    pair: str
    direction: str
    lot_size: float
    entry_price: float
    current_price: float
    stop_loss: float | None
    take_profit: float | None
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None
    closed_reason: CloseReason | None = None
    is_open: bool = True
    comment: str = ""

    def entry_pips_distance(self, current_price: float) -> float:
        if self.direction == "long":
            return (current_price - self.entry_price) / 0.0001
        else:
            return (self.entry_price - current_price) / 0.0001


@dataclass
class PaperTradeResult:
    success: bool
    signal: HumanSignal
    position_id: str = ""
    lot_size: float = 0.0
    fill_price: float = 0.0
    slippage_applied: float = 0.0
    rejection_reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PaperCloseResult:
    success: bool
    position_id: str
    exit_price: float = 0.0
    pnl: float = 0.0
    reason: CloseReason = CloseReason.MANUAL
    error: str = ""


@dataclass
class PaperTradingStats:
    total_signals_processed: int = 0
    signals_accepted: int = 0
    signals_rejected: int = 0
    trades_executed: int = 0
    trades_closed: int = 0
    wins: int = 0
    losses: int = 0
    starting_balance: float = 100_000.0
    current_balance: float = 100_000.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


class HybridPaperTrader:
    def __init__(
        self,
        starting_balance: float = 100_000.0,
        trade_rules_config: TradeRulesConfig | None = None,
        slippage_base_pips: float = 0.1,
        slippage_random_pips: float = 0.2,
        use_session_filter: bool = True,
    ) -> None:
        self._starting_balance = starting_balance
        self._current_balance = starting_balance
        self._trade_rules_config = trade_rules_config or TradeRulesConfig.ftmo()
        self._slippage = SlippageModel(slippage_base_pips, slippage_random_pips)

        self._engine = HybridEngine(
            risk_manager=RiskManager(starting_balance=starting_balance),
            starting_balance=starting_balance,
            config=HybridEngineConfig(session_filter_enabled=use_session_filter),
        )

        self._rules_engine = TradeRulesEngine(
            config=self._trade_rules_config,
            starting_balance=starting_balance,
        )

        self._lock = RLock()
        self._positions: dict[str, PaperPosition] = {}
        self._position_count = 0
        self._order_count = 0
        self._trade_history: deque[PaperPosition] = deque(maxlen=10000)
        self._stats = PaperTradingStats(
            starting_balance=starting_balance, current_balance=starting_balance
        )
        self._session_filter_enabled = use_session_filter

    @property
    def balance(self) -> float:
        return self._current_balance

    @property
    def engine(self) -> HybridEngine:
        return self._engine

    @property
    def rules_engine(self) -> TradeRulesEngine:
        return self._rules_engine

    def process_signal(
        self, signal: HumanSignal, spread: float = 0.0
    ) -> PaperTradeResult:
        with self._lock:
            self._stats.total_signals_processed += 1

            if signal.signal_type == SignalType.CLOSE:
                return PaperTradeResult(
                    success=True,
                    signal=signal,
                    rejection_reason="Close signals handled separately",
                )

            engine_result = self._engine.submit_signal(signal)
            if not engine_result.success:
                self._stats.signals_rejected += 1
                return PaperTradeResult(
                    success=False,
                    signal=signal,
                    rejection_reason=engine_result.error,
                )

            rule_result = self._rules_engine.check_new_signal(signal)
            if rule_result.action == RuleAction.REJECT:
                self._stats.signals_rejected += 1
                return PaperTradeResult(
                    success=False,
                    signal=signal,
                    rejection_reason=rule_result.reason,
                )

            self._order_count += 1
            position_id = f"hybrid-pt-{self._order_count:06d}"
            lot_size = engine_result.lot_size

            fill_price, slippage = self._slippage.apply(
                signal.entry_price, signal.signal_type == SignalType.BUY
            )

            if spread > 0:
                if signal.signal_type == SignalType.BUY:
                    fill_price += spread / 2
                else:
                    fill_price -= spread / 2

            self._position_count += 1
            position = PaperPosition(
                position_id=position_id,
                pair=signal.pair,
                direction=signal.to_direction_str(),
                lot_size=lot_size,
                entry_price=fill_price,
                current_price=fill_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                opened_at=signal.timestamp,
                comment="",
            )

            self._positions[position_id] = position

            self._rules_engine.register_position(
                position_id=position_id,
                entry_price=fill_price,
                stop_loss=signal.stop_loss or fill_price,
                direction=position.direction,
                lot_size=lot_size,
            )

            self._stats.signals_accepted += 1
            self._stats.trades_executed += 1

            logger.info(
                f"[PAPER] Opened: {position.direction} {lot_size} {signal.pair} "
                f"@ {fill_price:.5f} SL={signal.stop_loss} TP={signal.take_profit} "
                f"(slippage={slippage:.5f})"
            )

            return PaperTradeResult(
                success=True,
                signal=signal,
                position_id=position_id,
                lot_size=lot_size,
                fill_price=fill_price,
                slippage_applied=slippage,
            )

    def update_market_prices(
        self, prices: dict[str, float], now: datetime | None = None
    ) -> dict[str, list[RuleResult]]:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            actions: dict[str, list[RuleResult]] = {}

            for position_id, position in list(self._positions.items()):
                if not position.is_open:
                    continue

                pair = position.pair
                if pair not in prices:
                    continue

                current_price = prices[pair]
                position.current_price = current_price

                self._update_unrealized_pnl(position, current_price)

                rule_result = self._rules_engine.on_tick(
                    position_id, current_price, now
                )

                if rule_result.action == RuleAction.NO_ACTION:
                    continue

                if position_id not in actions:
                    actions[position_id] = []
                actions[position_id].append(rule_result)

                self._apply_rule_action(position, rule_result, current_price)

            self._current_balance = (
                self._starting_balance
                + self._stats.realized_pnl
                + self._stats.unrealized_pnl
            )
            self._stats.current_balance = self._current_balance
            return actions

    def _update_unrealized_pnl(
        self, position: PaperPosition, current_price: float
    ) -> None:
        if position.direction == "long":
            pnl = (current_price - position.entry_price) * position.lot_size * 100_000
        else:
            pnl = (position.entry_price - current_price) * position.lot_size * 100_000
        position.unrealized_pnl = pnl

        total_unrealized = sum(
            p.unrealized_pnl for p in self._positions.values() if p.is_open
        )
        self._stats.unrealized_pnl = total_unrealized

    def _apply_rule_action(
        self, position: PaperPosition, result: RuleResult, current_price: float
    ) -> None:
        action = result.action

        if action == RuleAction.MODIFY_SL and result.new_sl is not None:
            position.stop_loss = result.new_sl
            logger.info(
                f"[PAPER] {position.position_id}: SL modified to {result.new_sl:.5f} "
                f"({result.reason})"
            )

        elif action == RuleAction.PARTIAL_CLOSE:
            self._handle_partial_close(position, result, current_price)

        elif action == RuleAction.CLOSE_ALL:
            reason = self._determine_close_reason(result.reason)
            self._close_position_internal(position, current_price, reason)

    def _determine_close_reason(self, reason: str) -> CloseReason:
        reason_lower = reason.lower()
        if "stop loss" in reason_lower or "sl hit" in reason_lower:
            return CloseReason.STOP_LOSS
        if "trailing" in reason_lower or "trail" in reason_lower:
            return CloseReason.TRAILING_STOP
        return CloseReason.SIGNAL_FLIP

    def _handle_partial_close(
        self, position: PaperPosition, result: RuleResult, current_price: float
    ) -> None:
        close_pct = result.close_pct
        closed_lots = position.lot_size * close_pct
        remaining_lots = position.lot_size * (1 - close_pct)

        if position.direction == "long":
            pnl = (current_price - position.entry_price) * closed_lots * 100_000
        else:
            pnl = (position.entry_price - current_price) * closed_lots * 100_000

        position.realized_pnl += pnl
        position.lot_size = remaining_lots

        self._stats.realized_pnl += pnl
        self._current_balance += pnl

        if result.new_sl is not None:
            position.stop_loss = result.new_sl

        self._rules_engine.record_pnl(pnl)

        logger.info(
            f"[PAPER] {position.position_id}: Partial close {close_pct * 100:.0f}% "
            f"({closed_lots:.2f} lots) @ {current_price:.5f}, PnL={pnl:.2f} "
            f"({result.reason}), remaining={remaining_lots:.2f} lots"
        )

    def close_position(
        self,
        position_id: str,
        exit_price: float | None = None,
        reason: CloseReason = CloseReason.MANUAL,
    ) -> PaperCloseResult:
        with self._lock:
            position = self._positions.get(position_id)
            if position is None:
                return PaperCloseResult(
                    success=False,
                    position_id=position_id,
                    error=f"Position {position_id} not found",
                )

            if not position.is_open:
                return PaperCloseResult(
                    success=False,
                    position_id=position_id,
                    error=f"Position {position_id} is already closed",
                )

            if exit_price is None:
                exit_price = position.current_price

            self._close_position_internal(position, exit_price, reason)

            return PaperCloseResult(
                success=True,
                position_id=position_id,
                exit_price=exit_price,
                pnl=position.realized_pnl,
                reason=reason,
            )

    def _close_position_internal(
        self, position: PaperPosition, exit_price: float, reason: CloseReason
    ) -> None:
        if position.direction == "long":
            pnl = (exit_price - position.entry_price) * position.lot_size * 100_000
        else:
            pnl = (position.entry_price - exit_price) * position.lot_size * 100_000

        position.realized_pnl = pnl
        position.unrealized_pnl = 0.0
        position.closed_at = datetime.now(timezone.utc)
        position.closed_reason = reason
        position.is_open = False

        self._stats.realized_pnl += pnl
        self._stats.trades_closed += 1

        if pnl > 0:
            self._stats.wins += 1
        else:
            self._stats.losses += 1

        self._position_count -= 1

        self._engine.risk_manager.close_position()
        self._rules_engine.record_pnl(pnl)
        self._rules_engine.remove_position(position.position_id)

        self._trade_history.append(position)

        self._current_balance += pnl
        self._stats.current_balance = self._current_balance

        total_unrealized = sum(
            p.unrealized_pnl for p in self._positions.values() if p.is_open
        )
        self._stats.unrealized_pnl = total_unrealized

        logger.info(
            f"[PAPER] Closed: {position.pair} {position.direction} "
            f"@ {exit_price:.5f}, PnL={pnl:.2f} ({reason.value}), "
            f"Balance=${self._current_balance:.2f}"
        )

    def close_all_positions(
        self,
        exit_prices: dict[str, float] | None = None,
        reason: CloseReason = CloseReason.FORCE_CLOSE,
    ) -> list[PaperCloseResult]:
        results = []
        with self._lock:
            for position in list(self._positions.values()):
                if not position.is_open:
                    continue
                exit_price = None
                if exit_prices and position.pair in exit_prices:
                    exit_price = exit_prices[position.pair]
                result = self.close_position(position.position_id, exit_price, reason)
                results.append(result)
        return results

    def get_open_positions(self) -> list[PaperPosition]:
        with self._lock:
            return [p for p in self._positions.values() if p.is_open]

    def get_position(self, position_id: str) -> PaperPosition | None:
        return self._positions.get(position_id)

    def get_trade_history(self) -> list[PaperPosition]:
        return list(self._trade_history)

    def get_stats(self) -> PaperTradingStats:
        with self._lock:
            return PaperTradingStats(
                total_signals_processed=self._stats.total_signals_processed,
                signals_accepted=self._stats.signals_accepted,
                signals_rejected=self._stats.signals_rejected,
                trades_executed=self._stats.trades_executed,
                trades_closed=self._stats.trades_closed,
                wins=self._stats.wins,
                losses=self._stats.losses,
                starting_balance=self._starting_balance,
                current_balance=self._current_balance,
                realized_pnl=self._stats.realized_pnl,
                unrealized_pnl=self._stats.unrealized_pnl,
            )

    def get_rules_stats(self) -> dict:
        return self._rules_engine.get_stats()

    def reset(self) -> None:
        with self._lock:
            self._current_balance = self._starting_balance
            self._stats = PaperTradingStats(
                starting_balance=self._starting_balance,
                current_balance=self._starting_balance,
            )
            self._positions.clear()
            self._position_count = 0
            self._order_count = 0
            self._trade_history.clear()
            self._rules_engine.reset_circuit_breaker()
            self._rules_engine.reset_daily(self._get_utc_now())
            logger.info("[PAPER] PaperTrader reset to initial state")

    def reset_daily(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self._engine.risk_manager.reset_daily_tracking()
            self._rules_engine.reset_daily(now)
            logger.info("[PAPER] Daily tracking reset")

    def _get_utc_now(self) -> datetime:
        return datetime.now(timezone.utc)
