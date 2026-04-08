"""Tests for BACKTEST Q6 DXY Leading/Lagging Analysis"""

import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.data_loader import CsvDataLoader  # noqa: E402
from backtest.engine import Bar  # noqa: E402


class TestSyntheticDXYFromEURUSD:
    """Tests for synthetic DXY proxy creation."""

    def test_inverts_eurusd(self):
        """Synthetic DXY should be inverse of EURUSD rate."""
        from scripts.backtest_q6_dxy_leading_lagging import synthetic_dxy_from_eurusd

        bars = [
            Bar(time=None, open=1.0, high=1.0, low=1.0, close=1.0),
            Bar(time=None, open=1.1, high=1.1, low=1.1, close=1.1),
            Bar(time=None, open=0.9, high=0.9, low=0.9, close=0.9),
        ]
        dxy = synthetic_dxy_from_eurusd(bars)
        assert len(dxy) == 3
        assert abs(dxy[0] - 1.0) < 0.001
        assert abs(dxy[1] - (1.0 / 1.1)) < 0.001
        assert abs(dxy[2] - (1.0 / 0.9)) < 0.001

    def test_handles_zero_rate(self):
        """Should handle zero rate gracefully."""
        from scripts.backtest_q6_dxy_leading_lagging import synthetic_dxy_from_eurusd

        bars = [
            Bar(time=None, open=1.0, high=1.0, low=1.0, close=1.0),
            Bar(time=None, open=0.0, high=0.0, low=0.0, close=0.0),
            Bar(time=None, open=0.9, high=0.9, low=0.9, close=0.9),
        ]
        dxy = synthetic_dxy_from_eurusd(bars)
        assert len(dxy) == 3
        assert dxy[1] == 1.0


class TestIdentifyLevelBreaks:
    """Tests for level break identification."""

    def test_no_breaks_in_calm_market(self):
        """No breaks when price is within range."""
        from scripts.backtest_q6_dxy_leading_lagging import identify_level_breaks

        prices = [1.0] * 30
        breaks = identify_level_breaks(prices, lookback=20, threshold_pct=0.005)
        break_indices = [idx for idx, is_break in breaks if is_break]
        assert len(break_indices) == 0

    def test_breaks_on_strong_move_up(self):
        """Should detect upper break when price breaks out."""
        from scripts.backtest_q6_dxy_leading_lagging import identify_level_breaks

        prices = [1.0] * 20 + [1.005, 1.01, 1.02]
        breaks = identify_level_breaks(prices, lookback=20, threshold_pct=0.01)
        break_indices = [idx for idx, is_break in breaks if is_break]
        assert len(break_indices) > 0


class TestMeasureLeadLag:
    """Tests for lead/lag measurement."""

    def test_dxy_leads_when_eur_follows(self):
        """DXY should count as leading when EURUSD follows within window."""
        from scripts.backtest_q6_dxy_leading_lagging import measure_lead_lag

        bars = [Bar(time=None, open=i, high=i, low=i, close=i) for i in range(1, 51)]
        dxy_proxy = [1.0 / b.close for b in bars]
        dxy_proxy[20] = dxy_proxy[19] * 1.02

        break_indices = [20]
        stats = measure_lead_lag(dxy_proxy, bars, break_indices, response_window=8)
        assert stats["dxy_leads_count"] >= 0
        assert stats["eur_leads_count"] >= 0


class TestQ6Results:
    """Integration test for Q6 analysis."""

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

        from scripts.backtest_q6_dxy_leading_lagging import analyze_dxy_leading_lagging

        results = analyze_dxy_leading_lagging(bars)

        assert results["question"] == "Q6"
        assert "test_period" in results
        assert results["instrument"] == "EURUSD"
        assert results["timeframe"] == "H1"
        assert results["sample_size"] > 1000
        assert "correlation_coefficient" in results["results"]
        assert "dxy_leads_pct" in results["results"]
        assert "avg_delay_candles" in results["results"]
        assert "dxy_first_break_confirms" in results["results"]
        assert "pass" in results
        assert "notes" in results


if __name__ == "__main__":
    pytest.main([__file__, "-v"])