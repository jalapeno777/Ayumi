#!/usr/bin/env python3
"""
Live FIX Order Lifecycle Validation — cTrader TRADE Port
=========================================================

Validates the full order lifecycle against the live cTrader TRADE port (5202):

  1. Connect (plain text) + authenticate
  2. Market order:  NewOrderSingle (35=D) -> ExecutionReport (35=8) fill
  3. Limit order:   NewOrderSingle (35=D) -> ExecutionReport new -> cancel
  4. Cancel:        OrderCancelRequest (35=F) -> ExecutionReport cancelled (35=8)

Usage:
    python scripts/validate_fix_order_lifecycle.py

Requires .env with CTRADER_* credentials (demo account).
"""

import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from adapters.ctrader.models import (  # noqa: I001
    cTraderCredentials,
    TradeDirection,
    OrderType,
)
from adapters.ctrader.api_client import FIXClient, FIXMessage

SOH = "\x01"

MSG_TYPE_NAMES = {
    "0": "Heartbeat",
    "1": "TestRequest",
    "3": "Reject",
    "5": "Logout",
    "8": "ExecutionReport",
    "9": "OrderCancelReject",
    "A": "Logon",
    "D": "NewOrderSingle",
    "F": "OrderCancelRequest",
}


class MessageLog:
    """Intercepts all FIX messages for audit logging."""

    def __init__(self, client: FIXClient):
        self._entries: List[Dict[str, str]] = []
        self._orig_send = client._send_raw
        self._orig_handle = client._handle_message
        client._send_raw = self._wrap_send
        client._handle_message = self._wrap_handle

    def _wrap_send(self, wire: str) -> bool:
        self._entries.append(
            {
                "dir": "OUT",
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": self._parse_type(wire),
                "wire": wire,
            }
        )
        return self._orig_send(wire)

    def _wrap_handle(self, msg: FIXMessage):
        self._entries.append(
            {
                "dir": "IN",
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": msg.msg_type or "?",
                "wire": str(msg.fields),
            }
        )
        return self._orig_handle(msg)

    @staticmethod
    def _parse_type(wire: str) -> str:
        for f in wire.split(SOH):
            if f.startswith("35="):
                return f[3:]
        return "?"

    def dump(self):
        print("\n" + "=" * 80)
        print("FIX MESSAGE LOG")
        print("=" * 80)
        for e in self._entries:
            arrow = ">>>" if e["dir"] == "OUT" else "<<<"
            name = MSG_TYPE_NAMES.get(e["type"], e["type"])
            print(f"  {e['ts']}  {arrow} {name} ({e['type']})")
            display = e["wire"].replace(SOH, "|") if e["dir"] == "OUT" else e["wire"]
            for line in display[:400].split("|"):
                line = line.strip()
                if line:
                    print(f"       {line}")
        print("=" * 80)


def load_credentials() -> cTraderCredentials:
    dotenv_path = Path(__file__).resolve().parents[2] / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
    return cTraderCredentials(
        host=os.environ["CTRADER_HOST"],
        port=5202,
        use_ssl=False,
        sender_comp_id=os.environ["CTRADER_SENDER_COMP_ID"],
        target_comp_id=os.environ.get("CTRADER_TARGET_COMP_ID", "cServer"),
        sender_sub_id=os.environ.get("CTRADER_SENDER_SUB_ID", "TRADE"),
        username=os.environ["CTRADER_ACCOUNT"],
        password=os.environ["CTRADER_PASSWORD"],
    )


def validate() -> tuple:
    errors: List[str] = []
    results: Dict[str, dict] = {}
    msg_log: Optional[MessageLog] = None

    print("=" * 80)
    print("FIX ORDER LIFECYCLE VALIDATION")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)

    client: Optional[FIXClient] = None
    try:
        creds = load_credentials()
        print(f"\nHost: {creds.host}:{creds.port} (SSL={creds.use_ssl})")
        print(f"SenderCompID: {creds.sender_comp_id}")
        print(f"TargetCompID: {creds.target_comp_id}")
        print(f"Account: {creds.username}")

        client = FIXClient(creds)
        msg_log = MessageLog(client)

        logon_event = threading.Event()
        client.register_callback("on_logon", lambda msg: logon_event.set())

        # --- Step 1: Connect & Authenticate ---
        print("\n--- Step 1: Connect & Authenticate ---")
        if not client.connect():
            errors.append("connect() returned False")
            print("  [FAIL] Connection failed")
            return errors, results, msg_log

        if not logon_event.wait(timeout=15):
            errors.append("Logon confirmation timeout (15s)")
            print("  [FAIL] No logon confirmation received")
            return errors, results, msg_log

        print("  [OK] Connected and authenticated")
        time.sleep(1)

        # --- Step 2: Market Order ---
        print("\n--- Step 2: Market Order (symbol=1 EUR/USD, BUY 0.01 lot) ---")

        market_fill_event = threading.Event()
        market_reject_event = threading.Event()
        market_fill_data: Dict[str, object] = {}
        market_reject_reason: List[str] = []

        def on_market_fill(order, msg):
            if order:
                market_fill_data["order_id"] = order.order_id
                market_fill_data["price"] = order.filled_price
                market_fill_data["status"] = order.status.value
            market_fill_event.set()

        def on_market_reject(order, msg, reason):
            market_reject_reason.append(reason)
            market_reject_event.set()

        client.register_callback("on_order_filled", on_market_fill)
        client.register_callback("on_order_rejected", on_market_reject)

        market_order = client.send_order(
            symbol="1",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=0.01,
            comment="FIX lifecycle validation - market",
        )

        if not market_order:
            errors.append("Market order send_order() returned None")
            print("  [FAIL] Could not send market order")
        else:
            print(f"  [OUT] NewOrderSingle sent: {market_order.order_id}")

            if market_reject_event.wait(timeout=5):
                errors.append(f"Market order rejected: {market_reject_reason[0]}")
                print(f"  [FAIL] Market order rejected: {market_reject_reason[0]}")
            elif market_fill_event.wait(timeout=10):
                results["market_fill"] = dict(market_fill_data)
                price = market_fill_data.get("price")
                print(f"  [OK] Market order filled @ {price}")
            else:
                errors.append("Market order fill timeout (10s)")
                print("  [FAIL] No fill received within 10s")

        # --- Step 3: Limit Order + Cancel ---
        print("\n--- Step 3: Limit Order (symbol=1 EUR/USD, BUY 0.01 @ 0.5000) + Cancel ---")

        limit_new_event = threading.Event()
        limit_cancel_event = threading.Event()
        limit_fill_event = threading.Event()
        limit_cancel_data: Dict[str, object] = {}
        limit_new_data: Dict[str, object] = {}

        def on_limit_new(order, msg):
            if order:
                limit_new_data["order_id"] = order.order_id
            limit_new_event.set()

        def on_limit_cancel(order, msg):
            if order:
                limit_cancel_data["order_id"] = order.order_id
                limit_cancel_data["comment"] = order.comment
            limit_cancel_event.set()

        def on_limit_fill(order, msg):
            if order:
                limit_cancel_data["order_id"] = order.order_id
                limit_cancel_data["comment"] = f"Filled unexpectedly @ {order.filled_price}"
            limit_fill_event.set()

        client.register_callback("on_order_new", on_limit_new)
        client.register_callback("on_order_cancelled", on_limit_cancel)
        client.register_callback("on_order_filled", on_limit_fill)

        limit_order = client.send_order(
            symbol="1",
            direction=TradeDirection.LONG,
            order_type=OrderType.LIMIT,
            volume=0.01,
            price=0.5000,
            comment="FIX lifecycle validation - limit",
        )

        if not limit_order:
            errors.append("Limit order send_order() returned None")
            print("  [FAIL] Could not send limit order")
        else:
            print(f"  [OUT] NewOrderSingle sent: {limit_order.order_id} @ 0.5000")

            if limit_fill_event.wait(timeout=3):
                errors.append("Limit order filled unexpectedly (price 0.5000 should be far from market)")
                print(f"  [FAIL] Limit order filled unexpectedly: {limit_cancel_data.get('comment')}")
            elif limit_new_event.wait(timeout=5):
                print("  [OK] Limit order acknowledged (pending new)")
            else:
                print("  [WARN] No 'new' confirmation, proceeding with cancel...")

            time.sleep(1)

            print(f"  [OUT] OrderCancelRequest for {limit_order.order_id}")
            cancel_sent = client.cancel_order(limit_order.order_id)
            if not cancel_sent:
                errors.append("cancel_order() returned False")
                print("  [FAIL] Could not send cancel request")
            elif limit_cancel_event.wait(timeout=10):
                results["limit_cancel"] = dict(limit_cancel_data)
                comment = limit_cancel_data.get("comment", "")
                print(f"  [OK] Limit order cancelled: {comment}")
            else:
                errors.append("Cancel confirmation timeout (10s)")
                print("  [FAIL] No cancel confirmation within 10s")

    except KeyError as e:
        errors.append(f"Missing environment variable: {e}")
        print(f"  [FAIL] {e}")
    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")
        print(f"  [FAIL] {type(e).__name__}: {e}")
    finally:
        if client:
            print("\n--- Step 4: Disconnect ---")
            client.disconnect()
            time.sleep(1)
            print("  [OK] Disconnected")

    return errors, results, msg_log


def main():
    errors, results, msg_log = validate()

    if msg_log:
        msg_log.dump()

    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    if errors:
        print(f"FAILED - {len(errors)} error(s):")
        for e in errors:
            print(f"  x {e}")
        sys.exit(1)
    else:
        print("PASSED - Full order lifecycle validated successfully")
        mf = results.get("market_fill", {})
        print(f"  - Market order filled @ {mf.get('price')}")
        lc = results.get("limit_cancel", {})
        print(f"  - Limit order cancelled: {lc.get('comment', 'OK')}")
        sys.exit(0)


if __name__ == "__main__":
    main()
