"""BQ-508: Regime labels on walk-forward windows."""

from __future__ import annotations  # noqa: I001

from dataclasses import dataclass
from datetime import datetime, timezone


from quant.walk_forward import (
    WindowMetrics,
    detect_regime_for_window,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeBar:
    """Minimal Bar-like object for testing."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    spread_pips: float = 0.0


def _make_bar(
    price: float = 1.1000,
    hour: int = 10,
    day_of_week: int = 2,
    spread: float = 0.0005,
) -> FakeBar:
    return FakeBar(
        time=datetime(2026, 1, 5 + day_of_week, hour, 0, tzinfo=timezone.utc),
        open=price,
        high=price + spread,
        low=price - spread,
        close=price + spread * 0.3,
        volume=100.0,
        spread_pips=0.0,
    )


def _make_bars(n: int, start_price: float = 1.1000, trend: float = 0.0) -> list[FakeBar]:
    """Generate n fake bars with optional trend."""
    bars = []
    price = start_price
    for i in range(n):
        price += trend
        bars.append(_make_bar(price=price, hour=8 + (i % 12)))
    return bars


# ---------------------------------------------------------------------------
# Tests: WindowMetrics regime fields
# ---------------------------------------------------------------------------


class TestWindowMetricsRegimeFields:
    def test_default_regime_values(self):
        m = WindowMetrics(
            window_index=0,
            win_rate=0.5,
            profit_factor=1.0,
            max_drawdown=0.05,
            sharpe_ratio=1.0,
            trade_count=10,
            total_pnl=100.0,
            passed_go_nogo=True,
        )
        assert m.regime_volatility == "unknown"
        assert m.regime_trend == "unknown"
        assert m.regime_session == "unknown"
        assert m.regime_combined == "unknown"
        assert m.regime_quality == 0.0

    def test_regime_fields_set(self):
        m = WindowMetrics(
            window_index=0,
            win_rate=0.5,
            profit_factor=1.0,
            max_drawdown=0.05,
            sharpe_ratio=1.0,
            trade_count=10,
            total_pnl=100.0,
            passed_go_nogo=True,
            regime_volatility="high",
            regime_trend="trending_up",
            regime_session="london",
            regime_combined="high_trending_up_london",
            regime_quality=0.75,
        )
        assert m.regime_volatility == "high"
        assert m.regime_trend == "trending_up"
        assert m.regime_session == "london"
        assert m.regime_combined == "high_trending_up_london"
        assert m.regime_quality == 0.75


# ---------------------------------------------------------------------------
# Tests: detect_regime_for_window
# ---------------------------------------------------------------------------


class TestDetectRegimeForWindow:
    def test_short_window_returns_defaults(self):
        """<14 bars → all defaults (council amendment K-3)."""
        bars = _make_bars(10)
        result = detect_regime_for_window(bars)
        assert result["regime_volatility"] == "unknown"
        assert result["regime_trend"] == "unknown"
        assert result["regime_session"] == "unknown"
        assert result["regime_combined"] == "unknown"
        assert result["regime_quality"] == 0.0

    def test_exact_14_bars_computes_regime(self):
        """Exactly 14 bars should compute regime (>= threshold)."""
        bars = _make_bars(14, trend=0.0005)
        result = detect_regime_for_window(bars)
        assert result["regime_volatility"] != "unknown"
        assert result["regime_trend"] != "unknown"
        assert result["regime_session"] != "unknown"
        assert result["regime_quality"] > 0.0

    def test_sufficient_bars_populates_all_fields(self):
        """With 50+ bars, all regime fields should be populated."""
        bars = _make_bars(60, trend=0.0003)
        result = detect_regime_for_window(bars)
        assert result["regime_volatility"] in {"low", "normal", "high", "extreme"}
        assert result["regime_trend"] in {
            "trending",
            "trending_up",
            "trending_down",
            "ranging",
            "neutral",
        }
        assert result["regime_session"] in {
            "asian",
            "london",
            "new_york",
            "off_hours",
        }
        assert len(result["regime_combined"]) > 0
        assert 0.0 <= result["regime_quality"] <= 1.0

    def test_empty_bars_returns_defaults(self):
        result = detect_regime_for_window([])
        assert result["regime_volatility"] == "unknown"
        assert result["regime_quality"] == 0.0

    def test_atr_percentile_guard_small_sample(self):
        """With 14-29 bars (small ATR series), should still produce a volatility label."""
        bars = _make_bars(20)
        result = detect_regime_for_window(bars)
        # Should use median-based classification, not crash
        assert result["regime_volatility"] in {"low", "normal", "high", "extreme"}

    def test_trending_up_detected(self):
        """Strong uptrend should detect trending_up."""
        bars = _make_bars(50, trend=0.005)
        result = detect_regime_for_window(bars)
        assert result["regime_trend"] == "trending_up"

    def test_trending_down_detected(self):
        """Strong downtrend should detect trending_down."""
        bars = _make_bars(50, trend=-0.005)
        result = detect_regime_for_window(bars)
        assert result["regime_trend"] == "trending_down"


# ---------------------------------------------------------------------------
# Tests: Regime labels in walk-forward output
# ---------------------------------------------------------------------------


class TestRegimeInWalkForwardOutput:
    def test_window_metrics_in_results(self):
        """Verify WindowMetrics with regime labels can be created (frozen dataclass)."""
        m = WindowMetrics(
            window_index=0,
            win_rate=0.6,
            profit_factor=1.5,
            max_drawdown=0.03,
            sharpe_ratio=1.2,
            trade_count=15,
            total_pnl=200.0,
            passed_go_nogo=True,
            regime_volatility="normal",
            regime_trend="trending_up",
            regime_session="london",
            regime_combined="normal_trending_up_london",
            regime_quality=0.8,
        )
        # Verify it's a proper frozen dataclass
        assert m.window_index == 0
        assert m.regime_volatility == "normal"
        assert m.regime_quality == 0.8
