"""Tests for Q1BacktestStudy — M/W Formation 3:1 R&R"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.engine import Bar  # noqa: E402
from backtest.pattern_detector import MWPattern, MWPatternDetector  # noqa: E402
from backtest.statistical_study import (  # noqa: E402
    GoNoGoCriteria,
    StatisticalStudy,
)


class Q1BacktestStudy(StatisticalStudy):
    SWING_LOOKBACK = 5
    MIN_DEPTH_ATR = 0.5
    MIN_BAR_SPAN = 10
    MAX_BAR_SPAN = 200
    SYMMETRY_TOLERANCE = 0.30
    ATR_PERIOD = 14
    MAX_BARS_AHEAD = 96

    def __init__(self):
        super().__init__(
            question_id="Q1",
            instrument="EURUSD",
            timeframe="H1",
            go_nogo_criteria=[
                GoNoGoCriteria(metric="rr_3_1_hit_rate", threshold=0.60, operator=">="),
            ],
        )
        self.detector = MWPatternDetector(
            swing_lookback=self.SWING_LOOKBACK,
            symmetry_tolerance=self.SYMMETRY_TOLERANCE,
            min_depth_atr=self.MIN_DEPTH_ATR,
            min_bar_span=self.MIN_BAR_SPAN,
            max_bar_span=self.MAX_BAR_SPAN,
        )

    def analyze(self, bars: list[Bar]) -> dict:
        atr_values = self.compute_atr(bars, period=self.ATR_PERIOD)
        patterns = self.detector.detect(bars, atr_values)

        if not patterns:
            return {
                "sample_size": 0,
                "rr_3_1_hit_rate": 0.0,
                "average_rr": 0.0,
                "l1_hit_rate": 0.0,
                "l2_hit_rate": 0.0,
                "l3_hit_rate": 0.0,
                "stop_loss_rate": 0.0,
            }

        outcomes: dict[str, int] = {"L1": 0, "L2": 0, "L3": 0, "SL": 0, "open": 0}
        rr_ratios: list[float] = []
        trades_with_3_1_or_better = 0
        total_closed_trades = 0

        for pattern in patterns:
            result = self._evaluate_pattern(pattern, bars, atr_values)
            outcome = result["outcome"]
            rr = result["rr"]

            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            rr_ratios.append(rr)

            if outcome != "open":
                total_closed_trades += 1
                if rr >= 3.0:
                    trades_with_3_1_or_better += 1

        total_closed = sum(v for k, v in outcomes.items() if k != "open")
        sample_size = len(patterns)

        l1_hit_rate = outcomes.get("L1", 0) / total_closed if total_closed > 0 else 0.0
        l2_hit_rate = outcomes.get("L2", 0) / total_closed if total_closed > 0 else 0.0
        l3_hit_rate = outcomes.get("L3", 0) / total_closed if total_closed > 0 else 0.0
        stop_loss_rate = outcomes.get("SL", 0) / total_closed if total_closed > 0 else 0.0
        rr_3_1_hit_rate = trades_with_3_1_or_better / total_closed if total_closed > 0 else 0.0

        closed_rrs = [r for r in rr_ratios if r > 0.0]
        average_rr = sum(closed_rrs) / len(closed_rrs) if closed_rrs else 0.0

        return {
            "sample_size": sample_size,
            "rr_3_1_hit_rate": round(rr_3_1_hit_rate, 4),
            "average_rr": round(average_rr, 4),
            "l1_hit_rate": round(l1_hit_rate, 4),
            "l2_hit_rate": round(l2_hit_rate, 4),
            "l3_hit_rate": round(l3_hit_rate, 4),
            "stop_loss_rate": round(stop_loss_rate, 4),
        }

    def _evaluate_pattern(
        self, pattern: MWPattern, bars: list[Bar], atr_values: list[float]
    ) -> dict:
        entry_idx = pattern.right_shoulder_idx + 1
        if entry_idx >= len(bars):
            return {"outcome": "open", "rr": 0.0}

        entry_price = bars[entry_idx].close
        atr = atr_values[entry_idx] if entry_idx < len(atr_values) else 0.0001

        if pattern.is_bullish:
            return self._evaluate_long(pattern, bars, entry_idx, entry_price, atr)
        else:
            return self._evaluate_short(pattern, bars, entry_idx, entry_price, atr)

    def _evaluate_long(
        self, pattern: MWPattern, bars: list[Bar], entry_idx: int, entry_price: float, atr: float
    ) -> dict:
        neckline = pattern.neckline_level
        stop = neckline - atr * 1.5
        risk = entry_price - stop
        if risk <= 0:
            return {"outcome": "open", "rr": 0.0}

        tp1 = entry_price + risk * 1
        tp2 = entry_price + risk * 2
        tp3 = entry_price + risk * 3

        for i in range(entry_idx, min(entry_idx + self.MAX_BARS_AHEAD, len(bars))):
            bar = bars[i]
            if bar.high >= tp3:
                return {"outcome": "L3", "rr": 3.0}
            elif bar.high >= tp2:
                return {"outcome": "L2", "rr": 2.0}
            elif bar.high >= tp1:
                return {"outcome": "L1", "rr": 1.0}
            elif bar.low <= stop:
                return {"outcome": "SL", "rr": 0.0}

        return {"outcome": "open", "rr": 0.0}

    def _evaluate_short(
        self, pattern: MWPattern, bars: list[Bar], entry_idx: int, entry_price: float, atr: float
    ) -> dict:
        neckline = pattern.neckline_level
        stop = neckline + atr * 1.5
        risk = stop - entry_price
        if risk <= 0:
            return {"outcome": "open", "rr": 0.0}

        tp1 = entry_price - risk * 1
        tp2 = entry_price - risk * 2
        tp3 = entry_price - risk * 3

        for i in range(entry_idx, min(entry_idx + self.MAX_BARS_AHEAD, len(bars))):
            bar = bars[i]
            if bar.low <= tp3:
                return {"outcome": "L3", "rr": 3.0}
            elif bar.low <= tp2:
                return {"outcome": "L2", "rr": 2.0}
            elif bar.low <= tp1:
                return {"outcome": "L1", "rr": 1.0}
            elif bar.high >= stop:
                return {"outcome": "SL", "rr": 0.0}

        return {"outcome": "open", "rr": 0.0}


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


def _make_bar_set(hour: int, day: int = 1, month: int = 1, year: int = 2023) -> Bar:
    return Bar(
        time=datetime(year, month, day, hour, 0),
        open=1.1000,
        high=1.1005,
        low=1.0995,
        close=1.1000,
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