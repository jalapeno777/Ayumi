#!/usr/bin/env python3
"""Forward test runner — Session Range MR GBPUSD on cTrader demo.

Wires together:
  LiveMarketDataFeed -> TickBarBuilder -> SessionRangeMeanReversionStrategy
    -> cTraderSignalAdapter -> PaperTrader -> TradeLogger

Starts in paper mode.  Pass --live to switch to live execution.

Features:
  - Live spread + slippage simulation on paper fills
  - Session-aware: only trades during Asian/early London (per strategy rules)
  - Passes live bid/ask spread to adapter for realistic fills
  - --reset clears synthetic trade logs and starts fresh

Usage:
    python scripts/run_live_session_range_gbpusd.py [--live] [--bar-minutes 15] [--reset]
"""

import argparse
import logging
import shutil
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "forex-bot"))

from backtest.engine import Bar, MarketState, SessionType
from adapters.ctrader.market_data_feed import DEFAULT_SYMBOLS, LiveMarketDataFeed, Tick
from adapters.ctrader.models import cTraderCredentials
from adapters.ctrader.session_range_gbpusd import (
    SessionRangeGBPUSDConfig,
    build_gbpusd_paper_trader,
    load_credentials_from_env,
)
from adapters.ctrader.tick_bar_builder import TickBarBuilder
from strategies.session_range_mean_reversion import (
    SessionRangeMeanReversionStrategy,
    SessionRangeMRConfig,
)

logger = logging.getLogger("forward_test")

SYMBOL = "GBP/USD"
STRATEGY_SYMBOL = "GBPUSD"
MIN_BARS = 100
STATUS_INTERVAL_S = 300
LOG_DIR = "logs/trades"


def _build_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _current_session() -> SessionType:
    utc_hour = datetime.now(timezone.utc).hour
    if 0 <= utc_hour < 7:
        return SessionType.ASIAN
    if 7 <= utc_hour < 11:
        return SessionType.LONDON
    if 11 <= utc_hour < 16:
        return SessionType.NY_AM
    if 16 <= utc_hour < 20:
        return SessionType.NY_PM
    return SessionType.OUTSIDE


def _is_trading_session() -> bool:
    session = _current_session()
    return session in (SessionType.ASIAN, SessionType.LONDON, SessionType.NY_AM, SessionType.NY_PM)


def _reset_synthetic_data(log_dir: str):
    log_path = Path(log_dir)
    if not log_path.exists():
        logger.info("No existing trade logs to reset")
        return

    csv_files = list(log_path.glob("session_range_mr_gbpusd_*.csv"))
    if not csv_files:
        logger.info("No synthetic trade logs found")
        return

    archive_dir = log_path / "synthetic_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    removed = 0
    for f in csv_files:
        content = f.read_text()
        if "1.26" in content and ("1.258" in content or "1.262" in content):
            dest = archive_dir / f.name
            shutil.move(str(f), str(dest))
            removed += 1
            logger.info(f"Archived synthetic log: {f.name} -> {dest}")

    logger.info(f"Reset complete: archived {removed} synthetic trade log(s)")
    if removed == 0:
        logger.info("No synthetic data detected — logs may contain real data, not clearing")


def main():
    parser = argparse.ArgumentParser(description="Forward test: Session Range MR GBPUSD")
    parser.add_argument("--live", action="store_true", help="Enable live execution")
    parser.add_argument("--bar-minutes", type=int, default=15, help="Bar timeframe in minutes")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    parser.add_argument("--reset", action="store_true", help="Clear synthetic trade logs and start fresh")
    args = parser.parse_args()

    _build_logging(args.verbose)

    if args.reset:
        _reset_synthetic_data(LOG_DIR)

    shutdown_event = _install_shutdown_handlers()

    config = SessionRangeGBPUSDConfig(live_mode=args.live)
    strategy = SessionRangeMeanReversionStrategy(SessionRangeMRConfig())

    if args.live:
        logger.warning("=== LIVE MODE ENABLED — real orders will be placed ===")
        credentials = load_credentials_from_env()
        trade_credentials = cTraderCredentials(
            host=credentials.host,
            port=credentials.port,
            use_ssl=credentials.use_ssl,
            sender_comp_id=credentials.sender_comp_id,
            target_comp_id=credentials.target_comp_id,
            sender_sub_id=credentials.sender_sub_id,
            username=credentials.username,
            password=credentials.password,
        )
        quote_credentials = cTraderCredentials(
            host=credentials.host,
            port=5211,
            use_ssl=credentials.use_ssl,
            sender_comp_id=credentials.sender_comp_id,
            target_comp_id=credentials.target_comp_id,
            sender_sub_id="QUOTE",
            username=credentials.username,
            password=credentials.password,
        )
    else:
        logger.info("=== PAPER MODE — no real orders ===")
        trade_credentials = load_credentials_from_env()
        quote_credentials = cTraderCredentials(
            host=trade_credentials.host,
            port=5211,
            use_ssl=trade_credentials.use_ssl,
            sender_comp_id=trade_credentials.sender_comp_id,
            target_comp_id=trade_credentials.target_comp_id,
            sender_sub_id="QUOTE",
            username=trade_credentials.username,
            password=trade_credentials.password,
        )

    trader, adapter, trade_logger = build_gbpusd_paper_trader(strategy, config)

    if args.reset:
        cleared = trader.clear_stuck_positions()
        if cleared > 0:
            logger.info(f"Cleared {cleared} stuck position(s) from previous runs")
        trader.reset()
        logger.info("Paper trader reset to initial state")

    bar_builder = TickBarBuilder(bar_minutes=args.bar_minutes, max_bars=500)

    def on_tick(tick: Tick):
        spread = tick.spread
        adapter.update_spread(spread)
        bar_builder.on_tick(tick)

    def on_bar_complete(symbol_name: str, bar: Bar):
        if symbol_name != SYMBOL:
            return
        bars = bar_builder.get_bars(SYMBOL)
        if len(bars) < MIN_BARS:
            logger.info(f"Accumulating bars: {len(bars)}/{MIN_BARS}")
            return

        tick = feed.get_tick(SYMBOL)
        current_spread = tick.spread if tick else 0.0

        market_state = MarketState(bars=bars, current_session=_current_session())
        try:
            adapter.evaluate_and_trade(market_state, spread=current_spread)
        except Exception:
            logger.exception("Error evaluating strategy")

    bar_builder.register_bar_callback(on_bar_complete)

    feed = LiveMarketDataFeed(quote_credentials)
    bar_builder.set_symbol_map(dict(DEFAULT_SYMBOLS))

    logger.info("Starting market data feed...")
    if not feed.start(auto_subscribe=[SYMBOL]):
        logger.error("Failed to start market data feed — exiting")
        sys.exit(1)

    feed.on_tick(on_tick)

    logger.info(
        f"Forward test running — {SYMBOL}, {args.bar_minutes}m bars, "
        f"{'LIVE' if args.live else 'PAPER'} mode"
    )
    logger.info(f"Need {MIN_BARS} bars before strategy activates (~{MIN_BARS * args.bar_minutes // 60}h)")
    logger.info("Spread/slippage simulation enabled on paper fills")

    last_status = 0.0
    try:
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=1.0)

            now = time.monotonic()
            if now - last_status >= STATUS_INTERVAL_S:
                last_status = now
                stats = trader.get_stats()
                risk = trader.get_risk_guard_stats()
                bars = bar_builder.get_bars(SYMBOL)
                summary = trade_logger.get_summary()
                tick = feed.get_tick(SYMBOL)
                current_spread = tick.spread if tick else 0.0
                logger.info(
                    f"[STATUS] session={_current_session().name} "
                    f"bars={len(bars)} signals={stats.total_signals_processed} "
                    f"trades={stats.trades_executed} rejected={stats.trades_rejected} "
                    f"risk_blocked={stats.signals_blocked_by_risk} "
                    f"balance={stats.current_balance:.2f} "
                    f"realized={stats.realized_pnl:.2f} unrealized={stats.unrealized_pnl:.2f} "
                    f"daily_pnl={risk.get('daily_pnl', 0):.2f} "
                    f"dd_pct={risk.get('drawdown_pct', 0):.2%} "
                    f"spread={current_spread:.5f}"
                )
                if summary["total_trades"] > 0:
                    logger.info(
                        f"[PERF] win_rate={summary['win_rate']:.1%} "
                        f"wins={summary['wins']} losses={summary['losses']} "
                        f"pnl={summary['total_pnl']:.2f}"
                    )

            tick = feed.get_tick(SYMBOL)
            if tick:
                adapter.update_spread(tick.spread)
                trader.update_market_prices({STRATEGY_SYMBOL: tick.mid})
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        logger.info("Shutting down...")
        feed.stop()
        stats = trader.get_stats()
        summary = trade_logger.get_summary()
        logger.info(
            f"[FINAL] signals={stats.total_signals_processed} "
            f"trades={stats.trades_executed} "
            f"balance={stats.current_balance:.2f} "
            f"realized={stats.realized_pnl:.2f} "
            f"win_rate={summary['win_rate']:.1%}" if summary["total_trades"] else ""
        )


def _install_shutdown_handlers():
    import threading
    event = threading.Event()

    def handler(signum, frame):
        logger.info(f"Received signal {signum} — shutting down")
        event.set()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
    return event


if __name__ == "__main__":
    main()
