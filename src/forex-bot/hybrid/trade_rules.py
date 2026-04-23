from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum

from hybrid.signal import HumanSignal, SignalType

logger = logging.getLogger(__name__)


class RuleAction(StrEnum):
    ALLOW = "allow"
    REJECT = "reject"
    MODIFY_SL = "modify_sl"
    PARTIAL_CLOSE = "partial_close"
    CLOSE_ALL = "close_all"
    NO_ACTION = "no_action"


class RejectReason(StrEnum):
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    WEEKLY_DRAWDOWN_LIMIT = "weekly_drawdown_limit"
    MAX_POSITIONS = "max_positions"
    NO_STOP_LOSS = "no_stop_loss"
    MIN_RISK_REWARD = "min_risk_reward"


@dataclass
class RuleResult:
    action: RuleAction
    reason: str = ""
    new_sl: float | None = None
    close_pct: float = 0.0
    reject_reason: RejectReason | None = None


@dataclass
class ProgressiveStopLossConfig:
    breakeven_trigger_pips: float = 20.0
    breakeven_offset_pips: float = 2.0
    trail_start_pips: float = 40.0
    trail_step_pips: float = 10.0
    enabled: bool = True


@dataclass
class PartialProfitConfig:
    enabled: bool = True
    tiers: list[tuple[float, float, bool]] = field(
        default_factory=lambda: [
            (0.50, 1.0, True),
            (0.75, 2.0, False),
        ]
    )


@dataclass
class DailyLossConfig:
    enabled: bool = True
    max_loss_pct: float = 0.045
    reset_hour_utc: int = 0
    reset_minute_utc: int = 0


@dataclass
class WeeklyDrawdownConfig:
    enabled: bool = True
    max_drawdown_pct: float = 0.09
    rolling_days: int = 7


@dataclass
class PositionLimitConfig:
    enabled: bool = True
    max_positions: int = 3


@dataclass
class TradeRulesConfig:
    progressive_sl: ProgressiveStopLossConfig = field(
        default_factory=ProgressiveStopLossConfig
    )
    partial_profit: PartialProfitConfig = field(default_factory=PartialProfitConfig)
    daily_loss: DailyLossConfig = field(default_factory=DailyLossConfig)
    weekly_drawdown: WeeklyDrawdownConfig = field(default_factory=WeeklyDrawdownConfig)
    position_limit: PositionLimitConfig = field(default_factory=PositionLimitConfig)
    min_risk_reward: float = 1.5

    @classmethod
    def ftmo(cls) -> TradeRulesConfig:
        return cls(
            progressive_sl=ProgressiveStopLossConfig(
                breakeven_trigger_pips=20.0,
                breakeven_offset_pips=2.0,
                trail_start_pips=40.0,
                trail_step_pips=10.0,
            ),
            partial_profit=PartialProfitConfig(
                tiers=[(0.50, 1.0, True), (0.75, 2.0, False)],
            ),
            daily_loss=DailyLossConfig(max_loss_pct=0.045),
            weekly_drawdown=WeeklyDrawdownConfig(max_drawdown_pct=0.09),
            position_limit=PositionLimitConfig(max_positions=3),
            min_risk_reward=1.5,
        )


@dataclass
class PnlRecord:
    timestamp: datetime
    pnl: float


@dataclass
class _DailyBucket:
    date: date
    start_balance: float
    realized_pnl: float = 0.0


@dataclass
class _PositionState:
    entry_price: float
    stop_loss: float
    original_sl: float
    direction: str
    lot_size: float
    highest_price: float = 0.0
    lowest_price: float = 0.0
    sl_moved_to_breakeven: bool = False
    trail_active: bool = False
    tiers_hit: int = 0
    cumulative_closed_pct: float = 0.0
    remaining_pct: float = 1.0


class TradeRulesEngine:
    def __init__(
        self,
        config: TradeRulesConfig | None = None,
        starting_balance: float = 100_000.0,
    ) -> None:
        self._config = config or TradeRulesConfig.ftmo()
        self._starting_balance = starting_balance
        self._current_balance = starting_balance
        self._peak_balance = starting_balance
        self._daily_bucket: _DailyBucket | None = None
        self._pnl_history: deque[PnlRecord] = deque()
        self._positions: dict[str, _PositionState] = {}
        self._daily_trade_count: int = 0
        self._circuit_breaker_active: bool = False
        self._circuit_breaker_reason: str = ""
        self._circuit_breaker_type: RejectReason | None = None

    @property
    def config(self) -> TradeRulesConfig:
        return self._config

    @property
    def current_balance(self) -> float:
        return self._current_balance

    @property
    def open_position_count(self) -> int:
        return len(self._positions)

    @property
    def is_circuit_breaker_active(self) -> bool:
        return self._circuit_breaker_active

    def reset_daily(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        today = now.date()
        if self._daily_bucket is not None and self._daily_bucket.date != today:
            self._daily_bucket = _DailyBucket(
                date=today,
                start_balance=self._current_balance,
            )
            self._daily_trade_count = 0
            if self._circuit_breaker_active and self._circuit_breaker_reason.startswith(
                "Daily"
            ):
                self._circuit_breaker_active = False
                self._circuit_breaker_reason = ""

    def _ensure_daily_bucket(self, now: datetime) -> _DailyBucket:
        today = now.date()
        if self._daily_bucket is None or self._daily_bucket.date != today:
            self._daily_bucket = _DailyBucket(
                date=today,
                start_balance=self._current_balance,
            )
            self._daily_trade_count = 0
        return self._daily_bucket

    def check_new_signal(
        self, signal: HumanSignal, now: datetime | None = None
    ) -> RuleResult:
        now = now or datetime.now(timezone.utc)

        if signal.signal_type == SignalType.CLOSE:
            return RuleResult(action=RuleAction.ALLOW, reason="Close always allowed")

        self.reset_daily(now)

        cutoff = now - timedelta(days=self._config.weekly_drawdown.rolling_days)
        while self._pnl_history and self._pnl_history[0].timestamp < cutoff:
            self._pnl_history.popleft()

        if self._circuit_breaker_active:
            if self._circuit_breaker_type == RejectReason.DAILY_LOSS_LIMIT:
                bucket = self._ensure_daily_bucket(now)
                if bucket.start_balance > 0:
                    daily_loss_pct = bucket.realized_pnl / bucket.start_balance
                    if daily_loss_pct > -self._config.daily_loss.max_loss_pct:
                        self._circuit_breaker_active = False
                        self._circuit_breaker_reason = ""
                        self._circuit_breaker_type = None
            if (
                self._circuit_breaker_active
                and self._circuit_breaker_type == RejectReason.WEEKLY_DRAWDOWN_LIMIT
            ):
                weekly_loss_pct = self._calc_weekly_drawdown(now)
                if weekly_loss_pct > -self._config.weekly_drawdown.max_drawdown_pct:
                    self._circuit_breaker_active = False
                    self._circuit_breaker_reason = ""
                    self._circuit_breaker_type = None

        if self._circuit_breaker_active:
            return RuleResult(
                action=RuleAction.REJECT,
                reason=self._circuit_breaker_reason,
                reject_reason=self._circuit_breaker_type
                or RejectReason.DAILY_LOSS_LIMIT,
            )

        if self._config.daily_loss.enabled:
            bucket = self._ensure_daily_bucket(now)
            daily_loss_pct = (
                bucket.realized_pnl / bucket.start_balance
                if bucket.start_balance > 0
                else 0.0
            )
            if daily_loss_pct <= -self._config.daily_loss.max_loss_pct:
                self._circuit_breaker_active = True
                self._circuit_breaker_type = RejectReason.DAILY_LOSS_LIMIT
                self._circuit_breaker_reason = (
                    f"Daily loss {daily_loss_pct * 100:.2f}% >= "
                    f"-{self._config.daily_loss.max_loss_pct * 100:.1f}%"
                )
                logger.critical(self._circuit_breaker_reason)
                return RuleResult(
                    action=RuleAction.REJECT,
                    reason=self._circuit_breaker_reason,
                    reject_reason=RejectReason.DAILY_LOSS_LIMIT,
                )

        if self._config.weekly_drawdown.enabled:
            weekly_loss_pct = self._calc_weekly_drawdown(now)
            if weekly_loss_pct <= -self._config.weekly_drawdown.max_drawdown_pct:
                self._circuit_breaker_active = True
                self._circuit_breaker_type = RejectReason.WEEKLY_DRAWDOWN_LIMIT
                self._circuit_breaker_reason = (
                    f"Weekly drawdown {weekly_loss_pct * 100:.2f}% >= "
                    f"-{self._config.weekly_drawdown.max_drawdown_pct * 100:.1f}%"
                )
                logger.critical(self._circuit_breaker_reason)
                return RuleResult(
                    action=RuleAction.REJECT,
                    reason=self._circuit_breaker_reason,
                    reject_reason=RejectReason.WEEKLY_DRAWDOWN_LIMIT,
                )

        if self._config.position_limit.enabled:
            if self.open_position_count >= self._config.position_limit.max_positions:
                return RuleResult(
                    action=RuleAction.REJECT,
                    reason=(
                        f"Max positions reached: {self.open_position_count}/"
                        f"{self._config.position_limit.max_positions}"
                    ),
                    reject_reason=RejectReason.MAX_POSITIONS,
                )

        if not signal.has_stop_loss and signal.signal_type != SignalType.CLOSE:
            return RuleResult(
                action=RuleAction.REJECT,
                reason="Signal must include a stop loss",
                reject_reason=RejectReason.NO_STOP_LOSS,
            )

        if signal.has_stop_loss and signal.has_take_profit:
            rr = self._calc_risk_reward(signal)
            if rr < self._config.min_risk_reward:
                return RuleResult(
                    action=RuleAction.REJECT,
                    reason=(
                        f"Risk:Reward {rr:.2f} below minimum "
                        f"{self._config.min_risk_reward}"
                    ),
                    reject_reason=RejectReason.MIN_RISK_REWARD,
                )

        return RuleResult(action=RuleAction.ALLOW, reason="Signal passes all rules")

    def register_position(
        self,
        position_id: str,
        entry_price: float,
        stop_loss: float,
        direction: str,
        lot_size: float,
    ) -> None:
        self._positions[position_id] = _PositionState(
            entry_price=entry_price,
            stop_loss=stop_loss,
            original_sl=stop_loss,
            direction=direction,
            lot_size=lot_size,
            highest_price=entry_price,
            lowest_price=entry_price,
        )

    def remove_position(self, position_id: str) -> None:
        self._positions.pop(position_id, None)

    def on_tick(
        self,
        position_id: str,
        current_price: float,
        now: datetime | None = None,
    ) -> RuleResult:
        now = now or datetime.now(timezone.utc)
        state = self._positions.get(position_id)
        if state is None:
            return RuleResult(action=RuleAction.NO_ACTION)

        if state.direction == "long":
            state.highest_price = max(state.highest_price, current_price)
        else:
            state.lowest_price = min(state.lowest_price, current_price)

        sl_result = self._check_progressive_sl(state, current_price)
        if sl_result.action != RuleAction.NO_ACTION:
            return sl_result

        partial_result = self._check_partial_profit(state, current_price)
        if partial_result.action != RuleAction.NO_ACTION:
            return partial_result

        return RuleResult(action=RuleAction.NO_ACTION)

    def record_pnl(self, pnl: float, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._current_balance += pnl
        if self._current_balance > self._peak_balance:
            self._peak_balance = self._current_balance

        bucket = self._ensure_daily_bucket(now)
        bucket.realized_pnl += pnl
        self._daily_trade_count += 1

        self._pnl_history.append(PnlRecord(timestamp=now, pnl=pnl))
        cutoff = now - timedelta(days=self._config.weekly_drawdown.rolling_days)
        while self._pnl_history and self._pnl_history[0].timestamp < cutoff:
            self._pnl_history.popleft()

        if self._config.daily_loss.enabled and bucket.start_balance > 0:
            daily_loss_pct = bucket.realized_pnl / bucket.start_balance
            if daily_loss_pct <= -self._config.daily_loss.max_loss_pct:
                self._circuit_breaker_active = True
                self._circuit_breaker_type = RejectReason.DAILY_LOSS_LIMIT
                self._circuit_breaker_reason = (
                    f"Daily loss {daily_loss_pct * 100:.2f}% >= "
                    f"-{self._config.daily_loss.max_loss_pct * 100:.1f}%"
                )
                logger.critical(self._circuit_breaker_reason)

        if self._config.weekly_drawdown.enabled and self._peak_balance > 0:
            weekly_loss_pct = self._calc_weekly_drawdown(now)
            if weekly_loss_pct <= -self._config.weekly_drawdown.max_drawdown_pct:
                self._circuit_breaker_active = True
                self._circuit_breaker_type = RejectReason.WEEKLY_DRAWDOWN_LIMIT
                self._circuit_breaker_reason = (
                    f"Weekly drawdown {weekly_loss_pct * 100:.2f}% >= "
                    f"-{self._config.weekly_drawdown.max_drawdown_pct * 100:.1f}%"
                )
                logger.critical(self._circuit_breaker_reason)

    def reset_circuit_breaker(self) -> None:
        self._circuit_breaker_active = False
        self._circuit_breaker_reason = ""
        self._circuit_breaker_type = None
        logger.info("Circuit breaker reset")

    def get_stats(self) -> dict:
        daily_loss_pct = 0.0
        if self._daily_bucket and self._daily_bucket.start_balance > 0:
            daily_loss_pct = (
                self._daily_bucket.realized_pnl / self._daily_bucket.start_balance
            )
        drawdown_pct = 0.0
        if self._peak_balance > 0:
            drawdown_pct = (
                self._peak_balance - self._current_balance
            ) / self._peak_balance
        return {
            "current_balance": self._current_balance,
            "peak_balance": self._peak_balance,
            "open_positions": self.open_position_count,
            "daily_trade_count": self._daily_trade_count,
            "daily_pnl_pct": daily_loss_pct,
            "total_drawdown_pct": drawdown_pct,
            "circuit_breaker_active": self._circuit_breaker_active,
            "circuit_breaker_reason": self._circuit_breaker_reason,
        }

    def _check_progressive_sl(
        self, state: _PositionState, current_price: float
    ) -> RuleResult:
        if not self._config.progressive_sl.enabled:
            return RuleResult(action=RuleAction.NO_ACTION)

        pip_value = self._pip_value(state.entry_price)
        be_trigger = self._config.progressive_sl.breakeven_trigger_pips
        be_offset = self._config.progressive_sl.breakeven_offset_pips * pip_value
        trail_start = self._config.progressive_sl.trail_start_pips
        trail_step = self._config.progressive_sl.trail_step_pips * pip_value

        profit_pips = self._calc_profit_pips(state, current_price, pip_value)

        if profit_pips >= be_trigger and not state.sl_moved_to_breakeven:
            state.sl_moved_to_breakeven = True
            if state.direction == "long":
                new_sl = state.entry_price + be_offset
            else:
                new_sl = state.entry_price - be_offset
            state.stop_loss = new_sl
            return RuleResult(
                action=RuleAction.MODIFY_SL,
                reason=f"SL moved to breakeven at {profit_pips:.1f} pips",
                new_sl=new_sl,
            )

        if profit_pips >= trail_start:
            state.trail_active = True

        if state.trail_active:
            if state.direction == "long":
                new_sl = state.highest_price - trail_step
                if new_sl > state.stop_loss:
                    state.stop_loss = new_sl
                    return RuleResult(
                        action=RuleAction.MODIFY_SL,
                        reason=f"Trailing SL updated to {new_sl:.5f}",
                        new_sl=new_sl,
                    )
                if current_price <= state.stop_loss:
                    return RuleResult(
                        action=RuleAction.CLOSE_ALL,
                        reason="Trailing stop hit",
                    )
            else:
                new_sl = state.lowest_price + trail_step
                if new_sl < state.stop_loss:
                    state.stop_loss = new_sl
                    return RuleResult(
                        action=RuleAction.MODIFY_SL,
                        reason=f"Trailing SL updated to {new_sl:.5f}",
                        new_sl=new_sl,
                    )
                if current_price >= state.stop_loss:
                    return RuleResult(
                        action=RuleAction.CLOSE_ALL,
                        reason="Trailing stop hit",
                    )

        if not state.trail_active:
            if state.direction == "long" and current_price <= state.stop_loss:
                return RuleResult(action=RuleAction.CLOSE_ALL, reason="Stop loss hit")
            if state.direction == "short" and current_price >= state.stop_loss:
                return RuleResult(action=RuleAction.CLOSE_ALL, reason="Stop loss hit")

        return RuleResult(action=RuleAction.NO_ACTION)

    def _check_partial_profit(
        self, state: _PositionState, current_price: float
    ) -> RuleResult:
        if not self._config.partial_profit.enabled:
            return RuleResult(action=RuleAction.NO_ACTION)

        risk = abs(state.entry_price - state.original_sl)
        if risk == 0:
            return RuleResult(action=RuleAction.NO_ACTION)

        if state.direction == "long":
            reward = current_price - state.entry_price
        else:
            reward = state.entry_price - current_price

        current_rr = reward / risk

        for i, (close_pct, rr_target, move_sl) in enumerate(
            self._config.partial_profit.tiers
        ):
            if i < state.tiers_hit:
                continue
            if current_rr < rr_target - 1e-9:
                continue

            actual_close_pct = close_pct - state.cumulative_closed_pct
            state.tiers_hit = i + 1
            state.cumulative_closed_pct = close_pct
            state.remaining_pct = 1.0 - close_pct

            new_sl = None
            if move_sl and not state.sl_moved_to_breakeven:
                state.sl_moved_to_breakeven = True
                new_sl = state.entry_price

            return RuleResult(
                action=RuleAction.PARTIAL_CLOSE,
                reason=f"Partial close at tier {i + 1} ({rr_target}R)",
                close_pct=actual_close_pct,
                new_sl=new_sl,
            )

        return RuleResult(action=RuleAction.NO_ACTION)

    def _calc_weekly_drawdown(self, now: datetime) -> float:
        if not self._pnl_history:
            return 0.0
        cutoff = now - timedelta(days=self._config.weekly_drawdown.rolling_days)
        weekly_pnl = sum(r.pnl for r in self._pnl_history if r.timestamp >= cutoff)
        if self._peak_balance <= 0:
            return 0.0
        return weekly_pnl / self._peak_balance

    def _calc_profit_pips(
        self, state: _PositionState, current_price: float, pip_value: float
    ) -> float:
        if state.direction == "long":
            return (current_price - state.entry_price) / pip_value
        else:
            return (state.entry_price - current_price) / pip_value

    @staticmethod
    def _pip_value(price: float) -> float:
        if price >= 50:
            return 0.01
        elif price >= 1:
            return 0.0001
        return 0.00000001

    @staticmethod
    def _calc_risk_reward(signal: HumanSignal) -> float:
        sl = signal.stop_loss if signal.stop_loss is not None else signal.entry_price
        tp = (
            signal.take_profit if signal.take_profit is not None else signal.entry_price
        )
        risk = abs(signal.entry_price - sl)
        reward = abs(tp - signal.entry_price)
        if risk == 0:
            return 0.0
        return reward / risk
