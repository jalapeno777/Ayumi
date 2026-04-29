"""Production forward test runner wiring the full Ayumi signal pipeline."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from common.logging_config import setup_logging
from confidence.engine import ConfidenceEngine, ConfidenceResult
from confidence.gates import GateConfig
from orchestrator.signal_orchestrator import (
    OrchestratedOrder,
    SignalOrchestrator,
    TradeSignal,
)
from orchestrator.strategy_adapter import StrategyAdapter
from risk.profile_router import ProfileRouter
from risk.sl_position_sizer import SLPositionSizer
from risk.state_persistence import StatePersistence

logger = logging.getLogger("ayumi.forward_test")


class BlendForwardTestRunner:
    """Production forward test runner wiring the full Ayumi signal pipeline.

    Wires: confidence engine → profile router → position sizer → orchestrator.
    Handles state persistence across restarts via StatePersistence.
    """

    def __init__(self, config: dict):
        """
        config keys:
        - account_balance: float
        - risk_per_trade_pct: float (default 0.005)
        - daily_risk_cap_pct: float (default 0.03)
        - max_sniper: int (default 3)
        - max_swarm: int (default 5)
        - spread_pips: dict per symbol
        - atr_cache_path: str
        - state_path: str
        - log_level: str
        """
        self._config = config
        self._balance = config["account_balance"]

        # Setup logging
        setup_logging(level=config.get("log_level", "INFO"))

        # Build pipeline components
        spread_pips = config.get("spread_pips", {})
        gate_config = GateConfig(
            default_max_spread=2.0,
            symbol_max_spreads=spread_pips,
        )
        self._engine = ConfidenceEngine(gate_config)

        self._router = ProfileRouter(
            sniper_threshold=0.70,
            swarm_threshold=0.40,
            max_sniper=config.get("max_sniper", 3),
            max_swarm=config.get("max_swarm", 5),
        )

        self._sizer = SLPositionSizer(
            account_balance=self._balance,
            risk_per_trade_pct=config.get("risk_per_trade_pct", 0.005),
            daily_risk_cap_pct=config.get("daily_risk_cap_pct", 0.03),
        )

        self._adapter = StrategyAdapter()
        self._orchestrator = SignalOrchestrator(
            confidence_engine=self._engine,
            profile_router=self._router,
            position_sizer=self._sizer,
            account_balance=self._balance,
        )

        # State persistence
        self._persistence = StatePersistence(
            state_path=config.get("state_path", "data/risk_state.json"),
        )

        # Track open positions for fill handling
        self._open_positions: dict[str, dict] = {}
        self._current_day: Optional[str] = None

    def start(self) -> None:
        """Initialize all components, restore state, start logging."""
        self._persistence.restore(self._sizer)
        self._balance = self._sizer.account_balance
        self._orchestrator.update_balance(self._balance)
        logger.info(
            "BlendForwardTestRunner started — balance=$%.2f", self._balance,
        )

    def _check_daily_reset(self, timestamp: datetime) -> None:
        """Reset daily risk cap on day boundaries."""
        day_str = timestamp.strftime("%Y-%m-%d")
        if self._current_day and day_str != self._current_day:
            self._sizer.reset_daily()
            logger.info("Daily risk cap reset — new day: %s", day_str)
        self._current_day = day_str

    def on_signal(self, strategy_id: str, signal_data: dict) -> OrchestratedOrder:
        """Handle incoming strategy signal through full pipeline."""
        signal = self._adapter.adapt_signal(strategy_id, signal_data)
        self._check_daily_reset(signal.timestamp)
        order = self._orchestrator.process_signal(signal)

        if not order.rejected:
            # Register position tracking
            self._open_positions[order.signal.strategy_id + "_" + str(signal.timestamp.timestamp())] = {
                "order": order,
                "risk_amount": order.risk_amount,
            }
            self._sizer.register_open_position(order.risk_amount)
            logger.info(
                "Order accepted: %s %s %.4f lots risk=$%.2f",
                signal.symbol, signal.direction, order.lots, order.risk_amount,
            )
        else:
            logger.info(
                "Order rejected: %s — %s",
                signal.symbol, order.rejection_reason,
            )

        return order

    def on_fill(self, order_id: str, fill_price: float, pnl: float) -> None:
        """Handle position fill/close — update sizer state and persist."""
        pos = self._open_positions.pop(order_id, None)
        if pos is None:
            logger.warning("on_fill: unknown order_id %s", order_id)
            return

        order = pos["order"]
        risk_amount = pos["risk_amount"]
        win = pnl > 0

        self._sizer.close_position(pnl, risk_amount, win)
        self._balance = self._sizer.account_balance
        self._orchestrator.update_balance(self._balance)

        logger.info(
            "Fill: %s pnl=$%.2f balance=$%.2f",
            order.signal.symbol, pnl, self._balance,
        )

        # Persist state after fill
        self._persistence.save(self._sizer)

    def stop(self) -> None:
        """Persist state and shutdown cleanly."""
        self._persistence.save(self._sizer)
        logger.info("BlendForwardTestRunner stopped — balance=$%.2f", self._balance)
