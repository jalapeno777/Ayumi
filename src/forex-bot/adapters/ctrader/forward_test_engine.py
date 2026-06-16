"""Forward Test Engine — wires cTrader live market data into the PaperTrader.

Bridges ``LiveMarketDataFeed`` (tick streaming) with ``PaperTrader`` (signal
processing / risk / P&L tracking) and ``cTraderLiveAdapter`` (strategy
evaluation) so the forward test runs on real market data end-to-end.

Usage::

    engine = ForwardTestEngine(config, strategies=[my_strategy])
    engine.start()
    ...
    engine.stop()
"""

import json
import logging
import os
import signal as sig_module
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    pass

from backtest.engine import Bar, MarketState
from backtest.strategies import ISignalStrategy

from .auth import CTraderAuth
from .kill_switch import KillSwitchManager
from .market_data_feed import Tick
from .open_api_spot_feed import OpenApiSpotFeed
from .models import cTraderCredentials, TradeSignal, TradeDirection
from .order_manager import PositionSizeConfig
from .paper_trader import PaperTrader
from .position_monitor import PositionMonitor
from .risk_guard import FTMOConfig
from .signal_adapter import cTraderLiveAdapter
from .trade_logger import TradeLogger

from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATradeSide,
)

logger = logging.getLogger("ayumi.forward_test")

_DEFAULT_RECONNECT_DELAY_SEC = 5.0
_DEFAULT_MAX_RECONNECT_DELAY_SEC = 120.0
_DEFAULT_STALE_TICK_THRESHOLD_SEC = 300.0
_DEFAULT_MAX_RECONNECT_ATTEMPTS = 20

# Heartbeat writer defaults
_HEARTBEAT_FILE = "data/heartbeat_trading.json"
_HEARTBEAT_INTERVAL_SEC = 5.0  # piggybacks on health monitor loop

# Error rate monitor defaults
_ERROR_RATE_WINDOW_SEC = 60.0
_ERROR_RATE_THRESHOLD_PCT = 0.50  # >50% error rate in 60s window → freeze

_WEEKEND_CLOSE_HOUR_UTC = 21
_WEEKEND_CLOSE_MINUTE_UTC = 55
_WEEKEND_OPEN_HOUR_UTC = 21


def _is_forex_market_closed() -> bool:
    now = datetime.now(timezone.utc)
    if now.weekday() == 4:
        if now.hour > _WEEKEND_CLOSE_HOUR_UTC:
            return True
        if (
            now.hour == _WEEKEND_CLOSE_HOUR_UTC
            and now.minute >= _WEEKEND_CLOSE_MINUTE_UTC
        ):
            return True
    if now.weekday() == 5:
        return True
    if now.weekday() == 6:
        if now.hour < _WEEKEND_OPEN_HOUR_UTC:
            return True
        return False
    if now.weekday() == 0 and now.hour < _WEEKEND_OPEN_HOUR_UTC:
        return True
    return False


@dataclass
class ForwardTestConfig:
    symbol: str = "GBPUSD"
    symbols: list[str] = None  # multi-symbol support; if None, defaults to [symbol]
    starting_balance: float = 100_000.0
    min_confidence: float = 0.50
    max_bars_per_symbol: int = 500
    min_bars_for_evaluation: int = 50
    quote_host: str = "live-uk-eqx-01.p.c-trader.com"
    quote_port: int = 5211
    use_ssl: bool = True
    quote_sender_sub_id: str = "QUOTE"
    quote_target_sub_id: Optional[str] = None
    log_dir: str = "logs/trades"
    stats_interval_sec: float = 60.0
    live_mode: bool = False
    trade_host: Optional[str] = None
    trade_port: Optional[int] = None
    evaluation_interval_sec: float = 1.0
    bar_period_minutes: int = 60
    stale_tick_threshold_sec: float = 900.0  # Increased from 400.0 to reduce stale-tick warnings during quiet periods
    reconnect_delay_sec: float = _DEFAULT_RECONNECT_DELAY_SEC
    max_reconnect_delay_sec: float = _DEFAULT_MAX_RECONNECT_DELAY_SEC
    max_reconnect_attempts: int = _DEFAULT_MAX_RECONNECT_ATTEMPTS
    health_monitor_interval_sec: float = 5.0  # Runs every 5s for heartbeat + error monitoring
    clear_stuck_positions_on_start: bool = False
    reset_on_start: bool = False
    strategy_timeframes: dict[str, int] = None  # strategy_name -> period_minutes; empty/None = all use bar_period_minutes
    use_openapi_feed: bool = False  # True = Open API spot feed, False = FIX feed
    openapi_host: str = "demo.ctraderapi.com"
    openapi_port: int = 5035

    def __post_init__(self):
        if self.strategy_timeframes is None:
            self.strategy_timeframes = {}
        if self.symbols is None:
            self.symbols = [self.symbol]


@dataclass
class ForwardTestHealth:
    connected: bool = False
    last_tick_at: Optional[datetime] = None
    ticks_received: int = 0
    ticks_per_second: float = 0.0
    signals_generated: int = 0
    signals_traded: int = 0
    signals_rejected: int = 0
    uptime_sec: float = 0.0
    evaluation_errors: int = 0
    reconnection_attempts: int = 0
    reconnection_successes: int = 0
    bars_built: int = 0
    consecutive_risk_rejections: int = 0


class ForwardTestEngine:
    # INVARIANT: Strategy evaluation only occurs on CLOSED bars.
    # - self._bars contains finalized bars only
    # - self._current_bar contains the FORMING bar (excluded from evaluation)
    # - Evaluation triggers ONLY when _bar_completed flag is set (bar just finalized)
    # - Never pass self._current_bar into MarketState or strategy evaluation

    # Allowed timeframe whitelist
    _ALLOWED_TIMEFRAMES = {15, 60, 240}

    @staticmethod
    def _bar_key(symbol: str, period_minutes: int) -> str:
        return f"{symbol}:{period_minutes}"

    def __init__(
        self,
        config: ForwardTestConfig,
        strategies: list[ISignalStrategy],
        ftmo_config: Optional[FTMOConfig] = None,
        position_config: Optional[PositionSizeConfig] = None,
        credentials: Optional[cTraderCredentials] = None,
        *,
        blend_mode: bool = False,
    ):
        self._config = config
        self._strategies = strategies
        self._ftmo_config = ftmo_config
        self._position_config = position_config
        self._blend_mode = blend_mode
        self._running = False
        self._lock = threading.RLock()
        self._eval_semaphore = threading.Semaphore(1)

        # Derive required timeframes
        self._strategy_timeframes: dict[str, int] = config.strategy_timeframes or {}
        self._required_timeframes: set[int] = (
            set(self._strategy_timeframes.values()) if self._strategy_timeframes
            else {config.bar_period_minutes}
        )

        # Startup assertion: whitelist check
        for tf in self._required_timeframes:
            assert tf in self._ALLOWED_TIMEFRAMES, (
                f"Timeframe {tf} not in allowed whitelist {self._ALLOWED_TIMEFRAMES}"
            )

        # Startup assertion: every key in strategy_timeframes must match a registered strategy .name
        if self._strategy_timeframes:
            registered_names = {s.name for s in strategies}
            for stg_name in self._strategy_timeframes:
                assert stg_name in registered_names, (
                    f"strategy_timeframes key '{stg_name}' does not match any registered "
                    f"strategy .name property. Registered: {sorted(registered_names)}"
                )

        self._bars: dict[str, list[Bar]] = {}  # key = _bar_key(symbol, period_minutes)
        self._current_bar: dict[str, Optional[Bar]] = {}  # same key scheme
        self._paper_trader: Optional[PaperTrader] = None
        self._position_monitor: Optional[PositionMonitor] = None
        self._market_feed: Optional[LiveMarketDataFeed] = None
        self._live_adapter: Optional[cTraderLiveAdapter] = None
        self._trade_logger: Optional[TradeLogger] = None
        self._live_client = None
        self._preload_complete: bool = False  # T2: blocks evaluation until bars loaded
        self._credentials = credentials

        self._start_time: Optional[datetime] = None
        self._tick_timestamps: list[datetime] = []
        self._tick_rate_window_sec = 10.0

        self._callbacks: list[tuple[str, "Callable"]] = []
        self._health = ForwardTestHealth()

        self._last_evaluation_at: float = 0.0

        # Bar-completion flags: set when a bar is finalized for a timeframe
        # key = _bar_key(symbol, timeframe), value = True when new bar completed
        self._bar_completed: dict[str, bool] = {}


        # Rejection circuit breaker (T5)
        self._consecutive_risk_rejections: int = 0
        self._rejection_cooldown_until: float = 0.0  # monotonic timestamp
        self._reconnect_delay: float = config.reconnect_delay_sec
        self._last_reconnect_attempt_at: float = 0.0
        self._health_monitor_thread: Optional[threading.Thread] = None
        self._stop_health_monitor = threading.Event()
        self._current_spread: float = 0.0
        self._current_bid: float = 0.0
        self._current_ask: float = 0.0

        # Kill switch — global safety system
        self._kill_switch = KillSwitchManager()
        if self._kill_switch.is_globally_killed():
            logger.critical(
                "STARTUP: Kill switch is ACTIVE (%s) — trading will be blocked",
                self._kill_switch.get_status().get('reason', 'unknown'),
            )

        # Heartbeat writer
        self._heartbeat_file = _HEARTBEAT_FILE
        self._heartbeat_pid = os.getpid()

        # Error rate monitor — rolling 60s window
        self._eval_timestamps: deque[float] = deque()  # monotonic timestamps of evaluations
        self._eval_errors: deque[float] = deque()  # monotonic timestamps of errors
        self._feed_disconnect_frozen = False  # track if we already froze for feed disconnect

        # S1: Per-strategy diagnostic counters
        self._strategy_eval_counts: dict[str, int] = {s.name: 0 for s in strategies}
        self._strategy_no_signal_counts: dict[str, int] = {s.name: 0 for s in strategies}
        self._strategy_last_eval: dict[str, float] = {s.name: 0.0 for s in strategies}

    @property
    def health(self) -> ForwardTestHealth:
        with self._lock:
            return ForwardTestHealth(
                connected=self._market_feed.is_running if self._market_feed else False,
                last_tick_at=self._health.last_tick_at,
                ticks_received=self._health.ticks_received,
                ticks_per_second=self._health.ticks_per_second,
                signals_generated=self._health.signals_generated,
                signals_traded=self._health.signals_traded,
                signals_rejected=self._health.signals_rejected,
                uptime_sec=self._health.uptime_sec,
                evaluation_errors=self._health.evaluation_errors,
                reconnection_attempts=self._health.reconnection_attempts,
                reconnection_successes=self._health.reconnection_successes,
                bars_built=self._health.bars_built,
            )

    @property
    def paper_trader(self) -> Optional[PaperTrader]:
        return self._paper_trader

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        if self._running:
            logger.warning("ForwardTestEngine already running")
            return True

        if not self._validate_credentials():
            logger.error("Invalid credentials — aborting start")
            return False

        self._build_components()
        self._wire_callbacks()

        if self._config.clear_stuck_positions_on_start and self._paper_trader:
            cleared = self._paper_trader.clear_stuck_positions()
            logger.info("Cleared %d stuck position(s) on start", cleared)

        if self._config.reset_on_start and self._paper_trader:
            self._paper_trader.reset()
            logger.info("Paper trader reset on start")

        if not self._start_market_feed():
            logger.error("Failed to start market data feed")
            return False

        # T2: Preload bars from API after feed is connected
        self._preload_complete = False
        if isinstance(self._market_feed, OpenApiSpotFeed):
            self._preload_historical_bars()

        self._running = True
        self._start_time = datetime.now(timezone.utc)

        self._stop_health_monitor.clear()
        self._health_monitor_thread = threading.Thread(
            target=self._health_monitor_loop,
            name="forward-test-health-monitor",
            daemon=True,
        )
        self._health_monitor_thread.start()

        try:
            sig_module.signal(sig_module.SIGINT, self._on_shutdown)
            sig_module.signal(sig_module.SIGTERM, self._on_shutdown)
        except (ValueError, RuntimeError):
            logger.debug(
                "Signal handler registration not available (subprocess/thread context)"
            )

        logger.info(
            "Forward test started: symbols=%s strategies=%s mode=%s eval_interval=%.1fs bar_period=%dm",
            self._config.symbols,
            [s.name for s in self._strategies],
            "LIVE" if self._config.live_mode else "PAPER",
            self._config.evaluation_interval_sec,
            self._config.bar_period_minutes,
        )

        # B5: Startup diagnostic
        logger.info("[B5 Startup] Strategy list: %s", [s.name for s in self._strategies])
        logger.info("[B5 Startup] Symbols: %s", self._config.symbols)
        logger.info("[B5 Startup] Bar period: %dm", self._config.bar_period_minutes)
        logger.info("[B5 Startup] Min confidence: %.2f", self._config.min_confidence)
        logger.info("[B5 Startup] Min bars for evaluation: %d", self._config.min_bars_for_evaluation)
        logger.info(
            "[B5 Startup] Strategy timeframes: %s",
            self._strategy_timeframes or {s.name: self._config.bar_period_minutes for s in self._strategies},
        )
        logger.info(
            "[B5 Startup] Required timeframes: %s",
            sorted(self._required_timeframes),
        )
        return True

    def stop(self):
        if not self._running:
            return

        self._running = False
        self._stop_health_monitor.set()

        if self._health_monitor_thread is not None:
            self._health_monitor_thread.join(timeout=10.0)
            self._health_monitor_thread = None

        with self._lock:
            for key in list(self._current_bar.keys()):
                self._finalize_and_store_bar(key)

        if self._market_feed:
            self._market_feed.stop()

        # Write final heartbeat with engine_running=false (clean shutdown signal)
        self._write_heartbeat()

        self._update_health()
        stats = self._paper_trader.get_stats() if self._paper_trader else None
        if stats:
            logger.info(
                "Forward test stopped: balance=%.2f trades=%d pnl=%.2f errors=%d reconnects=%d",
                stats.current_balance,
                stats.trades_executed,
                stats.current_balance - stats.starting_balance,
                self._health.evaluation_errors,
                self._health.reconnection_attempts,
            )

    def register_callback(self, event: str, callback: Callable):
        self._callbacks.append((event, callback))

    def _validate_credentials(self) -> bool:
        # Validate quote credentials (used for market data)
        creds = self._build_quote_credentials()
        if not creds.host:
            logger.error("Credential validation: host is empty")
            return False
        if not creds.username:
            logger.error("Credential validation: username (CTRADER_ACCOUNT) is empty")
            return False
        if not creds.password:
            logger.error("Credential validation: password (CTRADER_PASSWORD) is empty")
            return False
        if not creds.sender_comp_id:
            logger.warning(
                "Credential validation: sender_comp_id is empty — may cause FIX logon failure"
            )
        return True

    def _build_live_credentials(self) -> dict | None:
        """Build kwargs dict for the cTrader Open API spot feed via CTraderAuth."""
        try:
            auth = CTraderAuth.create()
        except Exception as exc:
            logger.error("Failed to load cTrader credentials via CTraderAuth: %s", exc)
            return None

        access_token = auth.access_token
        if not access_token:
            logger.error("cTrader access token is empty after CTraderAuth.load_credentials()")
            return None

        return {
            "ctid_account_id": auth.account_id,
            "client_id": auth.client_id,
            "client_secret": auth.client_secret,
            "access_token": access_token,
            "refresh_token": auth.refresh_token or None,
            "host": self._config.openapi_host,
            "port": self._config.openapi_port,
        }

    def _build_components(self):
        cfg = self._config
        ftmo = self._ftmo_config or FTMOConfig()
        pos_cfg = self._position_config or PositionSizeConfig()

        if cfg.live_mode:
            live_creds = self._build_live_credentials()
            if live_creds is None:
                logger.error("Cannot build live spot feed: missing credentials")
                return

            self._market_feed = OpenApiSpotFeed(**live_creds)
            self._market_feed.set_kill_switch(self._kill_switch)
            logger.info("OpenApiSpotFeed constructed for live_mode")

        self._paper_trader = PaperTrader(
            ftmo_config=ftmo,
            position_config=pos_cfg,
            starting_balance=cfg.starting_balance,
            api_client=self._market_feed,
        )

        self._live_adapter = cTraderLiveAdapter(
            paper_trader=self._paper_trader,
            strategies=self._strategies,
            symbols=cfg.symbols,
            # In live mode we return signals from the adapter and execute them
            # directly against the OpenApiSpotFeed so the engine controls real
            # order placement instead of relying on the paper-trader chain.
            blend_mode=self._blend_mode or cfg.live_mode,
        )

        strategy_names = "+".join(s.name for s in self._strategies)
        self._trade_logger = TradeLogger(
            log_dir=cfg.log_dir,
            strategy_name=strategy_names,
        )

        self._paper_trader.register_callback(
            "on_trade_executed", self._on_trade_executed
        )
        self._paper_trader.register_callback(
            "on_position_closed", self._on_position_closed
        )

        # Position monitor — centralized lifecycle tracking
        self._position_monitor = PositionMonitor(
            order_manager=self._paper_trader._order_manager,
            risk_guard=self._paper_trader._risk_guard,
            kill_switch=self._kill_switch,
        )

        # Share kill switch with risk guard so circuit breaker uses
        # the same instance (avoids creating a new KillSwitchManager
        # that writes to production state from tests)
        self._paper_trader._risk_guard.set_kill_switch(self._kill_switch)

    def _wire_callbacks(self):
        if self._market_feed is None:
            return

        self._market_feed.on_tick(self._on_tick)

    def _start_market_feed(self) -> bool:
        cfg = self._config

        # Use OpenAPI feed by default (FIX feed archived)
        use_fix = getattr(cfg, 'use_fix_feed', False)
        if not use_fix:
            return self._start_openapi_feed()

        # multi-symbol routing — candidate for extraction if complexity grows
        subscribe_names = []
        for sym in cfg.symbols:
            symbol_key = sym.upper().replace("/", "")
            subscribe_name = self._resolve_feed_symbol_name(symbol_key)
            if subscribe_name is None:
                logger.error("Cannot resolve symbol %s for market data feed", sym)
                return False
            subscribe_names.append(subscribe_name)

        success = self._market_feed.start(auto_subscribe=subscribe_names)
        if success:
            logger.info("Market data feed connected for %s", cfg.symbols)
        return success

    def _resolve_feed_symbol_name(self, symbol_key: str) -> Optional[str]:
        name_to_id = self._market_feed.name_to_id if self._market_feed else {}
        feed_names = list(name_to_id.keys())

        slash_name = symbol_key[:3] + "/" + symbol_key[3:]
        no_slash_name = symbol_key

        for candidate in [slash_name, no_slash_name]:
            if candidate in feed_names:
                return candidate

        logger.warning(
            "Symbol %s not found in feed symbol map: %s",
            symbol_key,
            feed_names,
        )
        return None

    def _start_openapi_feed(self) -> bool:
        """Start the Open API spot feed instead of the FIX feed."""
        if self._market_feed is None:
            live_creds = self._build_live_credentials()
            if live_creds is None:
                logger.error("Missing Open API credentials in env")
                return False

            self._market_feed = OpenApiSpotFeed(**live_creds)
            self._market_feed.set_kill_switch(self._kill_switch)
            self._wire_callbacks()

        subscribe_names = []
        for sym in self._config.symbols:
            subscribe_names.append(sym.upper().replace("/", ""))

        success = self._market_feed.start(auto_subscribe=subscribe_names)
        if success:
            logger.info("Open API spot feed connected for %s", self._config.symbols)
        return success

    def _build_quote_credentials(self) -> cTraderCredentials:
        from dotenv import load_dotenv
        import os
        from pathlib import Path

        env_path = Path(__file__).resolve().parents[4] / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=True)

        host = os.environ.get("CTRADER_HOST", self._config.quote_host)
        port = int(
            os.environ.get("CTRADER_READONLY_SSL_PORT", str(self._config.quote_port))
        )

        quote_sender_sub_id = os.environ.get("CTRADER_QUOTE_SENDER_SUB_ID") or self._config.quote_sender_sub_id
        _raw_target = os.environ.get("CTRADER_QUOTE_TARGET_SUB_ID")
        quote_target_sub_id = _raw_target or self._config.quote_target_sub_id or quote_sender_sub_id

        return cTraderCredentials(
            host=host,
            port=port,
            use_ssl=self._config.use_ssl,
            sender_comp_id=os.environ.get("CTRADER_SENDER_COMP_ID", ""),
            target_comp_id=os.environ.get("CTRADER_TARGET_COMP_ID", "cServer"),
            sender_sub_id=quote_sender_sub_id,
            target_sub_id=quote_target_sub_id,
            username=os.environ.get("CTRADER_ACCOUNT", ""),
            password=os.environ.get("CTRADER_PASSWORD", ""),
        )

    def _bar_period_start(self, ts: datetime, period_minutes: int = 0) -> datetime:
        minutes = period_minutes or self._config.bar_period_minutes
        return ts.replace(second=0, microsecond=0) - timedelta(
            minutes=ts.minute % minutes
        )

    def _finalize_current_bar(self, key: str) -> Optional[Bar]:
        current = self._current_bar.get(key)
        if current is None:
            return None
        finalized = Bar(
            time=current.time,
            open=current.open,
            high=current.high,
            low=current.low,
            close=current.close,
            volume=current.volume,
        )
        self._current_bar[key] = None
        return finalized

    def _assert_bar_integrity(self, bar: Bar):
        """Verify bar OHLC integrity."""
        assert bar.high >= max(bar.open, bar.close), (
            f"Bar integrity fail: high={bar.high} < max(open={bar.open}, close={bar.close})"
        )
        assert bar.low <= min(bar.open, bar.close), (
            f"Bar integrity fail: low={bar.low} > min(open={bar.open}, close={bar.close})"
        )

    def _store_bar(self, key: str, bar: Bar):
        self._assert_bar_integrity(bar)
        if key not in self._bars:
            self._bars[key] = []
        self._bars[key].append(bar)
        self._health.bars_built += 1
        if len(self._bars[key]) > self._config.max_bars_per_symbol:
            self._bars[key] = self._bars[key][-self._config.max_bars_per_symbol :]

    def _finalize_and_store_bar(self, key: str) -> Optional[Bar]:
        finalized = self._finalize_current_bar(key)
        if finalized is not None:
            self._store_bar(key, finalized)
            # Mark this timeframe as having a new completed bar
            self._bar_completed[key] = True
        return finalized

    def _update_current_bar(self, tick: Tick, key: str, bar_time: datetime) -> Bar:
        current = self._current_bar.get(key)

        if current is not None and current.time == bar_time:
            mid = tick.mid
            updated = Bar(
                time=current.time,
                open=current.open,
                high=max(current.high, tick.ask),
                low=min(current.low, tick.bid),
                close=mid,
                volume=current.volume + 1,
            )
            self._current_bar[key] = updated
            return updated

        self._finalize_and_store_bar(key)

        new_bar = Bar(
            time=bar_time,
            open=tick.mid,
            high=tick.ask,
            low=tick.bid,
            close=tick.mid,
            volume=1,
        )
        self._current_bar[key] = new_bar
        return new_bar

    def _on_tick(self, tick: Tick):
        with self._lock:
            self._health.ticks_received += 1
            now = datetime.now(timezone.utc)
            self._health.last_tick_at = now

            self._tick_timestamps.append(now)
            cutoff = now.timestamp() - self._tick_rate_window_sec
            self._tick_timestamps = [
                t for t in self._tick_timestamps if t.timestamp() > cutoff
            ]
            if self._tick_timestamps:
                window = (
                    self._tick_timestamps[-1].timestamp()
                    - self._tick_timestamps[0].timestamp()
                )
                self._health.ticks_per_second = (
                    len(self._tick_timestamps) / window if window > 0 else 0.0
                )

        symbol_name = self._resolve_symbol_name(tick)
        if symbol_name is None or symbol_name not in self._config.symbols:
            return

        # Build bars for ALL required timeframes from this tick
        with self._lock:
            for tf in self._required_timeframes:
                bar_time = self._bar_period_start(tick.timestamp, period_minutes=tf)
                key = self._bar_key(symbol_name, tf)
                self._update_current_bar(tick, key, bar_time)

            self._update_paper_trader_prices(tick, symbol_name)
            self._current_spread = tick.spread
            self._current_bid = tick.bid
            self._current_ask = tick.ask

            # Phase 1D: Update position monitor (MAE/MFE, water marks, time tracking)
            if self._position_monitor is not None:
                self._position_monitor.update_positions(
                    prices={symbol_name: tick.mid},
                    bids={symbol_name: tick.bid},
                    asks={symbol_name: tick.ask},
                )

        # Evaluation trigger: purely event-driven — only on bar completion
        # Per-timeframe evaluation threshold (Rei #7): check primary timeframe
        primary_key = self._bar_key(symbol_name, self._config.bar_period_minutes)
        with self._lock:
            bar_count = len(self._bars.get(primary_key, []))
            current_bar = self._current_bar.get(primary_key)
            total_bars = bar_count + (1 if current_bar else 0)

        if total_bars < self._config.min_bars_for_evaluation:
            return

        # Check if any required timeframe has a new completed bar
        has_new_bar = False
        with self._lock:
            for tf in self._required_timeframes:
                key = self._bar_key(symbol_name, tf)
                if self._bar_completed.get(key, False):
                    has_new_bar = True
                    break

        if not has_new_bar:
            return

        # Consume the completion flags
        with self._lock:
            for tf in self._required_timeframes:
                key = self._bar_key(symbol_name, tf)
                self._bar_completed[key] = False

        logger.debug("Evaluating on bar completion for %s", symbol_name)
        self._last_evaluation_at = time.monotonic()
        self._evaluate_strategies(symbol_name)

    def _resolve_symbol_name(self, tick: Tick) -> Optional[str]:
        if self._market_feed is None:
            return None

        symbol_info = self._market_feed.symbols.get(tick.symbol_id)
        if symbol_info is None:
            return None

        feed_name = symbol_info.name
        no_slash = feed_name.replace("/", "")
        cfg_symbols = {s.upper().replace("/", "") for s in self._config.symbols}

        if no_slash in cfg_symbols:
            return no_slash
        return None

    def _update_paper_trader_prices(self, tick: Tick, symbol_name: str):
        if self._paper_trader is None:
            return

        mid_price = tick.mid
        self._paper_trader.update_market_prices(
            {symbol_name: mid_price},
            bids={symbol_name: tick.bid},
            asks={symbol_name: tick.ask},
        )

    # Rejection circuit breaker constants (T5)
    _REJECTION_BREAKER_THRESHOLD = 5
    _REJECTION_COOLDOWN_SEC = 60.0

    def _execute_signal_live(self, signal: TradeSignal):
        """Place a real cTrader order via the OpenApiSpotFeed.

        In live mode the signal adapter runs in blend mode so it returns signals
        without calling ``paper_trader.process_signal()``.  This method performs
        the actual order placement using ``OpenApiSpotFeed.new_order()``.
        """
        if self._market_feed is None or not isinstance(self._market_feed, OpenApiSpotFeed):
            logger.warning("Cannot execute live order: no OpenApiSpotFeed available")
            return None

        try:
            symbol_id = self._market_feed.resolve_symbol_id(signal.symbol)
        except Exception as exc:
            logger.warning("Live order rejected: unknown symbol %s (%s)", signal.symbol, exc)
            return None

        side = ProtoOATradeSide.BUY if signal.direction == TradeDirection.LONG else ProtoOATradeSide.SELL

        # Size the order using the same position-sizing logic as the paper trader.
        balance = (
            self._paper_trader.balance
            if self._paper_trader else self._config.starting_balance
        )
        volume_lots = 0.0
        if self._paper_trader is not None:
            volume_lots = self._paper_trader._order_manager.calculate_position_size(
                account_balance=balance,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                symbol=signal.symbol,
            )
        if volume_lots <= 0.0:
            logger.warning("Live order rejected: calculated volume is zero for %s", signal.symbol)
            return None

        volume_raw = int(round(volume_lots * 100_000))

        order = self._market_feed.new_order(
            symbol_id=symbol_id,
            side=side,
            volume=volume_raw,
            order_type=ProtoOAOrderType.MARKET,
            sl=signal.stop_loss,
            tp=signal.take_profit_1,
            comment=signal.rationale,
        )

        logger.info(
            "Live order placed: %s %s %s lots=%.2f raw_volume=%d status=%s",
            signal.direction.value,
            signal.symbol,
            signal.rationale,
            volume_lots,
            volume_raw,
            order.status.value if order.status else "unknown",
        )
        return order

    def _evaluate_strategies(self, symbol: str):
        if self._live_adapter is None:
            return

        # Kill switch gate — checked before any strategy evaluation
        if self._kill_switch.is_globally_killed():
            logger.debug("Kill switch active — skipping strategy evaluation")
            return

        # T5: Rejection circuit breaker — cooldown check
        if time.monotonic() < self._rejection_cooldown_until:
            logger.debug("Rejection cooldown active, skipping evaluation")
            return

        if not self._eval_semaphore.acquire(blocking=False):
            logger.debug("Evaluation already in progress — skipping")
            return

        try:
            # Build per-timeframe bar snapshots
            tf_bars: dict[int, list[Bar]] = {}
            with self._lock:
                for tf in self._required_timeframes:
                    key = self._bar_key(symbol, tf)
                    bars = list(self._bars.get(key, []))
                    tf_bars[tf] = bars

            # Defensive: verify no forming bars leaked into evaluation
            for tf_key in tf_bars:
                forming = self._current_bar.get(tf_key)
                if forming is not None and tf_bars[tf_key]:
                    if forming.time == tf_bars[tf_key][-1].time:
                        logger.error("Bar-close invariant violated: forming bar leaked into evaluation for %s", tf_key)
                        tf_bars[tf_key] = tf_bars[tf_key][:-1]  # remove the leaked bar

            if not any(tf_bars.values()):
                return

            # S1: Bar eval triggered — confirm evaluation IS being called
            logger.info(
                "[S1] Bar eval triggered: symbol=%s bars_15m=%d bars_60m=%d",
                symbol,
                len(tf_bars.get(15, [])),
                len(tf_bars.get(60, [])),
            )

            # Record evaluation attempt for error-rate monitor
            self._eval_timestamps.append(time.monotonic())

            # Resolve each strategy's timeframe
            strategy_tf_map: dict[str, int] = {}
            for s in self._strategies:
                strategy_tf_map[s.name] = (
                    self._strategy_timeframes.get(s.name, self._config.bar_period_minutes)
                )

            # Per-strategy evaluation with correct timeframe bars
            for strategy in self._strategies:
                tf = strategy_tf_map[strategy.name]
                bars = tf_bars.get(tf, [])

                # Per-timeframe evaluation threshold (Rei #7)
                if len(bars) < self._config.min_bars_for_evaluation:
                    continue

                state = MarketState(bars=bars)

                # T5: Capture risk block count before evaluation
                _pre_risk_blocks = (
                    self._paper_trader.get_stats().signals_blocked_by_risk
                    if self._paper_trader else 0
                )

                try:
                    signals = self._live_adapter.evaluate_all_strategies(
                        {symbol: state},
                        spread=self._current_spread,
                        bid=self._current_bid,
                        ask=self._current_ask,
                    )
                except Exception as exc:
                    with self._lock:
                        self._health.evaluation_errors += 1
                    self._eval_errors.append(time.monotonic())
                    logger.error(
                        "Strategy %s evaluation error (total=%d): %s",
                        strategy.name, self._health.evaluation_errors, exc, exc_info=True,
                    )
                    continue

                # S1: Per-strategy diagnostic counters
                self._strategy_eval_counts[strategy.name] += 1
                if not signals:
                    self._strategy_no_signal_counts[strategy.name] += 1
                self._strategy_last_eval[strategy.name] = time.monotonic()

                # S1: INFO-level per-strategy eval log
                logger.info(
                    "[S1] Strategy %s: eval #%d, signals=%d, total_no_signal=%d",
                    strategy.name,
                    self._strategy_eval_counts[strategy.name],
                    len(signals),
                    self._strategy_no_signal_counts[strategy.name],
                )

                # T5: Check if risk guard blocked any signals (circuit breaker tracking)
                _post_risk_blocks = (
                    self._paper_trader.get_stats().signals_blocked_by_risk
                    if self._paper_trader else 0
                )
                _new_risk_rejections = _post_risk_blocks - _pre_risk_blocks

                if _new_risk_rejections > 0:
                    # Actual RiskGuard rejections — track for circuit breaker
                    self._consecutive_risk_rejections += _new_risk_rejections
                    with self._lock:
                        self._health.signals_rejected += _new_risk_rejections
                        self._health.consecutive_risk_rejections = self._consecutive_risk_rejections
                    logger.warning(
                        "Risk guard rejected %d signal(s) (consecutive=%d/%d)",
                        _new_risk_rejections, self._consecutive_risk_rejections,
                        self._REJECTION_BREAKER_THRESHOLD,
                    )
                    if self._consecutive_risk_rejections >= self._REJECTION_BREAKER_THRESHOLD:
                        self._rejection_cooldown_until = (
                            time.monotonic() + self._REJECTION_COOLDOWN_SEC
                        )
                        logger.warning(
                            "Rejection circuit breaker TRIPPED at %d consecutive — "
                            "cooldown for %.0fs",
                            self._consecutive_risk_rejections,
                            self._REJECTION_COOLDOWN_SEC,
                        )
                        # Check if daily loss limit is the cause
                        if self._paper_trader:
                            stats = self._paper_trader.get_stats()
                            drawdown_pct = abs(
                                (stats.current_balance - stats.starting_balance)
                                / stats.starting_balance
                            ) if stats.starting_balance > 0 else 0
                            if drawdown_pct > 0.03:
                                logger.critical(
                                    "Daily drawdown %.1f%% — possible daily loss limit breach",
                                    drawdown_pct * 100,
                                )
                elif signals:
                    # Signal passed risk — reset consecutive counter
                    self._consecutive_risk_rejections = 0
                    with self._lock:
                        self._health.consecutive_risk_rejections = 0

                with self._lock:
                    self._health.signals_generated += len(signals)

                for s in signals:
                    with self._lock:
                        self._health.signals_traded += 1
                    logger.info(
                        "Signal traded: %s %s %s @ %.5f conf=%.2f",
                        s.direction.value,
                        s.volume,
                        s.symbol,
                        s.entry_price,
                        s.confidence,
                    )
                    if self._config.live_mode:
                        self._execute_signal_live(s)
                    self._trigger_callback("on_signal_traded", s)
        except Exception as exc:
            with self._lock:
                self._health.evaluation_errors += 1
            self._eval_errors.append(time.monotonic())
            logger.error(
                "Strategy evaluation outer error (total=%d): %s",
                self._health.evaluation_errors, exc, exc_info=True,
            )
        finally:
            self._eval_semaphore.release()

    def _preload_historical_bars(self):
        """T2: Fetch historical bars from the API and preload them into the engine."""
        if not isinstance(self._market_feed, OpenApiSpotFeed):
            return

        for sym in self._config.symbols:
            for tf in self._required_timeframes:
                # Skip if already preloaded by launcher
                key = self._bar_key(sym, tf)
                if key in self._bars and len(self._bars[key]) >= self._config.min_bars_for_evaluation:
                    logger.info("Skipping preload for %s %dm — already has %d bars", sym, tf, len(self._bars[key]))
                    continue
                try:
                    bars = self._market_feed.fetch_trendbars(
                        symbol=sym,
                        period_minutes=tf,
                        count=self._config.min_bars_for_evaluation,
                    )
                    if bars:
                        self.preload_bars(sym, tf, bars)
                        logger.info(
                            "Preloaded %d bars for %s %dm",
                            len(bars), sym, tf,
                        )
                    else:
                        logger.warning(
                            "No bars returned for %s %dm — evaluation may be delayed",
                            sym, tf,
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to preload bars for %s %dm: %s",
                        sym, tf, exc,
                    )

        self._preload_complete = True
        logger.info("Bar preloading complete")

    def _write_heartbeat(self):
        """Atomically write the trading heartbeat file.

        Uses temp + rename to guarantee no partial reads by the watchdog.
        """
        try:
            heartbeat = {
                "last_beat": datetime.now(timezone.utc).isoformat(),
                "pid": self._heartbeat_pid,
                "ticks_received": self._health.ticks_received,
                "engine_running": self._running,
            }
            json_str = json.dumps(heartbeat, indent=2)

            filepath = Path(self._heartbeat_file)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(
                dir=str(filepath.parent),
                prefix=".heartbeat_trading.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(json_str)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, str(filepath))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
            logger.warning("Failed to write heartbeat: %s", exc)

    def _check_error_rate(self):
        """Check evaluation error rate in rolling 60s window.

        If error rate exceeds 50%, activate GLOBAL FREEZE.
        Resets counters on successful evaluation (called when no error).
        """
        now_mono = time.monotonic()
        cutoff = now_mono - _ERROR_RATE_WINDOW_SEC

        # Prune old entries
        while self._eval_timestamps and self._eval_timestamps[0] < cutoff:
            self._eval_timestamps.popleft()
        while self._eval_errors and self._eval_errors[0] < cutoff:
            self._eval_errors.popleft()

        total_evals = len(self._eval_timestamps)
        if total_evals < 5:
            return  # not enough data to judge

        error_count = len(self._eval_errors)
        error_rate = error_count / total_evals

        if error_rate > _ERROR_RATE_THRESHOLD_PCT:
            logger.critical(
                "Error rate %.1f%% (%d/%d) in 60s window — ACTIVATING GLOBAL FREEZE",
                error_rate * 100,
                error_count,
                total_evals,
            )
            self._kill_switch.activate_global_freeze(
                reason="high_error_rate",
                triggered_by="error_monitor",
            )
            # Clear to prevent re-trigger every cycle
            self._eval_timestamps.clear()
            self._eval_errors.clear()

    def _check_feed_health_kill_switch(self):
        """Check feed disconnect and activate FREEZE if needed.

        On feed disconnect: activate GLOBAL FREEZE (not kill — positions
        have broker-side SL/TP).
        On feed reconnect: log info but do NOT auto-recover.
        """
        with self._lock:
            feed_connected = (
                self._market_feed.is_running if self._market_feed else False
            )
            last_tick = self._health.last_tick_at

        # Only freeze if feed is actually disconnected.
        # "feed connected but no tick yet" = still initializing, not a disconnect.
        if not feed_connected:
            if not self._feed_disconnect_frozen and not self._kill_switch.is_active():
                logger.warning(
                    "Feed disconnect detected — activating GLOBAL FREEZE"
                )
                self._kill_switch.activate_global_freeze(
                    reason="feed_disconnect",
                    triggered_by="feed_health_monitor",
                )
                self._feed_disconnect_frozen = True
        elif last_tick is not None and self._feed_disconnect_frozen:
            logger.info(
                "Feed reconnected — kill switch remains active "
                "(manual recovery required)"
            )
            # Do NOT auto-recover. Manual recovery required.
            self._feed_disconnect_frozen = True

    def _health_monitor_loop(self):
        # B5: Periodic diagnostic tracking
        _last_diagnostic_log = time.monotonic()
        _diagnostic_interval = 60.0

        while not self._stop_health_monitor.wait(
            self._config.health_monitor_interval_sec
        ):
            try:
                self._update_health()
                self._check_connection_health()

                # Write heartbeat (atomic)
                if self._running:
                    self._write_heartbeat()

                # Feed health → kill switch
                self._check_feed_health_kill_switch()

                # Error rate monitor
                self._check_error_rate()

                # B5: Periodic health diagnostic log (every 60s)
                now = time.monotonic()
                if now - _last_diagnostic_log >= _diagnostic_interval:
                    _last_diagnostic_log = now
                    with self._lock:
                        ticks = self._health.ticks_received
                        bars = self._health.bars_built
                        signals = self._health.signals_generated
                        traded = self._health.signals_traded
                        errors = self._health.evaluation_errors
                    logger.info(
                        "[B5 Periodic] ticks=%d bars_built=%d signals=%d traded=%d eval_errors=%d",
                        ticks, bars, signals, traded, errors,
                    )
                    # B5 Amendment 4: tick-to-bar pipeline health
                    if ticks > 0 and bars == 0:
                        logger.warning(
                            "[B5 Pipeline] %d ticks received but 0 bars built — "
                            "tick-to-bar conversion may be stalled",
                            ticks,
                        )

                    # Phase 1D: Portfolio summary from position monitor
                    if self._position_monitor is not None:
                        summary = self._position_monitor.get_portfolio_summary()
                        if summary["position_count"] > 0:
                            logger.info(
                                "[Portfolio] positions=%d unrealized_pnl=%.2f "
                                "notional=%.2f symbols=%s mfe=%.2f mae=%.2f",
                                summary["position_count"],
                                summary["total_unrealized_pnl"],
                                summary["total_notional_exposure"],
                                summary["positions_by_symbol"],
                                summary["total_mfe"],
                                summary["total_mae"],
                            )

                    # S1: Per-strategy diagnostic in B5 Periodic health
                    for sname in sorted(self._strategy_eval_counts):
                        last_eval_ago = time.monotonic() - self._strategy_last_eval.get(sname, 0)
                        logger.info(
                            "[S1 Health] %s: evals=%d no_signal=%d last=%.0fs ago",
                            sname,
                            self._strategy_eval_counts[sname],
                            self._strategy_no_signal_counts[sname],
                            last_eval_ago,
                        )
            except Exception as exc:
                logger.error("Health monitor error: %s", exc, exc_info=True)

    def _check_connection_health(self):
        if not self._running:
            return

        with self._lock:
            feed_connected = (
                self._market_feed.is_running if self._market_feed else False
            )
            last_tick = self._health.last_tick_at

        staleness = float("inf")
        if last_tick is not None:
            staleness = (datetime.now(timezone.utc) - last_tick).total_seconds()

        is_healthy = (
            feed_connected
            and last_tick is not None
            and staleness < self._config.stale_tick_threshold_sec
        )
        if is_healthy:
            self._reconnect_delay = self._config.reconnect_delay_sec
            with self._lock:
                if self._health.reconnection_attempts > 0:
                    logger.info(
                        "Connection healthy — reset consecutive reconnect counter (%d -> 0)",
                        self._health.reconnection_attempts,
                    )
                    self._health.reconnection_attempts = 0
            return

        if feed_connected and last_tick is None:
            # No ticks received yet — skip reconnect (feed still initializing)
            return

        if feed_connected and _is_forex_market_closed():
            self._reconnect_delay = self._config.reconnect_delay_sec
            with self._lock:
                if self._health.reconnection_attempts > 0:
                    logger.info(
                        "Market closed — reset consecutive reconnect counter (%d -> 0)",
                        self._health.reconnection_attempts,
                    )
                    self._health.reconnection_attempts = 0
            return

        now = time.monotonic()
        if now - self._last_reconnect_attempt_at < self._reconnect_delay:
            return

        logger.warning(
            "Connection health check failed: connected=%s last_tick_ago=%.1fs threshold=%.1fs — reconnecting",
            feed_connected,
            staleness,
            self._config.stale_tick_threshold_sec,
        )

        self._last_reconnect_attempt_at = now
        self._attempt_reconnect()

    def _attempt_reconnect(self):
        with self._lock:
            self._health.reconnection_attempts += 1
            attempts = self._health.reconnection_attempts

        if attempts >= self._config.max_reconnect_attempts:
            logger.critical(
                "Reconnect circuit-breaker tripped: %d consecutive attempts with no ticks "
                "(max=%d). Stopping engine gracefully.",
                attempts,
                self._config.max_reconnect_attempts,
            )
            # Set running=False directly instead of calling stop() to avoid
            # self-join deadlock (stop() calls _health_monitor_thread.join() which
            # is the current thread when called from _health_monitor_loop).
            self._running = False
            return

        logger.info(
            "Reconnection attempt %d (backoff=%.1fs)",
            self._health.reconnection_attempts,
            self._reconnect_delay,
        )

        if self._market_feed:
            try:
                self._market_feed.stop()
            except Exception as exc:
                logger.warning("Error stopping feed for reconnect: %s", exc)

        success = self._start_market_feed()
        if success:
            with self._lock:
                self._health.reconnection_successes += 1
                self._health.reconnection_attempts = 0
            self._reconnect_delay = self._config.reconnect_delay_sec
            logger.info("Reconnection successful — reset consecutive failure counter")
        else:
            self._reconnect_delay = min(
                self._reconnect_delay * 2,
                self._config.max_reconnect_delay_sec,
            )
            logger.warning(
                "Reconnection failed — next attempt in %.1fs", self._reconnect_delay
            )

    def _on_trade_executed(self, result):
        if self._trade_logger and result.order:
            self._trade_logger.log_trade_opened(result.order, result.position)
        self._trigger_callback("on_trade_executed", result)

    def _on_position_closed(self, position):
        if self._trade_logger:
            self._trade_logger.log_position_closed(position)
        self._trigger_callback("on_position_closed", position)

    def _update_health(self):
        with self._lock:
            if self._start_time:
                self._health.uptime_sec = (
                    datetime.now(timezone.utc) - self._start_time
                ).total_seconds()

    def _trigger_callback(self, event: str, *args, **kwargs):
        for evt, callback in self._callbacks:
            if evt == event:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    logger.error("Callback error for %s: %s", event, e)

    def _on_shutdown(self, signum, frame):
        logger.info("Shutdown signal received (sig=%d)", signum)
        self.stop()

    def preload_bars(self, symbol: str, period_minutes: int, bars: list[Bar]):
        """Preload historical bars for a specific symbol+timeframe."""
        key = self._bar_key(symbol, period_minutes)
        self._bars[key] = bars[-self._config.max_bars_per_symbol :]
        logger.info("Preloaded %d bars into key '%s'", len(self._bars[key]), key)

    def get_bars_including_forming(self, symbol: str, period_minutes: int) -> list[Bar]:
        """Get bars for a symbol+timeframe.

        WARNING: Includes the current FORMING bar as the last element if one exists.
        Do NOT use this for strategy evaluation — use self._bars directly instead.
        """
        key = self._bar_key(symbol, period_minutes)
        bars = list(self._bars.get(key, []))
        current = self._current_bar.get(key)
        if current is not None:
            bars.append(current)
        return bars

    def get_stats(self) -> dict:
        self._update_health()
        stats = self._paper_trader.get_stats() if self._paper_trader else None
        health = self.health
        return {
            "health": {
                "connected": health.connected,
                "last_tick_at": health.last_tick_at.isoformat()
                if health.last_tick_at
                else None,
                "ticks_received": health.ticks_received,
                "ticks_per_second": round(health.ticks_per_second, 2),
                "uptime_sec": round(health.uptime_sec, 1),
                "current_spread": round(self._current_spread, 5),
            },
            "trading": {
                "current_balance": stats.current_balance if stats else 0,
                "trades_executed": stats.trades_executed if stats else 0,
                "trades_rejected": stats.trades_rejected if stats else 0,
                "signals_blocked_by_risk": stats.signals_blocked_by_risk
                if stats
                else 0,
                "realized_pnl": stats.realized_pnl if stats else 0,
                "unrealized_pnl": stats.unrealized_pnl if stats else 0,
            },
            # S1: Per-strategy diagnostic stats
            "strategy_stats": {
                sname: {
                    "evals": self._strategy_eval_counts.get(sname, 0),
                    "no_signal": self._strategy_no_signal_counts.get(sname, 0),
                    "last_eval_ago_sec": round(
                        time.monotonic() - self._strategy_last_eval.get(sname, 0), 1
                    ),
                }
                for sname in sorted(self._strategy_eval_counts)
            },
        }
