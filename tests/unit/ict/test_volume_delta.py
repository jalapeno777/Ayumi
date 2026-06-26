from datetime import datetime, timedelta
from backtest.engine import Bar
from backtest.ict_smc.volume_delta import VolumeDeltaAnalyzer, VolumeDeltaResult


def _make_bars(n: int, base_vol: float = 500.0, seed: int = 42) -> list:
    import random

    random.seed(seed)
    bars = []
    price = 1.1000
    now = datetime(2024, 1, 1, 0, 0)
    for i in range(n):
        change = random.uniform(-0.001, 0.001)
        vol = base_vol + random.uniform(-200, 200)
        high = price + abs(change)
        low = price - abs(change)
        close = price + change
        bars.append(
            Bar(
                time=now + timedelta(hours=i),
                open=price,
                high=max(price, close, high),
                low=min(price, close, low),
                close=close,
                volume=vol,
            )
        )
        price = close
    return bars


class TestVolumeDeltaAnalyzer:
    def test_insufficient_bars_returns_none(self):
        a = VolumeDeltaAnalyzer()
        bars = _make_bars(10)
        assert a.analyze(bars) is None

    def test_returns_result_with_sufficient_bars(self):
        a = VolumeDeltaAnalyzer()
        bars = _make_bars(30)
        result = a.analyze(bars)
        assert result is not None
        assert isinstance(result, VolumeDeltaResult)

    def test_result_fields(self):
        a = VolumeDeltaAnalyzer()
        bars = _make_bars(50)
        result = a.analyze(bars)
        assert hasattr(result, "current_delta")
        assert hasattr(result, "rolling_avg_delta")
        assert hasattr(result, "delta_ratio")
        assert hasattr(result, "is_high_volume")
        assert hasattr(result, "is_low_volume")
        assert hasattr(result, "volume_percentile")
        assert 0.0 <= result.volume_percentile <= 100.0

    def test_custom_rolling_window(self):
        a = VolumeDeltaAnalyzer(rolling_window=10)
        bars = _make_bars(30)
        result = a.analyze(bars)
        assert result is not None

    def test_high_volume_detection(self):
        a = VolumeDeltaAnalyzer(rolling_window=20, high_volume_percentile=50.0)
        bars = _make_bars(30, base_vol=100.0, seed=1)
        bars[-1] = Bar(
            time=bars[-1].time,
            open=bars[-1].open,
            high=bars[-1].high,
            low=bars[-1].low,
            close=bars[-1].close,
            volume=10000.0,
        )
        result = a.analyze(bars)
        assert result is not None
        assert result.is_high_volume

    def test_low_volume_detection(self):
        a = VolumeDeltaAnalyzer(rolling_window=20, low_volume_percentile=50.0)
        bars = _make_bars(30, base_vol=1000.0, seed=1)
        bars[-1] = Bar(
            time=bars[-1].time,
            open=bars[-1].open,
            high=bars[-1].high,
            low=bars[-1].low,
            close=bars[-1].close,
            volume=1.0,
        )
        result = a.analyze(bars)
        assert result is not None
        assert result.is_low_volume

    def test_score_sweep_conviction_none(self):
        a = VolumeDeltaAnalyzer()
        assert a.score_sweep_conviction(None, "long") == 0.5

    def test_score_sweep_conviction_high_volume_long(self):
        a = VolumeDeltaAnalyzer()
        result = VolumeDeltaResult(
            current_delta=0.001,
            rolling_avg_delta=0.0001,
            delta_ratio=2.0,
            is_high_volume=True,
            is_low_volume=False,
            volume_percentile=90.0,
        )
        score = a.score_sweep_conviction(result, "long")
        assert score > 0.5

    def test_score_sweep_conviction_low_volume_penalty(self):
        a = VolumeDeltaAnalyzer()
        result = VolumeDeltaResult(
            current_delta=-0.001,
            rolling_avg_delta=0.0001,
            delta_ratio=-2.0,
            is_high_volume=False,
            is_low_volume=True,
            volume_percentile=10.0,
        )
        score = a.score_sweep_conviction(result, "long")
        assert score < 0.5

    def test_score_fvg_strength_high_volume(self):
        a = VolumeDeltaAnalyzer()
        result = VolumeDeltaResult(
            current_delta=0.002,
            rolling_avg_delta=0.0005,
            delta_ratio=3.0,
            is_high_volume=True,
            is_low_volume=False,
            volume_percentile=95.0,
        )
        score = a.score_fvg_strength(result)
        assert score > 0.5

    def test_score_fvg_strength_low_volume(self):
        a = VolumeDeltaAnalyzer()
        result = VolumeDeltaResult(
            current_delta=0.0,
            rolling_avg_delta=0.0005,
            delta_ratio=0.0,
            is_high_volume=False,
            is_low_volume=True,
            volume_percentile=5.0,
        )
        score = a.score_fvg_strength(result)
        assert score < 0.5

    def test_overall_volume_score_high(self):
        a = VolumeDeltaAnalyzer()
        result = VolumeDeltaResult(
            current_delta=0.001,
            rolling_avg_delta=0.0001,
            delta_ratio=2.0,
            is_high_volume=True,
            is_low_volume=False,
            volume_percentile=90.0,
        )
        assert a.overall_volume_score(result) == 0.8

    def test_overall_volume_score_low(self):
        a = VolumeDeltaAnalyzer()
        result = VolumeDeltaResult(
            current_delta=0.0,
            rolling_avg_delta=0.0001,
            delta_ratio=0.0,
            is_high_volume=False,
            is_low_volume=True,
            volume_percentile=5.0,
        )
        assert a.overall_volume_score(result) == 0.2

    def test_overall_volume_score_none(self):
        a = VolumeDeltaAnalyzer()
        assert a.overall_volume_score(None) == 0.5

    def test_delta_ratio_calculation(self):
        a = VolumeDeltaAnalyzer()
        bars = _make_bars(30, seed=10)
        result = a.analyze(bars)
        assert result is not None
        assert isinstance(result.delta_ratio, float)

    def test_zero_volume_handling(self):
        a = VolumeDeltaAnalyzer()
        bars = _make_bars(30, base_vol=0.0, seed=1)
        result = a.analyze(bars)
        assert result is not None
        assert result.volume_percentile >= 0.0
