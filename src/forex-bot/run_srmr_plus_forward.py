"""Forward Test Runner — Multi-Strategy Orchestrator.

Replaces the old per-engine runner scripts with the unified
MultiStrategyOrchestrator. Strategy configuration is driven by
config/strategies.yaml.

Usage:
  PYTHONPATH=src/forex-bot:src python -m run_srmr_plus_forward
  PYTHONPATH=src/forex-bot:src python -m run_srmr_plus_forward --live-execution
"""

import logging
import os
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not _env_path.exists():
        _env_path = Path(__file__).resolve().parents[3] / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass

from engine.orchestrator import MultiStrategyOrchestrator
from adapters.ctrader.models import cTraderCredentials

logger = logging.getLogger(__name__)

STATUS_INTERVAL_S = 60


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


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Forward Test (Multi-Strategy Orchestrator)"
    )
    parser.add_argument(
        "--live-execution",
        action="store_true",
        help="Enable real broker order execution (default is paper-only). "
        "USE WITH EXTREME CAUTION.",
    )
    parser.add_argument(
        "--config",
        default="config/strategies.yaml",
        help="Path to strategy configuration YAML",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    live_mode = args.live_execution
    if live_mode:
        logger.warning("=" * 60)
        logger.warning("LIVE EXECUTION ENABLED — REAL ORDERS WILL BE SENT")
        logger.warning("Account: %s", os.environ.get("CTRADER_ACCOUNT", "17087404"))
        logger.warning("=" * 60)

    creds = _load_credentials()
    config_path = args.config

    if not Path(config_path).exists():
        logger.error("Config not found: %s", config_path)
        sys.exit(1)

    orchestrator = MultiStrategyOrchestrator(
        config_path=config_path,
        credentials=creds,
        log_dir="logs/forward_test",
        live_mode=live_mode,
    )

    def _status_loop():
        while orchestrator.is_running:
            time.sleep(STATUS_INTERVAL_S)
            if not orchestrator.is_running:
                break
            status = orchestrator.get_status()
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).strftime("%H:%M:%S")
            parts = [f"[{now} UTC]"]
            if status.strategies:
                parts.append(f"strategies={','.join(status.strategies)}")
            parts.append(f"signals={status.signals_generated}")
            parts.append(f"executed={status.signals_executed}")
            parts.append(f"rejected={status.signals_rejected}")
            parts.append(f"ticks={status.ticks_received}")
            parts.append(f"errors={status.evaluation_errors}")
            parts.append(f"conn={'Y' if status.connected else 'N'}")
            print(" | ".join(parts))

    import threading

    status_thread = threading.Thread(target=_status_loop, daemon=True, name="status")
    status_thread.start()

    success = orchestrator.start()
    if not success:
        logger.error("Failed to start orchestrator")
        sys.exit(1)

    mode = "LIVE" if live_mode else "PAPER"
    print("=" * 60)
    print(f"FORWARD TEST ({mode}) — Orchestrator")
    print("=" * 60)
    print(f"Config: {config_path}")
    print(
        f"Strategies: {', '.join(s for s in (orchestrator.get_status().strategies or []))}"
    )
    print("Press Ctrl+C to stop.")
    print("-" * 60)

    try:
        while orchestrator.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    orchestrator.stop()
    status = orchestrator.get_status()
    print(f"\nStopped after {status.uptime_sec:.0f}s")
    print("Shutdown complete.")


if __name__ == "__main__":
    main()
