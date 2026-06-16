#!/usr/bin/env python3
"""Forward Test Launcher v2 — built on the new cTrader infrastructure modules.

Replaces launch_blend_forward_test.py with a clean architecture:
    CredentialStore → TokenLifecycle → cTraderSession → MarketDataFeed
    → strategies → blend runner → OrderGateway → PositionTracker
    → HealthMonitor

Key fixes over the old launcher:
    1. Volume computed from actual lotSize queried via ProtoOASymbolByIdReq
    2. Token refresh via single TokenLifecycle path (no competing refreshers)
    3. Order execution via OrderGateway with explicit FILLED/REJECTED/TIMEOUT
    4. Structured file logging via logging_config.setup_logging()
    5. Health monitoring via HealthMonitor ([B5 Health] / [S1 Health] tags)

The old launch_blend_forward_test.py remains untouched as a fallback.

Reference: BQ-1043 Phase 4b — Engine Refactor (Point of No Return)
"""

from __future__ import annotations

import argparse
import logging
import os
import signal as sig_module
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Path setup ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "forex-bot"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ── Domain layer imports (reused, not reimplemented) ────────────────────────

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from backtest.engine import MarketState
from core.types import BarPeriod

# Strategies — same 9 as the old launcher
from strategies.srmr_plus import SRMRPlusStrategy, SRMRPlusConfig
from strategies.killzone_momentum import KillzoneMomentumStrategy, KillzoneMomentumConfig
from strategies.momentum import DonchianBreakoutStrategy, MomentumConfig
from strategies.session_range_mean_reversion import (
    SessionRangeMeanReversionStrategy,
    SessionRangeMRConfig,
)
from strategies.bb_rsi_reversion import BBRSIMeanReversion, BBRSIConfig
from strategies.rsi_threshold import SimpleRSIThresholdStrategy, RSIThresholdConfig
from strategies.session_breakout import SessionBreakoutStrategy

# Blend runner + correlation gate (domain layer)
from forward_test.blend_runner import BlendForwardTestRunner

# Old models for TradeSignal (used by strategies)
from adapters.ctrader.models import TradeSignal, TradeDirection

# ── New infrastructure imports ──────────────────────────────────────────────

from common.logging_config import setup_logging
from adapters.ctrader.credential_store import CredentialStore
from adapters.ctrader.token_lifecycle import TokenLifecycle
from adapters.ctrader.session import cTraderSession
from adapters.ctrader.market_data_feed import MarketDataFeed
from adapters.ctrader.execution_event_handler import ExecutionEventHandler
from adapters.ctrader.order_gateway import OrderGateway
from adapters.ctrader.position_tracker import PositionTracker
from adapters.ctrader.protocols import OrderStatus, TradeSide
from engine.health_monitor import HealthMonitor

logger = logging.getLogger("ayumi.launch_v2")


# ── Constants ───────────────────────────────────────────────────────────────

# Known symbol IDs on demo account (fallback if symbol lookup fails)
_DEFAULT_SYMBOL_IDS: dict[str, int] = {
    "GBPUSD": 2,
    "USDJPY": 3,
    "EURUSD": 1,
}

# Strategy → bar period minutes (same as old launcher)
STRATEGY_TIMEFRAMES: dict[str, int] = {
    "SRMR+": 60,
    "Killzone Momentum": 15,
    "Donchian Channel Breakout": 15,
    "Session-Range Mean Reversion": 60,
    "BB+RSI Mean Reversion": 60,
    "Session Breakout London": 15,
    "Session Breakout NY": 15,
    "Session Breakout Asian": 15,
    "Simple RSI Threshold": 15,
}

# Strategy class → blend runner ID
STRATEGY_ID_MAP: dict[str, str] = {
    "SRMR+": "srmr_plus",
    "Killzone Momentum": "killzone_momentum",
    "Donchian Channel Breakout": "momentum",
    "Session-Range Mean Reversion": "session_range_mr",
    "BB+RSI Mean Reversion": "bb_rsi_reversion",
    "Session Breakout London": "session_breakout_london",
    "Session Breakout NY": "session_breakout_ny",
    "Session Breakout Asian": "session_breakout_asian",
    "Simple RSI Threshold": "rsi_threshold",
}


# ── Volume conversion (CRITICAL FIX) ────────────────────────────────────────

def lots_to_volume(lots: float, lot_size: int) -> int:
    """Convert lots to raw cTrader volume units.

    The cTrader Open API volume field is NOT in lots. It is in units of
    the base asset, scaled by the symbol's lotSize field.

    For demo account 46877902 (GBPUSD lotSize=10,000,000):
        0.01 lots → 100,000 raw volume

    Formula: raw_volume = lots × lotSize

    Verified on 2026-06-16: volume=100000 for 0.01 lots FILLED.

    Reference: docs/diagnoses/ctrader-integration-findings-2026-06-16.md
    """
    return int(lots * lot_size)


# ── Correlation Gate (reused from old launcher) ─────────────────────────────

class CorrelationGate:
    """Blocks duplicate symbol-direction signals — max 1 position per (symbol, direction)."""

    def __init__(self):
        self._active: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def check(self, symbol: str, direction: str, strategy_id: str) -> tuple[bool, str]:
        key = (symbol.upper(), direction.upper())
        with self._lock:
            existing = self._active.get(key)
            if existing:
                return False, f"correlation_block: {existing} already holds {symbol}/{direction}"
            self._active[key] = strategy_id
            return True, ""

    def release(self, symbol: str, direction: str):
        key = (symbol.upper(), direction.upper())
        with self._lock:
            self._active.pop(key, None)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)


# ── Symbol spec query ───────────────────────────────────────────────────────

def query_symbol_specs(
    session: cTraderSession,
    account_id: int,
    symbol_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """Query cTrader for symbol specifications (lotSize, minVolume, stepVolume).

    Sends ProtoOASymbolByIdReq for each symbol ID and extracts the key
    trading parameters.

    Returns:
        Dict mapping symbol_id → {"lotSize": int, "minVolume": int, "stepVolume": int, ...}
    """
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolByIdReq

    specs: dict[int, dict[str, Any]] = {}

    for sym_id in symbol_ids:
        req = ProtoOASymbolByIdReq()
        req.ctidTraderAccountId = account_id
        req.symbolId.append(sym_id)

        try:
            response = session.send(req, f"symbol_spec_{sym_id}", timeout=15.0)
            if response is None:
                logger.error("Symbol spec query timed out for symbol_id=%d", sym_id)
                continue

            # Extract the payload
            from ctrader_open_api.protobuf import Protobuf
            payload = Protobuf.extract(response)

            symbol_info = getattr(payload, "symbol", [None])
            if symbol_info:
                sym = symbol_info[0]
                specs[sym_id] = {
                    "lotSize": getattr(sym, "lotSize", 100_000),
                    "minVolume": getattr(sym, "minVolume", 1),
                    "stepVolume": getattr(sym, "stepVolume", 1),
                    "digits": getattr(sym, "digits", 5),
                    "pipSize": getattr(sym, "pipSize", 0.0001),
                }
                logger.info(
                    "Symbol spec: id=%d lotSize=%d minVolume=%d stepVolume=%d",
                    sym_id,
                    specs[sym_id]["lotSize"],
                    specs[sym_id]["minVolume"],
                    specs[sym_id]["stepVolume"],
                )
            else:
                logger.warning("No symbol info in response for symbol_id=%d", sym_id)

        except Exception as exc:
            logger.error("Failed to query symbol spec for id=%d: %s", sym_id, exc)

    return specs


# ── Strategy builder (reused from old launcher) ─────────────────────────────

def build_strategies() -> list:
    """Build the same 9 strategies as the old launcher."""
    return [
        SRMRPlusStrategy(config=SRMRPlusConfig()),
        KillzoneMomentumStrategy(config=KillzoneMomentumConfig()),
        DonchianBreakoutStrategy(momentum=MomentumConfig()),
        SessionRangeMeanReversionStrategy(config=SessionRangeMRConfig()),
        BBRSIMeanReversion(config=BBRSIConfig()),
        SessionBreakoutStrategy({
            "name": "Session Breakout London",
            "range_start_hour": 0, "range_end_hour": 8,
            "trade_start_hour": 8, "trade_end_hour": 12,
            "min_range_pips": 30, "max_range_pips": 80,
            "buffer_pips": 3, "sl_atr_multiplier": 2.0,
            "atr_period": 14, "min_range_bars": 20,
        }),
        SessionBreakoutStrategy({
            "name": "Session Breakout NY",
            "range_start_hour": 8, "range_end_hour": 13,
            "trade_start_hour": 13, "trade_end_hour": 17,
            "min_range_pips": 25, "max_range_pips": 70,
            "buffer_pips": 3, "sl_atr_multiplier": 1.8,
            "atr_period": 14, "min_range_bars": 20,
        }),
        SessionBreakoutStrategy({
            "name": "Session Breakout Asian",
            "range_start_hour": 21, "range_end_hour": 0,
            "trade_start_hour": 0, "trade_end_hour": 6,
            "min_range_pips": 20, "max_range_pips": 60,
            "buffer_pips": 3, "sl_atr_multiplier": 1.5,
            "atr_period": 14, "min_range_bars": 20,
        }),
        SimpleRSIThresholdStrategy(config=RSIThresholdConfig()),
    ]


def build_blend_runner() -> BlendForwardTestRunner:
    """Build the blend forward test runner with the same config as old launcher."""
    config = {
        "account_balance": 10_000.0,
        "risk_per_trade_pct": 0.005,
        "daily_risk_cap_pct": 0.05,
        "max_sniper": 3,
        "max_swarm": 5,
        "spread_pips": {"GBPUSD": 2.0, "EURUSD": 0.8},
        "atr_cache_path": "data/atr_cache.json",
        "state_path": "data/risk_state_blend.json",
        "log_level": "INFO",
    }
    runner = BlendForwardTestRunner(config)
    runner.start()
    return runner


# ── Signal conversion ───────────────────────────────────────────────────────

def trade_signal_to_blend_dict(signal: TradeSignal, strategy_name: str) -> dict:
    """Convert cTrader TradeSignal to the dict format BlendForwardTestRunner.on_signal() expects."""
    return {
        "symbol": signal.symbol,
        "direction": signal.direction.value if hasattr(signal.direction, "value") else str(signal.direction),
        "entry_price": signal.entry_price,
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit_1 or 0.0,
        "confidence": signal.confidence,
        "timestamp": datetime.now(timezone.utc),
    }


# ── V2 Forward Test Engine ──────────────────────────────────────────────────

class ForwardTestV2:
    """Evaluation loop using new infrastructure modules.

    Receives ticks from MarketDataFeed, builds bars, evaluates strategies,
    routes signals through blend runner → OrderGateway.
    """

    def __init__(
        self,
        session: cTraderSession,
        market_data_feed: MarketDataFeed,
        order_gateway: OrderGateway,
        position_tracker: PositionTracker,
        execution_event_handler: ExecutionEventHandler,
        health_monitor: HealthMonitor,
        blend_runner: BlendForwardTestRunner,
        correlation_gate: CorrelationGate,
        strategies: list,
        symbol_id_map: dict[str, int],
        symbol_specs: dict[int, dict[str, Any]],
        live_mode: bool = False,
    ):
        self._session = session
        self._feed = market_data_feed
        self._gateway = order_gateway
        self._tracker = position_tracker
        self._event_handler = execution_event_handler
        self._health = health_monitor
        self._blend = blend_runner
        self._corr_gate = correlation_gate
        self._strategies = strategies
        self._symbol_id_map = symbol_id_map
        self._symbol_specs = symbol_specs
        self._live_mode = live_mode

        # Bar tracking (per symbol per timeframe)
        self._bar_buffers: dict[str, list] = {}
        self._forming_bars: dict[str, Any] = {}
        self._lock = threading.Lock()

        # Stats
        self._ticks_received = 0
        self._bars_built = 0
        self._signals_generated = 0
        self._signals_accepted = 0
        self._signals_rejected = 0
        self._live_fills = 0
        self._paper_trades = 0
        self._running = False

        # Strategy eval counters for [S1 Health]
        self._strategy_evals: dict[str, int] = {}
        self._strategy_no_signal: dict[str, int] = {}
        self._strategy_last_eval: dict[str, float] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def ticks_received(self) -> int:
        return self._ticks_received

    @property
    def bars_built(self) -> int:
        return self._bars_built

    @property
    def ticks_per_second(self) -> float:
        return 0.0  # computed in health loop if needed

    @property
    def signals_generated(self) -> int:
        return self._signals_generated

    @property
    def paper_trades(self) -> int:
        return self._paper_trades

    @property
    def live_fills(self) -> int:
        return self._live_fills

    @property
    def balance(self) -> float:
        return getattr(self._blend, "_balance", 10_000.0)

    @property
    def open_positions(self) -> int:
        return len(self._tracker.get_open_positions())

    @property
    def pending_orders(self) -> int:
        return 0

    @property
    def state(self) -> str:
        return str(self._session.state)

    def start(self) -> None:
        """Register listeners and start the evaluation loop."""
        self._feed.add_tick_listener(self._on_tick)
        self._feed.add_bar_listener(self._on_bar)
        self._running = True
        logger.info("ForwardTestV2 evaluation loop started")

    def stop(self) -> None:
        """Stop the evaluation loop."""
        self._running = False
        logger.info("ForwardTestV2 evaluation loop stopped")

    def _on_tick(self, tick) -> None:
        """Called on every incoming tick from MarketDataFeed."""
        self._ticks_received += 1

        # Update position tracker prices
        self._tracker.update_prices({tick.symbol: tick.mid})

    def _on_bar(self, bar) -> None:
        """Called when a bar closes from MarketDataFeed."""
        with self._lock:
            buf = self._bar_buffers.setdefault(bar.symbol, [])
            buf.append(bar)
            if len(buf) > 500:
                buf = buf[-500:]
                self._bar_buffers[bar.symbol] = buf
            self._bars_built += 1

        # Evaluate strategies on bar close
        self._evaluate_strategies(bar.symbol)

    def _evaluate_strategies(self, symbol: str) -> None:
        """Evaluate all strategies for the given symbol on bar close.

        Uses the same pattern as the old BlendForwardTestEngine: build a
        MarketState from buffered bars, call each strategy's evaluate method,
        route signals through correlation gate → blend runner → OrderGateway.
        """
        bars = self._bar_buffers.get(symbol, [])
        if len(bars) < 20:
            return

        for strategy in self._strategies:
            sname = strategy.name
            strategy_id = STRATEGY_ID_MAP.get(sname, sname.lower().replace(" ", "_"))

            # Per-strategy eval counter
            self._strategy_evals[sname] = self._strategy_evals.get(sname, 0) + 1
            self._strategy_last_eval[sname] = time.monotonic()

            try:
                # Build MarketState from bars
                state = MarketState(bars=list(bars))

                # Evaluate strategy — use its evaluate method
                result = strategy.evaluate(state)
            except Exception as exc:
                logger.error("Strategy %s evaluation error: %s", sname, exc, exc_info=True)
                continue

            if result is None:
                self._strategy_no_signal[sname] = self._strategy_no_signal.get(sname, 0) + 1
                continue

            # Convert strategy signal to TradeSignal
            signal = self._convert_signal(result, symbol, sname)
            if signal is None:
                continue

            self._signals_generated += 1
            self._route_signal(signal, sname, strategy_id)

    def _convert_signal(self, strategy_signal, symbol: str, strategy_name: str) -> TradeSignal | None:
        """Convert a strategy's signal to a TradeSignal.

        Strategy signals may be StrategySignal or TradeSignal objects.
        """
        # Handle StrategySignal from backtest.engine
        if hasattr(strategy_signal, "direction"):
            direction = strategy_signal.direction
            entry = getattr(strategy_signal, "entry_price", 0.0)
            sl = getattr(strategy_signal, "stop_loss", 0.0)
            tp = getattr(strategy_signal, "take_profit", 0.0)
            conf = getattr(strategy_signal, "confidence", 0.5)

            return TradeSignal(
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                stop_loss=sl,
                take_profit_1=tp,
                take_profit_2=0.0,
                take_profit_3=0.0,
                volume=0.01,
                confidence=conf,
                rationale=f"{strategy_name} signal",
            )
        return None

    def _route_signal(self, signal: TradeSignal, strategy_name: str, strategy_id: str) -> None:
        """Route a signal through correlation gate → blend runner → OrderGateway."""
        direction_str = (
            signal.direction.value
            if hasattr(signal.direction, "value")
            else str(signal.direction)
        )

        # Check correlation gate
        allowed, reason = self._corr_gate.check(signal.symbol, direction_str, strategy_id)
        if not allowed:
            logger.info(
                "Signal blocked: %s | %s %s conf=%.2f — %s",
                strategy_id, direction_str, signal.symbol, signal.confidence, reason,
            )
            self._signals_rejected += 1
            return

        # Convert to blend format
        signal_dict = trade_signal_to_blend_dict(signal, strategy_name)
        signal_dict["strategy_id"] = strategy_id

        try:
            order = self._blend.on_signal(strategy_id, signal_dict)
        except Exception as exc:
            logger.error("Blend runner error: %s", exc, exc_info=True)
            self._corr_gate.release(signal.symbol, direction_str)
            self._signals_rejected += 1
            return

        if order.rejected:
            logger.info(
                "Signal rejected by blend: %s %s %s conf=%.2f — %s",
                strategy_id, direction_str, signal.symbol,
                signal.confidence, order.rejection_reason,
            )
            self._signals_rejected += 1
            self._corr_gate.release(signal.symbol, direction_str)
            return

        logger.info(
            "Signal accepted: %s %s %s @ %.5f conf=%.2f lots=%.4f",
            strategy_id, direction_str, signal.symbol,
            signal.entry_price, signal.confidence, order.lots,
        )
        self._signals_accepted += 1

        # Execute through OrderGateway if live mode
        if self._live_mode:
            self._execute_via_gateway(signal, order.lots, strategy_id, direction_str)
        else:
            self._paper_trades += 1
            logger.info("Paper trade: %s %s %.4f lots", strategy_id, direction_str, order.lots)

    def _execute_via_gateway(
        self,
        signal: TradeSignal,
        lots: float,
        strategy_id: str,
        direction_str: str,
    ) -> None:
        """Execute an order through the OrderGateway with correct volume."""
        symbol_id = self._symbol_id_map.get(signal.symbol)
        if symbol_id is None:
            logger.error("No symbol_id for %s — cannot execute", signal.symbol)
            self._corr_gate.release(signal.symbol, direction_str)
            return

        # CRITICAL: compute volume from actual lotSize
        spec = self._symbol_specs.get(symbol_id, {})
        lot_size = spec.get("lotSize", 10_000_000)
        raw_volume = lots_to_volume(lots, lot_size)

        # Determine side
        direction_val = (
            signal.direction.value
            if hasattr(signal.direction, "value")
            else str(signal.direction)
        ).upper()
        side = TradeSide.BUY if direction_val in ("LONG", "BUY") else TradeSide.SELL

        logger.info(
            "Sending order: %s %s vol=%d (lots=%.4f lotSize=%d)",
            strategy_id, direction_str, raw_volume, lots, lot_size,
        )

        try:
            result = self._gateway.send_market_order(
                symbol_id=symbol_id,
                side=side,
                volume=raw_volume,
                sl=signal.stop_loss if signal.stop_loss else None,
                tp=signal.take_profit_1 if signal.take_profit_1 else None,
                comment=strategy_id,
            )
        except Exception as exc:
            logger.error("Order gateway error: %s", exc, exc_info=True)
            self._corr_gate.release(signal.symbol, direction_str)
            return

        # Handle result with explicit status checking
        if result.status == OrderStatus.FILLED:
            self._live_fills += 1
            filled_price = result.filled_price or 0.0
            logger.info(
                "✅ FILLED: %s %s @ %.5f vol=%d (%.4f lots)",
                strategy_id, direction_str, filled_price, raw_volume, lots,
            )
            # Track position
            if result.order_id:
                self._tracker.on_position_opened(
                    position_id=int(result.order_id),
                    symbol=signal.symbol,
                    direction=direction_str,
                    volume=raw_volume,
                    entry_price=filled_price,
                    sl=signal.stop_loss if signal.stop_loss else None,
                    tp=signal.take_profit_1 if signal.take_profit_1 else None,
                )
        elif result.status == OrderStatus.REJECTED:
            logger.warning(
                "❌ REJECTED: %s %s — %s",
                strategy_id, direction_str,
                result.error_message or result.error_code or "unknown",
            )
            self._corr_gate.release(signal.symbol, direction_str)
        elif result.status == OrderStatus.TIMEOUT:
            logger.warning(
                "⏰ TIMEOUT: %s %s — order timed out",
                strategy_id, direction_str,
            )
            self._corr_gate.release(signal.symbol, direction_str)
        else:
            logger.warning(
                "❓ Unknown status %s: %s %s",
                result.status, strategy_id, direction_str,
            )
            self._corr_gate.release(signal.symbol, direction_str)

    def get_strategy_health_info(self) -> dict[str, dict]:
        """Build per-strategy health info for HealthMonitor."""
        now = time.monotonic()
        info = {}
        for sname in sorted(STRATEGY_ID_MAP.values()):
            evals = self._strategy_evals.get(sname, 0)
            no_sig = self._strategy_no_signal.get(sname, 0)
            last = self._strategy_last_eval.get(sname, now)
            info[sname] = {
                "evals": evals,
                "no_signal": no_sig,
                "last_eval_monotonic": last,
            }
        return info


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ayumi Forward Test v2 (New Infrastructure)"
    )
    parser.add_argument(
        "--symbols", default="GBPUSD,USDJPY",
        help="Comma-separated symbols (default: GBPUSD,USDJPY)",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Send real orders to cTrader via OrderGateway (default: paper)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args()

    symbols = [s.strip().upper().replace("/", "") for s in args.symbols.split(",")]

    # ── Step 1: Setup logging ──────────────────────────────────────────────
    setup_logging(level=args.log_level, log_dir=str(PROJECT_ROOT / "logs"))
    logger.info("=" * 60)
    logger.info("=== Ayumi Forward Test v2 (BQ-1043 Phase 4b) ===")
    logger.info("=" * 60)
    logger.info("Symbols: %s", symbols)
    logger.info("Live mode: %s", args.live)

    # ── Step 2: Load credentials ───────────────────────────────────────────
    cred_store = CredentialStore(
        credentials_path=str(PROJECT_ROOT / "data" / ".credentials")
    )
    try:
        creds = cred_store.load()
        logger.info("Credentials loaded for account_id=%d", creds.account_id)
    except Exception as exc:
        logger.error("Failed to load credentials: %s", exc)
        sys.exit(1)

    # ── Step 3: Create TokenLifecycle ──────────────────────────────────────
    token_lifecycle = TokenLifecycle(cred_store)
    try:
        token = token_lifecycle.ensure_valid()
        logger.info("Token valid, expires_at=%s", token_lifecycle.expires_at)
    except Exception as exc:
        logger.error("Token validation failed: %s", exc)
        sys.exit(1)

    # Start proactive token refresh timer
    token_lifecycle.start_proactive_timer()
    logger.info("Proactive token refresh timer started")

    # ── Step 4: Create session and connect ─────────────────────────────────
    session = cTraderSession(
        token_lifecycle=token_lifecycle,
        credential_store=cred_store,
        host=os.getenv("CTRADER_HOST", "demo.ctraderapi.com"),
        port=int(os.getenv("CTRADER_SSL_PORT", "5035")),
    )

    if not session.connect():
        logger.error("Session connection failed — aborting")
        token_lifecycle.stop_proactive_timer()
        sys.exit(1)

    logger.info("Session connected and authenticated")

    # ── Step 5: Query symbol specs (CRITICAL for volume) ───────────────────
    symbol_id_map: dict[str, int] = {}
    for sym in symbols:
        symbol_id_map[sym] = _DEFAULT_SYMBOL_IDS.get(sym, 1)

    all_symbol_ids = list(symbol_id_map.values())
    symbol_specs = query_symbol_specs(session, creds.account_id, all_symbol_ids)

    # Verify we got specs for all symbols
    for sym, sid in symbol_id_map.items():
        if sid not in symbol_specs:
            logger.warning(
                "No spec for %s (id=%d) — using default lotSize=10M",
                sym, sid,
            )
            symbol_specs[sid] = {
                "lotSize": 10_000_000,
                "minVolume": 100_000,
                "stepVolume": 100_000,
                "digits": 5,
                "pipSize": 0.0001,
            }

    # Log volume conversion info
    for sym, sid in symbol_id_map.items():
        spec = symbol_specs[sid]
        vol_001 = lots_to_volume(0.01, spec["lotSize"])
        logger.info(
            "Volume: %s 0.01 lots = %d raw (lotSize=%d)",
            sym, vol_001, spec["lotSize"],
        )

    # ── Step 6: Create MarketDataFeed ──────────────────────────────────────
    # Use H1 (3600s) as primary bar period
    sid_to_name = {v: k for k, v in symbol_id_map.items()}
    market_data_feed = MarketDataFeed(
        symbols=symbols,
        bar_period_seconds=3600,
        symbol_id_map=sid_to_name,
    )

    # ── Step 7: Create ExecutionEventHandler ───────────────────────────────
    event_handler = ExecutionEventHandler()

    # ── Step 8: Create OrderGateway ────────────────────────────────────────
    order_gateway = OrderGateway(
        session=session,
        event_handler=event_handler,
        account_id=creds.account_id,
    )

    # ── Step 9: Create PositionTracker ─────────────────────────────────────
    position_tracker = PositionTracker(session=session)

    # ── Step 10: Subscribe to market data ──────────────────────────────────
    if not session.subscribe_market_data(all_symbol_ids):
        logger.error("Failed to subscribe to market data — aborting")
        session.disconnect()
        token_lifecycle.stop_proactive_timer()
        sys.exit(1)

    logger.info("Subscribed to market data for %d symbols", len(all_symbol_ids))

    # Register the event handler for execution events
    for pt in (2126, 2151, 2132, 2142):
        session.register_message_handler(pt, lambda msg: event_handler.route(msg, msg))

    # ── Step 11: Load strategies ───────────────────────────────────────────
    strategies = build_strategies()
    logger.info("Loaded %d strategies: %s", len(strategies), [s.name for s in strategies])

    # Verify strategy names
    for s in strategies:
        assert s.name in STRATEGY_ID_MAP, f"Strategy .name '{s.name}' not in STRATEGY_ID_MAP"
        assert s.name in STRATEGY_TIMEFRAMES, f"Strategy .name '{s.name}' not in STRATEGY_TIMEFRAMES"
    logger.info("All strategy names verified against maps")

    # ── Step 12: Create blend runner and correlation gate ──────────────────
    blend_runner = build_blend_runner()
    correlation_gate = CorrelationGate()

    # ── Step 13: Create ForwardTestV2 engine ───────────────────────────────
    engine = ForwardTestV2(
        session=session,
        market_data_feed=market_data_feed,
        order_gateway=order_gateway,
        position_tracker=position_tracker,
        execution_event_handler=event_handler,
        health_monitor=None,  # set below
        blend_runner=blend_runner,
        correlation_gate=correlation_gate,
        strategies=strategies,
        symbol_id_map=symbol_id_map,
        symbol_specs=symbol_specs,
        live_mode=args.live,
    )

    # ── Step 14: Wire HealthMonitor ────────────────────────────────────────
    health_monitor = HealthMonitor(interval_seconds=60)
    health_monitor.attach(
        session=session,
        market_data_feed=engine,  # engine exposes the needed attributes
        order_gateway=engine,
        position_tracker=engine,
        strategies=engine.get_strategy_health_info(),
    )
    engine._health = health_monitor

    # ── Start engine and health monitor ────────────────────────────────────
    engine.start()
    health_monitor.start()

    # ── Step 15: Signal handlers for clean shutdown ────────────────────────
    def shutdown(signum, frame):
        logger.info("Shutdown signal (%s) — stopping...", signum)
        health_monitor.stop()
        engine.stop()
        blend_runner.stop()
        token_lifecycle.stop_proactive_timer()
        session.disconnect()
        logger.info("Clean shutdown complete")
        sys.exit(0)

    sig_module.signal(sig_module.SIGINT, shutdown)
    sig_module.signal(sig_module.SIGTERM, shutdown)

    logger.info("=" * 60)
    logger.info("=== Forward Test v2 RUNNING ===")
    logger.info("Pipeline: MarketDataFeed → strategies → blend → %s",
                "OrderGateway" if args.live else "PaperTrade")
    logger.info("=" * 60)

    # ── Main loop (keeps process alive) ────────────────────────────────────
    try:
        while engine.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
