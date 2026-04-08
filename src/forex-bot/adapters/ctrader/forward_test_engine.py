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

import logging
import signal as sig_module
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Callable
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    pass

from backtest.engine import Bar, MarketState
from backtest.strategies import ISignalStrategy

from .market_data_feed import LiveMarketDataFeed, Tick
from .models import cTraderCredentials
from .order_manager import PositionSizeConfig
from .paper_trader import PaperTrader
from .risk_guard import FTMOConfig
from .signal_adapter import cTraderLiveAdapter
from .trade_logger import TradeLogger

logger = logging.getLogger(__name__)


@dataclass
class ForwardTestConfig:
    symbol: str = "GBPUSD"
    starting_balance: float = 100_000.0
    min_confidence: float = 0.50
    max_bars_per_symbol: int = 500
    min_bars_for_evaluation: int = 50
    quote_host: str = "live-uk-eqx-01.p.c-trader.com"
    quote_port: int = 5211
    use_ssl: bool = True
    quote_sender_sub_id: str = "QUOTE"
    log_dir: str = "logs/trades"
    stats_interval_sec: float = 60.0
    live_mode: bool = False
    trade_host: Optional[str] = None
    trade_port: Optional[int] = None


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


class ForwardTestEngine:
    def __init__(
        self,
        config: ForwardTestConfig,
        strategies: list[ISignalStrategy],
        ftmo_config: Optional[FTMOConfig] = None,
        position_config: Optional[PositionSizeConfig] = None,
        credentials: Optional[cTraderCredentials] = None,
    ):
        self._config = config
        self._strategies = strategies
        self._ftmo_config = ftmo_config
        self._position_config = position_config
        self._running = False
        self._lock = threading.RLock()

        self._bars: dict[str, list[Bar]] = {}
        self._paper_trader: Optional[PaperTrader] = None
        self._market_feed: Optional[LiveMarketDataFeed] = None
        self._live_adapter: Optional[cTraderLiveAdapter] = None
        self._trade_logger: Optional[TradeLogger] = None
        self._credentials = credentials

        self._start_time: Optional[datetime] = None
        self._tick_timestamps: list[datetime] = []
        self._tick_rate_window_sec = 10.0

        self._callbacks: list[tuple[str, "Callable"]] = []
        self._health = ForwardTestHealth()

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

        self._build_components()
        self._wire_callbacks()

        if not self._start_market_feed():
            logger.error("Failed to start market data feed")
            return False

        self._running = True
        self._start_time = datetime.now(timezone.utc)

        sig_module.signal(sig_module.SIGINT, self._on_shutdown)
        sig_module.signal(sig_module.SIGTERM, self._on_shutdown)

        logger.info(
            "Forward test started: symbol=%s strategies=%s mode=%s",
            self._config.symbol,
            [s.name for s in self._strategies],
            "LIVE" if self._config.live_mode else "PAPER",
        )
        return True

    def stop(self):
        if not self._running:
            return

        self._running = False

        if self._market_feed:
            self._market_feed.stop()

        self._update_health()
        stats = self._paper_trader.get_stats() if self._paper_trader else None
        if stats:
            logger.info(
                "Forward test stopped: balance=%.2f trades=%d pnl=%.2f",
                stats.current_balance,
                stats.trades_executed,
                stats.current_balance - stats.starting_balance,
            )

    def register_callback(self, event: str, callback: Callable):
        self._callbacks.append((event, callback))

    def _build_components(self):
        cfg = self._config
        ftmo = self._ftmo_config or FTMOConfig()
        pos_cfg = self._position_config or PositionSizeConfig()

        self._paper_trader = PaperTrader(
            ftmo_config=ftmo,
            position_config=pos_cfg,
            starting_balance=cfg.starting_balance,
        )

        self._live_adapter = cTraderLiveAdapter(
            paper_trader=self._paper_trader,
            strategies=self._strategies,
            symbols=[cfg.symbol],
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

    def _wire_callbacks(self):
        if self._market_feed is None:
            return

        self._market_feed.on_tick(self._on_tick)

    def _start_market_feed(self) -> bool:
        cfg = self._config
        creds = self._credentials or self._build_quote_credentials()

        self._market_feed = LiveMarketDataFeed(creds)
        self._wire_callbacks()

        symbol_key = cfg.symbol.upper().replace("/", "")
        subscribe_name = self._resolve_feed_symbol_name(symbol_key)

        if subscribe_name is None:
            logger.error(
                "Cannot resolve symbol %s for market data feed", cfg.symbol
            )
            return False

        success = self._market_feed.start(auto_subscribe=[subscribe_name])
        if success:
            logger.info("Market data feed connected for %s", cfg.symbol)
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

    def _build_quote_credentials(self) -> cTraderCredentials:
        from dotenv import load_dotenv
        import os
        from pathlib import Path

        env_path = Path(__file__).resolve().parents[4] / ".env"
        if env_path.exists():
            load_dotenv(env_path)

        host = os.environ.get("CTRADER_HOST", self._config.quote_host)
        port = int(
            os.environ.get("CTRADER_SSL_PORT", str(self._config.quote_port))
        )

        return cTraderCredentials(
            host=host,
            port=port,
            use_ssl=self._config.use_ssl,
            sender_comp_id=os.environ.get("CTRADER_SENDER_COMP_ID", ""),
            target_comp_id=os.environ.get(
                "CTRADER_TARGET_COMP_ID", "cServer"
            ),
            sender_sub_id=os.environ.get(
                "CTRADER_QUOTE_SENDER_SUB_ID",
                self._config.quote_sender_sub_id,
            ),
            username=os.environ.get("CTRADER_ACCOUNT", ""),
            password=os.environ.get("CTRADER_PASSWORD", ""),
        )

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
        if symbol_name is None or symbol_name != self._config.symbol:
            return

        bar = Bar(
            time=tick.timestamp,
            open=tick.bid,
            high=tick.ask,
            low=tick.bid,
            close=tick.bid,
            volume=0,
        )

        with self._lock:
            if symbol_name not in self._bars:
                self._bars[symbol_name] = []
            self._bars[symbol_name].append(bar)

            if len(self._bars[symbol_name]) > self._config.max_bars_per_symbol:
                self._bars[symbol_name] = self._bars[symbol_name][
                    -self._config.max_bars_per_symbol :
                ]

        self._update_paper_trader_prices(tick, symbol_name)

        if len(self._bars[symbol_name]) < self._config.min_bars_for_evaluation:
            return

        self._evaluate_strategies(symbol_name)

    def _resolve_symbol_name(self, tick: Tick) -> Optional[str]:
        if self._market_feed is None:
            return None

        symbol_info = self._market_feed.symbols.get(tick.symbol_id)
        if symbol_info is None:
            return None

        feed_name = symbol_info.name
        no_slash = feed_name.replace("/", "")
        cfg_normalized = self._config.symbol.upper().replace("/", "")

        if no_slash == cfg_normalized:
            return cfg_normalized
        return None

    def _update_paper_trader_prices(self, tick: Tick, symbol_name: str):
        if self._paper_trader is None:
            return

        mid_price = tick.mid
        self._paper_trader.update_market_prices({symbol_name: mid_price})

    def _evaluate_strategies(self, symbol: str):
        if self._live_adapter is None:
            return

        with self._lock:
            bars = self._bars.get(symbol, [])

        if not bars:
            return

        state = MarketState(bars=list(bars))

        signals = self._live_adapter.evaluate_all_strategies({symbol: state})

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

            self._trigger_callback("on_signal_traded", s)

    def _on_trade_executed(self, result):
        if self._trade_logger and result.order:
            self._trade_logger.log_trade_opened(
                result.order, result.position
            )
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
        }
