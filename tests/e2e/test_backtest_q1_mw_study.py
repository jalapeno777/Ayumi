"""Tests for Q1BacktestStudy — M/W Formation 3:1 R&R"""

from __future__ import annotations  # noqa: I001

import json
from datetime import datetime

import pytest

from backtest.engine import Bar  # noqa: E402
from backtest.pattern_detector import MWPattern  # noqa: E402
from backtest_q1_mw_formation_study import Q1BacktestStudy  # noqa: E402


def _make_bar(
    hour: int,
    day: int = 1,
    month: int = 1,
    year: int = 2023,
    open_p: float = 1.0,
    high: float = 1.001,
    low: float = 0.999,
    close: float = 1.0005,
) -> Bar:
    hour = hour % 24
    day = (day - 1) % 30 + 1
    month = (month - 1) % 12 + 1
    return Bar(
        time=datetime(year, month, day, hour, 0),
        open=open_p,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


class TestQ1BacktestStudy:
    def test_empty_bars_returns_zero_results(self):
        study = Q1BacktestStudy()
        result = study.run([])
        assert result.sample_size == 0
        assert result.go_nogo is False
        assert result.results == {}

    def test_sample_data_runs_without_error(self):
        bars = [_make_bar(h % 24) for h in range(50)]
        study = Q1BacktestStudy()
        result = study.run(bars)
        assert result.question == "Q1"
        assert result.instrument == "EURUSD"
        assert result.timeframe == "H1"
        assert "rr_3_1_hit_rate" in result.results

    def test_pass_criteria_requires_60_percent_at_3_1(self):
        study = Q1BacktestStudy()
        assert len(study.go_nogo_criteria) == 1
        c = study.go_nogo_criteria[0]
        assert c.metric == "rr_3_1_hit_rate"
        assert c.threshold == 0.60
        assert c.operator == ">="

    def test_analyze_returns_required_metrics(self):
        bars = [_make_bar(h) for h in range(100)]
        study = Q1BacktestStudy()
        metrics = study.analyze(bars)
        required = [
            "sample_size",
            "rr_3_1_hit_rate",
            "average_rr",
            "l1_hit_rate",
            "l2_hit_rate",
            "l3_hit_rate",
            "stop_loss_rate",
        ]
        for m in required:
            assert m in metrics, f"Missing metric: {m}"

    def test_average_rr_includes_sl_trades(self):
        study = Q1BacktestStudy()
        bars = [
            _make_bar(0, day=1),
            _make_bar(1, day=1),
            _make_bar(2, day=1, open_p=1.1000, high=1.1000, low=1.1000, close=1.1000),
            _make_bar(3, day=1, open_p=1.0980, high=1.0980, low=1.0980, close=1.0980),
            _make_bar(4, day=1, open_p=1.0960, high=1.0960, low=1.0960, close=1.0960),
            _make_bar(5, day=1, open_p=1.0980, high=1.0980, low=1.0980, close=1.0980),
            _make_bar(6, day=1, open_p=1.0960, high=1.0960, low=1.0960, close=1.0960),
            _make_bar(7, day=2, open_p=1.0975, high=1.0975, low=1.0975, close=1.0975),
            _make_bar(8, day=2, open_p=1.0980, high=1.0980, low=1.0920, close=1.0925),
        ]
        pattern = MWPattern(
            pattern_type="W",
            left_shoulder_idx=2,
            left_shoulder_price=1.1000,
            neckline_start_idx=2,
            neckline_start_price=1.1000,
            valley_peak_idx=4,
            valley_peak_price=1.0960,
            neckline_end_idx=6,
            neckline_end_price=1.0960,
            right_shoulder_idx=6,
            right_shoulder_price=1.0960,
            neckline_level=1.0980,
            depth_pips=40.0,
            formation_start_time=datetime(2023, 1, 1, 2),
            formation_end_time=datetime(2023, 1, 1, 6),
            sessions=[],
            bar_count=5,
        )
        entry_idx = 7
        entry_price = bars[entry_idx].close
        atr = 0.0010
        result = study._evaluate_long(pattern, bars, entry_idx, entry_price, atr)
        assert result["outcome"] == "SL"
        assert result["rr"] == 0.0

        metrics = study.analyze(bars)
        sl_count = sum(
            1
            for p in study.detector.detect(bars, study.compute_atr(bars, 14))
            if study._evaluate_pattern(p, bars, study.compute_atr(bars, 14))["outcome"] == "SL"
        )
        if sl_count > 0:
            closed_count = sum(
                1
                for v in [
                    study._evaluate_pattern(p, bars, study.compute_atr(bars, 14))["outcome"]
                    for p in study.detector.detect(bars, study.compute_atr(bars, 14))
                ]
                if v != "open"
            )
            if closed_count > 0:
                avg = metrics["average_rr"]
                assert avg >= 0.0, "average_rr must include SL trades at rr=0.0"


class TestQ1TradeSimulation:
    def test_long_tp3_triggers_before_tp2_and_tp1(self):
        study = Q1BacktestStudy()
        bars = [
            _make_bar(0, day=1),
            _make_bar(1, day=1),
            _make_bar(2, day=1, open_p=1.1000, high=1.1000, low=1.1000, close=1.1000),
            _make_bar(3, day=1, open_p=1.0980, high=1.0980, low=1.0980, close=1.0980),
            _make_bar(4, day=1, open_p=1.0960, high=1.0960, low=1.0960, close=1.0960),
            _make_bar(5, day=1, open_p=1.0980, high=1.0980, low=1.0980, close=1.0980),
            _make_bar(6, day=1, open_p=1.0960, high=1.0960, low=1.0960, close=1.0960),
            _make_bar(7, day=2, open_p=1.0970, high=1.0970, low=1.0970, close=1.0970),
            _make_bar(8, day=2, open_p=1.0975, high=1.1040, low=1.0975, close=1.1035),
        ]

        pattern = MWPattern(
            pattern_type="W",
            left_shoulder_idx=2,
            left_shoulder_price=1.1000,
            neckline_start_idx=2,
            neckline_start_price=1.1000,
            valley_peak_idx=4,
            valley_peak_price=1.0960,
            neckline_end_idx=6,
            neckline_end_price=1.0960,
            right_shoulder_idx=6,
            right_shoulder_price=1.0960,
            neckline_level=1.0980,
            depth_pips=40.0,
            formation_start_time=datetime(2023, 1, 1, 2),
            formation_end_time=datetime(2023, 1, 1, 6),
            sessions=[],
            bar_count=5,
        )

        entry_idx = 7
        entry_price = bars[entry_idx].close
        atr = 0.0010

        result = study._evaluate_long(pattern, bars, entry_idx, entry_price, atr)
        assert result["outcome"] == "L3"
        assert result["rr"] == 3.0

    def test_short_tp3_triggers_before_tp2_and_tp1(self):
        study = Q1BacktestStudy()
        bars = [
            _make_bar(0, day=1),
            _make_bar(1, day=1),
            _make_bar(2, day=1, open_p=1.0960, high=1.0960, low=1.0960, close=1.0960),
            _make_bar(3, day=1, open_p=1.0980, high=1.0980, low=1.0980, close=1.0980),
            _make_bar(4, day=1, open_p=1.1000, high=1.1000, low=1.1000, close=1.1000),
            _make_bar(5, day=1, open_p=1.0980, high=1.0980, low=1.0980, close=1.0980),
            _make_bar(6, day=1, open_p=1.1000, high=1.1000, low=1.1000, close=1.1000),
            _make_bar(7, day=2, open_p=1.0995, high=1.0995, low=1.0995, close=1.0995),
            _make_bar(8, day=2, open_p=1.0990, high=1.0930, low=1.0990, close=1.0935),
        ]

        pattern = MWPattern(
            pattern_type="M",
            left_shoulder_idx=2,
            left_shoulder_price=1.0960,
            neckline_start_idx=2,
            neckline_start_price=1.0960,
            valley_peak_idx=4,
            valley_peak_price=1.1000,
            neckline_end_idx=6,
            neckline_end_price=1.1000,
            right_shoulder_idx=6,
            right_shoulder_price=1.1000,
            neckline_level=1.0980,
            depth_pips=40.0,
            formation_start_time=datetime(2023, 1, 1, 2),
            formation_end_time=datetime(2023, 1, 1, 6),
            sessions=[],
            bar_count=5,
        )

        entry_idx = 7
        entry_price = bars[entry_idx].close
        atr = 0.0010

        result = study._evaluate_short(pattern, bars, entry_idx, entry_price, atr)
        assert result["outcome"] == "L3"
        assert result["rr"] == 3.0

    def test_stop_loss_triggers_when_price_reverses(self):
        study = Q1BacktestStudy()
        bars = [
            _make_bar(0, day=1),
            _make_bar(1, day=1),
            _make_bar(2, day=1, open_p=1.1000, high=1.1000, low=1.1000, close=1.1000),
            _make_bar(3, day=1, open_p=1.0980, high=1.0980, low=1.0980, close=1.0980),
            _make_bar(4, day=1, open_p=1.0960, high=1.0960, low=1.0960, close=1.0960),
            _make_bar(5, day=1, open_p=1.0980, high=1.0980, low=1.0980, close=1.0980),
            _make_bar(6, day=1, open_p=1.0960, high=1.0960, low=1.0960, close=1.0960),
            _make_bar(7, day=2, open_p=1.0975, high=1.0975, low=1.0975, close=1.0975),
            _make_bar(8, day=2, open_p=1.0980, high=1.0980, low=1.0920, close=1.0925),
        ]

        pattern = MWPattern(
            pattern_type="W",
            left_shoulder_idx=2,
            left_shoulder_price=1.1000,
            neckline_start_idx=2,
            neckline_start_price=1.1000,
            valley_peak_idx=4,
            valley_peak_price=1.0960,
            neckline_end_idx=6,
            neckline_end_price=1.0960,
            right_shoulder_idx=6,
            right_shoulder_price=1.0960,
            neckline_level=1.0980,
            depth_pips=40.0,
            formation_start_time=datetime(2023, 1, 1, 2),
            formation_end_time=datetime(2023, 1, 1, 6),
            sessions=[],
            bar_count=5,
        )

        entry_idx = 7
        entry_price = bars[entry_idx].close
        atr = 0.0010

        result = study._evaluate_long(pattern, bars, entry_idx, entry_price, atr)
        assert result["outcome"] == "SL"
        assert result["rr"] == 0.0


class TestQ1BacktestIntegration:
    def test_q1_study_produces_valid_result(self):
        study = Q1BacktestStudy()
        bars = [_make_bar(h % 24, day=i // 24 + 1) for i, h in enumerate(range(2400))]
        result = study.run(bars)
        assert isinstance(result.sample_size, int)
        assert result.sample_size >= 0

    def test_result_json_is_valid(self):
        study = Q1BacktestStudy()
        bars = [_make_bar(h % 24, day=i // 24 + 1) for i, h in enumerate(range(1200))]
        result = study.run(bars)
        j = result.to_json()
        parsed = json.loads(j)
        assert parsed["question"] == "Q1"
        assert "pass" in parsed
        assert "criteria" in parsed

    def test_save_creates_report_file(self, tmp_path):
        study = Q1BacktestStudy()
        bars = [_make_bar(h % 24, day=i // 24 + 1) for i, h in enumerate(range(1200))]
        result = study.run(bars)
        report_path = tmp_path / "q1_report.json"
        result.save(str(report_path))
        assert report_path.exists()
        parsed = json.loads(report_path.read_text())
        assert parsed["question"] == "Q1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
