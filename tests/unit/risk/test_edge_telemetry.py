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
