from __future__ import annotations

import logging
import signal as sig_module
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from adapters.ctrader.api_client import cTraderAPIClient

from .protocol import CanonicalSignal
from .signal_router import RouteResult
from .strategy_executor import StrategyExecutor
from .strategy_registry import StrategyRegistry, StrategySlot

from adapters.ctrader.market_data_feed import LiveMarketDataFeed, Tick
from adapters.ctrader.models import cTraderCredentials, Position
from adapters.ctrader.order_manager import OrderManager, PositionSizeConfig
from adapters.ctrader.portfolio_risk_guard import PortfolioRiskGuard
from adapters.ctrader.trade_journal import TradeJournal
from adapters.ctrader.risk_guard import FTMOConfig

logger = logging.getLogger(__name__)

_HISTORICAL_BARS_DIR = "data/forex/historical"
_DEFAULT_MAX_BARS = 500
_DEFAULT_MIN_BARS = 50
_DEFAULT_EVAL_INTERVAL_SEC = 1.0
_DEFAULT_HEALTH_INTERVAL_SEC = 5.0
_DEFAULT_STALE_TICK_SEC = 300.0


@dataclass
class OrchestratorStatus:
    running: bool = False
    strategies: list[str] = None
    connected: bool = False
    last_tick_at: Optional[datetime] = None
    ticks_received: int = 0
    signals_generated: int = 0
    signals_executed: int = 0
    signals_rejected: int = 0
    evaluation_errors: int = 0
    uptime_sec: float = 0.0


class MultiStrategyOrchestrator:
    def __init__(
        self,
        config_path: str = "config/strategies.yaml",
        credentials: Optional[cTraderCredentials] = None,
        log_dir: str = "logs/forward_test",
        live_mode: bool = False,
        api_client: Optional[cTraderAPIClient] = None,
    ):
        self._config_path = config_path
        self._credentials = credentials
        self._log_dir = log_dir
        self._live_mode = live_mode
        self._api_client = api_client
        self._running = False
        self._shutdown = False

        self._registry: Optional[StrategyRegistry] = None
        self._executors: list[StrategyExecutor] = []
        self._executors_by_symbol: dict[str, list[StrategyExecutor]] = {}
        self._executors_by_id: dict[str, StrategyExecutor] = {}

        self._market_feed: Optional[LiveMarketDataFeed] = None
        self._portfolio_risk: Optional[PortfolioRiskGuard] = None
        self._order_manager: Optional[OrderManager] = None
        self._router = None
        self._journal: Optional[TradeJournal] = None

        self._start_time: Optional[datetime] = None
        self._last_tick_at: Optional[datetime] = None
        self._ticks_received = 0
        self._signals_generated = 0
        self._signals_executed = 0
        self._signals_rejected = 0
        self._evaluation_errors = 0
        self._current_spread = 0.0
        self._last_eval_at = 0.0

        self._health_thread: Optional[threading.Thread] = None
        self._stop_health = threading.Event()
        self._callbacks: list[tuple[str, callable]] = []

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        if self._running:
            logger.warning("Orchestrator already running")
            return True

        try:
            self._build_components()
        except Exception as exc:
            logger.error("Failed to build components: %s", exc, exc_info=True)
            return False

        if not self._start_market_feed():
            logger.error("Failed to start market data feed")
            return False

        self._running = True
        self._start_time = datetime.now(timezone.utc)

        self._stop_health.clear()
        self._health_thread = threading.Thread(
            target=self._health_monitor_loop,
            name="orchestrator-health",
            daemon=True,
        )
        self._health_thread.start()

        try:
            sig_module.signal(sig_module.SIGINT, self._on_shutdown)
            sig_module.signal(sig_module.SIGTERM, self._on_shutdown)
        except (ValueError, RuntimeError):
            pass

        strategy_ids = [ex.slot_id for ex in self._executors]
        logger.info(
            "MultiStrategyOrchestrator started: strategies=%s mode=%s balance=%.0f",
            strategy_ids,
            "LIVE" if self._live_mode else "PAPER",
            self._portfolio_risk.current_balance if self._portfolio_risk else 0,
        )
        return True

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._shutdown = True
        self._stop_health.set()

        if self._health_thread:
            self._health_thread.join(timeout=10.0)
            self._health_thread = None

        if self._market_feed:
            self._market_feed.stop()

        self._update_open_positions()

        if self._journal:
            summary = self._journal.get_portfolio_summary()
            logger.info(
                "Orchestrator stopped: trades=%d pnl=%.2f strategies=%s",
                summary["total_trades"],
                summary["total_pnl"],
                list(summary.get("per_strategy", {}).keys()),
            )

    def get_status(self) -> OrchestratorStatus:
        return OrchestratorStatus(
            running=self._running,
            strategies=[ex.slot_id for ex in self._executors],
            connected=self._market_feed.is_running if self._market_feed else False,
            last_tick_at=self._last_tick_at,
            ticks_received=self._ticks_received,
            signals_generated=self._signals_generated,
            signals_executed=self._signals_executed,
            signals_rejected=self._signals_rejected,
            evaluation_errors=self._evaluation_errors,
            uptime_sec=(
                (datetime.now(timezone.utc) - self._start_time).total_seconds()
                if self._start_time
                else 0.0
            ),
        )

    def register_callback(self, event: str, callback: callable):
        self._callbacks.append((event, callback))

    def _build_components(self):
        self._registry = StrategyRegistry(self._config_path)
        slots = self._registry.load()
        enabled = self._registry.get_enabled()

        balance = self._registry.account_balance
        ftmo_raw = self._registry.ftmo_config
        ftmo = FTMOConfig(
            daily_loss_limit_pct=ftmo_raw.get("daily_loss_limit_pct", 0.04),
            total_drawdown_limit_pct=ftmo_raw.get("total_drawdown_limit_pct", 0.07),
            max_trades_per_day=ftmo_raw.get("max_trades_per_day", 10),
            max_positions=ftmo_raw.get("max_positions", 5),
            min_risk_reward=ftmo_raw.get("min_risk_reward", 0.0),
        )

        self._portfolio_risk = PortfolioRiskGuard(ftmo, balance)
        self._order_manager = OrderManager(
            PositionSizeConfig(), api_client=self._api_client
        )
        self._router = None
        self._journal = TradeJournal(log_dir=self._log_dir)

        for slot in enabled:
            strategy = self._registry.instantiate(slot)
            hist_csv = self._historical_csv_path(slot)
            executor = StrategyExecutor(
                slot=slot,
                strategy=strategy,
                max_bars=_DEFAULT_MAX_BARS,
                min_bars=_DEFAULT_MIN_BARS,
                historical_bars_csv=hist_csv,
            )
            self._executors.append(executor)
            self._executors_by_symbol.setdefault(slot.symbol, []).append(executor)
            self._executors_by_id[executor.slot_id] = executor
            logger.info(
                "Built executor: %s (%s %s)", slot.id, slot.strategy_type, slot.symbol
            )

        from .signal_router import SignalRouter

        self._router = SignalRouter(self._portfolio_risk, self._order_manager)
        self._router.register_callback("on_signal_routed", self._on_signal_routed)

        self._portfolio_risk.register_circuit_breaker_callback(self._on_circuit_breaker)

    def _start_market_feed(self) -> bool:
        creds = self._credentials or self._load_credentials()
        if not creds or not creds.host or not creds.username:
            logger.error("Invalid credentials — cannot start market data feed")
            return False

        self._market_feed = LiveMarketDataFeed(creds)
        self._market_feed.on_tick(self._on_tick)

        symbols = list(self._executors_by_symbol.keys())
        subscribe_names = []
        seen = set()
        for sym in symbols:
            key = sym.upper().replace("/", "")
            if key in seen:
                continue
            seen.add(key)
            subscribe_names.append(key[:3] + "/" + key[3:])

        logger.info("Starting market feed, subscribing to: %s", subscribe_names)
        success = self._market_feed.start(auto_subscribe=subscribe_names)
        if success:
            logger.info("Market feed connected")
        return success

    def _on_tick(self, tick: Tick):
        if not self._running:
            return

        self._ticks_received += 1
        self._last_tick_at = datetime.now(timezone.utc)
        self._current_spread = tick.spread

        symbol_name = self._resolve_symbol_name(tick)
        if symbol_name is None:
            return

        executors = self._executors_by_symbol.get(symbol_name, [])
        for executor in executors:
            try:
                executor.on_tick(tick.mid, tick.bid, tick.ask, tick.timestamp)
            except Exception as exc:
                logger.error("Tick processing error [%s]: %s", executor.slot_id, exc)

        now = time.monotonic()
        if now - self._last_eval_at < _DEFAULT_EVAL_INTERVAL_SEC:
            return
        self._last_eval_at = now

        for executor in executors:
            try:
                signal = executor.try_evaluate()
                if signal is None:
                    continue
                self._signals_generated += 1
                if self._router:
                    result = self._router.route(signal, spread=self._current_spread)
                    if result.action == "executed":
                        self._signals_executed += 1
                        if result.order and result.position:
                            self._journal.log_open(
                                strategy_id=signal.strategy_id,
                                strategy_type=executor.slot.strategy_type,
                                signal_confidence=signal.confidence,
                                signal_rationale=signal.rationale,
                                order=result.order,
                                position=result.position,
                            )
                    else:
                        self._signals_rejected += 1
            except Exception as exc:
                self._evaluation_errors += 1
                logger.error(
                    "Evaluation error [%s]: %s", executor.slot_id, exc, exc_info=True
                )

        self._update_open_positions()

    def _update_open_positions(self):
        if not self._order_manager or not self._portfolio_risk:
            return
        positions = self._order_manager.get_open_positions()
        total_unrealized = 0.0
        for pos in positions:
            total_unrealized += pos.unrealized_pnl
        guard_stats = self._portfolio_risk.get_portfolio_state()
        realized = (
            guard_stats["current_balance"]
            - total_unrealized
            - self._registry.account_balance
        )
        new_balance = self._registry.account_balance + realized + total_unrealized
        self._portfolio_risk.update_balance(new_balance)

    def _resolve_symbol_name(self, tick: Tick) -> Optional[str]:
        if not self._market_feed:
            return None
        symbol_info = self._market_feed.symbols.get(tick.symbol_id)
        if symbol_info is None:
            return None
        feed_name = symbol_info.name
        no_slash = feed_name.replace("/", "")
        for sym in self._executors_by_symbol:
            if sym.upper().replace("/", "") == no_slash:
                return sym
        return None

    def _on_signal_routed(self, result: RouteResult):
        self._trigger_callback("on_signal_routed", result)

    def _on_circuit_breaker(self, limit_type, current, limit):
        logger.critical(
            "PORTFOLIO CIRCUIT BREAKER: %s = %.2f%% >= %.2f%%",
            limit_type.value,
            current * 100,
            limit * 100,
        )
        self._trigger_callback("on_circuit_breaker", limit_type, current, limit)

    def _health_monitor_loop(self):
        while not self._stop_health.wait(_DEFAULT_HEALTH_INTERVAL_SEC):
            try:
                self._check_health()
            except Exception as exc:
                logger.error("Health monitor error: %s", exc, exc_info=True)

    def _check_health(self):
        if not self._running:
            return
        feed_connected = self._market_feed.is_running if self._market_feed else False
        if not feed_connected and self._last_tick_at:
            staleness = (
                datetime.now(timezone.utc) - self._last_tick_at
            ).total_seconds()
            if staleness > _DEFAULT_STALE_TICK_SEC:
                logger.warning(
                    "Feed disconnected for %.0fs — market may be closed or reconnecting",
                    staleness,
                )

    def _on_shutdown(self, signum=None, frame=None):
        logger.info("Shutdown signal received (sig=%s)", signum)
        self.stop()

    def _load_credentials(self) -> Optional[cTraderCredentials]:
        from dotenv import load_dotenv
        import os

        env_path = Path(__file__).resolve().parents[3] / ".env"
        if not env_path.exists():
            env_path = Path(__file__).resolve().parents[4] / ".env"
        if env_path.exists():
            load_dotenv(env_path)

        host = os.environ.get("CTRADER_HOST", "")
        port = int(os.environ.get("CTRADER_READONLY_SSL_PORT", "5211"))
        username = os.environ.get("CTRADER_ACCOUNT", "")
        password = os.environ.get("CTRADER_PASSWORD", "")

        if not host or not username:
            return None

        return cTraderCredentials(
            host=host,
            port=port,
            use_ssl=True,
            sender_comp_id=os.environ.get("CTRADER_SENDER_COMP_ID", ""),
            target_comp_id=os.environ.get("CTRADER_TARGET_COMP_ID", "cServer"),
            sender_sub_id="QUOTE",
            target_sub_id="QUOTE",
            username=username,
            password=password,
        )

    def _historical_csv_path(self, slot: StrategySlot) -> Optional[str]:
        csv_name = f"{slot.symbol.upper()}_H1.csv"
        path = Path(_HISTORICAL_BARS_DIR) / csv_name
        if path.exists():
            return str(path)
        return None

    def _trigger_callback(self, event: str, *args, **kwargs):
        for evt, callback in self._callbacks:
            if evt == event:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    logger.error("Orchestrator callback error for %s: %s", event, e)
