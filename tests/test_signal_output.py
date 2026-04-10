"""Tests for signal_output.py"""

import json
import pytest
from datetime import datetime, timezone
from signal_engine.signal_output import (
    format_signal_json,
    parse_signal_json,
    create_signal,
)
from signal_engine.data_types import Signal


def _make_signal(**overrides):
    defaults = dict(
        symbol="EURUSD",
        direction="long",
        entry_price=1.08500,
        stop_loss=1.08300,
        take_profit=1.08900,
        confidence=0.82,
        pattern_type="M",
        timeframe="M15",
        gates_passed=["structure", "session"],
        boosters_active=["volume", "level_proximity"],
    )
    defaults.update(overrides)
    return Signal(**defaults)


def test_format_signal_json_structure():
    sig = _make_signal()
    result = json.loads(format_signal_json(sig))

    assert "signal_id" in result
    assert "timestamp" in result
    assert result["direction"] == "long"
    assert result["entry_price"] == 1.08500
    assert result["confidence"] == 0.82


def test_format_with_gate_results():
    sig = _make_signal()
    gates = {"structure": True, "session": True, "ema": False}
    result = json.loads(format_signal_json(sig, gates))

    assert result["gate_results"]["structure"] is True
    assert result["gate_results"]["ema"] is False


def test_parse_signal_json_roundtrip():
    sig = _make_signal()
    json_str = format_signal_json(sig)
    parsed = parse_signal_json(json_str)

    assert parsed["direction"] == "long"
    assert parsed["symbol"] == "EURUSD"
    assert parsed["confidence"] == 0.82


def test_create_signal_factory():
    sig = create_signal(
        symbol="GBPUSD",
        direction="short",
        entry_price=1.26500,
        stop_loss=1.26800,
        take_profit=1.25900,
        confidence=0.75,
        pattern_type="W",
        session="London",
    )

    assert sig.symbol == "GBPUSD"
    assert sig.direction == "short"
    assert sig.pattern_type == "W"
    assert sig.setup_type == "London"
    assert sig.timestamp is not None


def test_signal_id_is_unique():
    sig = _make_signal()
    j1 = json.loads(format_signal_json(sig))
    j2 = json.loads(format_signal_json(sig))
    assert j1["signal_id"] != j2["signal_id"]


def test_timestamp_iso_format():
    sig = _make_signal(timestamp=datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc))
    result = json.loads(format_signal_json(sig))
    assert "2026-04-10" in result["timestamp"]
