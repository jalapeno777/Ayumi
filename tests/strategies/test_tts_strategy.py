"""Tests for TTSStrategy signal engine adapter — HTF, session, quality gates, and ConfidenceBuilder."""

import unittest  # noqa: I001
from datetime import datetime, timedelta

from backtest.engine import Bar, MarketState
from backtest.strategies.tts_strategy import (
    TTSStrategy,
    ConfidenceBuilder,
    _CONFLUENCE_DENSITY_BUCKETS,
)


def _make_bars(n: int, base_price: float = 1.1000, trend: float = 0.0) -> list[Bar]:
    """Generate synthetic M15 bars."""
    bars = []
    price = base_price
    for i in range(n):
        change = trend * 0.0001 + 0.0002 * (1 if i % 3 == 0 else -1 if i % 3 == 1 else 0)
        high = price + abs(change) + 0.0001
        low = price - abs(change) - 0.0001
        close = price + change
        bars.append(
            Bar(
                time=datetime(2024, 6, 1, 7, 0) + timedelta(minutes=15 * i),
                open=price,
                high=high,
                low=low,
                close=close,
                volume=1000,
            )
        )
        price = close
    return bars


class TestTTSStrategyHTF(unittest.TestCase):
    """Test HTF state computation."""

    def test_htf_state_returned(self):
        """HTF state should be computed without errors."""
        strategy = TTSStrategy("EURUSD", min_confidence=0.15, min_quality_score=0.15)
        bars = _make_bars(100, trend=1.0)  # uptrend
        htf = strategy._compute_htf_state(bars)
        self.assertIsNotNone(htf)
        # With trend, slope should be non-zero
        self.assertGreater(htf.ema_slope, 0)

    def test_htf_trending_up(self):
        """Uptrend should produce positive ema_slope."""
        strategy = TTSStrategy("EURUSD", min_confidence=0.15, min_quality_score=0.15)
        bars = _make_bars(700, base_price=1.1000, trend=2.0)  # strong uptrend
        htf = strategy._compute_htf_state(bars)
        self.assertGreater(htf.ema_slope, 0)

    def test_htf_trending_down(self):
        """Downtrend should produce negative ema_slope."""
        strategy = TTSStrategy("EURUSD", min_confidence=0.15, min_quality_score=0.15)
        bars = _make_bars(700, base_price=1.2000, trend=-2.0)  # strong downtrend
        htf = strategy._compute_htf_state(bars)
        self.assertLess(htf.ema_slope, 0)

    def test_htf_short_bars(self):
        """Should return NEUTRAL for insufficient data."""
        from signal_engine.data_types import HTFPhase

        strategy = TTSStrategy("EURUSD", min_confidence=0.15, min_quality_score=0.15)
        bars = _make_bars(10)
        htf = strategy._compute_htf_state(bars)
        self.assertEqual(htf.phase, HTFPhase.NEUTRAL)


class TestTTSStrategySession(unittest.TestCase):
    """Test session filtering."""

    def test_outside_session_no_crash(self):
        """Should not crash when outside trading sessions."""
        strategy = TTSStrategy("EURUSD", min_confidence=0.15, min_quality_score=0.15)
        # 3am UTC = outside all sessions
        bars = _make_bars(60)
        bars[-1] = Bar(
            time=datetime(2024, 6, 1, 3, 0),
            open=1.1,
            high=1.1005,
            low=1.0995,
            close=1.1001,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        # Just verify no crash — result may be None (outside session)
        # or may be None (no pattern detected)
        self.assertIsNone(result)


class TestTTSStrategyInit(unittest.TestCase):
    """Test initialization and parameter defaults."""

    def test_default_params(self):
        strategy = TTSStrategy("EURUSD")
        self.assertEqual(strategy.min_confidence, 0.20)
        self.assertEqual(strategy.min_quality_score, 0.25)
        self.assertEqual(strategy.HISTORY_BARS, 50)

    def test_custom_params(self):
        strategy = TTSStrategy("EURUSD", min_confidence=0.40, min_quality_score=0.50)
        self.assertEqual(strategy.min_confidence, 0.40)
        self.assertEqual(strategy.min_quality_score, 0.50)

    def test_reset(self):
        strategy = TTSStrategy("EURUSD")
        strategy._last_bar_idx = 42
        strategy.reset()
        self.assertEqual(strategy._last_bar_idx, -1)


class TestTTSStrategyEMA(unittest.TestCase):
    """Test EMA computation."""

    def test_ema_short_data(self):
        """EMA with insufficient data should return NaN-filled array."""
        import numpy as np

        data = np.array([1.0, 2.0, 3.0])
        result = TTSStrategy._ema(data, 10)
        self.assertTrue(np.all(np.isnan(result)))

    def test_ema_computation(self):
        """EMA should produce valid values for sufficient data."""
        import numpy as np

        data = np.array([float(i) for i in range(100)])
        result = TTSStrategy._ema(data, 10)
        # First 10 values should be NaN
        self.assertTrue(np.isnan(result[:10]).all())
        # Remaining values should be valid
        self.assertFalse(np.isnan(result[10:]).any())


class TestConfidenceBuilderDensityScaling(unittest.TestCase):
    """Test multiplicative confluence density scaling in ConfidenceBuilder."""

    def test_zero_boosts_no_multiplier(self):
        builder = ConfidenceBuilder(0.30)
        result = builder.finalize()
        self.assertAlmostEqual(result, 0.30)

    def test_single_positive_boost_low_density(self):
        builder = ConfidenceBuilder(0.30)
        builder.add_boost("htf_trend_aligned", 0.10)
        result = builder.finalize()
        density = 1 / 15.0
        self.assertAlmostEqual(density, 0.0667, places=3)
        self.assertGreaterEqual(result, 0.40)
        self.assertLessEqual(result, 0.42)

    def test_two_positive_boosts_low_density(self):
        builder = ConfidenceBuilder(0.30)
        builder.add_boost("htf_trend_aligned", 0.10)
        builder.add_boost("rsi_divergence", 0.10)
        result = builder.finalize()
        density = 2 / 15.0
        self.assertAlmostEqual(density, 0.133, places=3)
        self.assertGreater(result, 0.40)
        self.assertLessEqual(result, 0.55)

    def test_four_positive_boosts_medium_density(self):
        builder = ConfidenceBuilder(0.30)
        builder.add_boost("htf_trend_aligned", 0.10)
        builder.add_boost("rsi_divergence", 0.10)
        builder.add_boost("vwap_rejection", 0.10)
        builder.add_boost("mfi", 0.08)
        result = builder.finalize()
        self.assertGreater(result, 0.50)

    def test_six_positive_boosts_high_density(self):
        builder = ConfidenceBuilder(0.30)
        builder.add_boost("htf_trend_aligned", 0.10)
        builder.add_boost("rsi_divergence", 0.10)
        builder.add_boost("vwap_rejection", 0.10)
        builder.add_boost("mfi", 0.08)
        builder.add_boost("ema_cross", 0.08)
        builder.add_boost("bollinger", 0.07)
        result = builder.finalize()
        self.assertGreater(result, 0.60)

    def test_negative_boosts_not_counted_as_positive(self):
        builder = ConfidenceBuilder(0.30)
        builder.add_boost("htf_trend_aligned", 0.10)
        builder.add_boost("kill_zone_active", -0.05)
        builder.add_boost("htf_opposing", -0.15)
        positive_count = sum(1 for _, v in builder.boosts_applied if v > 0)
        self.assertEqual(positive_count, 1)

    def test_capped_at_one(self):
        builder = ConfidenceBuilder(0.50)
        for i in range(10):
            builder.add_boost(f"boost_{i}", 0.10)
        result = builder.finalize()
        self.assertAlmostEqual(result, 1.0)

    def test_density_multipliers_monotonic(self):
        multipliers = [m for _, m in _CONFLUENCE_DENSITY_BUCKETS]
        for i in range(len(multipliers) - 1):
            self.assertGreaterEqual(multipliers[i], multipliers[i + 1])

    def test_high_confluence_exceeds_low_confluence(self):
        high = ConfidenceBuilder(0.30)
        for i in range(5):
            high.add_boost(f"boost_{i}", 0.08)
        low = ConfidenceBuilder(0.30)
        low.add_boost("single", 0.08)
        self.assertGreater(high.finalize(), low.finalize())

    def test_quality_and_scorer_always_count_as_positive(self):
        builder = ConfidenceBuilder(0.30)
        builder.add_boost("quality_gate", 0.10)
        builder.add_boost("confluence_scorer", 0.08)
        positive_count = sum(1 for _, v in builder.boosts_applied if v > 0)
        self.assertEqual(positive_count, 2)


if __name__ == "__main__":
    unittest.main()
