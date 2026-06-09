"""Position Monitor — centralized position monitoring and lifecycle management.

Tracks per-position MAE/MFE, time-based exit rules, portfolio exposure,
drawdown alerts, and integrates with the kill switch for portfolio-level
safety.

Thread-safe. Designed to be called on each tick from the forward test engine
or run autonomously via its background monitoring thread.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Optional

from .models import Position, PositionStatus, TradeDirection

logger = logging.getLogger(__name__)


class PositionMonitor:
    """Centralized position monitoring and lifecycle management."""

    def __init__(
        self,
        order_manager,
        risk_guard=None,
        kill_switch=None,
        max_trade_duration_sec: float = 14400,   # 4 hours default
        check_interval_sec: float = 5.0,
    ):
        self._order_manager = order_manager
        self._risk_guard = risk_guard
        self._kill_switch = kill_switch
        self._max_trade_duration_sec = max_trade_duration_sec
        self._check_interval_sec = check_interval_sec
        self._lock = threading.RLock()

        # Background monitoring thread
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitor = threading.Event()

        # Callbacks for alerts
        self._callbacks: dict[str, list[Callable]] = {
            "on_time_exit": [],
            "on_drawdown_warning": [],
            "on_drawdown_critical": [],
        }

    # ── Core: update_positions ─────────────────────────────────────────────

    def update_positions(self, prices: dict, bids: dict, asks: dict):
        """Called on each tick — update all positions, track MAE/MFE, check time limits.

        Args:
            prices: dict of {symbol: mid_price}
            bids: dict of {symbol: bid_price}
            asks: dict of {symbol: ask_price}
        """
        with self._lock:
            open_positions = self._order_manager.get_open_positions()
            now = datetime.now(timezone.utc)

            for position in open_positions:
                if position.symbol not in prices:
                    continue

                mid_price = prices[position.symbol]
                bid = bids.get(position.symbol, mid_price)
                ask = asks.get(position.symbol, mid_price)

                # Update MAE/MFE based on unrealized PnL
                self._update_excursions(position, bid, ask)

                # Update high/low water marks
                self._update_water_marks(position, bid, ask)

                # Update time in trade
                self._update_time_in_trade(position, now)

    def _update_excursions(self, position: Position, bid: float, ask: float):
        """Update Maximum Favorable / Adverse Excursion."""
        # Calculate current unrealized PnL for this tick
        if position.direction == TradeDirection.LONG:
            exit_price = bid if bid > 0 else position.current_price
            current_pnl = (exit_price - position.entry_price) * position.volume * 100000
        else:
            exit_price = ask if ask > 0 else position.current_price
            current_pnl = (position.entry_price - exit_price) * position.volume * 100000

        if current_pnl > position.max_favorable_excursion:
            position.max_favorable_excursion = current_pnl
        if current_pnl < position.max_adverse_excursion:
            position.max_adverse_excursion = current_pnl

    def _update_water_marks(self, position: Position, bid: float, ask: float):
        """Update high/low water marks for the position.

        For longs: high_water_mark = highest price seen, low_water_mark = lowest.
        For shorts: high_water_mark = lowest price seen, low_water_mark = highest.
        """
        if position.direction == TradeDirection.LONG:
            current = bid if bid > 0 else position.current_price
            if position.high_water_mark == 0.0 or current > position.high_water_mark:
                position.high_water_mark = current
            if position.low_water_mark == 0.0 or current < position.low_water_mark:
                position.low_water_mark = current
        else:
            current = ask if ask > 0 else position.current_price
            if position.high_water_mark == 0.0 or current < position.high_water_mark:
                position.high_water_mark = current
            if position.low_water_mark == 0.0 or current > position.low_water_mark:
                position.low_water_mark = current

    def _update_time_in_trade(self, position: Position, now: datetime):
        """Update time-in-trade seconds from opened_at."""
        if position.opened_at:
            if position.opened_at.tzinfo is None:
                opened = position.opened_at.replace(tzinfo=timezone.utc)
            else:
                opened = position.opened_at
            position.time_in_trade_sec = (now - opened).total_seconds()

    # ── Portfolio Summary ──────────────────────────────────────────────────

    def get_portfolio_summary(self) -> dict:
        """Return current portfolio state: total exposure, unrealized PnL, etc."""
        with self._lock:
            open_positions = self._order_manager.get_open_positions()

            total_unrealized_pnl = sum(p.unrealized_pnl for p in open_positions)
            total_notional = sum(
                p.volume * 100000 for p in open_positions
            )
            positions_by_symbol: dict[str, int] = {}
            for p in open_positions:
                positions_by_symbol[p.symbol] = (
                    positions_by_symbol.get(p.symbol, 0) + 1
                )

            largest_position = max(
                (p.volume * 100000 for p in open_positions), default=0.0
            )

            total_mfe = sum(p.max_favorable_excursion for p in open_positions)
            total_mae = sum(p.max_adverse_excursion for p in open_positions)

            return {
                "position_count": len(open_positions),
                "total_unrealized_pnl": round(total_unrealized_pnl, 2),
                "total_notional_exposure": round(total_notional, 2),
                "positions_by_symbol": positions_by_symbol,
                "largest_position_notional": round(largest_position, 2),
                "total_mfe": round(total_mfe, 2),
                "total_mae": round(total_mae, 2),
                "is_killed": (
                    self._kill_switch.is_globally_killed()
                    if self._kill_switch
                    else False
                ),
                "is_frozen": (
                    self._kill_switch.is_globally_frozen()
                    if self._kill_switch
                    else False
                ),
            }

    # ── Position Report ────────────────────────────────────────────────────

    def get_position_report(self, position_id: str) -> dict | None:
        """Detailed report for a single position."""
        position = self._order_manager.get_position(position_id)
        if position is None:
            return None

        return {
            "position_id": position.position_id,
            "symbol": position.symbol,
            "direction": position.direction.value,
            "volume": position.volume,
            "entry_price": position.entry_price,
            "current_price": position.current_price,
            "unrealized_pnl": round(position.unrealized_pnl, 2),
            "max_favorable_excursion (MFE)": round(
                position.max_favorable_excursion, 2
            ),
            "max_adverse_excursion (MAE)": round(
                position.max_adverse_excursion, 2
            ),
            "high_water_mark": position.high_water_mark,
            "low_water_mark": position.low_water_mark,
            "time_in_trade_sec": round(position.time_in_trade_sec, 1),
            "status": position.status.value,
            "stop_loss": position.stop_loss,
            "take_profit": position.take_profit,
            "opened_at": (
                position.opened_at.isoformat() if position.opened_at else None
            ),
        }

    # ── Time Exit ──────────────────────────────────────────────────────────

    def check_time_exits(self) -> list[str]:
        """Return position IDs that have exceeded max trade duration."""
        expired: list[str] = []
        with self._lock:
            open_positions = self._order_manager.get_open_positions()
            for position in open_positions:
                if position.time_in_trade_sec >= self._max_trade_duration_sec:
                    expired.append(position.position_id)
                    logger.info(
                        "Position %s exceeded max duration (%.0fs >= %.0fs)",
                        position.position_id,
                        position.time_in_trade_sec,
                        self._max_trade_duration_sec,
                    )
        return expired

    # ── Drawdown Alerts ────────────────────────────────────────────────────

    def check_drawdown_alerts(
        self,
        warning_threshold: float = 0.02,
        critical_threshold: float = 0.05,
    ) -> list[dict]:
        """Check per-position drawdown from MFE against thresholds.

        Drawdown from MFE = (MFE - current_unrealized) / |MFE| if MFE > 0
        If MFE <= 0, drawdown is measured from entry (unrealized loss).

        Returns list of alert dicts with position_id, level, drawdown, message.
        """
        alerts: list[dict] = []
        with self._lock:
            open_positions = self._order_manager.get_open_positions()
            for position in open_positions:
                mfe = position.max_favorable_excursion
                current_pnl = position.unrealized_pnl

                if mfe > 0:
                    # Give-back from peak favorable excursion
                    drawdown = (mfe - current_pnl) / mfe if mfe != 0 else 0.0
                else:
                    # Never been in profit — measure adverse excursion
                    drawdown = 0.0
                    if position.max_adverse_excursion < 0:
                        # Express as fraction of notional
                        notional = position.volume * 100000
                        if notional > 0:
                            drawdown = abs(
                                position.max_adverse_excursion
                            ) / notional

                if drawdown >= critical_threshold:
                    alert = {
                        "position_id": position.position_id,
                        "symbol": position.symbol,
                        "level": "critical",
                        "drawdown": round(drawdown, 4),
                        "mfe": round(mfe, 2),
                        "current_pnl": round(current_pnl, 2),
                        "message": (
                            f"CRITICAL drawdown {drawdown:.1%} on {position.symbol} "
                            f"(MFE={mfe:.2f}, current={current_pnl:.2f})"
                        ),
                    }
                    alerts.append(alert)
                    self._trigger_callbacks("on_drawdown_critical", alert)
                elif drawdown >= warning_threshold:
                    alert = {
                        "position_id": position.position_id,
                        "symbol": position.symbol,
                        "level": "warning",
                        "drawdown": round(drawdown, 4),
                        "mfe": round(mfe, 2),
                        "current_pnl": round(current_pnl, 2),
                        "message": (
                            f"WARNING drawdown {drawdown:.1%} on {position.symbol} "
                            f"(MFE={mfe:.2f}, current={current_pnl:.2f})"
                        ),
                    }
                    alerts.append(alert)
                    self._trigger_callbacks("on_drawdown_warning", alert)

        # Kill switch: check portfolio-level drawdown
        self._check_portfolio_drawdown_kill()

        return alerts

    def _check_portfolio_drawdown_kill(self):
        """Activate kill switch FREEZE if portfolio unrealized drawdown breaches limits."""
        if self._kill_switch is None or self._risk_guard is None:
            return

        # Use risk_guard's drawdown calculation
        drawdown_pct = self._risk_guard.current_drawdown_pct
        if drawdown_pct >= self._risk_guard._config.total_drawdown_limit_pct:
            if not self._kill_switch.is_active():
                logger.critical(
                    "Portfolio drawdown %.2f%% >= limit %.2f%% — activating FREEZE",
                    drawdown_pct * 100,
                    self._risk_guard._config.total_drawdown_limit_pct * 100,
                )
                self._kill_switch.activate_global_freeze(
                    reason="portfolio_drawdown_breach",
                    triggered_by="position_monitor",
                )

    # ── Background Monitoring Thread ───────────────────────────────────────

    def start_monitoring(self):
        """Start background monitoring thread."""
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            logger.warning("Position monitor already running")
            return

        self._stop_monitor.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="position-monitor",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info(
            "Position monitor started (interval=%.1fs, max_duration=%.0fs)",
            self._check_interval_sec,
            self._max_trade_duration_sec,
        )

    def stop_monitoring(self):
        """Stop background monitoring thread."""
        if self._monitor_thread is None:
            return

        self._stop_monitor.set()
        self._monitor_thread.join(timeout=10.0)
        self._monitor_thread = None
        logger.info("Position monitor stopped")

    def _monitor_loop(self):
        """Background loop: periodically check time exits and drawdown alerts."""
        while not self._stop_monitor.wait(self._check_interval_sec):
            try:
                # Check time-based exits
                expired = self.check_time_exits()
                for pid in expired:
                    self._trigger_callbacks("on_time_exit", pid)

                # Check drawdown alerts
                self.check_drawdown_alerts()

            except Exception as exc:
                logger.error("Position monitor loop error: %s", exc, exc_info=True)

    # ── Callback Registration ──────────────────────────────────────────────

    def register_callback(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callbacks(self, event: str, *args, **kwargs):
        if event in self._callbacks:
            for callback in self._callbacks[event]:
                try:
                    callback(*args, **kwargs)
                except Exception as exc:
                    logger.error("Callback error for %s: %s", event, exc)
