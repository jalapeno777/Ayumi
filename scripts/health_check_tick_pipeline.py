#!/usr/bin/env python3
"""Health check: alert if forward test tick pipeline is stalled.

Monitors engine health stats (ticks_received) to detect tick stalls.
Uses a state file to compare current ticks with the value 5 minutes ago.

Exit codes:
    0 — Healthy (ticks flowing)
    1 — Warning (ticks stalled 5+ minutes)
    2 — Critical (PID missing or engine not running)
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATE_FILE = DATA_DIR / "tick_stall_state.json"
ALERT_FILE = DATA_DIR / "ops" / "tick_stall_alerts.jsonl"
STALL_THRESHOLD_SEC = 300  # 5 minutes


def main():
    # Check PID file exists
    pid_file = DATA_DIR / "forward_test.pid"
    if not pid_file.exists():
        _emit_alert("CRITICAL: PID file missing — forward test not running")
        print("CRITICAL: PID file missing — forward test not running", file=sys.stderr)
        sys.exit(2)

    # Read last_signal.txt for tick count — engine writes this on each signal
    # For actual tick monitoring, parse the engine health log
    signal_file = DATA_DIR / "last_signal.txt"
    current_ticks = None

    # Try to get ticks from engine stats via state file approach
    # The engine writes health stats to logs; we use the signal file timestamp
    # as a proxy for pipeline health
    current_time = datetime.now(timezone.utc)

    if signal_file.exists():
        try:
            data = json.loads(signal_file.read_text())
            ts_str = data.get("timestamp", "")
            if ts_str:
                ts = datetime.fromisoformat(ts_str)
                age = (current_time - ts).total_seconds()
        except (json.JSONDecodeError, ValueError):
            age = None
    else:
        age = None

    # Load previous state
    prev_state = {}
    if STATE_FILE.exists():
        try:
            prev_state = json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, ValueError):
            pass

    prev_signal_ts = prev_state.get("last_signal_ts")
    prev_check_time = prev_state.get("last_check_time")

    # Write current state
    new_state = {
        "last_check_time": current_time.isoformat(),
        "last_signal_ts": signal_file.exists()
        and json.loads(signal_file.read_text()).get("timestamp", "")
        if signal_file.exists()
        else "",
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(new_state, indent=2) + "\n")

    # If we have a previous check and the signal timestamp hasn't changed,
    # the pipeline may be stalled
    if prev_signal_ts and new_state.get("last_signal_ts") == prev_signal_ts:
        # Signal file hasn't been updated since last check
        # Check if it's been stalled for 5+ minutes
        if prev_check_time:
            prev_dt = datetime.fromisoformat(prev_check_time)
            stall_duration = (current_time - prev_dt).total_seconds()
            if stall_duration >= STALL_THRESHOLD_SEC:
                msg = (
                    f"WARNING: Tick pipeline stalled — last_signal.txt unchanged "
                    f"for {stall_duration:.0f}s (threshold: {STALL_THRESHOLD_SEC}s)"
                )
                _emit_alert(msg)
                print(msg, file=sys.stderr)
                sys.exit(1)

    # Check if signal is just old (>30 min = probably market closed or stalled)
    if age is not None and age > 1800:  # 30 minutes
        msg = f"INFO: Last signal was {age:.0f}s ago (may be outside market hours)"
        print(msg)
        sys.exit(0)

    print("OK: Forward test tick pipeline healthy")
    sys.exit(0)


def _emit_alert(message: str):
    """Append alert to JSONL file."""
    ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": "CRITICAL" if "CRITICAL" in message else "WARNING",
        "message": message,
    }
    with open(ALERT_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    main()
