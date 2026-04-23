from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from hybrid.signal import HumanSignal, SignalType
from quant.position_sizing import fixed_fractional


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
        self._daily_trade_count = 0
        self._daily_risk_used_pct = 0.0
        self._peak_balance = starting_balance
        self._open_position_count = 0

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
        if risk_reward < self._min_risk_reward:
            return RiskDecision(
                action=RiskAction.REJECT,
                reason=(
                    f"Risk:Reward {risk_reward:.2f} below minimum "
                    f"{self._min_risk_reward}"
                ),
                risk_reward=risk_reward,
            )

        if self._risk_per_trade_pct > remaining_daily_risk:
            capped_risk = remaining_daily_risk
        else:
            capped_risk = self._risk_per_trade_pct

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

        lot_size = fixed_fractional(
            account_balance=balance,
            risk_pct=risk_pct,
            entry_price=signal.entry_price,
            stop_loss=sl,
        )
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
