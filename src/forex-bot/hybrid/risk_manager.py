from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone
from enum import StrEnum

from hybrid.signal import HumanSignal, SignalType
from quant.position_sizing import fixed_fractional

logger = logging.getLogger(__name__)


class RiskAction(StrEnum):
    ALLOW = "allow"
    REJECT = "reject"
    REDUCE_SIZE = "reduce_size"


@dataclass
class RiskDecision:
    action: RiskAction
    reason: str
    risk_reward: float | None = None
    suggested_lot_size: float | None = None
    max_lot_size: float | None = None


@dataclass
class LondonSessionConfig:
    start_hour: int = 8
    start_minute: int = 0
    end_hour: int = 12
    end_minute: int = 0
    min_risk_reward: float = 2.0
    size_multiplier: float = 0.5
    blocked_pair_prefixes: tuple[str, ...] = ("GBP",)

    def contains(self, utc_dt: datetime) -> bool:
        t = utc_dt.time()
        start = time(self.start_hour, self.start_minute)
        end = time(self.end_hour, self.end_minute)
        if start <= end:
            return start <= t < end
        return t >= start or t < end

    def is_blocked_pair(self, pair: str) -> bool:
        upper = pair.upper().replace("/", "")
        return any(upper.startswith(p) for p in self.blocked_pair_prefixes)


class RiskManager:
    def __init__(
        self,
        starting_balance: float = 100_000.0,
        risk_per_trade_pct: float = 0.5,
        max_daily_loss_pct: float = 5.0,
        max_total_drawdown_pct: float = 10.0,
        max_trades_per_day: int = 10,
        max_positions: int = 3,
        min_risk_reward: float = 1.5,
        max_daily_risk_pct: float = 1.5,
        max_lot_size: float = 1.0,
        london_config: LondonSessionConfig | None = None,
    ) -> None:
        self._starting_balance = starting_balance
        self._current_balance = starting_balance
        self._risk_per_trade_pct = risk_per_trade_pct
        self._max_daily_loss_pct = max_daily_loss_pct
        self._max_total_drawdown_pct = max_total_drawdown_pct
        self._max_trades_per_day = max_trades_per_day
        self._max_positions = max_positions
        self._min_risk_reward = min_risk_reward
        self._max_daily_risk_pct = max_daily_risk_pct
        self._max_lot_size = max_lot_size
        self._london_config = london_config or LondonSessionConfig()
        self._daily_trade_count = 0
        self._daily_risk_used_pct = 0.0
        self._peak_balance = starting_balance
        self._open_position_count = 0
        self._london_trade_count = 0

    @property
    def current_balance(self) -> float:
        return self._current_balance

    @property
    def daily_trade_count(self) -> int:
        return self._daily_trade_count

    @property
    def open_position_count(self) -> int:
        return self._open_position_count

    @property
    def max_lot_size(self) -> float:
        return self._max_lot_size

    @property
    def london_trade_count(self) -> int:
        return self._london_trade_count

    @property
    def london_config(self) -> LondonSessionConfig:
        return self._london_config

    @property
    def daily_loss_pct(self) -> float:
        if self._starting_balance <= 0:
            return 0.0
        return max(
            0.0,
            (self._starting_balance - self._current_balance)
            / self._starting_balance
            * 100.0,
        )

    @property
    def total_drawdown_pct(self) -> float:
        if self._peak_balance <= 0:
            return 0.0
        return max(
            0.0,
            (self._peak_balance - self._current_balance) / self._peak_balance * 100.0,
        )

    def is_london_session(self, utc_dt: datetime | None = None) -> bool:
        if utc_dt is None:
            utc_dt = datetime.now(timezone.utc)
        return self._london_config.contains(utc_dt)

    def validate_signal(self, signal: HumanSignal) -> RiskDecision:
        if signal.signal_type == SignalType.CLOSE:
            return RiskDecision(
                action=RiskAction.ALLOW,
                reason="Close signals are always allowed",
            )

        if self._daily_trade_count >= self._max_trades_per_day:
            return RiskDecision(
                action=RiskAction.REJECT,
                reason=(
                    f"Daily trade limit reached: {self._daily_trade_count}/"
                    f"{self._max_trades_per_day}"
                ),
            )

        if self._open_position_count >= self._max_positions:
            return RiskDecision(
                action=RiskAction.REJECT,
                reason=(
                    f"Max positions reached: {self._open_position_count}/"
                    f"{self._max_positions}"
                ),
            )

        if not signal.has_stop_loss:
            return RiskDecision(
                action=RiskAction.REJECT,
                reason="Signal must include a stop loss",
            )

        if self._london_config.contains(signal.timestamp):
            pair_rejection = self._check_london_pair_filter(signal)
            if pair_rejection is not None:
                return pair_rejection

        daily_dd = self.daily_loss_pct
        if daily_dd >= self._max_daily_loss_pct:
            return RiskDecision(
                action=RiskAction.REJECT,
                reason=(
                    f"Daily drawdown {daily_dd:.2f}% >= limit "
                    f"{self._max_daily_loss_pct:.2f}%"
                ),
            )

        total_dd = self.total_drawdown_pct
        if total_dd >= self._max_total_drawdown_pct:
            return RiskDecision(
                action=RiskAction.REJECT,
                reason=(
                    f"Total drawdown {total_dd:.2f}% >= limit "
                    f"{self._max_total_drawdown_pct:.2f}%"
                ),
            )

        remaining_daily_risk = self._max_daily_risk_pct - self._daily_risk_used_pct
        if remaining_daily_risk <= 0:
            return RiskDecision(
                action=RiskAction.REJECT,
                reason=(
                    f"Daily risk budget exhausted: "
                    f"{self._daily_risk_used_pct:.2f}%/{self._max_daily_risk_pct:.2f}%"
                ),
            )

        risk_reward = self._calculate_risk_reward(signal)
        effective_min_rr = self._get_effective_min_rr(signal)
        if risk_reward < effective_min_rr:
            return RiskDecision(
                action=RiskAction.REJECT,
                reason=(
                    f"Risk:Reward {risk_reward:.2f} below minimum {effective_min_rr}"
                ),
                risk_reward=risk_reward,
            )

        if self._risk_per_trade_pct > remaining_daily_risk:
            capped_risk = remaining_daily_risk
        else:
            capped_risk = self._risk_per_trade_pct

        in_london = self._london_config.contains(signal.timestamp)
        if in_london:
            self._london_trade_count += 1
            logger.info(
                "London entry: pair=%s R:R=%.2f risk_pct=%.2f",
                signal.pair,
                risk_reward,
                capped_risk,
            )

        return RiskDecision(
            action=RiskAction.ALLOW,
            reason="Signal passes all risk checks",
            risk_reward=risk_reward,
            suggested_lot_size=capped_risk,
            max_lot_size=remaining_daily_risk,
        )

    def calculate_position_size(
        self,
        signal: HumanSignal,
        account_balance: float | None = None,
        risk_pct_override: float | None = None,
    ) -> float:
        balance = (
            account_balance if account_balance is not None else self._current_balance
        )
        if signal.signal_type == SignalType.CLOSE:
            return 0.0
        if not signal.has_stop_loss or signal.entry_price <= 0:
            return 0.0

        sl = signal.stop_loss if signal.stop_loss is not None else signal.entry_price
        risk_pct = (
            risk_pct_override
            if risk_pct_override is not None
            else self._risk_per_trade_pct
        )

        if self._london_config.contains(signal.timestamp):
            risk_pct *= self._london_config.size_multiplier
            logger.info(
                "London size reduction: pair=%s multiplier=%.1f adjusted_risk_pct=%.2f",
                signal.pair,
                self._london_config.size_multiplier,
                risk_pct,
            )

        lot_size = fixed_fractional(
            account_balance=balance,
            risk_pct=risk_pct,
            entry_price=signal.entry_price,
            stop_loss=sl,
        )
        lot_size = min(lot_size, self._max_lot_size)
        return max(0.0, round(lot_size, 2))

    def open_position(self) -> None:
        self._open_position_count += 1

    def close_position(self) -> None:
        if self._open_position_count > 0:
            self._open_position_count -= 1

    def record_trade(self, pnl: float, risk_pct: float | None = None) -> None:
        self._current_balance += pnl
        self._daily_trade_count += 1
        used_risk = risk_pct if risk_pct is not None else self._risk_per_trade_pct
        self._daily_risk_used_pct += used_risk
        if self._current_balance > self._peak_balance:
            self._peak_balance = self._current_balance

    def reset_daily_tracking(self) -> None:
        self._daily_trade_count = 0
        self._daily_risk_used_pct = 0.0
        self._london_trade_count = 0

    def _get_effective_min_rr(self, signal: HumanSignal) -> float:
        if self._london_config.contains(signal.timestamp):
            return max(self._min_risk_reward, self._london_config.min_risk_reward)
        return self._min_risk_reward

    def _check_london_pair_filter(self, signal: HumanSignal) -> RiskDecision | None:
        if self._london_config.is_blocked_pair(signal.pair):
            logger.info(
                "London pair filter: rejected %s during London session",
                signal.pair,
            )
            return RiskDecision(
                action=RiskAction.REJECT,
                reason=(
                    f"Pair {signal.pair} blocked during London session "
                    f"({self._london_config.start_hour:02d}:00-"
                    f"{self._london_config.end_hour:02d}:00 UTC)"
                ),
            )
        return None

    def _calculate_risk_reward(self, signal: HumanSignal) -> float:
        if not signal.has_stop_loss or not signal.has_take_profit:
            return 0.0
        sl = signal.stop_loss if signal.stop_loss is not None else signal.entry_price
        tp = (
            signal.take_profit if signal.take_profit is not None else signal.entry_price
        )
        risk = abs(signal.entry_price - sl)
        reward = abs(tp - signal.entry_price)
        if risk == 0:
            return 0.0
        return reward / risk
