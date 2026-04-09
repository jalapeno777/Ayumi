"""Tests for Q2BacktestStudy — LOD/HOD Stop Hit Rate Analysis"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src" / "forex-bot"))
sys.path.insert(0, str(project_root / "scripts"))

from backtest.engine import Bar  # noqa: E402
from backtest_q2_lod_hod_stop_rate import Q2BacktestStudy  # noqa: E402


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


class TestGetSessionBars:
    def test_only_returns_bars_before_entry(self):
        study = Q2BacktestStudy()
        bars = [
            make_bar(8, 0, 1.10, 1.11, 1.09, 1.105),
            make_bar(9, 0, 1.10, 1.12, 1.095, 1.10),
            make_bar(10, 0, 1.10, 1.10, 1.08, 1.09),
            make_bar(11, 0, 1.10, 1.13, 1.09, 1.11),
        ]
        result = study._get_session_bars(bars, entry_idx=2)
        assert len(result) == 2
        assert all(b.time.hour <= 9 for b in result)

    def test_excludes_future_session_bars(self):
        study = Q2BacktestStudy()
        bars = [
            make_bar(8, 0, 1.10, 1.10, 1.08, 1.09),
            make_bar(9, 0, 1.10, 1.10, 1.07, 1.09),
            make_bar(10, 0, 1.10, 1.10, 1.06, 1.09),
            make_bar(11, 0, 1.10, 1.10, 1.05, 1.09),
            make_bar(14, 0, 1.10, 1.10, 1.04, 1.09),
        ]
        entry_idx = 2
        result = study._get_session_bars(bars, entry_idx)
        future_bars = [b for b in bars[entry_idx:]]
        for fb in future_bars:
            assert fb not in result

    def test_london_session_hours(self):
        study = Q2BacktestStudy()
        bars = [
            make_bar(7, 0, 1.10, 1.11, 1.09, 1.105),
            make_bar(8, 0, 1.10, 1.12, 1.095, 1.10),
            make_bar(9, 0, 1.10, 1.13, 1.09, 1.11),
        ]
        result = study._get_session_bars(bars, entry_idx=2)
        assert len(result) == 2
        assert result[0].time.hour == 7
        assert result[1].time.hour == 8

    def test_ny_session_hours(self):
        study = Q2BacktestStudy()
        bars = [
            make_bar(12, 0, 1.10, 1.11, 1.09, 1.105),
            make_bar(14, 0, 1.10, 1.12, 1.095, 1.10),
            make_bar(16, 0, 1.10, 1.13, 1.09, 1.11),
            make_bar(20, 0, 1.10, 1.14, 1.09, 1.12),
        ]
        result = study._get_session_bars(bars, entry_idx=3)
        assert len(result) == 3
        assert all(12 <= b.time.hour < 22 for b in result)

    def test_falls_back_to_entry_bar_when_no_prior_session_bars(self):
        study = Q2BacktestStudy()
        bars = [make_bar(10, 0, 1.10, 1.11, 1.09, 1.10)]
        result = study._get_session_bars(bars, entry_idx=0)
        assert len(result) == 1
        assert result[0] is bars[0]


class TestCheckStopHit:
    def test_bullish_tp1_hit_returns_breakeven(self):
        study = Q2BacktestStudy()
        entry_price = 1.1000
        stop_level = 1.0950
        bars = [
            make_bar(8, 0, 1.10, 1.11, 1.09, 1.10),
            make_bar(9, 0, 1.10, 1.11, 1.09, 1.10),
            make_bar(10, 0, 1.10, 1.105, 1.095, 1.10),
            make_bar(11, 0, 1.10, 1.115, 1.095, 1.105),
        ]
        result = study._check_stop_hit(
            bars, entry_idx=2, entry_price=entry_price,
            stop_level=stop_level, session_lod=1.0940,
            session_hod=1.1050, atr=0.001, is_bullish=True,
        )
        assert result["outcome"] == "breakeven"
        assert result["hit_at_lod_hod"] is False

    def test_bullish_sl_at_stop_level_not_at_lod(self):
        study = Q2BacktestStudy()
        entry_price = 1.1000
        stop_level = 1.0940
        session_lod = 1.0920
        bars = [
            make_bar(8, 0, 1.10, 1.11, 1.09, 1.10),
            make_bar(9, 0, 1.10, 1.11, 1.09, 1.10),
            make_bar(10, 0, 1.10, 1.105, 1.095, 1.10),
            make_bar(11, 0, 1.10, 1.105, 1.0935, 1.095),
        ]
        result = study._check_stop_hit(
            bars, entry_idx=2, entry_price=entry_price,
            stop_level=stop_level, session_lod=session_lod,
            session_hod=1.1050, atr=0.001, is_bullish=True,
        )
        assert result["outcome"] == "SL"
        assert result["hit_at_lod_hod"] is False
        assert result["slippage_pips"] == 5.0

    def test_bullish_sl_at_stop_level_reaches_lod(self):
        study = Q2BacktestStudy()
        entry_price = 1.1000
        stop_level = 1.0940
        session_lod = 1.0935
        bars = [
            make_bar(8, 0, 1.10, 1.11, 1.09, 1.10),
            make_bar(9, 0, 1.10, 1.11, 1.09, 1.10),
            make_bar(10, 0, 1.10, 1.105, 1.095, 1.10),
            make_bar(11, 0, 1.10, 1.105, 1.0930, 1.095),
        ]
        result = study._check_stop_hit(
            bars, entry_idx=2, entry_price=entry_price,
            stop_level=stop_level, session_lod=session_lod,
            session_hod=1.1050, atr=0.001, is_bullish=True,
        )
        assert result["outcome"] == "SL"
        assert result["hit_at_lod_hod"] is True
        assert result["slippage_pips"] == 10.0

    def test_bullish_no_exit_returns_open(self):
        study = Q2BacktestStudy()
        entry_price = 1.1000
        stop_level = 1.0900
        bars = [
            make_bar(8, 0, 1.10, 1.11, 1.09, 1.10),
            make_bar(9, 0, 1.10, 1.11, 1.09, 1.10),
            make_bar(10, 0, 1.10, 1.105, 1.095, 1.10),
            make_bar(11, 0, 1.10, 1.105, 1.095, 1.105),
        ]
        result = study._check_stop_hit(
            bars, entry_idx=2, entry_price=entry_price,
            stop_level=stop_level, session_lod=1.0880,
            session_hod=1.1050, atr=0.001, is_bullish=True,
        )
        assert result["outcome"] == "open"

    def test_bearish_tp1_hit_returns_breakeven(self):
        study = Q2BacktestStudy()
        entry_price = 1.1000
        stop_level = 1.1050
        tp1 = entry_price - (stop_level - entry_price)
        bars = [
            make_bar(12, 0, 1.10, 1.11, 1.09, 1.10),
            make_bar(13, 0, 1.10, 1.10, 1.09, 1.095),
            make_bar(14, 0, 1.095, 1.095, tp1 - 0.0005, 1.090),
        ]
        result = study._check_stop_hit(
            bars, entry_idx=1, entry_price=entry_price,
            stop_level=stop_level, session_lod=1.0850,
            session_hod=1.1040, atr=0.001, is_bullish=False,
        )
        assert result["outcome"] == "breakeven"
        assert result["hit_at_lod_hod"] is False

    def test_bearish_sl_at_stop_level_not_at_hod(self):
        study = Q2BacktestStudy()
        entry_price = 1.1000
        stop_level = 1.1060
        tp1 = entry_price - (stop_level - entry_price)
        bars = [
            make_bar(12, 0, 1.10, 1.105, 1.09, 1.10),
            make_bar(13, 0, 1.10, 1.105, 1.09, 1.10),
            make_bar(14, 0, 1.10, 1.1065, max(tp1 + 0.001, 1.09), 1.10),
        ]
        result = study._check_stop_hit(
            bars, entry_idx=1, entry_price=entry_price,
            stop_level=stop_level, session_lod=1.0900,
            session_hod=1.1080, atr=0.001, is_bullish=False,
        )
        assert result["outcome"] == "SL"
        assert result["hit_at_lod_hod"] is False
        assert result["slippage_pips"] == 5.0

    def test_bearish_sl_reaches_hod(self):
        study = Q2BacktestStudy()
        entry_price = 1.1000
        stop_level = 1.1060
        tp1 = entry_price - (stop_level - entry_price)
        bars = [
            make_bar(12, 0, 1.10, 1.105, 1.09, 1.10),
            make_bar(13, 0, 1.10, 1.105, 1.09, 1.10),
            make_bar(14, 0, 1.10, 1.1070, max(tp1 + 0.001, 1.09), 1.10),
        ]
        result = study._check_stop_hit(
            bars, entry_idx=1, entry_price=entry_price,
            stop_level=stop_level, session_lod=1.0900,
            session_hod=1.1055, atr=0.001, is_bullish=False,
        )
        assert result["outcome"] == "SL"
        assert result["hit_at_lod_hod"] is True


class TestSlippagePips:
    def test_slippage_calculation(self):
        study = Q2BacktestStudy()
        slippage = study._slippage_pips(1.0935, 1.0940)
        assert slippage == 5.0

    def test_zero_slippage_exact_hit(self):
        study = Q2BacktestStudy()
        slippage = study._slippage_pips(1.0940, 1.0940)
        assert slippage == 0.0


class TestBufferDifferentiation:
    def test_different_buffers_produce_different_sl_outcomes(self):
        study = Q2BacktestStudy()
        entry_idx = 3
        entry_price = 1.1000

        bars = [
            make_bar(7, 0, 1.10, 1.1020, 1.0960, 1.0980),
            make_bar(8, 0, 1.10, 1.1030, 1.0950, 1.0990),
            make_bar(9, 0, 1.10, 1.1040, 1.0940, 1.0980),
            make_bar(10, 0, 1.10, 1.1050, 1.0990, 1.1000),
            make_bar(11, 0, 1.10, 1.1050, 1.0932, 1.0990),
            make_bar(12, 0, 1.10, 1.1050, 1.0990, 1.1000),
        ]

        session_bars = study._get_session_bars(bars, entry_idx)
        session_lod = min(b.low for b in session_bars)
        session_hod = max(b.high for b in session_bars)
        assert session_lod == 1.0940

        results_by_buffer = {}
        for buf in [0, 5, 10]:
            pv = study.pip_value(entry_price)
            stop_level = session_lod - buf * pv
            risk = entry_price - stop_level
            assert risk > 0
            result = study._check_stop_hit(
                bars, entry_idx=entry_idx, entry_price=entry_price,
                stop_level=stop_level, session_lod=session_lod,
                session_hod=session_hod, atr=0.001, is_bullish=True,
            )
            results_by_buffer[buf] = result

        assert results_by_buffer[0]["outcome"] == "SL"
        assert results_by_buffer[0]["hit_at_lod_hod"] is True

        assert results_by_buffer[5]["outcome"] == "SL"
        assert results_by_buffer[5]["hit_at_lod_hod"] is True

        assert results_by_buffer[10]["outcome"] == "open"


class TestAnalyzeIntegration:
    def test_empty_bars_returns_zero_results(self):
        study = Q2BacktestStudy()
        result = study.analyze([])
        assert result["sample_size"] == 0
        assert result["stop_loss_rate"] == 0.0

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

    def test_result_json_is_valid(self):
        study = Q2BacktestStudy()
        result = study.analyze([])
        result_json = json.dumps(result)
        assert json.loads(result_json) is not None

    def test_buffer_comparison_structure(self):
        study = Q2BacktestStudy()
        assert [0, 2, 5, 10] == study.BUFFER_PIPS
