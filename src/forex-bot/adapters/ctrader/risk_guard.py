import json
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import Lock

from .models import TradeDirection, TradeSignal

logger = logging.getLogger(__name__)


class RiskLimitType(Enum):
    DAILY_LOSS = "daily_loss"
    TOTAL_DRAWDOWN = "total_drawdown"
    MAX_TRADES = "max_trades"
    MAX_POSITIONS = "max_positions"
    MIN_RISK_REWARD = "min_risk_reward"
    POSITION_SIZE = "position_size"


@dataclass
class RiskLimitResult:
    allowed: bool
    limit_type: RiskLimitType
    message: str
    current_value: float = 0.0
    limit_value: float = 0.0


@dataclass
class FTMOProfile:
    risk_per_trade_pct: float = 0.005
    daily_loss_limit_pct: float = 0.05
    total_drawdown_limit_pct: float = 0.10
    max_trades_per_day: int = 10
    max_positions: int = 3
    min_risk_reward: float = 1.5
    best_day_rule_max_pct: float = 0.50

    def __post_init__(self):
        if self.risk_per_trade_pct <= 0:
            raise ValueError(
                f"risk_per_trade_pct must be positive, got {self.risk_per_trade_pct}"
            )
        if self.daily_loss_limit_pct <= 0:
            raise ValueError(
                f"daily_loss_limit_pct must be positive, got {self.daily_loss_limit_pct}"
            )
        if self.max_trades_per_day <= 0:
            raise ValueError(
                f"max_trades_per_day must be positive, got {self.max_trades_per_day}"
            )
        max_total_risk = self.risk_per_trade_pct * self.max_trades_per_day
        if max_total_risk > self.daily_loss_limit_pct:
            raise ValueError(
                f"risk_per_trade_pct ({self.risk_per_trade_pct}) * "
                f"max_trades_per_day ({self.max_trades_per_day}) = "
                f"{max_total_risk:.4f} exceeds daily_loss_limit_pct "
                f"({self.daily_loss_limit_pct}). Reduce risk per trade or "
                f"max trades per day."
            )


FTMO_PROFILE_CHALLENGE = FTMOProfile()


@dataclass
class FTMOConfig:
    daily_loss_limit_pct: float = FTMO_PROFILE_CHALLENGE.daily_loss_limit_pct
    total_drawdown_limit_pct: float = FTMO_PROFILE_CHALLENGE.total_drawdown_limit_pct
    max_trades_per_day: int = FTMO_PROFILE_CHALLENGE.max_trades_per_day
    max_positions: int = FTMO_PROFILE_CHALLENGE.max_positions
    min_risk_reward: float = FTMO_PROFILE_CHALLENGE.min_risk_reward
    max_position_size_pct: float = FTMO_PROFILE_CHALLENGE.risk_per_trade_pct
    best_day_rule_max_pct: float = FTMO_PROFILE_CHALLENGE.best_day_rule_max_pct


@dataclass
class DailyTradingStats:
    date: date
    trades_count: int = 0
    wins: int = 0
    losses: int = 0
    pnl: float = 0.0
    best_day_profit: float = 0.0
    positive_days_pnl: float = 0.0


class RiskGuard:
    def __init__(
        self,
        ftmo_config: FTMOConfig | None = None,
        starting_balance: float = 100000.0,
        state_path: str = "data/state/risk_guard_state.json",
    ):
        self._config = ftmo_config or FTMOConfig()
        self._starting_balance = starting_balance
        self._peak_balance = starting_balance
        self._current_balance = starting_balance
        self._daily_start_balance = starting_balance
        self._current_day: date | None = None
        self._daily_stats: list[DailyTradingStats] = []
        self._lock = Lock()
        self._callbacks: list[Callable] = []
        self._daily_trade_count = 0
        self._total_trades = 0
        self._blocked_until: datetime | None = None
        self._circuit_breaker_triggered = False
        self._per_strategy_pnl: dict[str, float] = {}
        self._state_path = state_path
        self._restore_state()

    def check_signal(self, signal: TradeSignal) -> RiskLimitResult:
        with self._lock:
            return self._check_signal_internal(signal)

    def _check_signal_internal(self, signal: TradeSignal) -> RiskLimitResult:
        if self._circuit_breaker_triggered:
            return RiskLimitResult(
                allowed=False,
                limit_type=RiskLimitType.DAILY_LOSS,
                message="Circuit breaker triggered - trading paused",
                current_value=1.0,
                limit_value=1.0,
            )

        if self._blocked_until and datetime.now(timezone.utc) < self._blocked_until:
            return RiskLimitResult(
                allowed=False,
                limit_type=RiskLimitType.DAILY_LOSS,
                message=f"Trading blocked until {self._blocked_until}",
            )

        risk_reward = self._calculate_risk_reward(signal)
        if risk_reward < self._config.min_risk_reward:
            return RiskLimitResult(
                allowed=False,
                limit_type=RiskLimitType.MIN_RISK_REWARD,
                message=f"Risk:Reward {risk_reward:.2f} below minimum {self._config.min_risk_reward}",
                current_value=risk_reward,
                limit_value=self._config.min_risk_reward,
            )

        return RiskLimitResult(
            allowed=True,
            limit_type=RiskLimitType.MIN_RISK_REWARD,
            message="Signal approved",
        )

    def check_trade_allowed(
        self,
        direction: TradeDirection,
        volume: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        account_balance: float | None = None,
        symbol: str | None = None,
    ) -> RiskLimitResult:
        with self._lock:
            return self._check_trade_allowed_internal(
                direction, volume, entry_price, stop_loss, take_profit, account_balance, symbol
            )

    def _check_trade_allowed_internal(
        self,
        direction: TradeDirection,
        volume: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        account_balance: float | None = None,
        symbol: str | None = None,
    ) -> RiskLimitResult:
        if account_balance:
            self._current_balance = account_balance

        if self._circuit_breaker_triggered:
            return RiskLimitResult(
                allowed=False,
                limit_type=RiskLimitType.DAILY_LOSS,
                message="Circuit breaker triggered - trading paused",
            )

        if self._blocked_until and datetime.now(timezone.utc) < self._blocked_until:
            return RiskLimitResult(
                allowed=False,
                limit_type=RiskLimitType.DAILY_LOSS,
                message=f"Trading blocked until {self._blocked_until}",
            )

        self._update_daily_tracking()

        # Only enforce daily loss limit when trades have actually occurred.
        # Without this guard, an externally-updated balance (e.g. from a
        # broker snapshot) can falsely trigger the circuit breaker when
        # no trades have been placed today.
        daily_loss_pct = 0.0
        if self._daily_trade_count > 0:
            daily_loss_pct = (
                self._daily_start_balance - self._current_balance
            ) / self._daily_start_balance
        if self._daily_trade_count > 0 and daily_loss_pct >= self._config.daily_loss_limit_pct:
            self._trigger_circuit_breaker(
                RiskLimitType.DAILY_LOSS,
                daily_loss_pct,
                self._config.daily_loss_limit_pct,
            )
            return RiskLimitResult(
                allowed=False,
                limit_type=RiskLimitType.DAILY_LOSS,
                message=f"Daily loss limit {daily_loss_pct * 100:.2f}% >= {self._config.daily_loss_limit_pct * 100}%",
                current_value=daily_loss_pct,
                limit_value=self._config.daily_loss_limit_pct,
            )

        drawdown_pct = (self._peak_balance - self._current_balance) / self._peak_balance
        if drawdown_pct >= self._config.total_drawdown_limit_pct:
            self._trigger_circuit_breaker(
                RiskLimitType.TOTAL_DRAWDOWN,
                drawdown_pct,
                self._config.total_drawdown_limit_pct,
            )
            return RiskLimitResult(
                allowed=False,
                limit_type=RiskLimitType.TOTAL_DRAWDOWN,
                message=f"Total drawdown {drawdown_pct * 100:.2f}% >= {self._config.total_drawdown_limit_pct * 100}%",
                current_value=drawdown_pct,
                limit_value=self._config.total_drawdown_limit_pct,
            )

        if self._daily_trade_count >= self._config.max_trades_per_day:
            return RiskLimitResult(
                allowed=False,
                limit_type=RiskLimitType.MAX_TRADES,
                message=f"Daily trade count {self._daily_trade_count} >= {self._config.max_trades_per_day}",
                current_value=float(self._daily_trade_count),
                limit_value=float(self._config.max_trades_per_day),
            )

        # Risk-based position size check: SL hit cost as % of balance.
        # Notional exposure (volume * 100k) is not meaningful for FTMO rules —
        # what matters is how much you lose if SL is hit.
        sl_distance = abs(entry_price - stop_loss)
        # Use SymbolInfo metadata when symbol is available; fall back to price heuristic.
        from .models import get_symbol_info
        if symbol:
            sym_info = get_symbol_info(symbol)
            pip_size = sym_info.pip_size
            pip_value_per_lot = sym_info.pip_value_per_lot
        else:
            # Heuristic fallback: infer from price level
            is_jpy_pair = abs(entry_price) > 50
            if is_jpy_pair:
                if abs(entry_price) > 1000:
                    pip_size = 0.01
                    pip_value_per_lot = 1.0
                else:
                    pip_size = 0.01
                    pip_value_per_lot = 6.5
            else:
                pip_size = 0.0001
                pip_value_per_lot = 10.0
        sl_pips = sl_distance / pip_size if pip_size > 0 else 0
        risk_amount = volume * sl_pips * pip_value_per_lot
        risk_pct = risk_amount / self._current_balance if self._current_balance > 0 else float('inf')
        # Use >= with epsilon tolerance to avoid false rejections when risk
        # lands exactly at the limit due to rounding/approximation.
        epsilon = 0.0001  # 0.01% tolerance
        if risk_pct > self._config.max_position_size_pct + epsilon:
            return RiskLimitResult(
                allowed=False,
                limit_type=RiskLimitType.POSITION_SIZE,
                message=f"Position risk {risk_pct * 100:.2f}% > max {self._config.max_position_size_pct * 100}%",
                current_value=risk_pct,
                limit_value=self._config.max_position_size_pct,
            )

        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        if risk == 0 or reward / risk < self._config.min_risk_reward:
            return RiskLimitResult(
                allowed=False,
                limit_type=RiskLimitType.MIN_RISK_REWARD,
                message=f"Risk:Reward below minimum {self._config.min_risk_reward}",
            )

        return RiskLimitResult(
            allowed=True,
            limit_type=RiskLimitType.POSITION_SIZE,
            message="Trade allowed",
        )

    def _calculate_risk_reward(self, signal: TradeSignal) -> float:
        risk = abs(signal.entry_price - signal.stop_loss)
        reward = abs(signal.take_profit_1 - signal.entry_price)
        if risk == 0:
            return 0.0
        return reward / risk

    def _update_daily_tracking(self):
        today = datetime.now(timezone.utc).date()
        if self._current_day is None:
            self._current_day = today
            self._daily_start_balance = self._current_balance
            self._daily_trade_count = 0
        elif today != self._current_day:
            self._record_daily_stats()
            self._current_day = today
            self._daily_start_balance = self._current_balance
            self._daily_trade_count = 0

    def _record_daily_stats(self):
        if self._current_day:
            stats = DailyTradingStats(
                date=self._current_day,
                trades_count=self._daily_trade_count,
                pnl=self._current_balance - self._daily_start_balance,
            )
            self._daily_stats.append(stats)

            if stats.pnl > 0:
                if stats.pnl > self._get_best_day_profit():
                    self._check_best_day_rule(stats)

    def _get_best_day_profit(self) -> float:
        return max((s.pnl for s in self._daily_stats if s.pnl > 0), default=0.0)

    def _check_best_day_rule(self, stats: DailyTradingStats):
        positive_days = [s for s in self._daily_stats if s.pnl > 0]
        if len(positive_days) < 2:
            return

        total_positive_pnl = sum(s.pnl for s in positive_days)
        best_day_pct = stats.pnl / total_positive_pnl if total_positive_pnl > 0 else 0

        if best_day_pct > self._config.best_day_rule_max_pct:
            logger.warning(
                f"Best day rule warning: Best day {best_day_pct * 100:.1f}% > {self._config.best_day_rule_max_pct * 100}% limit"
            )

    def _trigger_circuit_breaker(
        self, limit_type: RiskLimitType, current: float, limit: float
    ):
        if limit_type == RiskLimitType.DAILY_LOSS:
            # R2: Daily loss = block until UTC midnight (NOT 5 min)
            next_midnight = (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).replace(hour=0, minute=0, second=0, microsecond=0)
            self._blocked_until = next_midnight
            # Do NOT set _circuit_breaker_triggered for daily loss —
            # this allows auto-recovery at UTC midnight without manual reset.
            logger.critical(
                f"DAILY LOSS HALT: blocking until UTC midnight "
                f"({next_midnight.isoformat()}) — {limit_type.value} = "
                f"{current * 100:.2f}% >= {limit * 100:.2f}%"
            )
        else:
            # Total drawdown or other breaches: PERMANENT circuit breaker.
            # R2 (Kaito): No auto-recovery, no _blocked_until expiry.
            # Requires explicit reset_circuit_breaker() call.
            self._circuit_breaker_triggered = True
            self._blocked_until = None  # permanent — no time-based expiry
            logger.critical(
                f"MAX DRAWDOWN BREACH: permanent block until manual reset "
                f"— {limit_type.value} = "
                f"{current * 100:.2f}% >= {limit * 100:.2f}%"
            )

        self._save_state()

        # Activate kill switch based on breach type
        # Uses injected kill_switch if available, otherwise creates one.
        # Tests should inject a mock to avoid writing to production state.
        try:
            ks = getattr(self, '_kill_switch', None)
            if ks is None:
                from .kill_switch import KillSwitchManager
                ks = KillSwitchManager()
            if limit_type == RiskLimitType.DAILY_LOSS:
                ks.activate_global_kill(
                    "ftmo_daily_loss_limit", "risk_guard", close_positions=True
                )
            elif limit_type == RiskLimitType.TOTAL_DRAWDOWN:
                ks.activate_global_kill(
                    "ftmo_total_drawdown", "risk_guard", close_positions=True
                )
        except Exception:
            logger.error(
                "Failed to activate kill switch from risk guard", exc_info=True
            )

        for callback in self._callbacks:
            try:
                callback(limit_type, current, limit)
            except Exception as e:
                logger.error(f"Circuit breaker callback error: {e}")

    def record_trade(
        self,
        pnl: float,
        is_win: bool,
        trade_count_increment: int = 1,
    ):
        with self._lock:
            self._total_trades += trade_count_increment
            self._daily_trade_count += trade_count_increment
            self._current_balance += pnl

            if self._current_balance > self._peak_balance:
                self._peak_balance = self._current_balance

            self._update_daily_tracking()
            self._save_state()

    def record_strategy_trade(self, strategy_id: str, pnl: float):
        with self._lock:
            self._per_strategy_pnl[strategy_id] = (
                self._per_strategy_pnl.get(strategy_id, 0.0) + pnl
            )

    def set_kill_switch(self, kill_switch):
        """Inject a kill switch instance (used by ForwardTestEngine to share state)."""
        self._kill_switch = kill_switch

    def update_balance(self, new_balance: float):
        with self._lock:
            self._current_balance = new_balance
            if new_balance > self._peak_balance:
                self._peak_balance = new_balance

    def reset_daily_tracking(self):
        with self._lock:
            self._daily_start_balance = self._current_balance
            self._daily_trade_count = 0

    def reset_circuit_breaker(self, reason: str = "manual reset") -> bool:
        """Manually clear circuit breaker state.

        Only works for permanent (total drawdown) blocks, not daily loss
        time-based blocks.  Daily loss blocks expire automatically at UTC
        midnight and cannot be manually cleared.

        Returns True if the permanent block was cleared, False otherwise.
        """
        with self._lock:
            if self._blocked_until is not None:
                logger.warning(
                    "Cannot reset time-based block (daily loss). "
                    "Wait for UTC midnight."
                )
                return False
            if not self._circuit_breaker_triggered:
                logger.info("Circuit breaker not triggered — nothing to reset.")
                return True
            self._circuit_breaker_triggered = False
            logger.info("Circuit breaker manually reset: %s", reason)
            self._save_state()
            return True

    def _save_state(self) -> None:
        """Persist RiskGuard state atomically to JSON (R1)."""
        state = {
            "peak_balance": self._peak_balance,
            "current_balance": self._current_balance,
            "daily_start_balance": self._daily_start_balance,
            "current_day": self._current_day.isoformat() if self._current_day else None,
            "daily_trade_count": self._daily_trade_count,
            "total_trades": self._total_trades,
            "circuit_breaker_triggered": self._circuit_breaker_triggered,
            "blocked_until": self._blocked_until.isoformat() if self._blocked_until else None,
            "last_save_ts": datetime.now(timezone.utc).isoformat(),
        }

        path = Path(self._state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            logger.error("Failed to save RiskGuard state", exc_info=True)

    def _restore_state(self) -> None:
        """Restore RiskGuard state from JSON file (R1)."""
        path = Path(self._state_path)
        if not path.exists():
            logger.info("No RiskGuard state file at %s — starting fresh", path)
            return

        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Corrupt RiskGuard state file %s: %s", path, e)
            return

        try:
            self._peak_balance = raw.get("peak_balance", self._peak_balance)
            self._current_balance = raw.get("current_balance", self._current_balance)
            self._daily_start_balance = raw.get(
                "daily_start_balance", self._daily_start_balance
            )

            day_str = raw.get("current_day")
            self._current_day = (
                date.fromisoformat(day_str) if day_str else None
            )

            self._daily_trade_count = raw.get("daily_trade_count", 0)
            self._total_trades = raw.get("total_trades", 0)
            self._circuit_breaker_triggered = raw.get(
                "circuit_breaker_triggered", False
            )

            blocked_str = raw.get("blocked_until")
            if blocked_str:
                self._blocked_until = datetime.fromisoformat(blocked_str)
            else:
                self._blocked_until = None

            # If restored state is from a previous day, reset daily counters
            today = datetime.now(timezone.utc).date()
            if self._current_day is not None and self._current_day != today:
                logger.info(
                    "State from %s — resetting daily tracking for %s",
                    self._current_day,
                    today,
                )
                self._current_day = today
                self._daily_start_balance = self._current_balance
                self._daily_trade_count = 0
                # Clear expired daily-loss block
                if self._blocked_until and datetime.now(timezone.utc) >= self._blocked_until:
                    self._blocked_until = None

            logger.info("Restored RiskGuard state from %s", path)
        except Exception as e:
            logger.error("Failed to restore RiskGuard state: %s", e)

    def register_circuit_breaker_callback(self, callback: Callable):
        self._callbacks.append(callback)

    @property
    def daily_trade_count(self) -> int:
        return self._daily_trade_count

    @property
    def total_trades(self) -> int:
        return self._total_trades

    @property
    def current_drawdown_pct(self) -> float:
        return (self._peak_balance - self._current_balance) / self._peak_balance

    @property
    def current_daily_loss_pct(self) -> float:
        return (
            self._daily_start_balance - self._current_balance
        ) / self._daily_start_balance

    @property
    def is_blocked(self) -> bool:
        if self._circuit_breaker_triggered:
            return True
        if (
            self._blocked_until is not None
            and datetime.now(timezone.utc) < self._blocked_until
        ):
            return True
        return False

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "total_trades": self._total_trades,
                "daily_trades": self._daily_trade_count,
                "current_balance": self._current_balance,
                "peak_balance": self._peak_balance,
                "daily_loss_pct": self.current_daily_loss_pct,
                "total_drawdown_pct": self.current_drawdown_pct,
                "is_blocked": self.is_blocked,
                "per_strategy_pnl": dict(self._per_strategy_pnl),
            }
