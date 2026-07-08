"""Production forward test runner wiring the full Ayumi signal pipeline."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from common.logging_config import setup_logging
from confidence.engine import ConfidenceEngine
from confidence.gates import GateConfig
from orchestrator.signal_orchestrator import (
    OrchestratedOrder,
    OrchestratorTradeSignal,
    SignalOrchestrator,
)
from orchestrator.strategy_adapter import StrategyAdapter
from risk.profile_router import ProfileRouter
from risk.sl_position_sizer import SLPositionSizer
from risk.regime_thresholds import Regime, RegimeAwareThresholds
from risk.edge_telemetry import EdgeTelemetryTracker
from risk.state_persistence import StatePersistence
# Import the canonical CET date helper from ftmo_guard — do NOT duplicate it.
# The daily reset boundary is FTMO-defined: CET midnight, not UTC midnight.
from risk.ftmo_guard import _cet_date

logger = logging.getLogger("ayumi.forward_test")


class BlendForwardTestRunner:
    """Production forward test runner wiring the full Ayumi signal pipeline.

    Wires: confidence engine → profile router → position sizer → orchestrator.
    Handles state persistence across restarts via StatePersistence.

    Supports registering ISignalStrategy instances (e.g. TTCXAUUSDStrategy)
    which are evaluated on each bar and routed through the blend pipeline.
    """
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

        # Phase 4: Regime-aware risk sizing
        self._regime_thresholds = RegimeAwareThresholds()
        self._current_regime: Regime = Regime.STABLE
        self._regime_history: list = []

        # Phase 4.2: Edge telemetry (R-multiple expectancy per strategy × symbol)
        self._edge_tracker = EdgeTelemetryTracker()

        # State persistence
        self._persistence = StatePersistence(
            state_path=config.get("state_path", "data/risk_state.json"),
        )

        # Registered strategies (ISignalStrategy instances)
        self._strategies: list = []

        # Track open positions for fill handling
        self._open_positions: dict[str, dict] = {}
        self._current_day: Optional[str] = None

        # Phase 6A: position_id → signal_id mapping for close() wiring.
        # Populated by register_position_mapping() when the engine links
        # a PaperTrader position_id to the blend_runner's signal_id.
        self._position_id_to_signal_id: dict[str, str] = {}

    def start(self) -> None:
        """Initialize all components, restore state, start logging."""
        self._persistence.restore(self._sizer)
        self._balance = self._sizer.account_balance
        self._orchestrator.update_balance(self._balance)
        logger.info(
            "BlendForwardTestRunner started — balance=$%.2f", self._balance,
        )

    def _check_daily_reset(self, timestamp: datetime) -> None:
        """Reset daily risk cap on day boundaries.

        Uses the CET date (FTMO spec) — not the timestamp's naive date — so
        that the daily budget rolls over at CET midnight regardless of which
        timezone the timestamp is recorded in.
        """
        cet_day = _cet_date(timestamp)
        if self._current_day and cet_day != self._current_day:
            pre_daily = self._sizer._daily_risk_used
            pre_open = self._sizer.open_risk
            positions_carried = len(self._sizer.open_positions)
            self._sizer.reset_daily(cet_date=cet_day)
            logger.info(
                "Daily risk cap reset — new CET day: %s (daily_used=%.2f→0.00, "
                "open_risk=%.2f, positions_carried=%d)",
                cet_day, pre_daily, pre_open, positions_carried,
            )
        self._current_day = cet_day

    def daily_reset(self, now: Optional[datetime] = None) -> None:
        """Public daily reset — safe to call from engine scheduler.

        Logs pre-reset and post-reset values so operators can verify
        the daily counter was zeroed while open positions are carried over.
        Uses the CET date (FTMO spec) so the rollover boundary matches
        :meth:`_check_daily_reset` and ``FTMOGuard``.
        """
        sizer = self._sizer
        pre_daily = sizer._daily_risk_used
        pre_open = sizer.open_risk
        positions_carried = len(sizer.open_positions)
        if now is None:
            now = datetime.now(timezone.utc)
        cet_day = _cet_date(now)
        sizer.reset_daily(cet_date=cet_day)
        self._current_day = cet_day
        logger.info(
            "Daily risk reset: daily_used=%.2f→0.00, open_risk=%.2f, "
            "positions_carried=%d, cet_day=%s",
            pre_daily, pre_open, positions_carried, cet_day,
        )

    def make_signal_id(self, signal: OrchestratorTradeSignal) -> str:
        """Build the canonical signal_id used by on_signal() to register
        a position with the sizer.

        Public helper so callers (launcher, engine, scripts) can use
        the SAME identity for cancel/close without duplicating the
        construction pattern.  Previously each caller built the id
        independently and could drift out of sync.
        """
        return signal.strategy_id + "_" + str(signal.timestamp.timestamp())

    def register_strategy(self, strategy) -> None:
        """Register an ISignalStrategy (e.g. TTCXAUUSDStrategy) for evaluation.

        Registered strategies are evaluated on each bar via evaluate_bars().
        When a strategy produces a signal, it is routed through on_signal().
        """
        self._strategies.append(strategy)
        logger.info("Strategy registered: %s", getattr(strategy, 'name', type(strategy).__name__))

    def evaluate_bars(self, bars: list, latest_bar=None) -> list:
        """Evaluate all registered strategies on the latest bar data.

        Args:
            bars: List of bar objects (must have .time, .open, .high, .low, .close).
            latest_bar: The most recent bar (optional, defaults to bars[-1]).

        Returns:
            List of OrchestratedOrder results for signals that were generated.
        """
        orders = []
        if not self._strategies:
            return orders

        bar = latest_bar or (bars[-1] if bars else None)
        if not bar:
            return orders

        # Phase 4: Update market regime from recent bars
        self.update_regime(bars)

        # Build a simple state object that strategies can evaluate
        state = type('BarState', (), {
            'bars': bars,
            'latest_bar': bar,
            'symbol': getattr(bar, 'symbol', 'XAUUSD'),
        })()

        for strategy in self._strategies:
            try:
                result = strategy.evaluate(state)
            except Exception as exc:
                logger.warning(
                    "Strategy %s raised during evaluate: %s",
                    getattr(strategy, 'name', '?'), exc,
                )
                continue

            if result is None:
                continue

            # Convert strategy result to signal_data dict for on_signal
            signal_data = self._strategy_result_to_dict(result, bar)
            if signal_data is None:
                continue

            strategy_id = getattr(strategy, 'name', strategy.__class__.__name__)
            order = self.on_signal(strategy_id, signal_data)
            orders.append(order)

        return orders

    @staticmethod
    def _strategy_result_to_dict(result, bar) -> dict | None:
        """Convert a strategy evaluate() result to a signal_data dict.

        Handles common result types: dict, dataclass, or object with attributes.
        """
        if result is None:
            return None

        # Extract spread from bar (core.types.Bar has spread_pips)
        bar_spread = getattr(bar, 'spread_pips', 0.0)

        if isinstance(result, dict):
            # Ensure spread is present; bar value is the fallback
            if 'spread' not in result:
                result['spread'] = bar_spread
            return result

        # Try dataclass-style or object attribute access
        as_dict = {}
        for key in ('symbol', 'direction', 'entry_price', 'stop_loss',
                     'take_profit', 'confidence'):
            val = getattr(result, key, None)
            if val is not None:
                as_dict[key] = val

        # Fall back to bar values for required fields
        as_dict.setdefault('symbol', getattr(bar, 'symbol', 'XAUUSD'))
        as_dict.setdefault('direction', getattr(result, 'direction', 'LONG'))
        as_dict.setdefault('entry_price', getattr(bar, 'close', 0.0))
        as_dict.setdefault('stop_loss', getattr(result, 'stop_loss', 0.0))
        as_dict.setdefault('take_profit', getattr(result, 'take_profit', 0.0))
        as_dict.setdefault('confidence', getattr(result, 'confidence', 0.5))

        # Always include spread so downstream gates receive actual data
        as_dict.setdefault('spread', bar_spread)

        if not as_dict.get('entry_price') or not as_dict.get('stop_loss'):
            return None

        return as_dict

    def update_regime(self, bars: list) -> None:
        """Classify current market regime from recent bars (ATR-based heuristic).

        Simple volatility-based detection:
        - Compute recent range (high-low) as proxy for ATR
        - Compare to rolling mean: if current > 2x mean → BREAKDOWN
        - If between 1x and 2x → TRANSITION
        - Below 1x → STABLE
        """
        if len(bars) < 20:
            return  # Not enough data

        recent = bars[-20:]
        ranges = [getattr(b, 'high', 0) - getattr(b, 'low', 0) for b in recent]
        if not ranges or max(ranges) == 0:
            return

        current_range = ranges[-1]
        avg_range = sum(ranges) / len(ranges)
        if avg_range == 0:
            return

        ratio = current_range / avg_range
        if ratio >= 2.0:
            new_regime = Regime.BREAKDOWN
        elif ratio >= 1.5:
            new_regime = Regime.TRANSITION
        else:
            new_regime = Regime.STABLE

        if new_regime != self._current_regime:
            logger.info(
                "Regime shift: %s → %s (range ratio %.2f)",
                self._current_regime.value, new_regime.value, ratio,
            )
            self._current_regime = new_regime
            self._regime_history.append((new_regime.value, ratio))

    def on_signal(self, strategy_id: str, signal_data: dict) -> OrchestratedOrder:
        """Handle incoming strategy signal through full pipeline."""
        signal = self._adapter.adapt_signal(strategy_id, signal_data)
        self._check_daily_reset(signal.timestamp)
        order = self._orchestrator.process_signal(signal)

        if not order.rejected:
            # Phase 4: Apply regime-aware exposure multiplier
            exposure_mult = self._regime_thresholds.get_exposure_multiplier(self._current_regime)

            # Phase 4.2: Apply edge-based risk multiplier
            edge_mult = self._edge_tracker.get_risk_multiplier(strategy_id, signal.symbol)

            combined_mult = exposure_mult * edge_mult
            if combined_mult < 1.0:
                order.risk_amount *= combined_mult
                order.lots *= combined_mult
                logger.info(
                    "Regime+edge sizing: %s %.0f%% × %.1f%% = %.0f%% exposure (risk=$%.2f lots=%.4f)",
                    self._current_regime.value, exposure_mult * 100, edge_mult * 100,
                    combined_mult * 100, order.risk_amount, order.lots,
                )
            elif edge_mult > 1.0:
                order.risk_amount *= edge_mult
                order.lots *= edge_mult
                logger.info(
                    "Edge sizing: %.1fx multiplier (high edge, risk=$%.2f lots=%.4f)",
                    edge_mult, order.risk_amount, order.lots,
                )

            # Register position tracking under a unique signal_id
            signal_id = self.make_signal_id(signal)
            self._open_positions[signal_id] = {
                "order": order,
                "risk_amount": order.risk_amount,
            }
            self._sizer.register(signal_id, order.risk_amount)
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

    def cancel_risk(self, signal_id: str, risk_amount: float) -> None:
        """Free risk budget when a sized order is rejected downstream."""
        self._sizer.cancel(signal_id)
        logger.info(
            "Risk cancelled: signal_id=%s risk=$%.2f freed, daily remaining=$%.2f",
            signal_id, risk_amount, self._sizer.daily_risk_remaining,
        )

    def register_position_mapping(self, position_id: str, signal_id: str) -> None:
        """Map a PaperTrader position_id to the blend_runner's signal_id.

        Called by the engine when a trade is executed, so that
        :meth:`close_position` can resolve the correct signal_id when
        the PaperTrader fires ``on_position_closed`` with a position_id.
        """
        self._position_id_to_signal_id[position_id] = signal_id

    def on_fill(self, order_id: str, fill_price: float, pnl: float) -> None:
        """Handle position fill/close — update sizer state and persist.

        Args:
            order_id: The signal_id used when registering the position
                      (``strategy_id + "_" + timestamp``).
            fill_price: Closing price (used for logging only).
            pnl: Realized PnL from the close.
        """
        pos = self._open_positions.pop(order_id, None)

        # Also clean up any position_id mapping pointing to this signal_id
        self._position_id_to_signal_id.pop(order_id, None)

        try:
            self._sizer.close(order_id, pnl)
        except KeyError:
            if pos is not None:
                # Restore the popped entry so a retry can find it
                self._open_positions[order_id] = pos
            logger.warning("on_fill: signal_id %s not registered in sizer", order_id)
            return

        self._balance = self._sizer.account_balance
        self._orchestrator.update_balance(self._balance)

        symbol = pos["order"].signal.symbol if pos else "unknown"
        strategy_id = pos["order"].signal.strategy_id if pos else "unknown"
        risk_amount = pos["risk_amount"] if pos else 0.0
        logger.info(
            "Position closed: signal_id=%s symbol=%s pnl=%.2f open_risk=%.2f",
            order_id, symbol, pnl, self._sizer.open_risk,
        )

        # Phase 4.2: Record edge telemetry
        if strategy_id != "unknown" and risk_amount > 0:
            self._edge_tracker.record_close(
                strategy_id=strategy_id,
                symbol=symbol,
                risk_amount=risk_amount,
                pnl=pnl,
                signal_id=order_id,
            )

        # Persist state after fill
        self._persistence.save(self._sizer)

    def close_position(self, position_id: str, pnl: float) -> None:
        """Close a position by its position_id, resolving the signal_id.

        This is the primary close entry point for the engine, which tracks
        positions by their PaperTrader-assigned ``position_id``.  The
        mapping from ``position_id`` to ``signal_id`` is established via
        :meth:`register_position_mapping` when the trade is first opened.

        Falls back to using ``position_id`` directly as the signal_id if
        no mapping exists (backward-compat for tests / direct callers).
        """
        signal_id = self._position_id_to_signal_id.pop(position_id, None)
        if signal_id is None:
            # No mapping registered — fall back to using position_id as-is
            signal_id = position_id

        self.on_fill(signal_id, fill_price=0.0, pnl=pnl)

    def stop(self) -> None:
        """Persist state and shutdown cleanly."""
        self._persistence.save(self._sizer)
        logger.info("BlendForwardTestRunner stopped — balance=$%.2f", self._balance)
