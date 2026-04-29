"""SRMR+ Forward Test Runner — H1 bars, walk-forward validated pairs.

Launches ForwardTestEngine instances for each Optuna-validated SRMR+ pair
(GBPUSD, EURUSD, XAUUSD) on H1 bars via cTrader live market data.

Usage:
  PYTHONPATH=src/forex-bot:src python -m run_srmr_plus_forward
  PYTHONPATH=src/forex-bot:src python -m run_srmr_plus_forward --paper-only
"""

import logging
import os
import signal as sig
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not _env_path.exists():
        _env_path = Path(__file__).resolve().parents[3] / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass

from adapters.ctrader.forward_test_engine import ForwardTestEngine, ForwardTestConfig
from adapters.ctrader.models import cTraderCredentials
from adapters.ctrader.risk_guard import FTMOConfig
from strategies.srmr_plus import SRMRPlusStrategy, SRMRPlusConfig

logger = logging.getLogger(__name__)

LOG_DIR = "logs/srmr_plus"
STATUS_INTERVAL_S = 60

SRMR_PLUS_PAIRS = [
    {
        "symbol": "GBPUSD",
        "min_confidence": 0.40,
        "config": SRMRPlusConfig(
            session_range_min_pips=25.0,
            entry_near_extreme_pips=15.0,
            hard_cap_sl_pips=25.0,
            tp1_rr=1.0,
            tp2_rr=1.5,
        ),
    },
    {
        "symbol": "EURUSD",
        "min_confidence": 0.40,
        "config": SRMRPlusConfig(
            session_range_min_pips=15.0,
            entry_near_extreme_pips=12.0,
            hard_cap_sl_pips=20.0,
            tp1_rr=1.0,
            tp2_rr=1.5,
        ),
    },
    {
        "symbol": "XAUUSD",
        "min_confidence": 0.40,
        "config": SRMRPlusConfig(
            session_range_min_pips=200.0,
            entry_near_extreme_pips=150.0,
            hard_cap_sl_pips=300.0,
            tp1_rr=1.0,
            tp2_rr=1.5,
            pip_value=0.01,
        ),
    },
]


def _load_credentials() -> cTraderCredentials:
    host = os.environ.get("CTRADER_HOST", "")
    readonly_port = int(os.environ.get("CTRADER_READONLY_SSL_PORT", "5211"))
    sender = os.environ.get("CTRADER_SENDER_COMP_ID", "")
    target = os.environ.get("CTRADER_TARGET_COMP_ID", "cServer")
    username = os.environ.get("CTRADER_ACCOUNT", "")
    password = os.environ.get("CTRADER_PASSWORD", "")
    missing = [
        k
        for k, v in [
            ("CTRADER_HOST", host),
            ("CTRADER_SENDER_COMP_ID", sender),
            ("CTRADER_ACCOUNT", username),
            ("CTRADER_PASSWORD", password),
        ]
        if not v
    ]
    if missing:
        raise ValueError(f"Missing required env vars: {', '.join(missing)}")
    return cTraderCredentials(
        host=host,
        port=readonly_port,
        use_ssl=True,
        sender_comp_id=sender,
        target_comp_id=target,
        sender_sub_id="QUOTE",
        target_sub_id="QUOTE",
        username=username,
        password=password,
    )


@dataclass
class PairEngine:
    symbol: str
    engine: ForwardTestEngine
    thread: threading.Thread | None = None
    running: bool = False


class SRMRPlusForwardTest:
    def __init__(self, paper_only: bool = False):
        self._paper_only = paper_only
        self._shutdown = False
        self._engines: list[PairEngine] = []
        self._status_thread: threading.Thread | None = None

    def _build_engines(self):
        creds = _load_credentials()
        ftmo = FTMOConfig(
            daily_loss_limit_pct=0.04,
            total_drawdown_limit_pct=0.07,
            min_risk_reward=0.0,
            max_trades_per_day=10,
            max_positions=5,
        )

        for pair in SRMR_PLUS_PAIRS:
            strategy = SRMRPlusStrategy(config=pair["config"])
            config = ForwardTestConfig(
                symbol=pair["symbol"],
                starting_balance=10_000.0,
                min_confidence=pair["min_confidence"],
                bar_period_minutes=60,
                min_bars_for_evaluation=50,
                max_bars_per_symbol=500,
                stats_interval_sec=STATUS_INTERVAL_S,
                live_mode=not self._paper_only,
                log_dir=LOG_DIR,
                health_monitor_interval_sec=5.0,
                max_reconnect_attempts=20,
                reset_on_start=True,
            )
            engine = ForwardTestEngine(
                config=config,
                strategies=[strategy],
                ftmo_config=ftmo,
                credentials=creds,
            )
            pe = PairEngine(symbol=pair["symbol"], engine=engine)
            self._engines.append(pe)
            logger.info(f"Engine built: {pair['symbol']} (H1, SRMR+)")

    def _on_signal_traded(self, signal):
        logger.info(
            f"SIGNAL: {signal.direction.value} {signal.symbol} @ {signal.entry_price:.5f} "
            f"conf={signal.confidence:.2f}"
        )

    def _status_loop(self):
        while not self._shutdown:
            time.sleep(STATUS_INTERVAL_S)
            if self._shutdown:
                break
            now = datetime.now(timezone.utc).strftime("%H:%M:%S")
            parts = [f"[{now} UTC]"]
            for pe in self._engines:
                if not pe.running:
                    continue
                health = pe.engine.health
                stats = pe.engine.get_stats().get("trading", {})
                bal = stats.get("current_balance", 0)
                trades = stats.get("trades_executed", 0)
                signals = health.signals_generated
                ticks = health.ticks_received
                connected = "Y" if health.connected else "N"
                parts.append(
                    f"{pe.symbol}: bal=${bal:.2f} trades={trades} "
                    f"signals={signals} ticks={ticks} conn={connected}"
                )
            print(" | ".join(parts))

    def run(self):
        self._build_engines()

        print("=" * 60)
        mode = "PAPER-ONLY" if self._paper_only else "DEMO EXECUTION"
        print(f"SRMR+ FORWARD TEST ({mode})")
        print("=" * 60)
        symbols = [pe.symbol for pe in self._engines]
        print(f"Pairs: {', '.join(symbols)}")
        print(f"Bar period: H1")
        print(f"Strategies: SRMR+ (walk-forward validated)")
        print("-" * 60)

        for pe in self._engines:
            pe.engine.register_callback("on_signal_traded", self._on_signal_traded)
            t = threading.Thread(
                target=self._run_engine, args=(pe,), daemon=True, name=f"ft-{pe.symbol}"
            )
            pe.thread = t
            t.start()
            pe.running = True
            logger.info(f"Started engine thread for {pe.symbol}")

        sig.signal(sig.SIGINT, self._shutdown_handler)
        sig.signal(sig.SIGTERM, self._shutdown_handler)

        self._status_thread = threading.Thread(
            target=self._status_loop, daemon=True, name="status"
        )
        self._status_thread.start()

        print("All engines started. Press Ctrl+C to stop.")
        print("-" * 60)

        try:
            while not self._shutdown:
                time.sleep(1)
        except KeyboardInterrupt:
            self._shutdown_handler()

    def _run_engine(self, pe: PairEngine):
        try:
            success = pe.engine.start()
            if not success:
                logger.error(f"{pe.symbol}: engine failed to start")
                pe.running = False
                return
            logger.info(f"{pe.symbol}: engine running")
            while not self._shutdown and pe.engine.is_running:
                time.sleep(1)
            pe.engine.stop()
            logger.info(f"{pe.symbol}: engine stopped")
        except Exception as e:
            logger.error(f"{pe.symbol}: engine error: {e}", exc_info=True)
        finally:
            pe.running = False

    def _shutdown_handler(self, signum=None, frame=None):
        print("\nShutting down...")
        self._shutdown = True
        for pe in self._engines:
            if pe.running:
                pe.engine.stop()
        time.sleep(2)
        for pe in self._engines:
            stats = pe.engine.get_stats().get("trading", {})
            bal = stats.get("current_balance", 0)
            trades = stats.get("trades_executed", 0)
            pnl = stats.get("realized_pnl", 0)
            print(f"  {pe.symbol}: bal=${bal:.2f} trades={trades} pnl=${pnl:.2f}")
        print("Shutdown complete.")
        sys.exit(0)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="SRMR+ Forward Test")
    parser.add_argument(
        "--paper-only",
        action="store_true",
        help="Local simulation only - no real broker orders",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    os.makedirs(LOG_DIR, exist_ok=True)
    system = SRMRPlusForwardTest(paper_only=args.paper_only)
    system.run()


if __name__ == "__main__":
    main()
