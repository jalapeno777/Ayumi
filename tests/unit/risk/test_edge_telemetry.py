"""Tests for edge telemetry — R-multiple expectancy tracking."""

import json
from pathlib import Path

import pytest
from risk.edge_telemetry import EdgeTelemetryTracker


@pytest.fixture
def tracker(tmp_path):
    """Fresh tracker with temp persistence path."""
    return EdgeTelemetryTracker(persist_path=str(tmp_path / "edge_telemetry.jsonl"))


class TestRecordClose:
    """Tests for recording closed trades."""

    def test_record_close_creates_stats(self, tracker):
        """Recording a close should create edge stats for the pair."""
        tracker.record_close("srmr_xauusd", "XAUUSD", risk_amount=50.0, pnl=35.0)
        stats = tracker.get_stats("srmr_xauusd", "XAUUSD")
        assert stats is not None
        assert stats.total_trades == 1
        assert stats.wins == 1
        assert stats.losses == 0

    def test_r_multiple_calculation(self, tracker):
        """R-multiple should be pnl / risk_amount."""
        tracker.record_close("srmr_xauusd", "XAUUSD", risk_amount=50.0, pnl=100.0)
        stats = tracker.get_stats("srmr_xauusd", "XAUUSD")
        assert stats.best_r == 2.0  # 100/50 = 2R

    def test_loss_recorded_correctly(self, tracker):
        """A losing trade should increment losses and have negative R."""
        tracker.record_close("srmr_xauusd", "XAUUSD", risk_amount=50.0, pnl=-25.0)
        stats = tracker.get_stats("srmr_xauusd", "XAUUSD")
        assert stats.losses == 1
        assert stats.worst_r == -0.5  # -25/50 = -0.5R

    def test_persistence_to_jsonl(self, tracker, tmp_path):
        """Recorded trades should persist to JSONL."""
        tracker.record_close("strat", "SYM", risk_amount=100.0, pnl=50.0, signal_id="sig_001")
        persist_path = Path(tracker._persist_path)
        assert persist_path.exists()
        with open(persist_path) as f:
            line = f.readline()
            rec = json.loads(line)
            assert rec["strategy_id"] == "strat"
            assert rec["symbol"] == "SYM"
            assert rec["r_multiple"] == 0.5
            assert rec["signal_id"] == "sig_001"


class TestExpectancy:
    """Tests for expectancy calculation."""

    def test_empty_expectancy_is_zero(self, tracker):
        """Expectancy with no trades should be 0."""
        assert tracker.get_expectancy("none", "NONE") == 0.0

    def test_mixed_win_loss_expectancy(self, tracker):
        """Expectancy should be the mean of R-multiples."""
        # Win: +1R, Loss: -0.5R, Win: +2R → avg = (1 - 0.5 + 2) / 3 = 0.833
        tracker.record_close("strat", "SYM", risk_amount=100.0, pnl=100.0)  # +1R
        tracker.record_close("strat", "SYM", risk_amount=100.0, pnl=-50.0)  # -0.5R
        tracker.record_close("strat", "SYM", risk_amount=100.0, pnl=200.0)  # +2R
        exp = tracker.get_expectancy("strat", "SYM")
        assert abs(exp - (1.0 - 0.5 + 2.0) / 3.0) < 1e-6

    def test_rolling_window_caps_at_50(self, tracker):
        """Rolling window should cap at 50 trades."""
        for i in range(60):
            tracker.record_close("strat", "SYM", risk_amount=10.0, pnl=float(i % 3))
        stats = tracker.get_stats("strat", "SYM")
        assert len(stats.trades) == 50  # Rolling window cap
        assert stats.total_trades == 60  # But total count preserved


class TestRiskMultiplier:
    """Tests for the risk sizing multiplier."""

    def test_insufficient_data_returns_1(self, tracker):
        """Less than 5 trades should return 1.0 (standard size)."""
        for _ in range(4):
            tracker.record_close("strat", "SYM", risk_amount=50.0, pnl=100.0)
        assert tracker.get_risk_multiplier("strat", "SYM") == 1.0

    def test_high_edge_returns_1_5(self, tracker):
        """Expectancy > 0.5R should return 1.5 multiplier."""
        for _ in range(5):
            tracker.record_close("strat", "SYM", risk_amount=100.0, pnl=100.0)  # +1R each
        assert tracker.get_risk_multiplier("strat", "SYM") == 1.5

    def test_negative_edge_returns_0_6(self, tracker):
        """Negative expectancy should return 0.6 multiplier."""
        for _ in range(5):
            tracker.record_close("strat", "SYM", risk_amount=100.0, pnl=-50.0)  # -0.5R each
        assert tracker.get_risk_multiplier("strat", "SYM") == 0.6

    def test_positive_edge_returns_1_0(self, tracker):
        """Expectancy between 0 and 0.5 should return 1.0."""
        # 3 wins (+0.3R each) + 2 losses (-0.2R each) → avg = (0.9 - 0.4) / 5 = 0.1R
        for _ in range(3):
            tracker.record_close("strat", "SYM", risk_amount=100.0, pnl=30.0)
        for _ in range(2):
            tracker.record_close("strat", "SYM", risk_amount=100.0, pnl=-20.0)
        assert tracker.get_risk_multiplier("strat", "SYM") == 1.0


class TestLoadHistory:
    """Tests for loading historical data on init."""

    def test_loads_existing_jsonl(self, tmp_path):
        """Tracker should load existing JSONL on init."""
        persist = tmp_path / "edge.jsonl"
        with open(persist, "w") as f:
            f.write(
                json.dumps(
                    {
                        "strategy_id": "strat",
                        "symbol": "SYM",
                        "risk_amount": 50.0,
                        "pnl": 100.0,
                        "r_multiple": 2.0,
                        "timestamp": "2026-07-08T12:00:00+00:00",
                        "signal_id": "sig_001",
                    }
                )
                + "\n"
            )

        tracker = EdgeTelemetryTracker(persist_path=str(persist))
        stats = tracker.get_stats("strat", "SYM")
        assert stats is not None
        assert stats.total_trades == 1
        assert stats.best_r == 2.0

    def test_handles_corrupt_jsonl(self, tmp_path):
        """Corrupt JSONL lines should be skipped, not crash."""
        persist = tmp_path / "edge.jsonl"
        with open(persist, "w") as f:
            f.write(
                '{"valid": "json", "strategy_id": "s", "symbol": "X", "risk_amount": 10, "pnl": 5, "r_multiple": 0.5, "timestamp": "2026-01-01T00:00:00Z"}\n'  # noqa: E501
            )
            f.write('{"invalid json\n')
            f.write("not json at all\n")

        tracker = EdgeTelemetryTracker(persist_path=str(persist))
        # Should have loaded 1 valid record
        stats = tracker.get_stats("s", "X")
        assert stats is not None
        assert stats.total_trades == 1


class TestWriteStateSnapshot:
    """Tests for canonical-state snapshot writer (card d8c2a10b).

    The snapshot writer is what closes the 47h+ drift between the
    trade-by-trade JSONL (only updates on record_close) and the
    operational path (5-min equity/health cadence). It rewrites a
    JSON file atomically so external readers always see fresh state.
    """

    def test_snapshot_writes_atomic_file(self, tracker, tmp_path):
        """Snapshot should atomically rewrite the JSON file."""
        snap_path = tmp_path / "edge_telemetry_state.json"

        tracker.record_close("srmr_xauusd", "XAUUSD", risk_amount=50.0, pnl=35.0)
        tracker.record_close("srmr_xauusd", "XAUUSD", risk_amount=50.0, pnl=-25.0)
        tracker.record_close("srmr_plus", "XAUUSD", risk_amount=25.0, pnl=10.0)

        result = tracker.write_state_snapshot(snapshot_path=str(snap_path))

        # File exists and is valid JSON
        assert snap_path.exists()
        with open(snap_path) as f:
            on_disk = json.load(f)
        assert on_disk["kind"] == "edge_telemetry_state_snapshot"
        assert on_disk["schema_version"] == 1
        assert on_disk["total_strategy_symbol_pairs"] == 2
        assert on_disk["total_trades"] == 3

        # Returned dict matches what was written
        assert result == on_disk

        # Stats contain rolling metrics for each pair
        strategy_ids = {s["strategy_id"] for s in on_disk["stats"]}
        assert strategy_ids == {"srmr_xauusd", "srmr_plus"}

    def test_snapshot_excludes_empty_pairs(self, tracker, tmp_path):
        """Snapshot should not include pairs with zero trades."""
        snap_path = tmp_path / "state.json"

        tracker.record_close("strat_a", "SYM_A", risk_amount=10.0, pnl=5.0)
        # strat_b has no trades

        result = tracker.write_state_snapshot(snapshot_path=str(snap_path))

        assert result["total_strategy_symbol_pairs"] == 1
        assert result["total_trades"] == 1
        assert len(result["stats"]) == 1

    def test_snapshot_default_path(self, tracker, monkeypatch, tmp_path):
        """Default snapshot path should be data/edge_telemetry_state.json."""
        # Run from tmp_path so default data/ path is local
        monkeypatch.chdir(tmp_path)
        result = tracker.write_state_snapshot()
        assert Path(tmp_path / "data" / "edge_telemetry_state.json").exists()
        assert result["kind"] == "edge_telemetry_state_snapshot"

    def test_snapshot_overwrites_existing(self, tracker, tmp_path):
        """Re-writing should atomically replace (no stale content)."""
        snap_path = tmp_path / "state.json"

        tracker.record_close("strat_a", "SYM_A", risk_amount=10.0, pnl=5.0)
        tracker.write_state_snapshot(snapshot_path=str(snap_path))
        first_ts = json.loads(snap_path.read_text())["timestamp"]

        # Wait a moment then re-record + re-snapshot
        import time
        time.sleep(0.01)
        tracker.record_close("strat_b", "SYM_B", risk_amount=10.0, pnl=7.0)
        result = tracker.write_state_snapshot(snapshot_path=str(snap_path))
        second_ts = result["timestamp"]

        assert first_ts != second_ts
        assert result["total_trades"] == 2

    def test_snapshot_has_iso_timestamp(self, tracker, tmp_path):
        """Timestamp should be ISO-8601 UTC for downstream parsers."""
        snap_path = tmp_path / "state.json"
        result = tracker.write_state_snapshot(snapshot_path=str(snap_path))
        ts = result["timestamp"]
        # ISO-8601 UTC: ends with +00:00, parses round-trip
        from datetime import datetime
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None

    def test_snapshot_handles_no_trades(self, tracker, tmp_path):
        """Snapshot with zero trades should write valid empty state."""
        snap_path = tmp_path / "state.json"
        result = tracker.write_state_snapshot(snapshot_path=str(snap_path))

        assert snap_path.exists()
        assert result["total_strategy_symbol_pairs"] == 0
        assert result["total_trades"] == 0
        assert result["stats"] == []
