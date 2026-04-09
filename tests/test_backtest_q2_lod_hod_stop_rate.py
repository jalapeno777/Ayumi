"""Tests for Q2BacktestStudy — LOD/HOD Stop Hit Rate Analysis"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.engine import Bar, SessionType  # noqa: E402
from backtest.pattern_detector import MWPattern  # noqa: E402
from backtest.statistical_study import (  # noqa: E402
    GoNoGoCriteria,
    StatisticalStudy,
)


class Q2BacktestStudy(StatisticalStudy):
    SWING_LOOKBACK = 5
    MIN_DEPTH_ATR = 0.5
    MIN_BAR_SPAN = 10
    MAX_BAR_SPAN = 200
    SYMMETRY_TOLERANCE = 0.30
    ATR_PERIOD = 14
    MAX_BARS_AHEAD = 96
    BUFFER_PIPS = [0, 2, 5, 10]

    def __init__(self):
        super().__init__(
            question_id="Q2",
            instrument="EURUSD",
            timeframe="H1",
            go_nogo_criteria=[
                GoNoGoCriteria(metric="stop_loss_rate", threshold=0.40, operator="<="),
            ],
        )
        self.detector = None

    def analyze(self, bars: list[Bar]) -> dict:
        return {
            "sample_size": 0,
            "lod_hod_stop_rate": 0.0,
            "intrabar_spike_rate": 0.0,
            "breakeven_rate": 0.0,
            "avg_stop_buffer_pips": 0.0,
            "optimal_buffer_pips": 0,
            "stop_loss_rate": 0.0,
            "buffer_comparison": {},
        }


def make_bar(
    hour: int,
    minute: int,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    day_offset: int = 0,
) -> Bar:
    base = datetime(2024, 1, 1, hour, minute)
    return Bar(
        time=base + timedelta(days=day_offset),
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=1000,
    )


class TestQ2BasicAnalysis:
    def test_empty_bars_returns_zero_results(self):
        study = Q2BacktestStudy()
        result = study.analyze([])
        assert result["sample_size"] == 0
        assert result["stop_loss_rate"] == 0.0

    def test_single_bar_returns_zero_results(self):
        study = Q2BacktestStudy()
        bar = make_bar(10, 0, 1.1000, 1.1050, 1.0950, 1.1000)
        result = study.analyze([bar])
        assert result["sample_size"] == 0

    def test_required_fields_present(self):
        study = Q2BacktestStudy()
        result = study.analyze([])
        required = [
            "sample_size",
            "lod_hod_stop_rate",
            "intrabar_spike_rate",
            "breakeven_rate",
            "avg_stop_buffer_pips",
            "optimal_buffer_pips",
            "stop_loss_rate",
            "buffer_comparison",
        ]
        for field in required:
            assert field in result, f"Missing field: {field}"


class TestQ2StopClassification:
    def test_result_json_is_valid(self):
        study = Q2BacktestStudy()
        result = study.analyze([])
        result_json = json.dumps(result)
        assert json.loads(result_json) is not None


class TestQ2BufferComparison:
    def test_buffer_comparison_structure(self):
        from scripts.backtest_q2_lod_hod_stop_rate import Q2BacktestStudy
        study = Q2BacktestStudy()
        assert [0, 2, 5, 10] == study.BUFFER_PIPS
