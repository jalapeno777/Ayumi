from datetime import datetime, timedelta  # noqa: I001

from backtest.engine import Bar
from scripts.backtest_q2_lod_hod_stop_rate import (
    Q2LODHODStudy,
    classify_stop_hit,
    compute_optimal_buffer,
    group_by_day,
    simulate_trade,
)


def _make_bar(dt: datetime, o: float, h: float, low: float, c: float) -> Bar:
    return Bar(time=dt, open=o, high=h, low=low, close=c)


def _make_day_bars(date: datetime, levels: list[tuple[float, float, float]]) -> list[Bar]:
    bars = []
    for hour, (o, h, low, c) in enumerate(levels):
        bars.append(_make_bar(date + timedelta(hours=hour), o, h, low, c))
    return bars


class TestGroupByDay:
    def test_groups_bars_by_date(self):
        bars = [
            _make_bar(datetime(2024, 1, 1, 0), 1.1, 1.15, 1.09, 1.12),
            _make_bar(datetime(2024, 1, 1, 1), 1.12, 1.16, 1.10, 1.11),
            _make_bar(datetime(2024, 1, 2, 0), 1.11, 1.14, 1.08, 1.13),
        ]
        days = group_by_day(bars)
        assert len(days) == 2
        assert days[0].date == "2024-01-01"
        assert days[0].lod == 1.09
        assert days[0].hod == 1.16
        assert days[1].date == "2024-01-02"
        assert days[1].lod == 1.08
        assert days[1].hod == 1.14

    def test_empty_bars(self):
        assert group_by_day([]) == []

    def test_single_day(self):
        bars = [_make_bar(datetime(2024, 1, 1, 0), 1.1, 1.15, 1.09, 1.12)]
        days = group_by_day(bars)
        assert len(days) == 1
        assert days[0].lod == 1.09
        assert days[0].hod == 1.15


class TestClassifyStopHit:
    def test_exact_hit_long(self):
        bar = _make_bar(datetime(2024, 1, 1), 1.10, 1.12, 1.0998, 1.11)
        hit_type = classify_stop_hit(bar, 1.10, "long")
        assert hit_type == "lod_hod_exact"

    def test_exact_hit_short(self):
        bar = _make_bar(datetime(2024, 1, 1), 1.10, 1.1002, 1.09, 1.095)
        hit_type = classify_stop_hit(bar, 1.10, "short")
        assert hit_type == "lod_hod_exact"

    def test_intrabar_spike_long(self):
        bar = _make_bar(datetime(2024, 1, 1), 1.10, 1.12, 1.0950, 1.11)
        hit_type = classify_stop_hit(bar, 1.10, "long")
        assert hit_type == "intrabar_spike"

    def test_intrabar_spike_short(self):
        bar = _make_bar(datetime(2024, 1, 1), 1.10, 1.1050, 1.09, 1.095)
        hit_type = classify_stop_hit(bar, 1.10, "short")
        assert hit_type == "intrabar_spike"


class TestSimulateTrade:
    def test_long_stop_loss_hit(self):
        bars = [
            _make_bar(datetime(2024, 1, 1, 0), 1.1000, 1.1050, 1.0950, 1.1000),
            _make_bar(datetime(2024, 1, 1, 1), 1.1000, 1.1010, 1.0960, 1.0980),
            _make_bar(datetime(2024, 1, 1, 2), 1.0980, 1.0990, 1.0940, 1.0950),
        ]
        result = simulate_trade(bars, 0, "long", 1.0950, 50, rr_ratio=3.0)
        assert result.exit_reason == "stop_loss"
        assert result.direction == "long"
        assert result.stop_price == 1.0950

    def test_short_stop_loss_hit(self):
        bars = [
            _make_bar(datetime(2024, 1, 1, 0), 1.1000, 1.1050, 1.0950, 1.1000),
            _make_bar(datetime(2024, 1, 1, 1), 1.1000, 1.1010, 1.0960, 1.0980),
            _make_bar(datetime(2024, 1, 1, 2), 1.0980, 1.1060, 1.0970, 1.1050),
        ]
        result = simulate_trade(bars, 0, "short", 1.1050, 50, rr_ratio=3.0)
        assert result.exit_reason == "stop_loss"
        assert result.direction == "short"

    def test_long_take_profit(self):
        bars = [
            _make_bar(datetime(2024, 1, 1, 0), 1.1000, 1.1050, 1.0950, 1.1000),
            _make_bar(datetime(2024, 1, 1, 1), 1.1000, 1.1020, 1.0990, 1.1010),
            _make_bar(datetime(2024, 1, 1, 2), 1.1010, 1.1160, 1.1000, 1.1150),
        ]
        result = simulate_trade(bars, 0, "long", 1.0950, 50, rr_ratio=3.0)
        assert result.exit_reason == "take_profit"
        assert result.exit_price == 1.1000 + 50 * 0.0001 * 3.0

    def test_short_take_profit(self):
        bars = [
            _make_bar(datetime(2024, 1, 1, 0), 1.1000, 1.1050, 1.0950, 1.1000),
            _make_bar(datetime(2024, 1, 1, 1), 1.1000, 1.1010, 1.0980, 1.0990),
            _make_bar(datetime(2024, 1, 1, 2), 1.0990, 1.1000, 1.0840, 1.0850),
        ]
        result = simulate_trade(bars, 0, "short", 1.1050, 50, rr_ratio=3.0)
        assert result.exit_reason == "take_profit"
        assert result.exit_price == 1.1000 - 50 * 0.0001 * 3.0

    def test_no_exit_open_trade(self):
        bars = [
            _make_bar(datetime(2024, 1, 1, 0), 1.1000, 1.1050, 1.0950, 1.1000),
            _make_bar(datetime(2024, 1, 1, 1), 1.1000, 1.1010, 1.0990, 1.1005),
        ]
        result = simulate_trade(bars, 0, "long", 1.0950, 50, rr_ratio=3.0)
        assert result.exit_reason == "open"

    def test_slippage_measured_on_intrabar_spike(self):
        bars = [
            _make_bar(datetime(2024, 1, 1, 0), 1.1000, 1.1050, 1.0950, 1.1000),
            _make_bar(datetime(2024, 1, 1, 1), 1.1000, 1.1005, 1.0900, 1.0950),
        ]
        result = simulate_trade(bars, 0, "long", 1.0950, 50, rr_ratio=3.0)
        assert result.exit_reason == "stop_loss"
        assert result.slippage_pips > 0
        assert result.hit_type == "intrabar_spike"

    def test_zero_slippage_on_exact_hit(self):
        bars = [
            _make_bar(datetime(2024, 1, 1, 0), 1.1000, 1.1050, 1.0950, 1.1000),
            _make_bar(datetime(2024, 1, 1, 1), 1.1000, 1.1005, 1.0950, 1.0960),
        ]
        result = simulate_trade(bars, 0, "long", 1.0950, 50, rr_ratio=3.0)
        assert result.exit_reason == "stop_loss"
        assert result.slippage_pips == 0.0
        assert result.hit_type == "lod_hod_exact"


class TestComputeOptimalBuffer:
    def test_returns_median_slippage(self):
        from scripts.backtest_q2_lod_hod_stop_rate import TradeResult

        trades = [
            TradeResult(
                0,
                1.1,
                "long",
                1.095,
                1.11,
                1.095,
                "stop_loss",
                1.095,
                1,
                5.0,
                "intrabar_spike",
            ),
            TradeResult(
                1,
                1.1,
                "long",
                1.095,
                1.11,
                1.095,
                "stop_loss",
                1.095,
                2,
                10.0,
                "intrabar_spike",
            ),
            TradeResult(
                2,
                1.1,
                "long",
                1.095,
                1.11,
                1.095,
                "stop_loss",
                1.095,
                3,
                3.0,
                "intrabar_spike",
            ),
        ]
        buf = compute_optimal_buffer(trades)
        assert buf == 5.0

    def test_empty_trades_returns_zero(self):
        assert compute_optimal_buffer([]) == 0.0


class TestQ2LODHODStudy:
    def test_study_produces_required_fields(self):
        base = datetime(2024, 1, 1)
        bars = []
        for day in range(5):
            day_start = base + timedelta(days=day)
            lod = 1.1000 - (day + 1) * 0.001
            hod = 1.1000 + (day + 1) * 0.001
            for hour in range(24):
                o = 1.1000 + (hour * 0.0001 * (1 if day % 2 == 0 else -1))
                h = max(o, hod - 0.002)
                low = min(o, lod + 0.002)
                c = o + 0.0001
                bars.append(_make_bar(day_start + timedelta(hours=hour), o, h, low, c))

        study = Q2LODHODStudy(rr_ratio=3.0)
        result = study.run(bars)

        assert result.question == "Q2"
        assert result.instrument == "EURUSD"
        assert "stop_loss_rate" in result.results
        assert "lod_hod_stop_rate" in result.results
        assert "intrabar_spike_rate" in result.results
        assert "avg_slippage_intrabar_pips" in result.results
        assert "optimal_buffer_pips" in result.results
        assert "profit_factor" in result.results
        assert "net_expectancy_r" in result.results
        assert "rr_ratio" in result.results
        assert result.sample_size >= 0

    def test_study_empty_bars(self):
        study = Q2LODHODStudy(rr_ratio=3.0)
        result = study.run([])
        assert result.sample_size == 0
        assert result.go_nogo is False

    def test_profit_factor_calculation(self):
        study = Q2LODHODStudy(rr_ratio=3.0)
        result = study.run([])
        assert result.results.get("profit_factor", 0.0) == 0.0

    def test_net_expectancy_positive_with_favorable_rr(self):
        study = Q2LODHODStudy(rr_ratio=3.0)
        result = study.run([])
        assert result.results.get("net_expectancy_r", 0.0) == 0.0

    def test_rr_ratio_stored_in_results(self):
        base = datetime(2024, 1, 1)
        bars = []
        for day in range(5):
            day_start = base + timedelta(days=day)
            lod = 1.1000 - (day + 1) * 0.001
            hod = 1.1000 + (day + 1) * 0.001
            for hour in range(24):
                o = 1.1000 + (hour * 0.0001 * (1 if day % 2 == 0 else -1))
                h = max(o, hod - 0.002)
                low = min(o, lod + 0.002)
                c = o + 0.0001
                bars.append(_make_bar(day_start + timedelta(hours=hour), o, h, low, c))
        study = Q2LODHODStudy(rr_ratio=3.0)
        result = study.run(bars)
        assert result.results["rr_ratio"] == 3.0

    def test_study_with_custom_rr(self):
        study = Q2LODHODStudy(rr_ratio=2.0)
        base = datetime(2024, 1, 1)
        bars = []
        for day in range(5):
            day_start = base + timedelta(days=day)
            lod = 1.1000 - (day + 1) * 0.001
            hod = 1.1000 + (day + 1) * 0.001
            for hour in range(24):
                o = 1.1000 + (hour * 0.0001 * (1 if day % 2 == 0 else -1))
                h = max(o, hod - 0.002)
                low = min(o, lod + 0.002)
                c = o + 0.0001
                bars.append(_make_bar(day_start + timedelta(hours=hour), o, h, low, c))
        result = study.run(bars)
        assert result.results["rr_ratio"] == 2.0

    def test_result_to_json(self):
        study = Q2LODHODStudy(rr_ratio=3.0)
        result = study.run([])
        j = result.to_json()
        import json

        parsed = json.loads(j)
        assert parsed["question"] == "Q2"
        assert "pass" in parsed
