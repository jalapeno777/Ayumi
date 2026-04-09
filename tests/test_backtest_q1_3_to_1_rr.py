"""Tests for BACKTEST Q1 3:1 R&R on EURUSD H1 M/W Formation"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.engine import Bar  # noqa: E402

from scripts.backtest_q1_3_to_1_rr import (
    SwingPoint,
    SessionType,
    calculate_atr,
    compute_outcome_stats,
    detect_swing_points,
    evaluate_trade_outcome,
    find_mw_formations,
)


def _bar(hour: int, minute: int, high: float, low: float, close: float, **kw) -> Bar:
    return Bar(
        time=datetime(2024, 1, 1, hour, minute),
        open=kw.get("open", close),
        high=high,
        low=low,
        close=close,
    )


class TestSwingPointDetection:
    def test_detects_swing_highs_and_lows(self):
        prices = [
            (1.1005, 1.0995, 1.1000),
            (1.0805, 1.0795, 1.0800),
            (1.1205, 1.1195, 1.1200),
            (1.0705, 1.0695, 1.0700),
            (1.1105, 1.1095, 1.1100),
            (1.0905, 1.0895, 1.0900),
            (1.1305, 1.1295, 1.1300),
            (1.0605, 1.0595, 1.0600),
            (1.1205, 1.1195, 1.1200),
            (1.0805, 1.0795, 1.0800),
        ]
        bars = [_bar(10 + i, 0, hi, lo, cl) for i, (hi, lo, cl) in enumerate(prices)]

        points = detect_swing_points(bars, lookback=2)
        assert len(points) >= 4

    def test_empty_bars(self):
        assert detect_swing_points([], lookback=2) == []

    def test_too_few_bars(self):
        bars = [_bar(10 + i, 0, 1.10, 1.09, 1.095) for i in range(4)]
        assert detect_swing_points(bars, lookback=2) == []


class TestMWFormationDetection:
    def test_formation_detection_runs(self):
        prices = [
            (1.1005, 1.0995, 1.1000),
            (1.0805, 1.0795, 1.0800),
            (1.1005, 1.0995, 1.1000),
            (1.0705, 1.0695, 1.0700),
            (1.0905, 1.0895, 1.0900),
            (1.1105, 1.1095, 1.1100),
            (1.0805, 1.0795, 1.0800),
            (1.1005, 1.0995, 1.1000),
        ]
        bars = [_bar(10 + i, 0, hi, lo, cl) for i, (hi, lo, cl) in enumerate(prices)]

        swing_points = detect_swing_points(bars, lookback=2)
        formations = find_mw_formations(bars, swing_points, min_swing_pct=0.005)
        assert isinstance(formations, list)

    def test_empty_swing_points(self):
        assert find_mw_formations([], [], min_swing_pct=0.003) == []

    def test_fewer_than_5_swing_points(self):
        pts = [SwingPoint(0, 1.10, True, datetime(2024, 1, 1), SessionType.LONDON)]
        assert find_mw_formations([], pts, min_swing_pct=0.003) == []


class TestATRCalculation:
    def test_calculates_atr(self):
        bars = [_bar(10, i, 1.11, 1.09, 1.10) for i in range(16)]
        atr = calculate_atr(bars)
        assert atr > 0

    def test_insufficient_bars_returns_small_default(self):
        bars = [_bar(10, i, 1.10, 1.10, 1.10) for i in range(5)]
        atr = calculate_atr(bars)
        assert atr == 0.0001


class TestEvaluateTradeOutcome:
    def test_long_tp3_priority(self):
        bars = [_bar(12, i, 1.10, 1.10, 1.10) for i in range(5)]
        result = evaluate_trade_outcome(
            bars,
            entry_idx=0,
            entry_direction=1,
            stop=1.0950,
            tp1=1.1050,
            tp2=1.1100,
            tp3=1.1150,
        )
        assert result is None

        bars[0] = _bar(12, 0, 1.1200, 1.10, 1.1150)
        result = evaluate_trade_outcome(
            bars,
            entry_idx=0,
            entry_direction=1,
            stop=1.0950,
            tp1=1.1050,
            tp2=1.1100,
            tp3=1.1150,
        )
        assert result == "L3"

    def test_long_tp2_priority(self):
        bars = [_bar(12, i, 1.10, 1.10, 1.10) for i in range(5)]
        bars[0] = _bar(12, 0, 1.1120, 1.10, 1.1110)
        result = evaluate_trade_outcome(
            bars,
            entry_idx=0,
            entry_direction=1,
            stop=1.0950,
            tp1=1.1050,
            tp2=1.1100,
            tp3=1.1150,
        )
        assert result == "L2"

    def test_long_tp1_priority(self):
        bars = [_bar(12, i, 1.10, 1.10, 1.10) for i in range(5)]
        bars[0] = _bar(12, 0, 1.1070, 1.10, 1.1060)
        result = evaluate_trade_outcome(
            bars,
            entry_idx=0,
            entry_direction=1,
            stop=1.0950,
            tp1=1.1050,
            tp2=1.1100,
            tp3=1.1150,
        )
        assert result == "L1"

    def test_long_stop_hit(self):
        bars = [_bar(12, i, 1.10, 1.10, 1.10) for i in range(5)]
        bars[0] = _bar(12, 0, 1.10, 1.0940, 1.0945)
        result = evaluate_trade_outcome(
            bars,
            entry_idx=0,
            entry_direction=1,
            stop=1.0950,
            tp1=1.1050,
            tp2=1.1100,
            tp3=1.1150,
        )
        assert result == "SL"

    def test_short_tp3_priority(self):
        bars = [_bar(12, i, 1.10, 1.10, 1.10) for i in range(5)]
        bars[0] = _bar(12, 0, 1.10, 1.0800, 1.0850)
        result = evaluate_trade_outcome(
            bars,
            entry_idx=0,
            entry_direction=-1,
            stop=1.1050,
            tp1=1.0950,
            tp2=1.0900,
            tp3=1.0850,
        )
        assert result == "L3"

    def test_short_tp2_priority(self):
        bars = [_bar(12, i, 1.10, 1.10, 1.10) for i in range(5)]
        bars[0] = _bar(12, 0, 1.10, 1.0880, 1.0890)
        result = evaluate_trade_outcome(
            bars,
            entry_idx=0,
            entry_direction=-1,
            stop=1.1050,
            tp1=1.0950,
            tp2=1.0900,
            tp3=1.0850,
        )
        assert result == "L2"

    def test_short_tp1_priority(self):
        bars = [_bar(12, i, 1.10, 1.10, 1.10) for i in range(5)]
        bars[0] = _bar(12, 0, 1.10, 1.0930, 1.0940)
        result = evaluate_trade_outcome(
            bars,
            entry_idx=0,
            entry_direction=-1,
            stop=1.1050,
            tp1=1.0950,
            tp2=1.0900,
            tp3=1.0850,
        )
        assert result == "L1"

    def test_short_stop_hit(self):
        bars = [_bar(12, i, 1.10, 1.10, 1.10) for i in range(5)]
        bars[0] = _bar(12, 0, 1.1060, 1.10, 1.1055)
        result = evaluate_trade_outcome(
            bars,
            entry_idx=0,
            entry_direction=-1,
            stop=1.1050,
            tp1=1.0950,
            tp2=1.0900,
            tp3=1.0850,
        )
        assert result == "SL"

    def test_no_hit_returns_none(self):
        bars = [_bar(12, i, 1.10, 1.10, 1.10) for i in range(5)]
        result = evaluate_trade_outcome(
            bars,
            entry_idx=0,
            entry_direction=1,
            stop=1.0950,
            tp1=1.1050,
            tp2=1.1100,
            tp3=1.1150,
        )
        assert result is None

    def test_sl_before_tp1_in_long(self):
        bars = [_bar(12, i, 1.10, 1.10, 1.10) for i in range(3)]
        bars[0] = _bar(12, 0, 1.10, 1.0940, 1.0945)
        result = evaluate_trade_outcome(
            bars,
            entry_idx=0,
            entry_direction=1,
            stop=1.0950,
            tp1=1.1050,
            tp2=1.1100,
            tp3=1.1150,
        )
        assert result == "SL"


class TestComputeOutcomeStats:
    def test_open_trades_excluded_from_avg_rr(self):
        outcomes = {"L1": 2, "L2": 1, "L3": 0, "SL": 1, "open": 5}
        rr_ratios = [1.0, 1.0, 2.0, 0.0]
        stats = compute_outcome_stats(outcomes, rr_ratios)
        assert stats["average_rr"] == 1.33
        assert stats["stop_loss_rate"] == 0.25
        assert stats["rr_3_1_hit_rate"] == 0.0

    def test_all_stops(self):
        outcomes = {"L1": 0, "L2": 0, "L3": 0, "SL": 10, "open": 3}
        rr_ratios = [0.0] * 10
        stats = compute_outcome_stats(outcomes, rr_ratios)
        assert stats["average_rr"] == 0.0
        assert stats["stop_loss_rate"] == 1.0

    def test_all_tp3(self):
        outcomes = {"L1": 0, "L2": 0, "L3": 5, "SL": 0, "open": 0}
        rr_ratios = [3.0] * 5
        stats = compute_outcome_stats(outcomes, rr_ratios)
        assert stats["average_rr"] == 3.0
        assert stats["rr_3_1_hit_rate"] == 1.0
        assert stats["pass"] if "pass" in stats else True

    def test_empty_outcomes(self):
        outcomes = {"L1": 0, "L2": 0, "L3": 0, "SL": 0, "open": 0}
        stats = compute_outcome_stats(outcomes, [])
        assert stats["average_rr"] == 0.0
        assert stats["stop_loss_rate"] == 0.0


class TestQ1Results:
    def test_results_format(self):
        data_dir = project_root / "data" / "forex" / "historical"
        eurusd_file = data_dir / "EURUSD_H1.csv"

        if not eurusd_file.exists():
            pytest.skip("EURUSD H1 data not available")

        from backtest.data_loader import CsvDataLoader  # noqa: E402

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
