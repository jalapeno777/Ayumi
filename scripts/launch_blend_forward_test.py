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
import json
import signal as sig_module
import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml  # PyYAML — Optuna-tuned strategy configs (config/strategies.yaml)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "forex-bot"))

def _refuse_root():
    """Refuse to run the trading service as root.

    Ayumi must run as TacoPants to avoid file-ownership conflicts on
    .env, PID files, lock files and runtime state.  This guard exits
    *before* any broker connection or credential read so that a
    mistaken root launch cannot create state that a subsequent
    TacoPants launch cannot clean up.
    """
    if os.geteuid() == 0:
        sys.exit(
            "FATAL: Refusing to run Ayumi forward test as root.\n"
            "Use 'systemctl start ayumi-forward-test.service' or run as TacoPants user.\n"
            "This guard prevents permission conflicts and credential ownership issues."
        )


if __name__ == "__main__":
    _refuse_root()

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from adapters.ctrader.forward_test_engine import (
    ForwardTestConfig,
    ForwardTestEngine,
    _is_forex_market_closed,
)
from adapters.ctrader.models import cTraderCredentials, CTraderTradeSignal
from adapters.ctrader.risk_guard import FTMOConfig
from forward_test.blend_runner import BlendForwardTestRunner
from strategies.srmr_plus import SRMRPlusStrategy, SRMRPlusConfig
from strategies.killzone_momentum import KillzoneMomentumStrategy, KillzoneMomentumConfig
from strategies.momentum import DonchianBreakoutStrategy, MomentumConfig
from strategies.session_range_mean_reversion import SessionRangeMeanReversionStrategy, SessionRangeMRConfig
from strategies.bb_rsi_reversion import BBRSIMeanReversion, BBRSIConfig
from strategies.rsi_threshold import SimpleRSIThresholdStrategy, RSIThresholdConfig
from strategies.test_canary import TestCanaryStrategy
from reporting.equity_tracker import EquityTracker
from common.logging_config import setup_logging
from core.types import Bar, BarPeriod

logger = logging.getLogger("ayumi.blend_launcher")

import os as _os
_os.umask(0o022)  # Ensure files are created 644/755 regardless of process owner


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
        self._lock = threading.RLock()

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


# ── Bar Fetcher (now handled by single-connection spot feed) ───────────────

GBPUSD_SYMBOL_ID = 2
USDJPY_SYMBOL_ID = 4

# Symbol name → OpenAPI symbol_id mapping (static fallback)
SYMBOL_IDS = {
    "GBPUSD": 2,
    "USDJPY": 4,
    "EURUSD": 1,
}


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

def trade_signal_to_blend_dict(signal: CTraderTradeSignal, strategy_name: str) -> dict:
    """Convert cTrader CTraderTradeSignal to the dict format BlendForwardTestRunner.on_signal() expects."""
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

    def _blend_signal_id(self, signal: CTraderTradeSignal) -> str:
        """Delegate to BlendForwardTestRunner.make_signal_id so we never
        drift out of sync with the canonical id construction.

        Must match the pattern in blend_runner.on_signal:
            signal.strategy_id + "_" + str(signal.timestamp.timestamp())
        """
        return self._blend_runner.make_signal_id(signal)

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

    def _route_signal(self, signal: CTraderTradeSignal, strategy_name: str):
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
                    # T2: do NOT bump ``signals_traded`` here yet — that
                    # counter now means "execution confirmed successful,"
                    # not "blend runner accepted."  We bump it only after
                    # the order reaches the broker with a FILLED outcome
                    # (or after a paper-mode ``process_signal`` returns
                    # success).  ``signals_accepted`` captures the blend-side
                    # accept count for operators who want to see it.
                    with self._lock:
                        self._health.signals_accepted = (
                            getattr(self._health, "signals_accepted", 0) + 1
                        )
                    self._heartbeat.record_signal(accepted=True)

                    # Execute directly: live → cTrader, paper → PaperTrader
                    # Single-connection architecture: no dual execution path.
                    try:
                        exec_signal = CTraderTradeSignal(
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
                        if self._config.live_mode:
                            # Direct cTrader execution — skip paper trader entirely
                            from adapters.ctrader.forward_test_engine import (
                                LiveExecutionStatus,
                            )
                            outcome = self._execute_signal_live(
                                exec_signal, strategy_id=strategy_id
                            )
                            if outcome is None:
                                logger.warning(
                                    "Live execution skipped (pre-flight): %s %s %.4f lots",
                                    strategy_id,
                                    direction_str,
                                    order.lots,
                                )
                                self._blend_runner.cancel_risk(
                                    self._blend_signal_id(signal),
                                    order.risk_amount,
                                )
                                self._correlation_gate.release(signal.symbol, direction_str)
                            elif outcome.status == LiveExecutionStatus.FILLED:
                                self._live_fill_count = getattr(self, "_live_fill_count", 0) + 1
                                with self._lock:
                                    self._health.signals_traded += 1
                                logger.info(
                                    "Live trade executed: %s %s %.4f lots order_id=%s",
                                    strategy_id,
                                    direction_str,
                                    order.lots,
                                    getattr(outcome.order, "order_id", ""),
                                )
                            elif outcome.status == LiveExecutionStatus.SENT:
                                # Order sent to cTrader but no execution event
                                # yet — bump signals_sent and signals_pending.
                                # Do NOT count as a fill.  Late-fill callbacks
                                # will upgrade it if the event arrives late.
                                with self._lock:
                                    self._health.signals_sent += 1
                                    self._health.signals_pending += 1
                                logger.info(
                                    "Live order SENT, awaiting ack: %s %s %.4f lots order_id=%s",
                                    strategy_id,
                                    direction_str,
                                    order.lots,
                                    getattr(outcome.order, "order_id", ""),
                                )
                            elif outcome.status == LiveExecutionStatus.TIMEOUT:
                                # Our local wait_for_event fired without seeing
                                # the broker's execution event. The order WAS
                                # transmitted; the verdict isn't terminal yet.
                                # Treat as a pending ack state (mirrors SENT) and
                                # hand the verdict to the late-fill callback.
                                # This split is required because every TIMEOUT
                                # that later confirms as FILLED was previously
                                # double-counted in signals_failed_live, which
                                # then mirrored live_fills 1:1 in the B5 health
                                # line. Holding the correlation gate + risk
                                # budget here matches SENT semantics: the broker
                                # may still deliver an execution event late.
                                with self._lock:
                                    self._health.signals_sent += 1
                                    self._health.signals_pending += 1
                                logger.warning(
                                    "Live order TIMEOUT awaiting ack: %s %s %.4f lots order_id=%s — deferring verdict to late-fill callback",
                                    strategy_id,
                                    direction_str,
                                    order.lots,
                                    getattr(outcome.order, "order_id", ""),
                                )
                            else:
                                # REJECTED / NOT_CONNECTED / CANCELLED — terminal
                                # failures only. SENT and TIMEOUT are handled in
                                # their own branches above and treated as
                                # awaiting-ack until the late callback decides.
                                with self._lock:
                                    self._health.signals_failed_live += 1
                                logger.warning(
                                    "Live execution failed: %s %s %.4f lots status=%s reason=%s",
                                    strategy_id,
                                    direction_str,
                                    order.lots,
                                    outcome.status.value,
                                    outcome.reason,
                                )
                                self._blend_runner.cancel_risk(
                                    self._blend_signal_id(signal),
                                    order.risk_amount,
                                )
                                self._correlation_gate.release(signal.symbol, direction_str)
                        else:
                            # Paper mode: execute through paper trader
                            exec_result = self._paper_trader.process_signal(
                                exec_signal, spread=self._current_spread
                            )
                            if exec_result.success:
                                with self._lock:
                                    self._health.signals_traded += 1
                                logger.info("Paper trade executed: %s %s %.4f lots", strategy_id, direction_str, order.lots)
                            else:
                                logger.warning("Trade execution failed: %s", exec_result.rejection_reason)
                                self._blend_runner.cancel_risk(
                                    self._blend_signal_id(signal),
                                    order.risk_amount,
                                )
                                self._correlation_gate.release(signal.symbol, direction_str)
                    except Exception as exec_err:
                        logger.error("Trade execution error: %s", exec_err, exc_info=True)
                        # Free risk budget on execution error too
                        self._blend_runner.cancel_risk(
                            self._blend_signal_id(signal),
                            order.risk_amount,
                        )
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
    "Test Canary": "test_canary",
}

# Strategy -> bar period minutes mapping
STRATEGY_TIMEFRAMES = {
    "SRMR+": 60,
    "Killzone Momentum": 60,  # H1 per SRF validation Jul 2026
    "Donchian Channel Breakout": 15,
    "Session-Range Mean Reversion": 60,
    "BB+RSI Mean Reversion": 60,
    "Session Breakout London": 15,
    "Session Breakout NY": 15,
    "Session Breakout Asian": 15,
    "Simple RSI Threshold": 15,
    "Test Canary": 15,
}

# ── strategies.yaml loader (Optuna-tuned per-symbol/timeframe configs) ────
# `strategies.yaml` is the source of truth for SRMR+ per-symbol/timeframe
# variants produced by the Optuna walk-forward pipeline.  Loading happens
# at module-import time so STRATEGY_ID_MAP / STRATEGY_TIMEFRAMES can be
# fully populated before the engine's startup assertions run.
_STRATEGIES_YAML_PATH = (
    PROJECT_ROOT / "src" / "forex-bot" / "config" / "strategies.yaml"
)
_TF_CODE_TO_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H2": 120, "H4": 240, "D1": 1440}
_ALLOWED_TF_MINUTES = {15, 60, 240}  # mirrors ForwardTestEngine._ALLOWED_TIMEFRAMES
_SUPPORTED_YAML_STRATEGY_TYPES = {"srmr_plus"}


def _load_yaml_strategies(
    yaml_path: Path,
) -> tuple[list[dict], list[dict]]:
    """Parse ``strategies.yaml`` into per-variant extras + skip-reasons.

    Returns ``(extra, skipped)`` where each extra is::

        {"name":        "SRMR+ GBPUSD H1",
         "id":          "srmr_gbpusd_h1",
         "symbol":      "GBPUSD",
         "timeframe":   "H1",
         "tf_minutes":  60,
         "params":      {...},
         "min_confidence": 0.40,    # engine-level; informational only
        }

    and each skipped entry is::

        {"id": "ttc_xauusd_h1", "reason": "unsupported type 'ttc'"}
    """
    if not yaml_path.exists():
        logger.warning(
            "strategies.yaml not found at %s — falling back to default strategy pool",
            yaml_path,
        )
        return [], [{"id": None, "reason": f"yaml not found at {yaml_path}"}]

    try:
        cfg = yaml.safe_load(yaml_path.read_text()) or {}
    except yaml.YAMLError as exc:
        logger.error("Failed to parse strategies.yaml: %s — using defaults", exc)
        return [], [{"id": None, "reason": f"yaml parse error: {exc}"}]

    yaml_strategies = (
        cfg.get("forward_test", {}).get("strategies")
        if isinstance(cfg.get("forward_test"), dict)
        else None
    )
    if yaml_strategies is None:
        # Fallback: tolerate root-level `strategies:` if forward_test wrapper absent
        yaml_strategies = cfg.get("strategies") or []

    extra: list[dict] = []
    skipped: list[dict] = []
    for entry in yaml_strategies or []:
        entry_id = entry.get("id", "?")
        if not entry.get("enabled", False):
            skipped.append({"id": entry_id, "reason": "disabled"})
            continue
        etype = entry.get("type")
        if etype not in _SUPPORTED_YAML_STRATEGY_TYPES:
            skipped.append({
                "id": entry_id,
                "reason": f"unsupported type '{etype}' (no class wired)",
            })
            continue
        tf_code = entry.get("timeframe")
        tf_minutes = _TF_CODE_TO_MINUTES.get(tf_code)
        if tf_minutes is None:
            skipped.append({"id": entry_id, "reason": f"unknown timeframe '{tf_code}'"})
            continue
        if tf_minutes not in _ALLOWED_TF_MINUTES:
            skipped.append({
                "id": entry_id,
                "reason": f"tf {tf_minutes}m not in allowed whitelist {_ALLOWED_TF_MINUTES}",
            })
            continue
        symbol = entry.get("symbol")
        if not symbol:
            skipped.append({"id": entry_id, "reason": "missing 'symbol'"})
            continue
        params = dict(entry.get("params") or {})
        extra.append({
            "name": f"SRMR+ {symbol} {tf_code}",
            "id": entry_id,
            "symbol": symbol,
            "timeframe": tf_code,
            "tf_minutes": tf_minutes,
            "params": params,
            "min_confidence": entry.get("min_confidence"),
        })
    return extra, skipped


_yaml_extras, _yaml_skipped = _load_yaml_strategies(_STRATEGIES_YAML_PATH)

# Register each YAML variant in the id + timeframe maps so the engine's
# startup assertions (s.name in STRATEGY_ID_MAP / STRATEGY_TIMEFRAMES) pass.
for _extra in _yaml_extras:
    STRATEGY_ID_MAP[_extra["name"]] = _extra["id"]
    STRATEGY_TIMEFRAMES[_extra["name"]] = _extra["tf_minutes"]

# The default "SRMR+" entry was the single un-tuned pool instance;
# it is intentionally REPLACED by the per-symbol/timeframe variants
# above when YAML has at least one enabled variant.  When YAML has no
# enabled SRMR+ variant, we keep the default entry as a safety fallback
# so the existing 10-strategy pool behaviour is preserved exactly.
if any(_e["id"].startswith("srmr_") for _e in _yaml_extras):
    STRATEGY_ID_MAP.pop("SRMR+", None)
    STRATEGY_TIMEFRAMES.pop("SRMR+", None)


def _build_srmr_instances_from_yaml(extras: list[dict]) -> list["SRMRPlusStrategy"]:
    """Instantiate SRMRPlusStrategy objects from the parsed YAML extras."""
    valid_fields = set(SRMRPlusConfig.__dataclass_fields__.keys())
    instances: list[SRMRPlusStrategy] = []
    for extra in extras:
        params = dict(extra["params"])
        unknown = sorted(set(params) - valid_fields)
        if unknown:
            logger.warning(
                "SRMR+ %s: dropping unknown params %s",
                extra["name"], unknown,
            )
            params = {k: v for k, v in params.items() if k in valid_fields}
        try:
            cfg = SRMRPlusConfig(**params)
        except (TypeError, ValueError) as exc:
            logger.error(
                "SRMR+ %s: failed to build SRMRPlusConfig from YAML params: %s — skipping",
                extra["name"], exc,
            )
            continue
        instances.append(SRMRPlusStrategy(config=cfg, name=extra["name"]))
    return instances


def build_blend_runner() -> BlendForwardTestRunner:
    config = {
        "account_balance": 10_000.0,
        "risk_per_trade_pct": 0.005,
        "daily_risk_cap_pct": 0.05,
        "max_sniper": 3,
        "max_swarm": 5,
        "spread_pips": {"GBPUSD": 2.0, "EURUSD": 0.8, "XAUUSD": 0.3, "USDJPY": 0.8},
        "atr_cache_path": "data/atr_cache.json",
        "state_path": "data/risk_state_blend.json",
        "log_level": "INFO",
    }
    runner = BlendForwardTestRunner(config)
    runner.start()
    return runner


def wire_connection_reliability(connection_manager):
    """Wire connection reliability modules (watchdog, OAuth refresh).

    TokenLifecycle handles refresh with 5-day buffer (day-25 proactive refresh
    on 30-day tokens). BQ-978 two-token-path conflict is safe: TokenLifecycle
    reads from .env via CredentialStore; OAuthRefreshManager reads from
    data/.credentials JSON — different stores, no race.
    """
    connection_manager.start_watchdog()
    try:
        connection_manager.refresh_oauth_if_needed()
    except Exception as exc:
        logger.warning("OAuth refresh on startup failed: %s", exc)


# ── Forward Test Health JSON Writer ──────────────────────────────────────────

_HEALTH_JSON_PATH = PROJECT_ROOT / "data" / "forward_test_health.json"


def write_forward_test_health_json(engine: ForwardTestEngine) -> None:
    """Atomically write forward-test health status to ``data/forward_test_health.json``.

    Called on startup (immediately clears stale ``down`` state) and every 60s
    from the periodic health loop.
    """
    try:
        health = engine.health
        stats = engine.get_stats()
        trading = stats.get("trading", {})

        # Connection state from the spot feed's state manager
        feed = getattr(engine, "_market_feed", None)
        state_mgr = getattr(feed, "_state_mgr", None)
        connection_state = state_mgr.state.value if state_mgr else "unknown"

        # trades_executed observability fix (live mode):
        # In live mode, PaperTrader.trades_executed stays at 0 because the
        # paper trader's execute path is bypassed (live orders are sent
        # directly to cTrader and counted via engine._live_fill_count).
        # Reading from the paper trader in live mode produces a false zero
        # in this health file even when real fills have happened.
        is_live = bool(getattr(getattr(engine, "_config", None), "live_mode", False))
        if is_live:
            live_fills = getattr(engine, "_live_fill_count", 0)
            # closed_trades_live: fills - currently-open positions. The paper
            # trader's order manager does mirror live positions in live mode
            # (execute_live_order is called for each live signal), so its
            # get_open_positions() is a valid count of still-open trades.
            try:
                paper = getattr(engine, "_paper_trader", None)
                open_positions = (
                    len(paper.get_open_positions())
                    if paper is not None and hasattr(paper, "get_open_positions")
                    else 0
                )
            except Exception:
                open_positions = 0
            closed_trades_live = max(0, int(live_fills) - int(open_positions))
            trades_executed = int(live_fills)
        else:
            trades_executed = trading.get("trades_executed", 0)
            closed_trades_live = 0

        health_data = {
            "service_status": "up" if engine.is_running else "down",
            "ticks_received": health.ticks_received,
            "bars_built": health.bars_built,
            "signals_generated": health.signals_generated,
            "trades_executed": trades_executed,
            "closed_trades_live": closed_trades_live,
            "last_tick_time": health.last_tick_at.isoformat() if health.last_tick_at else None,
            "connection_state": connection_state,
            "market_closed": _is_forex_market_closed(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        json_str = json.dumps(health_data, indent=2)
        _HEALTH_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = _HEALTH_JSON_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(json_str)
        os.replace(str(tmp_path), str(_HEALTH_JSON_PATH))
    except Exception as exc:
        logger.warning("Failed to write forward_test_health.json: %s", exc)


# ── Stale Log Compression (MAINT) ────────────────────────────────────────────

# Threshold for compressing stale logs. Files older than this on disk get
# gzipped and originals removed (data preserved in .gz archives). The active
# forward_test.log is rotated daily by TimedRotatingFileHandler in
# common.logging_config; this routine handles older files left over from
# prior logging configs (e.g. the `ayumi_*.log` family).
_STALE_LOG_MAX_AGE_DAYS = 7
_STALE_LOG_MIN_SIZE_BYTES = 1024  # skip empty / sub-KB stubs


def compress_stale_logs(log_dir: Path, max_age_days: int = _STALE_LOG_MAX_AGE_DAYS) -> int:
    """Gzip-compress ``*.log`` files in ``log_dir`` older than ``max_age_days``.

    Skips files that are already compressed (``*.log.gz``), tiny stubs below
    :data:`_STALE_LOG_MIN_SIZE_BYTES`, or that fail to read. After successful
    compression the original uncompressed file is removed — data is preserved
    in the ``.gz`` archive, never truly deleted.

    Returns the number of files compressed.
    """
    import gzip
    import time as _time

    if not log_dir.exists():
        return 0

    cutoff_mtime = _time.time() - (max_age_days * 86400)
    compressed = 0
    try:
        for log_file in log_dir.glob("*.log"):
            # Skip files already compressed
            if log_file.with_suffix(log_file.suffix + ".gz").exists():
                continue
            try:
                stat = log_file.stat()
            except OSError:
                continue
            # Skip small stubs and anything not old enough
            if stat.st_size < _STALE_LOG_MIN_SIZE_BYTES:
                continue
            if stat.st_mtime >= cutoff_mtime:
                continue
            gz_path = log_file.with_suffix(log_file.suffix + ".gz")
            try:
                with open(log_file, "rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
                    # chunked copy so very large logs don't balloon RSS
                    while True:
                        chunk = src.read(64 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
                # Verify the .gz is valid before removing original
                import gzip as _gzip_check
                with _gzip_check.open(gz_path, "rb") as _verify:
                    _verify.read(1024)  # read a bit to confirm integrity
                log_file.unlink()  # remove original — data preserved in .gz
                compressed += 1
            except OSError as exc:
                # Don't fail startup over a single bad log
                logger.warning("Failed to compress %s: %s", log_file, exc)
                # Remove partial .gz if it was started
                if gz_path.exists():
                    try:
                        gz_path.unlink()
                    except OSError:
                        pass
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("compress_stale_logs encountered unexpected error: %s", exc)

    if compressed:
        logger.info(
            "Compressed %d stale log(s) in %s (older than %d days)",
            compressed, log_dir, max_age_days,
        )
    return compressed


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ayumi Multi-Strategy Forward Test")
    parser.add_argument("--symbols", default="GBPUSD,USDJPY,EURUSD", help="Comma-separated symbols (default: GBPUSD,USDJPY,EURUSD)")
    parser.add_argument("--mode", choices=["paper", "live"], default=None,
                        help="Execution mode (paper/live). If not specified, derives from --live flag.")
    parser.add_argument("--live", action="store_true", help="Send real orders to cTrader via OpenAPI using account id from CTRADER_OPENAPI_ACCOUNT_ID (default: paper-only)")
    parser.add_argument("--paper-only", action="store_true", help="Run in paper-only mode (default, overridden by --live)")
    parser.add_argument("--only", default=None,
                        help="Comma-separated strategy names to keep (drops rest). e.g. --only 'Killzone Momentum'")
    args = parser.parse_args()

    # Resolve execution mode: --mode takes priority, then fall back to --live
    if args.mode:
        execution_mode = args.mode
    else:
        execution_mode = "live" if args.live else "paper"

    # Fail-closed: refuse paper mode on a live endpoint
    from adapters.ctrader.environment import Environment, _infer_environment, DEMO_HOSTS, LIVE_HOSTS
    _startup_host = os.getenv("CTRADER_HOST", "") or os.getenv("CTRADER_OPENAPI_HOST", "")
    if _startup_host:
        _startup_env = _infer_environment(_startup_host)
        if execution_mode == "paper" and _startup_env == Environment.LIVE:
            logger.error(
                "Cannot start in paper mode on a live endpoint (%s). "
            "Use --mode live or --live.",
                _startup_host,
            )
            sys.exit(1)
    symbols = [s.strip().upper().replace("/", "") for s in args.symbols.split(",")]

    # Check for files in data/ not owned by current user (defense-in-depth)
    import pwd, stat
    _current_uid = os.getuid()
    _data_dir = Path("data")
    if _data_dir.exists():
        _foreign_files = []
        for _f in _data_dir.rglob("*"):
            if _f.is_file():
                try:
                    _st = _f.stat()
                    if _st.st_uid != _current_uid:
                        _owner = pwd.getpwuid(_st.st_uid).pw_name
                        _foreign_files.append(f"{_f} (owned by {_owner})")
                except (KeyError, OSError):
                    pass
        if _foreign_files:
            logger.warning(
                "Found %d file(s) in data/ not owned by current user: %s",
                len(_foreign_files), ", ".join(_foreign_files[:5])
            )

    # Check for root-owned log files (root contamination from prior runs).
    # Remove foreign-owned .log files so they get recreated with correct
    # ownership on the next setup_logging() call.  Unix allows deleting a
    # root-owned file if the containing directory is writable by current user.
    _logs_dir = PROJECT_ROOT / "logs"
    if _logs_dir.exists():
        for _log_f in _logs_dir.glob("*.log"):
            try:
                _lst = _log_f.stat()
                if _lst.st_uid != _current_uid:
                    _log_owner = pwd.getpwuid(_lst.st_uid).pw_name
                    logger.warning(
                        "Found foreign-owned log %s (owned by %s) — removing",
                        _log_f, _log_owner,
                    )
                    _log_f.unlink()
                    logger.info(
                        "Removed foreign-owned %s (uid=%d) — will be recreated "
                        "with correct ownership (uid=%d)",
                        _log_f.name, _lst.st_uid, _current_uid,
                    )
            except (KeyError, OSError) as _log_fix_err:
                logger.error(
                    "Could not remove foreign-owned %s: %s — "
                    "run 'sudo chown %s:%s %s' to fix manually",
                    _log_f, _log_fix_err,
                    os.getenv("USER", "TacoPants"),
                    os.getenv("USER", "TacoPants"),
                    _log_f,
                )

    # ── Single-instance guard (B1) ─────────────────────────────────────────
    from adapters.ctrader.pid_guard import acquire_pid_lock
    _pid_path = PROJECT_ROOT / "data" / "forward_test.pid"
    # Guard must be acquired BEFORE logging setup floods, but we need logging
    # for the guard's own messages, so set up basic logging first.
    setup_logging(level="DEBUG")
    # Specifically enable the spot feed and execution event loggers
    logging.getLogger("ayumi.openapi_spot_feed").setLevel(logging.DEBUG)
    # Compress stale logs (>7d) from prior logging configs. Replaces
    # originals with .gz archives — data preserved, space reclaimed.
    # Cheap to run at startup; avoids `logs/` growing without bound.
    compress_stale_logs(PROJECT_ROOT / "logs")
    _pid_ctx = acquire_pid_lock(_pid_path)
    _pid_guard = _pid_ctx.__enter__()  # acquire lock, exit(1) if duplicate
    _pid_guard.write_pid()

    logger.info("=== Ayumi Multi-Strategy Forward Test (Blend Pipeline) ===")
    logger.info("Symbols: %s", symbols)

    # ── Single-Connection Architecture ────────────────────────────────────
    # The old architecture created a separate CTraderOpenApiClient to fetch
    # historical bars, disconnected, slept 3s, then connected the spot feed
    # with the same credentials → cTrader's single-session rule caused a
    # death loop. Now the spot feed connects ONCE and historical bars are
    # fetched through the same authenticated connection by the engine's
    # _preload_historical_bars() after start().

    # 1. Build credentials
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

    # 3a. Load Optuna-tuned SRMR+ variants from strategies.yaml
    yaml_srmr_strategies = _build_srmr_instances_from_yaml(_yaml_extras)

    if yaml_srmr_strategies:
        logger.info(
            "Loaded %d SRMR+ variant(s) from strategies.yaml: %s",
            len(yaml_srmr_strategies),
            [s.name for s in yaml_srmr_strategies],
        )
        for s in yaml_srmr_strategies:
            logger.info(
                "  YAML SRMR+ %s: rsi_long=%.1f rsi_short=%.1f adx_max=%.1f "
                "session_range_min=%.1f entry_near_extreme=%.1f sl_cap=%.1f",
                s.name,
                s.config.rsi_long_level,
                s.config.rsi_short_level,
                s.config.adx_max_threshold,
                s.config.session_range_min_pips,
                s.config.entry_near_extreme_pips,
                s.config.hard_cap_sl_pips,
            )
    else:
        logger.warning(
            "No SRMR+ variants loaded from strategies.yaml — "
            "falling back to single default SRMRPlusConfig()"
        )
        yaml_srmr_strategies = [SRMRPlusStrategy(config=SRMRPlusConfig())]

    for _skipped in _yaml_skipped:
        logger.info(
            "  YAML skipped entry: id=%s reason=%s",
            _skipped["id"], _skipped["reason"],
        )

    # 3b. Build the full strategy pool: YAML-tuned SRMR+ + default non-SRMR+
    strategies = yaml_srmr_strategies + [
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
        TestCanaryStrategy.from_env(),  # disabled unless AYUMI_ENABLE_CANARY=1
    ]

    # Distinguish YAML-loaded strategies from default-pool strategies in logs
    _yaml_names = {s.name for s in yaml_srmr_strategies}
    _default_names = [s.name for s in strategies if s.name not in _yaml_names]

    # Apply --only filter if specified
    if args.only:
        keep = {s.strip() for s in args.only.split(",")}
        strategies = [s for s in strategies if s.name in keep]
        logger.info("Strategy filter --only '%s': %d strategies kept", ", ".join(keep), len(strategies))

    _yaml_names_after = {s.name for s in strategies if s.name in _yaml_names}
    _default_names = [s.name for s in strategies if s.name not in _yaml_names]
    logger.info(
        "Strategy pool: %d total | YAML-loaded: %d %s | default: %d %s",
        len(strategies),
        len(yaml_srmr_strategies), sorted(_yaml_names),
        len(_default_names), _default_names,
    )

    # Verify .name properties match STRATEGY_ID_MAP keys
    for s in strategies:
        assert s.name in STRATEGY_ID_MAP, f"Strategy .name '{s.name}' not in STRATEGY_ID_MAP"
        assert s.name in STRATEGY_TIMEFRAMES, f"Strategy .name '{s.name}' not in STRATEGY_TIMEFRAMES"
    logger.info("All strategy .name properties verified against maps")

    # When --only is used, filter the maps to match the active pool
    active_names = {s.name for s in strategies}
    active_strategy_timeframes = {k: v for k, v in STRATEGY_TIMEFRAMES.items() if k in active_names}
    active_strategy_id_map = {k: v for k, v in STRATEGY_ID_MAP.items() if k in active_names}

    # 4. Build blend runner
    blend_runner = build_blend_runner()
    correlation_gate = CorrelationGate()
    heartbeat = HeartbeatTracker(interval=100)

    # 5. Build engine config with strategy_timeframes and multi-symbol
    config = ForwardTestConfig(
        symbol=symbols[0],
        symbols=symbols,
        starting_balance=10_000.0,
        min_confidence=0.30,  # Match SRF-validated threshold
        max_bars_per_symbol=500,
        min_bars_for_evaluation=55,
        live_mode=(execution_mode == "live"),
        execution_mode=execution_mode,
        strategy_timeframes=active_strategy_timeframes,
        preload_bar_count=200,  # bars per symbol/timeframe fetched through spot feed
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
        strategy_id_map=active_strategy_id_map,
        blend_mode=True,
    )

    # Release correlation slots when paper positions close.
    engine.register_callback("on_position_closed", engine.on_position_closed_release)

    # Historical bars are fetched automatically by engine.start() through
    # the single spot feed connection (_preload_historical_bars). No separate
    # client connection needed.

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
    logger.info("=== STARTING MULTI-STRATEGY FORWARD TEST (Single-Connection) ===")
    logger.info("Pipeline: SRMR+ + Killzone + Momentum + SessionRangeMR → Correlation Gate → Blend Runner → cTrader")
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

    # ── Startup reconciliation (card 0e0338d4) ─────────────────────────────
    # engine.start() already calls _seed_existing_positions() which ADDS
    # to the sizer's _open_positions dict, but does not clear phantom
    # entries left over from the _open_risk restore path or duplicate
    # registrations. Run a nuke-and-rebuild reconciliation now so the
    # sizer's positions_carried count matches the broker exactly from
    # tick #1 of the new session.
    _broker_positions: list = []
    _feed = getattr(engine, "_market_feed", None)
    if _feed is not None and hasattr(_feed, "reconcile"):
        try:
            _broker_positions = _feed.reconcile() or []
            logger.info(
                "Startup reconciliation: broker reports %d open position(s)",
                len(_broker_positions),
            )
        except Exception as _recon_exc:
            logger.warning(
                "Startup reconciliation: broker.reconcile() failed (non-fatal): %s",
                _recon_exc,
            )
            _broker_positions = []
    try:
        _recon_result = blend_runner.reconcile_with_broker(_broker_positions)
        logger.info(
            "Startup reconciliation result: positions %d→%d (seeded=%d, "
            "diverged=%s, open_risk $%.2f→$%.2f)",
            _recon_result["before_count"],
            _recon_result["after_count"],
            _recon_result["seeded_count"],
            _recon_result["diverged"],
            _recon_result["before_open_risk"],
            _recon_result["after_open_risk"],
        )
    except Exception as _recon_exc:
        logger.warning(
            "Startup reconciliation: blend_runner.reconcile_with_broker() "
            "failed (non-fatal, continuing with engine-seeded positions): %s",
            _recon_exc,
        )

    # Write health JSON immediately on startup to clear any stale "down" state
    write_forward_test_health_json(engine)
    logger.info("Forward test health JSON written on startup")

    # ── Equity tracker (A8) ─────────────────────────────────────────────
    _equity_tracker = EquityTracker(
        data_dir=PROJECT_ROOT / "data",
        starting_balance=10_000.0,
    )
    _equity_record_interval = 300.0  # 5 minutes
    _last_equity_record = 0.0  # record immediately on first loop
    _last_balance_sync = 0.0  # sync RiskGuard from cTrader every 5 min
    _reconcile_interval = 300.0  # 5 minutes — sizer/broker drift check
    _last_reconcile = 0.0  # reconcile immediately on first loop

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
                    _paper_trades = t.get("trades_executed", 0)
                    _paper_balance = t.get("current_balance", 0.0)
                    _live_mode = (execution_mode == "live")

                    # Fetch real cTrader balance in live mode
                    _balance_str = f"balance=${_paper_balance:.2f}"
                    if _live_mode and hasattr(engine, "_market_feed") and engine._market_feed is not None:
                        try:
                            from adapters.ctrader.account_state import get_balance as _get_balance
                            _feed = engine._market_feed
                            _real_balance = _get_balance(
                                _feed.connection,
                                _feed.ctid_account_id,
                                timeout=5.0,
                            )
                            if _real_balance is not None:
                                engine._live_balance = float(_real_balance)
                                _balance_str = f"ctrader=${float(_real_balance):.2f}"
                            else:
                                _balance_str = f"ctrader=N/A (timeout)"
                        except Exception as _bal_err:
                            _balance_str = f"ctrader=ERR ({_bal_err})"
                    _stats_fails = getattr(engine, "_stats_fail_count", 0)
                    # Periodic balance sync from cTrader → RiskGuard (every 5 min)
                    if now - _last_balance_sync >= 300.0:
                        _last_balance_sync = now
                        if hasattr(engine, '_sync_live_balance'):
                            engine._sync_live_balance()
                        # Activate live-balance mode on RiskGuard so that
                        # PaperTrader.update_market_prices tick recalculation
                        # does not overwrite the synced cTrader balance.
                        # PaperTrader recalculates _current_balance from
                        # starting_balance + pnl on every tick, which reverts
                        # the balance to $10K between 5-min sync intervals.
                        # sync_live_balance() sets a flag that makes
                        # update_balance() a no-op until the next sync.
                        # Daily counter reset hook (card 18d69d04): when the
                        # 17:00 America/Toronto trading-day boundary has
                        # crossed since the last sync, reset the per-day
                        # health counters (signals_sent, signals_failed_live,
                        # signals_pending, signals_cancelled, signals_rejected,
                        # signals_traded, signals_accepted).
                        if hasattr(engine, '_paper_trader') and engine._paper_trader:
                            _rg_for_reset = getattr(engine._paper_trader, '_risk_guard', None)
                            if _rg_for_reset is not None:
                                _current_trading_day = _rg_for_reset._current_trading_day()
                                _last_health_day = getattr(
                                    engine._health, '_last_health_trading_day', None,
                                )
                                if (
                                    _last_health_day is None
                                    or _current_trading_day != _last_health_day
                                ):
                                    engine._health.reset_daily_counters()
                                    engine._health._last_health_trading_day = (
                                        _current_trading_day
                                    )
                                    logger.info(
                                        "[B5 Daily Reset] counters reset at trading_day=%s "
                                        "(17:00 America/Toronto boundary crossed)",
                                        _current_trading_day.isoformat(),
                                    )
                        if hasattr(engine, '_live_balance') and engine._live_balance:
                            _rg_pre = getattr(engine._paper_trader, "_risk_guard", None)
                            if _rg_pre is not None:
                                _rg_pre.sync_live_balance(engine._live_balance)

                    # Risk guard status (B5 health extension — A6)
                    # Uses two-balance model: starting=$10K baseline, live=cTrader
                    _rg = getattr(engine._paper_trader, "_risk_guard", None)
                    if _rg is not None:
                        _start_bal = _rg._starting_balance
                        _bal = _rg._current_balance
                        _daily_pnl = _bal - _rg._daily_start_balance
                        _dd_pct = (_start_bal - _bal) / _start_bal * 100 if _start_bal > 0 else 0.0
                        _breaker = "ON" if _rg._circuit_breaker_triggered else "OFF"
                        _halt = "NONE"
                        if _rg._blocked_until is not None:
                            _halt = f"until {_rg._blocked_until.isoformat()}"
                        _risk_str = (
                            f"risk: starting=${_start_bal:.2f} balance=${_bal:.2f} "
                            f"daily_pnl=${_daily_pnl:.2f} dd={_dd_pct:.2f}% "
                            f"dd_breaker={_breaker} halt={_halt}"
                        )
                    else:
                        _risk_str = "risk: N/A"

                    logger.info(
                        "[B5 Health] ticks=%d tps=%.2f bars=%d signals=%d "
                        "trades=%d live_fills=%d signals_failed_live=%d "
                        "stats_fails=%d %s %s uptime=%.0fs",
                        h.get("ticks_received", 0),
                        h.get("ticks_per_second", 0.0),
                        engine.health.bars_built,
                        engine.health.signals_generated,
                        _paper_trades,
                        _live_fills,
                        engine.health.signals_failed_live,
                        _stats_fails,
                        _balance_str,
                        _risk_str,
                        h.get("uptime_sec", 0),
                    )
                    # Alert if live mode has zero fills despite signals.
                    # Distinguish "orders reaching broker but rejected" from
                    # "orders not reaching broker" so operators can diagnose
                    # the actual failure mode without grepping rejection logs.
                    if _live_mode and engine.health.signals_generated > 0 and _live_fills == 0:
                        _failed = engine.health.signals_failed_live
                        if _failed > 0:
                            logger.warning(
                                "[B5 Health] ⚠️  live_fills=0 signals_generated=%d "
                                "signals_failed_live=%d — orders reaching broker "
                                "but being rejected (see rejection log for errorCode)",
                                engine.health.signals_generated,
                                _failed,
                            )
                        else:
                            logger.warning(
                                "[B5 Health] ⚠️  live_fills=0 but signals_generated=%d — "
                                "orders may not be reaching cTrader",
                                engine.health.signals_generated,
                            )
                    # Tick-to-bar pipeline health (Amendment 4)
                    # During market-closed hours (Fri 21:00 UTC → Sun 21:00 UTC),
                    # cTrader delivers stale/dribble ticks but no new bars form —
                    # that's expected. Downgrade to INFO so we don't generate
                    # false-positive stall warnings every health cycle.
                    #
                    # Amendment 5 (tick-to-bar stall fix): The bars_built counter
                    # only counts bars finalized from LIVE ticks at period
                    # boundaries — it does NOT include preloaded historical bars.
                    # With 200 preloaded bars and an H1 timeframe, bars_built
                    # stays 0 until the first hour boundary (up to 60 min),
                    # causing false-positive stall warnings every 60s. Fix:
                    # count total bars (including preloaded) before warning.
                    if h.get("ticks_received", 0) > 0 and engine.health.bars_built == 0:
                        # Count total bars across all keys, including preloaded
                        # and currently-forming bars (mirrors engine's internal
                        # B5 check at line ~2756 in forward_test_engine.py).
                        _total_bars_all = (
                            sum(len(v) for v in engine._bars.values())
                            + sum(1 for v in engine._current_bar.values() if v is not None)
                        )
                        if _total_bars_all > 0:
                            # Preloaded/forming bars exist — pipeline is healthy,
                            # just waiting for first live bar boundary crossing.
                            logger.debug(
                                "[B5 Pipeline] ticks=%d bars_built=%d total_bars=%d "
                                "— awaiting first bar boundary (preloaded bars available)",
                                h.get("ticks_received", 0),
                                engine.health.bars_built,
                                _total_bars_all,
                            )
                        elif _is_forex_market_closed():
                            logger.info(
                                "[B5 Pipeline] Market closed — ticks=%d bars=%d "
                                "(idle, expected)",
                                h.get("ticks_received", 0),
                                engine.health.bars_built,
                            )
                        else:
                            logger.warning(
                                "[B5 Pipeline] Ticks received (%d) but zero bars built — "
                                "tick-to-bar pipeline may be stalled",
                                h.get("ticks_received", 0),
                            )

                    # Write health JSON for external watchdogs / dashboards
                    write_forward_test_health_json(engine)

                    # ── Periodic sizer/broker reconciliation (card 0e0338d4)
                    # Every 5 min: query cTrader for open positions and
                    # nuke-and-rebuild the sizer's _open_positions dict.
                    # Catches any drift introduced by duplicate
                    # registration, late close callbacks, or the
                    # _legacy_open_risk restore path. The first call
                    # fires immediately on the first health tick
                    # (_last_reconcile starts at 0).
                    if now - _last_reconcile >= _reconcile_interval:
                        _last_reconcile = now
                        _feed_recon = getattr(engine, "_market_feed", None)
                        if _feed_recon is not None and hasattr(_feed_recon, "reconcile"):
                            try:
                                _positions_now = _feed_recon.reconcile() or []
                                _recon = blend_runner.reconcile_with_broker(_positions_now)
                                if _recon.get("diverged"):
                                    logger.warning(
                                        "[B5 Reconcile] sizer/broker drift: "
                                        "positions %d→%d (seeded=%d, "
                                        "open_risk $%.2f→$%.2f)",
                                        _recon["before_count"],
                                        _recon["after_count"],
                                        _recon["seeded_count"],
                                        _recon["before_open_risk"],
                                        _recon["after_open_risk"],
                                    )
                                else:
                                    logger.info(
                                        "[B5 Reconcile] sizer/broker in sync: "
                                        "positions=%d, open_risk=$%.2f",
                                        _recon["after_count"],
                                        _recon["after_open_risk"],
                                    )
                            except Exception as _recon_err:
                                logger.warning(
                                    "[B5 Reconcile] failed (non-fatal): %s",
                                    _recon_err,
                                )

                    # ── Equity snapshot (A8) — every 5 min ──────────────────
                    if now - _last_equity_record >= _equity_record_interval:
                        _last_equity_record = now
                        try:
                            # Determine current balance and trade count
                            _eq_balance = _paper_balance
                            if hasattr(engine, "_live_balance"):
                                _eq_balance = engine._live_balance
                            _eq_trades = t.get("trades_executed", 0)
                            if _live_mode:
                                _eq_trades = getattr(engine, "_live_fill_count", 0)
                            _equity_tracker.record(_eq_balance, _eq_trades)
                            logger.info(
                                "[A8 Equity] Recorded: balance=$%.2f trades=%d",
                                _eq_balance, _eq_trades,
                            )
                        except Exception as _eq_err:
                            logger.warning("[A8 Equity] Record failed: %s", _eq_err)
                except Exception as exc:
                    logger.warning("[B5 Health] Error logging health: %s", exc)
    except KeyboardInterrupt:
        shutdown(None, None)
    finally:
        # Write daily equity report on exit (A8)
        try:
            _report_path = _equity_tracker.write_daily_report()
            if _report_path:
                logger.info("[A8 Equity] Daily report written: %s", _report_path)
        except Exception:
            pass
        # Release PID lock on exit
        try:
            _pid_ctx.__exit__(None, None, None)
        except Exception:
            pass


if __name__ == "__main__":
    main()
