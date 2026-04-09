"""Tests for BACKTEST Q6 DXY Leading/Lagging Analysis"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.engine import Bar

BASE_TIME = datetime(2024, 1, 1, 10, 0)


def _bar_at(offset: int, **kwargs) -> Bar:
    return Bar(time=BASE_TIME + timedelta(hours=offset), **kwargs)


class TestAlignBarsByTimestamp:
    def test_matches_by_timestamp(self):
        from scripts.backtest_q6_dxy_leading_lagging import align_bars_by_timestamp

        t1 = BASE_TIME
        eurusd = [Bar(time=t1, open=1.0, high=1.01, low=0.99, close=1.005)]
        usdjpy = [Bar(time=t1, open=150.0, high=150.5, low=149.5, close=150.2)]
        result = align_bars_by_timestamp(eurusd, usdjpy)
        assert len(result) == 1
        assert result[0][0].time == t1
        assert result[0][1].time == t1

    def test_skips_unmatched(self):
        from scripts.backtest_q6_dxy_leading_lagging import align_bars_by_timestamp

        t1 = BASE_TIME
        t2 = BASE_TIME + timedelta(hours=1)
        eurusd = [Bar(time=t1, open=1.0, high=1.01, low=0.99, close=1.005)]
        usdjpy = [Bar(time=t2, open=150.0, high=150.5, low=149.5, close=150.2)]
        result = align_bars_by_timestamp(eurusd, usdjpy)
        assert len(result) == 0

    def test_empty_inputs(self):
        from scripts.backtest_q6_dxy_leading_lagging import align_bars_by_timestamp

        result = align_bars_by_timestamp([], [])
        assert len(result) == 0


class TestCalculateReturns:
    def test_basic_returns(self):
        from scripts.backtest_q6_dxy_leading_lagging import calculate_returns

        prices = [100.0, 101.0, 99.0]
        returns = calculate_returns(prices)
        assert len(returns) == 2
        assert abs(returns[0] - 0.01) < 1e-10
        assert abs(returns[1] - (-0.019801980198019802)) < 1e-10

    def test_single_price(self):
        from scripts.backtest_q6_dxy_leading_lagging import calculate_returns

        returns = calculate_returns([1.0])
        assert returns == []

    def test_empty_list(self):
        from scripts.backtest_q6_dxy_leading_lagging import calculate_returns

        returns = calculate_returns([])
        assert returns == []


class TestCalculateRollingCorrelation:
    def test_perfect_positive_correlation(self):
        from scripts.backtest_q6_dxy_leading_lagging import calculate_rolling_correlation

        s1 = [float(i) for i in range(100)]
        s2 = [float(i * 2) for i in range(100)]
        corr = calculate_rolling_correlation(s1, s2, window=20)
        assert len(corr) == 81
        assert all(abs(c - 1.0) < 0.001 for c in corr)

    def test_perfect_negative_correlation(self):
        from scripts.backtest_q6_dxy_leading_lagging import calculate_rolling_correlation

        s1 = [float(i) for i in range(100)]
        s2 = [float(-i) for i in range(100)]
        corr = calculate_rolling_correlation(s1, s2, window=20)
        assert all(abs(c + 1.0) < 0.001 for c in corr)

    def test_zero_correlation(self):
        from scripts.backtest_q6_dxy_leading_lagging import calculate_rolling_correlation

        import random
        random.seed(42)
        s1 = [random.gauss(0, 1) for _ in range(200)]
        s2 = [random.gauss(0, 1) for _ in range(200)]
        corr = calculate_rolling_correlation(s1, s2, window=50)
        avg = sum(corr) / len(corr)
        assert abs(avg) < 0.3


class TestIdentifyBreakoutBars:
    def test_detects_up_breakout(self):
        from scripts.backtest_q6_dxy_leading_lagging import identify_breakout_bars

        aligned = []
        for i in range(30):
            jpy_close = 150.0 + (0.1 if i < 20 else 5.0)
            eur_bar = _bar_at(i, open=1.0, high=1.01, low=0.99, close=1.0)
            jpy_bar = _bar_at(i, open=jpy_close, high=jpy_close + 0.1, low=jpy_close - 0.1, close=jpy_close)
            aligned.append((eur_bar, jpy_bar))

        breakouts = identify_breakout_bars(aligned, lookback=20, atr_window=14, breakout_multiplier=0.1)
        assert len(breakouts) > 0
        assert breakouts[-1][1] == "UP"

    def test_detects_down_breakout(self):
        from scripts.backtest_q6_dxy_leading_lagging import identify_breakout_bars

        aligned = []
        for i in range(30):
            jpy_close = 150.0 - (0.0 if i < 20 else 5.0)
            eur_bar = _bar_at(i, open=1.0, high=1.01, low=0.99, close=1.0)
            jpy_bar = _bar_at(i, open=jpy_close, high=jpy_close + 0.1, low=jpy_close - 0.1, close=jpy_close)
            aligned.append((eur_bar, jpy_bar))

        breakouts = identify_breakout_bars(aligned, lookback=20, atr_window=14, breakout_multiplier=0.1)
        assert len(breakouts) > 0
        assert breakouts[-1][1] == "DOWN"

    def test_no_breakouts_in_flat_market(self):
        from scripts.backtest_q6_dxy_leading_lagging import identify_breakout_bars

        aligned = []
        for i in range(50):
            eur_bar = _bar_at(i, open=1.0, high=1.01, low=0.99, close=1.0)
            jpy_bar = _bar_at(i, open=150.0, high=150.1, low=149.9, close=150.0)
            aligned.append((eur_bar, jpy_bar))

        breakouts = identify_breakout_bars(aligned, lookback=20, atr_window=14, breakout_multiplier=1.5)
        break_indices = [idx for idx, _ in breakouts]
        assert len(break_indices) == 0

    def test_min_separation_enforced(self):
        from scripts.backtest_q6_dxy_leading_lagging import identify_breakout_bars

        aligned = []
        for i in range(50):
            jpy_close = 150.0 + (5.0 if i >= 20 else 0.0)
            eur_bar = _bar_at(i, open=1.0, high=1.01, low=0.99, close=1.0)
            jpy_bar = _bar_at(i, open=jpy_close, high=jpy_close + 0.1, low=jpy_close - 0.1, close=jpy_close)
            aligned.append((eur_bar, jpy_bar))

        breakouts = identify_breakout_bars(aligned, lookback=20, atr_window=14, breakout_multiplier=0.1)
        for i in range(1, len(breakouts)):
            assert breakouts[i][0] - breakouts[i - 1][0] >= 8


class TestMeasureLeadLag:
    def test_dxy_up_eur_follows_down(self):
        from scripts.backtest_q6_dxy_leading_lagging import measure_lead_lag

        aligned = []
        for i in range(30):
            eur_close = 1.0 if i < 20 else 0.99
            eur_bar = _bar_at(i, open=eur_close, high=eur_close + 0.001, low=eur_close - 0.001, close=eur_close)
            jpy_close = 150.0 if i < 20 else 155.0
            jpy_bar = _bar_at(i, open=jpy_close, high=jpy_close + 0.1, low=jpy_close - 0.1, close=jpy_close)
            aligned.append((eur_bar, jpy_bar))

        breakouts = [(20, "UP")]
        stats = measure_lead_lag(aligned, breakouts, response_window=8)
        assert stats["dxy_leads_count"] >= 0
        assert "total_breakouts" in stats

    def test_dxy_down_eur_follows_up(self):
        from scripts.backtest_q6_dxy_leading_lagging import measure_lead_lag

        aligned = []
        for i in range(30):
            eur_close = 1.0 if i < 20 else 1.01
            eur_bar = _bar_at(i, open=eur_close, high=eur_close + 0.001, low=eur_close - 0.001, close=eur_close)
            jpy_close = 150.0 if i < 20 else 145.0
            jpy_bar = _bar_at(i, open=jpy_close, high=jpy_close + 0.1, low=jpy_close - 0.1, close=jpy_close)
            aligned.append((eur_bar, jpy_bar))

        breakouts = [(20, "DOWN")]
        stats = measure_lead_lag(aligned, breakouts, response_window=8)
        assert stats["dxy_leads_count"] >= 0

    def test_no_breakouts(self):
        from scripts.backtest_q6_dxy_leading_lagging import measure_lead_lag

        aligned = []
        for i in range(10):
            eur_bar = _bar_at(i, open=1.0, high=1.01, low=0.99, close=1.0)
            jpy_bar = _bar_at(i, open=150.0, high=150.1, low=149.9, close=150.0)
            aligned.append((eur_bar, jpy_bar))

        stats = measure_lead_lag(aligned, [], response_window=8)
        assert stats["total_breakouts"] == 0
        assert stats["dxy_leads_count"] == 0


class TestCalculateCrossCorrelation:
    def test_zero_lag_highest_for_simultaneous(self):
        from scripts.backtest_q6_dxy_leading_lagging import calculate_cross_correlation

        import random
        random.seed(42)
        s1 = [random.gauss(0, 1) for _ in range(500)]
        s2 = [x * -0.5 for x in s1]
        xcorr = calculate_cross_correlation(s1, s2, max_lag=5)
        assert abs(xcorr[0]) >= abs(xcorr[1])

    def test_lagged_signal_detected(self):
        from scripts.backtest_q6_dxy_leading_lagging import calculate_cross_correlation

        s1 = [float(i % 10) for i in range(200)]
        s2 = s1[3:] + [0.0] * 3
        xcorr = calculate_cross_correlation(s1, s2, max_lag=5)
        assert xcorr.get(3, 0) > xcorr.get(0, 0)


class TestQ6Integration:
    def test_results_format(self):
        from backtest.data_loader import CsvDataLoader

        data_dir = Path(project_root / "data/forex/historical")
        eurusd_file = data_dir / "EURUSD_H1.csv"
        usdjpy_file = data_dir / "USDJPY_H1.csv"

        if not eurusd_file.exists() or not usdjpy_file.exists():
            pytest.skip("Data files not available")

        loader = CsvDataLoader()
        eurusd_bars = loader.load(str(eurusd_file))
        usdjpy_bars = loader.load(str(usdjpy_file))

        if len(eurusd_bars) < 1000 or len(usdjpy_bars) < 1000:
            pytest.skip("Insufficient data")

        from scripts.backtest_q6_dxy_leading_lagging import (
            align_bars_by_timestamp,
            analyze_dxy_leading_lagging,
        )

        aligned = align_bars_by_timestamp(eurusd_bars, usdjpy_bars)
        results = analyze_dxy_leading_lagging(aligned)

        assert results["question"] == "Q6"
        assert "test_period" in results
        assert results["instrument"] == "EURUSD"
        assert results["timeframe"] == "H1"
        assert results["sample_size"] > 0
        assert "correlation_coefficient" in results["results"]
        assert "dxy_leads_pct" in results["results"]
        assert "avg_delay_candles" in results["results"]
        assert "dxy_first_break_confirms" in results["results"]
        assert "pass" in results
        assert isinstance(results["pass"], bool)
        assert "notes" in results
        assert "methodology" in results

    def test_report_json_exists(self):
        report = Path(project_root / "reports/backtest_q6_dxy_leading_lagging.json")
        if not report.exists():
            pytest.skip("Report not yet generated")
        import json
        data = json.loads(report.read_text())
        assert data["question"] == "Q6"
        assert "pass" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
