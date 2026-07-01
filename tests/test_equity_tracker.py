"""Tests for equity curve tracking (A8)."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure src is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "forex-bot"))

from reporting.equity_tracker import EquityTracker, EquitySnapshot


@pytest.fixture
def tracker(tmp_path):
    """Fresh EquityTracker pointing at a temp directory."""
    return EquityTracker(data_dir=tmp_path, starting_balance=10_000.0)


# ── Test 1: record() appends to JSONL file ────────────────────────────────

def test_record_appends_to_jsonl(tracker, tmp_path):
    """Each call to record() appends one JSON line to the snapshots file."""
    tracker.record(10_100.0, 1)
    tracker.record(10_050.0, 2)
    tracker.record(10_200.0, 3)

    snapshots_file = tmp_path / "forex" / "equity_snapshots.jsonl"
    assert snapshots_file.exists(), "Snapshots JSONL file should be created"

    lines = snapshots_file.read_text().strip().split("\n")
    assert len(lines) == 3, "Should have 3 snapshot lines"

    first = json.loads(lines[0])
    assert first["balance"] == 10_100.0
    assert first["trade_count"] == 1
    assert "timestamp" in first
    assert "drawdown_pct" in first
    assert "peak_balance" in first
    assert "daily_pnl" in first


# ── Test 2: daily_summary() computes correct P&L ──────────────────────────

def test_daily_summary_computes_pnl(tracker):
    """daily_summary() should compute open/close/P&L from same-day snapshots."""
    # All snapshots on the same day
    tracker.record(10_000.0, 0)
    tracker.record(10_200.0, 2)
    tracker.record(10_150.0, 3)

    ds = tracker.daily_summary()
    assert ds is not None
    assert ds.open_balance == 10_000.0
    assert ds.close_balance == 10_150.0
    assert ds.pnl == 150.0
    assert ds.pnl_pct == 1.5
    assert ds.trades == 3
    assert ds.ftmo_status == "OK"


def test_daily_summary_ftmo_warning_on_large_loss(tracker):
    """A >5% loss should flag FTMO WARNING."""
    tracker.record(10_000.0, 0)
    tracker.record(9_400.0, 1)  # -6%

    ds = tracker.daily_summary()
    assert ds.ftmo_status == "WARNING"


# ── Test 3: weekly_summary() aggregates days correctly ────────────────────

def test_weekly_summary_aggregates(tracker):
    """weekly_summary() should aggregate across the full week."""
    # Simulate a week of data using direct JSONL injection
    snapshots_file = tracker._snapshots_path
    base_date = "2025-01-06"  # Monday of ISO week 2025-W02
    lines = []
    bal = 10_000.0
    trades = 0
    for day_offset in range(5):  # Mon-Fri
        d = f"2025-01-{6 + day_offset:02d}"
        for hour in range(9, 17, 2):
            trades += 1
            lines.append(json.dumps({
                "timestamp": f"{d}T{hour:02d}:00:00+00:00",
                "balance": round(bal, 2),
                "daily_pnl": 50.0,
                "peak_balance": round(bal, 2),
                "drawdown_pct": 0.0,
                "trade_count": trades,
            }))
            bal += 50.0
    snapshots_file.write_text("\n".join(lines) + "\n")

    ws = tracker.weekly_summary()
    assert ws is not None
    assert ws.start_balance == 10_000.0
    # 20 snapshots, first at 10000, each +50 → last at 10950
    assert ws.end_balance == 10_950.0
    assert ws.pnl == 950.0
    # trade_count delta: last(20) - first(1) = 19
    assert ws.total_trades == 19
    assert ws.best_day is not None
    assert ws.worst_day is not None


# ── Test 4: drawdown_pct calculated correctly from peak ───────────────────

def test_drawdown_calculated_from_peak(tracker):
    """drawdown_pct should reflect drop from peak, not from day open."""
    # Rise to peak then drawdown
    tracker.record(10_000.0, 0)
    tracker.record(10_500.0, 1)   # new peak
    tracker.record(10_200.0, 2)   # drawdown from peak

    snapshots_file = tracker._snapshots_path
    lines = snapshots_file.read_text().strip().split("\n")
    last = json.loads(lines[-1])

    # Drawdown = (10500 - 10200) / 10500 * 100 = 2.857%
    expected_dd = round((10_500 - 10_200) / 10_500 * 100, 4)
    assert last["drawdown_pct"] == expected_dd
    assert last["peak_balance"] == 10_500.0


def test_drawdown_zero_when_at_peak(tracker):
    """drawdown_pct should be 0 when balance equals or exceeds peak."""
    tracker.record(10_000.0, 0)
    tracker.record(10_500.0, 1)

    snapshots_file = tracker._snapshots_path
    lines = snapshots_file.read_text().strip().split("\n")
    last = json.loads(lines[-1])
    assert last["drawdown_pct"] == 0.0


# ── Test 5: write_daily_report produces markdown ──────────────────────────

def test_write_daily_report(tracker, tmp_path):
    """write_daily_report should produce a markdown file."""
    tracker.record(10_000.0, 0)
    tracker.record(10_200.0, 2)

    report_path = tracker.write_daily_report()
    assert report_path is not None
    assert report_path.exists()
    content = report_path.read_text()
    assert "Equity Daily Report" in content
    assert "P&L" in content
    assert "FTMO" in content
