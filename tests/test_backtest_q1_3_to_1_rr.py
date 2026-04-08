"""Tests for BACKTEST Q1 3:1 R&R on EURUSD H1 M/W Formation"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.data_loader import CsvDataLoader  # noqa: E402
from backtest.engine import Bar  # noqa: E402


class TestSwingPointDetection:
    """Tests for swing point detection."""

    def test_detects_swing_highs_and_lows(self):
        """Should detect swing highs and swing lows in a simple pattern."""
        from scripts.backtest_q1_3_to_1_rr import detect_swing_points

        bars = [
            Bar(time=datetime(2024, 1, 1, 10, 0), open=1.10, high=1.10, low=1.10, close=1.10),
            Bar(time=datetime(2024, 1, 1, 11, 0), open=1.08, high=1.08, low=1.08, close=1.08),
            Bar(time=datetime(2024, 1, 1, 12, 0), open=1.12, high=1.12, low=1.12, close=1.12),
            Bar(time=datetime(2024, 1, 1, 13, 0), open=1.07, high=1.07, low=1.07, close=1.07),
            Bar(time=datetime(2024, 1, 1, 14, 0), open=1.11, high=1.11, low=1.11, close=1.11),
            Bar(time=datetime(2024, 1, 1, 15, 0), open=1.09, high=1.09, low=1.09, close=1.09),
            Bar(time=datetime(2024, 1, 1, 16, 0), open=1.13, high=1.13, low=1.13, close=1.13),
            Bar(time=datetime(2024, 1, 1, 17, 0), open=1.06, high=1.06, low=1.06, close=1.06),
            Bar(time=datetime(2024, 1, 1, 18, 0), open=1.12, high=1.12, low=1.12, close=1.12),
            Bar(time=datetime(2024, 1, 1, 19, 0), open=1.08, high=1.08, low=1.08, close=1.08),
        ]

        points = detect_swing_points(bars, lookback=2)
        assert len(points) >= 4


class TestMWFormationDetection:
    """Tests for M/W formation detection."""

    def test_formation_detection_runs(self):
        """Should run without errors on sample data."""
        from scripts.backtest_q1_3_to_1_rr import detect_swing_points, find_mw_formations

        bars = [
            Bar(time=datetime(2024, 1, 1, 10, 0), open=1.10, high=1.10, low=1.10, close=1.10),
            Bar(time=datetime(2024, 1, 1, 11, 0), open=1.08, high=1.08, low=1.08, close=1.08),
            Bar(time=datetime(2024, 1, 1, 12, 0), open=1.10, high=1.10, low=1.10, close=1.10),
            Bar(time=datetime(2024, 1, 1, 13, 0), open=1.07, high=1.07, low=1.07, close=1.07),
            Bar(time=datetime(2024, 1, 1, 14, 0), open=1.09, high=1.09, low=1.09, close=1.09),
            Bar(time=datetime(2024, 1, 1, 15, 0), open=1.11, high=1.11, low=1.11, close=1.11),
            Bar(time=datetime(2024, 1, 1, 16, 0), open=1.08, high=1.08, low=1.08, close=1.08),
            Bar(time=datetime(2024, 1, 1, 17, 0), open=1.10, high=1.10, low=1.10, close=1.10),
        ]

        swing_points = detect_swing_points(bars, lookback=2)
        formations = find_mw_formations(bars, swing_points, min_swing_pct=0.005)
        assert isinstance(formations, list)


class TestATRCalculation:
    """Tests for ATR calculation."""

    def test_calculates_atr(self):
        """ATR should be calculated correctly from bars."""
        from scripts.backtest_q1_3_to_1_rr import calculate_atr

        bars = [
            Bar(time=datetime(2024, 1, 1, 10, i), open=1.10, high=1.11, low=1.09, close=1.10)
            for i in range(16)
        ]

        atr = calculate_atr(bars)
        assert atr > 0


class TestQ1Results:
    """Integration test for Q1 analysis."""

    def test_results_format(self):
        """Results JSON should match required format."""
        data_dir = Path(project_root / "data/forex/historical")
        eurusd_file = data_dir / "EURUSD_H1.csv"

        if not eurusd_file.exists():
            pytest.skip("EURUSD H1 data not available")

        loader = CsvDataLoader()
        bars = loader.load(str(eurusd_file))

        if len(bars) < 1000:
            pytest.skip("Insufficient data for analysis")

        from scripts.backtest_q1_3_to_1_rr import analyze_3_to_1_rr

        results = analyze_3_to_1_rr(bars)

        assert results["question"] == "Q1"
        assert "test_period" in results
        assert results["instrument"] == "EURUSD"
        assert results["timeframe"] == "H1"
        assert results["sample_size"] > 0
        assert "rr_3_1_hit_rate" in results["results"]
        assert "average_rr" in results["results"]
        assert "l1_hit_rate" in results["results"]
        assert "l2_hit_rate" in results["results"]
        assert "l3_hit_rate" in results["results"]
        assert "stop_loss_rate" in results["results"]
        assert "pass" in results
        assert "notes" in results


if __name__ == "__main__":
    pytest.main([__file__, "-v"])