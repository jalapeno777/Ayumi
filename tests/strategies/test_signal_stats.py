"""Tests for the SignalStatsRecorder (Phase 0 forward test diagnostics).

These tests use a per-test temp directory (``tmp_path``) for the JSONL
log so they don't pollute the real ``data/signal_stats.jsonl`` or
interfere with each other. No module-level sys.modules pollution —
each test instantiates a fresh ``SignalStatsRecorder`` and exercises
the real filesystem code path.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

import pytest
from signal_engine.signal_stats import (
    SignalRecord,
    SignalStatsRecorder,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    signal_id: str = "test-signal-1",
    strategy: str = "Test Strategy A",
    symbol: str = "GBPUSD",
    direction: str = "BUY",
    confidence: float = 0.7,
    confluence_score: float = 0.6,
    lots: float = 0.10,
    entry_price: float = 1.2500,
    sl_price: float = 1.2450,
    tp_price: float = 1.2600,
) -> SignalRecord:
    """Build a SignalRecord with sensible defaults for tests."""
    return SignalRecord(
        signal_id=signal_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        strategy=strategy,
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        rationale_tags=["london_session", "rsi_oversold"],
        confluence_score=confluence_score,
        lots=lots,
        entry_price=entry_price,
        sl_price=sl_price,
        tp_price=tp_price,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSignalStatsRecorder:
    def test_record_signal_appends_to_file(self, tmp_path):
        """First record_signal() creates the file with a single OPEN line."""
        log = tmp_path / "signal_stats.jsonl"
        assert not log.exists(), "fixture pre-condition: log should not exist yet"

        recorder = SignalStatsRecorder(log_path=str(log))
        rec = _make_signal(signal_id="s-001")
        returned_id = recorder.record_signal(rec)

        # Returned id matches the input
        assert returned_id == "s-001"

        # File was created and contains exactly one valid JSON line
        assert log.exists()
        with open(log, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]

        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["signal_id"] == "s-001"
        assert parsed["strategy"] == "Test Strategy A"
        assert parsed["symbol"] == "GBPUSD"
        assert parsed["outcome"] == "open"
        # Outcome fields are None on the open line
        assert parsed["pips_realized"] is None
        assert parsed["time_to_close_seconds"] is None
        assert parsed["closed_at"] is None

    def test_record_outcome_updates_existing_signal(self, tmp_path):
        """record_outcome() appends a second line with the same signal_id
        and populates the outcome fields. Both lines remain in the log."""
        log = tmp_path / "signal_stats.jsonl"
        recorder = SignalStatsRecorder(log_path=str(log))

        recorder.record_signal(_make_signal(signal_id="s-100", strategy="Breakout NY"))
        recorder.record_outcome(
            signal_id="s-100",
            outcome="tp_hit",
            pips=50.0,
            time_to_close=120,
        )

        with open(log, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]

        assert len(lines) == 2, "expected one open + one close line"

        open_row = json.loads(lines[0])
        close_row = json.loads(lines[1])

        # Both rows share the signal_id (correlation key)
        assert open_row["signal_id"] == "s-100"
        assert close_row["signal_id"] == "s-100"

        # Open line is unchanged
        assert open_row["outcome"] == "open"
        assert open_row["pips_realized"] is None
        assert open_row["strategy"] == "Breakout NY"

        # Close line carries the outcome
        assert close_row["outcome"] == "tp_hit"
        assert close_row["pips_realized"] == pytest.approx(50.0)
        assert close_row["time_to_close_seconds"] == 120
        assert close_row["closed_at"] is not None
        # Original signal metadata is preserved on the close line
        assert close_row["strategy"] == "Breakout NY"
        assert close_row["symbol"] == "GBPUSD"

    def test_get_stats_aggregates_correctly(self, tmp_path):
        """3 signals, 2 closed as tp_hit, 1 closed as sl_hit -> hit_rate 0.667."""
        log = tmp_path / "signal_stats.jsonl"
        recorder = SignalStatsRecorder(log_path=str(log))

        recorder.record_signal(_make_signal(signal_id="s-A", strategy="S1"))
        recorder.record_signal(_make_signal(signal_id="s-B", strategy="S1"))
        recorder.record_signal(_make_signal(signal_id="s-C", strategy="S1"))

        recorder.record_outcome("s-A", "tp_hit", pips=30.0, time_to_close=60)
        recorder.record_outcome("s-B", "tp_hit", pips=20.0, time_to_close=90)
        recorder.record_outcome("s-C", "sl_hit", pips=-15.0, time_to_close=45)

        stats = recorder.get_stats()
        assert stats["total_signals"] == 3
        assert stats["closed_signals"] == 3
        assert stats["open_signals"] == 0
        assert stats["wins"] == 2
        assert stats["losses"] == 1
        # 2/3 = 0.6666...; allow ~1e-6 tolerance for float math
        assert stats["hit_rate"] == pytest.approx(2 / 3, rel=1e-3)

        # avg_pips = (30 + 20 + -15) / 3 = 11.666...
        assert stats["avg_pips"] == pytest.approx(35.0 / 3, rel=1e-3)

        # avg_time_to_close = (60 + 90 + 45) / 3 = 65
        assert stats["avg_time_to_close_seconds"] == pytest.approx(65.0, rel=1e-3)

    def test_thread_safety(self, tmp_path):
        """10 threads x 100 signals = 1000 lines, no corruption."""
        log = tmp_path / "signal_stats.jsonl"
        recorder = SignalStatsRecorder(log_path=str(log))

        n_threads = 10
        n_per_thread = 100
        barrier = threading.Barrier(n_threads)
        errors: list[BaseException] = []

        def worker(thread_idx: int) -> None:
            try:
                # All threads wait at the barrier so the contention is
                # real — they all hit the lock at once.
                barrier.wait(timeout=5.0)
                for j in range(n_per_thread):
                    sid = f"t{thread_idx:02d}-{j:04d}"
                    recorder.record_signal(
                        _make_signal(
                            signal_id=sid,
                            strategy=f"Thread-{thread_idx}",
                            symbol="EURUSD",
                        )
                    )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,), name=f"writer-{i}") for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)
            assert not t.is_alive(), "writer thread hung"

        assert not errors, f"writer threads raised: {errors!r}"

        # Every line must be valid JSON with the expected shape.
        with open(log, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]

        assert len(lines) == n_threads * n_per_thread, f"expected {n_threads * n_per_thread} lines, got {len(lines)}"

        seen_ids: set[str] = set()
        for line in lines:
            row = json.loads(line)  # raises JSONDecodeError on a torn line
            assert row["signal_id"] not in seen_ids, f"duplicate signal_id {row['signal_id']!r} indicates a write race"
            seen_ids.add(row["signal_id"])
            assert row["symbol"] == "EURUSD"
            assert row["outcome"] == "open"

    def test_filter_by_strategy_and_symbol(self, tmp_path):
        """Recording 2 GBPUSD + 3 USDJPY signals; per-symbol counts match."""
        log = tmp_path / "signal_stats.jsonl"
        recorder = SignalStatsRecorder(log_path=str(log))

        # 2 GBPUSD
        recorder.record_signal(_make_signal(signal_id="g-1", symbol="GBPUSD", strategy="S1"))
        recorder.record_signal(_make_signal(signal_id="g-2", symbol="GBPUSD", strategy="S1"))
        # 3 USDJPY (two different strategies)
        recorder.record_signal(_make_signal(signal_id="u-1", symbol="USDJPY", strategy="S1"))
        recorder.record_signal(_make_signal(signal_id="u-2", symbol="USDJPY", strategy="S2"))
        recorder.record_signal(_make_signal(signal_id="u-3", symbol="USDJPY", strategy="S2"))

        # No filter — total should be 5
        all_stats = recorder.get_stats()
        assert all_stats["total_signals"] == 5
        assert all_stats["by_symbol"]["GBPUSD"] == 2
        assert all_stats["by_symbol"]["USDJPY"] == 3
        assert all_stats["by_strategy"]["S1"] == 3  # 2 GBPUSD + 1 USDJPY
        assert all_stats["by_strategy"]["S2"] == 2

        # Filter by symbol
        gbpusd_stats = recorder.get_stats(symbol="GBPUSD")
        assert gbpusd_stats["total_signals"] == 2
        assert set(gbpusd_stats["by_symbol"].keys()) == {"GBPUSD"}

        usdjpy_stats = recorder.get_stats(symbol="USDJPY")
        assert usdjpy_stats["total_signals"] == 3
        assert set(usdjpy_stats["by_symbol"].keys()) == {"USDJPY"}

        # Filter by strategy
        s1_stats = recorder.get_stats(strategy="S1")
        assert s1_stats["total_signals"] == 3
        assert s1_stats["by_strategy"] == {"S1": 3}

        s2_stats = recorder.get_stats(strategy="S2")
        assert s2_stats["total_signals"] == 2
        assert s2_stats["by_strategy"] == {"S2": 2}

        # Combined filter: USDJPY + S2 -> 2 signals
        combo = recorder.get_stats(strategy="S2", symbol="USDJPY")
        assert combo["total_signals"] == 2
