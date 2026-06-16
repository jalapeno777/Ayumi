#!/usr/bin/env python3
"""Multi-strategy forward test launcher using BlendForwardTestRunner pipeline.

Replaces single-strategy launcher with a 3-strategy blend pipeline:
  FIX Tick Stream → Bar Building → SRMR+/Killzone/Momentum → Correlation Gate → Blend Runner → Paper

Uses existing BlendForwardTestRunner for confidence/risk/sizing and
existing cTraderLiveAdapter for strategy evaluation.
"""

from __future__ import annotations

import os
import sys
import argparse
import signal as sig_module
import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "forex-bot"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from adapters.ctrader.forward_test_engine import ForwardTestConfig, ForwardTestEngine
from adapters.ctrader.models import cTraderCredentials, TradeSignal
from adapters.ctrader.risk_guard import FTMOConfig
from adapters.ctrader.open_api_client import CTraderOpenApiClient
from forward_test.blend_runner import BlendForwardTestRunner
from strategies.srmr_plus import SRMRPlusStrategy, SRMRPlusConfig
from strategies.killzone_momentum import KillzoneMomentumStrategy, KillzoneMomentumConfig
from strategies.momentum import DonchianBreakoutStrategy, MomentumConfig
from strategies.session_range_mean_reversion import SessionRangeMeanReversionStrategy, SessionRangeMRConfig
from strategies.bb_rsi_reversion import BBRSIMeanReversion, BBRSIConfig
from strategies.rsi_threshold import SimpleRSIThresholdStrategy, RSIThresholdConfig
from common.logging_config import setup_logging
from core.types import Bar, BarPeriod

logger = logging.getLogger("ayumi.blend_launcher")


# ── Correlation Gate ──────────────────────────────────────────────────────────

class CorrelationGate:
    """Blocks duplicate symbol-direction signals — max 1 position per (symbol, direction)."""

    def __init__(self):
        self._active: dict[tuple[str, str], str] = {}  # (symbol, direction) -> strategy_id
        self._lock = threading.Lock()

    def check(self, symbol: str, direction: str, strategy_id: str) -> tuple[bool, str]:
        """Returns (allowed, reason). Reserves slot on success."""
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


# ── Heartbeat ─────────────────────────────────────────────────────────────────

class HeartbeatTracker:
    """Logs pipeline health every N bars."""

    def __init__(self, interval: int = 100):
        self._interval = interval
        self._bars_evaluated = 0
        self._signals_generated = 0
        self._signals_accepted = 0
        self._signals_rejected = 0
        self._lock = threading.Lock()

    def record_bar(self):
        with self._lock:
            self._bars_evaluated += 1
            if self._bars_evaluated % self._interval == 0:
                self._log()

    def record_signal(self, accepted: bool):
        with self._lock:
            self._signals_generated += 1
            if accepted:
                self._signals_accepted += 1
            else:
                self._signals_rejected += 1

    def _log(self):
        with self._lock:
            total_rejected = self._signals_rejected
            total_accepted = self._signals_accepted
            total_generated = self._signals_generated
            bars = self._bars_evaluated
        logger.info(
            "Heartbeat: Bars evaluated=%d, Signals generated=%d, Accepted=%d, Rejected=%d",
            bars, total_generated, total_accepted, total_rejected,
        )


# ── Bar Fetcher ───────────────────────────────────────────────────────────────

GBPUSD_SYMBOL_ID = 2
USDJPY_SYMBOL_ID = 4

# Symbol name → OpenAPI symbol_id mapping
SYMBOL_IDS = {
    "GBPUSD": 2,
    "USDJPY": 4,
    "EURUSD": 1,
}


def build_symbol_id_lookup(client) -> dict[str, int]:
    """Build symbol name → symbol_id mapping from OpenAPI."""
    lookup = dict(SYMBOL_IDS)  # start with known IDs
    try:
        symbols = client.get_symbols()
        for sym in symbols:
            name = sym.get("name", "").upper().replace("/", "")
            if name and name not in lookup:
                lookup[name] = sym.get("id")
    except Exception as exc:
        logger.warning("Could not fetch symbol list from OpenAPI: %s — using static mapping", exc)
    return lookup


def fetch_bars(symbol_id: int = GBPUSD_SYMBOL_ID, period: str = "H1", count: int = 100) -> list[dict]:
    """Fetch bars via OpenAPI for any period."""
    account_id = int(os.getenv("CTRADER_OPENAPI_ACCOUNT_ID", "0"))
    if not account_id:
        raise RuntimeError("CTRADER_OPENAPI_ACCOUNT_ID is required in .env")
    client = CTraderOpenApiClient(
        client_id=os.getenv("CTRADER_OPENAPI_CLIENT_ID"),
        client_secret=os.getenv("CTRADER_OPENAPI_CLIENT_SECRET"),
        account_id=account_id,
        access_token=os.getenv("CTRADER_OPENAPI_ACCESS_TOKEN"),
    )
    client.connect()

    period_seconds = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
    sec = period_seconds.get(period, 3600)
    to_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    from_ts = to_ts - (count * sec * 1000) + sec * 1000

    logger.info("Fetching %d %s bars (symbol_id=%d) from OpenAPI...", count, period, symbol_id)
    bars = client.get_trendbars(
        symbol_id=symbol_id,
        period=period,
        from_ts=from_ts,
        to_ts=to_ts,
        max_bars=count,
    )
    client.disconnect()
    logger.info("Fetched %d %s bars", len(bars), period)
    return bars


def fetch_h1_bars(symbol_id: int = GBPUSD_SYMBOL_ID, count: int = 100) -> list[dict]:
    """Backward-compatible wrapper."""
    return fetch_bars(symbol_id, period="H1", count=count)


def raw_bars_to_bar_objects(raw_bars: list[dict], period: BarPeriod | None = None) -> list[Bar]:
    """Convert OpenAPI raw bar dicts to Bar objects."""
    if period is None:
        period = BarPeriod.H1()
    result = []
    for rb in raw_bars:
        result.append(Bar(
            time=datetime.fromtimestamp(rb["timestamp"] / 1000, tz=timezone.utc),
            open=rb["open"],
            high=rb["high"],
            low=rb["low"],
            close=rb["close"],
            volume=rb["volume"],
            period=period,
        ))
    return result


# ── Signal Conversion ─────────────────────────────────────────────────────────

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


# ── Blend-Aware Forward Test Engine ──────────────────────────────────────────

class BlendForwardTestEngine(ForwardTestEngine):
    """Extended ForwardTestEngine that routes signals through BlendForwardTestRunner
    instead of directly to PaperTrader."""

    def __init__(self, *args, blend_runner: Optional[BlendForwardTestRunner] = None,
                 correlation_gate: Optional[CorrelationGate] = None,
                 heartbeat: Optional[HeartbeatTracker] = None,
                 strategy_id_map: Optional[dict[str, str]] = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self._blend_runner = blend_runner
        self._correlation_gate = correlation_gate or CorrelationGate()
        self._heartbeat = heartbeat or HeartbeatTracker()
        self._strategy_id_map = strategy_id_map or {}  # strategy_name -> strategy_id

    def _evaluate_strategies(self, symbol: str):
        """Override: route signals through blend pipeline with multi-TF support."""
        if self._live_adapter is None:
            return

        if not self._eval_semaphore.acquire(blocking=False):
            return

        try:
            # Build per-timeframe bar snapshots
            tf_bars: dict[int, list[Bar]] = {}
            with self._lock:
                for tf in self._required_timeframes:
                    key = self._bar_key(symbol, tf)
                    bars = list(self._bars.get(key, []))
                    current = self._current_bar.get(key)
                    if current is not None:
                        bars.append(current)
                    tf_bars[tf] = bars

            if not any(tf_bars.values()):
                return

            generated = 0
            for strategy_name in self._live_adapter._strategies.keys():
                # Resolve this strategy's timeframe
                tf = self._strategy_timeframes.get(strategy_name, self._config.bar_period_minutes)
                bars = tf_bars.get(tf, [])

                # Per-timeframe evaluation threshold (Rei #7)
                if len(bars) < self._config.min_bars_for_evaluation:
                    continue

                from backtest.engine import MarketState
                state = MarketState(bars=bars)

                # Per-strategy exception isolation (Kaito #3)
                try:
                    adapter = self._live_adapter.get_adapter(strategy_name, symbol)
                    if not adapter:
                        continue
                    s = adapter.evaluate_and_trade(state, spread=self._current_spread)
                except Exception as exc:
                    logger.error("Strategy %s evaluation error: %s", strategy_name, exc, exc_info=True)
                    with self._lock:
                        self._health.evaluation_errors += 1
                    continue

                # S1: Per-strategy diagnostic counters (mirrors base class pattern)
                # Bump counters for every strategy that passes the bar threshold,
                # regardless of whether a signal was generated. This is what makes
                # the [S1 Health] log show non-zero evals. (BQ-1037)
                with self._lock:
                    self._strategy_eval_counts[strategy_name] = (
                        self._strategy_eval_counts.get(strategy_name, 0) + 1
                    )
                    if s is None:
                        self._strategy_no_signal_counts[strategy_name] = (
                            self._strategy_no_signal_counts.get(strategy_name, 0) + 1
                        )
                    self._strategy_last_eval[strategy_name] = time.monotonic()

                # S1: INFO-level per-strategy eval log
                logger.info(
                    "[S1] Strategy %s: eval #%d, signals=%d, total_no_signal=%d",
                    strategy_name,
                    self._strategy_eval_counts[strategy_name],
                    1 if s is not None else 0,
                    self._strategy_no_signal_counts[strategy_name],
                )

                if s is None:
                    continue

                generated += 1
                self._heartbeat.record_bar()
                self._route_signal(s, strategy_name)

            with self._lock:
                self._health.signals_generated += generated

        except Exception as exc:
            with self._lock:
                self._health.evaluation_errors += 1
            logger.error("Strategy evaluation error: %s", exc, exc_info=True)
        finally:
            self._eval_semaphore.release()

    def _route_signal(self, signal: TradeSignal, strategy_name: str):
        """Route a single signal through correlation gate → blend runner."""
        strategy_id = self._strategy_id_map.get(strategy_name, strategy_name.lower().replace(" ", "_"))

        direction_str = signal.direction.value if hasattr(signal.direction, "value") else str(signal.direction)

        if self._blend_runner:
            # Check correlation gate
            allowed, reason = self._correlation_gate.check(signal.symbol, direction_str, strategy_id)
            if not allowed:
                logger.info("Signal blocked: %s | %s %s conf=%.2f — %s", strategy_id, direction_str, signal.symbol, signal.confidence, reason)
                with self._lock:
                    self._health.signals_rejected += 1
                self._heartbeat.record_signal(accepted=False)
                return

            # Convert to blend format
            signal_dict = trade_signal_to_blend_dict(signal, strategy_id)
            signal_dict["strategy_id"] = strategy_id

            try:
                order = self._blend_runner.on_signal(strategy_id, signal_dict)
                if order.rejected:
                    logger.info("Signal rejected by blend: %s %s %s conf=%.2f — %s", strategy_id, direction_str, signal.symbol, signal.confidence, order.rejection_reason)
                    with self._lock:
                        self._health.signals_rejected += 1
                    self._correlation_gate.release(signal.symbol, direction_str)
                    self._heartbeat.record_signal(accepted=False)
                else:
                    logger.info("Signal accepted: %s %s %s @ %.5f conf=%.2f lots=%.4f", strategy_id, direction_str, signal.symbol, signal.entry_price, signal.confidence, order.lots)
                    with self._lock:
                        self._health.signals_traded += 1
                    self._heartbeat.record_signal(accepted=True)

                    # Execute through paper trader using blend runner's sized lots
                    try:
                        exec_signal = TradeSignal(
                            symbol=signal.symbol,
                            direction=signal.direction,
                            entry_price=signal.entry_price,
                            stop_loss=signal.stop_loss,
                            take_profit_1=signal.take_profit_1,
                            take_profit_2=signal.take_profit_2,
                            take_profit_3=signal.take_profit_3,
                            volume=order.lots,  # Sized by blend runner orchestrator
                            confidence=signal.confidence,
                            rationale=getattr(signal, 'rationale', ''),
                        )
                        exec_result = self._paper_trader.process_signal(
                            exec_signal, spread=self._current_spread
                        )
                        if exec_result.success:
                            logger.info("Trade executed: %s %s %.4f lots", strategy_id, direction_str, order.lots)
                        else:
                            logger.warning("Trade execution failed: %s", exec_result.rejection_reason)
                            # Free risk budget: sizer registered open risk but
                            # PaperTrader rejected the order downstream.
                            self._blend_runner.cancel_risk(order.risk_amount)
                            self._correlation_gate.release(signal.symbol, direction_str)
                    except Exception as exec_err:
                        logger.error("Trade execution error: %s", exec_err, exc_info=True)
                        # Free risk budget on execution error too
                        self._blend_runner.cancel_risk(order.risk_amount)
                        self._correlation_gate.release(signal.symbol, direction_str)

                    # Write last_signal.txt for watchdog health check
                    try:
                        import json as _json
                        _sig_data = {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "strategy": strategy_id,
                            "symbol": signal.symbol,
                            "direction": direction_str,
                            "entry_price": signal.entry_price,
                            "confidence": signal.confidence,
                            "lots": order.lots,
                            "stop_loss": signal.stop_loss,
                            "take_profit": signal.take_profit,
                        }
                        _sig_path = Path(PROJECT_ROOT) / "data" / "last_signal.txt"
                        _sig_path.parent.mkdir(parents=True, exist_ok=True)
                        _sig_path.write_text(_json.dumps(_sig_data, indent=2) + "\n")
                    except Exception:
                        pass  # Non-critical — don't break signal flow
            except Exception as exc:
                logger.error("Blend runner error: %s", exc, exc_info=True)
                self._correlation_gate.release(signal.symbol, direction_str)
                with self._lock:
                    self._health.signals_rejected += 1
                self._heartbeat.record_signal(accepted=False)
        else:
            # Fallback: direct to paper trader (original behavior)
            with self._lock:
                self._health.signals_traded += 1
            logger.info("Signal traded (direct): %s %s %s @ %.5f conf=%.2f", strategy_id, direction_str, signal.symbol, signal.entry_price, signal.confidence)
            self._heartbeat.record_signal(accepted=True)

    def on_position_closed_release(self, position):
        """Release correlation gate on position close to avoid stale blocks."""
        try:
            direction = position.direction.value if hasattr(position.direction, "value") else str(position.direction)
            self._correlation_gate.release(position.symbol, direction)
            logger.info(
                "Correlation gate released: %s %s (active=%d)",
                direction,
                position.symbol,
                self._correlation_gate.active_count,
            )
        except Exception as exc:
            logger.warning("Failed to release correlation gate on close: %s", exc)


# ── Main ──────────────────────────────────────────────────────────────────────

STRATEGY_ID_MAP = {
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

# Strategy -> bar period minutes mapping
STRATEGY_TIMEFRAMES = {
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


def build_blend_runner() -> BlendForwardTestRunner:
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


def wire_connection_reliability(connection_manager):
    """Wire connection reliability modules (watchdog, OAuth refresh).

    BQ-716 Phase 2: Activates heartbeat watchdog and proactive OAuth refresh.
    Called after connection manager is constructed, before engine start.
    """
    connection_manager.start_watchdog()
    # NOTE: refresh_oauth_if_needed() disabled until BQ-978-RECONCILE resolves
    # the two-token-path conflict. The existing token_manager handles refresh.
    # try:
    #     connection_manager.refresh_oauth_if_needed()
    # except Exception as exc:
    #     logger.warning("OAuth refresh failed on startup: %s", exc)


def main():
    parser = argparse.ArgumentParser(description="Ayumi Multi-Strategy Forward Test")
    parser.add_argument("--symbols", default="GBPUSD", help="Comma-separated symbols (default: GBPUSD)")
    parser.add_argument("--live", action="store_true", help="Send real orders to cTrader via OpenAPI using account id from CTRADER_OPENAPI_ACCOUNT_ID (default: paper-only)")
    parser.add_argument("--paper-only", action="store_true", help="Run in paper-only mode (default, overridden by --live)")
    args = parser.parse_args()
    symbols = [s.strip().upper().replace("/", "") for s in args.symbols.split(",")]

    # ── Single-instance guard (B1) ─────────────────────────────────────────
    from adapters.ctrader.pid_guard import acquire_pid_lock
    _pid_path = PROJECT_ROOT / "data" / "forward_test.pid"
    # Guard must be acquired BEFORE logging setup floods, but we need logging
    # for the guard's own messages, so set up basic logging first.
    setup_logging(level="DEBUG")
    # Specifically enable the spot feed and execution event loggers
    logging.getLogger("ayumi.openapi_spot_feed").setLevel(logging.DEBUG)
    _pid_ctx = acquire_pid_lock(_pid_path)
    _pid_guard = _pid_ctx.__enter__()  # acquire lock, exit(1) if duplicate
    _pid_guard.write_pid()

    logger.info("=== Ayumi Multi-Strategy Forward Test (Blend Pipeline) ===")
    logger.info("Symbols: %s", symbols)

    # 1. Fetch historical bars — per symbol, H1 and M15 in a SINGLE OpenAPI connection
    account_id = int(os.getenv("CTRADER_OPENAPI_ACCOUNT_ID", "0"))
    if not account_id:
        raise RuntimeError("CTRADER_OPENAPI_ACCOUNT_ID is required in .env")
    client = CTraderOpenApiClient(
        client_id=os.getenv("CTRADER_OPENAPI_CLIENT_ID"),
        client_secret=os.getenv("CTRADER_OPENAPI_CLIENT_SECRET"),
        account_id=account_id,
        access_token=os.getenv("CTRADER_OPENAPI_ACCESS_TOKEN"),
    )
    client.connect()

    symbol_id_lookup = build_symbol_id_lookup(client)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Fetch bars per symbol
    symbol_bars: dict[str, dict[int, list[Bar]]] = {}  # symbol -> tf -> bars
    for sym in symbols:
        sym_id = symbol_id_lookup.get(sym)
        if sym_id is None:
            logger.warning("No symbol_id for %s — skipping bar preload", sym)
            continue

        # H1 bars
        h1_count = 100
        h1_from = now_ms - (h1_count * 3600 * 1000) + 3600 * 1000
        logger.info("Fetching %d H1 bars for %s (id=%d)...", h1_count, sym, sym_id)
        raw_h1 = client.get_trendbars(
            symbol_id=sym_id, period="H1",
            from_ts=h1_from, to_ts=now_ms, max_bars=h1_count,
        )
        symbol_bars.setdefault(sym, {})[60] = raw_bars_to_bar_objects(raw_h1, period=BarPeriod.H1())
        logger.info("Fetched %d H1 bars for %s", len(raw_h1), sym)

        # M15 bars
        m15_count = 200
        m15_from = now_ms - (m15_count * 900 * 1000) + 900 * 1000
        logger.info("Fetching %d M15 bars for %s (id=%d)...", m15_count, sym, sym_id)
        raw_m15 = client.get_trendbars(
            symbol_id=sym_id, period="M15",
            from_ts=m15_from, to_ts=now_ms, max_bars=m15_count,
        )
        symbol_bars.setdefault(sym, {})[15] = raw_bars_to_bar_objects(raw_m15, period=BarPeriod.M15())
        logger.info("Fetched %d M15 bars for %s", len(raw_m15), sym)

    client.disconnect()

    # Critical: give the Twisted reactor time to fully process the TCP
    # disconnect and clean up all protocol state before the spot feed
    # opens a new connection on the same reactor. Without this sleep,
    # the old connection's teardown races with the new connection's
    # setup, causing CH_CLIENT_AUTH_FAILURE on the spot feed.
    import time as _time
    _time.sleep(3)

    if not any(symbol_bars.values()):
        logger.error("Failed to fetch any bars — aborting")
        sys.exit(1)

    # Use first symbol's H1 bars as primary for backward compat checks
    primary_symbol = symbols[0]
    raw_h1 = symbol_bars.get(primary_symbol, {}).get(60, [])

    # 2. Build credentials
    credentials = cTraderCredentials(
        host=os.getenv("CTRADER_HOST", "demo-uk-eqx-01.p.c-trader.com"),
        port=int(os.getenv("CTRADER_SSL_PORT", "5212")),
        use_ssl=True,
        username=os.getenv("CTRADER_ACCOUNT", ""),
        password=os.getenv("CTRADER_PASSWORD", ""),
        sender_comp_id=os.getenv("CTRADER_SENDER_COMP_ID", ""),
        target_comp_id=os.getenv("CTRADER_TARGET_COMP_ID", ""),
        sender_sub_id=os.getenv("CTRADER_SENDER_SUB_ID", ""),
    )

    # 3. Instantiate strategies (T3)
    from strategies.session_breakout import SessionBreakoutStrategy

    strategies = [
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
    logger.info("Registered %d strategies: %s", len(strategies), [s.name for s in strategies])

    # Verify .name properties match STRATEGY_ID_MAP keys
    for s in strategies:
        assert s.name in STRATEGY_ID_MAP, f"Strategy .name '{s.name}' not in STRATEGY_ID_MAP"
        assert s.name in STRATEGY_TIMEFRAMES, f"Strategy .name '{s.name}' not in STRATEGY_TIMEFRAMES"
    logger.info("All strategy .name properties verified against maps")

    # 4. Build blend runner
    blend_runner = build_blend_runner()
    correlation_gate = CorrelationGate()
    heartbeat = HeartbeatTracker(interval=100)

    # 5. Build engine config with strategy_timeframes and multi-symbol
    config = ForwardTestConfig(
        symbol=symbols[0],
        symbols=symbols,
        starting_balance=10_000.0,
        min_confidence=0.50,
        max_bars_per_symbol=500,
        min_bars_for_evaluation=55,
        live_mode=args.live,
        strategy_timeframes=STRATEGY_TIMEFRAMES,
    )

    # 6. Create blend-aware engine
    engine = BlendForwardTestEngine(
        config=config,
        strategies=strategies,
        ftmo_config=FTMOConfig(min_risk_reward=0.0),
        credentials=credentials,
        blend_runner=blend_runner,
        correlation_gate=correlation_gate,
        heartbeat=heartbeat,
        strategy_id_map=STRATEGY_ID_MAP,
        blend_mode=True,
    )

    # Release correlation slots when paper positions close.
    engine.register_callback("on_position_closed", engine.on_position_closed_release)

    # Preload historical bars into engine (after engine creation, before start)
    for sym, timeframes in symbol_bars.items():
        for period_minutes, bars in timeframes.items():
            engine.preload_bars(sym, period_minutes, bars)
            logger.info("Preloaded %d %dmin bars for %s into engine", len(bars), period_minutes, sym)

    # 8. Shutdown handler
    def shutdown(signum, frame):
        logger.info("Shutdown signal — stopping engine...")
        engine.stop()
        blend_runner.stop()
        sys.exit(0)

    sig_module.signal(sig_module.SIGINT, shutdown)
    sig_module.signal(sig_module.SIGTERM, shutdown)

    # ── Connection reliability wiring (BQ-716) ──────────────────────────
    from adapters.ctrader.connection_manager import ConnectionManager as _ConnectionManager
    _connection_mgr = _ConnectionManager()
    wire_connection_reliability(_connection_mgr)

    # ── Startup diagnostics (B5) ──────────────────────────────────────────
    logger.info("=== STARTING MULTI-STRATEGY FORWARD TEST ===")
    logger.info("Pipeline: SRMR+ + Killzone + Momentum + SessionRangeMR → Correlation Gate → Blend Runner → Paper")
    logger.info("Startup diagnostic: strategies=%s", [s.name for s in strategies])
    logger.info("Startup diagnostic: symbols=%s", symbols)
    logger.info("Startup diagnostic: bar_period=%dm, min_confidence=%.2f", config.bar_period_minutes, config.min_confidence)
    logger.info("Startup diagnostic: strategy_timeframes=%s", STRATEGY_TIMEFRAMES)
    started = engine.start()
    if not started:
        logger.error("Engine failed to start. See logs above for the specific failure reason.")
        logger.error(
            "For live mode, verify: CTRADER_OPENAPI_CLIENT_ID, CTRADER_OPENAPI_CLIENT_SECRET, "
            "CTRADER_OPENAPI_ACCESS_TOKEN, CTRADER_OPENAPI_REFRESH_TOKEN, "
            "CTRADER_OPENAPI_ACCOUNT_ID, CTRADER_OPENAPI_TRADER_LOGIN in .env"
        )
        blend_runner.stop()
        sys.exit(1)

    # ── Periodic health loop (B5) ─────────────────────────────────────────
    try:
        _health_interval = 60.0
        _last_health_log = time.monotonic()
        while True:
            time.sleep(1)
            if not engine.is_running:
                logger.warning("Engine is no longer running — exiting health loop")
                break
            now = time.monotonic()
            if now - _last_health_log >= _health_interval:
                _last_health_log = now
                try:
                    stats = engine.get_stats()
                    h = stats.get("health", {})
                    t = stats.get("trading", {})
                    # Determine live execution status (BQ-1042: prevent false trade claims)
                    _live_fills = getattr(engine, "_live_fill_count", 0)
                    _live_balance = getattr(engine, "_live_balance", None)
                    _paper_trades = t.get("trades_executed", 0)
                    _paper_balance = t.get("current_balance", 0.0)
                    _live_mode = getattr(engine, "_live_adapter", None) is not None
                    _balance_str = (
                        f"paper=${_paper_balance:.2f}"
                        + (f" live=${_live_balance:.2f}" if _live_balance is not None else " live=N/A")
                    ) if _live_mode else f"balance=${_paper_balance:.2f}"
                    logger.info(
                        "[B5 Health] ticks=%d tps=%.2f bars=%d signals=%d "
                        "paper_trades=%d live_fills=%d %s uptime=%.0fs",
                        h.get("ticks_received", 0),
                        h.get("ticks_per_second", 0.0),
                        engine.health.bars_built,
                        engine.health.signals_generated,
                        _paper_trades,
                        _live_fills,
                        _balance_str,
                        h.get("uptime_sec", 0),
                    )
                    # Alert if live mode has zero fills despite paper trades
                    if _live_mode and _paper_trades > 0 and _live_fills == 0:
                        logger.warning(
                            "[B5 Health] ⚠️  live_fills=0 but paper_trades=%d — "
                            "orders may not be reaching cTrader",
                            _paper_trades,
                        )
                    # Tick-to-bar pipeline health (Amendment 4)
                    if h.get("ticks_received", 0) > 0 and engine.health.bars_built == 0:
                        logger.warning(
                            "[B5 Pipeline] Ticks received (%d) but zero bars built — "
                            "tick-to-bar pipeline may be stalled",
                            h.get("ticks_received", 0),
                        )
                except Exception as exc:
                    logger.warning("[B5 Health] Error logging health: %s", exc)
    except KeyboardInterrupt:
        shutdown(None, None)
    finally:
        # Release PID lock on exit
        try:
            _pid_ctx.__exit__(None, None, None)
        except Exception:
            pass


if __name__ == "__main__":
    main()
