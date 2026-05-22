"""SL-Derived Position Sizer for Ayumi.

Core principle: Strategy decides WHERE the SL goes (wick, EMA, support).
Position sizer decides HOW MUCH to trade so that SL hit = intended risk.

Formula:
    position_size_lots = (account_risk_amount) / (sl_distance_price * pip_value_per_lot)

Guards:
    - Max position size: 1.0 lot
    - Min SL distance: 5 pips
    - Daily risk cap: 3% (recycling — recovers as positions close)
    - Circuit breaker: halts trading for 24h on trigger
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Union
import logging

logger = logging.getLogger(__name__)


# Instrument specifications
@dataclass(frozen=True)
class InstrumentSpec:
    """Specification for a trading instrument."""
    symbol: str
    pip_size: float          # Price change per pip (e.g., 0.0001 for EURUSD, 0.01 for XAUUSD)
    lot_size: int            # Units per lot (e.g., 100000 for forex, 100 for XAUUSD)
    pip_value_per_lot: float # USD value of 1 pip movement per 1 lot

    @property
    def min_sl_pips(self) -> float:
        return 5.0  # Minimum SL distance in pips


# Common instruments
INSTRUMENTS = {
    "EURUSD": InstrumentSpec("EURUSD", pip_size=0.0001, lot_size=100000, pip_value_per_lot=10.0),
    "GBPUSD": InstrumentSpec("GBPUSD", pip_size=0.0001, lot_size=100000, pip_value_per_lot=10.0),
    # NOTE: USDJPY pip value varies with USD/JPY rate (~6.5 at 154.00).
    #       Update at runtime from broker feed for production accuracy.
    "USDJPY": InstrumentSpec("USDJPY", pip_size=0.01, lot_size=100000, pip_value_per_lot=6.5),
    "XAUUSD": InstrumentSpec("XAUUSD", pip_size=0.01, lot_size=100, pip_value_per_lot=1.0),
}


@dataclass
class PositionSizeResult:
    """Result of position sizing calculation."""
    lots: float
    risk_amount: float        # USD risk if SL hit
    sl_distance_pips: float
    sl_distance_price: float  # Absolute price distance
    pip_value: float
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: str = ""


@dataclass
class CircuitBreakerState:
    """Tracks circuit breaker conditions."""
    # Win rate tracking
    recent_trades: list[bool] = field(default_factory=list)  # True=win, False=loss
    max_trades_tracked: int = 20
    min_win_rate: float = 0.25

    # Drawdown tracking
    daily_dd_pct: float = 0.0
    daily_dd_limit: float = 0.03      # 3%
    account_dd_pct: float = 0.0
    account_dd_limit: float = 0.07    # 7%

    # Halt state
    halted: bool = False
    halted_until: Optional[datetime] = None
    halt_reason: str = ""

    def record_trade(self, win: bool):
        """Record a trade result."""
        self.recent_trades.append(win)
        if len(self.recent_trades) > self.max_trades_tracked:
            self.recent_trades = self.recent_trades[-self.max_trades_tracked:]

    @property
    def win_rate(self) -> float:
        if len(self.recent_trades) == 0:
            return 1.0  # No data = no breaker trigger
        return sum(self.recent_trades) / len(self.recent_trades)

    def check_breakers(self) -> Optional[str]:
        """Check if any circuit breaker should trigger. Returns reason or None."""
        if self.halted:
            if datetime.now(timezone.utc) >= self.halted_until:
                self.halted = False
                self.halted_until = None
                self.halt_reason = ""
                self.daily_dd_pct = 0.0  # Reset daily DD on un-halt
                logger.info("Circuit breaker lifted: %s", self.halt_reason)
            else:
                return f"Trading halted until {self.halted_until.isoformat()}: {self.halt_reason}"

        # Check win rate
        if len(self.recent_trades) >= 10:  # Need minimum sample
            if self.win_rate < self.min_win_rate:
                return f"Win rate {self.win_rate:.0%} < {self.min_win_rate:.0%} over last {len(self.recent_trades)} trades"

        # Check daily drawdown
        if self.daily_dd_pct >= self.daily_dd_limit:
            return f"Daily drawdown {self.daily_dd_pct:.1%} >= {self.daily_dd_limit:.1%}"

        # Check account drawdown
        if self.account_dd_pct >= self.account_dd_limit:
            return f"Account drawdown {self.account_dd_pct:.1%} >= {self.account_dd_limit:.1%}"

        return None

    def halt(self, reason: str, duration_hours: float = 24.0):
        """Trigger circuit breaker."""
        self.halted = True
        self.halted_until = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        self.halt_reason = reason
        logger.warning("CIRCUIT BREAKER TRIGGERED: %s. Halted until %s", reason, self.halted_until)


class SLPositionSizer:
    """Calculate position size based on SL distance and intended risk."""

    def __init__(
        self,
        account_balance: float,
        risk_per_trade_pct: float = 0.005,   # 0.5%
        max_lot_size: float = 1.0,
        daily_risk_cap_pct: float = 0.03,     # 3%
        min_sl_pips: float = 5.0,
    ):
        self.account_balance = account_balance
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_lot_size = max_lot_size
        self.daily_risk_cap_pct = daily_risk_cap_pct
        self.min_sl_pips = min_sl_pips

        # Track daily risk used (recycling)
        self._daily_risk_used: float = 0.0
        self._open_risk: float = 0.0  # Risk currently in open positions
        self._peak_balance: float = account_balance  # Track peak for account DD

        self.breaker = CircuitBreakerState()

    @property
    def risk_per_trade(self) -> float:
        """USD amount risked per trade."""
        return self.account_balance * self.risk_per_trade_pct

    @property
    def daily_risk_remaining(self) -> float:
        """USD risk remaining today.
        
        Recycling logic: open positions consume daily cap, but when they close,
        the risk budget is freed up for new trades. Realized losses stay consumed.
        """
        max_daily = self.account_balance * self.daily_risk_cap_pct
        # _daily_risk_used = realized losses (already closed)
        # _open_risk = risk in currently open positions
        # Total consumed = realized losses + open risk
        # When position closes with win: realized loss = 0, open risk freed
        # When position closes with loss: realized loss = actual loss, open risk freed
        return max(0.0, max_daily - self._daily_risk_used - self._open_risk)

    def update_balance(self, balance: float):
        """Update account balance and track peak."""
        if balance > self._peak_balance:
            self._peak_balance = balance
        self.account_balance = balance
        # Update account DD
        if self._peak_balance > 0:
            self.breaker.account_dd_pct = (self._peak_balance - balance) / self._peak_balance

    def register_open_position(self, risk_amount: float):
        """Track risk of an open position."""
        self._open_risk += risk_amount

    def cancel_position(self, risk_amount: float):
        """Cancel an open position that was sized but never executed.

        Frees risk budget when a downstream component (e.g. PaperTrader)
        rejects an order after the sizer already registered open risk.
        """
        if risk_amount > self._open_risk + 1e-9:
            logger.warning(
                "cancel_position overshoot: risk_amount=$%.2f > open_risk=$%.2f "
                "— clamping to zero (possible double-cancel or sizing mismatch)",
                risk_amount, self._open_risk,
            )
        self._open_risk -= risk_amount
        self._open_risk = max(0.0, self._open_risk)

    def close_position(self, pnl: float, risk_amount: float, win: bool):
        """Handle position close — update daily risk and record trade."""
        # Remove from open risk (this is the recycling — budget is freed)
        self._open_risk -= risk_amount
        self._open_risk = max(0.0, self._open_risk)

        # Only count actual losses toward daily budget
        if not win and pnl < 0:
            self._daily_risk_used += abs(pnl)  # Actual loss consumed daily budget

        self.breaker.record_trade(win)

        # Update account DD from actual P&L
        new_balance = self.account_balance + pnl
        if new_balance > self._peak_balance:
            self._peak_balance = new_balance
        self.account_balance = new_balance
        if self._peak_balance > 0:
            self.breaker.account_dd_pct = (self._peak_balance - self.account_balance) / self._peak_balance

    def reset_daily(self):
        """Reset daily counters (call at session open)."""
        if self._open_risk > 0:
            logger.warning(
                "reset_daily called with $%.2f in open positions — "
                "not resetting open_risk to avoid losing track",
                self._open_risk,
            )
        self._daily_risk_used = 0.0
        self.breaker.daily_dd_pct = 0.0

    def calculate(
        self,
        symbol: str,
        entry_price: float,
        sl_price: float,
        profile: Union[str, "Profile"] = "sniper",
    ) -> PositionSizeResult:
        """
        Calculate position size so SL hit = intended risk.

        Args:
            symbol: Trading instrument (e.g., "EURUSD")
            entry_price: Entry price
            sl_price: Stop loss price level (determined by strategy)
            profile: "sniper" (full risk) or "swarm" (reduced risk)

        Returns:
            PositionSizeResult with lots and metadata
        """
        warnings = []

        # Normalize profile (accept both str and Profile enum)
        if hasattr(profile, 'value'):
            profile = profile.value.lower()
        profile = str(profile).lower()

        # Check circuit breakers
        breaker_reason = self.breaker.check_breakers()
        if breaker_reason:
            return PositionSizeResult(
                lots=0.0, risk_amount=0.0, sl_distance_pips=0.0,
                sl_distance_price=0.0, pip_value=0.0,
                blocked=True, block_reason=breaker_reason
            )

        # Get instrument spec
        spec = INSTRUMENTS.get(symbol)
        if not spec:
            return PositionSizeResult(
                lots=0.0, risk_amount=0.0, sl_distance_pips=0.0,
                sl_distance_price=0.0, pip_value=0.0,
                blocked=True, block_reason=f"Unknown instrument: {symbol}"
            )

        # Calculate SL distance
        sl_distance_price = abs(entry_price - sl_price)
        sl_distance_pips = sl_distance_price / spec.pip_size

        logger.debug(
            "Sizing: symbol=%s entry=%.5f sl=%.5f dist_price=%.6f dist_pips=%.1f pip_size=%.4f",
            symbol, entry_price, sl_price, sl_distance_price, sl_distance_pips, spec.pip_size,
        )

        # Check min SL distance
        if sl_distance_pips < self.min_sl_pips - 0.01:  # Allow tiny floating point margin
            return PositionSizeResult(
                lots=0.0, risk_amount=0.0, sl_distance_pips=sl_distance_pips,
                sl_distance_price=sl_distance_price, pip_value=spec.pip_value_per_lot,
                blocked=True,
                block_reason=f"SL distance {sl_distance_pips:.1f} pips < minimum {self.min_sl_pips} pips"
            )

        # Determine risk amount based on profile
        base_risk = self.risk_per_trade
        if base_risk <= 0:
            return PositionSizeResult(
                lots=0.0, risk_amount=0.0, sl_distance_pips=sl_distance_pips,
                sl_distance_price=sl_distance_price, pip_value=spec.pip_value_per_lot,
                blocked=True, block_reason="Account risk amount is zero"
            )

        if profile not in ("sniper", "swarm"):
            return PositionSizeResult(
                lots=0.0, risk_amount=0.0, sl_distance_pips=sl_distance_pips,
                sl_distance_price=sl_distance_price, pip_value=spec.pip_value_per_lot if spec else 0.0,
                blocked=True, block_reason=f"Unknown profile: {profile}"
            )
        if profile == "swarm":
            base_risk *= 0.5  # Swarm uses half the per-trade risk

        # Check daily risk cap
        if base_risk > self.daily_risk_remaining:
            return PositionSizeResult(
                lots=0.0, risk_amount=0.0, sl_distance_pips=sl_distance_pips,
                sl_distance_price=sl_distance_price, pip_value=spec.pip_value_per_lot,
                blocked=True,
                block_reason=f"Trade risk ${base_risk:.2f} exceeds daily remaining ${self.daily_risk_remaining:.2f}"
            )

        # Calculate lots: risk_amount / (sl_pips * pip_value_per_lot)
        lots = base_risk / (sl_distance_pips * spec.pip_value_per_lot)

        # Apply max lot cap
        if lots > self.max_lot_size:
            warnings.append(f"Lots {lots:.4f} capped to max {self.max_lot_size}")
            lots = self.max_lot_size
            # Recalculate actual risk with capped lots
            actual_risk = lots * sl_distance_pips * spec.pip_value_per_lot
        else:
            actual_risk = base_risk

        # Round to reasonable precision (0.01 lots = micro lots)
        lots = round(lots, 2)
        if lots < 0.01:
            return PositionSizeResult(
                lots=0.0, risk_amount=0.0, sl_distance_pips=sl_distance_pips,
                sl_distance_price=sl_distance_price, pip_value=spec.pip_value_per_lot,
                blocked=True, block_reason=f"Calculated lots {lots:.4f} below minimum 0.01"
            )

        return PositionSizeResult(
            lots=lots,
            risk_amount=actual_risk,
            sl_distance_pips=sl_distance_pips,
            sl_distance_price=sl_distance_price,
            pip_value=spec.pip_value_per_lot,
            warnings=warnings,
        )
